// pack.def and model module parsing (engine-spec.md, Pack definition grammar;
// v0.2 bits wire; v0.4 model modules and distribution).
#include <algorithm>
#include <cstdint>
#include <set>
#include <unordered_map>

#include "codecs.hpp"
#include "derive.hpp"
#include "linecheck.hpp"
#include "sequential.hpp"
#include "goat_transformers/engine.hpp"
#include "transforms.hpp"
#include "wires.hpp"

namespace goat_transformers {

const char* error_kind_name(ErrorKind kind) {
    switch (kind) {
        case ErrorKind::UnterminatedQuote: return "unterminated-quote";
        case ErrorKind::UnknownDirective: return "unknown-directive";
        case ErrorKind::UnknownTransform: return "unknown-transform";
        case ErrorKind::UnknownWire: return "unknown-wire";
        case ErrorKind::BadLocator: return "bad-locator";
        case ErrorKind::MissingFormat: return "missing-format";
        case ErrorKind::MissingVersion: return "missing-version";
        case ErrorKind::MissingWire: return "missing-wire";
        case ErrorKind::MissingModule: return "missing-module";
        case ErrorKind::DuplicateFormat: return "duplicate-format";
        case ErrorKind::UnknownFormat: return "unknown-format";
        case ErrorKind::MalformedWire: return "malformed-wire";
        case ErrorKind::MissingRoot: return "missing-root";
        case ErrorKind::TransformDecode: return "transform-decode";
        case ErrorKind::TransformEncode: return "transform-encode";
        case ErrorKind::Io: return "io";
        case ErrorKind::MissingDistribution: return "missing-distribution";
        case ErrorKind::MissingSource: return "missing-source";
        case ErrorKind::DistributionRefused: return "distribution-refused";
        case ErrorKind::UnknownModule: return "unknown-module";
        case ErrorKind::DistributionViolation: return "distribution-violation";
        case ErrorKind::ModuleNotUsed: return "module-not-used";
        case ErrorKind::UndeclaredKey: return "undeclared-key";
        case ErrorKind::KeyTypeMismatch: return "key-type-mismatch";
        case ErrorKind::DuplicateModule: return "duplicate-module";
        case ErrorKind::DuplicateKey: return "duplicate-key";
        case ErrorKind::NoKind: return "no-kind";
        case ErrorKind::DuplicateKind: return "duplicate-kind";
        case ErrorKind::DuplicateField: return "duplicate-field";
        case ErrorKind::BadDirective: return "bad-directive";
        case ErrorKind::BadLicence: return "bad-licence";
        case ErrorKind::MessageCount: return "message-count";
    }
    return "unknown";
}

namespace {
// Every message begins with the error kind and a colon.
std::string error_message(ErrorKind kind, const std::string& format, const std::string& locator,
                          const std::string& detail) {
    std::string m = error_kind_name(kind);
    m += ":";
    if (!format.empty()) m += " format=" + format;
    if (!locator.empty()) m += " locator=" + locator;
    if (!detail.empty()) m += " " + detail;
    return m;
}
}  // namespace

Error::Error(ErrorKind kind, std::string format, std::string locator, const std::string& detail)
    : std::runtime_error(error_message(kind, format, locator, detail)),
      kind_(kind),
      format_(std::move(format)),
      locator_(std::move(locator)),
      detail_(detail) {}

const char* distribution_name(Distribution d) {
    return d == Distribution::Public ? "public" : "controlled";
}

const char* key_type_name(KeyType t) {
    switch (t) {
        case KeyType::String: return "string";
        case KeyType::Float: return "float";
        case KeyType::Int: return "int";
    }
    return "?";
}

// engine-spec.md v0.4, The type a transform yields.
KeyType transform_yields(Transform t) {
    switch (t) {
        case Transform::String:
        case Transform::Pstring: return KeyType::String;
        case Transform::Float:
        case Transform::Linscale:
        case Transform::Pdouble:
        case Transform::Pfloat:
        case Transform::Uscale:
        case Transform::Sscale:
        case Transform::F32:
        case Transform::F64:
        case Transform::Dec:
        case Transform::Dm:
        case Transform::Hms: return KeyType::Float;
        case Transform::Ascii:
        case Transform::Sixbit:
        case Transform::Utf8:
        case Transform::Hex:
        case Transform::CborText:
        case Transform::CborBytes: return KeyType::String;
        case Transform::EpochS:
        case Transform::CodeNum: return KeyType::Int;
        case Transform::Code:
        case Transform::CodeStr: return KeyType::String;
        case Transform::Smscale:
        case Transform::F32scale:
        case Transform::F64scale:
        case Transform::Scale: return KeyType::Float;
        case Transform::CharsIcao6:
        case Transform::CharsAis6:
        case Transform::CharsAscii7:
        case Transform::CharsAscii8:
        case Transform::Octal: return KeyType::String;
        case Transform::IntW:
        case Transform::HmsDmy:
        case Transform::Uiscale:
        case Transform::Siscale:
        case Transform::Smag:
        case Transform::Iscale:
        case Transform::Bool:
        case Transform::Int:
        case Transform::Iso8601Ms:
        case Transform::Iso8601Short:
        case Transform::Iso8601S:
        case Transform::Uint:
        case Transform::Twos:
        case Transform::Pvarint:
        case Transform::Psint: return KeyType::Int;
    }
    return KeyType::String;
}

const ModelKey* Module::find(const std::string& key) const {
    if (index.size() == keys.size()) {
        auto it = index.find(key);
        return it == index.end() ? nullptr : &keys[it->second];
    }
    for (const auto& k : keys)
        if (k.name == key) return &k;
    return nullptr;
}

const ModelList* Module::find_list(const std::string& list) const {
    if (list_index.size() == lists.size()) {
        auto it = list_index.find(list);
        return it == list_index.end() ? nullptr : &lists[it->second];
    }
    for (const auto& l : lists)
        if (l.name == list) return &l;
    return nullptr;
}

const char* wire_name(Wire w) {
    switch (w) {
        case Wire::Xml: return "xml";
        case Wire::GeoJson: return "geojson";
        case Wire::Bits: return "bits";
        case Wire::Protobuf: return "protobuf";
        case Wire::Json: return "json";
        case Wire::Text: return "text";
        case Wire::Tlv: return "tlv";
        case Wire::Cbor: return "cbor";
    }
    return "?";
}

bool wire_built(Wire w) {
    switch (w) {
        case Wire::Xml: return GT_WIRE_XML;
        case Wire::GeoJson: return GT_WIRE_GEOJSON;
        case Wire::Json: return GT_WIRE_JSON;
        case Wire::Bits: return GT_WIRE_BITS;
        case Wire::Protobuf: return GT_WIRE_PROTOBUF;
        case Wire::Text: return GT_WIRE_TEXT;
        case Wire::Tlv: return GT_WIRE_TLV;
        case Wire::Cbor: return GT_WIRE_CBOR;
    }
    return false;
}

namespace {
constexpr Wire kAllWires[] = {Wire::Xml, Wire::GeoJson, Wire::Json, Wire::Bits, Wire::Protobuf, Wire::Text, Wire::Tlv,
                             Wire::Cbor};
}  // namespace

std::vector<std::string> built_wires() {
    std::vector<std::string> out;
    for (Wire w : kAllWires)
        if (wire_built(w)) out.push_back(wire_name(w));
    return out;
}

bool detail::parse_wire_value(const std::string& text, Wire& out, std::string& why) {
    for (Wire w : kAllWires) {
        if (text != wire_name(w)) continue;
        if (!wire_built(w)) {
            why = "wire '" + text + "' is a wire of the specification that this build does not have";
            return false;
        }
        out = w;
        return true;
    }
    why = "wire '" + text + "'";
    return false;
}

namespace {

bool tokenize(const std::string& line, std::vector<std::string>& out, std::string& err);
}  // namespace

bool detail::tokenize_line(const std::string& line, std::vector<std::string>& out, std::string& err) {
    return tokenize(line, out, err);
}

namespace {

// Split one line into tokens: whitespace separated, double quotes group, a '#'
// at the start of a token starts a comment. A quoted value runs to the next double
// quote: there is no escape, and '#' inside it is literal (0.5 rulings 6 and 17).
bool tokenize(const std::string& line, std::vector<std::string>& out, std::string& err) {
    std::size_t i = 0;
    while (i < line.size()) {
        char c = line[i];
        if (c == ' ' || c == '\t' || c == '\r') {
            ++i;
            continue;
        }
        if (c == '#') break;
        std::string tok;
        if (c == '"') {
            ++i;
            bool closed = false;
            while (i < line.size()) {
                char d = line[i++];
                if (d == '"') {
                    closed = true;
                    break;
                }
                tok += d;
            }
            if (!closed) {
                err = "unterminated quoted argument";
                return false;
            }
        } else {
            // '#' inside a token is literal (locators such as path/#text).
            while (i < line.size() && line[i] != ' ' && line[i] != '\t' && line[i] != '\r') {
                if (line[i] == '"') {
                    err = "quote inside an unquoted argument";
                    return false;
                }
                tok += line[i++];
            }
        }
        out.push_back(std::move(tok));
    }
    return true;
}

bool parse_u32(const std::string& s, std::uint32_t& out) {
    if (s.empty()) return false;
    std::uint64_t v = 0;
    for (char c : s) {
        if (c < '0' || c > '9') return false;
        v = v * 10 + static_cast<std::uint64_t>(c - '0');
        if (v > 0xFFFFFFFFull) return false;
    }
    out = static_cast<std::uint32_t>(v);
    return true;
}

bool parse_distribution(const std::string& s, Distribution& out) {
    if (s == "public") out = Distribution::Public;
    else if (s == "controlled") out = Distribution::Controlled;
    else return false;
    return true;
}

}  // namespace

namespace {
// Model module grammar (engine-spec.md v0.4): same line rules as pack.def.
// A `derive` line is checked as a line here, while the file is read (its
// function, parameter and argument count: 0.6 ruling 9); its keys and types
// are checked after the other checks of the module (0.8 ruling 29), by
// detail::check_derives.
Module parse_model_impl(const std::string& text, const std::string& origin) {
    // 0.11 ruling 5b: the line checks of every line; then, as the file is read
    // again, every other cause of a module line (key type, `.` in a key name,
    // duplicate-key, a derive function or parameter); then missing-module,
    // missing-version; then missing-distribution, missing-source.
    detail::check_module_lines(text, origin);
    Module m;
    m.origin = origin;
    bool have_module = false, have_version = false, have_distribution = false;
    std::size_t lineno = 0, pos = 0;

    while (pos <= text.size()) {
        std::size_t nl = text.find('\n', pos);
        std::string line = text.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
        pos = nl == std::string::npos ? text.size() + 1 : nl + 1;
        ++lineno;

        const std::string where = origin + ":" + std::to_string(lineno);
        std::vector<std::string> t;
        std::string err;
        if (!tokenize(line, t, err)) throw Error(detail::tokenize_kind(err), "", "", where + ": " + err);
        if (t.empty()) continue;

        const std::string& kw = t[0];
        auto arity = [&](std::size_t n) {
            if (t.size() != n + 1)
                throw Error(ErrorKind::BadDirective, "", "",
                            where + ": '" + kw + "' takes " + std::to_string(n) + " argument(s), got " +
                                std::to_string(t.size() - 1));
        };
        auto once = [&](bool& seen) {
            if (seen) throw Error(ErrorKind::BadDirective, "", "", where + ": duplicate '" + kw + "'");
            seen = true;
        };

        if (kw == "module") {
            arity(1);
            once(have_module);
            m.name = t[1];
        } else if (kw == "version") {
            arity(1);
            once(have_version);
            m.version = t[1];
        } else if (kw == "distribution") {
            arity(1);
            once(have_distribution);
            if (!parse_distribution(t[1], m.distribution))
                throw Error(ErrorKind::BadDirective, "", "", where + ": distribution '" + t[1] + "'");
        } else if (kw == "source") {
            arity(1);
            m.sources.push_back(t[1]);
        } else if (kw == "uses") {
            // v0.8: a module may name other modules; a repeated line is accepted.
            arity(1);
            if (std::find(m.uses.begin(), m.uses.end(), t[1]) == m.uses.end()) m.uses.push_back(t[1]);
        } else if (kw == "key") {
            if (t.size() != 4 && t.size() != 5)
                throw Error(ErrorKind::BadDirective, "", "",
                            where + ": 'key' takes 3 or 4 argument(s), got " + std::to_string(t.size() - 1));
            ModelKey k;
            k.name = t[1];
            if (k.name.empty() || k.name.find('.') != std::string::npos)
                throw Error(ErrorKind::BadDirective, "", "", where + ": key name '" + k.name + "' contains '.'");
            if (t[2] == "string") k.type = KeyType::String;
            else if (t[2] == "float") k.type = KeyType::Float;
            else if (t[2] == "int") k.type = KeyType::Int;
            else throw Error(ErrorKind::BadDirective, "", "", where + ": key type '" + t[2] + "'");
            k.unit = t[3];
            if (t.size() == 5) k.meaning = t[4];
            if (m.list_index.count(k.name) || !m.index.emplace(k.name, m.keys.size()).second)
                throw Error(ErrorKind::DuplicateKey, "", "",
                            where + ": key '" + k.name + "' appears twice in module '" + m.name + "'");
            m.keys.push_back(std::move(k));
        } else if (kw == "list") {
            // v0.7: a list is named like a key and shares the key namespace of its module.
            if (t.size() != 2 && t.size() != 3)
                throw Error(ErrorKind::BadDirective, "", "",
                            where + ": 'list' takes 1 or 2 argument(s), got " + std::to_string(t.size() - 1));
            ModelList l;
            l.name = t[1];
            if (l.name.empty() || l.name.find('.') != std::string::npos)
                throw Error(ErrorKind::BadDirective, "", "", where + ": list name '" + l.name + "' contains '.'");
            if (t.size() == 3) l.meaning = t[2];
            if (m.index.count(l.name) || !m.list_index.emplace(l.name, m.lists.size()).second)
                throw Error(ErrorKind::DuplicateKey, "", "",
                            where + ": name '" + l.name + "' appears twice in module '" + m.name + "'");
            m.lists.push_back(std::move(l));
        } else if (kw == "derive") {
            DeriveLine d = detail::parse_derive(t, where);
            d.line = lineno;
            m.derives.push_back(std::move(d));
        } else {
            throw Error(ErrorKind::UnknownDirective, "", "", where + ": directive '" + kw + "'");
        }
    }

    if (!have_module || m.name.empty()) throw Error(ErrorKind::MissingModule, "", "", origin + ": missing 'module'");
    if (!have_version) throw Error(ErrorKind::MissingVersion, "", "", origin + ": the module has no 'version' line");
    if (!have_distribution) throw Error(ErrorKind::MissingDistribution, "", "", origin + ": module has no 'distribution'");
    if (m.sources.empty()) throw Error(ErrorKind::MissingSource, "", "", origin + ": module has no 'source'");
    if (m.name.find('.') != std::string::npos)
        throw Error(ErrorKind::BadDirective, "", "", origin + ": module name '" + m.name + "' contains '.'");
    return m;
}
}  // namespace

// With no engine there are no loaded modules: a `derive` line that names a key
// of `core` or of a used module is left for Engine::add_model.
Module parse_model(const std::string& text, const std::string& origin) {
    Module m = parse_model_impl(text, origin);
    detail::check_derives(m, nullptr, false);
    return m;
}

Module detail::parse_model_unchecked(const std::string& text, const std::string& origin) {
    return parse_model_impl(text, origin);
}

namespace {

bool parse_u64(const std::string& s, std::uint64_t& out) {
    if (s.empty()) return false;
    std::uint64_t v = 0;
    for (char c : s) {
        if (c < '0' || c > '9') return false;
        const std::uint64_t d = static_cast<std::uint64_t>(c - '0');
        if (v > (~std::uint64_t{0} - d) / 10) return false;
        v = v * 10 + d;
    }
    out = v;
    return true;
}

const std::uint64_t kNoBit = ~std::uint64_t{0};

// Call `fn` on every group of a scope (a pack's common lines, a kind, or a group
// body) and on every group nested in one, outermost first.
template <class Scope, class Fn>
void each_group(Scope& scope, Fn&& fn) {
    for (auto& g : scope.groups) {
        fn(g);
        each_group(g, fn);
    }
}

// Call `fn(scope_fields, scope_consts, in_group)` on the common lines, every kind
// and every group body.
template <class P, class Fn>
void each_scope(P& p, Fn&& fn) {
    fn(p.fields, p.consts, false);
    each_group(p, [&](auto& g) { fn(g.fields, g.consts, true); });
    for (auto& k : p.kinds) {
        fn(k.fields, k.consts, false);
        each_group(k, [&](auto& g) { fn(g.fields, g.consts, true); });
    }
}

// Checks that need the wire and so run once the whole file is read: the bit
// lengths a bits transform allows and the value of every `when` (bad-directive).
void check_bits_field_len(const Pack& p, const FieldLine& f) {
    detail::BitsLocator loc;
    if (!detail::parse_bits_locator(f.locator, loc)) return;  // reported as invalid_locator later
    if (!detail::bits_len_allowed(f.transform, loc.len))
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    p.source + ":" + std::to_string(f.line) + ": transform '" + transform_name(f.transform) +
                        "' does not allow a length of " + std::to_string(loc.len) + " bits");
}

void resolve_when(const Pack& p, WhenLine& w, const std::string& word) {
    if (p.wire == Wire::Tlv || p.wire == Wire::Cbor) return;  // checked by detail::check_tlv_pack, check_cbor_pack
    const std::string where = p.source + ":" + std::to_string(w.line);
    if (p.wire == Wire::Bits) {
        detail::BitsLocator loc;
        if (!detail::parse_bits_locator(w.locator, loc)) return;  // invalid_locator later
        if (loc.len < 1 || loc.len > 64)
            throw Error(ErrorKind::BadDirective, p.format, w.locator,
                        where + ": a '" + word + "' covers 1 to 64 bits");
        if (word == "when") {
            // v0.20: a list of values and ranges.
            std::string why;
            if (!detail::parse_when_numbers(w.value, loc.len, w.ranges, why))
                throw Error(ErrorKind::BadDirective, p.format, w.locator, where + ": 'when' " + why);
            w.number = w.ranges.front().first;
            return;
        }
        if (!parse_u64(w.value, w.number))
            throw Error(ErrorKind::BadDirective, p.format, w.locator,
                        where + ": '" + word + "' value '" + w.value + "' is not an unsigned decimal integer");
        if (loc.len < 64 && (w.number >> loc.len) != 0)
            throw Error(ErrorKind::BadDirective, p.format, w.locator,
                        where + ": '" + word + "' value " + w.value + " does not fit " + std::to_string(loc.len) + " bits");
        return;
    }
    // `const <locator> present` is bad-directive; `=present` writes the text (0.6 ruling 3).
    if (w.value == "present" && word == "const")
        throw Error(ErrorKind::BadDirective, p.format, w.locator,
                    where + ": 'const' cannot write 'present'; write '=present' for the text");
    // v0.20 lists on xml, json, geojson and protobuf. The `text` wire (0.10)
    // keeps one literal value: 0.20 does not extend lists to it, and a comma
    // there is the default delimiter, which a `when` value may not hold.
    if (word == "when" && w.value != "present" && p.wire != Wire::Text) {
        std::vector<std::string> items;
        if (!detail::split_value_list(w.value, items))
            throw Error(ErrorKind::BadDirective, p.format, w.locator,
                        where + ": the 'when' value list '" + w.value + "' has an empty value");
        if (items.size() > 1 && std::find(items.begin(), items.end(), "present") != items.end())
            throw Error(ErrorKind::BadDirective, p.format, w.locator,
                        where + ": 'present' may not be combined with other values");
        if (p.wire == Wire::Protobuf) {
            std::string why;
            if (!detail::parse_when_numbers(w.value, 64, w.ranges, why))
                throw Error(ErrorKind::BadDirective, p.format, w.locator, where + ": 'when' " + why);
            w.number = w.ranges.front().first;
            return;
        }
        // Text wires: `..` is literal; a leading `=` is stripped from each value.
        for (auto& item : items) {
            if (!item.empty() && item[0] == '=') item.erase(0, 1);
            w.texts.push_back(item);
        }
        w.forced_string = !w.value.empty() && w.value[0] == '=';
        w.text = w.texts.front();
        return;
    }
    if (p.wire == Wire::Protobuf) {
        if (w.value == "present") w.present = true;
        else if (!parse_u64(w.value, w.number))
            throw Error(ErrorKind::BadDirective, p.format, w.locator,
                        where + ": '" + word + "' value '" + w.value + "' is not 'present' or an unsigned decimal integer");
    } else {
        if (w.value == "present") {
            w.present = true;
        } else if (!w.value.empty() && w.value[0] == '=') {
            w.forced_string = true;
            w.text = w.value.substr(1);
        } else {
            w.text = w.value;
        }
    }
}

// v0.15: a transform of this version on a wire it does not list (bad-directive).
void check_v015_wire(const Pack& p, const FieldLine& f) {
    // v0.18 ruling 11: iso8601_short on bits or protobuf.
    if (f.transform == Transform::Iso8601Short && (p.wire == Wire::Bits || p.wire == Wire::Protobuf))
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    p.source + ":" + std::to_string(f.line) + ": transform 'iso8601_short' is not valid on wire " +
                        wire_name(p.wire));
    if (!detail::transform_is_v015(f.transform)) return;
    const bool ok = detail::transform_is_text_scale(f.transform)
                        ? p.wire == Wire::Xml || p.wire == Wire::Json || p.wire == Wire::GeoJson
                        : p.wire == Wire::Bits;
    if (!ok)
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    p.source + ":" + std::to_string(f.line) + ": transform '" + transform_name(f.transform) +
                        "' is not valid on wire " + wire_name(p.wire));
}

// v0.6 field options: `via` names a table of the pack, and `swap`, `trim` and
// `optional` apply to the bits wire only (bad-directive).
void check_field_options(const Pack& p, const std::unordered_map<std::string, int>& tables, FieldLine& f) {
    const std::string where = p.source + ":" + std::to_string(f.line);
    if (!f.via.empty()) {
        auto it = tables.find(f.via);
        if (it == tables.end())
            throw Error(ErrorKind::BadDirective, p.format, f.locator,
                        where + ": 'via " + f.via + "' names a table with no 'map' line");
        f.table = it->second;
    }
    // v0.22: `stop` on a `chars` field, with a code its width holds (ruling 16).
    if (f.has_stop) {
        const unsigned w = detail::chars_width(f.transform);
        if (!w)
            throw Error(ErrorKind::BadDirective, p.format, f.locator,
                        where + ": option 'stop' applies to a 'chars' transform only");
        if (f.stop_code >> w)
            throw Error(ErrorKind::BadDirective, p.format, f.locator,
                        where + ": the 'stop' code " + std::to_string(f.stop_code) + " does not fit " +
                            std::to_string(w) + " bits");
    }
    if (!f.swap && !f.trim && !f.optional) return;
    // v0.10: `optional` on text marks a trailing field encode may remove.
    if (p.wire == Wire::Text && !f.swap && !f.trim) return;
    const char* option = f.swap ? "swap" : f.trim ? "trim" : "optional";
    if (p.wire != Wire::Bits)
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    where + ": option '" + option + "' applies to wire bits only");
    if (f.trim && f.transform != Transform::Ascii && f.transform != Transform::Sixbit)
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    where + ": option 'trim' applies to transforms ascii and sixbit only");
    if (f.swap && (f.transform == Transform::Sixbit || detail::chars_width(f.transform) || f.transform == Transform::Octal ||
                   f.transform == Transform::Hex))
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    where + ": option 'swap' does not apply to transform " + transform_name(f.transform));
    detail::BitsLocator loc;
    if (f.swap && detail::parse_bits_locator(f.locator, loc) && loc.len % 8 != 0)
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    where + ": option 'swap' needs a length that is a multiple of 8 bits, not " +
                        std::to_string(loc.len));
}

// The form of a `group` line on the pack's wire (bad-directive): `item` and
// `count` belong to the bits wire, which requires both.
void settle_group(const Pack& p, GroupLine& g) {
    const std::string where = p.source + ":" + std::to_string(g.line);
    g.scalar = false;
    for (const auto& f : g.fields)
        if (f.locator == ".") g.scalar = true;
    // A protobuf group body is scalar only when every line is `.` (0.7 ruling 13).
    if (p.wire == Wire::Protobuf && g.scalar) {
        bool mixed = !g.consts.empty() || !g.groups.empty();
        for (const auto& f : g.fields)
            if (f.locator != ".") mixed = true;
        if (mixed)
            throw Error(ErrorKind::BadDirective, p.format, g.locator,
                        where + ": the body of the group '" + g.list + "' mixes '.' with paths");
        // 0.18 rulings 4 and 17: an item of the packed form cannot be left out.
        // A group is packed when every `.` field of its body is numeric.
        bool packed = true, with = false;
        for (const auto& f : g.fields) {
            packed = packed && (f.transform == Transform::Pvarint || f.transform == Transform::Psint ||
                                f.transform == Transform::Pdouble || f.transform == Transform::Pfloat);
            with = with || !f.with.empty();
        }
        if (packed && with)
                throw Error(ErrorKind::BadDirective, p.format, g.locator,
                            where + ": 'with' on the '.' field of a packed group '" + g.list + "'");
    }
    if (p.wire == Wire::Tlv)
        throw Error(ErrorKind::BadDirective, p.format, g.locator, where + ": 'group' on wire tlv is not defined in 0.13");
    if (p.wire == Wire::Text) {
        // v0.10: `group <list> <i> item <n>`; `count` is not allowed.
        if (g.has_count)
            throw Error(ErrorKind::BadDirective, p.format, g.locator,
                        where + ": 'count' is not allowed on a group of wire text");
        if (!g.has_item || !parse_u32(g.item_text, g.text_item) || g.text_item == 0)
            throw Error(ErrorKind::BadDirective, p.format, g.locator,
                        where + ": a group on wire text takes 'item <n>', n from 1");
        return;
    }
    if (p.wire != Wire::Bits) {
        if (g.has_count)
            throw Error(ErrorKind::BadDirective, p.format, g.locator,
                        where + ": 'count' applies to a group on wire bits only");
        if (g.has_item)
            throw Error(ErrorKind::BadDirective, p.format, g.locator,
                        where + ": 'item' applies to a group on wire bits only");
        return;
    }
    if (!g.has_item || !g.has_count)
        throw Error(ErrorKind::BadDirective, p.format, g.locator,
                    where + ": a group on wire bits takes 'item <bits>' and 'count <count-locator | n>'");
    if (!parse_u32(g.item_text, g.item_bits) || g.item_bits == 0)
        throw Error(ErrorKind::BadDirective, p.format, g.locator,
                    where + ": 'item " + g.item_text + "' is not a positive number of bits");
    if (g.count_text.find(':') != std::string::npos) {
        detail::BitsLocator loc;
        if (!detail::parse_bits_locator(g.count_text, loc) || loc.len < 1 || loc.len > 64)
            throw Error(ErrorKind::BadDirective, p.format, g.locator,
                        where + ": 'count " + g.count_text + "' is not a <word>:<pos>:<len> of 1 to 64 bits");
        g.count_fixed = false;
        g.count_locator = g.count_text;
        g.count_start = static_cast<std::uint64_t>(loc.word) * p.word_bytes * 8 + loc.pos;
        g.count_len = loc.len;
    } else {
        if (!parse_u64(g.count_text, g.count_n))
            throw Error(ErrorKind::BadDirective, p.format, g.locator,
                        where + ": 'count " + g.count_text + "' is not a count locator or an unsigned integer");
        g.count_fixed = true;
    }
    std::uint32_t word = 0, pos = 0;
    // An invalid group locator is reported as invalid_locator later.
    g.bits_start = detail::parse_bits_group_locator(g.locator, word, pos)
                       ? static_cast<std::uint64_t>(word) * p.word_bytes * 8 + pos
                       : kNoBit;
}

// ---- bits: where a group may stand (bad-directive)

// The bits one scope's own lines cover: the furthest end of a `field`, `when`
// or `const`, and where its groups start.
struct BitsExtent {
    std::uint64_t line_end = 0;             // furthest end of a field, when or const
    const std::string* line_locator = nullptr;
    std::size_t line_no = 0;
    std::uint64_t group_start_max = 0;      // furthest start of a group
    bool has_group = false;
    std::uint64_t counted_start = kNoBit;   // nearest start of a group counted by a locator
    const GroupLine* counted = nullptr;
};

std::uint64_t bits_end(const Pack& p, const std::string& locator) {
    detail::BitsLocator loc;
    if (!detail::parse_bits_locator(locator, loc)) return 0;  // invalid_locator later
    return static_cast<std::uint64_t>(loc.word) * p.word_bytes * 8 + loc.pos + loc.len;
}

[[noreturn]] void bad_beyond(const Pack& p, const std::string& what, const std::string& locator, std::size_t line,
                             const GroupLine& g) {
    throw Error(ErrorKind::BadDirective, p.format, locator,
                p.source + ":" + std::to_string(line) + ": " + what + " lies at or beyond the start of the group '" +
                    g.list + "', which is counted by a locator and so is the last thing in its scope");
}

// The gate blocks of a scope (0.17).
const std::vector<int>& scope_gates(const Pack&, const Pack& scope) { return scope.common_gates; }
const std::vector<int>& scope_gates(const Pack&, const Kind& scope) { return scope.gates; }
const std::vector<int>& scope_gates(const Pack&, const GroupLine& scope) { return scope.gates; }

std::uint64_t gate_end(const Pack& p, int id) {
    const GateBlock& b = p.gates[static_cast<std::size_t>(id)];
    return b.start + b.len;
}

// A gate any of whose bits lies within the items of a fixed-count group of its
// scope (0.17 ruling 9) is bad-directive.
void check_gates_vs_fixed(const Pack& p, const std::vector<int>& gates, const std::vector<GroupLine>& groups) {
    for (int id : gates) {
        const GateBlock& b = p.gates[static_cast<std::size_t>(id)];
        for (const auto& o : groups) {
            if (!o.count_fixed || o.bits_start == kNoBit) continue;
            const std::uint64_t end = o.bits_start + o.count_n * o.item_bits;
            if (b.start < end && b.start + b.len > o.bits_start)
                throw Error(ErrorKind::BadDirective, p.format, b.locator,
                            p.source + ":" + std::to_string(b.line) + ": the gate " + b.locator +
                                " lies within the items of the group '" + o.list + "'");
        }
    }
}

// One scope's lines against the counted group `g` (of the same scope, or of the
// common lines when the scope is a kind).
template <class Scope>
void check_against_counted(const Pack& p, const Scope& scope, const std::vector<WhenLine>* whens, const GroupLine& g) {
    for (int id : scope_gates(p, scope))
        if (gate_end(p, id) > g.bits_start)
            bad_beyond(p, "the gate", p.gates[static_cast<std::size_t>(id)].locator,
                       p.gates[static_cast<std::size_t>(id)].line, g);
    for (const auto& f : scope.fields)
        if (bits_end(p, f.locator) > g.bits_start) bad_beyond(p, "the field", f.locator, f.line, g);
    for (const auto& c : scope.consts)
        if (bits_end(p, c.locator) > g.bits_start) bad_beyond(p, "the const", c.locator, c.line, g);
    if (whens)
        for (const auto& w : *whens)
            if (bits_end(p, w.locator) > g.bits_start) bad_beyond(p, "the when", w.locator, w.line, g);
    for (const auto& o : scope.groups) {
        if (&o == &g || o.bits_start == kNoBit) continue;
        if (o.bits_start >= g.bits_start) bad_beyond(p, "the group '" + o.list + "'", o.locator, o.line, g);
        // A fixed-count group that starts before it and whose items reach its start (0.7 ruling 16).
        if (o.count_fixed && o.count_n > (g.bits_start - o.bits_start) / o.item_bits)
            bad_beyond(p, "an item of the group '" + o.list + "'", o.locator, o.line, g);
    }
}

template <class Scope>
BitsExtent bits_extent(const Pack& p, const Scope& scope, const std::vector<WhenLine>* whens) {
    BitsExtent x;
    auto line = [&](const std::string& locator, std::size_t no) {
        const std::uint64_t end = bits_end(p, locator);
        if (end > x.line_end) {
            x.line_end = end;
            x.line_locator = &locator;
            x.line_no = no;
        }
    };
    for (const auto& f : scope.fields) line(f.locator, f.line);
    for (const auto& c : scope.consts) line(c.locator, c.line);
    if (whens)
        for (const auto& w : *whens) line(w.locator, w.line);
    for (int id : scope_gates(p, scope)) {
        const GateBlock& b = p.gates[static_cast<std::size_t>(id)];
        if (b.start + b.len > x.line_end) {
            x.line_end = b.start + b.len;
            x.line_locator = &b.locator;
            x.line_no = b.line;
        }
    }
    for (const auto& g : scope.groups) {
        if (g.bits_start == kNoBit) continue;
        x.has_group = true;
        x.group_start_max = std::max(x.group_start_max, g.bits_start);
        if (!g.count_fixed && g.bits_start < x.counted_start) {
            x.counted_start = g.bits_start;
            x.counted = &g;
        }
    }
    return x;
}

// A group body on the bits wire: what must lie within `item <bits>` (0.7 ruling
// 4), its own counted group (the last thing in the item), and the bodies nested
// in it.
void check_bits_group(const Pack& p, const GroupLine& g) {
    const std::string where = p.source + ":" + std::to_string(g.line);
    // A count locator that reaches the group's start (0.7 ruling 2).
    if (!g.count_fixed && g.bits_start != kNoBit && g.count_start + g.count_len > g.bits_start)
        throw Error(ErrorKind::BadDirective, p.format, g.locator,
                    where + ": the count locator " + g.count_locator + " reaches the start of the group");
    for (const auto& f : g.fields)
        if (bits_end(p, f.locator) > g.item_bits)
            throw Error(ErrorKind::BadDirective, p.format, f.locator,
                        p.source + ":" + std::to_string(f.line) + ": the field reaches beyond 'item " +
                            std::to_string(g.item_bits) + "'");
    for (int id : g.gates)
        if (gate_end(p, id) > g.item_bits)
            throw Error(ErrorKind::BadDirective, p.format, p.gates[static_cast<std::size_t>(id)].locator,
                        p.source + ":" + std::to_string(p.gates[static_cast<std::size_t>(id)].line) +
                            ": the gate reaches beyond 'item " + std::to_string(g.item_bits) +
                            "': a bit outside the item cannot gate a field of every item");
    check_gates_vs_fixed(p, g.gates, g.groups);
    for (const auto& c : g.consts)
        if (bits_end(p, c.locator) > g.item_bits)
            throw Error(ErrorKind::BadDirective, p.format, c.locator,
                        p.source + ":" + std::to_string(c.line) + ": the const reaches beyond 'item " +
                            std::to_string(g.item_bits) + "'");
    for (const auto& n : g.groups) {
        // A nested group's count locator is bounded by `item <bits>` as a field is (0.7 ruling 15).
        if (!n.count_fixed && n.count_start + n.count_len > g.item_bits)
            throw Error(ErrorKind::BadDirective, p.format, n.locator,
                        p.source + ":" + std::to_string(n.line) + ": the count locator " + n.count_locator +
                            " of the group '" + n.list + "' reaches beyond 'item " + std::to_string(g.item_bits) + "'");
        if (!n.count_fixed || n.bits_start == kNoBit) continue;
        const std::uint64_t room = g.item_bits > n.bits_start ? (g.item_bits - n.bits_start) / n.item_bits : 0;
        if (n.bits_start > g.item_bits || n.count_n > room)
            throw Error(ErrorKind::BadDirective, p.format, n.locator,
                        p.source + ":" + std::to_string(n.line) + ": the group '" + n.list +
                            "' with a fixed count reaches beyond 'item " + std::to_string(g.item_bits) + "'");
    }
    const BitsExtent x = bits_extent(p, g, nullptr);
    if (x.counted) check_against_counted(p, g, nullptr, *x.counted);
    for (const auto& n : g.groups) check_bits_group(p, n);
}

void check_bits_groups(const Pack& p) {
    // The common lines alone, then the common lines plus each kind. Each kind
    // costs its own lines only: the common lines enter through their extent.
    const BitsExtent common = bits_extent(p, p, &p.whens);
    if (common.counted) check_against_counted(p, p, &p.whens, *common.counted);
    check_gates_vs_fixed(p, p.common_gates, p.groups);
    for (const auto& g : p.groups) check_bits_group(p, g);
    for (const auto& k : p.kinds) {
        check_gates_vs_fixed(p, k.gates, p.groups);
        check_gates_vs_fixed(p, k.gates, k.groups);
        check_gates_vs_fixed(p, p.common_gates, k.groups);
        const BitsExtent own = bits_extent(p, k, &k.whens);
        if (common.counted) check_against_counted(p, k, &k.whens, *common.counted);
        if (own.counted) {
            check_against_counted(p, k, &k.whens, *own.counted);
            if (common.line_end > own.counted_start)
                bad_beyond(p, "a common line", *common.line_locator, common.line_no, *own.counted);
            if (common.has_group && common.group_start_max >= own.counted_start)
                bad_beyond(p, "a common group", own.counted->locator, own.counted->line, *own.counted);
        }
        for (const auto& g : k.groups) check_bits_group(p, g);
    }
}

// Within one scope (common plus one kind, or one group body) a list is mapped
// by at most one `group` (bad-directive).
void check_lists_once(const Pack& p, const std::vector<GroupLine>& groups, const std::set<std::string>* outer,
                      std::set<std::string>* names_out) {
    std::set<std::string> names;
    for (const auto& g : groups) {
        if ((outer && outer->count(g.list)) || !names.insert(g.list).second)
            throw Error(ErrorKind::BadDirective, p.format, g.locator,
                        p.source + ":" + std::to_string(g.line) + ": the list '" + g.list +
                            "' is mapped by two groups of one scope");
        check_lists_once(p, g.groups, nullptr, nullptr);
    }
    if (names_out) *names_out = std::move(names);
}

// ---- a `field` whose locator passes through a `group`'s path (0.7 ruling 21)

// Does the field locator address something at or under an item of the group?
bool passes_through(Wire wire, const std::string& field, const std::string& group) {
    char sep;
    switch (wire) {
        case Wire::Xml: sep = '/'; break;
        case Wire::Json:
        case Wire::Protobuf: sep = '.'; break;
        default: return false;
    }
    return field.size() > group.size() && field[group.size()] == sep && field.compare(0, group.size(), group) == 0;
}

void check_through(const Pack& p, Wire wire, const std::vector<FieldLine>& fields, const std::vector<GroupLine>& groups) {
    if (groups.empty()) return;
    for (const auto& f : fields)
        for (const auto& g : groups)
            if (passes_through(wire, f.locator, g.locator))
                throw Error(ErrorKind::BadDirective, p.format, f.locator,
                            p.source + ":" + std::to_string(f.line) + ": the field's locator passes through the path '" +
                                g.locator + "' of the group '" + g.list + "'");
}

// The body of every group: its own fields against its own groups. Inside a
// group a geojson pack uses the json locators.
void check_through_groups(const Pack& p, const std::vector<GroupLine>& groups) {
    const Wire inner = p.wire == Wire::GeoJson ? Wire::Json : p.wire;
    for (const auto& g : groups) {
        check_through(p, inner, g.fields, g.groups);
        check_through_groups(p, g.groups);
    }
}

// A scope is the common lines plus one kind, or one group body. Applies to
// `field` lines only (0.8 ruling 15).
void check_fields_through_groups(const Pack& p) {
    check_through(p, p.wire, p.fields, p.groups);
    check_through_groups(p, p.groups);
    for (const auto& k : p.kinds) {
        check_through(p, p.wire, k.fields, p.groups);
        check_through(p, p.wire, k.fields, k.groups);
        check_through(p, p.wire, p.fields, k.groups);
        check_through_groups(p, k.groups);
    }
}

// ---- locators and transforms against the wire (invalid_pack, invalid_locator)

// The wire whose locator grammar the lines of a scope follow: inside a group a
// geojson pack uses the json locators.
Wire locator_wire(const Pack& p, bool in_group) {
    return in_group && p.wire == Wire::GeoJson ? Wire::Json : p.wire;
}

bool scalar_item_wire(Wire w) { return w == Wire::Json || w == Wire::GeoJson || w == Wire::Protobuf; }

void check_field(const Pack& p, const FieldLine& f, bool in_group) {
    if (p.wire == Wire::Text || p.wire == Wire::Tlv || p.wire == Wire::Cbor) return;  // checked by detail::check_text_pack
    const bool is_bits = detail::transform_is_bits(f.transform);
    const bool is_pb = detail::transform_is_protobuf(f.transform);
    bool matches;
    if (p.wire == Wire::Protobuf) matches = is_pb;
    else if (p.wire == Wire::Bits) matches = is_bits;
    else if (f.transform == Transform::CodeNum) matches = true;  // v0.46: bits and the text wires
    else matches = !is_bits && !is_pb && (f.transform != Transform::Bool || p.wire == Wire::Json);
    if (!matches)
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    p.source + ": transform '" + std::string(transform_name(f.transform)) +
                        "' is not valid on wire " + wire_name(p.wire));
    if (in_group && f.locator == "." && scalar_item_wire(p.wire)) return;  // the item itself, a scalar
    if (!detail::valid_locator(locator_wire(p, in_group), f.locator))
        throw Error(ErrorKind::BadLocator, p.format, f.locator,
                    p.source + ": not a " + wire_name(p.wire) + " field locator");
}

void check_when(const Pack& p, const WhenLine& w, bool in_group) {
    if (p.wire == Wire::Text || p.wire == Wire::Tlv || p.wire == Wire::Cbor) return;  // checked by detail::check_text_pack, check_tlv_pack
    // `.` is the item itself: outside a group it is bad-directive, as earlier
    // versions state, not bad-locator (0.11 ruling 5a).
    if (w.locator == "." && scalar_item_wire(p.wire))
        throw Error(ErrorKind::BadDirective, p.format, w.locator,
                    p.source + ":" + std::to_string(w.line) + ": the locator '.' outside a group");
    // A UPER locator outside a UPER pack, here a fixed-layout one (0.19 rulings 9 and 24).
    if (p.wire == Wire::Bits &&
        (w.locator.compare(0, 4, "int:") == 0 || w.locator.compare(0, 5, "enum:") == 0 ||
         w.locator.compare(0, 6, "chars:") == 0 || w.locator.compare(0, 7, "octets:") == 0))
        throw Error(ErrorKind::BadDirective, p.format, w.locator,
                    p.source + ":" + std::to_string(w.line) + ": the locator '" + w.locator +
                        "' needs 'encoding uper', and a 'when' or 'const' takes a bit length");
    const Wire wire = locator_wire(p, in_group);
    bool ok = detail::valid_locator(wire, w.locator);
    if (ok && wire == Wire::GeoJson) {
        detail::GeoLocator g;
        detail::parse_geo_locator(w.locator, g);
        ok = g.kind == detail::GeoLocator::Kind::Property || g.kind == detail::GeoLocator::Kind::Member;
    }
    if (!ok)
        throw Error(ErrorKind::BadLocator, p.format, w.locator,
                    p.source + ": not a " + wire_name(p.wire) + " 'when' or 'const' locator");
}

void check_group_locators(const Pack& p, const GroupLine& g, bool in_group) {
    if (p.wire == Wire::Text || p.wire == Wire::Tlv || p.wire == Wire::Cbor) return;  // checked by detail::parse_text_locators
    const Wire wire = locator_wire(p, in_group);
    bool ok = false;
    switch (wire) {
        case Wire::Xml: {
            detail::XmlLocator x;
            ok = detail::parse_xml_locator(g.locator, x) && x.kind == detail::XmlLocator::Kind::Element;
            break;
        }
        case Wire::GeoJson: {
            detail::GeoLocator x;
            ok = detail::parse_geo_locator(g.locator, x) &&
                 (x.kind == detail::GeoLocator::Kind::Property || x.kind == detail::GeoLocator::Kind::Member);
            break;
        }
        case Wire::Bits: {
            std::uint32_t word = 0, pos = 0;
            ok = detail::parse_bits_group_locator(g.locator, word, pos);
            break;
        }
        case Wire::Json:
        case Wire::Protobuf: ok = detail::valid_locator(wire, g.locator); break;
        case Wire::Text:
        case Wire::Tlv:
        case Wire::Cbor: ok = true; break;
    }
    // A group whose locator is not one of its wire is a bad group line (0.21
    // ruling 8: `rest` is not a protobuf path).
    if (!ok)
        throw Error(ErrorKind::BadDirective, p.format, g.locator,
                    p.source + ":" + std::to_string(g.line) + ": not a " + wire_name(p.wire) + " group locator");
    for (const auto& f : g.fields) check_field(p, f, true);
    for (const auto& c : g.consts) check_when(p, c, true);
    for (const auto& n : g.groups) check_group_locators(p, n, true);
}

}  // namespace

// v0.18 ruling 12: an `element` whose path equals or passes through the item
// path of a group the same message may write.
void check_elements_vs_groups(const Pack& p) {
    auto check = [&](const std::vector<ElementLine>& els, const std::vector<GroupLine>& groups) {
        for (const auto& el : els)
            for (const auto& g : groups) {
                detail::XmlLocator loc;
                if (!detail::parse_xml_locator(g.locator, loc)) continue;  // reported elsewhere
                if (loc.path.empty() || loc.path.size() > el.steps.size()) continue;
                if (!std::equal(loc.path.begin(), loc.path.end(), el.steps.begin())) continue;
                throw Error(ErrorKind::BadDirective, p.format, el.path,
                            p.source + ":" + std::to_string(el.line) + ": 'element " + el.path +
                                "' equals or passes through the path of the group '" + g.list + "'");
            }
    };
    check(p.elements, p.groups);
    for (const auto& k : p.kinds) {
        check(p.elements, k.groups);
        check(k.elements, p.groups);
        check(k.elements, k.groups);
    }
}

namespace detail {

void add_charset(Pack& p, const std::vector<std::string>& t, std::size_t line, bool misplaced) {
    auto s = std::make_shared<CharSet>();
    s->name = t[1];
    s->chars = t[2];
    s->has_width = t.size() > 3;
    if (s->has_width) s->width_text = t[3];
    s->misplaced = misplaced;
    s->line = line;
    p.charsets.push_back(std::move(s));
}

void check_charsets(Pack& p) {
    std::set<std::string> names;
    for (const auto& sp : p.charsets) {
        CharSet& s = *sp;
        auto bad = [&](const std::string& why) {
            throw Error(ErrorKind::BadDirective, p.format, "",
                        p.source + ":" + std::to_string(s.line) + ": charset '" + s.name + "': " + why);
        };
        if (s.misplaced) bad("it stands in a block or after the first 'kind'");
        if (s.name.empty() || s.name.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                                                       "0123456789_-") != std::string::npos)
            bad("a name is one or more of A-Z, a-z, 0-9, '_' and '-'");
        if (!names.insert(s.name).second) bad("a second charset of one name");
        if (s.chars.empty()) bad("no characters");
        for (std::size_t k = 0; k < s.chars.size(); ++k) {
            const unsigned char c = static_cast<unsigned char>(s.chars[k]);
            if (c < 0x21 || c > 0x7E) bad("a character outside 0x21 to 0x7E");
            if (s.chars.find(s.chars[k]) != k) bad(std::string("the character '") + s.chars[k] + "' appears twice");
        }
        unsigned least = 1;
        while ((std::size_t{1} << least) < s.chars.size()) ++least;
        s.width = least;
        if (p.wire != Wire::Bits || !s.has_width) continue;  // ignored off bits (ruling 14)
        std::uint64_t w = 0;
        if (!parse_u64(s.width_text, w) || w < least || w > 8)
            bad("the width '" + s.width_text + "' is not a decimal integer from " + std::to_string(least) + " to 8");
        s.width = static_cast<unsigned>(w);
    }
}

void resolve_code_sets(const Pack& p, FieldLine& f, const std::uint32_t* bits_len) {
    if (!transform_is_code(f.transform)) return;
    auto bad = [&](const std::string& why) {
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    p.source + ":" + std::to_string(f.line) + ": transform '" + transform_name(f.transform) + ":" +
                        f.code_list + "' " + why);
    };
    const bool text_wire =
        p.wire == Wire::Xml || p.wire == Wire::Json || p.wire == Wire::GeoJson || p.wire == Wire::Text;
    const bool fits = f.transform == Transform::Code      ? p.wire == Wire::Bits
                      : f.transform == Transform::CodeStr ? text_wire
                                                          : text_wire || p.wire == Wire::Bits;
    if (!fits) bad(std::string("is not valid on wire ") + wire_name(p.wire));
    if (f.code_list.empty()) bad("names no position");
    f.code_sets.clear();
    std::size_t from = 0;
    for (;;) {
        const std::size_t comma = f.code_list.find(',', from);
        const std::string name =
            f.code_list.substr(from, comma == std::string::npos ? std::string::npos : comma - from);
        const std::shared_ptr<CharSet>* found = nullptr;
        for (const auto& s : p.charsets)
            if (s->name == name) found = &s;
        if (!found) bad("names the set '" + name + "', which no 'charset' declares");
        f.code_sets.push_back(*found);
        if (comma == std::string::npos) break;
        from = comma + 1;
    }
    if (f.code_sets.size() > 16) bad("names more than 16 positions");
    std::uint64_t width = 0, product = 1;
    const std::uint64_t most = std::uint64_t{1} << 63;
    for (const auto& s : f.code_sets) {
        width += s->width;
        if (f.transform == Transform::CodeNum) {
            if (product > most / s->chars.size()) bad("has more than 2^63 values");
            product *= s->chars.size();
        }
        if (p.wire != Wire::Text) continue;
        // Characters the record cannot carry (ruling 12).
        if (!p.delimiter_none && s->chars.find(p.delimiter) != std::string::npos)
            bad("uses the set '" + s->name + "', which holds the delimiter");
        if (p.checksum_nmea && s->chars.find('*') != std::string::npos)
            bad("uses the set '" + s->name + "', which holds '*' under 'checksum nmea'");
    }
    if (p.wire == Wire::Bits && bits_len && (*bits_len != width || width > 64))
        bad("covers " + std::to_string(width) + " bits, and its field has " + std::to_string(*bits_len) +
            " (at most 64)");
}

}  // namespace detail

Pack parse_pack(const std::string& text, const std::string& source) {
    // 0.11 ruling 5b: the line checks of every line, then missing-format,
    // missing-version and missing-wire, before any other check of the file.
    detail::check_pack_lines(text, source);
    // v0.8: a pack with `layout sequential` is lines read from a cursor.
    if (detail::is_sequential_pack(text)) return detail::parse_seq_pack(text, source);
    Pack p;
    p.source = source;
    std::size_t layout_line = 0;
    bool have_format = false, have_version = false, have_wire = false, have_root = false,
         have_word_bytes = false, have_distribution = false, have_bit_order = false;
    std::set<std::string> kind_names, natives;
    std::unordered_map<std::string, int> table_index;  // table name -> position in p.tables
    std::size_t lineno = 0, pos = 0, bit_order_line = 0, kind_root_line = 0;
    std::size_t delimiter_line = 0, start_line = 0, checksum_line = 0, text_directive_line = 0;
    // v0.13: `tag`, `length`, `key` and `checksum sum16 <tag>`, the first line of any of them.
    std::size_t tag_line = 0, length_line = 0, key_line = 0, tlv_directive_line = 0;
    // v0.28: the value of the `tag` line, and whether it is none of the tlv forms.
    std::string tag_text;
    bool tag_deferred = false;
    // A field transform on wire tlv that did not parse (0.13 ruling 8), raised after the file.
    bool pending_transform = false;
    // v0.14: `armor <hex | sixbit>`. The first error of its lines waits for the
    // end of the file (ruling 10 of 0.10), as do the checks against the wire.
    std::size_t armor_line = 0;
    std::string armor_error;
    std::size_t inner_line = 0;  // v0.34: the first `inner` line
    // v0.19: `encoding`, checked after the file is read: `encoding uper` needs
    // `layout sequential`, and `ext`, `choice` and `alt` lines are UPER lines,
    // bad-directive on any wire (rulings 9 and 21).
    std::size_t encoding_line = 0, uper_line = 0;
    std::string encoding_error, uper_kw;
    std::string pending_locator, pending_detail;
    // v0.30: the first `when ... as` line, refused after the file (ruling 16).
    std::string as_error;
    // The groups that are open at this line, outermost first. A group stays the
    // last element of its scope while it is open, so the pointers hold.
    std::vector<GroupLine*> open;
    // v0.17: the gate blocks open at this line, innermost last, each with the
    // number of groups open when it began. A gate holds no group, so the
    // innermost block is a gate when its depth is the current one.
    std::vector<std::pair<int, std::size_t>> gate_open;
    std::size_t first_gate_line = 0;
    // The first 0.17 error of a gate line or of a line inside a block, raised
    // after the file is read (0.17 ruling 13).
    std::string gate_error, gate_error_locator;
    std::size_t first_element_line = 0;  // v0.18
    auto cur_gate = [&]() -> int {
        return !gate_open.empty() && gate_open.back().second == open.size() ? gate_open.back().first : -1;
    };

    auto cur_fields = [&]() -> std::vector<FieldLine>& {
        return !open.empty() ? open.back()->fields : p.kinds.empty() ? p.fields : p.kinds.back().fields;
    };
    auto cur_consts = [&]() -> std::vector<WhenLine>& {
        return !open.empty() ? open.back()->consts : p.kinds.empty() ? p.consts : p.kinds.back().consts;
    };
    auto cur_defaults = [&]() -> std::vector<DefaultLine>& {
        return !open.empty() ? open.back()->defaults : p.kinds.empty() ? p.defaults : p.kinds.back().defaults;
    };
    auto cur_groups = [&]() -> std::vector<GroupLine>& {
        return !open.empty() ? open.back()->groups : p.kinds.empty() ? p.groups : p.kinds.back().groups;
    };

    while (pos <= text.size()) {
        std::size_t nl = text.find('\n', pos);
        std::string line = text.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
        pos = nl == std::string::npos ? text.size() + 1 : nl + 1;
        ++lineno;

        std::vector<std::string> t;
        std::string err;
        if (!tokenize(line, t, err))
            throw Error(detail::tokenize_kind(err), p.format, "", source + ":" + std::to_string(lineno) + ": " + err);
        if (t.empty()) continue;

        const std::string where = source + ":" + std::to_string(lineno);
        const std::string& kw = t[0];
        auto arity = [&](std::size_t n) {
            if (t.size() != n + 1)
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": '" + kw + "' takes " + std::to_string(n) + " argument(s), got " +
                                std::to_string(t.size() - 1));
        };
        auto once = [&](bool& seen) {
            if (seen) throw Error(ErrorKind::BadDirective, p.format, "", where + ": duplicate '" + kw + "'");
            seen = true;
        };
        // `when`, `requires`, `root`, `kind`, `map` and `typemap` are not allowed in a group.
        auto not_in_group = [&]() {
            if (!open.empty())
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": '" + kw + "' is not allowed inside a group");
        };

        // v0.46: its errors, its place among them, are found after the file is read.
        if (kw == "charset") {
            detail::add_charset(p, t, lineno, !open.empty() || !gate_open.empty() || !p.kinds.empty());
            continue;
        }

        // Inside a gate block only `field`, `const`, `default`, a nested `if` and
        // `end` are allowed (0.17).
        // Found after the file is read (0.17 ruling 13).
        if (cur_gate() >= 0 && kw != "field" && kw != "const" && kw != "default" && kw != "if" && kw != "end" &&
            gate_error.empty()) {
            gate_error = where + ": '" + kw + "' is not allowed inside a gate block";
            gate_error_locator.clear();
        }
        // Inside a group only `field`, `const`, `default`, `group`, a gate block
        // and `end` are allowed (0.7 ruling 18, 0.17).
        if (!open.empty() && kw != "field" && kw != "const" && kw != "default" && kw != "group" && kw != "end" &&
            kw != "if")
            not_in_group();

        if (kw == "format") {
            arity(1);
            once(have_format);
            p.format = t[1];
        } else if (kw == "version") {
            arity(1);
            once(have_version);
            p.version = t[1];
        } else if (kw == "distribution") {
            arity(1);
            once(have_distribution);
            if (!parse_distribution(t[1], p.distribution))
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": distribution '" + t[1] + "'");
        } else if (kw == "source") {
            arity(1);
            p.sources.push_back(t[1]);
        } else if (kw == "uses") {
            arity(1);
            if (std::find(p.uses.begin(), p.uses.end(), t[1]) == p.uses.end()) p.uses.push_back(t[1]);
        } else if (kw == "wire") {
            arity(1);
            once(have_wire);
            std::string why;
            if (!detail::parse_wire_value(t[1], p.wire, why))
                throw Error(ErrorKind::UnknownWire, p.format, "", where + ": " + why);
        } else if (kw == "root") {
            not_in_group();
            arity(1);
            if (p.kinds.empty()) {
                once(have_root);
                p.root = t[1];
            } else {
                // v0.6: a root per kind (xml only; checked once the wire is known).
                if (!p.kinds.back().root.empty())
                    throw Error(ErrorKind::BadDirective, p.format, "",
                                where + ": duplicate 'root' in kind '" + p.kinds.back().name + "'");
                if (t[1].empty()) throw Error(ErrorKind::BadDirective, p.format, "", where + ": empty 'root'");
                p.kinds.back().root = t[1];
                if (kind_root_line == 0) kind_root_line = lineno;
            }
        } else if (kw == "word_bytes") {
            arity(1);
            once(have_word_bytes);
            if (!parse_u32(t[1], p.word_bytes) || p.word_bytes == 0)
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": word_bytes must be a positive integer");
        } else if (kw == "layout") {
            // v0.8: `layout fixed` is the default, the addressing of Version 0.2.
            arity(1);
            if (t[1] != "fixed")
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": layout '" + t[1] + "' is not fixed or sequential");
            if (layout_line == 0) layout_line = lineno;
        } else if (kw == "if") {
            // v0.17: `if [!]<word>:<pos>:<len> <value>[,<value>...]`, one locator and
            // one value list. An `if` with no argument is a line error; every
            // other error of the line is found after the file is read (0.17
            // ruling 13, 0.11 ruling 5b), so the block is kept for its `end`.
            if (t.size() < 2)
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": a gate 'if' takes a locator and a value list");
            GateBlock gb;
            gb.line = lineno;
            gb.locator = t[1];
            if (!gb.locator.empty() && gb.locator[0] == '!') {
                gb.negated = true;
                gb.locator.erase(0, 1);
            }
            auto defer = [&](const std::string& what) {
                if (gate_error.empty()) {
                    gate_error = where + ": " + what;
                    gate_error_locator = t[1];
                }
            };
            detail::BitsLocator loc;
            if (t.size() != 3) {
                defer("a gate 'if' takes one locator and one value list, got " + std::to_string(t.size() - 1) +
                      " argument(s)");
            } else if (!detail::parse_bits_locator(gb.locator, loc)) {
                defer("'" + t[1] + "' is not a gate locator [!]<word>:<pos>:<len> of a fixed layout");
            } else if (loc.len < 1 || loc.len > 64) {
                defer("a gate covers 1 to 64 bits");
            } else {
                gb.len = loc.len;
                std::size_t from = 0;
                const std::string& list = t[2];
                while (true) {
                    const std::size_t comma = list.find(',', from);
                    const std::string v = list.substr(from, comma == std::string::npos ? std::string::npos : comma - from);
                    std::uint64_t n = 0;
                    if (!parse_u64(v, n)) {
                        defer("gate value '" + v + "' is not an unsigned decimal integer");
                        break;
                    }
                    if (loc.len < 64 && (n >> loc.len) != 0) {
                        defer("gate value " + v + " does not fit " + std::to_string(loc.len) + " bits");
                        break;
                    }
                    if (std::find(gb.values.begin(), gb.values.end(), n) != gb.values.end()) {
                        defer("gate value " + v + " is listed twice");
                        break;
                    }
                    gb.values.push_back(n);
                    if (comma == std::string::npos) break;
                    from = comma + 1;
                }
            }
            gb.parent = cur_gate();
            const int id = static_cast<int>(p.gates.size());
            p.gates.push_back(std::move(gb));
            (!open.empty() ? open.back()->gates : p.kinds.empty() ? p.common_gates : p.kinds.back().gates).push_back(id);
            gate_open.emplace_back(id, open.size());
            if (first_gate_line == 0) first_gate_line = lineno;
        } else if (kw == "pad" || kw == "align" || kw == "presence" || kw == "opt" || kw == "chain" ||
                   kw == "fx" || kw == "also") {
            throw Error(ErrorKind::BadDirective, p.format, "",
                        where + ": '" + kw + "' is a line of a sequential layout, and the pack's layout is fixed");
        } else if (kw == "tag" || kw == "length" || kw == "key" ||
                   (kw == "checksum" && t.size() == 3 && (t[1] == "sum16" || t[1] == "crc32"))) {
            // v0.13: each once, before the first `kind`, with a value of its own;
            // on another wire bad-directive once the file is read. A `length`
            // that is not one of these forms is the block of a sequential
            // layout (0.8), which a fixed layout does not have.
            auto bad = [&](const std::string& why) {
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": " + why);
            };
            const bool is_checksum = kw == "checksum";
            if (!is_checksum && t.size() != 2) {
                if (kw == "length")
                    bad("'length' with a block is a line of a sequential layout, and 'length' on wire tlv "
                        "takes one value: ber, 1, 2 or 4");
                bad("'" + kw + "' takes one value");
            }
            const std::string& v = t[1];
            if (kw == "tag") {
                // v0.28: `tag <n>` on cbor. Its value is checked against the
                // wire once the file is read, when the wire is not known yet.
                tag_text = v;
                if (v == "ber-oid") p.tlv_tag_bytes = 0;
                else if (v == "1" || v == "2" || v == "4") p.tlv_tag_bytes = static_cast<std::uint32_t>(v[0] - '0');
                else if (!have_wire || p.wire == Wire::Cbor) tag_deferred = true;
                else bad("'tag' is ber-oid, 1, 2 or 4, not '" + v + "'");
            } else if (kw == "length") {
                if (v == "ber") p.tlv_length_bytes = 0;
                else if (v == "1" || v == "2" || v == "4") p.tlv_length_bytes = static_cast<std::uint32_t>(v[0] - '0');
                else bad("'length' on wire tlv is ber, 1, 2 or 4, not '" + v + "'");
            } else if (kw == "key") {
                bool ok = !v.empty() && v.size() % 2 == 0 && v.size() <= 128;
                for (char c : v) ok = ok && ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'));
                if (!ok) bad("'key' is 1 to 64 bytes as an even number of lowercase hex digits, not '" + v + "'");
                p.tlv_has_key = true;
                p.tlv_key.clear();
                for (std::size_t k = 0; k < v.size(); k += 2) {
                    auto nib = [](char c) { return c <= '9' ? c - '0' : c - 'a' + 10; };
                    p.tlv_key += static_cast<char>((nib(v[k]) << 4) | nib(v[k + 1]));
                }
            } else {
                if (!detail::parse_tlv_tag(t[2], p.tlv_checksum_tag))
                    bad("'checksum " + t[1] +
                        "' takes a tag, a decimal integer from 0 to 2^28-1 with no leading zero, not '" + t[2] + "'");
                p.tlv_checksum = true;
                p.tlv_checksum_crc32 = t[1] == "crc32";  // v0.27
            }
            if (!p.kinds.empty()) bad("'" + kw + "' after the first 'kind'");
            std::size_t& seen = kw == "tag" ? tag_line : kw == "length" ? length_line : kw == "key" ? key_line : checksum_line;
            if (seen != 0) bad("'" + kw + "' appears twice");
            seen = lineno;
            if (kw != "tag" && tlv_directive_line == 0) tlv_directive_line = lineno;
        } else if (kw == "delimiter" || kw == "start" || kw == "checksum") {
            // v0.10: each once, before the first `kind`, with a value of its own;
            // on another wire bad-directive once the file is read.
            auto bad = [&](const std::string& why) {
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": " + why);
            };
            if (t.size() != 2) bad("'" + kw + "' takes one value");
            if (!p.kinds.empty()) bad("'" + kw + "' after the first 'kind'");
            std::size_t& seen = kw == "delimiter" ? delimiter_line : kw == "start" ? start_line : checksum_line;
            if (seen != 0) bad("'" + kw + "' appears twice");
            seen = lineno;
            if (text_directive_line == 0) text_directive_line = lineno;
            const std::string& v = t[1];
            if (kw == "delimiter") {
                if (v == "none") {
                    p.delimiter_none = true;
                } else {
                    if (v.size() != 1 || v[0] < 0x21 || v[0] > 0x7E || v[0] == '"')
                        bad("'delimiter' takes one character from 0x21 to 0x7E other than '\"', or 'none'");
                    p.delimiter = v[0];
                }
            } else if (kw == "start") {
                if (v.empty()) bad("'start' takes one or more characters");
                for (char c : v)
                    if (c < 0x21 || c > 0x7E) bad("'start' takes characters from 0x21 to 0x7E");
                p.start = v;
            } else {
                if (v == "nmea") p.checksum_nmea = true;
                else if (v != "none") bad("'checksum' is none or nmea, not '" + v + "'");
            }
        } else if (kw == "armor") {
            std::string why;
            if (t.size() != 2) why = "'armor' takes one value: hex or sixbit";
            else if (t[1] != "hex" && t[1] != "sixbit") why = "'armor' is hex or sixbit, not '" + t[1] + "'";
            else if (armor_line != 0) why = "'armor' appears twice";
            else if (!p.kinds.empty()) why = "'armor' after the first 'kind'";
            if (!why.empty()) {
                if (armor_error.empty()) armor_error = where + ": " + why;
            } else {
                p.armor_sixbit = t[1] == "sixbit";
            }
            if (armor_line == 0) armor_line = lineno;
        } else if (kw == "encoding") {
            std::string why;
            if (t.size() != 2) why = "'encoding' takes one value: none or uper";
            else if (t[1] != "none" && t[1] != "uper") why = "'encoding' is none or uper, not '" + t[1] + "'";
            else if (encoding_line != 0) why = "'encoding' appears twice";
            else if (!p.kinds.empty()) why = "'encoding' after the first 'kind'";
            else if (t[1] == "uper") why = "'encoding uper' needs 'layout sequential'";
            if (!why.empty() && encoding_error.empty()) encoding_error = where + ": " + why;
            if (encoding_line == 0) encoding_line = lineno;
        } else if (kw == "framing") {
            // v0.92 ruling 16: a line of a `layout sequential` `bits` pack.
            throw Error(ErrorKind::BadDirective, p.format, "", where + ": 'framing' needs 'layout sequential'");
        } else if (kw == "ext" || kw == "choice" || kw == "alt") {
            // Outside a UPER pack, on any wire (ruling 21 of 0.19).
            if (uper_line == 0) {
                uper_line = lineno;
                uper_kw = kw;
            }
        } else if (kw == "bit_order") {
            arity(1);
            once(have_bit_order);
            bit_order_line = lineno;
            if (t[1] == "lsb") p.bit_order = BitOrder::Lsb;
            else if (t[1] == "msb") p.bit_order = BitOrder::Msb;
            else if (t[1] == "msb-lsb") p.bit_order = BitOrder::MsbLsb;  // v0.22
            else throw Error(ErrorKind::BadDirective, p.format, "", where + ": bit_order '" + t[1] + "' is not lsb, msb or msb-lsb");
        } else if (kw == "kind") {
            not_in_group();
            arity(1);
            if (!kind_names.insert(t[1]).second)
                throw Error(ErrorKind::DuplicateKind, p.format, "", where + ": kind '" + t[1] + "' is declared twice");
            p.kinds.emplace_back();
            p.kinds.back().name = t[1];
        } else if (kw == "group") {
            // v0.7: `group <list> <locator> [item <bits>] [count <count-locator> | count <n>]`.
            if (t.size() < 3)
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": 'group' takes a list and a locator, got " + std::to_string(t.size() - 1) +
                                " argument(s)");
            GroupLine g;
            g.list = t[1];
            g.locator = t[2];
            g.line = lineno;
            for (std::size_t k = 3; k < t.size(); k += 2) {
                bool* seen = t[k] == "item" ? &g.has_item : t[k] == "count" ? &g.has_count : nullptr;
                if (!seen || *seen || k + 1 >= t.size())
                    throw Error(ErrorKind::BadDirective, p.format, g.locator,
                                where + ": after its locator a 'group' takes 'item <bits>' and 'count <count-locator | n>', "
                                        "each once; got '" + t[k] + "'");
                *seen = true;
                (t[k] == "item" ? g.item_text : g.count_text) = t[k + 1];
            }
            std::vector<GroupLine>& groups = cur_groups();
            groups.push_back(std::move(g));
            open.push_back(&groups.back());
        } else if (kw == "end") {
            if (cur_gate() >= 0) {
                arity(0);
                gate_open.pop_back();
                continue;
            }
            if (open.empty())
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": 'end' with no open group");
            arity(0);
            open.pop_back();
        } else if (kw == "const") {
            if (t.size() > 3 && t[3] == "with")
                throw Error(ErrorKind::BadDirective, p.format, t[1], where + ": 'with' applies to a 'field' line only");
            arity(2);
            WhenLine w;
            w.locator = t[1];
            w.value = t[2];
            w.line = lineno;
            w.gate = cur_gate();
            cur_consts().push_back(std::move(w));
        } else if (kw == "default") {
            arity(2);
            DefaultLine d;
            d.key = t[1];
            d.text = t[2];
            d.line = lineno;
            d.gate = cur_gate();
            cur_defaults().push_back(std::move(d));
        } else if (kw == "element") {
            // v0.18: `element <path>`, common or in a kind (ruling 12: not in a group).
            not_in_group();
            if (t.size() != 2)
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": 'element' takes one path, got " + std::to_string(t.size() - 1) + " argument(s)");
            ElementLine el;
            el.path = t[1];
            el.line = lineno;
            if (first_element_line == 0) first_element_line = lineno;
            std::size_t st = 0;
            for (;;) {
                const std::size_t slash = el.path.find('/', st);
                el.steps.push_back(el.path.substr(st, slash == std::string::npos ? std::string::npos : slash - st));
                if (slash == std::string::npos) break;
                st = slash + 1;
            }
            for (const auto& s : el.steps)
                if (s.empty() || s.find_first_of("@#") != std::string::npos)  // rulings 13 and 16
                    throw Error(ErrorKind::BadDirective, p.format, el.path,
                                where + ": 'element " + el.path +
                                    "' is not a path of element names (an empty step, '@' or '#text')");
            (p.kinds.empty() ? p.elements : p.kinds.back().elements).push_back(std::move(el));
        } else if (kw == "map") {
            not_in_group();  // tables are pack-wide and are written outside groups (0.7 ruling 9)
            arity(3);
            auto it = table_index.find(t[1]);
            if (it == table_index.end()) {
                it = table_index.emplace(t[1], static_cast<int>(p.tables.size())).first;
                p.tables.emplace_back();
                p.tables.back().name = t[1];
            }
            p.tables[static_cast<std::size_t>(it->second)].entries.emplace_back(t[2], t[3]);
        } else if (kw == "when") {
            not_in_group();
            // v0.30: `as` belongs to `layout sequential`; refused after the file (ruling 16).
            if (t.size() > 3 && t[3] == "as" && !detail::when_holds_at(t)) {  // 0.52 ruling 17
                if (as_error.empty()) as_error = where + ": 'when ... as' applies to 'layout sequential' only";
            } else if (t.size() > 3 && (t[3] == "at" || t[3] == "as")) {
                // v0.33: raised with the other `at` errors, after the module checks.
                if (p.at_error.empty()) p.at_error = where + ": 'when ... at' applies to 'layout sequential' only";
            } else {
                // A third token (`1, 2`) is not a value list (0.20).
                if (t.size() > 3)
                    throw Error(ErrorKind::BadDirective, p.format, "",
                                where + ": 'when' takes a locator and one value list; a list has no spaces");
                arity(2);
            }
            WhenLine w;
            w.locator = t[1];
            w.value = t[2];
            w.line = lineno;
            if (p.kinds.empty()) p.whens.push_back(std::move(w));
            else p.kinds.back().whens.push_back(std::move(w));
        } else if (kw == "requires") {
            not_in_group();
            if (p.kinds.empty())
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": 'requires' before the first 'kind'");
            if (t.size() < 2)
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": 'requires' takes at least 1 argument");
            for (std::size_t k = 1; k < t.size(); ++k) {
                RequiresTerm term;
                std::string why;
                if (!detail::parse_requires_term(t[k], lineno, term, why))
                    throw Error(ErrorKind::BadDirective, p.format, "", where + ": " + why);
                p.kinds.back().requires_keys.push_back(term.key);
                p.kinds.back().requires_terms.push_back(std::move(term));
            }
        } else if (kw == "field") {
            if (t.size() < 4)
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": 'field' takes a key, a locator and a transform, got " +
                                std::to_string(t.size() - 1) + " argument(s)");
            FieldLine f;
            f.key = t[1];
            f.locator = t[2];
            f.line = lineno;
            std::string terr;
            const int tf = detail::parse_any_transform(t[3], f, terr);
            // 0.28 rulings 25 and 34: on cbor, as on tlv, a transform that does not
            // parse (name or parameters) is bad-directive after the file.
            if (tf != 0 && (p.wire == Wire::Tlv || p.wire == Wire::Cbor)) {
                // Ruling 8 of 0.13: on tlv a transform that does not parse, by
                // its name or its parameters, is bad-directive, checked after
                // the file is read (the line check of 0.11 ruling 5b step 7
                // leaves it). The `wire` line stands before every `field` (5b).
                if (!pending_transform) {
                    pending_transform = true;
                    pending_locator = f.locator;
                    pending_detail = where + ": " + terr + " for field '" + f.key + "'";
                }
                f.transform = Transform::Utf8;  // a placeholder; the pending error is raised first
            } else if (tf == -2) {
                throw Error(ErrorKind::UnknownTransform, p.format, f.locator,
                            where + ": " + terr + " for field '" + f.key + "'");
            } else if (tf == -1) {
                throw Error(ErrorKind::BadDirective, p.format, f.locator, where + ": " + terr + " for field '" + f.key + "'");
            }
            // v0.6 options after the transform, in any order.
            for (std::size_t k = 4; k < t.size(); ++k) {
                bool* flag = nullptr;
                if (t[k] == "via") {
                    if (k + 1 >= t.size() || t[k + 1].empty() || !f.via.empty())
                        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                    where + ": 'via' takes one table name, once");
                    f.via = t[++k];
                    continue;
                }
                // v0.9: `absent <value>[,<value>...]`; the next token is always its argument.
                if (t[k] == "absent") {
                    if (k + 1 >= t.size() || f.has_absent)
                        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                    where + ": 'absent' takes one argument, once");
                    f.has_absent = true;
                    f.absent_arg = t[++k];
                    continue;
                }
                // v0.18: `with <other-key>`, once.
                if (t[k] == "with") {
                    if (k + 1 >= t.size() || t[k + 1].empty() || !f.with.empty())
                        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                    where + ": 'with' takes one key, once");
                    f.with = t[++k];
                    continue;
                }
                // v0.22: `stop <code>`, once; whether it fits the transform is
                // checked with the other field options.
                if (t[k] == "stop") {
                    if (k + 1 >= t.size() || f.has_stop || !detail::parse_term_code(t[k + 1], f.stop_code))
                        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                    where + ": 'stop' takes one code of plain decimal digits, once");
                    f.has_stop = true;
                    ++k;
                    continue;
                }
                if (t[k] == "swap") flag = &f.swap;
                else if (t[k] == "trim") flag = &f.trim;
                else if (t[k] == "optional") flag = &f.optional;
                if (!flag || *flag)
                    throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                where + ": '" + t[k] + "' is not a field option, or is given twice");
                *flag = true;
            }
            // A model key may be mapped by several lines (0.6: `duplicate-field` is withdrawn).
            f.gate = cur_gate();
            cur_fields().push_back(std::move(f));
        } else if (kw == "typemap") {
            not_in_group();
            arity(2);
            if (!natives.insert(t[1]).second)
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": duplicate typemap code '" + t[1] + "'");
            p.typemap.emplace_back(t[1], t[2]);
        } else if (kw == "inner") {
            // v0.34: a line of a `layout sequential` bits pack, refused after the file is read.
            if (inner_line == 0) inner_line = lineno;
        } else if (kw == "count") {
            // v0.21: a count line belongs to a sequential layout.
            throw Error(ErrorKind::BadDirective, p.format, "",
                        where + ": 'count' is a line of a 'layout sequential' pack");
        } else if (kw == "switch" || kw == "case" || kw == "else") {
            // v0.20: a switch belongs to a sequential layout.
            throw Error(ErrorKind::BadDirective, p.format, "",
                        where + ": '" + kw + "' is a line of a 'layout sequential' pack");
        } else {
            throw Error(ErrorKind::UnknownDirective, p.format, "", where + ": directive '" + kw + "'");
        }
    }

    // Line errors that need the whole file: a block left open, where a directive
    // is allowed, and what a `when` value and a bits length may be.
    if (!as_error.empty()) throw Error(ErrorKind::BadDirective, p.format, "", as_error);
    if (pending_transform)  // set on wire tlv (0.13 ruling 8) and cbor (0.28 ruling 25) only
        throw Error(ErrorKind::BadDirective, p.format, pending_locator,
                    pending_detail + " (on wire " + wire_name(p.wire) + ", a transform not in the wire's table)");
    detail::check_charsets(p);
    each_scope(p, [&](std::vector<FieldLine>& fields, std::vector<WhenLine>&, bool in_group) {
        for (auto& f : fields) {
            // 0.46 ruling 23: a coordinate; inside a group the locator is a member path.
            if (p.wire == Wire::GeoJson && !in_group && detail::transform_is_code(f.transform) &&
                f.locator.compare(0, 9, "geometry.") == 0)
                throw Error(ErrorKind::BadDirective, p.format, f.locator,
                            source + ":" + std::to_string(f.line) + ": transform '" + transform_name(f.transform) +
                                "' does not apply to a geojson coordinate");
            detail::BitsLocator loc;
            const bool has_len = p.wire == Wire::Bits && detail::parse_bits_locator(f.locator, loc);
            detail::resolve_code_sets(p, f, has_len ? &loc.len : nullptr);
        }
    });
    if (!gate_error.empty()) throw Error(ErrorKind::BadDirective, p.format, gate_error_locator, gate_error);
    if (!gate_open.empty()) {
        const GateBlock& g = p.gates[static_cast<std::size_t>(gate_open.back().first)];
        throw Error(ErrorKind::BadDirective, p.format, g.locator,
                    source + ":" + std::to_string(g.line) + ": the gate 'if " + g.locator + "' has no 'end'");
    }
    if (first_gate_line != 0 && have_wire && p.wire != Wire::Bits)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(first_gate_line) + ": a gate block applies to wire bits only");
    if (!open.empty())
        throw Error(ErrorKind::BadDirective, p.format, open.back()->locator,
                    source + ":" + std::to_string(open.back()->line) + ": the group '" + open.back()->list +
                        "' has no 'end'");
    if (inner_line != 0)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(inner_line) +
                        ": 'inner' is a line of a 'layout sequential' pack on wire bits");
    if (encoding_line != 0 && have_wire && p.wire != Wire::Bits)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(encoding_line) + ": 'encoding' applies to wire bits only");
    if (!encoding_error.empty()) throw Error(ErrorKind::BadDirective, p.format, "", encoding_error);
    if (uper_line != 0) {
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(uper_line) + ": '" + uper_kw + "' needs 'encoding uper'");
    }
    if (!armor_error.empty()) throw Error(ErrorKind::BadDirective, p.format, "", armor_error);
    if (armor_line != 0 && have_wire && p.wire != Wire::Bits)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(armor_line) + ": 'armor' applies to wire bits only");
    if (p.armor_sixbit && p.bit_order != BitOrder::Msb)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(armor_line) + ": 'armor sixbit' needs 'bit_order msb'");
    if (first_element_line != 0 && have_wire && p.wire != Wire::Xml)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(first_element_line) + ": 'element' applies to wire xml only");
    if (have_wire && p.wire == Wire::Xml) check_elements_vs_groups(p);
    if (have_bit_order && have_wire && p.wire != Wire::Bits)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(bit_order_line) + ": 'bit_order' applies to wire bits only");
    if (layout_line != 0 && have_wire && p.wire != Wire::Bits)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(layout_line) + ": 'layout' applies to wire bits only");
    if (p.kinds.empty() && !p.whens.empty())
        throw Error(ErrorKind::BadDirective, p.format, p.whens.front().locator,
                    source + ":" + std::to_string(p.whens.front().line) + ": 'when' in a pack with no 'kind' line");
    // A list is mapped once in common plus one kind, and once in a group body.
    {
        std::set<std::string> common;
        check_lists_once(p, p.groups, nullptr, &common);
        for (const auto& k : p.kinds) check_lists_once(p, k.groups, &common, nullptr);
    }
    if (have_wire) {
        // v0.10: the text wire's locators, read before the checks that relate them.
#if GT_WIRE_TEXT
        if (p.wire == Wire::Text) detail::parse_text_locators(p);
#endif
        if (p.wire != Wire::Text) {
            if (text_directive_line != 0)
                throw Error(ErrorKind::BadDirective, p.format, "",
                            source + ":" + std::to_string(text_directive_line) +
                                ": 'delimiter', 'start' and 'checksum' apply to wire text only");
            each_scope(p, [&](std::vector<FieldLine>& fields, std::vector<WhenLine>&, bool) {
                for (const auto& f : fields)
                    if (detail::transform_is_text_only(f.transform))
                        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                    source + ":" + std::to_string(f.line) + ": transform '" +
                                        transform_name(f.transform) + "' applies to wire text only");
            });
        }
        // v0.13: `tag`, `length`, `key` and `checksum sum16` belong to the tlv
        // wire, and `utf8` and `hex` are valid on it only.
        // v0.28: `tag <n>` is a directive of cbor, and `tag` of tlv (ruling 5).
        if (tag_line != 0) {
            const std::string where = source + ":" + std::to_string(tag_line);
            if (p.wire == Wire::Cbor) {
#if GT_WIRE_CBOR  // without the cbor wire a cbor pack stops at its `wire` line (0.28 ruling 38)
                if (!detail::parse_cbor_tag(tag_text, p.cbor_tag_value))
                    throw Error(ErrorKind::BadDirective, p.format, "",
                                where + ": 'tag' on wire cbor is a decimal integer from 0 to 2^64-1 with no leading "
                                        "zero, not '" + tag_text + "'");
#endif
                p.cbor_tag = true;
            } else if (p.wire != Wire::Tlv) {
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": 'tag' applies to wire tlv and wire cbor only");
            } else if (tag_deferred) {
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": 'tag' is ber-oid, 1, 2 or 4, not '" + tag_text + "'");
            }
        }
        if (p.wire != Wire::Cbor)
            each_scope(p, [&](std::vector<FieldLine>& fields, std::vector<WhenLine>&, bool) {
                for (const auto& f : fields)
                    if (detail::transform_is_cbor_only(f.transform))
                        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                    source + ":" + std::to_string(f.line) + ": transform '" +
                                        transform_name(f.transform) + "' applies to wire cbor only");
            });
        if (p.wire != Wire::Tlv) {
            if (tlv_directive_line != 0)
                throw Error(ErrorKind::BadDirective, p.format, "",
                            source + ":" + std::to_string(tlv_directive_line) +
                                ": 'tag', 'length', 'key', 'checksum sum16' and 'checksum crc32' apply to wire tlv only");
            each_scope(p, [&](std::vector<FieldLine>& fields, std::vector<WhenLine>&, bool) {
                for (const auto& f : fields)
                    if (detail::transform_is_tlv_only(f.transform))
                        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                    source + ":" + std::to_string(f.line) + ": transform '" +
                                        transform_name(f.transform) + "' applies to wire tlv only");
            });
        }
        // v0.22: `hex` is a transform of the bits and tlv wires.
        if (p.wire != Wire::Bits && p.wire != Wire::Tlv)
            each_scope(p, [&](std::vector<FieldLine>& fields, std::vector<WhenLine>&, bool) {
                for (const auto& f : fields)
                    if (f.transform == Transform::Hex)
                        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                    source + ":" + std::to_string(f.line) + ": transform 'hex' applies to wires bits and tlv only");
            });
        // v0.14: `sixbit` is a transform of the bits wire only.
        if (p.wire != Wire::Bits)
            each_scope(p, [&](std::vector<FieldLine>& fields, std::vector<WhenLine>&, bool) {
                for (const auto& f : fields)
                    if (f.transform == Transform::Sixbit)
                        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                    source + ":" + std::to_string(f.line) + ": transform 'sixbit' applies to wire bits only");
            });
        if (kind_root_line != 0 && p.wire != Wire::Xml)
            throw Error(ErrorKind::BadDirective, p.format, "",
                        source + ":" + std::to_string(kind_root_line) + ": 'root' in a kind applies to wire xml only");
        each_scope(p, [&](std::vector<FieldLine>& fields, std::vector<WhenLine>& consts, bool in_group) {
            for (auto& f : fields) {
                // `.` is the item itself and has no meaning outside a group.
                if (!in_group && f.locator == "." && scalar_item_wire(p.wire))
                    throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                source + ":" + std::to_string(f.line) + ": the locator '.' outside a group");
                // A UPER locator outside a UPER pack (0.19 ruling 9).
                if (p.wire == Wire::Bits &&
                    (f.locator.compare(0, 4, "int:") == 0 || f.locator.compare(0, 5, "enum:") == 0 ||
                     f.locator.compare(0, 6, "chars:") == 0 || f.locator.compare(0, 7, "octets:") == 0))
                    throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                source + ":" + std::to_string(f.line) + ": the locator '" + f.locator +
                                    "' needs 'encoding uper'");
                // A bit length for a locator is a line of a sequential layout (0.8),
                // and so is `until:<code>` (0.22).
                if (p.wire == Wire::Bits && !f.locator.empty() &&
                    (f.locator.find_first_not_of("0123456789") == std::string::npos ||
                     f.locator.compare(0, 6, "until:") == 0))
                    throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                source + ":" + std::to_string(f.line) +
                                    ": a field with a bit length for a locator is a line of a sequential layout");
                check_v015_wire(p, f);
                if (p.wire == Wire::Bits && detail::transform_is_bits(f.transform)) check_bits_field_len(p, f);
                check_field_options(p, table_index, f);
                if (f.has_absent) {
                    detail::BitsLocator loc;
                    std::uint32_t len = 0;
                    if (p.wire == Wire::Bits && detail::parse_bits_locator(f.locator, loc)) len = loc.len;
                    const bool coordinate =
                        p.wire == Wire::GeoJson && !in_group && f.locator.compare(0, 9, "geometry.") == 0;
                    detail::resolve_absent(p, p.wire, f, len, coordinate);
                }
            }
            for (auto& w : consts) {
                if (w.locator == "." && scalar_item_wire(p.wire))
                    throw Error(ErrorKind::BadDirective, p.format, w.locator,
                                source + ":" + std::to_string(w.line) + ": a 'const' cannot name the locator '.'");
                resolve_when(p, w, "const");
            }
        });
        for (auto& w : p.whens) resolve_when(p, w, "when");
        for (auto& k : p.kinds)
            for (auto& w : k.whens) resolve_when(p, w, "when");
        each_group(p, [&](GroupLine& g) { settle_group(p, g); });
        for (auto& k : p.kinds) each_group(k, [&](GroupLine& g) { settle_group(p, g); });
        if (p.wire == Wire::Bits) {
            for (auto& g : p.gates) {
                detail::BitsLocator loc;
                detail::parse_bits_locator(g.locator, loc);
                g.start = static_cast<std::uint64_t>(loc.word) * p.word_bytes * 8 + loc.pos;
            }
            check_bits_groups(p);
        }
        // A wire this build lacks never gets here: its `wire` line is unknown-wire (0.24).
#if GT_WIRE_TEXT
        if (p.wire == Wire::Text) detail::check_text_pack(p);
#endif
#if GT_WIRE_TLV
        if (p.wire == Wire::Tlv) detail::check_tlv_pack(p);
#endif
#if GT_WIRE_CBOR
        if (p.wire == Wire::Cbor) detail::check_cbor_pack(p);
#endif
        check_fields_through_groups(p);
    }

    // The checks that need the whole file come before the order of 0.4 (0.11
    // ruling 5b): the load-time missing-root, the missing `word_bytes`, a
    // directive of another wire, and a transform or locator on its wire.
    if (!have_format || p.format.empty()) throw Error(ErrorKind::MissingFormat, "", "", source + ": missing 'format'");
    if (!have_wire) throw Error(ErrorKind::MissingWire, p.format, "", source + ": missing 'wire'");
    if (p.wire == Wire::Xml && !have_root) {
        // A pack whose every kind has a `root` needs no pack-level `root` (0.6).
        bool every_kind = !p.kinds.empty();
        for (const auto& k : p.kinds) every_kind = every_kind && !k.root.empty();
        if (!every_kind) throw Error(ErrorKind::MissingRoot, p.format, "", source + ": wire xml requires 'root'");
    }
    if (p.wire != Wire::Xml && have_root)
        throw Error(ErrorKind::BadDirective, p.format, "", source + ": 'root' applies to wire xml only");
    if (p.wire == Wire::Bits && !have_word_bytes)
        throw Error(ErrorKind::BadDirective, p.format, "", source + ": wire bits requires 'word_bytes'");
    if (p.wire != Wire::Bits && have_word_bytes)
        throw Error(ErrorKind::BadDirective, p.format, "", source + ": 'word_bytes' applies to wire bits only");
    for (const auto& f : p.fields) check_field(p, f, false);
    for (const auto& w : p.whens) check_when(p, w, false);
    for (const auto& w : p.consts) check_when(p, w, false);
    for (const auto& g : p.groups) check_group_locators(p, g, false);
    for (const auto& k : p.kinds) {
        for (const auto& f : k.fields) check_field(p, f, false);
        for (const auto& w : k.whens) check_when(p, w, false);
        for (const auto& w : k.consts) check_when(p, w, false);
        for (const auto& g : k.groups) check_group_locators(p, g, false);
    }

    if (!have_distribution)
        throw Error(ErrorKind::MissingDistribution, p.format, "", source + ": pack has no 'distribution'");
    if (p.sources.empty()) throw Error(ErrorKind::MissingSource, p.format, "", source + ": pack has no 'source'");

    return p;
}

}  // namespace goat_transformers
