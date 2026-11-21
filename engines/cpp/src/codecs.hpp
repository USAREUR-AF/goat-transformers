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

// Version 0.24 ruling 1c: the wire a `wire` value names. False when the value
// is no wire of the specification, or a wire this build does not have, with
// `why` saying which (the text of the `unknown-wire` message after its place).
bool parse_wire_value(const std::string& text, Wire& out, std::string& why);

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

// ---- kind selection (Version 0.20)

// A comma-separated list of values; false when an item is empty (`a,,b`,
// `a,`, ruling 16). A text with no comma, `""` included, is one item.
bool split_value_list(const std::string& text, std::vector<std::string>& out);
// The values of a `when` on `bits` or an integer `protobuf` `when`: unsigned
// decimal integers and ranges `<lo>..<hi>`, each within `len` bits (64 for
// protobuf). False with `why` set otherwise (bad-directive).
bool parse_when_numbers(const std::string& text, std::uint32_t len,
                        std::vector<std::pair<std::uint64_t, std::uint64_t>>& out, std::string& why);
// A `requires =` or `case` value read as `type`, as canonical text (ruling 1):
// an integer is an optional `-` then digits (ruling 17). False when it cannot be
// read (key-type-mismatch).
bool canonical_value_text(const std::string& text, KeyType type, std::string& out);
// One `requires` term: split at the first `=` (ruling 4). False with `why`
// for `k=`, `=v` or an empty item in the value list (bad-directive).
bool parse_requires_term(const std::string& token, std::size_t line, RequiresTerm& out, std::string& why);
// Canonical text of a model value: an integer as decimal digits, a float as in
// ruling 3 of 0.1.1, a string as itself. Throws std::invalid_argument.
std::string value_canonical_text(const Value& v);
// Does the item hold every `requires` term of a kind? A plain key: present, or a
// list with at least one item. `<key>=<values>`: present and its canonical text
// listed.
bool requires_hold(const std::vector<RequiresTerm>& terms, const std::vector<std::string>& keys, const Item& e);

// ---- value tables (Version 0.6)

// `text` read as a model type. Throws std::invalid_argument.
// `as_written`: text of a pack or module, read without trimming (0.18 ruling 18).
Value read_as(const std::string& text, KeyType type, bool as_written = false);
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
    void set_json_number(const FieldLine& f, const std::string& text);  // a JSON number (0.11 ruling 2d), then put
    void put(const FieldLine& f, Value native);             // the value table, then the key
    void fail(const FieldLine& f, const std::string& why);
    void finish();  // type mapping; throws transform-decode listing every failed field
};

// ---- one decode: the limit on list items and the failed fields (Version 0.11)

// The state of one decode, set up by Engine::decode for the codec it calls.
// While one is active, the items of every list are counted against the limit
// (ruling 7), and a failed field does not end the decode: the first is kept
// and raised when the decode ends, so that a failure of the wire found later,
// going over the limit among them, wins over it (ruling 7f).
class DecodeScope {
public:
    explicit DecodeScope(std::uint64_t max_items);
    ~DecodeScope();
    DecodeScope(const DecodeScope&) = delete;
    DecodeScope& operator=(const DecodeScope&) = delete;
    // Throws the first failed field, when there is one.
    void raise_failure() const;
    bool failed() const { return has_failure_; }

    std::uint64_t limit = 0;
    std::uint64_t held = 0;  // items the entity holds so far
    bool has_failure_ = false;
    std::string fail_format, fail_locator, fail_detail;

private:
    DecodeScope* outer_ = nullptr;
};
// `n` more items of the list `list`: malformed-wire when the decode would hold
// more than the limit (7a). No-op outside a decode.
void take_items(const Pack& p, const std::string& list, std::uint64_t n);
// Items a later group of one list replaced are no longer held (7g).
void give_back_items(std::uint64_t n);
// The items of a list, those of the lists inside its items included.
std::uint64_t count_items(const std::vector<Item>& items);

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
    // v0.18: does the entity (or the item) hold a key or list? A scalar holds
    // when present, a list when present with at least one item; a `default`
    // never holds (ruling 2).
    bool holds(const std::string& key) const;
    // v0.18: a line with `with <other-key>` whose key is not held: it writes
    // nothing, its default and its sentinel included (ruling 1).
    bool suppressed(const FieldLine& f) const { return !f.with.empty() && !holds(f.with); }
    // The items of a group's list; null when the item has no such list.
    const std::vector<Item>* list(const GroupLine& g) const;
};

// v0.56 `range <min> <max> [wrap]`: checks the model value `v` of a field
// with `range` against the interval, by the field's key type, and wraps it in
// place with `wrap`. Throws transform-encode outside a range without `wrap`.
void apply_range(const Pack& p, const FieldLine& f, Value& v);
// v0.56: one field option of the output conditions at t[k] (`null`, `implicit`,
// `range <min> <max> [wrap]`, a stray `wrap`), with its arguments; `k` is left
// on its last token. 1 when read, 0 when t[k] is not one of them, -1 with `why`
// when its syntax is refused (bad-directive; ruling 5b of 0.11, step 9: here
// <min> and <max> are number text, 2b).
int parse_output_option(const std::vector<std::string>& t, std::size_t& k, FieldLine& f, std::string& why);
// v0.56: the checks of `range` that need the key's type (bad-directive): an
// `int` or `float` key, an int key's integer text (2a), <min> below <max> read
// as that type. False with `why` when refused.
bool check_range(const FieldLine& f, KeyType type, std::string& why);

// ---- absent-value sentinels (Version 0.9)

// Checks a field's `absent` argument against the wire and the transform and
// fills the sentinels (bad-directive). `bits_len` is the field's length on the
// bits wire. A transform that does not belong to the wire is left for the
// invalid_pack check. `coordinate`: a geojson `geometry.*` slot, which takes
// only number text (0.9 ruling 25).
void resolve_absent(const Pack& p, Wire wire, FieldLine& f, std::uint32_t bits_len, bool coordinate = false);
// Does the raw value equal one of the field's sentinels?
bool sentinel_num(const FieldLine& f, std::uint64_t raw);
bool sentinel_text(const FieldLine& f, const std::string& raw);
// json and geojson: the raw text of a scalar member (a string's text, a
// number's canonical text through a double, a boolean's word); false for null,
// an array or an object.
bool json_raw_text(const json::Value& v, std::string& out);

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

// v0.14, `armor sixbit`: armored text -> the message bits, packed most
// significant bit first into bytes (the last byte's spare bits zero); `bits`
// is 6 * the characters. Every character is checked first: throws
// malformed-wire on any outside `0`-`W` and `` ` ``-`w`.
std::string armor_to_bytes(const Pack& p, const std::string& text, std::uint64_t& bits);
// The first `bits` bits of `data` (msb order), zero-filled to a multiple of 6,
// as armored text. Bits of `data` past its end read as zero.
std::string bytes_to_armor(const std::string& data, std::uint64_t bits);

// bits: how a pack's bit order places bits. `pos_msb`: bit i of the message is
// bit 7 - (i mod 8) of byte i div 8 (else bit i mod 8). `val_msb`: a field's
// first bit is its value's most significant (else its least). `msb` is both,
// `lsb` neither, and `msb-lsb` (v0.22) positions as `msb`, values as `lsb`.
struct BitMode {
    bool pos_msb = false;
    bool val_msb = false;
};
inline BitMode bit_mode(BitOrder o) { return BitMode{o != BitOrder::Lsb, o == BitOrder::Msb}; }

// bits: one field's message text, read from or written to `len` bits at
// `start`, for `ascii`, `sixbit` and the `chars` sets of 0.15. False for any
// other transform.
bool decode_bits_text(const FieldLine& f, const std::string& data, std::uint64_t start, std::uint32_t len, BitMode msb,
                      Value& out);
bool encode_bits_text(const FieldLine& f, const Value& v, std::string& data, std::uint64_t start, std::uint32_t len,
                      BitMode msb);

// json and geojson: the items of a group, from the array `arr` (an item per
// element), and back to the JSON text of an array. `geo` selects the geojson
// value types (0.7 ruling 7). Throws malformed-wire when `arr` is not an array.
std::vector<Item> json_decode_items(const Pack& p, const GroupLine& g, const json::Value& arr, bool geo);
std::string json_encode_items(const Pack& p, const GroupLine& g, const std::vector<Item>& items, bool geo);


// bits: `len` bits (1 to 64) from bit `start` of `data`, in the pack's bit
// order, and back; `swap_bytes` reverses the bytes of a `len`-bit value.
std::uint64_t read_bits(const std::string& data, std::uint64_t start, std::uint32_t len, BitMode msb);
void write_bits(std::string& data, std::uint64_t start, std::uint32_t len, std::uint64_t raw, BitMode msb);
std::uint64_t swap_bytes(std::uint64_t raw, std::uint32_t len);

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

// ---- the `text` wire (Version 0.10)

// `<i>`, `<i>:<from>:<len>` (len from 1) or `<i>+<j>`, indexes in decimal.
bool parse_text_locator(const std::string& loc, TextLocator& out);
// Parse the locator of every `field`, `when` and `const` line and of every
// `group` of a text pack. Throws bad-directive (0.10 ruling 14).
void parse_text_locators(Pack& p);
// The checks of a text pack that relate its directives, locators, transforms,
// values and groups to one another (bad-directive). Run after the file is read.
void check_text_pack(const Pack& p);
Entity decode_text(const Pack& p, const std::string& bytes);
std::string encode_text(const Pack& p, const Entity& e);

// ---- the `tlv` wire (Version 0.13)

// A tag as a pack writes it: a decimal integer from 0 to 2^28-1 with no leading zero.
bool parse_tlv_tag(const std::string& text, std::uint32_t& out);
// Parse the path and size of every `field`, `when` and `const` line of a tlv
// pack, and check them against the transforms, the directives and one another
// (bad-directive). Run after the file is read.
void check_tlv_pack(Pack& p);
Entity decode_tlv(const Pack& p, const std::string& bytes);
// The tlv checks of `utf8` and `hex` (v0.19 uses them on `octets` locators):
// is the text valid UTF-8; hex text of an even number of digits, either case, to bytes.
bool utf8_is_valid(const std::string& s);
bool hex_text_bytes(const std::string& s, std::string& out);
std::string encode_tlv(const Pack& p, const Entity& e);

}  // namespace goat_transformers::detail
