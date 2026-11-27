// protobuf wire codec (engine-spec.md, "Version 0.3: the protobuf wire").
//
// Fields are addressed by number; a dot-path (e.g. 4.1) descends into a nested
// length-delimited submessage. When a field number repeats on the wire the last
// occurrence wins. I/O is hex text. Encoded output is canonical: fields in
// ascending field-number order, each submessage serialised the same way, and
// only mapped fields written.
#include <cstdint>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "codecs.hpp"
#include "transforms.hpp"

namespace goat_transformers::detail {

namespace {

std::string locator_str(const std::vector<std::uint32_t>& path) {
    std::string s;
    for (std::size_t k = 0; k < path.size(); ++k) {
        if (k) s += '.';
        s += std::to_string(path[k]);
    }
    return s;
}

struct WireField {
    std::uint32_t num = 0;
    int wt = 0;                // 0 varint, 1 fixed64, 2 length-delimited, 5 fixed32
    std::uint64_t scalar = 0;  // wire types 0/1/5
    std::string bytes;         // wire type 2 payload
};

std::uint64_t read_varint(const Pack& p, const std::string& d, std::size_t& i) {
    std::uint64_t v = 0;
    int shift = 0;
    for (int k = 0; k < 10; ++k) {
        if (i >= d.size())
            throw Error(ErrorKind::MalformedWire, p.format, "", "varint runs past the end of the message");
        const std::uint8_t b = static_cast<std::uint8_t>(d[i++]);
        if (k == 9 && (b & 0x7F) > 1)
            throw Error(ErrorKind::MalformedWire, p.format, "", "varint wider than 64 bits");
        v |= static_cast<std::uint64_t>(b & 0x7F) << shift;
        if ((b & 0x80) == 0) return v;
        shift += 7;
    }
    throw Error(ErrorKind::MalformedWire, p.format, "", "varint is not terminated");
}

std::uint64_t read_fixed(const Pack& p, const std::string& d, std::size_t& i, int n) {
    if (static_cast<std::size_t>(n) > d.size() - i)  // i <= d.size() always
        throw Error(ErrorKind::MalformedWire, p.format, "", "fixed-width field runs past the end of the message");
    std::uint64_t v = 0;
    for (int k = 0; k < n; ++k)
        v |= static_cast<std::uint64_t>(static_cast<std::uint8_t>(d[i++])) << (8 * k);  // little-endian
    return v;
}

std::vector<WireField> parse_message(const Pack& p, const std::string& d) {
    std::vector<WireField> fields;
    std::size_t i = 0;
    while (i < d.size()) {
        const std::uint64_t tag = read_varint(p, d, i);
        WireField f;
        // A field number is 1 to 2^29-1 (0.8 ruling 38); checked on the whole
        // tag, before it is narrowed.
        const std::uint64_t num = tag >> 3;
        if (num == 0) throw Error(ErrorKind::MalformedWire, p.format, "", "field number 0 is not valid");
        if (num > 536870911ull)
            throw Error(ErrorKind::MalformedWire, p.format, "",
                        "field number " + std::to_string(num) + " is above 2^29-1");
        f.num = static_cast<std::uint32_t>(num);
        f.wt = static_cast<int>(tag & 7);
        switch (f.wt) {
            case 0: f.scalar = read_varint(p, d, i); break;
            case 1: f.scalar = read_fixed(p, d, i, 8); break;
            case 5: f.scalar = read_fixed(p, d, i, 4); break;
            case 2: {
                const std::uint64_t n = read_varint(p, d, i);
                // Compared against the bytes left, so a length near 2^64 cannot wrap.
                if (n > static_cast<std::uint64_t>(d.size() - i))
                    throw Error(ErrorKind::MalformedWire, p.format, "",
                                "length-delimited field runs past the end of the message");
                f.bytes.assign(d, i, static_cast<std::size_t>(n));
                i += static_cast<std::size_t>(n);
                break;
            }
            default:
                throw Error(ErrorKind::MalformedWire, p.format, "",
                            "unsupported wire type " + std::to_string(f.wt) +
                                " (the deprecated groups 3 and 4 are not supported)");
        }
        fields.push_back(std::move(f));
    }
    return fields;
}

// A parsed message: its fields in wire order, the occurrences of each field
// number, and the submessages a path has descended into, each parsed once.
struct Message {
    std::vector<WireField> fields;
    std::unordered_map<std::uint32_t, std::vector<std::size_t>> occ;  // field number -> indexes in `fields`, wire order
    std::unordered_map<std::size_t, std::unique_ptr<Message>> subs;   // index in `fields` -> its parse
};

Message parse_tree(const Pack& p, const std::string& d) {
    Message m;
    m.fields = parse_message(p, d);
    for (std::size_t k = 0; k < m.fields.size(); ++k) m.occ[m.fields[k].num].push_back(k);
    return m;
}

// The submessage `path` leads to from `msg`, last-occurrence-wins at each level;
// `msg` itself for an empty path. Null when a field on the path is absent, or
// (with `lenient`) is not length-delimited; otherwise that is malformed-wire.
Message* find_message(const Pack& p, Message& msg, const std::vector<std::uint32_t>& path, std::size_t depth,
                      bool lenient = false) {
    Message* m = &msg;
    for (std::size_t seg = 0; seg < depth; ++seg) {
        auto it = m->occ.find(path[seg]);
        if (it == m->occ.end()) return nullptr;
        const std::size_t index = it->second.back();
        const WireField& f = m->fields[index];
        if (f.wt != 2) {
            if (lenient) return nullptr;
            throw Error(ErrorKind::MalformedWire, p.format, locator_str(path),
                        "field " + std::to_string(path[seg]) + " is not a submessage");
        }
        auto& sub = m->subs[index];
        if (!sub) {
            if (lenient) {
                // 0.11 ruling 9b: a `when` path never fails a decode. Bytes that
                // do not parse as a message make it not hold; the failure is not
                // kept, so a `field` or `group` path that walks into them fails (9c).
                try {
                    sub = std::make_unique<Message>(parse_tree(p, f.bytes));
                } catch (const Error&) {
                    m->subs.erase(index);
                    return nullptr;
                }
            } else {
                sub = std::make_unique<Message>(parse_tree(p, f.bytes));
            }
        }
        m = sub.get();
    }
    return m;
}

// The field `path` names, last-occurrence-wins at each level (a repeated
// submessage is not merged). Returns null when the field is absent; when the path
// descends through a field that is not length-delimited it throws, or returns
// null with `lenient` (a `when` asks only whether the field occurs).
const WireField* find_leaf(const Pack& p, Message& msg, const std::vector<std::uint32_t>& path,
                           bool lenient = false) {
    Message* m = find_message(p, msg, path, path.size() - 1, lenient);
    if (!m) return nullptr;
    auto it = m->occ.find(path.back());
    return it == m->occ.end() ? nullptr : &m->fields[it->second.back()];
}

bool numeric_transform(Transform t) {
    return t == Transform::Pvarint || t == Transform::Psint || t == Transform::Pdouble || t == Transform::Pfloat;
}

// The first `.` field of a group body: the transform that reads an item as a scalar.
const FieldLine* scalar_field(const GroupLine& g) {
    for (const auto& f : g.fields)
        if (f.locator == ".") return &f;
    return nullptr;
}

void decode_leaf(Decoder& d, const FieldLine& f, const WireField& wf) {
    if (wf.wt != protobuf_wire_type(f.transform)) {
        d.fail(f, "wire type " + std::to_string(wf.wt) + " does not match transform '" + transform_name(f.transform) +
                      "'");
        return;
    }
    // After the wire type, before the transform (0.9 rulings 2 and 15).
    if (f.has_absent && (f.transform == Transform::Pstring ? sentinel_text(f, wf.bytes) : sentinel_num(f, wf.scalar)))
        return;
    try {
        d.put(f, decode_protobuf_value(f.transform, wf.scalar, wf.bytes));
    } catch (const std::invalid_argument& ex) {
        d.fail(f, ex.what());
    }
}

void decode_scope(const Pack& p, const std::vector<LineRef>& lines, Message& msg, Item& out);

// The items of a group whose items are scalars: one per occurrence, and one per
// value of a packed occurrence of a numeric transform (0.7).
void decode_scalar_items(const Pack& p, const GroupLine& g, const Message& m, const std::vector<std::size_t>& occ,
                         std::vector<Item>& items) {
    const FieldLine& first = *scalar_field(g);
    const bool packable = numeric_transform(first.transform);
    const int wt = protobuf_wire_type(first.transform);
    auto one = [&](const WireField& wf) {
        take_items(p, g.list, 1);  // 0.11 ruling 7a
        items.emplace_back();
        Decoder d(p, items.back());
        for (const auto& f : g.fields)
            if (f.locator == "." && d.wants(f)) decode_leaf(d, f, wf);
        d.finish();
    };
    for (std::size_t index : occ) {
        const WireField& wf = m.fields[index];
        if (!packable || wf.wt != 2) {
            one(wf);
            continue;
        }
        // The packed form: the values back to back. A payload whose length does
        // not fit its values is malformed-wire (0.7 ruling 8).
        WireField value;
        value.num = wf.num;
        value.wt = wt;
        std::size_t i = 0;
        if (wt != 0 && wf.bytes.size() % (wt == 1 ? 8 : 4) != 0)
            throw Error(ErrorKind::MalformedWire, p.format, g.locator,
                        "a packed occurrence of " + std::to_string(wf.bytes.size()) + " bytes does not hold whole " +
                            (wt == 1 ? "64-bit" : "32-bit") + " values");
        while (i < wf.bytes.size()) {
            value.scalar = wt == 0 ? read_varint(p, wf.bytes, i) : read_fixed(p, wf.bytes, i, wt == 1 ? 8 : 4);
            one(value);
        }
    }
}

// One scope's lines read from `msg`: the message, or an item's submessage.
void decode_scope(const Pack& p, const std::vector<LineRef>& lines, Message& msg, Item& out) {
    Decoder d(p, out);
    ProtobufLocator tmp;
    const ProtobufLocator* locp = &tmp;
    for (const auto& line : lines) {
        if (line.group) {
            // Each occurrence of the last field number, in wire order. The list is
            // present when at least one item occurs.
            const GroupLine& g = *line.group;
            protobuf_locator(p, g.locator, locp, tmp);  // validated at pack load
            const ProtobufLocator& loc = *locp;
            Message* m = find_message(p, msg, loc.path, loc.path.size() - 1);
            if (!m) continue;
            auto it = m->occ.find(loc.path.back());
            if (it == m->occ.end()) continue;
            std::vector<Item> items;
            if (g.scalar) {
                decode_scalar_items(p, g, *m, it->second, items);
            } else {
                std::vector<LineRef> body_tmp;
                const std::vector<LineRef>& body = body_lines(p, g, body_tmp);
                take_items(p, g.list, it->second.size());  // 0.11 ruling 7a
                items.reserve(it->second.size());
                for (std::size_t index : it->second) {
                    const WireField& wf = m->fields[index];
                    if (wf.wt != 2)
                        throw Error(ErrorKind::MalformedWire, p.format, g.locator,
                                    "an item of the group '" + g.list + "' is not a submessage");
                    Message sub = parse_tree(p, wf.bytes);
                    items.emplace_back();
                    decode_scope(p, body, sub, items.back());
                }
            }
            if (!items.empty()) out.lists[g.list] = std::move(items);
            continue;
        }
        if (!line.field) continue;
        const FieldLine& f = *line.field;
        if (!d.wants(f) || f.locator == ".") continue;
        protobuf_locator(p, f.locator, locp, tmp);  // validated at pack load
        if (const WireField* wf = find_leaf(p, msg, locp->path)) decode_leaf(d, f, *wf);
    }
    d.finish();
}

// ---- canonical encoding tree

struct Node {
    bool is_leaf = false;
    bool is_const = false;                     // leaf holding a `when` varint
    std::uint64_t const_value = 0;
    Transform transform = Transform::Pstring;  // leaf only
    Value value;                               // leaf only
    const FieldLine* field = nullptr;          // leaf only: the line it was written from
    bool is_sentinel = false;                  // leaf only: the field's first sentinel, written raw (0.9)
    bool is_raw = false;                       // a group: every occurrence, already serialised with its tag
    std::string raw;
    std::map<std::uint32_t, Node> children;    // submessage: ascending field number
    bool present = false;                      // a submessage a `when <path> present` names (0.5 ruling 14)
};

// `sentinel`: the line's key is absent and the leaf is its first sentinel (0.9).
void insert_field(const Pack& p, Node& node, const std::vector<std::uint32_t>& path, std::size_t seg,
                  const FieldLine& f, const Value& v, bool sentinel) {
    Node& child = node.children[path[seg]];
    if (seg + 1 == path.size()) {
        if (child.is_raw) return;  // a group writes this field number
        if (!child.children.empty())
            throw Error(ErrorKind::TransformEncode, p.format, locator_str(path),
                        "field is used both as a leaf and as a submessage");
        // Lines on one locator: the earliest present key is written, and a
        // present key wins over a sentinel whatever their order (0.9 ruling 16).
        if (child.is_leaf && (sentinel || !child.is_sentinel)) return;
        child.is_leaf = true;
        child.is_sentinel = sentinel;
        child.transform = f.transform;
        child.value = v;
        child.field = &f;
    } else {
        if (child.is_raw) return;
        if (child.is_leaf)
            throw Error(ErrorKind::TransformEncode, p.format, locator_str(path),
                        "field is used both as a leaf and as a submessage");
        insert_field(p, child, path, seg + 1, f, v, sentinel);
    }
}

// The raw wire value of a field's first sentinel: the integer for a varint or
// a fixed-width transform (no zig-zag), the text for `pstring`.
void sentinel_value(const FieldLine& f, std::uint64_t& scalar, std::string& bytes) {
    if (f.transform == Transform::Pstring) bytes = f.absent_text.front();
    else scalar = f.absent_num.front();
}

void write_varint(std::string& out, std::uint64_t v) {
    do {
        std::uint8_t b = static_cast<std::uint8_t>(v & 0x7F);
        v >>= 7;
        if (v) b |= 0x80;
        out += static_cast<char>(b);
    } while (v);
}

void write_tag(std::string& out, std::uint32_t num, int wt) {
    write_varint(out, (static_cast<std::uint64_t>(num) << 3) | static_cast<std::uint64_t>(wt));
}

void write_fixed(std::string& out, std::uint64_t v, int n) {
    for (int k = 0; k < n; ++k) out += static_cast<char>((v >> (8 * k)) & 0xFF);  // little-endian
}

void write_delimited(std::string& out, std::uint32_t num, const std::string& payload) {
    write_tag(out, num, 2);
    write_varint(out, payload.size());
    out += payload;
}

std::string serialize(const Pack& p, const Node& node) {
    std::string out;
    for (const auto& kv : node.children) {
        const std::uint32_t num = kv.first;
        const Node& c = kv.second;
        if (c.is_raw) {
            out += c.raw;
            continue;
        }
        if (!c.is_leaf) {
            const std::string sub = serialize(p, c);
            // A submessage whose every field `implicit` left out is not written,
            // unless a `when <path> present` names it (0.56).
            if (sub.empty() && !c.children.empty() && !c.present) continue;
            write_tag(out, num, 2);
            write_varint(out, sub.size());
            out += sub;
            continue;
        }
        if (c.is_const) {
            write_tag(out, num, 0);
            write_varint(out, c.const_value);
            continue;
        }
        const int wt = protobuf_wire_type(c.transform);
        std::uint64_t scalar = 0;
        std::string payload;
        if (c.is_sentinel) sentinel_value(*c.field, scalar, payload);
        else try {
            encode_protobuf_value(c.transform, c.value, scalar, payload);
        } catch (const std::invalid_argument& ex) {
            throw Error(ErrorKind::TransformEncode, p.format, c.field ? c.field->locator : std::to_string(num),
                        (c.field ? c.field->key + ": " : std::string()) + ex.what());
        }
        // v0.56 `implicit`: a value equal to the proto3 default of its wire type,
        // after `via` and `pfloat` narrowing, is not written; the line still holds
        // the place (ruling 16 of 0.5). The default's encoding is all zero bits
        // (0, zig-zag 0, +0.0) or the empty text; a sentinel is compared the same way.
        if (c.field && c.field->implicit && (wt == 2 ? payload.empty() : scalar == 0)) {
            // It counts as not written for a `when <path> present` on its own
            // path, which then writes an empty field (0.5 ruling 14).
            if (c.present) write_delimited(out, num, std::string());
            continue;
        }
        write_tag(out, num, wt);
        switch (wt) {
            case 0: write_varint(out, scalar); break;
            case 1: write_fixed(out, scalar, 8); break;
            case 5: write_fixed(out, scalar, 4); break;
            case 2:
                write_varint(out, payload.size());
                out += payload;
                break;
            default: break;
        }
    }
    return out;
}

void build_scope(const Pack& p, const std::vector<LineRef>& lines, const EncodeSource& src, Node& root);

// Every occurrence of a group's field number, serialised: one per item, or the
// packed form for a `.` field with a numeric transform.
std::string group_bytes(const Pack& p, const GroupLine& g, std::uint32_t num, const std::vector<Item>& items) {
    std::string out;
    if (!g.scalar) {
        std::vector<LineRef> body_tmp;
        const std::vector<LineRef>& body = body_lines(p, g, body_tmp);
        for (const Item& item : items) {
            // An item with nothing written is an empty length-delimited occurrence.
            Node sub;
            build_scope(p, body, EncodeSource(p, g, item), sub);
            write_delimited(out, num, serialize(p, sub));
        }
        return out;
    }
    const FieldLine& f = *scalar_field(g);
    const int wt = protobuf_wire_type(f.transform);
    const bool packed = numeric_transform(f.transform);
    std::string payload;
    Value v;
    for (const Item& item : items) {
        std::uint64_t scalar = 0;
        std::string bytes;
        const EncodeSource src(p, g, item);
        for (const auto& other : g.fields)
            if (&other != &f) src.check_range(other);  // 0.56 ruling 9: the first '.' line alone writes
        const bool sup = src.suppressed(f);  // an item without the value (0.18 ruling 4)
        if (!sup && src.value(f, v)) {
            try {
                encode_protobuf_value(f.transform, v, scalar, bytes);
            } catch (const std::invalid_argument& ex) {
                throw Error(ErrorKind::TransformEncode, p.format, g.locator, f.key + ": " + ex.what());
            }
        } else if (!sup && f.writes_sentinel()) {
            sentinel_value(f, scalar, bytes);  // in place of 0.7 ruling 11 (0.9 ruling 5)
        } else if (packed) {
            continue;  // an item with no value adds nothing to the packed form
        }
        if (!packed) {
            write_delimited(out, num, bytes);  // pstring: one occurrence per item
            continue;
        }
        switch (wt) {
            case 0: write_varint(payload, scalar); break;
            case 1: write_fixed(payload, scalar, 8); break;
            default: write_fixed(payload, scalar, 4); break;
        }
    }
    // A list whose items all lack the value writes nothing (0.7 ruling 11).
    if (packed && !payload.empty()) write_delimited(out, num, payload);
    return out;
}

// One scope's lines written into the encoding tree of the message, or of one item.
void build_scope(const Pack& p, const std::vector<LineRef>& lines, const EncodeSource& src, Node& root) {
    ProtobufLocator tmp;
    const ProtobufLocator* locp = &tmp;
    Value v;
    // Groups first, in line order: an absent or empty list writes nothing.
    for (const auto& line : lines) {
        if (!line.group) continue;
        const GroupLine& g = *line.group;
        const std::vector<Item>* items = src.list(g);
        if (!items || items->empty()) continue;
        protobuf_locator(p, g.locator, locp, tmp);  // validated at pack load
        const ProtobufLocator& loc = *locp;
        // A packed list with no value to write does not create its container either.
        std::string raw = group_bytes(p, g, loc.path.back(), *items);
        if (raw.empty()) continue;
        Node* n = &root;
        bool blocked = false;
        for (std::size_t k = 0; k < loc.path.size() && !blocked; ++k) {
            if (n->is_leaf || n->is_raw) blocked = true;
            else n = &n->children[loc.path[k]];
        }
        if (blocked || n->is_leaf || n->is_raw || !n->children.empty()) continue;
        n->is_raw = true;
        n->raw = std::move(raw);
    }
    for (const auto& line : lines) {
        if (!line.field) continue;
        const FieldLine& f = *line.field;
        if (f.locator == ".") continue;
        if (src.suppressed(f)) continue;  // 0.18 ruling 1
        // Only mapped fields that have a value are written, and the sentinel of an absent key (0.9).
        const bool present = src.value(f, v);
        if (!present && !f.writes_sentinel()) continue;
        protobuf_locator(p, f.locator, locp, tmp);  // validated at pack load
        insert_field(p, root, locp->path, 0, f, present ? v : Value(), !present);
    }
    // `when` and `const` values, so the output decodes as the same kind: an integer
    // is written as a varint over any field; `present` writes an empty
    // length-delimited field when nothing under its path was written (0.5 ruling 14).
    for (const auto& line : lines) {
        const WhenLine* w = line.fixed();
        if (!w) continue;
        protobuf_locator(p, w->locator, locp, tmp);
        const ProtobufLocator& loc = *locp;
        Node* n = &root;
        bool blocked = false;
        for (std::size_t k = 0; k < loc.path.size(); ++k) {
            if (n->is_leaf || n->is_raw) {  // a written leaf or group lies on the path: nothing can go under it
                blocked = true;
                break;
            }
            n = &n->children[loc.path[k]];
        }
        if (!blocked && w->present) n->present = true;
        if (blocked || w->present || n->is_raw) continue;
        // v0.20 ruling 3: a field line with a present key on the same path whose
        // varint matches the `when` keeps its value.
        if (line.when && n->is_leaf && !n->is_const && !n->is_sentinel && n->field &&
            src.e.fields.count(n->field->key) && protobuf_wire_type(n->transform) == 0) {
            std::uint64_t scalar = 0;
            std::string bytes;
            bool ok = true;
            try {
                encode_protobuf_value(n->transform, n->value, scalar, bytes);
            } catch (const std::invalid_argument&) {
                ok = false;
            }
            if (ok && w->holds_number(scalar)) {
                // The kind's `when` keeps the matching value, which `implicit`
                // would leave out: it is written, so the output decodes as the kind.
                if (n->field->implicit && scalar == 0) {
                    n->is_const = true;
                    n->const_value = 0;
                }
                continue;
            }
        }
        n->children.clear();
        n->is_leaf = true;
        n->is_const = true;
        n->const_value = w->number;
    }
}

}  // namespace

Entity decode_protobuf(const Pack& p, const std::string& bytes) {
    Message msg = parse_tree(p, hex_to_bytes(p, bytes));

    const Kind* kind = select_decode_kind(p, [&](const WhenLine& w) {
        ProtobufLocator tmp;
        const ProtobufLocator* loc = nullptr;
        protobuf_locator(p, w.locator, loc, tmp);  // validated at pack load
        const WireField* wf = find_leaf(p, msg, loc->path, true);
        if (!wf) return false;
        return w.present || (wf->wt == 0 && w.holds_number(wf->scalar));
    });

    Entity e;
    std::vector<LineRef> lines_tmp;
    decode_scope(p, scope_lines(p, kind, lines_tmp), msg, e);
    if (kind) e.kind = {p.format, kind->name};
    return e;
}

std::string encode_protobuf(const Pack& p, const Entity& e) {
    const Kind* kind = select_encode_kind(p, e);
    Node root;
    std::vector<LineRef> lines_tmp;
    build_scope(p, scope_lines(p, kind, lines_tmp), EncodeSource(p, kind, e), root);
    return bytes_to_hex(serialize(p, root));
}

}  // namespace goat_transformers::detail
