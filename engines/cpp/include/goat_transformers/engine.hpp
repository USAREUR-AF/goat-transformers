// goat-transformers C++ engine: public API.
// Implemented from spec/engine-spec.md, spec/shared-model.md and the pack vectors.
#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace goat_transformers {

namespace detail {
struct PackPlan;  // codecs.hpp: what is computed once from a loaded pack (0.25)
}

// ---------------------------------------------------------------- errors

// Every load and call failure has a kind of the specification (0.11 ruling 5),
// and its message begins with the kind's name and a colon. `Io` alone is not a
// kind of the specification: a directory or file could not be read.
enum class ErrorKind {
    UnterminatedQuote,  // a value that begins with `"` has no closing `"` on its line (0.11)
    UnknownDirective,   // the first word of a line is not a directive of its file type
    UnknownTransform,   // a transform name this specification does not have
    UnknownWire,        // a `wire` value that is not a wire, or a wire this build lacks (0.24)
    BadLocator,         // a locator that does not have the form its line takes on the wire (0.11)
    MissingFormat,      // a pack has no `format` line (0.11)
    MissingVersion,     // a pack or a module has no `version` line (0.11)
    MissingWire,        // a pack has no `wire` line, or a line that needs it stands before it (0.11)
    MissingModule,      // a module has no `module` line (0.11)
    DuplicateFormat,    // a pack whose `format` name is already loaded (0.11)
    UnknownFormat,      // decode/encode/convert asked for a format no loaded pack defines
    MalformedWire,      // input bytes are not well-formed for the wire
    MissingRoot,        // xml: a pack with no `root` (load), or a document with another root (decode)
    TransformDecode,    // a wire value could not be decoded by its field's transform
    TransformEncode,    // a model value could not be encoded by its field's transform
    Io,                 // a pack directory or file could not be read
    // v0.4 load checks.
    MissingDistribution,    // a module or pack has no `distribution` line
    MissingSource,          // a module or pack has no `source` line
    DistributionRefused,    // a module or pack is above the engine's distribution limit
    UnknownModule,          // `core` or a module in a `uses` line is not loaded
    DistributionViolation,  // a public pack uses a controlled module
    ModuleNotUsed,          // a mapped key's module is neither `core` nor in a `uses` line
    UndeclaredKey,          // a mapped key is not declared by its module
    KeyTypeMismatch,        // a field's transform does not yield the key's declared type
    DuplicateModule,        // a module name is loaded twice
    DuplicateKey,           // a key name appears twice in its module
    // v0.5
    NoKind,                 // no kind of the format matches the message or the entity
    DuplicateKind,          // a kind name is declared twice in its pack
    DuplicateField,         // withdrawn in 0.6 and never raised: a model key may be mapped by several lines
    BadDirective,           // a directive this specification has, used wrongly
    // v0.29
    BadLicence,             // a licence file that cannot be read as ruling 1 says, or a profile that is no profile
};

const char* error_kind_name(ErrorKind kind);

class Error : public std::runtime_error {
public:
    Error(ErrorKind kind, std::string format, std::string locator, const std::string& detail);
    ErrorKind kind() const noexcept { return kind_; }
    const std::string& format() const noexcept { return format_; }
    const std::string& locator() const noexcept { return locator_; }
    const std::string& detail() const noexcept { return detail_; }

private:
    ErrorKind kind_;
    std::string format_;
    std::string locator_;
    std::string detail_;
};

// ---------------------------------------------------------------- shared model

struct Value {
    enum class Kind { String, Float, Int };
    Kind kind = Kind::String;
    std::string s;
    double f = 0.0;
    std::int64_t i = 0;

    static Value of_string(std::string v);
    static Value of_float(double v);
    static Value of_int(std::int64_t v);
};

struct ResidueEntry {
    std::string format;   // the pack whose wire the locator belongs to
    std::string locator;  // that format's locator string
    std::string value;    // original wire value (xml, geojson: the text; json: canonical JSON text)
    // geojson: the member was an array or an object, and `value` is its JSON
    // text, written back as it was and not as a string (0.6 ruling 13).
    bool structured = false;
};

// What an item of a list holds (v0.7): model keys, and lists of its own. An
// item has no residue.
struct Item {
    std::map<std::string, Value> fields;
    // List name -> its items, in order. A list that is present and empty is
    // distinct from an absent list.
    std::map<std::string, std::vector<Item>> lists;
    // The kind decode selected, as (format, kind name): for an entity the
    // message's kind (v0.5), for an item of a list the item's kind (v0.8,
    // `Item.kind`). Both empty when no kind was selected or the kind was cleared.
    // Encode selects by it only when the format is the one being written, so an
    // item carried to another format chooses its kind by `requires`; so does an
    // item of a list whose group, in the format being written, has no kind of
    // that name (0.8 ruling 26).
    std::pair<std::string, std::string> kind;
};

struct Entity : Item {
    std::vector<ResidueEntry> residue;  // decode order
};

// ---------------------------------------------------------------- model modules (v0.4)

// How far a module or pack may be distributed. Public is below Controlled.
enum class Distribution { Public, Controlled };
enum class KeyType { String, Float, Int };

const char* distribution_name(Distribution d);
const char* key_type_name(KeyType t);

struct ModelKey {
    std::string name;     // no '.'
    KeyType type = KeyType::String;
    std::string unit;     // "-" when the key has none
    std::string meaning;  // optional
};

// The fixed set of functions a `derive` line may name (v0.6, Derived keys).
enum class DeriveFn { Copy, Hypot, Bearing, EastOf, NorthOf, Neg, Scale, Offset, Join,
                      DaySeconds, Any, Not, ParseInt, TextOf,  // v0.8
                      Present,  // v0.12
                      SecOf, NsecOf, MsOf, Deg, Rad, Add, Sub, DegLatOf, DegLonOf, MLatOf, MLonOf,  // v0.16
                      EcefX, EcefY, EcefZ, LatOfEcef, LonOfEcef, HaeOfEcef,
                      Tokens, HasToken, TextIf  // v0.18
};

// `derive <model-key> <function> <argument-key> [<argument-key>...]` (v0.6).
struct DeriveLine {
    std::string target;             // as written: bare for `core`, `<module>.<key>` otherwise
    std::string function;           // as written, with its parameter (`scale:1/3`)
    DeriveFn fn = DeriveFn::Copy;
    std::vector<std::string> args;  // argument keys, as written
    // scale: a decimal factor, or the fraction num/den (ruling 1 of 0.5).
    bool fraction = false;
    double factor = 1.0;
    double num = 1.0;
    double den = 1.0;
    // offset: <n> as a double, and as an integer when it is written as one.
    double offset = 0.0;
    bool offset_is_int = false;
    std::int64_t int_offset = 0;
    bool int_arith = false;         // offset, add or sub on `int` keys: integer arithmetic
    std::string sep;                // join; tokens and has_token: the separator character
    std::vector<std::string> tokens;  // tokens: the tokens; has_token: the one token
    std::string text;               // text_if
    std::size_t line = 0;           // line number in the module file
};

// `list <name> ["meaning"]` (v0.7): a list shares the key namespace of its module.
struct ModelList {
    std::string name;     // no '.'
    std::string meaning;  // optional
};

struct Module {
    std::string name;
    std::string version;
    Distribution distribution = Distribution::Controlled;
    std::vector<std::string> sources;  // `source` lines, file order
    std::vector<std::string> uses;     // `uses` lines, file order, each module once (v0.8)
    std::vector<ModelKey> keys;        // file order
    std::vector<ModelList> lists;      // `list` lines, file order (v0.7)
    std::vector<DeriveLine> derives;   // `derive` lines, file order (v0.6)
    std::string origin;                // where it was loaded from
    // Key name -> position in `keys`. parse_model fills it; a module built by
    // hand may leave it empty, and `find` then searches `keys`.
    std::unordered_map<std::string, std::size_t> index;
    std::unordered_map<std::string, std::size_t> list_index;  // the same, for `lists`

    const ModelKey* find(const std::string& key) const;
    const ModelList* find_list(const std::string& list) const;
};

// Parse the text of a model module file. `origin` names the file in error messages.
Module parse_model(const std::string& text, const std::string& origin = "model.def");

// ---------------------------------------------------------------- packs

// Text-wire transforms (xml, geojson) and bits-wire transforms are disjoint:
// a pack binds a field through a transform valid only on its wire's kind.
enum class Transform { String, Float, Int, Iso8601Ms, Uint, Twos, Linscale,
                       Pstring, Pvarint, Psint, Pdouble, Pfloat,
                       Bool,                             // v0.5, json wire only
                       Uscale, Sscale, F32, F64, Ascii,  // v0.5, bits wire
                       IntW, Dec, Dm, Hms, HmsDmy,       // v0.10, text wire only
                       Utf8, Hex,                        // v0.13, tlv wire only
                       Sixbit,                           // v0.14, bits wire
                       // v0.15, bits wire
                       Uiscale, Siscale, Smag, Smscale, F32scale, F64scale,
                       CharsIcao6, CharsAis6, CharsAscii7, Octal,
                       Scale, Iscale,                    // v0.15, xml, json and geojson
                       Iso8601Short,                     // v0.18, xml, json and geojson
                       CharsAscii8,                      // v0.22, bits wire
                       Iso8601S,                         // v0.26, xml, json, geojson and text
                       CborText, CborBytes, EpochS       // v0.28, cbor wire only: `text`, `bytes`, `epoch_s`
};
enum class Wire { Xml, GeoJson, Bits, Protobuf, Json, Text, Tlv, Cbor };

// A locator of the `text` wire (v0.10): a field, a column of a field, or a pair
// of fields. Inside a group the indexes count from the item's first field.
struct TextLocator {
    enum class Kind { Field, Column, Pair };
    Kind kind = Kind::Field;
    std::uint32_t i = 0;     // the field; the first field of a pair
    std::uint32_t j = 0;     // pair: the second field
    std::uint32_t from = 0;  // column: the first character, from 0
    std::uint32_t len = 0;   // column: the number of characters, from 1
};
// v0.22: MsbLsb, bit positions as `msb` counts them and a value's bits from
// its low bit up, as `lsb` assembles them.
enum class BitOrder { Lsb, Msb, MsbLsb };

const char* transform_name(Transform t);
KeyType transform_yields(Transform t);  // the model type a transform produces
const char* wire_name(Wire w);

// Version 0.24: the wires this build has, in the order xml, geojson, json,
// bits, protobuf, text, tlv. A build that names no set has all seven
// (README.md, Wires of a build). A pack on a wire the build lacks is refused
// with `unknown-wire`, and its message says this build does not have it.
std::vector<std::string> built_wires();
bool wire_built(Wire w);

struct FieldLine {
    std::string key;      // shared-model key
    std::string locator;  // place on the wire (text locator, or bits <word>:<pos>:<len>)
    Transform transform = Transform::String;
    double scale_maxpos = 0.0;  // linscale only: <maxpos>
    double scale_range = 0.0;   // linscale only: <range>
    // uscale / sscale (v0.5): factor is a decimal, or the fraction num/den.
    bool scale_fraction = false;
    double scale_factor = 1.0;
    double scale_num = 1.0;
    double scale_den = 1.0;
    double scale_offset = 0.0;
    // v0.10 text transforms: `int:<w>`, `dec:<f>[:<w>]`, `dm:<d>:<f>:<PN>`,
    // `hms:<f>`, `hms_dmy:<f>`. `text_w` is 0 when no width is given.
    int text_w = 0;
    int text_f = 0;
    int text_d = 0;
    char text_p = 'P';
    char text_n = 'N';
    TextLocator text_loc;       // text wire: the parsed locator
    // tlv wire (v0.13): the path of tags, outermost first, and `:<n>` (0 when none).
    std::vector<std::uint32_t> tlv_path;
    std::uint32_t tlv_size = 0;
    // uiscale, siscale, iscale (v0.15): the exact factor exact_num/exact_den in
    // lowest terms (den positive) and the integer offset.
    std::int64_t exact_num = 1;
    std::int64_t exact_den = 1;
    std::int64_t exact_offset = 0;
    std::size_t line = 0;       // line number in pack.def
    // v0.6 field options.
    std::string via;            // `via <table>`: the value table's name; empty when none
    int table = -1;             // index of that table in Pack::tables (parse_pack resolves it)
    bool swap = false;          // bits: the field's bytes are taken in reverse order
    bool trim = false;          // bits + ascii or sixbit: decode also removes trailing spaces (sixbit: and '@')
    bool optional = false;      // bits: absent when any of its bits lies beyond the input
    // v0.22. `stop <code>` on a fixed-size `chars` field: the text ends at the
    // first character of that code. `until:<code>` (sequential locator): the
    // field is the characters up to that code, which is consumed.
    bool has_stop = false;
    std::uint64_t stop_code = 0;
    bool until = false;
    std::uint64_t until_code = 0;
    // v0.9 `absent <value>[,<value>…]`: the raw wire values that mean "no value".
    bool has_absent = false;
    std::string absent_arg;                 // the argument as written ("" for the quoted empty token)
    std::vector<std::uint64_t> absent_num;  // bits and the integer forms of protobuf: the raw integers
    std::vector<std::string> absent_text;   // text wires and pstring: the texts compared (json: canonical)
    std::string absent_json;                // json and geojson: the JSON text the first sentinel is written as
    // The key's declared type. Engine::add_pack fills it from the loaded modules.
    KeyType key_type = KeyType::String;
    // v0.17: the innermost gate block holding the line (index in Pack::gates); -1 outside any.
    int gate = -1;
    // v0.18 `with <other-key>`: encode writes the line only when the entity (or
    // the item) holds that key. Empty when the line has no `with`.
    std::string with;
    // v0.20, sequential: the innermost `case` or `else` holding the line
    // (index in Pack::seq_cases); -1 outside any.
    int scase = -1;
};

// `when <locator> <value>` (v0.5), and `const <locator> <value>` (v0.6), which is
// written as a `when` value is and is never checked on decode.
struct WhenLine {
    std::string locator;
    std::string value;            // as written in the pack
    bool present = false;         // the value is the word `present` (text and protobuf wires)
    bool forced_string = false;   // text wires: the value was written with a leading `=`
    std::string text;             // text wires: the value with a leading `=` stripped
    std::uint64_t number = 0;     // bits wire, and protobuf when not `present`
    TextLocator text_loc;         // text wire: the parsed locator
    std::vector<std::uint32_t> tlv_path;  // tlv wire: the path of tags, outermost first
    std::uint32_t tlv_size = 0;           // tlv wire: `:<n>`, 0 when none
    // cbor wire (v0.28): the value's type, set at load. An integer is
    // `number` as the argument of major type 0, or of major type 1 when
    // `cbor_negative` (the value -1 - number); a bool is `number` 0 or 1; a
    // text string is `text`.
    enum class CborType { Int, Bool, Text };
    CborType cbor_type = CborType::Text;
    bool cbor_negative = false;
    std::size_t line = 0;         // line number in pack.def
    int gate = -1;                // v0.17, a `const` only: the innermost gate block holding it
    // v0.20, a `when` only: the values it holds for. bits and the integer form
    // of protobuf: closed ranges, a single value as lo == hi, in line order (the
    // first is `number`). Text wires: the texts, each with a leading `=`
    // stripped (the first is `text`).
    std::vector<std::pair<std::uint64_t, std::uint64_t>> ranges;
    std::vector<std::string> texts;
    bool holds_number(std::uint64_t v) const {
        if (ranges.empty()) return v == number;
        for (const auto& r : ranges)
            if (v >= r.first && v <= r.second) return true;
        return false;
    }
    bool holds_text(const std::string& v) const {
        if (texts.empty()) return v == text;
        for (const auto& t : texts)
            if (v == t) return true;
        return false;
    }
};

// v0.20: one term of a `requires` line, `<key>` or `<key>=<value>[,<value>...]`.
struct RequiresTerm {
    std::string key;
    bool has_values = false;
    std::vector<std::string> values;  // as written
    std::vector<std::string> canon;   // canonical text of each, as the key's type; Engine::add_pack fills it
    std::size_t line = 0;
};

// `default <model-key> <value>` (v0.6): the value encode uses for every `field`
// of the key in scope when the entity has none.
struct DefaultLine {
    std::string key;
    std::string text;   // as written in the pack
    Value value;        // `text` read as the key's declared type; Engine::add_pack fills it
    std::size_t line = 0;
    int gate = -1;      // v0.17: the innermost gate block holding it; -1 outside any
};

// `if [!]<word>:<pos>:<len> <value>[,<value>...]` ... `end` on a fixed layout
// (v0.17): the lines of the block exist only when the bits equal one of the
// values (with `!`, none of them).
struct GateBlock {
    std::string locator;                // as written, without the `!`
    bool negated = false;
    std::vector<std::uint64_t> values;  // line order
    int parent = -1;                    // the enclosing gate block; -1 when none
    std::uint64_t start = 0;            // bit offset in the scope (item-relative inside a group)
    std::uint32_t len = 0;
    std::size_t line = 0;               // line number in pack.def
    bool matches(std::uint64_t raw) const {
        bool listed = false;
        for (auto v : values) listed = listed || v == raw;
        return listed != negated;
    }
};

// The `map <table> <native> <model>` lines of one table, in pack order (v0.6).
struct MapTable {
    std::string name;
    std::vector<std::pair<std::string, std::string>> entries;  // native -> model
};

// `group <list> <locator> [item <bits>] [count <count-locator> | count <n>]` and
// the lines up to its `end` (v0.7). Every locator in the body is read relative
// to one item.
struct GroupLine {
    std::string list;      // the list's name, as written (`probe.items`)
    std::string locator;   // where the items are; bits: `<word>:<pos>` of the first item
    std::size_t line = 0;  // line number in pack.def
    // As written; parse_pack checks them against the wire.
    bool has_item = false;
    std::string item_text;
    bool has_count = false;
    std::string count_text;
    // bits only, settled by parse_pack.
    std::uint32_t item_bits = 0;     // `item <bits>`
    bool count_fixed = false;        // `count <n>`
    std::uint64_t count_n = 0;
    std::string count_locator;       // `count <word>:<pos>:<len>`, of the enclosing scope
    std::uint64_t count_start = 0;   // that locator as a bit offset in the enclosing scope
    std::uint32_t count_len = 0;
    std::uint64_t bits_start = 0;    // the first item's bit offset in the enclosing scope
    // text only (v0.10): `group <list> <i> item <n>`.
    std::uint32_t text_index = 0;    // <i>, the first item's first field
    std::uint32_t text_item = 0;     // <n>, the fields of one item
    // True when a `field` of the body has the locator `.`: an item is a scalar.
    bool scalar = false;
    std::vector<FieldLine> fields;
    std::vector<WhenLine> consts;
    std::vector<DefaultLine> defaults;
    std::vector<GroupLine> groups;   // nested
    std::vector<int> gates;          // v0.17: the body's gate blocks, line order (indices in Pack::gates)
};

// ---- sequential layouts (v0.8): a `bits` pack with `layout sequential` is a
// tree of lines read in order from a cursor.

struct SeqNode;

// A kind of the message or of a group's items. Its `when` lines are the first
// of `lines`.
struct SeqKind {
    std::string name;
    std::vector<std::string> requires_keys;
    std::vector<RequiresTerm> requires_terms;  // v0.20: every term, line order
    std::vector<DefaultLine> defaults;
    std::vector<SeqNode> lines;
    std::size_t line = 0;
};

// The lines of the message, of a block, or of one item of a group. `defaults`
// and `kinds` are used by the message and by a group only: a `default` inside
// an `if`, `opt`, `chain` or `length` block belongs to the message or item
// that holds the block.
struct SeqBody {
    std::vector<SeqNode> lines;         // the common lines
    std::vector<DefaultLine> defaults;  // the common `default` lines
    std::vector<SeqKind> kinds;
};

// One condition of an `if` line: `<name>.<i>` or `!<name>.<i>`.
struct SeqCond {
    int presence = -1;       // index in Pack::seq_presences
    std::uint32_t bit = 0;   // from 1, in reading order
    bool negated = false;
};

// A `presence` line of a sequential pack.
struct SeqPresence {
    std::string name;
    bool fx = false;
    std::uint32_t bits = 0;        // `presence <name> <n>`; 0 with `fx`
    std::uint32_t max_named = 0;   // the highest bit an `if` names
    std::vector<bool> named;       // named[i - 1]: some `if` outside every case names bit i, with or without `!`
    // v0.20 ruling 21: case_named[i - 1]: the innermost cases of the `if` lines
    // inside a case that name bit i.
    std::vector<std::vector<int>> case_named;
    std::size_t line = 0;
};

// v0.20: one `case` (or the `else`) of a `switch`: its lines and its
// `default` lines, which apply to its lines only (rulings 7 and 22).
struct SeqCase {
    bool is_else = false;
    std::vector<std::string> values;  // as written
    std::vector<std::string> canon;   // canonical text of each, as the key's type; Engine::add_pack fills it
    SeqBody body;
    int id = -1;                      // index in Pack::seq_cases
    std::size_t line = 0;
};

// v0.20: where a case is in the pack: the case it is nested in, in the same
// message or item.
struct SeqCaseScope {
    int parent = -1;  // the innermost case holding the switch; -1 when none
};

struct SeqNode {
    enum class Type { Field, Const, Pad, Align, When, Presence, If, Opt, Chain, Fx, Length, LengthWhole, Group,
                      Ext, Choice, Alt,  // v0.19
                      Switch,  // v0.20
                      Count };  // v0.21
    // v0.19: Size (`group <list> size`). v0.21: Rest (`group <list> rest`), Last
    // (`group <list> last`) and CountRef (`group <list> count @<name>`).
    enum class Repeat { Count, While, More, Fx, Size, Rest, Last, CountRef };
    // v0.19, `encoding uper`: the form of a field's locator. None is a bit length.
    enum class Uper { None, Int, IntExt, IntSemi, IntUn, Enum, EnumExt, Chars, Octets };
    Type type = Type::Pad;
    std::size_t line = 0;              // line number in pack.def
    // field: the bit length; const, when: the bit length of the value; pad:
    // the bits skipped; align: <n>; length: the bits of the length field;
    // group with `count`: the bits of the count.
    std::uint32_t len = 0;
    std::uint64_t number = 0;          // const, when: the value
    FieldLine field;                   // field: the key, transform and options; the locator is the length as written
    std::vector<FieldLine> also;       // `also` lines: more keys on the same bits, in line order
    int presence = -1;                 // presence: index in Pack::seq_presences
    std::vector<SeqCond> conds;        // if
    std::string list;                  // group: the list's name, as written
    Repeat repeat = Repeat::Count;     // group
    bool unit_bits = false;            // length: the block is counted in bits, not bytes
    std::int64_t plus = 0;             // length: `plus <n>`
    SeqBody inner;                     // if, opt, chain, length, ext, alt: the block; group: one item; choice: its alts
    // v0.19. field: the UPER locator form, with `lb` and `ub` (int:<lb>:<ub>,
    // int:<lb>:, chars and octets with `bounded`; enum: 0 and n - 1). group
    // with `size`: the bounds when `bounded`. choice: `number` is n and
    // `uext` the `ext` word; alt: `number` is the index.
    Uper uper = Uper::None;
    bool bounded = false;
    bool uext = false;
    std::int64_t lb = 0;
    std::int64_t ub = 0;
    // v0.20. when: the values it holds for, closed ranges in line order (the first's lo is `number`).
    std::vector<std::pair<std::uint64_t, std::uint64_t>> ranges;
    // v0.20. switch: the key (`field.key`) and the cases, the `else` last.
    std::vector<SeqCase> cases;
    // v0.20. if: the innermost case holding the block; -1 when none.
    int in_case = -1;
    // v0.21. count: the name; `len` is its bits and `plus` its `plus <n>`.
    // count and a group with `count @<name>`: the count line's index in
    // Pack::seq_count_lines.
    std::string count_name;
    int count_id = -1;
    bool holds(std::uint64_t v) const {
        if (ranges.empty()) return v == number;
        for (const auto& r : ranges)
            if (v >= r.first && v <= r.second) return true;
        return false;
    }
};

// `element <path>` (v0.18, xml only): the element at `path`, and each one on
// the way to it, is written on encode even when nothing inside it is.
struct ElementLine {
    std::string path;                // as written (`a/b`)
    std::vector<std::string> steps;  // the element names under the root
    std::size_t line = 0;            // line number in pack.def
};

struct Kind {
    std::string name;
    std::string root;                     // xml only: this kind's root element; empty = the pack's
    std::vector<FieldLine> fields;        // line order
    std::vector<WhenLine> whens;          // line order
    std::vector<WhenLine> consts;         // `const` lines, line order
    std::vector<DefaultLine> defaults;    // `default` lines, line order
    std::vector<GroupLine> groups;        // `group` blocks, line order (v0.7)
    std::vector<std::string> requires_keys;  // every `requires` key or list of the kind
    std::vector<RequiresTerm> requires_terms;  // v0.20: every term, line order
    std::vector<int> gates;               // v0.17: the kind's gate blocks, line order (indices in Pack::gates)
    std::vector<ElementLine> elements;    // v0.18: the kind's `element` lines, line order
};

struct Pack {
    std::string format;
    std::string version;
    Wire wire = Wire::Xml;
    std::string root;                                         // xml only; may be empty when every kind has its own
    std::uint32_t word_bytes = 0;                            // bits only: bytes per word
    BitOrder bit_order = BitOrder::Lsb;                       // bits only
    bool armor_sixbit = false;                                // v0.14, bits only: `armor sixbit`
    std::vector<FieldLine> fields;                            // common lines (every line when the pack has no kinds)
    std::vector<WhenLine> whens;                              // common `when` lines
    std::vector<WhenLine> consts;                             // common `const` lines
    std::vector<DefaultLine> defaults;                        // common `default` lines
    std::vector<GroupLine> groups;                            // common `group` blocks (v0.7)
    std::vector<MapTable> tables;                             // value tables, first appearance order
    std::vector<Kind> kinds;                                  // pack order; empty when the pack has no `kind` line
    std::vector<std::pair<std::string, std::string>> typemap; // native code -> CoT type
    std::vector<GateBlock> gates;                             // v0.17: every gate block, line order
    std::vector<int> common_gates;                            // v0.17: the common lines' gate blocks
    std::vector<ElementLine> elements;                        // v0.18: the common `element` lines, line order
    Distribution distribution = Distribution::Controlled;     // `distribution` line (required)
    std::vector<std::string> sources;                         // `source` lines (at least one)
    std::vector<std::string> uses;                            // `uses` lines; `core` is always used
    std::string source;                                       // where it was loaded from
    // xml: root element name -> the kinds decode considers for a document with that
    // root, in pack order (a kind with no `root` is listed under the pack's).
    // Engine::add_pack builds it, so kind selection does not scan every kind.
    std::unordered_map<std::string, std::vector<std::size_t>> kinds_by_root;
    // v0.25 ruling 1: the layouts computed from this pack once, when an engine
    // adds it (the lines of each kind and group body in line order, each
    // locator parsed, the placement of `element` lines, ...), so a conversion
    // reads them instead of recomputing them. Never written after the engine
    // has added the pack, so any number of threads may read it. It describes
    // the Pack it was built for only: a copy of the Pack does not use it.
    std::shared_ptr<const detail::PackPlan> plan;
    // v0.8, `layout sequential` (bits only): the message as lines read from a
    // cursor. `fields`, `whens`, `consts`, `groups`, `kinds` and `defaults`
    // above are then empty.
    bool sequential = false;
    bool uper = false;  // v0.19: `encoding uper`
    SeqBody seq;
    // v0.10, the `text` wire: `delimiter`, `start` and `checksum`.
    char delimiter = ',';
    bool delimiter_none = false;
    std::string start;
    bool checksum_nmea = false;
    std::vector<SeqPresence> seq_presences;
    // v0.13, the `tlv` wire: `tag`, `length`, `key` and `checksum sum16 <tag>`
    // (v0.27: or `checksum crc32 <tag>`).
    std::uint32_t tlv_tag_bytes = 0;     // 0: ber-oid; else 1, 2 or 4
    std::uint32_t tlv_length_bytes = 0;  // 0: ber; else 1, 2 or 4
    bool tlv_has_key = false;
    std::string tlv_key;                 // the key's bytes
    bool tlv_checksum = false;           // `checksum sum16 <tag>` or `checksum crc32 <tag>`
    bool tlv_checksum_crc32 = false;     // v0.27: the checksum is `crc32`, not `sum16`
    std::uint32_t tlv_checksum_tag = 0;
    std::vector<SeqCaseScope> seq_cases;  // v0.20: every `case` and `else`, file order
    std::size_t seq_count_lines = 0;      // v0.21: the number of `count <name>` lines
    // v0.28, the `cbor` wire: `tag <n>`, and whether the paths decide an array
    // as the top item (else a map).
    bool cbor_tag = false;
    std::uint64_t cbor_tag_value = 0;
    bool cbor_top_array = false;
};

// Parse the text of a pack.def. `source` names the file in error messages.
Pack parse_pack(const std::string& text, const std::string& source = "pack.def");

// ---------------------------------------------------------------- engine

// The capability report of an ordered pair of formats (0.11 ruling 6),
// computed from the two packs alone. `grade` is "full", "partial" or "none";
// `carried` and `dropped` are entries of model_keys(from), in its order.
// The licence of a loaded pack (engine-spec.md 0.29): its directory name, its
// format, the licence id of `<packs>/<dir>/REUSE.toml` (`Apache-2.0` when
// there is none) and the pack's own profile (ruling 2c): `open`,
// `open+copyleft`, `everything` or `none`.
struct PackLicence {
    std::string dir;
    std::string format;
    std::string licence;
    std::string profile;
};

struct Capability {
    std::string grade;
    std::vector<std::string> carried;
    std::vector<std::string> dropped;
};

class Engine {
public:
    // Load every `<models_dir>/*.def` in byte order of file name, then every
    // `<packs_dir>/<name>/pack.def`. An empty models_dir means `<packs_dir>/../model`.
    static Engine load(const std::string& packs_dir, const std::string& models_dir = "",
                       Distribution max_distribution = Distribution::Controlled);
    // Load only the packs named, each `<packs_dir>/<name>/pack.def`, in the
    // order given, and before them the modules they need: `core`, the modules
    // their `uses` lines name and the modules those use. A module is found by
    // the name its `module` line states, among `<models_dir>/*.def`: every file
    // there is read, so one that does not parse fails the load, and only the
    // needed modules are checked against the engine and loaded. A name that is
    // not a pack directory of `packs_dir` fails with Io; a name given twice is
    // loaded once.
    static Engine load_packs(const std::string& packs_dir, const std::vector<std::string>& names,
                             const std::string& models_dir = "",
                             Distribution max_distribution = Distribution::Controlled);
    // The loading of the command-line tool (engine-spec.md 0.23, Loading).
    // Modules: `<models_dir>/core.def`, then every other file of models_dir
    // whose name ends in `.def`, in byte order of file name, not recursing,
    // each after the modules it uses; a models_dir that does not exist or is
    // not a directory loads no modules. Packs: with `names`, each
    // `<packs_dir>/<name>/pack.def` in the order given, a name given twice
    // loaded twice (duplicate-format); a name that is not one path component
    // or not a pack directory fails with unknown-format when it is reached.
    // Without `names`, every entry of packs_dir that is a directory (a
    // symbolic link to one included), holds `pack.def` and does not begin
    // with `.`, in byte order of name; a packs_dir that cannot be read then
    // fails with Io. The modules are loaded before packs_dir is read.
    //
    // Licence profiles (engine-spec.md 0.29). `profile` is `open`,
    // `open+copyleft` or `everything`; any other text is bad-licence before
    // anything is read. With a profile, `<packs_dir>/../licences.toml` and,
    // for each module file in the order above, `<models_dir>/<file>.license`
    // are read before any module is loaded, then each pack's
    // `<packs_dir>/<dir>/REUSE.toml` when the pack is reached (after the
    // checks of its name); a module or pack whose profile the profile does
    // not hold is not loaded, nor otherwise read. A licence file that cannot
    // be read as ruling 1 says is bad-licence. With no profile no licence file
    // is read and the load is as above, unless `read_licences` is true: then
    // every licence file is read in the same order and nothing is skipped
    // (the `licences` subcommand). pack_licences() holds the result.
    static Engine load_tool(const std::string& packs_dir, const std::string& models_dir,
                            const std::vector<std::string>* names,
                            Distribution max_distribution = Distribution::Controlled,
                            const std::optional<std::string>& profile = std::nullopt,
                            bool read_licences = false);
    // True for the three profile names.
    static bool is_profile(const std::string& name);
    // The licences of the loaded packs in byte order of directory name, when
    // load_tool read them (a profile, or read_licences); otherwise empty.
    const std::vector<PackLicence>& pack_licences() const noexcept { return pack_licences_; }

    // The distribution limit, Controlled by default. It applies to later loads.
    void set_max_distribution(Distribution limit) { max_distribution_ = limit; }
    Distribution max_distribution() const noexcept { return max_distribution_; }

    // The limit on list items one decode holds (0.11 ruling 7): every item of
    // every list at every nesting level counts one. 100,000 by default; with 0
    // any item is refused. A decode that would hold one item more fails with
    // malformed-wire. `encode` of an entity a program built is not limited.
    static constexpr std::uint64_t kDefaultMaxItems = 100000;
    void set_max_items(std::uint64_t limit) { max_items_ = limit; }
    std::uint64_t max_items() const noexcept { return max_items_; }

    // Load one model module. Modules are loaded before the packs that use them.
    // A module is checked in this order (0.8 ruling 29): missing-distribution,
    // missing-source, distribution-refused, unknown-module,
    // distribution-violation, the keys and types of its `derive` lines,
    // duplicate-module. A `derive` line that is wrong as a line (its function,
    // parameter or argument count) fails while the text is read, before them
    // (0.6 ruling 9).
    void load_model(const std::string& text, const std::string& origin = "model.def");
    void add_model(Module module);
    bool has_module(const std::string& name) const;
    std::vector<std::string> modules() const;  // sorted

    // Check the pack against the loaded modules (engine-spec.md v0.4, Loading), then add it.
    // A pack whose `format` name is loaded already is refused with
    // duplicate-format, after every other check (0.11 ruling 5b).
    void add_pack(Pack pack);
    bool has_format(const std::string& format) const;
    const Pack& pack(const std::string& format) const;
    std::vector<std::string> formats() const;  // sorted
    // The keys the pack maps, each once, in the order of first appearance
    // reading the file top to bottom, common lines and every kind alike (0.11
    // ruling 6a). A list is `<list>[]` and an item key `<list>[].<key>`,
    // nested lists likewise (6b).
    std::vector<std::string> model_keys(const std::string& format) const;
    // The capability report of `from` against `to` (0.11 ruling 6). Throws
    // unknown-format for a format that is not loaded.
    Capability capability(const std::string& from, const std::string& to) const;

    Entity decode(const std::string& format, const std::string& bytes) const;
    std::string encode(const std::string& format, const Entity& entity) const;
    // decode; clear Entity.kind unless from == to; when from != to, the derivations;
    // encode. A same-format conversion with no context derives nothing, so it stays
    // byte-exact.
    std::string convert(const std::string& from, const std::string& to,
                        const std::string& bytes) const;

    // ---- v0.6: caller-supplied keys and derived keys

    // Model keys and values the caller supplies to `convert`.
    using Context = std::map<std::string, Value>;
    // decode; clear Entity.kind unless from == to; fill the keys the entity lacks
    // from `context`; the derivations; encode. Passing a context, even an empty one,
    // runs the derivations on a same-format conversion too.
    std::string convert(const std::string& from, const std::string& to, const std::string& bytes,
                        const Context& context) const;
    // The same with the context in string form (a vector's `context`, the CLI's
    // `--set`). The context is read and checked after the decode, so input that
    // does not decode fails with the decode's error whatever the context holds
    // (0.6 ruling 10).
    std::string convert_text(const std::string& from, const std::string& to, const std::string& bytes,
                             const std::map<std::string, std::string>& context) const;
    // A context given in string form:
    // each value is read as its key's declared type. Throws undeclared-key for a key
    // no loaded module declares and key-type-mismatch for a value that cannot be read.
    Context context_from_text(const std::map<std::string, std::string>& text) const;
    // A context in string form whose keys are read and checked in the order
    // given (engine-spec.md 0.23, `convert`: the `--set` options). A key given
    // twice takes its last value; the caller removes the repetition, which
    // keeps the place of the first.
    using TextContext = std::vector<std::pair<std::string, std::string>>;
    Context context_from_text_in_order(const TextContext& text) const;
    // convert_text with a context whose keys are checked in the order given.
    std::string convert_text_in_order(const std::string& from, const std::string& to, const std::string& bytes,
                                      const TextContext& context) const;
    // Check every context key (undeclared-key, key-type-mismatch), then set each
    // one the entity lacks.
    void apply_context(Entity& entity, const Context& context) const;
    // Apply the `derive` lines of the loaded modules: modules in byte order of
    // name, each module's lines in order, repeated until a pass sets nothing, at
    // most 8 passes. A present target is kept.
    void complete(Entity& entity) const;
    // The declaration of a model key as a pack writes it (`lat`, `track.class`);
    // null when no loaded module declares it.
    const ModelKey* find_key(const std::string& key) const;
    // True when a loaded module declares `list` (written as in a pack) as a list.
    bool is_list(const std::string& list) const;

private:
    // Each pack is immutable once added (0.25 ruling 1): a copy of the engine
    // shares it, and its plan stays valid wherever the engine is copied or moved.
    std::map<std::string, std::shared_ptr<const Pack>> packs_;
    std::map<std::string, Module> modules_;  // ordered by name, bytewise: the order derivations run in
    std::string convert_impl(const std::string& from, const std::string& to, const std::string& bytes,
                             const Context* context, const std::map<std::string, std::string>* text,
                             const TextContext* ordered = nullptr) const;
    Distribution max_distribution_ = Distribution::Controlled;
    std::uint64_t max_items_ = kDefaultMaxItems;
    std::vector<PackLicence> pack_licences_;
};

}  // namespace goat_transformers
