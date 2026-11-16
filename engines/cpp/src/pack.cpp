// pack.def and model module parsing (engine-spec.md, Pack definition grammar;
// v0.2 bits wire; v0.4 model modules and distribution).
#include <algorithm>
#include <cstdint>
#include <set>
#include <unordered_map>

#include "codecs.hpp"
#include "derive.hpp"
#include "sequential.hpp"
#include "goat_transformers/engine.hpp"
#include "transforms.hpp"

namespace goat_transformers {

const char* error_kind_name(ErrorKind kind) {
    switch (kind) {
        case ErrorKind::UnknownDirective: return "unknown_directive";
        case ErrorKind::UnknownTransform: return "unknown_transform";
        case ErrorKind::UnknownWire: return "unknown_wire";
        case ErrorKind::InvalidPack: return "invalid_pack";
        case ErrorKind::InvalidLocator: return "invalid_locator";
        case ErrorKind::UnknownFormat: return "unknown_format";
        case ErrorKind::MalformedWire: return "malformed-wire";
        case ErrorKind::MissingRoot: return "missing-root";
        case ErrorKind::TransformDecode: return "transform-decode";
        case ErrorKind::TransformEncode: return "transform-encode";
        case ErrorKind::Io: return "io";
        case ErrorKind::InvalidModel: return "invalid_model";
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
        case Transform::F64: return KeyType::Float;
        case Transform::Ascii: return KeyType::String;
        case Transform::Bool:
        case Transform::Int:
        case Transform::Iso8601Ms:
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
    }
    return "?";
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
        if (!tokenize(line, t, err)) throw Error(ErrorKind::InvalidModel, "", "", where + ": " + err);
        if (t.empty()) continue;

        const std::string& kw = t[0];
        auto arity = [&](std::size_t n) {
            if (t.size() != n + 1)
                throw Error(ErrorKind::InvalidModel, "", "",
                            where + ": '" + kw + "' takes " + std::to_string(n) + " argument(s), got " +
                                std::to_string(t.size() - 1));
        };
        auto once = [&](bool& seen) {
            if (seen) throw Error(ErrorKind::InvalidModel, "", "", where + ": duplicate '" + kw + "'");
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
                throw Error(ErrorKind::InvalidModel, "", "", where + ": distribution '" + t[1] + "'");
        } else if (kw == "source") {
            arity(1);
            m.sources.push_back(t[1]);
        } else if (kw == "uses") {
            // v0.8: a module may name other modules; a repeated line is accepted.
            arity(1);
            if (std::find(m.uses.begin(), m.uses.end(), t[1]) == m.uses.end()) m.uses.push_back(t[1]);
        } else if (kw == "key") {
            if (t.size() != 4 && t.size() != 5)
                throw Error(ErrorKind::InvalidModel, "", "",
                            where + ": 'key' takes 3 or 4 argument(s), got " + std::to_string(t.size() - 1));
            ModelKey k;
            k.name = t[1];
            if (k.name.empty() || k.name.find('.') != std::string::npos)
                throw Error(ErrorKind::InvalidModel, "", "", where + ": key name '" + k.name + "' contains '.'");
            if (t[2] == "string") k.type = KeyType::String;
            else if (t[2] == "float") k.type = KeyType::Float;
            else if (t[2] == "int") k.type = KeyType::Int;
            else throw Error(ErrorKind::InvalidModel, "", "", where + ": key type '" + t[2] + "'");
            k.unit = t[3];
            if (t.size() == 5) k.meaning = t[4];
            if (m.list_index.count(k.name) || !m.index.emplace(k.name, m.keys.size()).second)
                throw Error(ErrorKind::DuplicateKey, "", "",
                            where + ": key '" + k.name + "' appears twice in module '" + m.name + "'");
            m.keys.push_back(std::move(k));
        } else if (kw == "list") {
            // v0.7: a list is named like a key and shares the key namespace of its module.
            if (t.size() != 2 && t.size() != 3)
                throw Error(ErrorKind::InvalidModel, "", "",
                            where + ": 'list' takes 1 or 2 argument(s), got " + std::to_string(t.size() - 1));
            ModelList l;
            l.name = t[1];
            if (l.name.empty() || l.name.find('.') != std::string::npos)
                throw Error(ErrorKind::InvalidModel, "", "", where + ": list name '" + l.name + "' contains '.'");
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

    if (!have_distribution) throw Error(ErrorKind::MissingDistribution, "", "", origin + ": module has no 'distribution'");
    if (m.sources.empty()) throw Error(ErrorKind::MissingSource, "", "", origin + ": module has no 'source'");
    if (!have_module || m.name.empty()) throw Error(ErrorKind::InvalidModel, "", "", origin + ": missing 'module'");
    if (m.name.find('.') != std::string::npos)
        throw Error(ErrorKind::InvalidModel, "", "", origin + ": module name '" + m.name + "' contains '.'");
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
    bool ok = false;
    switch (f.transform) {
        case Transform::F32: ok = loc.len == 32; break;
        case Transform::F64: ok = loc.len == 64; break;
        case Transform::Ascii: ok = loc.len >= 8 && loc.len <= 2040 && loc.len % 8 == 0; break;
        default: ok = loc.len >= 1 && loc.len <= 64; break;
    }
    if (!ok)
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    p.source + ":" + std::to_string(f.line) + ": transform '" + transform_name(f.transform) +
                        "' does not allow a length of " + std::to_string(loc.len) + " bits");
}

void resolve_when(const Pack& p, WhenLine& w, const std::string& word) {
    const std::string where = p.source + ":" + std::to_string(w.line);
    if (p.wire == Wire::Bits) {
        detail::BitsLocator loc;
        if (!detail::parse_bits_locator(w.locator, loc)) return;  // invalid_locator later
        if (loc.len < 1 || loc.len > 64)
            throw Error(ErrorKind::BadDirective, p.format, w.locator,
                        where + ": a '" + word + "' covers 1 to 64 bits");
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
    if (!f.swap && !f.trim && !f.optional) return;
    const char* option = f.swap ? "swap" : f.trim ? "trim" : "optional";
    if (p.wire != Wire::Bits)
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    where + ": option '" + option + "' applies to wire bits only");
    if (f.trim && f.transform != Transform::Ascii)
        throw Error(ErrorKind::BadDirective, p.format, f.locator,
                    where + ": option 'trim' applies to transform ascii only");
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

// One scope's lines against the counted group `g` (of the same scope, or of the
// common lines when the scope is a kind).
template <class Scope>
void check_against_counted(const Pack& p, const Scope& scope, const std::vector<WhenLine>* whens, const GroupLine& g) {
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
    for (const auto& g : p.groups) check_bits_group(p, g);
    for (const auto& k : p.kinds) {
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
    const bool is_bits = detail::transform_is_bits(f.transform);
    const bool is_pb = detail::transform_is_protobuf(f.transform);
    bool matches;
    if (p.wire == Wire::Protobuf) matches = is_pb;
    else if (p.wire == Wire::Bits) matches = is_bits;
    else matches = !is_bits && !is_pb && (f.transform != Transform::Bool || p.wire == Wire::Json);
    if (!matches)
        throw Error(ErrorKind::InvalidPack, p.format, f.locator,
                    p.source + ": transform '" + std::string(transform_name(f.transform)) +
                        "' is not valid on wire " + wire_name(p.wire));
    if (in_group && f.locator == "." && scalar_item_wire(p.wire)) return;  // the item itself, a scalar
    if (!detail::valid_locator(locator_wire(p, in_group), f.locator))
        throw Error(ErrorKind::InvalidLocator, p.format, f.locator,
                    p.source + ": not a " + wire_name(p.wire) + " field locator");
}

void check_when(const Pack& p, const WhenLine& w, bool in_group) {
    const Wire wire = locator_wire(p, in_group);
    bool ok = detail::valid_locator(wire, w.locator);
    if (ok && wire == Wire::GeoJson) {
        detail::GeoLocator g;
        detail::parse_geo_locator(w.locator, g);
        ok = g.kind == detail::GeoLocator::Kind::Property || g.kind == detail::GeoLocator::Kind::Member;
    }
    if (!ok)
        throw Error(ErrorKind::InvalidLocator, p.format, w.locator,
                    p.source + ": not a " + wire_name(p.wire) + " 'when' or 'const' locator");
}

void check_group_locators(const Pack& p, const GroupLine& g, bool in_group) {
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
    }
    if (!ok)
        throw Error(ErrorKind::InvalidLocator, p.format, g.locator,
                    p.source + ":" + std::to_string(g.line) + ": not a " + wire_name(p.wire) + " group locator");
    for (const auto& f : g.fields) check_field(p, f, true);
    for (const auto& c : g.consts) check_when(p, c, true);
    for (const auto& n : g.groups) check_group_locators(p, n, true);
}

}  // namespace

Pack parse_pack(const std::string& text, const std::string& source) {
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
    // The groups that are open at this line, outermost first. A group stays the
    // last element of its scope while it is open, so the pointers hold.
    std::vector<GroupLine*> open;

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
            throw Error(ErrorKind::InvalidPack, p.format, "", source + ":" + std::to_string(lineno) + ": " + err);
        if (t.empty()) continue;

        const std::string where = source + ":" + std::to_string(lineno);
        const std::string& kw = t[0];
        auto arity = [&](std::size_t n) {
            if (t.size() != n + 1)
                throw Error(ErrorKind::InvalidPack, p.format, "",
                            where + ": '" + kw + "' takes " + std::to_string(n) + " argument(s), got " +
                                std::to_string(t.size() - 1));
        };
        auto once = [&](bool& seen) {
            if (seen) throw Error(ErrorKind::InvalidPack, p.format, "", where + ": duplicate '" + kw + "'");
            seen = true;
        };
        // `when`, `requires`, `root`, `kind`, `map` and `typemap` are not allowed in a group.
        auto not_in_group = [&]() {
            if (!open.empty())
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": '" + kw + "' is not allowed inside a group");
        };

        // Inside a group only `field`, `const`, `default`, `group` and `end` are
        // allowed (0.7 ruling 18).
        if (!open.empty() && kw != "field" && kw != "const" && kw != "default" && kw != "group" && kw != "end")
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
                throw Error(ErrorKind::InvalidPack, p.format, "", where + ": distribution '" + t[1] + "'");
        } else if (kw == "source") {
            arity(1);
            p.sources.push_back(t[1]);
        } else if (kw == "uses") {
            arity(1);
            if (std::find(p.uses.begin(), p.uses.end(), t[1]) == p.uses.end()) p.uses.push_back(t[1]);
        } else if (kw == "wire") {
            arity(1);
            once(have_wire);
            if (t[1] == "xml") p.wire = Wire::Xml;
            else if (t[1] == "geojson") p.wire = Wire::GeoJson;
            else if (t[1] == "bits") p.wire = Wire::Bits;
            else if (t[1] == "protobuf") p.wire = Wire::Protobuf;
            else if (t[1] == "json") p.wire = Wire::Json;
            else throw Error(ErrorKind::UnknownWire, p.format, "", where + ": wire '" + t[1] + "'");
        } else if (kw == "root") {
            not_in_group();
            arity(1);
            if (p.kinds.empty()) {
                once(have_root);
                p.root = t[1];
            } else {
                // v0.6: a root per kind (xml only; checked once the wire is known).
                if (!p.kinds.back().root.empty())
                    throw Error(ErrorKind::InvalidPack, p.format, "",
                                where + ": duplicate 'root' in kind '" + p.kinds.back().name + "'");
                if (t[1].empty()) throw Error(ErrorKind::InvalidPack, p.format, "", where + ": empty 'root'");
                p.kinds.back().root = t[1];
                if (kind_root_line == 0) kind_root_line = lineno;
            }
        } else if (kw == "word_bytes") {
            arity(1);
            once(have_word_bytes);
            if (!parse_u32(t[1], p.word_bytes) || p.word_bytes == 0)
                throw Error(ErrorKind::InvalidPack, p.format, "", where + ": word_bytes must be a positive integer");
        } else if (kw == "layout") {
            // v0.8: `layout fixed` is the default, the addressing of Version 0.2.
            arity(1);
            if (t[1] != "fixed")
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": layout '" + t[1] + "' is not fixed or sequential");
            if (layout_line == 0) layout_line = lineno;
        } else if (kw == "pad" || kw == "align" || kw == "presence" || kw == "if" || kw == "opt" || kw == "chain" ||
                   kw == "fx" || kw == "length" || kw == "also") {
            throw Error(ErrorKind::BadDirective, p.format, "",
                        where + ": '" + kw + "' is a line of a sequential layout, and the pack's layout is fixed");
        } else if (kw == "bit_order") {
            arity(1);
            once(have_bit_order);
            bit_order_line = lineno;
            if (t[1] == "lsb") p.bit_order = BitOrder::Lsb;
            else if (t[1] == "msb") p.bit_order = BitOrder::Msb;
            else throw Error(ErrorKind::BadDirective, p.format, "", where + ": bit_order '" + t[1] + "' is not lsb or msb");
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
                throw Error(ErrorKind::InvalidPack, p.format, "",
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
            if (open.empty())
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": 'end' with no open group");
            arity(0);
            open.pop_back();
        } else if (kw == "const") {
            arity(2);
            WhenLine w;
            w.locator = t[1];
            w.value = t[2];
            w.line = lineno;
            cur_consts().push_back(std::move(w));
        } else if (kw == "default") {
            arity(2);
            DefaultLine d;
            d.key = t[1];
            d.text = t[2];
            d.line = lineno;
            cur_defaults().push_back(std::move(d));
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
            arity(2);
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
                throw Error(ErrorKind::InvalidPack, p.format, "", where + ": 'requires' takes at least 1 argument");
            for (std::size_t k = 1; k < t.size(); ++k) p.kinds.back().requires_keys.push_back(t[k]);
        } else if (kw == "field") {
            if (t.size() < 4)
                throw Error(ErrorKind::InvalidPack, p.format, "",
                            where + ": 'field' takes a key, a locator and a transform, got " +
                                std::to_string(t.size() - 1) + " argument(s)");
            FieldLine f;
            f.key = t[1];
            f.locator = t[2];
            f.line = lineno;
            std::string terr;
            if (!detail::parse_transform(t[3], f, terr))
                throw Error(ErrorKind::UnknownTransform, p.format, f.locator,
                            where + ": " + terr + " for field '" + f.key + "'");
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
                if (t[k] == "swap") flag = &f.swap;
                else if (t[k] == "trim") flag = &f.trim;
                else if (t[k] == "optional") flag = &f.optional;
                if (!flag || *flag)
                    throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                where + ": '" + t[k] + "' is not a field option, or is given twice");
                *flag = true;
            }
            // A model key may be mapped by several lines (0.6: `duplicate-field` is withdrawn).
            cur_fields().push_back(std::move(f));
        } else if (kw == "typemap") {
            not_in_group();
            arity(2);
            if (!natives.insert(t[1]).second)
                throw Error(ErrorKind::InvalidPack, p.format, "", where + ": duplicate typemap code '" + t[1] + "'");
            p.typemap.emplace_back(t[1], t[2]);
        } else {
            throw Error(ErrorKind::UnknownDirective, p.format, "", where + ": directive '" + kw + "'");
        }
    }

    // Line errors that need the whole file: a group left open, where a directive
    // is allowed, and what a `when` value and a bits length may be.
    if (!open.empty())
        throw Error(ErrorKind::BadDirective, p.format, open.back()->locator,
                    source + ":" + std::to_string(open.back()->line) + ": the group '" + open.back()->list +
                        "' has no 'end'");
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
        if (kind_root_line != 0 && p.wire != Wire::Xml)
            throw Error(ErrorKind::BadDirective, p.format, "",
                        source + ":" + std::to_string(kind_root_line) + ": 'root' in a kind applies to wire xml only");
        each_scope(p, [&](std::vector<FieldLine>& fields, std::vector<WhenLine>& consts, bool in_group) {
            for (auto& f : fields) {
                // `.` is the item itself and has no meaning outside a group.
                if (!in_group && f.locator == "." && scalar_item_wire(p.wire))
                    throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                source + ":" + std::to_string(f.line) + ": the locator '.' outside a group");
                // A bit length for a locator is a line of a sequential layout (0.8).
                if (p.wire == Wire::Bits && !f.locator.empty() &&
                    f.locator.find_first_not_of("0123456789") == std::string::npos)
                    throw Error(ErrorKind::BadDirective, p.format, f.locator,
                                source + ":" + std::to_string(f.line) +
                                    ": a field with a bit length for a locator is a line of a sequential layout");
                if (p.wire == Wire::Bits && detail::transform_is_bits(f.transform)) check_bits_field_len(p, f);
                check_field_options(p, table_index, f);
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
        if (p.wire == Wire::Bits) check_bits_groups(p);
        check_fields_through_groups(p);
    }

    if (!have_distribution)
        throw Error(ErrorKind::MissingDistribution, p.format, "", source + ": pack has no 'distribution'");
    if (p.sources.empty()) throw Error(ErrorKind::MissingSource, p.format, "", source + ": pack has no 'source'");
    if (!have_format || p.format.empty()) throw Error(ErrorKind::InvalidPack, "", "", source + ": missing 'format'");
    if (!have_wire) throw Error(ErrorKind::InvalidPack, p.format, "", source + ": missing 'wire'");
    if (p.wire == Wire::Xml && !have_root) {
        // A pack whose every kind has a `root` needs no pack-level `root` (0.6).
        bool every_kind = !p.kinds.empty();
        for (const auto& k : p.kinds) every_kind = every_kind && !k.root.empty();
        if (!every_kind) throw Error(ErrorKind::InvalidPack, p.format, "", source + ": wire xml requires 'root'");
    }
    if (p.wire != Wire::Xml && have_root)
        throw Error(ErrorKind::InvalidPack, p.format, "", source + ": 'root' applies to wire xml only");
    if (p.wire == Wire::Bits && !have_word_bytes)
        throw Error(ErrorKind::InvalidPack, p.format, "", source + ": wire bits requires 'word_bytes'");
    if (p.wire != Wire::Bits && have_word_bytes)
        throw Error(ErrorKind::InvalidPack, p.format, "", source + ": 'word_bytes' applies to wire bits only");

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
    return p;
}

}  // namespace goat_transformers
