// Derived keys (engine-spec.md, Version 0.6, Derived keys).
#include "derive.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>

#include "transforms.hpp"
#include "util.hpp"

namespace goat_transformers::detail {

namespace {

// The double nearest to pi; degrees to radians uses pi / 180.
constexpr double kPi = 3.14159265358979323846;

[[noreturn]] void bad(const std::string& where, const std::string& what) {
    throw Error(ErrorKind::BadDirective, "", "", where + ": " + what);
}

}  // namespace

DeriveLine parse_derive(const std::vector<std::string>& t, const std::string& where) {
    if (t.size() < 4) bad(where, "'derive' takes a key, a function and at least 1 argument key");
    DeriveLine d;
    d.target = t[1];
    d.function = t[2];
    d.args.assign(t.begin() + 3, t.end());

    std::string name = d.function, param;
    bool have_param = false;
    const std::size_t colon = d.function.find(':');
    if (colon != std::string::npos) {
        name = d.function.substr(0, colon);
        param = d.function.substr(colon + 1);
        have_param = true;
    }

    std::size_t min_args = 1, max_args = 1;
    bool takes_param = false;
    if (name == "copy") d.fn = DeriveFn::Copy;
    else if (name == "neg") d.fn = DeriveFn::Neg;
    else if (name == "hypot") { d.fn = DeriveFn::Hypot; min_args = max_args = 2; }
    else if (name == "bearing") { d.fn = DeriveFn::Bearing; min_args = max_args = 2; }
    else if (name == "east_of") { d.fn = DeriveFn::EastOf; min_args = max_args = 2; }
    else if (name == "north_of") { d.fn = DeriveFn::NorthOf; min_args = max_args = 2; }
    else if (name == "scale") { d.fn = DeriveFn::Scale; takes_param = true; }
    else if (name == "offset") { d.fn = DeriveFn::Offset; takes_param = true; }
    else if (name == "join") { d.fn = DeriveFn::Join; takes_param = true; min_args = 1; max_args = static_cast<std::size_t>(-1); }
    else if (name == "day_seconds") d.fn = DeriveFn::DaySeconds;
    else if (name == "any") { d.fn = DeriveFn::Any; max_args = static_cast<std::size_t>(-1); }
    else if (name == "not") d.fn = DeriveFn::Not;
    else if (name == "parse_int") d.fn = DeriveFn::ParseInt;
    else if (name == "text_of") d.fn = DeriveFn::TextOf;
    else if (name == "present") d.fn = DeriveFn::Present;  // 0.12
    // Version 0.16: time, distance and frames. Each takes exactly its arguments.
    else if (name == "sec_of") d.fn = DeriveFn::SecOf;
    else if (name == "nsec_of") d.fn = DeriveFn::NsecOf;
    else if (name == "ms_of") { d.fn = DeriveFn::MsOf; min_args = max_args = 2; }
    else if (name == "deg") d.fn = DeriveFn::Deg;
    else if (name == "rad") d.fn = DeriveFn::Rad;
    else if (name == "add") { d.fn = DeriveFn::Add; min_args = max_args = 2; }
    else if (name == "sub") { d.fn = DeriveFn::Sub; min_args = max_args = 2; }
    else if (name == "deg_lat_of") { d.fn = DeriveFn::DegLatOf; min_args = max_args = 2; }
    else if (name == "deg_lon_of") { d.fn = DeriveFn::DegLonOf; min_args = max_args = 2; }
    else if (name == "m_lat_of") { d.fn = DeriveFn::MLatOf; min_args = max_args = 2; }
    else if (name == "m_lon_of") { d.fn = DeriveFn::MLonOf; min_args = max_args = 2; }
    else if (name == "ecef_x") { d.fn = DeriveFn::EcefX; min_args = max_args = 3; }
    else if (name == "ecef_y") { d.fn = DeriveFn::EcefY; min_args = max_args = 3; }
    else if (name == "ecef_z") { d.fn = DeriveFn::EcefZ; min_args = max_args = 3; }
    else if (name == "lat_of_ecef") { d.fn = DeriveFn::LatOfEcef; min_args = max_args = 3; }
    else if (name == "lon_of_ecef") { d.fn = DeriveFn::LonOfEcef; min_args = max_args = 3; }
    else if (name == "hae_of_ecef") { d.fn = DeriveFn::HaeOfEcef; min_args = max_args = 3; }
    else bad(where, "derive function '" + d.function + "' is not in the function table");

    if (takes_param != have_param)
        bad(where, takes_param ? "derive function '" + name + "' needs a parameter after ':'"
                               : "derive function '" + name + "' takes no parameter");
    if (d.args.size() < min_args || d.args.size() > max_args)
        bad(where, "derive function '" + name + "' does not take " + std::to_string(d.args.size()) +
                       " argument key(s)");

    if (d.fn == DeriveFn::Scale) {
        std::string err;
        if (!parse_scale_factor(param, d.fraction, d.factor, d.num, d.den, err)) bad(where, "derive " + err);
    } else if (d.fn == DeriveFn::Offset) {
        // Number text (0.11 ruling 2c); an integer when 2a reads it.
        if (!parse_number_text(param, d.offset)) bad(where, "derive offset is not number text");
        std::int64_t n = 0;
        if (parse_int_text(param, n)) {
            d.offset_is_int = true;
            d.int_offset = n;
        }
    } else if (d.fn == DeriveFn::Join) {
        d.sep = param;
    }
    return d;
}

namespace {

enum class Lookup { Found, Undeclared, Deferred };

// The declared type of a key written as in a pack: bare for `core`,
// `<module>.<key>` otherwise. A target is a key of `core` or of `m`; an
// argument may also be a key of a module `m` uses (0.8).
Lookup key_type_of(const Module& m, const ModuleLookup& loaded, bool require_core, bool target,
                   const std::string& key, KeyType& out) {
    std::string mod = "core", name = key;
    const std::size_t dot = key.find('.');
    if (dot != std::string::npos) {
        mod = key.substr(0, dot);
        name = key.substr(dot + 1);
    }
    const Module* owner = nullptr;
    if (mod == m.name) owner = &m;
    else if (mod == "core") {
        owner = loaded ? loaded("core") : nullptr;
        if (!owner) return require_core ? Lookup::Undeclared : Lookup::Deferred;
    } else if (!target && std::find(m.uses.begin(), m.uses.end(), mod) != m.uses.end()) {
        // A used module that is not loaded: the load fails with unknown-module.
        owner = loaded ? loaded(mod) : nullptr;
        if (!owner) return Lookup::Deferred;
    } else {
        return Lookup::Undeclared;  // a key of a module that is not used, or a target of another module
    }
    const ModelKey* k = owner->find(name);
    if (!k) return Lookup::Undeclared;
    out = k->type;
    return Lookup::Found;
}

}  // namespace

void check_derives(Module& m, const ModuleLookup& loaded, bool require_core) {
    for (auto& d : m.derives) {
        const std::string where = m.origin + ":" + std::to_string(d.line);
        bool deferred = false;
        KeyType target = KeyType::String;
        std::vector<KeyType> args(d.args.size(), KeyType::String);
        auto resolve = [&](const std::string& key, KeyType& out, bool is_target) {
            switch (key_type_of(m, loaded, require_core, is_target, key, out)) {
                case Lookup::Found: break;
                case Lookup::Deferred: deferred = true; break;
                case Lookup::Undeclared:
                    bad(where, "derive key '" + key + "' is not a declared key of 'core', of module '" + m.name +
                                   "'" + (is_target ? "" : " or of a module it uses"));
            }
        };
        resolve(d.target, target, true);
        for (std::size_t k = 0; k < d.args.size(); ++k) resolve(d.args[k], args[k], false);
        if (deferred) continue;

        auto all = [&](KeyType want) {
            if (target != want) return false;
            for (KeyType a : args)
                if (a != want) return false;
            return true;
        };
        bool fits = false;
        switch (d.fn) {
            case DeriveFn::Copy: fits = target == args[0]; break;
            case DeriveFn::Join: fits = all(KeyType::String); break;
            case DeriveFn::Offset:
                d.int_arith = all(KeyType::Int) && d.offset_is_int;
                fits = d.int_arith || all(KeyType::Float);
                break;
            case DeriveFn::DaySeconds: fits = target == KeyType::Float && args[0] == KeyType::Int; break;
            case DeriveFn::Any:
            case DeriveFn::Not: fits = all(KeyType::Int); break;
            case DeriveFn::ParseInt: fits = target == KeyType::Int && args[0] == KeyType::String; break;
            case DeriveFn::TextOf: fits = target == KeyType::String && args[0] == KeyType::Int; break;
            case DeriveFn::Present: fits = target == KeyType::Int; break;  // any scalar argument (0.12)
            // 0.16 ruling 4: no promotion.
            case DeriveFn::SecOf:
            case DeriveFn::NsecOf:
            case DeriveFn::MsOf: fits = all(KeyType::Int); break;
            case DeriveFn::Add:
            case DeriveFn::Sub:
                d.int_arith = all(KeyType::Int);
                fits = d.int_arith || all(KeyType::Float);
                break;
            default: fits = all(KeyType::Float); break;
        }
        if (!fits) bad(where, "the key types do not fit derive function '" + d.function + "'");
    }
}

namespace {

// ---- Version 0.16: time, distance and frames ----------------------------

// floor(x / d) and x - d * floor(x / d) for d > 0, exact on every int64.
std::int64_t floor_div(std::int64_t x, std::int64_t d) {
    std::int64_t q = x / d;
    if (x % d < 0) --q;
    return q;
}
std::int64_t floor_mod(std::int64_t x, std::int64_t d) {
    std::int64_t r = x % d;
    if (r < 0) r += d;
    return r;
}

// An int argument: an `int` value, or a value that holds an integer exactly.
std::int64_t int_arg(const Value& v) { return v.kind == Value::Kind::Int ? v.i : model_int(v); }

// sec * 1000 + floor(nsec / 1000000), exact; false when outside 64 bits
// (0.16 rulings 3 and 7). With q = floor(nsec / 1e6) = 1000 qd + qr
// (0 <= qr < 1000), the result is 1000 (sec + qd) + qr.
bool ms_of(std::int64_t sec, std::int64_t nsec, std::int64_t& out) {
    const std::int64_t q = floor_div(nsec, 1000000);
    const std::int64_t qd = floor_div(q, 1000), qr = floor_mod(q, 1000);
    if ((qd > 0 && sec > INT64_MAX - qd) || (qd < 0 && sec < INT64_MIN - qd)) return false;
    const std::int64_t s2 = sec + qd;
    // INT64_MAX = 1000 * 9223372036854775 + 807; INT64_MIN = 1000 * -9223372036854776 + 192.
    const std::int64_t hi_q = 9223372036854775, hi_r = 807, lo_q = -9223372036854776, lo_r = 192;
    if (s2 > hi_q || (s2 == hi_q && qr > hi_r)) return false;
    if (s2 < lo_q || (s2 == lo_q && qr < lo_r)) return false;
    // In range: the arithmetic modulo 2^64 gives the exact value.
    const std::uint64_t u = static_cast<std::uint64_t>(s2) * 1000u + static_cast<std::uint64_t>(qr);
    out = static_cast<std::int64_t>(u);
    return true;
}

// WGS 84 (0.16, The ellipsoid).
constexpr double kA = 6378137.0;
constexpr double kF = 1.0 / 298.257223563;
constexpr double kE2 = kF * (2.0 - kF);
constexpr double kB = kA * (1.0 - kF);

bool lat_ok(double lat) { return lat >= -90.0 && lat <= 90.0; }  // 0.16 ruling 6; false for NaN

double to_rad(double x) { return x * (kPi / 180.0); }
double to_deg(double x) { return x * (180.0 / kPi); }

// N and M at the latitude phi (radians).
double prime_vertical(double phi) {
    const double s = std::sin(phi);
    return kA / std::sqrt(1.0 - kE2 * s * s);
}
double meridional(double phi) {
    const double s = std::sin(phi);
    return kA * (1.0 - kE2) / std::pow(1.0 - kE2 * s * s, 1.5);
}

// Heikkinen's closed form, in the order the specification states. False when
// G <= 0 (ruling 2), an intermediate is not finite, or a square root other than
// the one in r0 has a negative argument (ruling 1; ruling 9 for r0).
bool geodetic_of(double x, double y, double z, double& phi_deg, double& h) {
    bool ok = true;
    auto fin = [&](double v) {
        if (!std::isfinite(v)) ok = false;
        return v;
    };
    auto root = [&](double v) {
        if (!(v >= 0.0)) ok = false;
        return fin(std::sqrt(v >= 0.0 ? v : 0.0));
    };
    const double a2 = kA * kA, b2 = kB * kB, e4 = kE2 * kE2;
    const double p = root(fin(x * x + y * y));
    const double F = fin(54.0 * b2 * z * z);
    const double G = fin(p * p + (1.0 - kE2) * z * z - kE2 * (a2 - b2));
    if (!ok || !(G > 0.0)) return false;
    const double c = fin(e4 * F * p * p / (G * G * G));
    const double s = fin(std::cbrt(fin(1.0 + c + root(c * c + 2.0 * c))));
    if (!ok || s == 0.0) return false;
    const double k = fin(s + 1.0 + 1.0 / s);
    const double den = fin(3.0 * k * k * G * G);
    if (!ok || den == 0.0) return false;
    const double P = fin(F / den);
    const double Q = root(fin(1.0 + 2.0 * e4 * P));
    if (!ok || Q == 0.0 || 1.0 + Q == 0.0) return false;
    const double inner = fin(a2 / 2.0 * (1.0 + 1.0 / Q) - P * (1.0 - kE2) * z * z / (Q * (1.0 + Q)) - P * p * p / 2.0);
    const double r0 = fin(-P * kE2 * p / (1.0 + Q) + std::sqrt(inner > 0.0 ? inner : 0.0));  // ruling 9
    const double t = p - kE2 * r0;
    const double U = root(fin(t * t + z * z));
    const double V = root(fin(t * t + (1.0 - kE2) * z * z));
    if (!ok || V == 0.0) return false;
    const double z0 = fin(b2 * z / (kA * V));
    h = fin(U * (1.0 - b2 / (kA * V)));
    phi_deg = fin(to_deg(fin(std::atan2(z + (a2 - b2) / b2 * z0, p))));
    return ok;
}

// The functions of 0.16. Returns false when the target stays absent.
bool apply16(const DeriveLine& d, const std::vector<const Value*>& a, Value& out) {
    switch (d.fn) {
        case DeriveFn::SecOf: out = Value::of_int(floor_div(int_arg(*a[0]), 1000)); return true;
        case DeriveFn::NsecOf: out = Value::of_int(floor_mod(int_arg(*a[0]), 1000) * 1000000); return true;
        case DeriveFn::MsOf: {
            std::int64_t r = 0;
            if (!ms_of(int_arg(*a[0]), int_arg(*a[1]), r)) return false;
            out = Value::of_int(r);
            return true;
        }
        case DeriveFn::Add:
        case DeriveFn::Sub:
            if (d.int_arith) {
                const std::int64_t x = int_arg(*a[0]), y = int_arg(*a[1]);
                if (d.fn == DeriveFn::Add) {
                    if ((y > 0 && x > INT64_MAX - y) || (y < 0 && x < INT64_MIN - y)) return false;
                    out = Value::of_int(x + y);
                } else {
                    if ((y < 0 && x > INT64_MAX + y) || (y > 0 && x < INT64_MIN + y)) return false;
                    out = Value::of_int(x - y);
                }
                return true;
            }
            break;
        default: break;
    }
    std::vector<double> v(a.size());
    for (std::size_t k = 0; k < a.size(); ++k) v[k] = model_double(*a[k]);
    double r = 0.0;
    switch (d.fn) {
        case DeriveFn::Add: r = v[0] + v[1]; break;
        case DeriveFn::Sub: r = v[0] - v[1]; break;
        case DeriveFn::Deg: r = to_deg(v[0]); break;
        case DeriveFn::Rad: r = to_rad(v[0]); break;
        case DeriveFn::DegLatOf:
            if (!lat_ok(v[1])) return false;
            r = to_deg(v[0] / meridional(to_rad(v[1])));
            break;
        case DeriveFn::DegLonOf: {
            if (!lat_ok(v[1])) return false;
            const double phi = to_rad(v[1]);
            const double c = std::fabs(std::cos(phi));
            if (c <= 1e-12) return false;
            r = to_deg(v[0] / (prime_vertical(phi) * c));
            break;
        }
        case DeriveFn::MLatOf:
            if (!lat_ok(v[1])) return false;
            r = to_rad(v[0]) * meridional(to_rad(v[1]));
            break;
        case DeriveFn::MLonOf: {
            if (!lat_ok(v[1])) return false;
            const double phi = to_rad(v[1]);
            r = to_rad(v[0]) * prime_vertical(phi) * std::fabs(std::cos(phi));
            break;
        }
        case DeriveFn::EcefX:
        case DeriveFn::EcefY:
        case DeriveFn::EcefZ: {
            if (!lat_ok(v[0])) return false;
            const double phi = to_rad(v[0]), lam = to_rad(v[1]), hae = v[2];
            const double n = prime_vertical(phi);
            if (d.fn == DeriveFn::EcefX) r = (n + hae) * std::cos(phi) * std::cos(lam);
            else if (d.fn == DeriveFn::EcefY) r = (n + hae) * std::cos(phi) * std::sin(lam);
            else r = (n * (1.0 - kE2) + hae) * std::sin(phi);
            break;
        }
        case DeriveFn::LatOfEcef:
        case DeriveFn::HaeOfEcef: {
            double phi = 0.0, h = 0.0;
            if (!geodetic_of(v[0], v[1], v[2], phi, h)) return false;
            r = d.fn == DeriveFn::LatOfEcef ? phi : h;
            break;
        }
        case DeriveFn::LonOfEcef:
            if (v[0] == 0.0 && v[1] == 0.0) return false;
            r = to_deg(std::atan2(v[1], v[0]));
            if (r == -180.0) r = 180.0;  // ruling 5
            break;
        default: return false;
    }
    if (!std::isfinite(r)) return false;
    out = Value::of_float(r);
    return true;
}

}  // namespace

bool apply_derive(const DeriveLine& d, Entity& e) {
    if (e.fields.count(d.target)) return false;
    if (d.fn == DeriveFn::Any) {
        // The one function whose target is set when only some arguments are
        // present: 1 when any present argument is not 0, else 0.
        bool present = false, any = false;
        for (const auto& key : d.args) {
            auto it = e.fields.find(key);
            if (it == e.fields.end()) continue;
            if (it->second.kind != Value::Kind::Int) return false;
            present = true;
            if (it->second.i != 0) any = true;
        }
        if (!present) return false;
        e.fields[d.target] = Value::of_int(any ? 1 : 0);
        return true;
    }
    std::vector<const Value*> a;
    a.reserve(d.args.size());
    for (const auto& key : d.args) {
        auto it = e.fields.find(key);
        if (it == e.fields.end()) return false;
        a.push_back(&it->second);
    }
    try {
        double r = 0.0;
        switch (d.fn) {
            case DeriveFn::Copy:
                e.fields[d.target] = *a[0];
                return true;
            case DeriveFn::Join: {
                std::string s;
                for (std::size_t k = 0; k < a.size(); ++k) {
                    if (a[k]->kind != Value::Kind::String) return false;
                    if (k) s += d.sep;
                    s += a[k]->s;
                }
                e.fields[d.target] = Value::of_string(std::move(s));
                return true;
            }
            case DeriveFn::Offset:
                if (d.int_arith) {
                    const std::int64_t x = model_int(*a[0]);
                    const std::int64_t n = d.int_offset;
                    if ((n > 0 && x > INT64_MAX - n) || (n < 0 && x < INT64_MIN - n)) return false;
                    e.fields[d.target] = Value::of_int(x + n);
                    return true;
                }
                r = model_double(*a[0]) + d.offset;
                break;
            case DeriveFn::Hypot: {
                const double x = model_double(*a[0]), y = model_double(*a[1]);
                r = std::sqrt(x * x + y * y);
                break;
            }
            case DeriveFn::Bearing: {
                const double east = model_double(*a[0]), north = model_double(*a[1]);
                if (east == 0.0 && north == 0.0) return false;
                r = std::atan2(east, north) * (180.0 / kPi);  // the quotient first (0.6 ruling 1)
                if (r < 0.0) r += 360.0;
                if (r >= 360.0) r -= 360.0;
                break;
            }
            case DeriveFn::EastOf:
                r = model_double(*a[0]) * std::sin(model_double(*a[1]) * (kPi / 180.0));
                break;
            case DeriveFn::NorthOf:
                r = model_double(*a[0]) * std::cos(model_double(*a[1]) * (kPi / 180.0));
                break;
            case DeriveFn::Neg: r = -model_double(*a[0]); break;
            case DeriveFn::DaySeconds: {
                // Seconds since UTC midnight of the instant, also before 1970.
                if (a[0]->kind != Value::Kind::Int) return false;
                const std::int64_t day = 86400000;
                const std::int64_t ms = ((a[0]->i % day) + day) % day;
                r = static_cast<double>(ms) / 1000.0;
                break;
            }
            case DeriveFn::Not:
                if (a[0]->kind != Value::Kind::Int) return false;
                e.fields[d.target] = Value::of_int(a[0]->i == 0 ? 1 : 0);
                return true;
            case DeriveFn::ParseInt: {
                // An optional '-' and then digits, leading zeros included, within
                // 64 bits; anything else leaves the target absent (0.8 ruling 28).
                if (a[0]->kind != Value::Kind::String) return false;
                const std::string& s = a[0]->s;
                const bool neg = !s.empty() && s[0] == '-';
                if (s.size() == (neg ? 1u : 0u)) return false;
                // The magnitude, at most 2^63 for a negative and 2^63 - 1 otherwise.
                const std::uint64_t limit = std::uint64_t{1} << 63;
                std::uint64_t mag = 0;
                for (std::size_t k = neg ? 1 : 0; k < s.size(); ++k) {
                    if (s[k] < '0' || s[k] > '9') return false;
                    const std::uint64_t digit = static_cast<std::uint64_t>(s[k] - '0');
                    if (mag > (limit - digit) / 10) return false;
                    mag = mag * 10 + digit;
                }
                if (!neg && mag == limit) return false;
                const std::int64_t n = neg ? (mag == limit ? INT64_MIN : -static_cast<std::int64_t>(mag))
                                           : static_cast<std::int64_t>(mag);
                e.fields[d.target] = Value::of_int(n);
                return true;
            }
            case DeriveFn::TextOf:
                if (a[0]->kind != Value::Kind::Int) return false;
                e.fields[d.target] = Value::of_string(std::to_string(a[0]->i));
                return true;
            case DeriveFn::Present:
                // Presence, not value: any value the entity holds gives 1 (0.12 ruling 1).
                e.fields[d.target] = Value::of_int(1);
                return true;
            case DeriveFn::Any: return false;  // handled above
            case DeriveFn::SecOf:
            case DeriveFn::NsecOf:
            case DeriveFn::MsOf:
            case DeriveFn::Deg:
            case DeriveFn::Rad:
            case DeriveFn::Add:
            case DeriveFn::Sub:
            case DeriveFn::DegLatOf:
            case DeriveFn::DegLonOf:
            case DeriveFn::MLatOf:
            case DeriveFn::MLonOf:
            case DeriveFn::EcefX:
            case DeriveFn::EcefY:
            case DeriveFn::EcefZ:
            case DeriveFn::LatOfEcef:
            case DeriveFn::LonOfEcef:
            case DeriveFn::HaeOfEcef: {
                Value out;
                if (!apply16(d, a, out)) return false;  // never an error (0.16 ruling 1)
                e.fields[d.target] = std::move(out);
                return true;
            }
            case DeriveFn::Scale: {
                const double x = model_double(*a[0]);
                r = d.fraction ? x * d.num / d.den : x * d.factor;
                break;
            }
        }
        if (!std::isfinite(r)) return false;
        e.fields[d.target] = Value::of_float(r);
        return true;
    } catch (const std::invalid_argument&) {
        return false;  // an argument that does not hold its declared type
    }
}

}  // namespace goat_transformers::detail
