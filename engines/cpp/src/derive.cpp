// Derived keys (engine-spec.md, Version 0.6, Derived keys).
#include "derive.hpp"

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

bool is_integer_text(const std::string& s) {
    std::size_t i = !s.empty() && (s[0] == '-' || s[0] == '+') ? 1 : 0;
    if (i >= s.size()) return false;
    for (; i < s.size(); ++i)
        if (s[i] < '0' || s[i] > '9') return false;
    return true;
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
        if (param.empty() || !parse_double(param, d.offset)) bad(where, "derive offset is not a decimal number");
        std::int64_t n = 0;
        if (is_integer_text(param) && parse_int(param, n)) {
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
// `<module>.<key>` otherwise. Only keys of `core` and of `m` are allowed.
Lookup key_type_of(const Module& m, const Module* core, bool require_core, const std::string& key, KeyType& out) {
    std::string mod = "core", name = key;
    const std::size_t dot = key.find('.');
    if (dot != std::string::npos) {
        mod = key.substr(0, dot);
        name = key.substr(dot + 1);
    }
    const Module* owner = nullptr;
    if (mod == m.name) owner = &m;
    else if (mod == "core") {
        if (!core) return require_core ? Lookup::Undeclared : Lookup::Deferred;
        owner = core;
    } else {
        return Lookup::Undeclared;  // a key of another module
    }
    const ModelKey* k = owner->find(name);
    if (!k) return Lookup::Undeclared;
    out = k->type;
    return Lookup::Found;
}

}  // namespace

void check_derives(Module& m, const Module* core, bool require_core) {
    for (auto& d : m.derives) {
        const std::string where = m.origin + ":" + std::to_string(d.line);
        bool deferred = false;
        KeyType target = KeyType::String;
        std::vector<KeyType> args(d.args.size(), KeyType::String);
        auto resolve = [&](const std::string& key, KeyType& out) {
            switch (key_type_of(m, core, require_core, key, out)) {
                case Lookup::Found: break;
                case Lookup::Deferred: deferred = true; break;
                case Lookup::Undeclared:
                    bad(where, "derive key '" + key + "' is not a declared key of 'core' or of module '" + m.name + "'");
            }
        };
        resolve(d.target, target);
        for (std::size_t k = 0; k < d.args.size(); ++k) resolve(d.args[k], args[k]);
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
            default: fits = all(KeyType::Float); break;
        }
        if (!fits) bad(where, "the key types do not fit derive function '" + d.function + "'");
    }
}

bool apply_derive(const DeriveLine& d, Entity& e) {
    if (e.fields.count(d.target)) return false;
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
