// xml, geojson and bits wire codecs, and the steps every codec shares
// (engine-spec.md: Locators, Residue, Type mapping, Canonicalisation; v0.2 bits
// wire; v0.5 message kinds, bit order, fields past their word; v0.6 constants,
// defaults, value tables, field options, a root per kind).
#include "codecs.hpp"

#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

#include "json.hpp"
#include "transforms.hpp"
#include "util.hpp"
#include "xml.hpp"

namespace goat_transformers::detail {

// ---------------------------------------------------------------- locators

namespace {
std::vector<std::string> split(const std::string& s, char sep) {
    std::vector<std::string> out;
    std::size_t st = 0;
    for (;;) {
        std::size_t e = s.find(sep, st);
        out.push_back(s.substr(st, e == std::string::npos ? std::string::npos : e - st));
        if (e == std::string::npos) return out;
        st = e + 1;
    }
}
}  // namespace

bool parse_xml_locator(const std::string& loc, XmlLocator& out) {
    if (loc.empty()) return false;
    std::vector<std::string> segs = split(loc, '/');
    for (const auto& s : segs)
        if (s.empty()) return false;
    XmlLocator r;
    const std::string& last = segs.back();
    if (last[0] == '@') {
        if (last.size() < 2) return false;
        r.kind = XmlLocator::Kind::Attr;
        r.name = last.substr(1);
        segs.pop_back();
    } else if (last == "#text") {
        r.kind = XmlLocator::Kind::Text;
        segs.pop_back();
    } else {
        r.kind = XmlLocator::Kind::Element;
    }
    for (const auto& s : segs)
        if (s[0] == '@' || s[0] == '#') return false;
    r.path = std::move(segs);
    out = std::move(r);
    return true;
}

bool parse_geo_locator(const std::string& loc, GeoLocator& out) {
    static const std::string props = "properties.";
    GeoLocator r;
    if (loc == "geometry.lon") r.kind = GeoLocator::Kind::Lon;
    else if (loc == "geometry.lat") r.kind = GeoLocator::Kind::Lat;
    else if (loc == "geometry.alt") r.kind = GeoLocator::Kind::Alt;
    else if (loc.compare(0, props.size(), props) == 0) {
        if (loc.size() == props.size()) return false;
        r.kind = GeoLocator::Kind::Property;
        r.name = loc.substr(props.size());
    } else {
        if (loc.empty() || loc == "type" || loc == "geometry" || loc == "properties" ||
            loc.compare(0, 9, "geometry.") == 0)
            return false;
        r.kind = GeoLocator::Kind::Member;
        r.name = loc;
    }
    out = std::move(r);
    return true;
}

bool parse_bits_locator(const std::string& loc, BitsLocator& out) {
    std::vector<std::string> segs = split(loc, ':');
    if (segs.size() != 3) return false;
    std::uint64_t vals[3];
    for (int k = 0; k < 3; ++k) {
        const std::string& s = segs[k];
        if (s.empty()) return false;
        std::uint64_t v = 0;
        for (char c : s) {
            if (c < '0' || c > '9') return false;
            v = v * 10 + static_cast<std::uint64_t>(c - '0');
            if (v > 0xFFFFFFFFull) return false;  // keep word/pos/len in uint32 range
        }
        vals[k] = v;
    }
    BitsLocator r;
    r.word = static_cast<std::uint32_t>(vals[0]);
    r.pos = static_cast<std::uint32_t>(vals[1]);
    r.len = static_cast<std::uint32_t>(vals[2]);
    out = r;
    return true;
}

bool parse_bits_group_locator(const std::string& loc, std::uint32_t& word, std::uint32_t& pos) {
    BitsLocator b;
    if (loc.empty() || loc.back() == ':' || !parse_bits_locator(loc + ":0", b)) return false;
    word = b.word;
    pos = b.pos;
    return true;
}

bool valid_locator(Wire w, const std::string& loc, bool allow_element) {
    if (w == Wire::Xml) {
        XmlLocator x;
        if (!parse_xml_locator(loc, x)) return false;
        return allow_element || x.kind != XmlLocator::Kind::Element;
    }
    if (w == Wire::GeoJson) {
        GeoLocator g;
        return parse_geo_locator(loc, g);
    }
    if (w == Wire::Bits) {
        BitsLocator b;
        return parse_bits_locator(loc, b);
    }
    if (w == Wire::Json) {
        std::vector<std::string> path;
        return parse_json_locator(loc, path);
    }
    ProtobufLocator pb;
    return parse_protobuf_locator(loc, pb);
}

bool parse_json_locator(const std::string& loc, std::vector<std::string>& path) {
    if (loc.empty()) return false;
    std::vector<std::string> segs = split(loc, '.');
    for (const auto& s : segs)
        if (s.empty()) return false;
    path = std::move(segs);
    return true;
}

// ---------------------------------------------------------------- shared steps

namespace {
// One scope's lines merged in line order.
void merge_lines(std::vector<LineRef>& out, const std::vector<FieldLine>& fields, const std::vector<WhenLine>* whens,
                 const std::vector<WhenLine>& consts, const std::vector<GroupLine>& groups) {
    std::size_t fi = 0, wi = 0, ci = 0, gi = 0;
    const std::size_t none = static_cast<std::size_t>(-1);
    const std::size_t nwhens = whens ? whens->size() : 0;
    for (;;) {
        const std::size_t fl = fi < fields.size() ? fields[fi].line : none;
        const std::size_t wl = wi < nwhens ? (*whens)[wi].line : none;
        const std::size_t cl = ci < consts.size() ? consts[ci].line : none;
        const std::size_t gl = gi < groups.size() ? groups[gi].line : none;
        if (fl == none && wl == none && cl == none && gl == none) break;
        LineRef r;
        if (fl <= wl && fl <= cl && fl <= gl) r.field = &fields[fi++];
        else if (wl <= cl && wl <= gl) r.when = &(*whens)[wi++];
        else if (cl <= gl) r.konst = &consts[ci++];
        else r.group = &groups[gi++];
        out.push_back(r);
    }
}
}  // namespace

std::vector<LineRef> active_lines(const Pack& p, const Kind* kind) {
    std::vector<LineRef> out;
    out.reserve(p.fields.size() + p.whens.size() + p.consts.size() + p.groups.size() +
                (kind ? kind->fields.size() + kind->whens.size() + kind->consts.size() + kind->groups.size() : 0));
    merge_lines(out, p.fields, &p.whens, p.consts, p.groups);
    if (kind) merge_lines(out, kind->fields, &kind->whens, kind->consts, kind->groups);
    return out;
}

std::vector<LineRef> group_lines(const GroupLine& g) {
    std::vector<LineRef> out;
    out.reserve(g.fields.size() + g.consts.size() + g.groups.size());
    merge_lines(out, g.fields, nullptr, g.consts, g.groups);
    return out;
}

const Kind* select_encode_kind(const Pack& p, const Entity& e) {
    if (p.kinds.empty()) return nullptr;
    if (e.kind.first == p.format) {
        for (const auto& k : p.kinds)
            if (k.name == e.kind.second) return &k;
        throw Error(ErrorKind::NoKind, p.format, "", "the entity names kind '" + e.kind.second +
                                                         "', which the format does not define");
    }
    for (const auto& k : p.kinds) {
        bool all = true;
        for (const auto& key : k.requires_keys) {
            if (e.fields.count(key)) continue;
            // `requires <list>` holds when the list is present and has at least one item (0.7).
            auto list = e.lists.find(key);
            if (list == e.lists.end() || list->second.empty()) {
                all = false;
                break;
            }
        }
        if (all) return &k;
    }
    throw Error(ErrorKind::NoKind, p.format, "", "the entity has the 'requires' keys of no kind");
}

// ---- value tables

namespace {

// 0.11 ruling 2c: a table entry is an integer when 2a accepts it.
bool integer_text(const std::string& s) {
    std::int64_t n = 0;
    return parse_int_text(s, n);
}

// Canonical text of a model value: an integer as decimal digits, a float as in
// ruling 3 of 0.1.1.
std::string canonical_text(const Value& v) {
    switch (v.kind) {
        case Value::Kind::String: return v.s;
        case Value::Kind::Int: return std::to_string(v.i);
        case Value::Kind::Float:
            try {
                return format_double(v.f);
            } catch (const std::domain_error& ex) {
                throw std::invalid_argument(ex.what());
            }
    }
    return std::string();
}

// A table entry in the canonical text of the type it is compared as; text that
// is not of that type is compared as written.
std::string canonical_entry(const std::string& text, KeyType type) {
    if (type == KeyType::Int) {
        std::int64_t n;
        if (parse_int_text(text, n)) return std::to_string(n);
    } else if (type == KeyType::Float) {
        double d;
        if (parse_number_text(text, d)) return format_double(d);
    }
    return text;
}

}  // namespace

Value read_as(const std::string& text, KeyType type) {
    switch (type) {
        case KeyType::String: return Value::of_string(text);
        // 0.11 ruling 2c: integer text (2a) and number text (2b).
        case KeyType::Int: {
            std::int64_t n;
            if (!parse_int_text(text, n)) throw std::invalid_argument("not integer text: \"" + text + "\"");
            return Value::of_int(n);
        }
        case KeyType::Float: {
            double d;
            if (!parse_number_text(text, d)) throw std::invalid_argument("not number text: \"" + text + "\"");
            return Value::of_float(d);
        }
    }
    throw std::invalid_argument("unknown type");
}

KeyType table_model_type(const MapTable& table) {
    bool all_int = !table.entries.empty(), all_num = !table.entries.empty();
    for (const auto& entry : table.entries) {
        double d;
        if (!integer_text(entry.second)) all_int = false;
        if (!parse_number_text(entry.second, d)) all_num = false;
    }
    return all_int ? KeyType::Int : all_num ? KeyType::Float : KeyType::String;
}

Value table_decode(const Pack& p, const FieldLine& f, const Value& native) {
    const MapTable& table = p.tables[static_cast<std::size_t>(f.table)];
    const KeyType wire_type = transform_yields(f.transform);
    const std::string text = canonical_text(native);
    for (const auto& entry : table.entries)  // several entries share a <native> value: the first
        if (canonical_entry(entry.first, wire_type) == text) return read_as(entry.second, f.key_type);
    if (wire_type == f.key_type) return native;
    throw std::invalid_argument("table '" + table.name + "' has no entry for the wire value " + text);
}

Value table_encode(const Pack& p, const FieldLine& f, const Value& model) {
    const MapTable& table = p.tables[static_cast<std::size_t>(f.table)];
    const KeyType wire_type = transform_yields(f.transform);
    const std::string text = canonical_text(model);
    for (const auto& entry : table.entries)  // several entries share a <model> value: the first
        if (canonical_entry(entry.second, f.key_type) == text) return read_as(entry.first, wire_type);
    if (wire_type == f.key_type) return model;
    throw std::invalid_argument("table '" + table.name + "' has no entry for the model value " + text);
}

// ---- one decode

namespace {
thread_local DecodeScope* current_scope = nullptr;
}  // namespace

DecodeScope::DecodeScope(std::uint64_t max_items) : limit(max_items), outer_(current_scope) { current_scope = this; }

DecodeScope::~DecodeScope() { current_scope = outer_; }

void DecodeScope::raise_failure() const {
    if (has_failure_) throw Error(ErrorKind::TransformDecode, fail_format, fail_locator, fail_detail);
}

void take_items(const Pack& p, const std::string& list, std::uint64_t n) {
    DecodeScope* s = current_scope;
    if (!s) return;
    if (n > s->limit || s->held > s->limit - n)
        throw Error(ErrorKind::MalformedWire, p.format, "",
                    "the list '" + list + "' takes the items of the message beyond the limit of " +
                        std::to_string(s->limit));
    s->held += n;
}

void give_back_items(std::uint64_t n) {
    if (DecodeScope* s = current_scope) s->held = n > s->held ? 0 : s->held - n;
}

std::uint64_t count_items(const std::vector<Item>& items) {
    std::uint64_t n = items.size();
    for (const auto& item : items)
        for (const auto& kv : item.lists) n += count_items(kv.second);
    return n;
}

// ---- decode bookkeeping

bool Decoder::wants(const FieldLine& f) const {
    if (out.fields.find(f.key) != out.fields.end()) return false;
    for (const auto& k : closed)
        if (k == f.key) return false;
    return true;
}

void Decoder::set(const FieldLine& f, const std::string& text) {
    if (!wants(f)) return;
    Value v;
    try {
        v = decode_value(f, text);
    } catch (const std::invalid_argument& ex) {
        fail(f, ex.what());
        return;
    }
    put(f, std::move(v));
}

void Decoder::set_json_number(const FieldLine& f, const std::string& text) {
    if (!wants(f)) return;
    Value v;
    try {
        v = decode_json_number(f, text);
    } catch (const std::invalid_argument& ex) {
        fail(f, ex.what());
        return;
    }
    put(f, std::move(v));
}

void Decoder::put(const FieldLine& f, Value native) {
    if (!wants(f)) return;
    if (f.table >= 0) {
        try {
            native = table_decode(p, f, native);
        } catch (const std::invalid_argument& ex) {
            // The transform succeeded and the table has no entry: the decode
            // fails, and later lines of the key are not tried (0.6 ruling 4).
            failures.push_back({f.key, f.locator, ex.what(), true});
            closed.push_back(f.key);
            return;
        }
    }
    out.fields.emplace(f.key, std::move(native));
}

void Decoder::fail(const FieldLine& f, const std::string& why) {
    if (!wants(f)) return;
    failures.push_back({f.key, f.locator, why, false});
}

void Decoder::finish() {
    // A key that another line filled is not a failure (one key at several locators).
    std::string d, first_locator;
    for (const auto& f : failures) {
        if (!f.table && out.fields.count(f.key)) continue;
        if (d.empty()) {
            d = "fields absent after failed decode:";
            first_locator = f.locator;
        }
        d += " [" + f.key + " (" + f.locator + "): " + f.why + "]";
    }
    if (!d.empty()) {
        // Inside a decode the first failure is kept and the decode goes on (0.11 ruling 7f).
        if (DecodeScope* s = current_scope) {
            if (!s->has_failure_) {
                s->has_failure_ = true;
                s->fail_format = p.format;
                s->fail_locator = first_locator;
                s->fail_detail = d;
            }
            return;
        }
        throw Error(ErrorKind::TransformDecode, p.format, first_locator, d);
    }
    // Type mapping: native code -> CoT token; an unmapped code passes through.
    if (!p.typemap.empty()) {
        auto it = out.fields.find("type");
        if (it != out.fields.end() && it->second.kind == Value::Kind::String)
            for (const auto& tm : p.typemap)
                if (tm.first == it->second.s) {
                    it->second.s = tm.second;
                    break;
                }
    }
}

// ---- encode: the value of a field

bool EncodeSource::value(const FieldLine& f, Value& out) const {
    const Value* v = nullptr;
    auto it = e.fields.find(f.key);
    if (it != e.fields.end()) {
        v = &it->second;
    } else {
        // v0.17 ruling 5: a default inside a gate block applies to the fields of
        // that block and of the blocks nested in it; the innermost wins, and it
        // wins over a kind or common default.
        for (int g = f.gate; g >= 0 && !v; g = p.gates[static_cast<std::size_t>(g)].parent)
            for (const std::vector<DefaultLine>* defs : {defaults.first, defaults.second}) {
                if (!defs || v) continue;
                for (const auto& d : *defs)
                    if (d.gate == g && d.key == f.key) {
                        v = &d.value;
                        break;
                    }
            }
        // The default in scope: the selected kind's (or the group body's), else a common one.
        for (const std::vector<DefaultLine>* defs : {defaults.first, defaults.second}) {
            if (!defs || v) continue;
            for (const auto& d : *defs)
                if (d.gate < 0 && d.key == f.key) {
                    v = &d.value;
                    break;
                }
        }
        if (!v) return false;
    }
    out = typemapped_out(p, f, *v);
    if (f.table >= 0) {
        try {
            out = table_encode(p, f, out);
        } catch (const std::invalid_argument& ex) {
            throw Error(ErrorKind::TransformEncode, p.format, f.locator, f.key + ": " + ex.what());
        }
    }
    return true;
}

const std::vector<Item>* EncodeSource::list(const GroupLine& g) const {
    auto it = e.lists.find(g.list);
    return it == e.lists.end() ? nullptr : &it->second;
}

Value typemapped_out(const Pack& p, const FieldLine& f, const Value& v) {
    if (f.key == "type" && !p.typemap.empty() && v.kind == Value::Kind::String)
        for (const auto& tm : p.typemap)
            if (tm.second == v.s) return Value::of_string(tm.first);
    return v;
}

std::string field_text(const Pack& p, const FieldLine& f, const Value& v) {
    try {
        return encode_value(f, v);
    } catch (const std::invalid_argument& ex) {
        throw Error(ErrorKind::TransformEncode, p.format, f.locator, f.key + ": " + ex.what());
    }
}

// ---- absent-value sentinels (Version 0.9)

namespace {

bool absent_u64(const std::string& s, std::uint64_t& out) {
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

// RFC 8259 number grammar: -?(0|[1-9][0-9]*)(.[0-9]+)?([eE][+-]?[0-9]+)?
bool json_number_text(const std::string& s) {
    std::size_t i = 0, n = s.size();
    auto digits = [&]() {
        const std::size_t from = i;
        while (i < n && s[i] >= '0' && s[i] <= '9') ++i;
        return i > from;
    };
    if (i < n && s[i] == '-') ++i;
    if (i >= n) return false;
    if (s[i] == '0') ++i;
    else if (!digits()) return false;
    if (i < n && s[i] == '.') {
        ++i;
        if (!digits()) return false;
    }
    if (i < n && (s[i] == 'e' || s[i] == 'E')) {
        ++i;
        if (i < n && (s[i] == '+' || s[i] == '-')) ++i;
        if (!digits()) return false;
    }
    return i == n;
}

}  // namespace

void resolve_absent(const Pack& p, Wire wire, FieldLine& f, std::uint32_t bits_len, bool coordinate) {
    if (!f.has_absent) return;
    f.absent_num.clear();
    f.absent_text.clear();
    f.absent_json.clear();
    const std::string where = p.source + ":" + std::to_string(f.line) + ": ";
    auto bad = [&](const std::string& why) {
        throw Error(ErrorKind::BadDirective, p.format, f.locator, where + "'absent " + f.absent_arg + "': " + why);
    };
    // 0.10 ruling 16: `absent` is not stated on the `text` wire yet.
    if (wire == Wire::Text) bad("'absent' is not available on the text wire");
    // 0.13 ruling 10: nor on the `tlv` wire, where an empty value is already absent.
    if (wire == Wire::Tlv) bad("'absent' is not available on the tlv wire");
    // The values: the quoted empty token is the one value "the empty text".
    std::vector<std::string> values;
    const bool empty_text = f.absent_arg.empty();
    if (empty_text) {
        values.emplace_back();
    } else {
        std::size_t st = 0;
        for (;;) {
            const std::size_t e = f.absent_arg.find(',', st);
            values.push_back(f.absent_arg.substr(st, e == std::string::npos ? std::string::npos : e - st));
            if (values.back().empty()) bad("an empty value in the list");
            if (e == std::string::npos) break;
            st = e + 1;
        }
    }
    for (const auto& v : values)
        if (v.find('"') != std::string::npos) bad("a value cannot hold a double quote");

    const bool is_bits = transform_is_bits(f.transform), is_pb = transform_is_protobuf(f.transform);
    if (wire == Wire::Bits) {
        if (!is_bits) return;  // invalid_pack later
        if (bits_len > 64) bad("a sentinel applies to a bits field of at most 64 bits, not " + std::to_string(bits_len));
        for (const auto& v : values) {
            std::uint64_t n = 0;
            if (!absent_u64(v, n)) bad("'" + v + "' is not an unsigned decimal integer");
            if (bits_len < 64 && (n >> bits_len) != 0)
                bad(v + " does not fit " + std::to_string(bits_len) + " bits");
            f.absent_num.push_back(n);
        }
        return;
    }
    if (wire == Wire::Protobuf) {
        if (!is_pb) return;
        if (f.transform == Transform::Pstring) {
            f.absent_text = values;  // `=` is part of the text on this wire (ruling 12)
            return;
        }
        for (const auto& v : values) {
            std::uint64_t n = 0;
            if (!absent_u64(v, n)) bad("'" + v + "' is not an unsigned decimal integer");
            if (f.transform == Transform::Pfloat && (n >> 32) != 0) bad(v + " does not fit 32 bits");
            f.absent_num.push_back(n);
        }
        return;
    }
    if (is_bits || is_pb) return;
    // xml, json, geojson: a leading `=` is stripped.
    const bool json_wire = wire == Wire::Json || wire == Wire::GeoJson;
    for (std::size_t k = 0; k < values.size(); ++k) {
        std::string v = values[k];
        bool forced = false;
        if (!empty_text && !v.empty() && v[0] == '=') {
            forced = true;
            v.erase(0, 1);
            if (v.empty()) bad("a value empty after its '=' is stripped; write \"\" for the empty text");
        }
        std::string json_text;
        if (json_wire) {
            if (!forced && json_number_text(v)) {
                double d = 0;
                if (!parse_number_text(v, d)) bad("'" + v + "' is number text that does not fit a finite double");
                v = format_double(d);
                json_text = v;
            } else if (coordinate) {
                bad("a coordinate takes only number text as a sentinel");
            } else if (!forced && (v == "true" || v == "false")) {
                json_text = v;
            } else if (!forced && v == "null") {
                bad("'null' is not a value a transform can hold");
            } else {
                json_text = json::quote(v);
            }
            if (f.transform == Transform::Bool && (forced || (v != "true" && v != "false")))
                bad("a sentinel on transform bool is true or false");
        }
        if (k == 0) f.absent_json = json_text;
        f.absent_text.push_back(std::move(v));
    }
}

bool sentinel_num(const FieldLine& f, std::uint64_t raw) {
    for (std::uint64_t n : f.absent_num)
        if (n == raw) return true;
    return false;
}

bool sentinel_text(const FieldLine& f, const std::string& raw) {
    for (const auto& t : f.absent_text)
        if (t == raw) return true;
    return false;
}

bool json_raw_text(const json::Value& v, std::string& out) {
    switch (v.kind) {
        case json::Value::Kind::String: out = v.text; return true;
        case json::Value::Kind::Bool: out = v.b ? "true" : "false"; return true;
        case json::Value::Kind::Number: {
            double d = 0;
            if (parse_number_text(v.text, d)) {
                out = format_double(d);
            } else {
                out = v.text;  // beyond a finite double: compared as written
            }
            return true;
        }
        default: return false;
    }
}

bool json_when_matches(const WhenLine& w, const json::Value& v) {
    switch (v.kind) {
        case json::Value::Kind::String: return v.text == w.text;
        case json::Value::Kind::Number: return json::canonical_number(v.text) == w.text;
        case json::Value::Kind::Bool: return w.text == (v.b ? "true" : "false");
        default: return false;
    }
}

std::string json_when_text(const WhenLine& w) {
    if (w.forced_string) return json::quote(w.text);
    if (w.text == "true" || w.text == "false") return w.text;
    try {
        json::Value v = json::parse(w.text);
        if (v.is(json::Value::Kind::Number) && v.text == w.text && json::canonical_number(w.text) == w.text &&
            w.text != "-0")
            return w.text;
    } catch (const json::ParseError&) {
    }
    return json::quote(w.text);
}

namespace {
int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
}  // namespace

std::string hex_to_bytes(const Pack& p, const std::string& text) {
    std::string data;
    data.reserve(text.size() / 2);
    int hi = -1;
    for (char c : text) {
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') continue;
        int n = hex_nibble(c);
        if (n < 0) throw Error(ErrorKind::MalformedWire, p.format, "", std::string("not a hex digit: '") + c + "'");
        if (hi < 0) {
            hi = n;
        } else {
            data += static_cast<char>((hi << 4) | n);
            hi = -1;
        }
    }
    if (hi >= 0) throw Error(ErrorKind::MalformedWire, p.format, "", "odd number of hex digits");
    return data;
}

std::string armor_to_bytes(const Pack& p, const std::string& text, std::uint64_t& bits) {
    std::string data((text.size() * 6 + 7) / 8, '\0');
    for (std::size_t k = 0; k < text.size(); ++k) {
        const unsigned char c = static_cast<unsigned char>(text[k]);
        unsigned v;
        if (c >= 0x30 && c <= 0x57) v = c - 0x30u;
        else if (c >= 0x60 && c <= 0x77) v = c - 0x38u;
        else
            throw Error(ErrorKind::MalformedWire, p.format, "",
                        "character " + std::to_string(k) + " (0x" + bytes_to_hex(std::string(1, static_cast<char>(c))) +
                            ") is not a six-bit armor character");
        write_bits(data, 6ull * k, 6, v, true);
    }
    bits = 6ull * text.size();
    return data;
}

std::string bytes_to_armor(const std::string& data, std::uint64_t bits) {
    const std::uint64_t chars = (bits + 5) / 6;
    std::string out;
    out.reserve(static_cast<std::size_t>(chars));
    const std::uint64_t have = static_cast<std::uint64_t>(data.size()) * 8;
    for (std::uint64_t k = 0; k < chars; ++k) {
        unsigned v = 0;
        for (std::uint64_t b = 6 * k; b < 6 * k + 6; ++b) {
            const bool one = b < bits && b < have &&
                             ((static_cast<unsigned char>(data[static_cast<std::size_t>(b / 8)]) >> (7 - b % 8)) & 1u);
            v = (v << 1) | (one ? 1u : 0u);
        }
        out += static_cast<char>(v < 40 ? 0x30 + v : 0x38 + v);
    }
    return out;
}

bool decode_bits_text(const FieldLine& f, const std::string& data, std::uint64_t start, std::uint32_t len, bool msb,
                      Value& out) {
    if (f.transform == Transform::Ascii) {
        std::string text;
        for (std::uint32_t k = 0; k < len / 8; ++k)
            text += static_cast<char>(read_bits(data, start + 8ull * k, 8, msb));
        if (f.swap) std::reverse(text.begin(), text.end());
        out = decode_ascii(text, f.trim);
        return true;
    }
    if (f.transform == Transform::Sixbit) {
        // Characters first to last, each one's six bits in the pack's bit order.
        std::string codes;
        for (std::uint32_t k = 0; k < len / 6; ++k)
            codes += static_cast<char>(read_bits(data, start + 6ull * k, 6, msb));
        out = decode_sixbit(codes, f.trim);
        return true;
    }
    if (const unsigned w = chars_width(f.transform)) {
        // v0.15 `chars`: character i is the w bits at bit i * w of the field.
        std::vector<std::uint8_t> codes(len / w);
        for (std::uint32_t k = 0; k < codes.size(); ++k)
            codes[k] = static_cast<std::uint8_t>(read_bits(data, start + std::uint64_t{w} * k, w, msb));
        out = decode_chars(f.transform, codes);
        return true;
    }
    return false;
}

bool encode_bits_text(const FieldLine& f, const Value& v, std::string& data, std::uint64_t start, std::uint32_t len,
                      bool msb) {
    if (f.transform == Transform::Ascii) {
        std::string text = encode_ascii(v, len / 8);
        if (f.swap) std::reverse(text.begin(), text.end());
        for (std::uint32_t k = 0; k < len / 8; ++k)
            write_bits(data, start + 8ull * k, 8, static_cast<std::uint8_t>(text[k]), msb);
        return true;
    }
    if (f.transform == Transform::Sixbit) {
        const std::string codes = encode_sixbit(v, len / 6);
        for (std::uint32_t k = 0; k < len / 6; ++k)
            write_bits(data, start + 6ull * k, 6, static_cast<std::uint8_t>(codes[k]), msb);
        return true;
    }
    if (const unsigned w = chars_width(f.transform)) {
        const std::vector<std::uint8_t> codes = encode_chars(f.transform, v, len / w);
        for (std::uint32_t k = 0; k < codes.size(); ++k) write_bits(data, start + std::uint64_t{w} * k, w, codes[k], msb);
        return true;
    }
    return false;
}

std::string bytes_to_hex(const std::string& data) {
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(data.size() * 2);
    for (unsigned char b : data) {
        out += kHex[b >> 4];
        out += kHex[b & 0xF];
    }
    return out;
}

namespace {

// Encode on a text wire: one slot per locator, at the place of the first line
// that names it (0.5 rulings 10 and 26). The earliest field line with a value
// fills the slot; a `when` or `const` value is written over any field.
struct TextSlots {
    struct Slot {
        const std::string* locator = nullptr;
        std::string value;
        bool has = false;
        bool sentinel = false;  // the value is a field's sentinel: a line whose key is present writes over it
        // xml: a `group` line with a list to write, one element per item.
        const GroupLine* group = nullptr;
        const std::vector<Item>* items = nullptr;
    };
    std::vector<Slot> slots;
    std::unordered_map<std::string, std::size_t> index;

    Slot& at(const std::string& locator) {
        auto it = index.find(locator);
        if (it != index.end()) return slots[it->second];
        index.emplace(locator, slots.size());
        slots.emplace_back();
        slots.back().locator = &locator;
        return slots.back();
    }
};

}  // namespace

// ---------------------------------------------------------------- xml

namespace {

// The element at `path` under the root; a name binds to its first sibling.
const xml::Node* xml_find(const xml::Node& root, const std::vector<std::string>& path) {
    const xml::Node* n = &root;
    for (const auto& seg : path) {
        const xml::Node* next = nullptr;
        for (const auto& c : n->children)
            if (c.name == seg) {
                next = &c;
                break;
            }
        if (!next) return nullptr;
        n = next;
    }
    return n;
}

// The wire text at an attribute or #text locator; false when absent.
bool xml_value(const xml::Node& root, const XmlLocator& loc, std::string& out) {
    const xml::Node* n = xml_find(root, loc.path);
    if (!n) return false;
    if (loc.kind == XmlLocator::Kind::Attr) {
        for (const auto& a : n->attrs)
            if (a.first == loc.name) {
                out = a.second;
                return true;
            }
        return false;
    }
    if (loc.kind == XmlLocator::Kind::Text && n->has_text) {
        out = n->text;
        return true;
    }
    return false;
}

// `present`: the attribute, or the element of a #text locator, exists.
bool xml_exists(const xml::Node& root, const XmlLocator& loc) {
    const xml::Node* n = xml_find(root, loc.path);
    if (!n) return false;
    if (loc.kind != XmlLocator::Kind::Attr) return true;
    for (const auto& a : n->attrs)
        if (a.first == loc.name) return true;
    return false;
}

}  // namespace

namespace {

// One scope's lines read from `node`: the root element, or an item element.
// `mapped` (the root only) collects the locators the lines map, for residue.
void xml_decode_scope(const Pack& p, const std::vector<LineRef>& lines, const xml::Node& node, Item& out,
                      std::unordered_set<std::string>* mapped) {
    Decoder d(p, out);
    std::string text;
    for (const auto& line : lines) {
        if (mapped && line.maps()) mapped->insert(line.locator());
        if (line.group) {
            // Each child element named by the last name, under the first element
            // matched by the names before it. The list is present when an item occurs.
            const GroupLine& g = *line.group;
            XmlLocator loc;
            parse_xml_locator(g.locator, loc);  // validated at pack load
            const std::string name = loc.path.back();
            loc.path.pop_back();
            const xml::Node* parent = xml_find(node, loc.path);
            if (!parent) continue;
            std::uint64_t count = 0;
            for (const auto& c : parent->children) count += c.name == name ? 1 : 0;
            take_items(p, g.list, count);  // 0.11 ruling 7a
            std::vector<Item> items;
            std::vector<LineRef> body;
            for (const auto& c : parent->children) {
                if (c.name != name) continue;
                if (items.empty()) body = group_lines(g);
                items.emplace_back();
                xml_decode_scope(p, body, c, items.back(), nullptr);
            }
            if (!items.empty()) out.lists[g.list] = std::move(items);
            continue;
        }
        if (!line.field) continue;
        const FieldLine& f = *line.field;
        if (!d.wants(f)) continue;
        XmlLocator loc;
        parse_xml_locator(f.locator, loc);
        if (!xml_value(node, loc, text)) continue;
        // A sentinel is compared with the text as resolved, not trimmed (0.9 ruling 14).
        if (f.has_absent && sentinel_text(f, text)) continue;
        d.set(f, text);
    }
    d.finish();
}

}  // namespace

Entity decode_xml(const Pack& p, const std::string& bytes) {
    xml::Node root;
    try {
        root = xml::parse(bytes);
    } catch (const xml::ParseError& ex) {
        throw Error(ErrorKind::MalformedWire, p.format, "", ex.what());
    }

    // A kind is considered only when the document's root element has its name
    // (its own `root`, else the pack's), before its `when` lines (0.6). A pack
    // with no kinds requires the pack's root (missing-root); in a pack that has
    // kinds a root matching no kind is no-kind (0.6 ruling 11).
    const std::vector<std::size_t>* candidates = nullptr;
    static const std::vector<std::size_t> no_kinds;
    if (p.kinds.empty()) {
        if (root.name != p.root)
            throw Error(ErrorKind::MissingRoot, p.format, "",
                        "expected root <" + p.root + ">, found <" + root.name + ">");
    } else {
        auto it = p.kinds_by_root.find(root.name);
        candidates = it == p.kinds_by_root.end() ? &no_kinds : &it->second;
    }

    const Kind* kind = select_decode_kind(
        p,
        [&](const WhenLine& w) {
            XmlLocator loc;
            parse_xml_locator(w.locator, loc);  // validated at pack load
            if (w.present) return xml_exists(root, loc);
            std::string text;
            return xml_value(root, loc, text) && text == w.text;
        },
        candidates);

    Entity e;
    std::unordered_set<std::string> mapped;
    xml_decode_scope(p, active_lines(p, kind), root, e, &mapped);
    // Residue: unmapped attributes of the root element (0.1.1 ruling 6). Unmapped
    // child elements, and what they hold, are not carried.
    for (const auto& a : root.attrs)
        if (!mapped.count("@" + a.first)) e.residue.push_back({p.format, "@" + a.first, a.second});
    if (kind) e.kind = {p.format, kind->name};
    return e;
}

namespace {
xml::Node& ensure_path(xml::Node& root, const std::vector<std::string>& path) {
    xml::Node* n = &root;
    for (const auto& seg : path) {
        xml::Node* next = nullptr;
        for (auto& c : n->children)
            if (c.name == seg) {
                next = &c;
                break;
            }
        if (!next) {
            n->children.emplace_back();
            n->children.back().name = seg;
            next = &n->children.back();
        }
        n = next;
    }
    return *n;
}

void place_xml(xml::Node& root, const XmlLocator& loc, const std::string& value) {
    xml::Node& n = ensure_path(root, loc.path);
    switch (loc.kind) {
        case XmlLocator::Kind::Attr:
            for (auto& a : n.attrs)
                if (a.first == loc.name) return;
            n.attrs.emplace_back(loc.name, value);
            break;
        case XmlLocator::Kind::Text:
            if (n.has_text) return;
            n.has_text = true;
            n.text = value;
            break;
        case XmlLocator::Kind::Element: break;
    }
}

// One scope's lines written into `node`: the root element, or an item element.
// `out` keeps the slots, so the caller can tell which locators were written.
void xml_encode_scope(const Pack& p, const std::vector<LineRef>& lines, const EncodeSource& src, xml::Node& node,
                      TextSlots& out) {
    Value v;
    for (const auto& line : lines) {
        if (line.group) {
            // The group takes its place in line order; an absent or empty list writes nothing.
            const std::vector<Item>* items = src.list(*line.group);
            if (!items || items->empty()) continue;
            out.slots.emplace_back();
            out.slots.back().group = line.group;
            out.slots.back().items = items;
            continue;
        }
        if (const WhenLine* w = line.fixed()) {
            if (w->present) continue;  // `present` writes nothing
            auto& slot = out.at(w->locator);
            slot.value = w->text;
            slot.has = true;
            slot.sentinel = false;
            continue;
        }
        const FieldLine& f = *line.field;
        auto& slot = out.at(f.locator);
        if (slot.has && !slot.sentinel) continue;
        if (src.value(f, v)) {
            slot.value = field_text(p, f, v);
            slot.has = true;
            slot.sentinel = false;
        } else if (f.has_absent && !slot.has) {
            // An absent key writes its first sentinel (0.9); a later line whose key is present wins (ruling 16).
            slot.value = f.absent_text.front();
            slot.has = true;
            slot.sentinel = true;
        }
    }
    for (const auto& slot : out.slots) {
        if (slot.group) {
            const GroupLine& g = *slot.group;
            XmlLocator loc;
            parse_xml_locator(g.locator, loc);  // validated at pack load
            const std::string name = loc.path.back();
            loc.path.pop_back();
            xml::Node& parent = ensure_path(node, loc.path);
            const std::vector<LineRef> body = group_lines(g);
            parent.children.reserve(parent.children.size() + slot.items->size());
            for (const Item& item : *slot.items) {
                parent.children.emplace_back();
                xml::Node& child = parent.children.back();
                child.name = name;
                TextSlots inner;
                xml_encode_scope(p, body, EncodeSource(p, g, item), child, inner);
            }
            continue;
        }
        if (!slot.has) continue;
        XmlLocator loc;
        parse_xml_locator(*slot.locator, loc);  // validated at pack load
        place_xml(node, loc, slot.value);
    }
}
}  // namespace

std::string encode_xml(const Pack& p, const Entity& e) {
    const Kind* kind = select_encode_kind(p, e);
    TextSlots out;
    xml::Node root;
    root.name = kind && !kind->root.empty() ? kind->root : p.root;
    xml_encode_scope(p, active_lines(p, kind), EncodeSource(p, kind, e), root, out);
    std::unordered_set<std::string> residue_seen;
    for (const auto& r : e.residue) {
        if (r.format != p.format) continue;
        auto it = out.index.find(r.locator);
        if (it != out.index.end() && out.slots[it->second].has) continue;
        if (!residue_seen.insert(r.locator).second) continue;
        XmlLocator loc;
        if (!parse_xml_locator(r.locator, loc)) continue;
        place_xml(root, loc, r.value);
    }
    try {
        return xml::write(root);
    } catch (const xml::WriteError& ex) {
        throw Error(ErrorKind::TransformEncode, p.format, "", ex.what());
    }
}

// ---------------------------------------------------------------- geojson

namespace {
// Scalar wire text of a JSON value; false for null (field absent).
bool json_text(const json::Value& v, std::string& out) {
    switch (v.kind) {
        case json::Value::Kind::Null: return false;
        case json::Value::Kind::String:
        case json::Value::Kind::Number: out = v.text; return true;
        case json::Value::Kind::Bool: out = v.b ? "true" : "false"; return true;
        default: out = json::write(v); return true;
    }
}
}  // namespace

Entity decode_geojson(const Pack& p, const std::string& bytes) {
    json::Value doc;
    try {
        doc = json::parse(bytes);
    } catch (const json::ParseError& ex) {
        throw Error(ErrorKind::MalformedWire, p.format, "", ex.what());
    }
    if (!doc.is(json::Value::Kind::Object)) throw Error(ErrorKind::MalformedWire, p.format, "", "not a JSON object");
    if (const json::Value* t = doc.find("type"))
        if (!t->is(json::Value::Kind::String) || t->text != "Feature")
            throw Error(ErrorKind::MalformedWire, p.format, "type", "not a GeoJSON Feature");

    const json::Value* coords = nullptr;
    if (const json::Value* g = doc.find("geometry")) {
        if (g->is(json::Value::Kind::Object)) {
            const json::Value* gt = g->find("type");
            if (gt && (!gt->is(json::Value::Kind::String) || gt->text != "Point"))
                throw Error(ErrorKind::MalformedWire, p.format, "geometry", "geometry is not a Point");
            coords = g->find("coordinates");
            if (coords && !coords->is(json::Value::Kind::Array))
                throw Error(ErrorKind::MalformedWire, p.format, "geometry", "coordinates is not an array");
        } else if (!g->is(json::Value::Kind::Null)) {
            throw Error(ErrorKind::MalformedWire, p.format, "geometry", "geometry is not an object");
        }
    }
    const json::Value* props = doc.find("properties");
    if (props && !props->is(json::Value::Kind::Object) && !props->is(json::Value::Kind::Null))
        throw Error(ErrorKind::MalformedWire, p.format, "properties", "properties is not an object");
    if (props && props->is(json::Value::Kind::Null)) props = nullptr;

    auto lookup = [&](const GeoLocator& loc) -> const json::Value* {
        auto slot = [&](std::size_t k) { return coords && coords->items.size() > k ? &coords->items[k] : nullptr; };
        switch (loc.kind) {
            case GeoLocator::Kind::Lon: return slot(0);
            case GeoLocator::Kind::Lat: return slot(1);
            case GeoLocator::Kind::Alt: return slot(2);
            case GeoLocator::Kind::Property: return props ? props->find(loc.name) : nullptr;
            case GeoLocator::Kind::Member: return doc.find(loc.name);
        }
        return nullptr;
    };

    const Kind* kind = select_decode_kind(p, [&](const WhenLine& w) {
        GeoLocator loc;
        parse_geo_locator(w.locator, loc);  // validated at pack load
        const json::Value* v = lookup(loc);
        if (!v || v->is(json::Value::Kind::Null)) return false;
        return w.present || json_when_matches(w, *v);
    });

    Entity e;
    Decoder d(p, e);
    std::unordered_set<std::string> mapped_props, mapped_members;
    for (const auto& line : active_lines(p, kind)) {
        GeoLocator loc;
        parse_geo_locator(line.locator(), loc);
        if (line.maps()) {
            if (loc.kind == GeoLocator::Kind::Property) mapped_props.insert(loc.name);
            else if (loc.kind == GeoLocator::Kind::Member) mapped_members.insert(loc.name);
        }
        if (line.group) {
            // The list is present when the member exists and is an array; `null` is absent.
            const json::Value* v = lookup(loc);
            if (v && !v->is(json::Value::Kind::Null))
                e.lists[line.group->list] = json_decode_items(p, *line.group, *v, true);
            continue;
        }
        if (!line.field) continue;
        const json::Value* v = lookup(loc);
        std::string text;
        if (v && line.field->has_absent && json_raw_text(*v, text) && sentinel_text(*line.field, text)) continue;
        if (v && transform_is_text_scale(line.field->transform) && !v->is(json::Value::Kind::Null) &&
            !v->is(json::Value::Kind::Number)) {
            // scale and iscale read a number, on geojson as on json (0.15 ruling 23).
            d.fail(*line.field, std::string("the member is not a number, which transform '") +
                                    transform_name(line.field->transform) + "' reads");
            continue;
        }
        if (v && v->is(json::Value::Kind::Number)) d.set_json_number(*line.field, v->text);
        else if (v && json_text(*v, text)) d.set(*line.field, text);
    }
    // Residue keeps its 0.1 form (0.5 ruling 28, 0.6 ruling 13): a string or a
    // number keeps its text as written and encode writes it back as a string;
    // an array or an object comes back as it was; `null` is dropped. Of two
    // members with one name, the last value is used at the first position.
    auto residue_of = [&](const json::Value& obj, const std::string& prefix,
                          const std::unordered_set<std::string>& mapped, bool top) {
        std::unordered_map<std::string, std::size_t> last;
        for (std::size_t k = 0; k < obj.keys.size(); ++k) last[obj.keys[k]] = k;
        std::unordered_set<std::string> seen;
        for (std::size_t k = 0; k < obj.keys.size(); ++k) {
            const std::string& name = obj.keys[k];
            if (top && (name == "type" || name == "geometry" || name == "properties")) continue;
            if (mapped.count(name) || !seen.insert(name).second) continue;
            const json::Value& v = obj.items[last[name]];
            const bool structured = v.is(json::Value::Kind::Array) || v.is(json::Value::Kind::Object);
            std::string text;
            if (structured) text = json::write_as_written(v);
            else if (!json_text(v, text)) continue;
            e.residue.push_back({p.format, prefix + name, text, structured});
        }
    };
    if (props) residue_of(*props, "properties.", mapped_props, false);
    residue_of(doc, "", mapped_members, true);
    d.finish();
    if (kind) e.kind = {p.format, kind->name};
    return e;
}

std::string encode_geojson(const Pack& p, const Entity& e) {
    const Kind* kind = select_encode_kind(p, e);
    const EncodeSource src(p, kind, e);
    std::string lon, lat, alt;
    bool has_lon = false, has_lat = false, has_alt = false;
    // A coordinate holding a sentinel: a later line whose key is present writes over it.
    bool sen_lon = false, sen_lat = false, sen_alt = false;
    TextSlots props, members;  // locator -> JSON text
    Value v;

    for (const auto& line : active_lines(p, kind)) {
        GeoLocator loc;
        parse_geo_locator(line.locator(), loc);  // validated at pack load
        if (const WhenLine* w = line.fixed()) {
            if (w->present) continue;  // a property or a member, checked at load
            auto& slot = (loc.kind == GeoLocator::Kind::Property ? props : members).at(w->locator);
            slot.value = json_when_text(*w);
            slot.has = true;
            slot.sentinel = false;
            continue;
        }
        if (line.group) {
            // An array at the member; an empty list writes `[]`, an absent one nothing.
            auto& slot = (loc.kind == GeoLocator::Kind::Property ? props : members).at(line.group->locator);
            const std::vector<Item>* items = src.list(*line.group);
            if ((slot.has && !slot.sentinel) || !items) continue;
            slot.value = json_encode_items(p, *line.group, *items, true);
            slot.has = true;
            slot.sentinel = false;
            continue;
        }
        const FieldLine& f = *line.field;
        TextSlots::Slot* slot = nullptr;
        bool taken = false, sentinel = false;
        switch (loc.kind) {
            case GeoLocator::Kind::Lon: taken = has_lon; sentinel = sen_lon; break;
            case GeoLocator::Kind::Lat: taken = has_lat; sentinel = sen_lat; break;
            case GeoLocator::Kind::Alt: taken = has_alt; sentinel = sen_alt; break;
            case GeoLocator::Kind::Property: slot = &props.at(f.locator); taken = slot->has; sentinel = slot->sentinel; break;
            case GeoLocator::Kind::Member: slot = &members.at(f.locator); taken = slot->has; sentinel = slot->sentinel; break;
        }
        if (taken && !sentinel) continue;
        std::string jv;
        bool writes_sentinel = false;
        if (src.value(f, v)) {
            std::string text = field_text(p, f, v);
            jv = transform_is_textual(f.transform) ? json::quote(text) : text;
        } else if (f.has_absent && !taken) {
            // The first sentinel, typed as a `when` value is (0.9). On `lon` and
            // `lat` it counts as a value, so `geometry` is written (ruling 10).
            jv = f.absent_json;
            writes_sentinel = true;
        } else {
            continue;
        }
        switch (loc.kind) {
            case GeoLocator::Kind::Lon: lon = jv; has_lon = true; sen_lon = writes_sentinel; break;
            case GeoLocator::Kind::Lat: lat = jv; has_lat = true; sen_lat = writes_sentinel; break;
            case GeoLocator::Kind::Alt: alt = jv; has_alt = true; sen_alt = writes_sentinel; break;
            default:
                slot->value = std::move(jv);
                slot->has = true;
                slot->sentinel = writes_sentinel;
                break;
        }
    }
    // Residue of this format, in input order, after the mapped members.
    std::vector<std::pair<std::string, std::string>> rprops, rmembers;
    std::unordered_set<std::string> residue_seen;
    for (const auto& r : e.residue) {
        if (r.format != p.format) continue;
        GeoLocator loc;
        if (!parse_geo_locator(r.locator, loc)) continue;
        if (loc.kind != GeoLocator::Kind::Property && loc.kind != GeoLocator::Kind::Member) continue;
        TextSlots& in = loc.kind == GeoLocator::Kind::Property ? props : members;
        auto it = in.index.find(r.locator);
        if (it != in.index.end() && in.slots[it->second].has) continue;
        if (!residue_seen.insert(r.locator).second) continue;
        (loc.kind == GeoLocator::Kind::Property ? rprops : rmembers)
            .emplace_back(loc.name, r.structured ? r.value : json::quote(r.value));
    }
    auto name_of = [](const std::string& locator) {
        GeoLocator loc;
        parse_geo_locator(locator, loc);
        return loc.name;
    };

    std::string out = "{\"type\":\"Feature\",\"geometry\":";
    if (has_lon && has_lat) {
        out += "{\"type\":\"Point\",\"coordinates\":[" + lon + "," + lat;
        if (has_alt) out += "," + alt;
        out += "]}";
    } else {
        out += "null";
    }
    out += ",\"properties\":{";
    bool first = true;
    for (const auto& slot : props.slots) {
        if (!slot.has) continue;
        if (!first) out += ',';
        first = false;
        out += json::quote(name_of(*slot.locator)) + ":" + slot.value;
    }
    for (const auto& kv : rprops) {
        if (!first) out += ',';
        first = false;
        out += json::quote(kv.first) + ":" + kv.second;
    }
    out += "}";
    for (const auto& slot : members.slots)
        if (slot.has) out += "," + json::quote(name_of(*slot.locator)) + ":" + slot.value;
    for (const auto& kv : rmembers) out += "," + json::quote(kv.first) + ":" + kv.second;
    out += "}";
    return out;
}

// ---------------------------------------------------------------- bits

namespace {

struct BitRange {
    std::uint64_t start = 0;  // bit offset in the message
    std::uint32_t len = 0;
    std::uint64_t end() const { return start + len; }
};

// <word>:<pos>:<len> addresses `len` bits from bit word * word_bytes * 8 + pos of
// the message; the field may run past its word (0.5).
BitRange bit_range(const Pack& p, const std::string& locator) {
    BitsLocator loc;
    parse_bits_locator(locator, loc);  // validated at pack load
    BitRange r;
    r.start = static_cast<std::uint64_t>(loc.word) * p.word_bytes * 8 + loc.pos;
    r.len = loc.len;
    return r;
}

}  // namespace

// lsb: bit i is bit (i mod 8) of byte (i div 8), a value's low bit first.
// msb: bit i is bit 7 - (i mod 8) of byte (i div 8), a value's high bit first.
std::uint64_t read_bits(const std::string& data, std::uint64_t start, std::uint32_t len, bool msb) {
    std::uint64_t raw = 0;
    for (std::uint32_t k = 0; k < len; ++k) {
        const std::uint64_t g = start + k;
        const std::uint8_t byte = static_cast<std::uint8_t>(data[static_cast<std::size_t>(g / 8)]);
        const std::uint64_t bit = (byte >> (msb ? 7 - g % 8 : g % 8)) & 1u;
        if (msb) raw = (raw << 1) | bit;
        else raw |= bit << k;
    }
    return raw;
}

void write_bits(std::string& data, std::uint64_t start, std::uint32_t len, std::uint64_t raw, bool msb) {
    for (std::uint32_t k = 0; k < len; ++k) {
        const std::uint64_t g = start + k;
        char& byte = data[static_cast<std::size_t>(g / 8)];
        const std::uint8_t mask = static_cast<std::uint8_t>(1u << (msb ? 7 - g % 8 : g % 8));
        const bool bit = ((raw >> (msb ? len - 1 - k : k)) & 1u) != 0;
        byte = static_cast<char>(bit ? (static_cast<std::uint8_t>(byte) | mask)
                                     : (static_cast<std::uint8_t>(byte) & static_cast<std::uint8_t>(~mask)));
    }
}

// `swap`: the bytes of a `len`-bit value (len a multiple of 8) in reverse order.
std::uint64_t swap_bytes(std::uint64_t raw, std::uint32_t len) {
    std::uint64_t out = 0;
    for (std::uint32_t k = 0; k < len / 8; ++k) out = (out << 8) | ((raw >> (8 * k)) & 0xFFu);
    return out;
}

namespace {

// v0.17: the gate block a line belongs to (-1 outside any). Only `field` and
// `const` lines may stand in a block.
int line_gate(const LineRef& line) {
    return line.field ? line.field->gate : line.konst ? line.konst->gate : -1;
}

// Is a line of gate block `gate` part of the scope as `held` says?
bool gate_on(int gate, const std::vector<char>* held) {
    return gate < 0 || (held && (*held)[static_cast<std::size_t>(gate)] != 0);
}

// The furthest bit one scope's own lines reach, counted from the scope's first
// bit: every `field`, `when` and `const`, and the count locator of every group.
// On decode an `optional` field does not count: the input need not reach it.
// The lines of a gate block count only when it holds; on encode the locator of
// a held gate counts too (0.17).
std::uint64_t fixed_extent(const Pack& p, const std::vector<LineRef>& lines, bool decode,
                           const std::vector<char>* held = nullptr, const std::vector<int>* gates = nullptr) {
    std::uint64_t end = 0;
    for (const auto& line : lines) {
        if (line.group) {
            if (!line.group->count_fixed) end = std::max(end, line.group->count_start + line.group->count_len);
            continue;
        }
        if (!gate_on(line_gate(line), held)) continue;
        if (decode && line.field && line.field->optional) continue;
        end = std::max(end, bit_range(p, line.locator()).end());
    }
    if (gates && held)
        for (int id : *gates)
            if ((*held)[static_cast<std::size_t>(id)]) {
                const GateBlock& b = p.gates[static_cast<std::size_t>(id)];
                end = std::max(end, b.start + b.len);
            }
    return end;
}

std::size_t whole_words(const Pack& p, std::uint64_t bits) {
    const std::uint64_t word_bits = static_cast<std::uint64_t>(p.word_bytes) * 8;
    return static_cast<std::size_t>((bits + word_bits - 1) / word_bits * p.word_bytes);
}

// Evaluate the gate blocks `gates` (line order, so an enclosing block comes
// before the blocks nested in it) of a scope at bit `base` of `data`. A nested
// block holds only when its enclosing block does. A gate any of whose bits lies
// beyond `data` does not hold, or, with `beyond_zero` (encode, step 4), reads
// those bits as 0.
void eval_gates(const Pack& p, const std::string& data, bool msb, std::uint64_t base, const std::vector<int>& gates,
                bool beyond_zero, std::vector<char>& held, std::uint64_t have_bits = ~std::uint64_t{0}) {
    // The input's bits: the whole bytes, or under armor (0.14) the 6 bits a character.
    const std::uint64_t have = std::min<std::uint64_t>(static_cast<std::uint64_t>(data.size()) * 8, have_bits);
    for (int id : gates) {
        const GateBlock& b = p.gates[static_cast<std::size_t>(id)];
        char& h = held[static_cast<std::size_t>(id)];
        h = 0;
        if (b.parent >= 0 && !held[static_cast<std::size_t>(b.parent)]) continue;
        const std::uint64_t start = base + b.start;
        std::uint64_t raw = 0;
        if (start + b.len <= have) {
            raw = read_bits(data, start, b.len, msb);
        } else {
            if (!beyond_zero) continue;
            for (std::uint32_t k = 0; k < b.len; ++k) {
                const std::uint64_t g = start + k;
                std::uint64_t bit = 0;
                if (g < have) bit = (static_cast<std::uint8_t>(data[static_cast<std::size_t>(g / 8)]) >> (msb ? 7 - g % 8 : g % 8)) & 1u;
                if (msb) raw = (raw << 1) | bit;
                else raw |= bit << k;
            }
        }
        h = b.matches(raw) ? 1 : 0;
    }
}

struct BitsIn {
    const Pack& p;
    const std::string& data;
    bool msb;
    std::uint64_t have;  // bits of input
    // The first transform failure. It is kept until the whole message has been
    // walked, so that input too short for its items is malformed-wire first.
    bool failed = false;
    std::string fail_locator, fail_detail;

    [[noreturn]] void too_short(const std::string& what, std::uint64_t need) const {
        throw Error(ErrorKind::MalformedWire, p.format, "",
                    what + " needs " + std::to_string((need + 7) / 8) + " bytes, got " + std::to_string(data.size()));
    }
};

// One scope's lines read from bit `base` of the message: the message itself
// (base 0) or one item. Returns the bit after the furthest one the scope
// requires, which for an item whose last group is counted by a locator is where
// the next item starts. `gates`: the scope's gate blocks (0.17).
std::uint64_t bits_decode_scope(BitsIn& in, const std::vector<LineRef>& lines, const std::vector<int>& gates,
                                std::uint64_t base, Item& out, const std::string& what) {
    const Pack& p = in.p;
    // A gate is read like a `when`: it does not count toward the length, and a
    // line of a block that does not hold is a line whose locator is absent.
    std::vector<char> held(gates.empty() ? 0 : p.gates.size(), 0);
    if (!gates.empty()) eval_gates(p, in.data, in.msb, base, gates, false, held, in.have);
    std::uint64_t end = base + fixed_extent(p, lines, true, &held);
    if (end > in.have) in.too_short(what, end);

    Decoder d(p, out);
    for (const auto& line : lines) {
        if (!line.field) continue;
        const FieldLine& f = *line.field;
        if (!gate_on(f.gate, &held)) continue;
        if (!d.wants(f)) continue;
        BitRange r = bit_range(p, f.locator);
        r.start += base;
        if (r.end() > in.have) continue;  // an `optional` field beyond the input is absent
        if (f.has_absent) {
            // The raw value after `swap`, before `trim`, a table and the transform (0.9 ruling 2).
            std::uint64_t raw = read_bits(in.data, r.start, r.len, in.msb);
            if (f.swap) raw = swap_bytes(raw, r.len);
            if (sentinel_num(f, raw)) continue;
        }
        try {
            Value text;
            if (decode_bits_text(f, in.data, r.start, r.len, in.msb, text)) {
                d.put(f, text);
            } else {
                std::uint64_t raw = read_bits(in.data, r.start, r.len, in.msb);
                if (f.swap) raw = swap_bytes(raw, r.len);
                d.put(f, decode_bits_value(f, raw, r.len));
            }
        } catch (const std::invalid_argument& ex) {
            d.fail(f, ex.what());
        }
    }

    // The groups, in line order: `count` items back to back. The list is always present.
    for (const auto& line : lines) {
        if (!line.group) continue;
        const GroupLine& g = *line.group;
        const std::uint64_t count =
            g.count_fixed ? g.count_n : read_bits(in.data, base + g.count_start, g.count_len, in.msb);
        std::vector<Item>& items = out.lists[g.list];
        give_back_items(count_items(items));
        items.clear();
        // 0.11 ruling 7d: the count is compared with the limit before any item is read.
        take_items(p, g.list, count);
        const std::vector<LineRef> body = group_lines(g);
        const std::string item_what = "an item of the group '" + g.list + "'";
        std::uint64_t at = base + g.bits_start;
        for (std::uint64_t k = 0; k < count; ++k) {
            if (at + g.item_bits > in.have) in.too_short(item_what, at + g.item_bits);
            items.emplace_back();
            const std::uint64_t used = bits_decode_scope(in, body, g.gates, at, items.back(), item_what);
            at = std::max(at + g.item_bits, used);
        }
        end = std::max(end, at);
    }

    try {
        d.finish();
    } catch (const Error& ex) {
        if (!in.failed) {
            in.failed = true;
            in.fail_locator = ex.locator();
            in.fail_detail = ex.detail();
        }
    }
    return end;
}

// Step 6 of a gated scope (0.17), checked once on the final output.
struct GateCheck {
    std::uint64_t base = 0;
    const std::vector<int>* gates = nullptr;
    std::vector<char> held;  // the held blocks of step 4
};

struct BitsOut {
    const Pack& p;
    std::string data;
    bool msb;
    // v0.14: the length L of armored output, one more than the highest bit of
    // any line written, an `optional` field with no value aside.
    std::uint64_t armor_end = 0;
    std::vector<GateCheck> checks;  // v0.17

    void reach(std::uint64_t bits) {
        const std::size_t bytes = static_cast<std::size_t>((bits + 7) / 8);
        if (data.size() < bytes) data.resize(bytes, '\0');
    }
};

bool overlaps(const std::vector<BitRange>& ranges, std::uint64_t start, std::uint64_t len) {
    for (const auto& r : ranges)
        if (r.start < start + len && start < r.end()) return true;
    return false;
}

// The sentinels and the `field` lines of a scope written into `data` from bit
// `base`; a line of a gate block is written when `held` says the block holds.
// `present`, when given, receives the ranges of the lines whose key is present.
void write_field_lines(const Pack& p, std::string& data, bool msb, const std::vector<LineRef>& lines,
                       std::uint64_t base, const EncodeSource& src, const std::vector<char>* held,
                       std::vector<BitRange>* present) {
    // An absent key with `absent` writes its first sentinel; a line whose key is
    // present wins over a sentinel whatever their order (0.9 ruling 16), so the
    // sentinels are written first.
    Value mv;
    for (auto it = lines.rbegin(); it != lines.rend(); ++it) {
        if (!it->field || !it->field->has_absent || !gate_on(it->field->gate, held)) continue;
        const FieldLine& f = *it->field;
        if (src.value(f, mv)) continue;
        BitRange r = bit_range(p, f.locator);
        r.start += base;
        std::uint64_t raw = f.absent_num.front();
        if (f.swap) raw = swap_bytes(raw, r.len);
        write_bits(data, r.start, r.len, raw, msb);
    }
    // Where two present fields cover the same bits the earlier line's value holds
    // (0.5 ruling 5): write the lines last to first. Absent fields without
    // `absent` leave zero bits.
    for (auto it = lines.rbegin(); it != lines.rend(); ++it) {
        if (!it->field || !gate_on(it->field->gate, held)) continue;
        const FieldLine& f = *it->field;
        const bool has = src.value(f, mv);
        if (!has) continue;
        BitRange r = bit_range(p, f.locator);
        r.start += base;
        if (present && src.e.fields.count(f.key)) present->push_back(r);
        try {
            if (!encode_bits_text(f, mv, data, r.start, r.len, msb)) {
                std::uint64_t raw = encode_bits_value(f, mv, r.len);
                if (f.swap) raw = swap_bytes(raw, r.len);
                write_bits(data, r.start, r.len, raw, msb);
            }
        } catch (const std::invalid_argument& ex) {
            throw Error(ErrorKind::TransformEncode, p.format, f.locator, f.key + ": " + ex.what());
        }
    }
}

// `when` and `const` values are written over any field, so the output decodes
// as the same kind. `written`, when given, receives their ranges.
void write_fixed_lines(const Pack& p, std::string& data, bool msb, const std::vector<LineRef>& lines,
                       std::uint64_t base, const std::vector<char>* held, std::vector<BitRange>* written) {
    for (const auto& line : lines) {
        const WhenLine* w = line.fixed();
        if (!w || !gate_on(line_gate(line), held)) continue;
        BitRange r = bit_range(p, w->locator);
        r.start += base;
        write_bits(data, r.start, r.len, w->number, msb);
        if (written) written->push_back(r);
    }
}

// The gate value step 3 gives a block: the first listed value, or for `!` the
// smallest value not listed. False when the list names every value.
bool gate_value(const GateBlock& b, std::uint64_t& out) {
    if (!b.negated) {
        out = b.values.front();
        return true;
    }
    const std::uint64_t max = b.len >= 64 ? ~std::uint64_t{0} : (std::uint64_t{1} << b.len) - 1;
    for (std::uint64_t v = 0;; ++v) {
        if (std::find(b.values.begin(), b.values.end(), v) == b.values.end()) {
            out = v;
            return true;
        }
        if (v == max) return false;
    }
}

// v0.14: a scope's contribution to the length L of armored output: every
// `field`, `when` and `const` line written (an `optional` field whose key is
// absent aside, unless a sentinel is written for it: 0.14 ruling 12), the
// count of a locator-counted group, and, with gate blocks (0.17), only the
// lines outside any block and those of held blocks, with the held blocks'
// gate locators.
std::uint64_t armor_extent(const Pack& p, const std::vector<LineRef>& lines, const std::vector<int>& gates,
                           std::uint64_t base, const EncodeSource& src, const std::vector<char>* held) {
    std::uint64_t end = 0;
    Value mv;
    for (const auto& line : lines) {
        if (line.group) {
            if (!line.group->count_fixed) end = std::max(end, base + line.group->count_start + line.group->count_len);
            continue;
        }
        if (!gate_on(line_gate(line), held)) continue;
        if (line.field && line.field->optional && !line.field->has_absent && !src.value(*line.field, mv)) continue;
        end = std::max(end, base + bit_range(p, line.locator()).end());
    }
    if (held)
        for (int id : gates)
            if ((*held)[static_cast<std::size_t>(id)]) {
                const GateBlock& b = p.gates[static_cast<std::size_t>(id)];
                end = std::max(end, base + b.start + b.len);
            }
    return end;
}

// One scope's lines written from bit `base`. Returns the bit after the furthest
// one written or left zero by the scope. `gates`: the scope's gate blocks (0.17).
std::uint64_t bits_encode_scope(BitsOut& out, const std::vector<LineRef>& lines, const std::vector<int>& gates,
                                std::uint64_t base, const EncodeSource& src) {
    const Pack& p = out.p;
    std::vector<char> held_store;
    const std::vector<char>* held = nullptr;
    std::vector<std::uint64_t> gv;    // step 3: the gate value of each block that got one
    std::vector<char> has_gv;
    std::vector<BitRange> present;    // step 5: the bits a line with a present key covers
    if (!gates.empty()) {
        const std::size_t n = p.gates.size();
        // Step 1: a block is open when one of its `field` lines, or a line of a
        // nested open block, maps a key the entity (or the item) holds.
        std::vector<char> open(n, 0);
        for (const auto& line : lines)
            if (line.field && line.field->gate >= 0 && src.e.fields.count(line.field->key))
                for (int g = line.field->gate; g >= 0 && !open[static_cast<std::size_t>(g)];
                     g = p.gates[static_cast<std::size_t>(g)].parent)
                    open[static_cast<std::size_t>(g)] = 1;
        // Step 2: the lines outside any block. A line with a present key, a
        // `const`, a `when` or a group count writes its bits; a `default` or a
        // sentinel does not (ruling 11: the union of the ranges).
        std::string bits = out.data;
        const std::vector<char> outside(n, 0);
        std::vector<BitRange> written;
        const std::size_t need = static_cast<std::size_t>((base + fixed_extent(p, lines, false, &outside) + 7) / 8);
        if (bits.size() < need) bits.resize(need, '\0');
        write_field_lines(p, bits, out.msb, lines, base, src, &outside, &written);
        write_fixed_lines(p, bits, out.msb, lines, base, &outside, &written);
        for (const auto& line : lines)
            if (line.group && !line.group->count_fixed)
                written.push_back({base + line.group->count_start, line.group->count_len});
        // Step 3: in line order, each open block none of whose gate bits is
        // written gets its gate value, and those bits are then written.
        gv.assign(n, 0);
        has_gv.assign(n, 0);
        std::uint64_t gate_end = 0;
        for (int id : gates) {
            const GateBlock& b = p.gates[static_cast<std::size_t>(id)];
            gate_end = std::max(gate_end, base + b.start + b.len);
            if (!open[static_cast<std::size_t>(id)] || overlaps(written, base + b.start, b.len)) continue;
            std::uint64_t v = 0;
            if (!gate_value(b, v)) continue;
            gv[static_cast<std::size_t>(id)] = v;
            has_gv[static_cast<std::size_t>(id)] = 1;
            const std::size_t bytes = static_cast<std::size_t>((base + b.start + b.len + 7) / 8);
            if (bits.size() < bytes) bits.resize(bytes, '\0');
            write_bits(bits, base + b.start, b.len, v, out.msb);
            written.push_back({base + b.start, b.len});
        }
        // Step 4: each block evaluated on those bits, as decode evaluates it;
        // bits nothing wrote read as 0.
        held_store.assign(n, 0);
        eval_gates(p, bits, out.msb, base, gates, true, held_store);
        held = &held_store;
        // Step 6, second half: a key the entity holds mapped only by lines of
        // blocks that are not held.
        for (const auto& line : lines) {
            if (!line.field || !src.e.fields.count(line.field->key)) continue;
            bool mapped = false;
            for (const auto& other : lines)
                if (other.field && other.field->key == line.field->key && gate_on(other.field->gate, held)) {
                    mapped = true;
                    break;
                }
            if (!mapped)
                throw Error(ErrorKind::TransformEncode, p.format, line.field->locator,
                            line.field->key + ": every line that maps the key is in a gate block that does not hold");
        }
    }

    std::uint64_t end = base + fixed_extent(p, lines, false, held, held ? &gates : nullptr);
    out.reach(end);
    if (p.armor_sixbit) out.armor_end = std::max(out.armor_end, armor_extent(p, lines, gates, base, src, held));

    // Step 5: the lines outside any block and those of the held blocks; a held
    // block's gate value over the bits of a `default` or a sentinel and under
    // those of a line with a present key, a `const` or a `when` (ruling 7).
    write_field_lines(p, out.data, out.msb, lines, base, src, held, held ? &present : nullptr);
    if (held) {
        for (int id : gates) {
            const std::size_t i = static_cast<std::size_t>(id);
            if (!held_store[i] || !has_gv[i]) continue;
            const GateBlock& b = p.gates[i];
            for (std::uint32_t k = 0; k < b.len; ++k) {
                const std::uint64_t bit = base + b.start + k;
                if (overlaps(present, bit, 1)) continue;
                const std::uint64_t one = (gv[i] >> (out.msb ? b.len - 1 - k : k)) & 1u;
                write_bits(out.data, bit, 1, one, out.msb);
            }
        }
    }
    write_fixed_lines(p, out.data, out.msb, lines, base, held, nullptr);

    // The groups, in line order: the count over any field on its bits, then the
    // items back to back.
    for (const auto& line : lines) {
        if (!line.group) continue;
        const GroupLine& g = *line.group;
        const std::vector<Item>* items = src.list(g);
        const std::uint64_t n = items ? items->size() : 0;
        if (g.count_fixed) {
            if (!items)
                throw Error(ErrorKind::TransformEncode, p.format, g.locator,
                            "the list '" + g.list + "' is absent and the group has the fixed count " +
                                std::to_string(g.count_n));
            if (n != g.count_n)
                throw Error(ErrorKind::TransformEncode, p.format, g.locator,
                            "the list '" + g.list + "' has " + std::to_string(n) +
                                " items and the group has the fixed count " + std::to_string(g.count_n));
        } else {
            if (g.count_len < 64 && (n >> g.count_len) != 0)
                throw Error(ErrorKind::TransformEncode, p.format, g.count_locator,
                            "the list '" + g.list + "' has " + std::to_string(n) + " items, which does not fit the " +
                                std::to_string(g.count_len) + " bits of its count");
            write_bits(out.data, base + g.count_start, g.count_len, n, out.msb);
        }
        std::uint64_t at = base + g.bits_start;
        if (items) {
            const std::vector<LineRef> body = group_lines(g);
            for (const Item& item : *items) {
                out.reach(at + g.item_bits);
                out.armor_end = std::max(out.armor_end, at + g.item_bits);
                const std::uint64_t used = bits_encode_scope(out, body, g.gates, at, EncodeSource(p, g, item));
                at = std::max(at + g.item_bits, used);
            }
        }
        end = std::max(end, at);
    }
    if (held) out.checks.push_back({base, &gates, std::move(held_store)});
    return end;
}

// The gate blocks of the message: the common ones, then the selected kind's.
std::vector<int> message_gates(const Pack& p, const Kind* kind) {
    std::vector<int> out = p.common_gates;
    if (kind) out.insert(out.end(), kind->gates.begin(), kind->gates.end());
    return out;
}

}  // namespace

Entity decode_bits(const Pack& p, const std::string& bytes) {
    // Hex text in, whitespace ignored, even nibble count (engine-spec.md, I/O);
    // or, under `armor sixbit`, six bits a character (0.14), every one checked here.
    std::uint64_t armored = 0;
    const std::string data = p.armor_sixbit ? armor_to_bytes(p, bytes, armored) : hex_to_bytes(p, bytes);
    BitsIn in{p, data, p.bit_order == BitOrder::Msb,
              p.armor_sixbit ? armored : static_cast<std::uint64_t>(data.size()) * 8, false, {}, {}};

    // A `when` any of whose bits lies beyond the input does not hold.
    const Kind* kind = select_decode_kind(p, [&](const WhenLine& w) {
        const BitRange r = bit_range(p, w.locator);
        return r.end() <= in.have && read_bits(data, r.start, r.len, in.msb) == w.number;
    });

    // The message is as many whole words as the furthest required bit reaches,
    // the items of its groups included. Longer input is accepted and the extra
    // bytes ignored; shorter is malformed.
    const std::string what = "the message" + (kind ? " of kind '" + kind->name + "'" : std::string());
    Entity e;
    const std::uint64_t end = bits_decode_scope(in, active_lines(p, kind), message_gates(p, kind), 0, e, what);
    // Under armor the message is any number of bits: whole words are not required.
    const std::size_t need = p.armor_sixbit ? 0 : whole_words(p, end);
    if (data.size() < need)
        throw Error(ErrorKind::MalformedWire, p.format, "",
                    what + " is " + std::to_string(need) + " bytes, got " + std::to_string(data.size()));
    if (in.failed) throw Error(ErrorKind::TransformDecode, p.format, in.fail_locator, in.fail_detail);
    if (kind) e.kind = {p.format, kind->name};
    return e;
}

std::string encode_bits(const Pack& p, const Entity& e) {
    const Kind* kind = select_encode_kind(p, e);
    BitsOut out{p, std::string(), p.bit_order == BitOrder::Msb, 0, {}};
    const std::vector<int> gates = message_gates(p, kind);
    const std::uint64_t end = bits_encode_scope(out, active_lines(p, kind), gates, 0, EncodeSource(p, kind, e));
    // Under armor (0.14) the output is the first L bits; step 6 reads it as decode
    // would, so a gate past L does not hold.
    std::string armored;
    std::uint64_t have_bits = ~std::uint64_t{0};
    if (p.armor_sixbit) {
        armored = bytes_to_armor(out.data, out.armor_end);
        out.data = armor_to_bytes(p, armored, have_bits);
    } else {
        out.data.resize(whole_words(p, end), '\0');
    }
    // Step 6 (0.17): the output decodes to the same choice, every scope and item.
    std::vector<char> now(p.gates.size(), 0);
    for (const auto& c : out.checks) {
        eval_gates(p, out.data, out.msb, c.base, *c.gates, false, now, have_bits);
        for (int id : *c.gates)
            if (now[static_cast<std::size_t>(id)] != c.held[static_cast<std::size_t>(id)]) {
                const GateBlock& b = p.gates[static_cast<std::size_t>(id)];
                throw Error(ErrorKind::TransformEncode, p.format, b.locator,
                            "the gate 'if " + std::string(b.negated ? "!" : "") + b.locator + "' " +
                                (c.held[static_cast<std::size_t>(id)] ? "held when encoded and does not hold"
                                                                      : "did not hold when encoded and holds") +
                                " on the output");
            }
    }
    return p.armor_sixbit ? armored : bytes_to_hex(out.data);
}

}  // namespace goat_transformers::detail
