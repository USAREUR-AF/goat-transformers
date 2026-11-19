#include "transforms.hpp"

#include <cfloat>
#include <cmath>
#include <cstring>
#include <stdexcept>
#include <vector>

#include "util.hpp"

namespace goat_transformers {

const char* transform_name(Transform t) {
    switch (t) {
        case Transform::String: return "string";
        case Transform::Float: return "float";
        case Transform::Int: return "int";
        case Transform::Iso8601Ms: return "iso8601_ms";
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
            // (2a), <den> an unsigned decimal integer that is not zero.
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
                  {"uint", Transform::Uint},       {"twos", Transform::Twos},
                  {"pstring", Transform::Pstring}, {"pvarint", Transform::Pvarint},
                  {"psint", Transform::Psint},     {"pdouble", Transform::Pdouble},
                  {"pfloat", Transform::Pfloat},   {"bool", Transform::Bool},
                  {"f32", Transform::F32},         {"f64", Transform::F64},
                  {"ascii", Transform::Ascii},     {"utf8", Transform::Utf8},
                  {"hex", Transform::Hex},         {"sixbit", Transform::Sixbit}};
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

bool transform_is_tlv_only(Transform t) { return t == Transform::Utf8 || t == Transform::Hex; }

bool transform_is_textual(Transform t) { return t == Transform::String || t == Transform::Iso8601Ms; }

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
        case Transform::Sixbit: return true;
        default: return false;
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

Value decode_json_number(Transform t, const std::string& text) {
    switch (t) {
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
        default: return decode_value(t, text);
    }
}

Value decode_value(Transform t, const std::string& text) {
    switch (t) {
        case Transform::String: return Value::of_string(text);
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
        case Transform::Iso8601Ms: {
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
// The quotient before rounding (0.11 ruling 4).
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
}  // namespace

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
        default:
            break;
    }
    throw std::invalid_argument("not a bits transform");
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

std::string encode_value(Transform t, const Value& v) {
    try {
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
            case Transform::Iso8601Ms: {
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
