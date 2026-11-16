// Wire codecs: locator grammar and decode/encode per wire.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"
#include "json.hpp"

namespace goat_transformers::detail {

struct XmlLocator {
    enum class Kind { Attr, Text, Element };
    std::vector<std::string> path;  // element names under the root
    Kind kind = Kind::Attr;
    std::string name;               // attribute name for Attr
};
bool parse_xml_locator(const std::string& loc, XmlLocator& out);

struct GeoLocator {
    enum class Kind { Lon, Lat, Alt, Property, Member };
    Kind kind = Kind::Member;
    std::string name;  // property or top-level member name
};
bool parse_geo_locator(const std::string& loc, GeoLocator& out);

struct BitsLocator {
    std::uint32_t word = 0;  // zero-based word index
    std::uint32_t pos = 0;   // bit position within the word
    std::uint32_t len = 0;   // bit length; the allowed range depends on the transform
};
bool parse_bits_locator(const std::string& loc, BitsLocator& out);
// A bits group locator, `<word>:<pos>`: where the first item starts.
bool parse_bits_group_locator(const std::string& loc, std::uint32_t& word, std::uint32_t& pos);

struct ProtobufLocator {
    std::vector<std::uint32_t> path;  // field numbers, outermost first (4.1 -> {4, 1})
};
bool parse_protobuf_locator(const std::string& loc, ProtobufLocator& out);

// json wire: one or more member names separated by '.'.
bool parse_json_locator(const std::string& loc, std::vector<std::string>& path);

// `allow_element` permits the element-presence form, which only residue uses.
bool valid_locator(Wire w, const std::string& loc, bool allow_element = false);

// ---- message kinds (engine-spec.md, Version 0.5) and mapping rules (Version 0.6)

// One `field`, `when` or `const` line, or one `group` block (0.7).
struct LineRef {
    const FieldLine* field = nullptr;
    const WhenLine* when = nullptr;
    const WhenLine* konst = nullptr;
    const GroupLine* group = nullptr;
    // The `when` or `const` line: both are written on encode, typed the same way.
    const WhenLine* fixed() const { return when ? when : konst; }
    const std::string& locator() const {
        return field ? field->locator : group ? group->locator : fixed()->locator;
    }
    // Text wires: does the line map its locator, so that what the wire holds
    // there is not residue? `when <locator> present` does not (0.5 ruling 27).
    bool maps() const { return !when || !when->present; }
};
// The common lines in line order, then the lines of `kind` (may be null) in line order.
std::vector<LineRef> active_lines(const Pack& p, const Kind* kind);
// The lines of a group body, in line order.
std::vector<LineRef> group_lines(const GroupLine& g);

// What a scope's lines are read into and written from: the `default` lines in
// scope. An item sees the defaults of its group body only (0.7): a common or
// kind default does not reach into items.
struct Defaults {
    const std::vector<DefaultLine>* first = nullptr;   // the selected kind's, or the group body's
    const std::vector<DefaultLine>* second = nullptr;  // the common ones
};

// Decode: every common `when` must hold, then the first kind whose every `when`
// holds. With `candidates` (xml: the kinds whose root is the document's) only
// those kinds are considered, in the order given. Null for a pack with no kinds;
// throws no-kind.
template <class Holds>
const Kind* select_decode_kind(const Pack& p, Holds holds, const std::vector<std::size_t>* candidates = nullptr) {
    if (p.kinds.empty()) return nullptr;
    for (const auto& w : p.whens)
        if (!holds(w))
            throw Error(ErrorKind::NoKind, p.format, w.locator, "the common 'when " + w.locator + " " + w.value +
                                                                    "' does not hold");
    auto matches = [&](const Kind& k) {
        for (const auto& w : k.whens)
            if (!holds(w)) return false;
        return true;
    };
    if (candidates) {
        for (std::size_t i : *candidates)
            if (matches(p.kinds[i])) return &p.kinds[i];
    } else {
        for (const auto& k : p.kinds)
            if (matches(k)) return &k;
    }
    throw Error(ErrorKind::NoKind, p.format, "", "the message matches no kind");
}

// Encode: the kind Entity.kind names for this format, else the first kind whose
// `requires` keys are all present. Null for a pack with no kinds; throws no-kind.
const Kind* select_encode_kind(const Pack& p, const Entity& e);

// ---- value tables (Version 0.6)

// `text` read as a model type. Throws std::invalid_argument.
Value read_as(const std::string& text, KeyType type);
// The type of a table's <model> side: string unless every <model> value is an
// integer (int) or every one is a number (float).
KeyType table_model_type(const MapTable& table);
// A field's value through its table: wire side to model side after the transform
// on decode, model side to wire side before it on encode. Throws
// std::invalid_argument when the value has no entry and the two types differ, or
// when the entry cannot be read as the type that side needs.
Value table_decode(const Pack& p, const FieldLine& f, const Value& native);
Value table_encode(const Pack& p, const FieldLine& f, const Value& model);

// Shared decode bookkeeping for one entity or one item: failed fields and type
// mapping. A model key takes its value from the earliest line whose locator is
// present on the wire and whose transform succeeds (0.6); a key every line of
// which failed makes the decode fail, and so does a line whose transform
// succeeds and whose table has no entry (0.7 ruling 10).
struct Decoder {
    const Pack& p;
    Item& out;
    struct Failure {
        std::string key, locator, why;
        bool table = false;  // the transform succeeded and the table had no entry
    };
    std::vector<Failure> failures;
    // Keys a table miss has closed: later lines of the key are not tried.
    std::vector<std::string> closed;

    Decoder(const Pack& pack, Item& target) : p(pack), out(target) {}
    // False once an earlier line has given the key its value, or failed in its
    // table: later lines are not read.
    bool wants(const FieldLine& f) const;
    void set(const FieldLine& f, const std::string& text);  // text-wire transform, then put
    void put(const FieldLine& f, Value native);             // the value table, then the key
    void fail(const FieldLine& f, const std::string& why);
    void finish();  // type mapping; throws transform-decode listing every failed field
};

// What encode writes for a field: the item's value, else the `default` in
// scope, then the reverse type mapping and the field's value table.
struct EncodeSource {
    const Pack& p;
    const Item& e;
    Defaults defaults;

    EncodeSource(const Pack& pack, const Kind* k, const Item& entity)
        : p(pack), e(entity), defaults{k ? &k->defaults : nullptr, &pack.defaults} {}
    EncodeSource(const Pack& pack, const GroupLine& g, const Item& item)
        : p(pack), e(item), defaults{&g.defaults, nullptr} {}
    // False when the field has no value. Throws transform-encode.
    bool value(const FieldLine& f, Value& out) const;
    // The items of a group's list; null when the item has no such list.
    const std::vector<Item>* list(const GroupLine& g) const;
};

// Wire text for one field's value on a text wire. Throws transform-encode.
std::string field_text(const Pack& p, const FieldLine& f, const Value& v);
// The reverse type mapping applied to the key `type`.
Value typemapped_out(const Pack& p, const FieldLine& f, const Value& v);

// json and geojson: does the member value satisfy a `when` that is not `present`?
bool json_when_matches(const WhenLine& w, const json::Value& v);
// json and geojson: the JSON text a `when` value is written as (0.5 ruling 11).
std::string json_when_text(const WhenLine& w);

// Hex text <-> bytes for the binary wires. Throws malformed-wire.
std::string hex_to_bytes(const Pack& p, const std::string& text);
std::string bytes_to_hex(const std::string& data);

// json and geojson: the items of a group, from the array `arr` (an item per
// element), and back to the JSON text of an array. `geo` selects the geojson
// value types (0.7 ruling 7). Throws malformed-wire when `arr` is not an array.
std::vector<Item> json_decode_items(const Pack& p, const GroupLine& g, const json::Value& arr, bool geo);
std::string json_encode_items(const Pack& p, const GroupLine& g, const std::vector<Item>& items, bool geo);

Entity decode_xml(const Pack& p, const std::string& bytes);
std::string encode_xml(const Pack& p, const Entity& e);
Entity decode_geojson(const Pack& p, const std::string& bytes);
std::string encode_geojson(const Pack& p, const Entity& e);
Entity decode_bits(const Pack& p, const std::string& bytes);
std::string encode_bits(const Pack& p, const Entity& e);
Entity decode_protobuf(const Pack& p, const std::string& bytes);
std::string encode_protobuf(const Pack& p, const Entity& e);
Entity decode_json(const Pack& p, const std::string& bytes);
std::string encode_json(const Pack& p, const Entity& e);

}  // namespace goat_transformers::detail
