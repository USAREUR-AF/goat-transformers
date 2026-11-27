// json wire codec (engine-spec.md, "Version 0.5: the `json` wire").
//
// The message is one JSON object. A locator is a path of member names separated
// by '.'; each name but the last addresses a nested object. Residue is every
// unmapped scalar member at any depth of nested objects, keyed by its path, with
// its canonical JSON text. Arrays and nulls are not carried.
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

#include "codecs.hpp"
#include "transforms.hpp"
#include "util.hpp"
#include "wires.hpp"

namespace goat_transformers::detail {

namespace {

// The member at `path`; null when it is absent, when its value is `null`, or
// when a name before the last does not hold an object.
const json::Value* json_lookup(const json::Value& doc, const std::vector<std::string>& path) {
    const json::Value* v = &doc;
    for (const auto& seg : path) {
        if (!v->is(json::Value::Kind::Object)) return nullptr;
        v = v->find(seg);
        if (!v) return nullptr;
    }
    return v->is(json::Value::Kind::Null) ? nullptr : v;
}

const char* json_kind_name(const json::Value& v) {
    switch (v.kind) {
        case json::Value::Kind::Null: return "null";
        case json::Value::Kind::Bool: return "a boolean";
        case json::Value::Kind::Number: return "a number";
        case json::Value::Kind::String: return "a string";
        case json::Value::Kind::Array: return "an array";
        case json::Value::Kind::Object: return "an object";
    }
    return "?";
}

// A value of the wrong JSON type for its transform is a transform decode failure.
void decode_member(Decoder& d, const FieldLine& f, const json::Value& v) {
    // A sentinel is compared before the transform reads the member's type (0.9).
    std::string raw;
    if (f.has_absent && json_raw_text(v, raw) && sentinel_text(f, raw)) return;
    json::Value::Kind want = json::Value::Kind::String;
    switch (f.transform) {
        case Transform::Float:
        case Transform::Scale:
        case Transform::Iscale:
        case Transform::Int: want = json::Value::Kind::Number; break;
        case Transform::Bool: want = json::Value::Kind::Bool; break;
        default: break;  // string, iso8601_ms, iso8601_short, iso8601_s
    }
    if (v.kind != want) {
        d.fail(f, std::string("the member is ") + json_kind_name(v) + ", which transform '" +
                      transform_name(f.transform) + "' does not read");
        return;
    }
    if (f.transform == Transform::Bool) d.put(f, Value::of_int(v.b ? 1 : 0));
    else if (v.kind == json::Value::Kind::Number) d.set_json_number(f, v.text);
    else d.set(f, v.text);
}

// The same member name twice in one object, at any depth (0.5 ruling 22).
bool has_duplicate_member(const json::Value& v) {
    if (v.is(json::Value::Kind::Object) && v.keys.size() > 1) {
        std::unordered_set<std::string> names;
        for (const auto& k : v.keys)
            if (!names.insert(k).second) return true;
    }
    for (const auto& item : v.items)
        if (has_duplicate_member(item)) return true;
    return false;
}

void collect_residue(Entity& d, const std::string& format, const json::Value& obj, const std::string& base,
                     const std::unordered_set<std::string>& mapped, std::unordered_set<std::string>& seen) {
    for (std::size_t k = 0; k < obj.keys.size(); ++k) {
        const std::string& name = obj.keys[k];
        if (name.empty() || name.find('.') != std::string::npos) continue;  // not addressable: dropped
        const json::Value& v = obj.items[k];
        const std::string path = base.empty() ? name : base + "." + name;
        switch (v.kind) {
            case json::Value::Kind::Object:
                if (seen.insert(path).second) collect_residue(d, format, v, path, mapped, seen);
                break;
            case json::Value::Kind::Number: {
                // A residue number whose nearest double is infinite has no
                // canonical text (0.11 ruling 2d).
                double x = 0;
                if (!mapped.count(path) && !parse_number_text(v.text, x))
                    throw Error(ErrorKind::MalformedWire, format, path,
                                "the residue number " + v.text + " has no finite nearest double");
            }
                [[fallthrough]];
            case json::Value::Kind::String:
            case json::Value::Kind::Bool:
                if (!mapped.count(path) && seen.insert(path).second)
                    d.residue.push_back({format, path, json::write(v)});
                break;
            default: break;  // arrays and nulls are not carried
        }
    }
}

// ---- canonical output tree

struct OutNode {
    std::string name;
    bool is_object = false;
    bool has_value = false;
    bool sentinel = false;       // the text is a field's sentinel: a line whose key is present writes over it
    std::string text;            // JSON text of a scalar member
    std::vector<OutNode> kids;   // members of an object, output order
};

// The slot at `path`, created at the end of each object on first use, so an
// object and a member sit where the first line that addresses them puts them.
// Null when the path runs through a member that already holds a scalar.
OutNode* out_slot(OutNode& root, const std::vector<std::string>& path) {
    OutNode* n = &root;
    for (std::size_t k = 0; k < path.size(); ++k) {
        if (n->has_value) return nullptr;
        n->is_object = true;
        OutNode* next = nullptr;
        for (auto& c : n->kids)
            if (c.name == path[k]) {
                next = &c;
                break;
            }
        if (!next) {
            n->kids.emplace_back();
            n->kids.back().name = path[k];
            next = &n->kids.back();
        }
        n = next;
    }
    return n;
}

bool out_empty(const OutNode& n) {
    if (n.has_value) return false;
    for (const auto& c : n.kids)
        if (!out_empty(c)) return false;
    return true;
}

void out_write(std::string& out, const OutNode& n) {
    if (n.has_value) {
        out += n.text;
        return;
    }
    out += '{';
    bool first = true;
    for (const auto& c : n.kids) {
        if (out_empty(c)) continue;  // an absent member, or an object with no members
        if (!first) out += ',';
        first = false;
        out += json::quote(c.name);
        out += ':';
        out_write(out, c);
    }
    out += '}';
}

// JSON text of a field's value (already through the default, type mapping and table).
std::string member_text(const Pack& p, const FieldLine& f, const Value& v) {
    if (f.transform == Transform::Bool) {
        std::int64_t n = 0;
        try {
            n = model_int(v);
        } catch (const std::invalid_argument& ex) {
            throw Error(ErrorKind::TransformEncode, p.format, f.locator, f.key + ": " + ex.what());
        }
        if (n != 0 && n != 1)
            throw Error(ErrorKind::TransformEncode, p.format, f.locator,
                        f.key + ": bool writes 1 or 0, not " + std::to_string(n));
        return n ? "true" : "false";
    }
    const std::string text = field_text(p, f, v);
    return transform_is_textual(f.transform) ? json::quote(text) : text;
}

// One field line at its member: the value when the key is present, else its
// first sentinel (0.9). A line whose key is present writes over a sentinel an
// earlier line wrote (ruling 16).
void write_field(const Pack& p, const EncodeSource& src, const FieldLine& f, OutNode& slot) {
    if (slot.has_value && !slot.sentinel) return;
    if (src.suppressed(f)) return;  // the member keeps its place (0.18 ruling 1)
    Value v;
    if (src.value(f, v)) {
        slot.text = member_text(p, f, v);
        slot.has_value = true;
        slot.sentinel = false;
    } else if (f.has_absent && !slot.has_value) {
        slot.text = f.absent_json;
        slot.has_value = true;
        slot.sentinel = true;
    }
}

// The value of one member of an item, by the wire's value types: `json` reads
// each transform from its own JSON type; `geojson` keeps its 0.1 types, where a
// scalar is read from its text (0.7 ruling 7).
void decode_item_value(Decoder& d, const FieldLine& f, const json::Value& v, bool geo) {
    if (!geo) {
        decode_member(d, f, v);
        return;
    }
    std::string raw;
    if (f.has_absent && json_raw_text(v, raw) && sentinel_text(f, raw)) return;
    if (transform_is_text_scale(f.transform) && !v.is(json::Value::Kind::Null) &&
        !v.is(json::Value::Kind::Number)) {
        // scale and iscale read a number, on geojson as on json (0.15 ruling 23).
        d.fail(f, std::string("the member is ") + json_kind_name(v) + ", which transform '" +
                      transform_name(f.transform) + "' does not read");
        return;
    }
    // codestr and codenum read a string, on geojson as on json (0.46 ruling 11).
    if (transform_is_code(f.transform) && !v.is(json::Value::Kind::Null) && !v.is(json::Value::Kind::String)) {
        d.fail(f, std::string("the member is ") + json_kind_name(v) + ", which transform '" +
                      transform_name(f.transform) + "' does not read");
        return;
    }
    switch (v.kind) {
        case json::Value::Kind::Null: break;
        case json::Value::Kind::String: d.set(f, v.text); break;
        case json::Value::Kind::Number: d.set_json_number(f, v.text); break;
        case json::Value::Kind::Bool: d.set(f, v.b ? "true" : "false"); break;
        default: d.set(f, json::write(v)); break;
    }
}

// The JSON text of one item: an object of the members its lines write, or the
// scalar a `.` field writes. An item with no members written is `{}`.
std::string encode_item(const Pack& p, const GroupLine& g, const std::vector<LineRef>& lines, const Item& item,
                        bool geo) {
    const EncodeSource src(p, g, item);
    OutNode root;
    root.is_object = true;
    OutNode scalar;
    std::vector<std::string> path_tmp;
    const std::vector<std::string>* path = &path_tmp;
    for (const auto& line : lines) {
        if (line.field && line.field->locator == ".") {
            // An item without the value writes the sentinel, not `null` (0.9 ruling 5).
            write_field(p, src, *line.field, scalar);
            continue;
        }
        json_locator(p, line.locator(), path, path_tmp);  // validated at pack load
        OutNode* slot = out_slot(root, *path);
        if (!slot || slot->is_object) continue;  // the path is also used as an object
        if (line.group) {
            const std::vector<Item>* items = src.list(*line.group);
            if ((slot->has_value && !slot->sentinel) || !items) continue;
            slot->sentinel = false;
            slot->text = json_encode_items(p, *line.group, *items, geo);
            slot->has_value = true;
            continue;
        }
        if (const WhenLine* w = line.fixed()) {
            slot->has_value = true;
            slot->sentinel = false;
            slot->text = json_when_text(*w);
            continue;
        }
        write_field(p, src, *line.field, *slot);
    }
    if (scalar.has_value) return scalar.text;
    std::string out;
    out_write(out, root);
    // A scalar (`.`) item with no value is written `null` (0.7 ruling 11).
    if (g.scalar && out == "{}") return "null";
    return out;
}

}  // namespace

std::vector<Item> json_decode_items(const Pack& p, const GroupLine& g, const json::Value& arr, bool geo) {
    if (!arr.is(json::Value::Kind::Array))
        throw Error(ErrorKind::MalformedWire, p.format, g.locator,
                    std::string("the member of the group '") + g.list + "' is " + json_kind_name(arr) +
                        ", not an array");
    take_items(p, g.list, arr.items.size());  // 0.11 ruling 7a
    std::vector<Item> items;
    items.reserve(arr.items.size());
    std::vector<LineRef> lines_tmp;
    const std::vector<LineRef>& lines = body_lines(p, g, lines_tmp);
    static const std::vector<std::string> no_path;
    std::vector<std::vector<std::string>> paths_tmp(lines.size());
    std::vector<const std::vector<std::string>*> paths(lines.size(), &no_path);  // empty for a `.` field and for a const
    for (std::size_t k = 0; k < lines.size(); ++k)
        if (!lines[k].fixed() && lines[k].locator() != ".") json_locator(p, lines[k].locator(), paths[k], paths_tmp[k]);
    for (const json::Value& el : arr.items) {
        items.emplace_back();
        Item& item = items.back();
        Decoder d(p, item);
        for (std::size_t k = 0; k < lines.size(); ++k) {
            const LineRef& line = lines[k];
            if (line.group) {
                // A nested list: present when the member exists and is an array.
                if (const json::Value* v = json_lookup(el, *paths[k]))
                    item.lists[line.group->list] = json_decode_items(p, *line.group, *v, geo);
                continue;
            }
            if (!line.field || !d.wants(*line.field)) continue;
            const FieldLine& f = *line.field;
            if (f.locator == ".") {
                // The element itself, when it is a scalar (0.7 ruling 6).
                if (el.is(json::Value::Kind::Object) || el.is(json::Value::Kind::Array))
                    d.fail(f, std::string("the item is ") + json_kind_name(el) + ", not a scalar");
                else if (!el.is(json::Value::Kind::Null)) decode_item_value(d, f, el, geo);
                continue;
            }
            if (const json::Value* v = json_lookup(el, *paths[k])) decode_item_value(d, f, *v, geo);
        }
        d.finish();
    }
    return items;
}

std::string json_encode_items(const Pack& p, const GroupLine& g, const std::vector<Item>& items, bool geo) {
    std::vector<LineRef> lines_tmp;
    const std::vector<LineRef>& lines = body_lines(p, g, lines_tmp);
    std::string out = "[";
    for (std::size_t k = 0; k < items.size(); ++k) {
        if (k) out += ',';
        out += encode_item(p, g, lines, items[k], geo);
    }
    out += ']';
    return out;
}

// The json codec itself; geojson uses only the items above (0.24 ruling 1d).
#if GT_WIRE_JSON

namespace {

// The members the field lines of a scope read, through its groups' items
// (any field line, whether or not decode then wants its key).
void mark_field_reads(const Pack& p, const std::vector<LineRef>& lines, const json::Value& obj,
                      std::unordered_set<const json::Value*>& read) {
    std::vector<std::string> path_tmp;
    const std::vector<std::string>* path = &path_tmp;
    for (const auto& line : lines) {
        if (line.field) {
            if (line.field->locator == ".") {
                read.insert(&obj);
                continue;
            }
            json_locator(p, line.field->locator, path, path_tmp);
            if (const json::Value* v = json_lookup(obj, *path)) read.insert(v);
        } else if (line.group) {
            json_locator(p, line.group->locator, path, path_tmp);
            const json::Value* v = json_lookup(obj, *path);
            if (!v || !v->is(json::Value::Kind::Array)) continue;
            std::vector<LineRef> body_tmp;
            const std::vector<LineRef>& body = body_lines(p, *line.group, body_tmp);
            for (const auto& el : v->items) mark_field_reads(p, body, el, read);
        }
    }
}

// A number outside the double range that no field reads, anywhere in the
// document, is malformed-wire (0.15 ruling 27, extending ruling 39 of 0.8).
void check_unread_overflow(const Pack& p, const json::Value& v, const std::unordered_set<const json::Value*>& read) {
    if (v.is(json::Value::Kind::Number)) {
        double d = 0;
        if (!parse_number_text(v.text, d) && !read.count(&v))
            throw Error(ErrorKind::MalformedWire, p.format, "",
                        "the number " + v.text + " is outside the double range and no field reads it");
        return;
    }
    for (const auto& item : v.items) check_unread_overflow(p, item, read);
}

}  // namespace

Entity decode_json(const Pack& p, const std::string& bytes) {
    json::Value doc;
    try {
        doc = json::parse(bytes);
    } catch (const json::ParseError& ex) {
        throw Error(ErrorKind::MalformedWire, p.format, "", ex.what());
    }
    if (!doc.is(json::Value::Kind::Object)) throw Error(ErrorKind::MalformedWire, p.format, "", "not a JSON object");
    if (has_duplicate_member(doc))
        throw Error(ErrorKind::MalformedWire, p.format, "", "an object holds the same member name twice");

    const Kind* kind = select_decode_kind(p, [&](const WhenLine& w) {
        std::vector<std::string> path_tmp;
        const std::vector<std::string>* path = &path_tmp;
        json_locator(p, w.locator, path, path_tmp);  // validated at pack load
        const json::Value* v = json_lookup(doc, *path);
        if (!v) return false;
        return w.present || json_when_matches(w, *v);
    });

    std::vector<LineRef> lines_tmp;
    const std::vector<LineRef>& lines = scope_lines(p, kind, lines_tmp);
    {
        std::unordered_set<const json::Value*> read;
        mark_field_reads(p, lines, doc, read);
        check_unread_overflow(p, doc, read);
    }

    Entity e;
    Decoder d(p, e);
    const PackPlan* plan = plan_of(p);
    std::unordered_set<std::string> mapped_tmp;
    std::vector<std::string> path_tmp;
    const std::vector<std::string>* path = &path_tmp;
    for (const auto& line : lines) {
        // `when <locator> present` does not map the member (0.5 ruling 27).
        if (!plan && line.maps()) mapped_tmp.insert(line.locator());
        if (line.group) {
            // The list is present when the member exists and is an array; `null` is absent.
            json_locator(p, line.group->locator, path, path_tmp);
            if (const json::Value* v = json_lookup(doc, *path))
                e.lists[line.group->list] = json_decode_items(p, *line.group, *v, false);
            continue;
        }
        if (!line.field || !d.wants(*line.field)) continue;
        json_locator(p, line.field->locator, path, path_tmp);
        if (const json::Value* v = json_lookup(doc, *path)) decode_member(d, *line.field, *v);
    }
    std::unordered_set<std::string> seen;
    collect_residue(e, p.format, doc, "", plan ? plan->mapped[kind_slot(p, kind)] : mapped_tmp, seen);
    d.finish();
    if (kind) e.kind = {p.format, kind->name};
    return e;
}

std::string encode_json(const Pack& p, const Entity& e) {
    const Kind* kind = select_encode_kind(p, e);
    const EncodeSource src(p, kind, e);
    OutNode root;
    root.is_object = true;
    const PackPlan* plan = plan_of(p);
    std::unordered_set<std::string> mapped_tmp;
    std::vector<std::string> path;
    Value v;
    // Mapped members, `when` members and `const` members in line order, common
    // lines first. Every such line takes its place whether or not its member is
    // written. Where lines share a locator the earliest field with a value gives
    // it; a `when` or `const` value is written over any field. A `when ...
    // present` line maps nothing and takes no place. A group writes an array at
    // its member: `[]` for an empty list, nothing for an absent one.
    std::vector<LineRef> lines_tmp;
    for (const auto& line : scope_lines(p, kind, lines_tmp)) {
        if (!line.maps()) continue;
        const std::string& locator = line.locator();
        if (!plan) mapped_tmp.insert(locator);
        const std::vector<std::string>* lpath = &path;
        json_locator(p, locator, lpath, path);  // validated at pack load
        OutNode* slot = out_slot(root, *lpath);
        if (!slot || slot->is_object) continue;  // the path is also used as an object
        if (line.group) {
            const std::vector<Item>* items = src.list(*line.group);
            if ((slot->has_value && !slot->sentinel) || !items) continue;
            slot->sentinel = false;
            slot->text = json_encode_items(p, *line.group, *items, false);
            slot->has_value = true;
            continue;
        }
        if (const WhenLine* w = line.fixed()) {
            if (w->present) continue;
            slot->has_value = true;
            slot->sentinel = false;
            slot->text = json_when_text(*w);
            continue;
        }
        write_field(p, src, *line.field, *slot);
    }
    const std::unordered_set<std::string>& mapped = plan ? plan->mapped[kind_slot(p, kind)] : mapped_tmp;
    // Then the residue members of each object, in input order.
    for (const auto& r : e.residue) {
        if (r.format != p.format || mapped.count(r.locator)) continue;
        if (!parse_json_locator(r.locator, path)) continue;
        OutNode* slot = out_slot(root, path);
        if (!slot || slot->is_object || slot->has_value) continue;
        slot->has_value = true;
        slot->text = r.value;
    }
    std::string out;
    out_write(out, root);
    return out;
}

#endif  // GT_WIRE_JSON

}  // namespace goat_transformers::detail
