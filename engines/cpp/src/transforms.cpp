#include "transforms.hpp"

#include <cfloat>
#include <cmath>
#include <cstring>
#include <stdexcept>
#include <vector>

#include "exact.hpp"
#include "util.hpp"

namespace goat_transformers {

const char* transform_name(Transform t) {
    switch (t) {
        case Transform::String: return "string";
        case Transform::Float: return "float";
        case Transform::Int: return "int";
        case Transform::Iso8601Ms: return "iso8601_ms";
        case Transform::Iso8601Short: return "iso8601_short";
        case Transform::Iso8601S: return "iso8601_s";
        case Transform::Uint: return "uint";
        case Transform::Twos: return "twos";
        case Transform::Linscale: return "linscale";
        case Transform::Pstring: return "pstring";
        case Transform::Pvarint: return "pvarint";
        case Transform::Psint: return "psint";
        case Transform::Pdouble: return "pdouble";
        case Transform::Pfloat: return "pfloat";
        case Transform::Bool: return "bool";
        case Transform::Uscale: return "uscale";
        case Transform::Sscale: return "sscale";
        case Transform::F32: return "f32";
        case Transform::F64: return "f64";
        case Transform::Ascii: return "ascii";
        case Transform::Sixbit: return "sixbit";
        case Transform::IntW: return "int:<w>";
        case Transform::Dec: return "dec";
        case Transform::Dm: return "dm";
        case Transform::Hms: return "hms";
        case Transform::HmsDmy: return "hms_dmy";
        case Transform::Utf8: return "utf8";
        case Transform::Hex: return "hex";
        case Transform::Uiscale: return "uiscale";
        case Transform::Siscale: return "siscale";
        case Transform::Smag: return "smag";
        case Transform::Smscale: return "smscale";
        case Transform::F32scale: return "f32scale";
        case Transform::F64scale: return "f64scale";
        case Transform::CharsIcao6: return "chars:icao6";
        case Transform::CharsAis6: return "chars:ais6";
        case Transform::CharsAscii7: return "chars:ascii7";
        case Transform::CharsAscii8: return "chars:ascii8";
        case Transform::Octal: return "octal";
        case Transform::Scale: return "scale";
        case Transform::Iscale: return "iscale";
        case Transform::CborText: return "text";
        case Transform::CborBytes: return "bytes";
        case Transform::EpochS: return "epoch_s";
        case Transform::Code: return "code";
        case Transform::CodeStr: return "codestr";
        case Transform::CodeNum: return "codenum";
    }
    return "?";
}

Value Value::of_string(std::string v) {
    Value x;
    x.kind = Kind::String;
    x.s = std::move(v);
    return x;
}
Value Value::of_float(double v) {
    Value x;
    x.kind = Kind::Float;
    x.f = v;
    return x;
}
Value Value::of_int(std::int64_t v) {
    Value x;
    x.kind = Kind::Int;
    x.i = v;
    return x;
}

namespace detail {

bool parse_scale_factor(std::string_view factor, bool& fraction, double& value, double& num, double& den,
                        std::string& err, bool transform) {
    std::size_t slash = factor.find('/');
    if (slash != std::string_view::npos) {
        if (transform) {
            // 0.11 ruling 4d: two unsigned decimal integers (2c), neither zero.
            std::uint64_t n = 0, d = 0;
            if (!parse_unsigned_text(factor.substr(0, slash), n) || !parse_unsigned_text(factor.substr(slash + 1), d)) {
                err = "scale fraction is not <num>/<den> of two unsigned decimal integers";
                return false;
            }
            if (n == 0 || d == 0) {
                err = "scale fraction has a numerator or a denominator of zero";
                return false;
            }
            num = static_cast<double>(n);
            den = static_cast<double>(d);
        } else {
            // The `scale` derive function (0.11 ruling 2c): <num> integer text
            // (2a), <den> an unsigned decimal integer that is not zero. It is
            // not a transform, so 0.15 ruling 25 leaves it signed.
            std::int64_t n = 0;
            std::uint64_t d = 0;
            if (!parse_int_text(factor.substr(0, slash), n) || !parse_unsigned_text(factor.substr(slash + 1), d)) {
                err = "scale fraction is not <num>/<den> of integer text and an unsigned decimal integer";
                return false;
            }
            if (d == 0) {
                err = "scale fraction has a zero denominator";
                return false;
            }
            num = static_cast<double>(n);
            den = static_cast<double>(d);
        }
        fraction = true;
    } else {
        // Number text (0.11 ruling 2b); a transform's factor is not zero (4d).
        if (!parse_number_text(factor, value)) {
            err = "scale factor is not number text";
            return false;
        }
        if (transform && value == 0.0) {
            err = "scale factor reads as zero";
            return false;
        }
        fraction = false;
    }
    return true;
}

namespace {
// uscale / sscale arguments: <factor>[:<offset>], factor number text or <num>/<den>.
bool parse_scale_args(std::string_view args, FieldLine& f, std::string& err) {
    std::string_view factor = args, offset;
    bool have_offset = false;
    std::size_t colon = args.find(':');
    if (colon != std::string_view::npos) {
        factor = args.substr(0, colon);
        offset = args.substr(colon + 1);
        have_offset = true;
    }
    if (!parse_scale_factor(factor, f.scale_fraction, f.scale_factor, f.scale_num, f.scale_den, err, true))
        return false;
    f.scale_offset = 0.0;
    if (have_offset && !parse_number_text(offset, f.scale_offset)) {
        err = "scale offset is not number text";
        return false;
    }
    return true;
}

// uiscale / siscale / iscale arguments (v0.15, Exact factors): exactly
// <factor> or <factor>:<offset>.
bool parse_exact_args(std::string_view args, FieldLine& f, std::string& err) {
    std::string_view factor = args, offset;
    const std::size_t colon = args.find(':');
    f.exact_offset = 0;
    if (colon != std::string_view::npos) {
        factor = args.substr(0, colon);
        offset = args.substr(colon + 1);
        if (offset.find(':') != std::string_view::npos) {
            err = "an integer scale takes <factor>[:<offset>], not '" + std::string(args) + "'";
            return false;
        }
        if (!parse_exact_offset(offset, f.exact_offset, err)) return false;
    }
    return parse_exact_factor(factor, f.exact_num, f.exact_den, err);
}
}  // namespace

int parse_any_transform(std::string_view token, FieldLine& f, std::string& err) {
    f.scale_maxpos = 0.0;
    f.scale_range = 0.0;
    const std::size_t colon = token.find(':');
    const std::string_view name = token.substr(0, colon);
    const bool has_params = colon != std::string_view::npos;
    static const struct {
        const char* name;
        Transform t;
    } kPlain[] = {{"string", Transform::String},   {"float", Transform::Float},
                  {"int", Transform::Int},         {"iso8601_ms", Transform::Iso8601Ms},
                  {"iso8601_short", Transform::Iso8601Short},
                  {"iso8601_s", Transform::Iso8601S},
                  {"uint", Transform::Uint},       {"twos", Transform::Twos},
                  {"pstring", Transform::Pstring}, {"pvarint", Transform::Pvarint},
                  {"psint", Transform::Psint},     {"pdouble", Transform::Pdouble},
                  {"pfloat", Transform::Pfloat},   {"bool", Transform::Bool},
                  {"f32", Transform::F32},         {"f64", Transform::F64},
                  {"ascii", Transform::Ascii},     {"utf8", Transform::Utf8},
                  {"hex", Transform::Hex},         {"sixbit", Transform::Sixbit},
                  // v0.28, the cbor wire
                  {"text", Transform::CborText},   {"bytes", Transform::CborBytes},
                  {"epoch_s", Transform::EpochS}};
    // The text-wire transforms with parameters (v0.10): `int:<w>`, `dec`, `dm`, `hms`, `hms_dmy`.
    const int text_tf = parse_text_transform(token, f, err);
    if (text_tf != 0) return text_tf > 0 ? 0 : -1;
    for (const auto& e : kPlain)
        if (name == e.name) {
            if (has_params) {
                err = "transform '" + std::string(name) + "' takes no parameter";
                return -1;
            }
            f.transform = e.t;
            return 0;
        }
    // v0.46: every error of the list is found after the file is read (ruling 15).
    if (name == "code" || name == "codestr" || name == "codenum") {
        f.transform = name == "code" ? Transform::Code : name == "codestr" ? Transform::CodeStr : Transform::CodeNum;
        f.code_list = has_params ? std::string(token.substr(colon + 1)) : std::string();
        return 0;
    }
    if (name == "linscale") {
        // 0.11 ruling 4d: exactly <maxpos>:<range>; maxpos an unsigned decimal
        // integer of at least 1, range number text that does not read as zero.
        f.transform = Transform::Linscale;
        const std::string_view args = has_params ? token.substr(colon + 1) : std::string_view();
        const std::size_t c2 = args.find(':');
        std::uint64_t mp = 0;
        double rg = 0;
        if (!has_params || c2 == std::string_view::npos || args.find(':', c2 + 1) != std::string_view::npos) {
            err = "linscale takes exactly <maxpos>:<range>";
            return -1;
        }
        if (!parse_unsigned_text(args.substr(0, c2), mp) || mp < 1) {
            err = "the <maxpos> of linscale is not an unsigned decimal integer of at least 1";
            return -1;
        }
        if (!parse_number_text(args.substr(c2 + 1), rg) || rg == 0.0) {
            err = "the <range> of linscale is not number text other than zero";
            return -1;
        }
        f.scale_maxpos = static_cast<double>(mp);
        f.scale_range = rg;
        return 0;
    }
    if (name == "uscale" || name == "sscale") {
        f.transform = name == "uscale" ? Transform::Uscale : Transform::Sscale;
        if (!has_params) {
            err = std::string(name) + " takes a factor";
            return -1;
        }
        const std::string_view args = token.substr(colon + 1);
        const std::size_t c2 = args.find(':');
        if (c2 != std::string_view::npos && args.find(':', c2 + 1) != std::string_view::npos) {
            err = std::string(name) + " takes a factor and an optional offset";
            return -1;
        }
        return parse_scale_args(args, f, err) ? 0 : -1;
    }
    // v0.15. A known name with parameters that do not parse is bad-directive.
    {
        const std::string_view args = has_params ? token.substr(colon + 1) : std::string_view();
        static const struct {
            const char* name;
            Transform t;
            int params;  // 0 none, 1 exact factor, 2 float factor, 3 character set
        } kNew[] = {{"uiscale", Transform::Uiscale, 1}, {"siscale", Transform::Siscale, 1},
                    {"iscale", Transform::Iscale, 1},   {"smag", Transform::Smag, 0},
                    {"octal", Transform::Octal, 0},     {"smscale", Transform::Smscale, 2},
                    {"f32scale", Transform::F32scale, 2}, {"f64scale", Transform::F64scale, 2},
                    {"scale", Transform::Scale, 2},     {"chars", Transform::CharsIcao6, 3}};
        for (const auto& e : kNew) {
            if (name != e.name) continue;
            bool ok = true;
            f.transform = e.t;
            switch (e.params) {
                case 0:
                    if (has_params) {
                        err = "transform '" + std::string(name) + "' takes no parameter";
                        ok = false;
                    }
                    break;
                case 1:
                    if (!has_params) {
                        err = "transform '" + std::string(name) + "' needs <factor>[:<offset>]";
                        ok = false;
                    } else {
                        ok = parse_exact_args(args, f, err);
                    }
                    break;
                case 2:
                    if (!has_params) {
                        err = "transform '" + std::string(name) + "' needs <factor>[:<offset>]";
                        ok = false;
                    } else if (args.find(':') != std::string_view::npos &&
                               args.find(':', args.find(':') + 1) != std::string_view::npos) {
                        err = "transform '" + std::string(name) + "' takes a factor and an optional offset";
                        ok = false;
                    } else {
                        ok = parse_scale_args(args, f, err);
                    }
                    break;
                case 3:
                    if (args == "icao6") f.transform = Transform::CharsIcao6;
                    else if (args == "ais6") f.transform = Transform::CharsAis6;
                    else if (args == "ascii7") f.transform = Transform::CharsAscii7;
                    else if (args == "ascii8") f.transform = Transform::CharsAscii8;  // v0.22
                    else {
                        err = "transform 'chars' needs a character set icao6, ais6 or ascii7, not '" +
                              std::string(args) + "'";
                        ok = false;
                    }
                    break;
            }
            if (!ok) {
                err += " ('" + std::string(token) + "')";
                return -1;
            }
            return 0;
        }
    }
    err = "unknown transform '" + std::string(token) + "'";
    return -2;
}

namespace {
// A parameter of a text transform: decimal digits whose value lies in [lo, hi].
bool text_param(std::string_view s, int lo, int hi, int& out) {
    if (s.empty() || s.size() > 3) return false;
    int v = 0;
    for (char c : s) {
        if (c < '0' || c > '9') return false;
        v = v * 10 + (c - '0');
    }
    if (v < lo || v > hi) return false;
    out = v;
    return true;
}

std::vector<std::string_view> split_colons(std::string_view s) {
    std::vector<std::string_view> out;
    std::size_t at = 0;
    for (;;) {
        const std::size_t c = s.find(':', at);
        out.push_back(s.substr(at, c == std::string_view::npos ? std::string_view::npos : c - at));
        if (c == std::string_view::npos) break;
        at = c + 1;
    }
    return out;
}
}  // namespace

int parse_text_transform(std::string_view token, FieldLine& f, std::string& err) {
    const std::vector<std::string_view> parts = split_colons(token);
    const std::string_view name = parts[0];
    const bool is_int = name == "int" && parts.size() > 1;
    if (!is_int && name != "dec" && name != "dm" && name != "hms" && name != "hms_dmy") return 0;
    const std::size_t nparams = parts.size() - 1;
    bool ok = false;
    f.text_w = 0;
    f.text_f = 0;
    f.text_d = 0;
    if (is_int) {
        f.transform = Transform::IntW;
        ok = nparams == 1 && text_param(parts[1], 1, 20, f.text_w);
    } else if (name == "dec") {
        f.transform = Transform::Dec;
        ok = (nparams == 1 || nparams == 2) && text_param(parts[1], 0, 9, f.text_f) &&
             (nparams == 1 || text_param(parts[2], 1, 20, f.text_w));
    } else if (name == "dm") {
        f.transform = Transform::Dm;
        ok = nparams == 3 && text_param(parts[1], 1, 3, f.text_d) && text_param(parts[2], 0, 9, f.text_f) &&
             parts[3].size() == 2 && parts[3][0] >= 'A' && parts[3][0] <= 'Z' && parts[3][1] >= 'A' &&
             parts[3][1] <= 'Z' && parts[3][0] != parts[3][1];
        if (ok) {
            f.text_p = parts[3][0];
            f.text_n = parts[3][1];
        }
    } else {
        f.transform = name == "hms" ? Transform::Hms : Transform::HmsDmy;
        ok = nparams == 1 && text_param(parts[1], 0, 3, f.text_f);
    }
    if (!ok) {
        err = "transform '" + std::string(token) + "' has parameters that are not valid";
        return -1;
    }
    return 1;
}

bool transform_is_text_only(Transform t) {
    return t == Transform::IntW || t == Transform::Dec || t == Transform::Dm || t == Transform::Hms ||
           t == Transform::HmsDmy;
}

// `hex` is also a transform of the bits wire from 0.22.
bool transform_is_tlv_only(Transform t) { return t == Transform::Utf8; }

bool transform_is_cbor_only(Transform t) {
    return t == Transform::CborText || t == Transform::CborBytes || t == Transform::EpochS;
}

bool transform_is_textual(Transform t) {
    return t == Transform::String || t == Transform::Iso8601Ms || t == Transform::Iso8601Short ||
           t == Transform::Iso8601S || t == Transform::CodeStr || t == Transform::CodeNum;
}

bool transform_is_code(Transform t) {
    return t == Transform::Code || t == Transform::CodeStr || t == Transform::CodeNum;
}

bool transform_is_bits(Transform t) {
    switch (t) {
        case Transform::Uint:
        case Transform::Twos:
        case Transform::Linscale:
        case Transform::Uscale:
        case Transform::Sscale:
        case Transform::F32:
        case Transform::F64:
        case Transform::Ascii:
        case Transform::Sixbit:
        case Transform::Uiscale:
        case Transform::Siscale:
        case Transform::Smag:
        case Transform::Smscale:
        case Transform::F32scale:
        case Transform::F64scale:
        case Transform::CharsIcao6:
        case Transform::CharsAis6:
        case Transform::CharsAscii7:
        case Transform::CharsAscii8:  // v0.22
        case Transform::Hex:          // v0.22: on bits as on tlv
        case Transform::Code:         // v0.46
        case Transform::CodeNum:      // v0.46: on the text wires too
        case Transform::Octal: return true;
        default: return false;
    }
}

bool transform_is_v015(Transform t) {
    switch (t) {
        case Transform::Uiscale:
        case Transform::Siscale:
        case Transform::Smag:
        case Transform::Smscale:
        case Transform::F32scale:
        case Transform::F64scale:
        case Transform::CharsIcao6:
        case Transform::CharsAis6:
        case Transform::CharsAscii7:
        case Transform::CharsAscii8:  // v0.22: a set of 0.15's `chars`, bits only as they are
        case Transform::Octal:
        case Transform::Scale:
        case Transform::Iscale: return true;
        default: return false;
    }
}

bool transform_is_text_scale(Transform t) { return t == Transform::Scale || t == Transform::Iscale; }

unsigned chars_width(Transform t) {
    switch (t) {
        case Transform::CharsIcao6:
        case Transform::CharsAis6: return 6;
        case Transform::CharsAscii7: return 7;
        case Transform::CharsAscii8: return 8;  // v0.22
        default: return 0;
    }
}

bool bits_len_allowed(Transform t, std::uint32_t len) {
    if (const unsigned w = chars_width(t)) return len >= w && len <= 2040 && len % w == 0;
    switch (t) {
        case Transform::F32:
        case Transform::F32scale: return len == 32;
        case Transform::F64:
        case Transform::F64scale: return len == 64;
        case Transform::Ascii: return len >= 8 && len <= 2040 && len % 8 == 0;
        case Transform::Sixbit: return len >= 6 && len <= 1530 && len % 6 == 0;  // v0.14
        case Transform::Smag:
        case Transform::Smscale: return len >= 2 && len <= 64;
        case Transform::Octal: return len >= 3 && len <= 63 && len % 3 == 0;
        case Transform::Hex: return len >= 4 && len <= 2040 && len % 4 == 0;  // v0.22
        default: return len >= 1 && len <= 64;
    }
}

bool transform_is_protobuf(Transform t) {
    return t == Transform::Pstring || t == Transform::Pvarint || t == Transform::Psint ||
           t == Transform::Pdouble || t == Transform::Pfloat;
}

int protobuf_wire_type(Transform t) {
    switch (t) {
        case Transform::Pstring: return 2;
        case Transform::Pvarint: return 0;
        case Transform::Psint: return 0;
        case Transform::Pdouble: return 1;
        case Transform::Pfloat: return 5;
        default: return -1;
    }
}

namespace {
Value decode_text_scale(const FieldLine& f, const std::string& text);
std::string encode_text_scale(const FieldLine& f, const Value& v);
Value decode_code_text(const FieldLine& f, const std::string& text);
std::string encode_code_text(const FieldLine& f, const Value& v);
}  // namespace

Value decode_json_number(const FieldLine& f, const std::string& text) {
    switch (f.transform) {
        case Transform::Float: {
            double d;
            if (!parse_number_text(text, d))
                throw std::invalid_argument("the number " + text + " has no finite nearest double");
            return Value::of_float(d);
        }
        case Transform::Int: {
            std::int64_t v;
            if (!json_exact_int(text, v))
                throw std::invalid_argument("the number " + text + " is not an integer within 64 bits");
            return Value::of_int(v);
        }
        default: return decode_value(f, text);
    }
}

Value decode_value(const FieldLine& f, const std::string& text) {
    const Transform t = f.transform;
    if (transform_is_text_scale(t)) return decode_text_scale(f, text);
    switch (t) {
        case Transform::String: return Value::of_string(text);
        case Transform::CodeStr:
        case Transform::CodeNum: return decode_code_text(f, text);
        // 0.11 ruling 2c: number text (2b) and integer text (2a), nothing trimmed.
        case Transform::Float: {
            double d;
            if (!parse_number_text(text, d)) throw std::invalid_argument("not number text: \"" + text + "\"");
            return Value::of_float(d);
        }
        case Transform::Int: {
            std::int64_t v;
            if (!parse_int_text(text, v)) throw std::invalid_argument("not integer text: \"" + text + "\"");
            return Value::of_int(v);
        }
        case Transform::Iso8601Ms:
        case Transform::Iso8601Short:  // 0.18: decode is that of iso8601_ms
        case Transform::Iso8601S: {    // 0.26 ruling 2: likewise
            std::int64_t ms;
            if (!parse_iso8601_ms(text, ms))
                throw std::invalid_argument("not an ISO 8601 time: \"" + text + "\"");
            return Value::of_int(ms);
        }
        default: break;
    }
    throw std::invalid_argument("not a text transform");
}

namespace {
bool integral_double(double d, std::int64_t& out) {
    if (!std::isfinite(d) || std::trunc(d) != d) return false;
    if (d < -9223372036854775808.0 || d >= 9223372036854775808.0) return false;
    out = static_cast<std::int64_t>(d);
    return true;
}

// Low `len` bits mask (len is 1..=64).
std::uint64_t low_mask(std::uint32_t len) {
    return len >= 64 ? ~std::uint64_t{0} : ((std::uint64_t{1} << len) - 1);
}

// Sign-extend the `len`-bit two's-complement value in `raw` to a signed integer.
std::int64_t sign_extend(std::uint64_t raw, std::uint32_t len) {
    raw &= low_mask(len);
    // The sign bits are set in the unsigned value: no signed arithmetic, which
    // overflows for a negative 63-bit value.
    if (len < 64 && (raw & (std::uint64_t{1} << (len - 1)))) raw |= ~low_mask(len);
    return static_cast<std::int64_t>(raw);
}

}  // namespace

// Model value coerced to a signed integer (Int direct; integral Float; decimal String).
std::int64_t model_int(const Value& v) {
    switch (v.kind) {
        case Value::Kind::Int: return v.i;
        case Value::Kind::Float: {
            std::int64_t n;
            if (!integral_double(v.f, n)) throw std::invalid_argument("not integral: " + format_double(v.f));
            return n;
        }
        case Value::Kind::String: {
            std::int64_t n;
            if (!parse_int(v.s, n)) throw std::invalid_argument("not an integer: \"" + v.s + "\"");
            return n;
        }
    }
    throw std::invalid_argument("unknown value kind");
}

// Model value coerced to a double (Float direct; Int widened; decimal String).
double model_double(const Value& v) {
    switch (v.kind) {
        case Value::Kind::Float: return v.f;
        case Value::Kind::Int: return static_cast<double>(v.i);
        case Value::Kind::String: {
            double d;
            if (!parse_double(v.s, d)) throw std::invalid_argument("not a decimal number: \"" + v.s + "\"");
            return d;
        }
    }
    throw std::invalid_argument("unknown value kind");
}

namespace {
// v * factor + offset, in doubles and in the order of ruling 1 of 0.5.
double scale_decode(const FieldLine& f, double v) {
    double x = f.scale_fraction ? v * f.scale_num / f.scale_den : v * f.scale_factor;
    return x + f.scale_offset;
}
// The quotient before rounding (0.11 ruling 4); the float scales of 0.15 take
// it unrounded (0.15 ruling 8).
double scale_encode(const FieldLine& f, double x) {
    double d = x - f.scale_offset;
    return f.scale_fraction ? d * f.scale_den / f.scale_num : d / f.scale_factor;
}

// A model float is always finite: infinity and not-a-number on the wire are refused.
double finite_wire(double d) {
    if (!std::isfinite(d)) throw std::invalid_argument("the wire holds infinity or not-a-number");
    return d;
}

// A double narrowed to a single; a value outside single range is refused.
float narrow_single(double d) {
    if (!std::isfinite(d) || std::fabs(d) > static_cast<double>(FLT_MAX))
        throw std::invalid_argument("value outside the range of a single: " + (std::isfinite(d) ? format_double(d) : std::string("not finite")));
    return static_cast<float>(d);
}

double finite_result(double d) {
    if (!std::isfinite(d)) throw std::invalid_argument("the scaled value is not finite");
    return d;
}

Value decode_text_scale(const FieldLine& f, const std::string& text) {
    if (f.transform == Transform::Scale) {
        double d;
        // The number as `float` decodes it: number text (0.11 ruling 2b).
        if (!parse_number_text(text, d)) throw std::invalid_argument("not number text: \"" + text + "\"");
        return Value::of_float(finite_result(scale_decode(f, d)));
    }
    std::int64_t out = 0;
    std::string why;
    if (!iscale_decode(text, f.exact_num, f.exact_den, f.exact_offset, out, why)) throw std::invalid_argument(why);
    return Value::of_int(out);
}

std::string encode_text_scale(const FieldLine& f, const Value& v) {
    if (f.transform == Transform::Scale) return format_double(finite_result(scale_encode(f, model_double(v))));
    std::string out, why;
    if (!iscale_encode(model_int(v), f.exact_num, f.exact_den, f.exact_offset, out, why))
        throw std::invalid_argument(why);
    return out;
}

// smag: the top bit of the `len` bits is the sign, the others the magnitude.
std::uint64_t smag_bits(bool neg, std::uint64_t mag, std::uint32_t len) {
    if (mag >= (std::uint64_t{1} << (len - 1)))
        throw std::invalid_argument("magnitude " + std::to_string(mag) + " does not fit the " +
                                    std::to_string(len - 1) + " magnitude bits");
    return (neg && mag != 0 ? std::uint64_t{1} << (len - 1) : 0) | mag;
}

std::int64_t smag_value(std::uint64_t raw, std::uint32_t len) {
    const std::uint64_t mag = raw & low_mask(len - 1);
    const bool neg = (raw >> (len - 1)) & 1u;
    return neg ? -static_cast<std::int64_t>(mag) : static_cast<std::int64_t>(mag);
}

// Text of a model value for the string transforms (chars, octal).
std::string model_text(const Value& v) {
    switch (v.kind) {
        case Value::Kind::String: return v.s;
        case Value::Kind::Int: return std::to_string(v.i);
        case Value::Kind::Float:
            try {
                return format_double(v.f);
            } catch (const std::domain_error& e) {
                throw std::invalid_argument(e.what());
            }
    }
    return std::string();
}

// ---- v0.46: one code per position, first position first

// Text -> codes: exactly one character per position, each in its set.
std::vector<unsigned> codes_of_text(const FieldLine& f, const std::string& text) {
    if (text.size() != f.code_sets.size())
        throw std::invalid_argument("text \"" + text + "\" is not exactly " + std::to_string(f.code_sets.size()) +
                                    " characters");
    std::vector<unsigned> codes(text.size());
    for (std::size_t k = 0; k < text.size(); ++k) {
        const std::size_t at = f.code_sets[k]->chars.find(text[k]);
        if (at == std::string::npos)
            throw std::invalid_argument("character " + std::to_string(k) + " of \"" + text +
                                        "\" is not in the set '" + f.code_sets[k]->name + "'");
        codes[k] = static_cast<unsigned>(at);
    }
    return codes;
}

std::string text_of_codes(const FieldLine& f, const std::vector<unsigned>& codes) {
    std::string text(codes.size(), ' ');
    for (std::size_t k = 0; k < codes.size(); ++k) text[k] = f.code_sets[k]->chars[codes[k]];
    return text;
}

// The mixed-radix number; the load check keeps the product of the sizes at or below 2^63.
std::int64_t number_of_codes(const FieldLine& f, const std::vector<unsigned>& codes) {
    std::uint64_t v = 0;
    for (std::size_t k = 0; k < codes.size(); ++k) v = v * f.code_sets[k]->chars.size() + codes[k];
    return static_cast<std::int64_t>(v);
}

std::vector<unsigned> codes_of_number(const FieldLine& f, std::int64_t n) {
    std::uint64_t rest = static_cast<std::uint64_t>(n);
    std::vector<unsigned> codes(f.code_sets.size());
    if (n >= 0)
        for (std::size_t k = codes.size(); k-- > 0;) {
            const std::uint64_t size = f.code_sets[k]->chars.size();
            codes[k] = static_cast<unsigned>(rest % size);
            rest /= size;
        }
    if (n < 0 || rest != 0)
        throw std::invalid_argument("the number " + std::to_string(n) + " is outside the codes of its positions");
    return codes;
}

// The model value -> codes: `codenum` from its integer, the others from their text.
std::vector<unsigned> codes_of_value(const FieldLine& f, const Value& v) {
    if (f.transform == Transform::CodeNum) return codes_of_number(f, model_int(v));
    return codes_of_text(f, model_text(v));
}

Value value_of_codes(const FieldLine& f, const std::vector<unsigned>& codes) {
    if (f.transform == Transform::CodeNum) return Value::of_int(number_of_codes(f, codes));
    return Value::of_string(text_of_codes(f, codes));
}

Value decode_code_text(const FieldLine& f, const std::string& text) { return value_of_codes(f, codes_of_text(f, text)); }

std::string encode_code_text(const FieldLine& f, const Value& v) { return text_of_codes(f, codes_of_value(f, v)); }

// The codes of a bits field, the first position in the most significant bits.
Value decode_code_bits(const FieldLine& f, std::uint64_t raw) {
    std::vector<unsigned> codes(f.code_sets.size());
    for (std::size_t k = codes.size(); k-- > 0;) {
        const CharSet& s = *f.code_sets[k];
        codes[k] = static_cast<unsigned>(raw & low_mask(s.width));
        raw >>= s.width;
        if (codes[k] >= s.chars.size())
            throw std::invalid_argument("position " + std::to_string(k) + " holds the code " +
                                        std::to_string(codes[k]) + ", which the set '" + s.name + "' does not have");
    }
    return value_of_codes(f, codes);
}

std::uint64_t encode_code_bits(const FieldLine& f, const Value& v) {
    const std::vector<unsigned> codes = codes_of_value(f, v);
    std::uint64_t raw = 0;
    for (std::size_t k = 0; k < codes.size(); ++k) raw = (raw << f.code_sets[k]->width) | codes[k];
    return raw;
}
}  // namespace

namespace {
// One character of a `chars` set: the code -> the character; false for a code
// the set does not define. Code 0 of ascii7 and ascii8 is NUL.
bool chars_decode_one(Transform t, unsigned c, char& ch) {
    switch (t) {
        case Transform::CharsIcao6:
            if (c >= 1 && c <= 26) ch = static_cast<char>('A' + c - 1);
            else if (c == 32 || (c >= 48 && c <= 57)) ch = static_cast<char>(c);
            else return false;
            return true;
        case Transform::CharsAis6: ch = static_cast<char>(c < 32 ? c + 64 : c); return true;
        case Transform::CharsAscii7:
        case Transform::CharsAscii8:
            if (c == 0 || (c >= 32 && c <= 126)) ch = static_cast<char>(c);
            else return false;
            return true;
        default: return false;
    }
}

// The code of a character in a `chars` set; -1 when the set cannot hold it.
// NUL is held by ascii7 and ascii8 only when `nul` says so (a terminator
// other than 0, 0.22 rulings 6, 20 and 21).
int chars_encode_one(Transform t, unsigned c, bool nul) {
    switch (t) {
        case Transform::CharsIcao6:
            if (c >= 'A' && c <= 'Z') return static_cast<int>(c - 'A' + 1);
            if (c == ' ' || (c >= '0' && c <= '9')) return static_cast<int>(c);
            return -1;
        case Transform::CharsAis6:
            if (c >= 32 && c <= 63) return static_cast<int>(c);
            if (c >= 64 && c <= 95) return static_cast<int>(c - 64);
            return -1;
        case Transform::CharsAscii7:
        case Transform::CharsAscii8:
            if (c >= 32 && c <= 126) return static_cast<int>(c);
            if (c == 0 && nul) return 0;
            return -1;
        default: return -1;
    }
}

std::string chars_text(Transform t, const std::vector<std::uint8_t>& codes) {
    std::string text;
    text.reserve(codes.size());
    for (std::size_t k = 0; k < codes.size(); ++k) {
        char ch = 0;
        if (!chars_decode_one(t, codes[k], ch))
            throw std::invalid_argument("character " + std::to_string(k) + " has the code " +
                                        std::to_string(codes[k]) + ", which " + transform_name(t) + " does not define");
        text += ch;
    }
    return text;
}

std::vector<std::uint8_t> chars_codes(Transform t, const std::string& text, bool nul) {
    std::vector<std::uint8_t> codes;
    codes.reserve(text.size());
    for (std::size_t k = 0; k < text.size(); ++k) {
        const unsigned c = static_cast<unsigned char>(text[k]);
        const int code = chars_encode_one(t, c, nul);
        if (code < 0)
            throw std::invalid_argument("character " + std::to_string(k) + " (byte " + std::to_string(c) +
                                        ") is not in " + transform_name(t));
        codes.push_back(static_cast<std::uint8_t>(code));
    }
    return codes;
}
}  // namespace

Value decode_chars(Transform t, const std::vector<std::uint8_t>& codes) {
    std::string text = chars_text(t, codes);
    std::size_t n = text.size();
    if (t == Transform::CharsAscii7 || t == Transform::CharsAscii8) {
        const std::size_t nul = text.find('\0');
        if (nul != std::string::npos) {
            if (text.find_first_not_of('\0', nul) != std::string::npos)
                throw std::invalid_argument("a NUL is followed by a character that is not NUL");
            n = nul;
        }
    } else {
        while (n > 0 && (text[n - 1] == ' ' || (t == Transform::CharsAis6 && text[n - 1] == '@'))) --n;
    }
    text.resize(n);
    return Value::of_string(std::move(text));
}

std::vector<std::uint8_t> encode_chars(Transform t, const Value& v, std::size_t count) {
    const std::string text = model_text(v);
    if (text.size() > count)
        throw std::invalid_argument("text of " + std::to_string(text.size()) + " characters does not fit " +
                                    std::to_string(count));
    std::vector<std::uint8_t> codes = chars_codes(t, text, false);
    codes.resize(count, chars_padding(t));
    return codes;
}

std::uint8_t chars_padding(Transform t) { return t == Transform::CharsIcao6 ? 32 : 0; }

bool parse_term_code(const std::string& s, std::uint64_t& out) {
    if (s.empty()) return false;
    out = 0;
    for (char c : s) {
        if (c < '0' || c > '9') return false;
        if (out <= (~std::uint64_t{0} - 9) / 10) out = out * 10 + static_cast<std::uint64_t>(c - '0');
        else out = ~std::uint64_t{0};
    }
    return true;
}

Value decode_chars_exact(Transform t, const std::vector<std::uint8_t>& codes) {
    return Value::of_string(chars_text(t, codes));
}

std::vector<std::uint8_t> encode_chars_until(Transform t, const Value& v, std::size_t max, unsigned code) {
    const std::string text = model_text(v);
    if (text.size() > max)
        throw std::invalid_argument("text of " + std::to_string(text.size()) + " characters is longer than " +
                                    std::to_string(max));
    std::vector<std::uint8_t> codes = chars_codes(t, text, code != 0);
    for (std::size_t k = 0; k < codes.size(); ++k)
        if (codes[k] == code)
            throw std::invalid_argument("character " + std::to_string(k) + " is the terminator's character (code " +
                                        std::to_string(code) + ")");
    return codes;
}

Value decode_bits_value(const FieldLine& f, std::uint64_t raw, std::uint32_t len) {
    raw &= low_mask(len);
    switch (f.transform) {
        case Transform::Uint:
            return Value::of_int(static_cast<std::int64_t>(raw));  // 64 bits: same bit pattern
        case Transform::Twos:
            return Value::of_int(sign_extend(raw, len));
        case Transform::Linscale: {
            double v = static_cast<double>(sign_extend(raw, len));
            return Value::of_float(v / f.scale_maxpos * f.scale_range);
        }
        case Transform::Uscale:
            return Value::of_float(scale_decode(f, static_cast<double>(raw)));
        case Transform::Sscale:
            return Value::of_float(scale_decode(f, static_cast<double>(sign_extend(raw, len))));
        case Transform::F32: {
            std::uint32_t u = static_cast<std::uint32_t>(raw);
            float fl;
            std::memcpy(&fl, &u, sizeof(fl));
            return Value::of_float(finite_wire(static_cast<double>(fl)));
        }
        case Transform::F64: {
            double d;
            std::memcpy(&d, &raw, sizeof(d));
            return Value::of_float(finite_wire(d));
        }
        case Transform::Uiscale:
        case Transform::Siscale: {
            const Big v = f.transform == Transform::Uiscale ? Big::of_u64(raw) : Big::of_i64(sign_extend(raw, len));
            std::int64_t out = 0;
            if (!exact_scale(v, f.exact_num, f.exact_den, f.exact_offset, out))
                throw std::invalid_argument("the scaled value is outside the signed 64-bit range");
            return Value::of_int(out);
        }
        case Transform::Smag: return Value::of_int(smag_value(raw, len));
        case Transform::Smscale:
            return Value::of_float(finite_result(scale_decode(f, static_cast<double>(smag_value(raw, len)))));
        case Transform::F32scale: {
            std::uint32_t u = static_cast<std::uint32_t>(raw);
            float fl;
            std::memcpy(&fl, &u, sizeof(fl));
            return Value::of_float(finite_result(scale_decode(f, static_cast<double>(fl))));
        }
        case Transform::F64scale: {
            double d;
            std::memcpy(&d, &raw, sizeof(d));
            return Value::of_float(finite_result(scale_decode(f, d)));
        }
        case Transform::Octal: {
            std::string s(len / 3, '0');
            for (std::size_t k = s.size(); k-- > 0; raw >>= 3) s[k] = static_cast<char>('0' + (raw & 7u));
            return Value::of_string(std::move(s));
        }
        case Transform::Code:
        case Transform::CodeNum: return decode_code_bits(f, raw);
        default:
            break;
    }
    // Unreachable for a validated bits pack.
    return Value::of_int(static_cast<std::int64_t>(raw));
}

std::uint64_t encode_bits_value(const FieldLine& f, const Value& v, std::uint32_t len) {
    const std::uint64_t mask = low_mask(len);
    // 0.11 ruling 4b: a value outside the field's range is refused, never
    // narrowed. `round` is half away from zero, exact for every double (4a).
    auto unsigned_fits = [&](double r) { return r >= 0.0 && r < std::ldexp(1.0, static_cast<int>(len)); };
    auto signed_fits = [&](double r) {
        const double half = std::ldexp(1.0, static_cast<int>(len) - 1);
        return r >= -half && r < half;
    };
    auto refuse = [&](const std::string& what) -> std::invalid_argument {
        return std::invalid_argument("value outside the range of " + what + " " + std::to_string(len) + "-bit field");
    };
    switch (f.transform) {
        case Transform::Uint: {
            const std::int64_t n = model_int(v);
            // 64 bits: every model integer, as its two's-complement pattern (ruling 2 of 0.5).
            if (len < 64 && (n < 0 || static_cast<std::uint64_t>(n) > mask)) throw refuse("an unsigned");
            return static_cast<std::uint64_t>(n) & mask;
        }
        case Transform::Twos: {
            const std::int64_t n = model_int(v);
            if (len < 64) {
                const std::int64_t lo = -(std::int64_t{1} << (len - 1)), hi = (std::int64_t{1} << (len - 1)) - 1;
                if (n < lo || n > hi) throw refuse("a signed");
            }
            return static_cast<std::uint64_t>(n) & mask;
        }
        case Transform::Linscale: {
            const double q = model_double(v) / f.scale_range * f.scale_maxpos;
            if (!std::isfinite(q)) throw std::invalid_argument("the scaled value is not finite");
            const double r = std::round(q);
            if (!signed_fits(r)) throw refuse("a signed");
            return static_cast<std::uint64_t>(static_cast<std::int64_t>(r)) & mask;
        }
        case Transform::Uscale: {
            const double q = scale_encode(f, model_double(v));
            if (!std::isfinite(q)) throw std::invalid_argument("the scaled value is not finite");
            const double r = std::round(q);
            if (!unsigned_fits(r)) throw refuse("an unsigned");
            return static_cast<std::uint64_t>(r) & mask;
        }
        case Transform::Sscale: {
            const double q = scale_encode(f, model_double(v));
            if (!std::isfinite(q)) throw std::invalid_argument("the scaled value is not finite");
            const double r = std::round(q);
            if (!signed_fits(r)) throw refuse("a signed");
            return static_cast<std::uint64_t>(static_cast<std::int64_t>(r)) & mask;
        }
        case Transform::F32: {
            float fl = narrow_single(model_double(v));
            std::uint32_t u = 0;
            std::memcpy(&u, &fl, sizeof(fl));
            return u;
        }
        case Transform::F64: {
            double d = model_double(v);
            if (!std::isfinite(d)) throw std::invalid_argument("a model float is finite");
            std::uint64_t u = 0;
            std::memcpy(&u, &d, sizeof(d));
            return u;
        }
        case Transform::Uiscale:
        case Transform::Siscale: {
            const Big r = exact_unscale(model_int(v), f.exact_num, f.exact_den, f.exact_offset);
            if (f.transform == Transform::Uiscale) {
                std::uint64_t u = 0;
                if (!big_to_u64(r, u) || (len < 64 && (u >> len) != 0))
                    throw std::invalid_argument("value outside the range of an unsigned " + std::to_string(len) +
                                                "-bit field");
                return u;
            }
            std::int64_t n = 0;
            const std::int64_t half = len == 64 ? 0 : std::int64_t{1} << (len - 1);
            if (!big_to_i64(r, n) || (len < 64 && (n < -half || n >= half)))
                throw std::invalid_argument("value outside the range of a signed " + std::to_string(len) +
                                            "-bit field");
            return static_cast<std::uint64_t>(n) & mask;
        }
        case Transform::Smag: {
            const std::int64_t x = model_int(v);
            const std::uint64_t mag = x < 0 ? ~static_cast<std::uint64_t>(x) + 1 : static_cast<std::uint64_t>(x);
            return smag_bits(x < 0, mag, len);
        }
        case Transform::Smscale: {
            // round((x - offset) / factor) as sscale computes it; the sign of the rounded integer.
            const double q = scale_encode(f, model_double(v));
            if (!std::isfinite(q)) throw std::invalid_argument("the scaled value is not finite");
            const double r = std::round(q);  // half away from zero (0.11 ruling 4a)
            if (std::fabs(r) >= std::ldexp(1.0, static_cast<int>(len) - 1))
                throw std::invalid_argument("value outside the range of a " + std::to_string(len) +
                                            "-bit sign and magnitude");
            return smag_bits(r < 0, static_cast<std::uint64_t>(std::fabs(r)), len);
        }
        case Transform::F32scale: {
            float fl = narrow_single(finite_result(scale_encode(f, model_double(v))));
            std::uint32_t u = 0;
            std::memcpy(&u, &fl, sizeof(fl));
            return u;
        }
        case Transform::F64scale: {
            double d = finite_result(scale_encode(f, model_double(v)));
            std::uint64_t u = 0;
            std::memcpy(&u, &d, sizeof(d));
            return u;
        }
        case Transform::Octal: {
            const std::string text = model_text(v);
            if (text.size() != len / 3)
                throw std::invalid_argument("octal text \"" + text + "\" is not exactly " + std::to_string(len / 3) +
                                            " digits");
            std::uint64_t u = 0;
            for (char c : text) {
                if (c < '0' || c > '7') throw std::invalid_argument("octal text \"" + text + "\" has a digit not 0-7");
                u = (u << 3) | static_cast<std::uint64_t>(c - '0');
            }
            return u;
        }
        case Transform::Code:
        case Transform::CodeNum: return encode_code_bits(f, v);
        default:
            break;
    }
    throw std::invalid_argument("not a bits transform");
}

Value decode_uper_int(const FieldLine& f, std::int64_t v) {
    switch (f.transform) {
        case Transform::Uscale:
        case Transform::Sscale: return Value::of_float(scale_decode(f, static_cast<double>(v)));
        default: return Value::of_int(v);
    }
}

std::int64_t encode_uper_int(const FieldLine& f, const Value& v) {
    if (f.transform != Transform::Uscale && f.transform != Transform::Sscale) return model_int(v);
    // scale_encode gives the quotient; `round` is half away from zero (0.11 ruling 4a).
    const double r = std::round(scale_encode(f, model_double(v)));
    if (!std::isfinite(r) || r < -9223372036854775808.0 || r >= 9223372036854775808.0)
        throw std::invalid_argument("the scaled value is not an integer of 64 signed bits");
    return static_cast<std::int64_t>(r);
}

Value decode_ascii(const std::string& bytes, bool trim) {
    std::size_t n = bytes.size();
    while (n > 0 && bytes[n - 1] == '\0') --n;
    if (trim)
        while (n > 0 && bytes[n - 1] == ' ') --n;
    for (std::size_t k = 0; k < n; ++k) {
        const unsigned char c = static_cast<unsigned char>(bytes[k]);
        if (c > 0x7E || c < 0x20)
            throw std::invalid_argument("byte " + std::to_string(k) + " (" + std::to_string(c) +
                                        ") is not printable ASCII");
    }
    return Value::of_string(bytes.substr(0, n));
}

Value decode_sixbit(const std::string& codes, bool trim) {
    std::string text;
    text.reserve(codes.size());
    for (char c : codes) {
        const unsigned v = static_cast<unsigned char>(c) & 0x3Fu;
        text += static_cast<char>(v < 32 ? 0x40 + v : v);
    }
    std::size_t n = text.size();
    if (trim)
        while (n > 0 && (text[n - 1] == '@' || text[n - 1] == ' ')) --n;
    else
        while (n > 0 && text[n - 1] == '@') --n;
    text.resize(n);
    return Value::of_string(text);
}

std::string encode_sixbit(const Value& v, std::size_t nchars) {
    std::string text;
    switch (v.kind) {
        case Value::Kind::String: text = v.s; break;
        case Value::Kind::Int: text = std::to_string(v.i); break;
        case Value::Kind::Float:
            try {
                text = format_double(v.f);
            } catch (const std::domain_error& e) {
                throw std::invalid_argument(e.what());
            }
            break;
    }
    if (text.size() > nchars)
        throw std::invalid_argument("text of " + std::to_string(text.size()) + " characters does not fit " +
                                    std::to_string(nchars) + " six-bit characters");
    std::string codes(nchars, '\0');  // padded with '@', value 0
    for (std::size_t k = 0; k < text.size(); ++k) {
        const unsigned char c = static_cast<unsigned char>(text[k]);
        if (c < 0x20 || c > 0x5F)
            throw std::invalid_argument("character " + std::to_string(k) + " (" + std::to_string(c) +
                                        ") is not in the six-bit set 0x20 to 0x5F");
        codes[k] = static_cast<char>(c >= 0x40 ? c - 0x40 : c);
    }
    return codes;
}

std::string encode_ascii(const Value& v, std::size_t nbytes) {
    std::string text;
    switch (v.kind) {
        case Value::Kind::String: text = v.s; break;
        case Value::Kind::Int: text = std::to_string(v.i); break;
        case Value::Kind::Float:
            try {
                text = format_double(v.f);
            } catch (const std::domain_error& e) {
                throw std::invalid_argument(e.what());
            }
            break;
    }
    if (text.size() > nbytes)
        throw std::invalid_argument("text of " + std::to_string(text.size()) + " bytes does not fit " +
                                    std::to_string(nbytes));
    for (std::size_t k = 0; k < text.size(); ++k) {
        const unsigned char c = static_cast<unsigned char>(text[k]);
        if (c > 0x7E || c < 0x20)
            throw std::invalid_argument("byte " + std::to_string(k) + " (" + std::to_string(c) +
                                        ") is not printable ASCII");
    }
    text.resize(nbytes, '\0');
    return text;
}

std::string encode_value(const FieldLine& f, const Value& v) {
    const Transform t = f.transform;
    try {
        if (transform_is_text_scale(t)) return encode_text_scale(f, v);
        if (t == Transform::CodeStr || t == Transform::CodeNum) return encode_code_text(f, v);
        switch (t) {
            case Transform::String:
                switch (v.kind) {
                    case Value::Kind::String: return v.s;
                    case Value::Kind::Int: return std::to_string(v.i);
                    case Value::Kind::Float: return format_double(v.f);
                }
                break;
            case Transform::Float:
                switch (v.kind) {
                    case Value::Kind::Float: return format_double(v.f);
                    case Value::Kind::Int: return std::to_string(v.i);
                    case Value::Kind::String: {
                        double d;
                        if (!parse_double(v.s, d)) throw std::invalid_argument("not a decimal number: \"" + v.s + "\"");
                        return format_double(d);
                    }
                }
                break;
            case Transform::Int: {
                std::int64_t n = 0;
                switch (v.kind) {
                    case Value::Kind::Int: n = v.i; break;
                    case Value::Kind::Float:
                        if (!integral_double(v.f, n)) throw std::invalid_argument("not integral: " + format_double(v.f));
                        break;
                    case Value::Kind::String:
                        if (!parse_int(v.s, n)) throw std::invalid_argument("not an integer: \"" + v.s + "\"");
                        break;
                }
                return std::to_string(n);
            }
            case Transform::Iso8601Ms:
            case Transform::Iso8601Short:
            case Transform::Iso8601S: {
                std::int64_t ms = 0;
                switch (v.kind) {
                    case Value::Kind::Int: ms = v.i; break;
                    case Value::Kind::Float:
                        if (!integral_double(v.f, ms)) throw std::invalid_argument("not integral epoch ms");
                        break;
                    case Value::Kind::String:
                        if (!parse_iso8601_ms(v.s, ms) && !parse_int(v.s, ms))
                            throw std::invalid_argument("not a time: \"" + v.s + "\"");
                        break;
                }
                if (f.transform == Transform::Iso8601Short) return format_iso8601_short(ms);
                if (f.transform == Transform::Iso8601S) return format_iso8601_s(ms);
                return format_iso8601_ms(ms);
            }
            default: throw std::invalid_argument("not a text transform");
        }
    } catch (const std::domain_error& e) {
        throw std::invalid_argument(e.what());
    }
    throw std::invalid_argument("unknown transform");
}

Value decode_protobuf_value(Transform t, std::uint64_t scalar, const std::string& bytes) {
    switch (t) {
        case Transform::Pstring:
            return Value::of_string(bytes);
        case Transform::Pvarint:
            return Value::of_int(static_cast<std::int64_t>(scalar));
        case Transform::Psint: {
            std::int64_t v = static_cast<std::int64_t>(scalar >> 1) ^
                             -static_cast<std::int64_t>(scalar & 1);  // zig-zag
            return Value::of_int(v);
        }
        case Transform::Pdouble: {
            double d;
            std::memcpy(&d, &scalar, sizeof(d));
            return Value::of_float(finite_wire(d));
        }
        case Transform::Pfloat: {
            std::uint32_t u = static_cast<std::uint32_t>(scalar);
            float fl;
            std::memcpy(&fl, &u, sizeof(fl));
            return Value::of_float(finite_wire(static_cast<double>(fl)));
        }
        default:
            break;
    }
    // Unreachable for a validated protobuf pack.
    return Value::of_int(static_cast<std::int64_t>(scalar));
}

void encode_protobuf_value(Transform t, const Value& v, std::uint64_t& scalar,
                           std::string& bytes) {
    scalar = 0;
    bytes.clear();
    switch (t) {
        case Transform::Pstring:
            switch (v.kind) {
                case Value::Kind::String: bytes = v.s; return;
                case Value::Kind::Int: bytes = std::to_string(v.i); return;
                case Value::Kind::Float: bytes = format_double(v.f); return;
            }
            break;
        case Transform::Pvarint:
            scalar = static_cast<std::uint64_t>(model_int(v));
            return;
        case Transform::Psint: {
            std::int64_t n = model_int(v);
            scalar = (static_cast<std::uint64_t>(n) << 1) ^
                     static_cast<std::uint64_t>(n >> 63);  // zig-zag
            return;
        }
        case Transform::Pdouble: {
            double d = model_double(v);
            if (!std::isfinite(d)) throw std::invalid_argument("a model float is finite");
            std::memcpy(&scalar, &d, sizeof(d));
            return;
        }
        case Transform::Pfloat: {
            float fl = narrow_single(model_double(v));
            std::uint32_t u = 0;
            std::memcpy(&u, &fl, sizeof(fl));
            scalar = u;
            return;
        }
        default:
            break;
    }
    throw std::invalid_argument("text/bits transform on a protobuf wire");
}

}  // namespace detail
}  // namespace goat_transformers
