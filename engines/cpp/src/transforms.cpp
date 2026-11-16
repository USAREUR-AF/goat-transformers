#include "transforms.hpp"

#include <cfloat>
#include <cmath>
#include <cstring>
#include <stdexcept>

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

namespace {
bool parse_decimal_integer(std::string_view s, double& out) {
    std::size_t i = 0;
    if (i < s.size() && (s[i] == '-' || s[i] == '+')) ++i;
    if (i >= s.size()) return false;
    for (std::size_t k = i; k < s.size(); ++k)
        if (s[k] < '0' || s[k] > '9') return false;
    return parse_double(s, out);
}

}  // namespace

bool parse_scale_factor(std::string_view factor, bool& fraction, double& value, double& num, double& den,
                        std::string& err) {
    std::size_t slash = factor.find('/');
    if (slash != std::string_view::npos) {
        if (!parse_decimal_integer(factor.substr(0, slash), num) ||
            !parse_decimal_integer(factor.substr(slash + 1), den)) {
            err = "scale fraction is not <num>/<den> of two decimal integers";
            return false;
        }
        if (den == 0.0) {
            err = "scale fraction has a zero denominator";
            return false;
        }
        fraction = true;
    } else {
        if (factor.empty() || !parse_double(factor, value)) {
            err = "scale factor is not a decimal number";
            return false;
        }
        fraction = false;
    }
    return true;
}

namespace {
// uscale / sscale arguments: <factor>[:<offset>], factor a decimal or <num>/<den>.
bool parse_scale_args(std::string_view args, FieldLine& f, std::string& err) {
    std::string_view factor = args, offset;
    bool have_offset = false;
    std::size_t colon = args.find(':');
    if (colon != std::string_view::npos) {
        factor = args.substr(0, colon);
        offset = args.substr(colon + 1);
        have_offset = true;
    }
    if (!parse_scale_factor(factor, f.scale_fraction, f.scale_factor, f.scale_num, f.scale_den, err)) return false;
    f.scale_offset = 0.0;
    if (have_offset && (offset.empty() || !parse_double(offset, f.scale_offset))) {
        err = "scale offset is not a decimal number";
        return false;
    }
    return true;
}
}  // namespace

bool parse_transform(std::string_view token, FieldLine& f, std::string& err) {
    f.scale_maxpos = 0.0;
    f.scale_range = 0.0;
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
                  {"ascii", Transform::Ascii}};
    for (const auto& e : kPlain)
        if (token == e.name) {
            f.transform = e.t;
            return true;
        }
    static const std::string_view kLin = "linscale:";
    if (token.size() > kLin.size() && token.substr(0, kLin.size()) == kLin) {
        std::string_view args = token.substr(kLin.size());
        std::size_t colon = args.find(':');
        if (colon == std::string_view::npos) {
            err = "linscale needs <maxpos>:<range>";
            return false;
        }
        std::string mp(args.substr(0, colon));
        std::string rg(args.substr(colon + 1));
        double mpv, rgv;
        if (mp.empty() || rg.empty() || !parse_double(mp, mpv) || !parse_double(rg, rgv)) {
            err = "linscale arguments are not decimals";
            return false;
        }
        if (!(mpv > 0.0) || !(rgv > 0.0)) {
            err = "linscale maxpos and range must be positive";
            return false;
        }
        f.transform = Transform::Linscale;
        f.scale_maxpos = mpv;
        f.scale_range = rgv;
        return true;
    }
    static const std::string_view kU = "uscale:", kS = "sscale:";
    if (token.size() > kU.size() && (token.substr(0, kU.size()) == kU || token.substr(0, kS.size()) == kS)) {
        f.transform = token[0] == 'u' ? Transform::Uscale : Transform::Sscale;
        return parse_scale_args(token.substr(kU.size()), f, err);
    }
    err = "unknown transform '" + std::string(token) + "'";
    return false;
}

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
        case Transform::Ascii: return true;
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

Value decode_value(Transform t, const std::string& text) {
    switch (t) {
        case Transform::String: return Value::of_string(text);
        case Transform::Float: {
            double d;
            if (!parse_double(text, d)) throw std::invalid_argument("not a decimal number: \"" + text + "\"");
            return Value::of_float(d);
        }
        case Transform::Int: {
            std::int64_t v;
            if (!parse_int(text, v)) throw std::invalid_argument("not an integer: \"" + text + "\"");
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
double scale_encode(const FieldLine& f, double x) {
    double d = x - f.scale_offset;
    return std::round(f.scale_fraction ? d * f.scale_den / f.scale_num : d / f.scale_factor);
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
    switch (f.transform) {
        case Transform::Uint:
        case Transform::Twos:
            return static_cast<std::uint64_t>(model_int(v)) & mask;
        case Transform::Linscale: {
            double x = model_double(v);
            double scaled = x / f.scale_range * f.scale_maxpos;
            // llround of a value outside 64 bits is not defined.
            if (!std::isfinite(scaled) || scaled < -9223372036854775808.0 || scaled >= 9223372036854775808.0)
                throw std::invalid_argument("linscale value out of range");
            std::int64_t r = static_cast<std::int64_t>(std::llround(scaled));
            return static_cast<std::uint64_t>(r) & mask;
        }
        case Transform::Uscale: {
            double r = scale_encode(f, model_double(v));
            if (!std::isfinite(r) || r < 0.0 || r >= std::ldexp(1.0, static_cast<int>(len)))
                throw std::invalid_argument("value outside the range of an unsigned " + std::to_string(len) +
                                            "-bit field");
            return static_cast<std::uint64_t>(r) & mask;
        }
        case Transform::Sscale: {
            double r = scale_encode(f, model_double(v));
            const double half = std::ldexp(1.0, static_cast<int>(len) - 1);
            if (!std::isfinite(r) || r < -half || r >= half)
                throw std::invalid_argument("value outside the range of a signed " + std::to_string(len) +
                                            "-bit field");
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
