#include "exact.hpp"

#include <algorithm>

namespace goat_transformers::detail {

namespace {

using Mag = std::vector<std::uint32_t>;

void mag_trim(Mag& a) {
    while (!a.empty() && a.back() == 0) a.pop_back();
}

int mag_cmp(const Mag& a, const Mag& b) {
    if (a.size() != b.size()) return a.size() < b.size() ? -1 : 1;
    for (std::size_t k = a.size(); k-- > 0;)
        if (a[k] != b[k]) return a[k] < b[k] ? -1 : 1;
    return 0;
}

Mag mag_add(const Mag& a, const Mag& b) {
    Mag r(std::max(a.size(), b.size()) + 1, 0);
    std::uint64_t carry = 0;
    for (std::size_t k = 0; k + 1 < r.size(); ++k) {
        std::uint64_t s = carry;
        if (k < a.size()) s += a[k];
        if (k < b.size()) s += b[k];
        r[k] = static_cast<std::uint32_t>(s);
        carry = s >> 32;
    }
    r.back() = static_cast<std::uint32_t>(carry);
    mag_trim(r);
    return r;
}

// a - b, with a >= b.
Mag mag_sub(const Mag& a, const Mag& b) {
    Mag r(a.size(), 0);
    std::int64_t borrow = 0;
    for (std::size_t k = 0; k < a.size(); ++k) {
        std::int64_t d = static_cast<std::int64_t>(a[k]) - borrow - (k < b.size() ? static_cast<std::int64_t>(b[k]) : 0);
        borrow = d < 0 ? 1 : 0;
        if (d < 0) d += std::int64_t{1} << 32;
        r[k] = static_cast<std::uint32_t>(d);
    }
    mag_trim(r);
    return r;
}

Mag mag_mul(const Mag& a, const Mag& b) {
    if (a.empty() || b.empty()) return {};
    Mag r(a.size() + b.size(), 0);
    for (std::size_t i = 0; i < a.size(); ++i) {
        std::uint64_t carry = 0;
        for (std::size_t j = 0; j < b.size(); ++j) {
            std::uint64_t t = static_cast<std::uint64_t>(a[i]) * b[j] + r[i + j] + carry;
            r[i + j] = static_cast<std::uint32_t>(t);
            carry = t >> 32;
        }
        std::size_t k = i + b.size();
        while (carry) {
            std::uint64_t t = static_cast<std::uint64_t>(r[k]) + carry;
            r[k++] = static_cast<std::uint32_t>(t);
            carry = t >> 32;
        }
    }
    mag_trim(r);
    return r;
}

void mag_mul_small_add(Mag& a, std::uint32_t m, std::uint32_t add) {
    std::uint64_t carry = add;
    for (auto& limb : a) {
        std::uint64_t t = static_cast<std::uint64_t>(limb) * m + carry;
        limb = static_cast<std::uint32_t>(t);
        carry = t >> 32;
    }
    if (carry) a.push_back(static_cast<std::uint32_t>(carry));
    mag_trim(a);
}

// a / d in place, returning the remainder; d is not 0.
std::uint32_t mag_div_small(Mag& a, std::uint32_t d) {
    std::uint64_t rem = 0;
    for (std::size_t k = a.size(); k-- > 0;) {
        std::uint64_t cur = (rem << 32) | a[k];
        a[k] = static_cast<std::uint32_t>(cur / d);
        rem = cur % d;
    }
    mag_trim(a);
    return static_cast<std::uint32_t>(rem);
}

std::size_t mag_bits(const Mag& a) {
    if (a.empty()) return 0;
    std::size_t n = (a.size() - 1) * 32;
    for (std::uint32_t top = a.back(); top; top >>= 1) ++n;
    return n;
}

// q = a / b, r = a mod b; b is not 0.
void mag_divmod(const Mag& a, const Mag& b, Mag& q, Mag& r) {
    if (b.size() == 1) {
        q = a;
        std::uint32_t rem = mag_div_small(q, b[0]);
        r.clear();
        if (rem) r.push_back(rem);
        return;
    }
    q.assign(a.size(), 0);
    r.clear();
    for (std::size_t i = mag_bits(a); i-- > 0;) {
        // r = r * 2 + bit i of a
        std::uint32_t carry = (a[i / 32] >> (i % 32)) & 1u;
        for (auto& limb : r) {
            std::uint32_t next = limb >> 31;
            limb = (limb << 1) | carry;
            carry = next;
        }
        if (carry) r.push_back(carry);
        if (mag_cmp(r, b) >= 0) {
            r = mag_sub(r, b);
            q[i / 32] |= 1u << (i % 32);
        }
    }
    mag_trim(q);
}

Mag mag_of_u64(std::uint64_t v) {
    Mag m;
    if (v) m.push_back(static_cast<std::uint32_t>(v));
    if (v >> 32) m.push_back(static_cast<std::uint32_t>(v >> 32));
    return m;
}

Mag mag_pow10(std::size_t k) {
    Mag m{1};
    for (; k >= 9; k -= 9) mag_mul_small_add(m, 1000000000u, 0);
    static const std::uint32_t kSmall[] = {1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000};
    if (k) mag_mul_small_add(m, kSmall[k], 0);
    return m;
}

// Decimal digits (only '0'-'9') to a magnitude.
Mag mag_of_digits(std::string_view digits) {
    Mag m;
    std::size_t k = 0;
    while (k < digits.size()) {
        std::size_t n = std::min<std::size_t>(9, digits.size() - k);
        std::uint32_t chunk = 0, scale = 1;
        for (std::size_t j = 0; j < n; ++j) {
            chunk = chunk * 10 + static_cast<std::uint32_t>(digits[k + j] - '0');
            scale *= 10;
        }
        mag_mul_small_add(m, scale, chunk);
        k += n;
    }
    return m;
}

std::string mag_decimal(Mag a) {
    if (a.empty()) return "0";
    std::vector<std::uint32_t> chunks;
    while (!a.empty()) chunks.push_back(mag_div_small(a, 1000000000u));
    std::string s = std::to_string(chunks.back());
    for (std::size_t k = chunks.size() - 1; k-- > 0;) {
        std::string c = std::to_string(chunks[k]);
        s += std::string(9 - c.size(), '0') + c;
    }
    return s;
}

Mag mag_gcd(Mag a, Mag b) {
    while (!b.empty()) {
        Mag q, r;
        mag_divmod(a, b, q, r);
        a = std::move(b);
        b = std::move(r);
    }
    return a;
}

// |v| <= 2^32
bool mag_at_most_2_32(const Mag& a) { return a.size() <= 1 || (a.size() == 2 && a[1] == 1 && a[0] == 0); }

bool all_digits(std::string_view s) {
    if (s.empty()) return false;
    for (char c : s)
        if (c < '0' || c > '9') return false;
    return true;
}

Big make(bool neg, Mag m) {
    Big b;
    b.mag = std::move(m);
    b.neg = neg && !b.mag.empty();
    return b;
}

}  // namespace

Big Big::of_u64(std::uint64_t v) { return make(false, mag_of_u64(v)); }

Big Big::of_i64(std::int64_t v) {
    const std::uint64_t m = v < 0 ? ~static_cast<std::uint64_t>(v) + 1 : static_cast<std::uint64_t>(v);
    return make(v < 0, mag_of_u64(m));
}

Big big_add(const Big& a, const Big& b) {
    if (a.neg == b.neg) return make(a.neg, mag_add(a.mag, b.mag));
    const int c = mag_cmp(a.mag, b.mag);
    if (c == 0) return Big{};
    return c > 0 ? make(a.neg, mag_sub(a.mag, b.mag)) : make(b.neg, mag_sub(b.mag, a.mag));
}

Big big_sub(const Big& a, const Big& b) {
    Big nb = b;
    nb.neg = !b.neg && !b.mag.empty();
    return big_add(a, nb);
}

Big big_mul(const Big& a, const Big& b) { return make(a.neg != b.neg, mag_mul(a.mag, b.mag)); }

Big big_round_div(const Big& a, const Big& b) {
    Mag q, r;
    mag_divmod(a.mag, b.mag, q, r);
    // Half away from zero: up in magnitude when 2r >= |b|.
    if (mag_cmp(mag_add(r, r), b.mag) >= 0) q = mag_add(q, Mag{1});
    return make(a.neg != b.neg, std::move(q));
}

bool big_to_u64(const Big& v, std::uint64_t& out) {
    if (v.neg || v.mag.size() > 2) return false;
    out = 0;
    for (std::size_t k = v.mag.size(); k-- > 0;) out = (out << 32) | v.mag[k];
    return true;
}

bool big_to_i64(const Big& v, std::int64_t& out) {
    if (v.mag.size() > 2) return false;
    std::uint64_t m = 0;
    for (std::size_t k = v.mag.size(); k-- > 0;) m = (m << 32) | v.mag[k];
    const std::uint64_t limit = std::uint64_t{1} << 63;
    if (v.neg) {
        if (m > limit) return false;
        out = static_cast<std::int64_t>(~m + 1);
    } else {
        if (m >= limit) return false;
        out = static_cast<std::int64_t>(m);
    }
    return true;
}

bool parse_exact_factor(std::string_view text, std::int64_t& num, std::int64_t& den, std::string& err) {
    std::string_view s = text;
    const bool neg = !s.empty() && s[0] == '-';
    if (neg) s.remove_prefix(1);
    Mag n, d;
    const std::size_t slash = s.find('/');
    if (slash != std::string_view::npos) {
        std::string_view a = s.substr(0, slash), b = s.substr(slash + 1);
        if (!all_digits(a) || !all_digits(b)) {
            err = "factor '" + std::string(text) + "' is not <num>/<den> of an optionally negative and an unsigned decimal integer";
            return false;
        }
        n = mag_of_digits(a);
        d = mag_of_digits(b);
        if (d.empty()) {
            err = "factor '" + std::string(text) + "' has a zero denominator";
            return false;
        }
    } else {
        const std::size_t dot = s.find('.');
        std::string_view ip = s.substr(0, dot), fp;
        if (dot != std::string_view::npos) {
            fp = s.substr(dot + 1);
            if (!all_digits(fp)) {
                err = "factor '" + std::string(text) + "' is not a decimal [-]digits[.digits]";
                return false;
            }
        }
        if (!all_digits(ip)) {
            err = "factor '" + std::string(text) + "' is not a decimal [-]digits[.digits]";
            return false;
        }
        n = mag_of_digits(std::string(ip) + std::string(fp));
        d = mag_pow10(fp.size());
    }
    if (n.empty()) {
        err = "factor '" + std::string(text) + "' is 0";
        return false;
    }
    const Mag g = mag_gcd(n, d);
    Mag q, r;
    mag_divmod(n, g, q, r);
    n = q;
    mag_divmod(d, g, q, r);
    d = q;
    if (!mag_at_most_2_32(n) || !mag_at_most_2_32(d)) {
        err = "factor '" + std::string(text) + "' in lowest terms has a numerator or a denominator above 2^32";
        return false;
    }
    std::uint64_t un = 0, ud = 0;
    big_to_u64(make(false, n), un);
    big_to_u64(make(false, d), ud);
    num = neg ? -static_cast<std::int64_t>(un) : static_cast<std::int64_t>(un);
    den = static_cast<std::int64_t>(ud);
    return true;
}

bool parse_exact_offset(std::string_view text, std::int64_t& off, std::string& err) {
    std::string_view s = text;
    const bool neg = !s.empty() && s[0] == '-';
    if (neg) s.remove_prefix(1);
    std::uint64_t m = 0;
    if (!all_digits(s) || !big_to_u64(make(false, mag_of_digits(s)), m) || m >= (std::uint64_t{1} << 63)) {
        err = "offset '" + std::string(text) + "' is not a decimal integer [-]digits with absolute value below 2^63";
        return false;
    }
    off = neg ? -static_cast<std::int64_t>(m) : static_cast<std::int64_t>(m);
    return true;
}

bool exact_scale(const Big& v, std::int64_t num, std::int64_t den, std::int64_t off, std::int64_t& out) {
    const Big r = big_round_div(big_mul(v, Big::of_i64(num)), Big::of_i64(den));
    return big_to_i64(big_add(r, Big::of_i64(off)), out);
}

Big exact_unscale(std::int64_t x, std::int64_t num, std::int64_t den, std::int64_t off) {
    const Big d = big_sub(Big::of_i64(x), Big::of_i64(off));
    return big_round_div(big_mul(d, Big::of_i64(den)), Big::of_i64(num));
}

bool iscale_decode(const std::string& text, std::int64_t num, std::int64_t den, std::int64_t off,
                   std::int64_t& out, std::string& why) {
    // -?digits(.digits)?([eE][+-]?digits)?
    std::size_t i = 0;
    const std::size_t n = text.size();
    auto digits = [&]() {
        const std::size_t from = i;
        while (i < n && text[i] >= '0' && text[i] <= '9') ++i;
        return std::string_view(text).substr(from, i - from);
    };
    auto bad_text = [&]() {
        why = "the text \"" + text + "\" is not a decimal number -?digits(.digits)?([eE][+-]?digits)?";
        return false;
    };
    const bool neg = i < n && text[i] == '-';
    if (neg) ++i;
    const std::string_view ip = digits();
    if (ip.empty()) return bad_text();
    std::string_view fp;
    if (i < n && text[i] == '.') {
        ++i;
        fp = digits();
        if (fp.empty()) return bad_text();
    }
    std::int64_t exp = 0;
    if (i < n && (text[i] == 'e' || text[i] == 'E')) {
        ++i;
        bool eneg = false;
        if (i < n && (text[i] == '+' || text[i] == '-')) eneg = text[i++] == '-';
        std::string_view ed = digits();
        if (ed.empty()) return bad_text();
        while (ed.size() > 1 && ed[0] == '0') ed.remove_prefix(1);
        if (ed.size() > 3 || std::stoi(std::string(ed)) > 400) {
            why = "the exponent of \"" + text + "\" is above 400 in absolute value";
            return false;
        }
        exp = std::stoi(std::string(ed));
        if (eneg) exp = -exp;
    }
    if (i != n) return bad_text();

    // r = D × 10^E with D the digits without leading zeros.
    std::string d = std::string(ip) + std::string(fp);
    const std::size_t lead = d.find_first_not_of('0');
    const std::int64_t e = exp - static_cast<std::int64_t>(fp.size());
    auto range = [&]() {
        why = "\"" + text + "\" scales to a value outside the signed 64-bit range";
        return false;
    };
    if (lead == std::string::npos) {
        out = off;  // r is 0, and round(0) + off is the offset
        return true;
    }
    d.erase(0, lead);
    // The position of the leading digit: r is in [10^L, 10^(L+1)).
    const std::int64_t L = static_cast<std::int64_t>(d.size()) - 1 + e;
    // |factor| is in [2^-32, 2^32] and |off| < 2^63: from 10^30 the result is
    // beyond 2^63, and below 10^-31 the product rounds to 0.
    if (L >= 30) return range();
    if (L <= -32) {
        out = off;
        return true;
    }
    Mag a = mag_mul(mag_of_digits(d), mag_of_u64(static_cast<std::uint64_t>(num < 0 ? -num : num)));
    Mag b = mag_of_u64(static_cast<std::uint64_t>(den));
    if (e >= 0) a = mag_mul(a, mag_pow10(static_cast<std::size_t>(e)));
    else b = mag_mul(b, mag_pow10(static_cast<std::size_t>(-e)));
    const Big r = big_round_div(make(neg != (num < 0), a), make(false, b));
    if (!big_to_i64(big_add(r, Big::of_i64(off)), out)) return range();
    return true;
}

bool iscale_encode(std::int64_t x, std::int64_t num, std::int64_t den, std::int64_t off, std::string& out,
                   std::string& why) {
    const Big nn = big_mul(big_sub(Big::of_i64(x), Big::of_i64(off)), Big::of_i64(den));
    const Mag m = mag_of_u64(static_cast<std::uint64_t>(num < 0 ? -num : num));
    Mag q, r;
    mag_divmod(nn.mag, m, q, r);
    std::string frac;
    while (!r.empty()) {
        if (frac.size() == 18) {
            why = "the quotient of " + std::to_string(x) + " needs more than 18 fraction digits";
            return false;
        }
        mag_mul_small_add(r, 10, 0);
        Mag dq, dr;
        mag_divmod(r, m, dq, dr);
        std::uint64_t digit = 0;
        big_to_u64(make(false, dq), digit);
        frac += static_cast<char>('0' + digit);
        r = std::move(dr);
    }
    const bool neg = !nn.mag.empty() && (nn.neg != (num < 0));
    out = (neg ? "-" : "") + mag_decimal(q);
    if (!frac.empty()) out += "." + frac;
    return true;
}

}  // namespace goat_transformers::detail
