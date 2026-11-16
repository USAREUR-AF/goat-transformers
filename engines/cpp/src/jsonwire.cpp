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
    json::Value::Kind want = json::Value::Kind::String;
    switch (f.transform) {
        case Transform::Float:
        case Transform::Int: want = json::Value::Kind::Number; break;
        case Transform::Bool: want = json::Value::Kind::Bool; break;
        default: break;  // string, iso8601_ms
    }
    if (v.kind != want) {
        d.fail(f, std::string("the member is ") + json_kind_name(v) + ", which transform '" +
                      transform_name(f.transform) + "' does not read");
        return;
    }
    if (f.transform == Transform::Bool) d.put(f, Value::of_int(v.b ? 1 : 0));
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
            case json::Value::Kind::String:
            case json::Value::Kind::Number:
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

// The value of one member of an item, by the wire's value types: `json` reads
// each transform from its own JSON type; `geojson` keeps its 0.1 types, where a
// scalar is read from its text (0.7 ruling 7).
void decode_item_value(Decoder& d, const FieldLine& f, const json::Value& v, bool geo) {
    if (!geo) {
        decode_member(d, f, v);
        return;
    }
    switch (v.kind) {
        case json::Value::Kind::Null: break;
        case json::Value::Kind::String:
        case json::Value::Kind::Number: d.set(f, v.text); break;
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
    std::string scalar;
    bool has_scalar = false;
    std::vector<std::string> path;
    Value v;
    for (const auto& line : lines) {
        if (line.field && line.field->locator == ".") {
            if (!has_scalar && src.value(*line.field, v)) {
                scalar = member_text(p, *line.field, v);
                has_scalar = true;
            }
            continue;
        }
        parse_json_locator(line.locator(), path);  // validated at pack load
        OutNode* slot = out_slot(root, path);
        if (!slot || slot->is_object) continue;  // the path is also used as an object
        if (line.group) {
            const std::vector<Item>* items = src.list(*line.group);
            if (slot->has_value || !items) continue;
            slot->text = json_encode_items(p, *line.group, *items, geo);
            slot->has_value = true;
            continue;
        }
        if (const WhenLine* w = line.fixed()) {
            slot->has_value = true;
            slot->text = json_when_text(*w);
            continue;
        }
        if (slot->has_value || !src.value(*line.field, v)) continue;
        slot->text = member_text(p, *line.field, v);
        slot->has_value = true;
    }
    if (has_scalar) return scalar;
    std::string out;
    out_write(out, root);
    return out;
}

}  // namespace

std::vector<Item> json_decode_items(const Pack& p, const GroupLine& g, const json::Value& arr, bool geo) {
    if (!arr.is(json::Value::Kind::Array))
        throw Error(ErrorKind::MalformedWire, p.format, g.locator,
                    std::string("the member of the group '") + g.list + "' is " + json_kind_name(arr) +
                        ", not an array");
    std::vector<Item> items;
    items.reserve(arr.items.size());
    const std::vector<LineRef> lines = group_lines(g);
    std::vector<std::vector<std::string>> paths(lines.size());  // empty for a `.` field and for a const
    for (std::size_t k = 0; k < lines.size(); ++k)
        if (!lines[k].fixed() && lines[k].locator() != ".") parse_json_locator(lines[k].locator(), paths[k]);
    for (const json::Value& el : arr.items) {
        items.emplace_back();
        Item& item = items.back();
        Decoder d(p, item);
        for (std::size_t k = 0; k < lines.size(); ++k) {
            const LineRef& line = lines[k];
            if (line.group) {
                // A nested list: present when the member exists and is an array.
                if (const json::Value* v = json_lookup(el, paths[k]))
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
            if (const json::Value* v = json_lookup(el, paths[k])) decode_item_value(d, f, *v, geo);
        }
        d.finish();
    }
    return items;
}

std::string json_encode_items(const Pack& p, const GroupLine& g, const std::vector<Item>& items, bool geo) {
    const std::vector<LineRef> lines = group_lines(g);
    std::string out = "[";
    for (std::size_t k = 0; k < items.size(); ++k) {
        if (k) out += ',';
        out += encode_item(p, g, lines, items[k], geo);
    }
    out += ']';
    return out;
}

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
        std::vector<std::string> path;
        parse_json_locator(w.locator, path);  // validated at pack load
        const json::Value* v = json_lookup(doc, path);
        if (!v) return false;
        return w.present || json_when_matches(w, *v);
    });

    Entity e;
    Decoder d(p, e);
    std::unordered_set<std::string> mapped;
    std::vector<std::string> path;
    for (const auto& line : active_lines(p, kind)) {
        // `when <locator> present` does not map the member (0.5 ruling 27).
        if (line.maps()) mapped.insert(line.locator());
        if (line.group) {
            // The list is present when the member exists and is an array; `null` is absent.
            parse_json_locator(line.group->locator, path);
            if (const json::Value* v = json_lookup(doc, path))
                e.lists[line.group->list] = json_decode_items(p, *line.group, *v, false);
            continue;
        }
        if (!line.field || !d.wants(*line.field)) continue;
        parse_json_locator(line.field->locator, path);
        if (const json::Value* v = json_lookup(doc, path)) decode_member(d, *line.field, *v);
    }
    std::unordered_set<std::string> seen;
    collect_residue(e, p.format, doc, "", mapped, seen);
    d.finish();
    if (kind) e.kind = {p.format, kind->name};
    return e;
}

std::string encode_json(const Pack& p, const Entity& e) {
    const Kind* kind = select_encode_kind(p, e);
    const EncodeSource src(p, kind, e);
    OutNode root;
    root.is_object = true;
    std::unordered_set<std::string> mapped;
    std::vector<std::string> path;
    Value v;
    // Mapped members, `when` members and `const` members in line order, common
    // lines first. Every such line takes its place whether or not its member is
    // written. Where lines share a locator the earliest field with a value gives
    // it; a `when` or `const` value is written over any field. A `when ...
    // present` line maps nothing and takes no place. A group writes an array at
    // its member: `[]` for an empty list, nothing for an absent one.
    for (const auto& line : active_lines(p, kind)) {
        if (!line.maps()) continue;
        const std::string& locator = line.locator();
        mapped.insert(locator);
        parse_json_locator(locator, path);  // validated at pack load
        OutNode* slot = out_slot(root, path);
        if (!slot || slot->is_object) continue;  // the path is also used as an object
        if (line.group) {
            const std::vector<Item>* items = src.list(*line.group);
            if (slot->has_value || !items) continue;
            slot->text = json_encode_items(p, *line.group, *items, false);
            slot->has_value = true;
            continue;
        }
        if (const WhenLine* w = line.fixed()) {
            if (w->present) continue;
            slot->has_value = true;
            slot->text = json_when_text(*w);
            continue;
        }
        if (slot->has_value || !src.value(*line.field, v)) continue;
        slot->text = member_text(p, *line.field, v);
        slot->has_value = true;
    }
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

}  // namespace goat_transformers::detail
