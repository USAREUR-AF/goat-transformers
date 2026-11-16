#include "util.hpp"

#include <charconv>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <system_error>

namespace goat_transformers::detail {

namespace {
bool is_space(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }
}  // namespace

std::string_view trim(std::string_view s) {
    while (!s.empty() && is_space(s.front())) s.remove_prefix(1);
    while (!s.empty() && is_space(s.back())) s.remove_suffix(1);
    return s;
}

std::string format_double(double d) {
    if (!std::isfinite(d)) throw std::domain_error("non-finite number");
    if (d == 0.0) return "0";  // ruling 3: negative zero prints as 0
    char buf[64];
    // Scientific form always yields the shortest round-trip digit string; the
    // default form may print large integral values with every exact digit
    // (1.2345678901234568e20 -> ...683968), which is not the shortest decimal.
    auto res = std::to_chars(buf, buf + sizeof buf, d, std::chars_format::scientific);
    if (res.ec != std::errc()) throw std::domain_error("number formatting failed");
    std::string s(buf, res.ptr);
    std::size_t e = s.find_first_of("eE");
    if (e == std::string::npos) return s;

    // Rewrite exponent form as plain decimal.
    std::string mant = s.substr(0, e);
    int exp = 0;
    {
        std::string_view es(s.c_str() + e + 1, s.size() - e - 1);
        if (!es.empty() && es.front() == '+') es.remove_prefix(1);
        auto r = std::from_chars(es.data(), es.data() + es.size(), exp);
        if (r.ec != std::errc()) throw std::domain_error("number formatting failed");
    }
    bool neg = !mant.empty() && mant[0] == '-';
    if (neg) mant.erase(0, 1);
    std::string digits;
    long point;
    std::size_t dot = mant.find('.');
    if (dot == std::string::npos) {
        digits = mant;
        point = static_cast<long>(mant.size());
    } else {
        digits = mant.substr(0, dot) + mant.substr(dot + 1);
        point = static_cast<long>(dot);
    }
    point += exp;
    // strip leading zeros of the digit string (keeps point consistent)
    while (digits.size() > 1 && digits[0] == '0') {
        digits.erase(0, 1);
        --point;
    }
    std::string out;
    long nd = static_cast<long>(digits.size());
    if (point <= 0) {
        out = "0." + std::string(static_cast<std::size_t>(-point), '0') + digits;
    } else if (point >= nd) {
        out = digits + std::string(static_cast<std::size_t>(point - nd), '0');
    } else {
        out = digits.substr(0, static_cast<std::size_t>(point)) + "." +
              digits.substr(static_cast<std::size_t>(point));
    }
    // drop trailing fractional zeros, if any slipped in
    if (out.find('.') != std::string::npos) {
        while (!out.empty() && out.back() == '0') out.pop_back();
        if (!out.empty() && out.back() == '.') out.pop_back();
    }
    return neg ? "-" + out : out;
}

bool parse_double(std::string_view s, double& out) {
    s = trim(s);
    if (!s.empty() && s.front() == '+') s.remove_prefix(1);
    if (s.empty()) return false;
    // reject the textual specials from_chars would otherwise accept
    char c0 = s.front() == '-' && s.size() > 1 ? s[1] : s.front();
    if (!(c0 >= '0' && c0 <= '9') && c0 != '.') return false;
    double v = 0;
    auto r = std::from_chars(s.data(), s.data() + s.size(), v, std::chars_format::general);
    if (r.ec != std::errc() || r.ptr != s.data() + s.size()) return false;
    if (!std::isfinite(v)) return false;
    out = v;
    return true;
}

bool parse_int(std::string_view s, std::int64_t& out) {
    s = trim(s);
    if (!s.empty() && s.front() == '+') s.remove_prefix(1);
    if (s.empty()) return false;
    std::int64_t v = 0;
    auto r = std::from_chars(s.data(), s.data() + s.size(), v);
    if (r.ec == std::errc() && r.ptr == s.data() + s.size()) {
        out = v;
        return true;
    }
    double d = 0;
    if (!parse_double(s, d)) return false;
    if (std::trunc(d) != d) return false;
    if (d < -9223372036854775808.0 || d >= 9223372036854775808.0) return false;
    out = static_cast<std::int64_t>(d);
    return true;
}

std::int64_t days_from_civil(std::int64_t y, unsigned m, unsigned d) {
    y -= m <= 2 ? 1 : 0;
    const std::int64_t era = (y >= 0 ? y : y - 399) / 400;
    const std::int64_t yoe = y - era * 400;                                   // [0, 399]
    const std::int64_t mp = m > 2 ? static_cast<std::int64_t>(m) - 3 : static_cast<std::int64_t>(m) + 9;
    const std::int64_t doy = (153 * mp + 2) / 5 + static_cast<std::int64_t>(d) - 1;  // [0, 365]
    const std::int64_t doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;            // [0, 146096]
    return era * 146097 + doe - 719468;
}

void civil_from_days(std::int64_t z, std::int64_t& y, unsigned& m, unsigned& d) {
    z += 719468;
    const std::int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    const std::int64_t doe = z - era * 146097;
    const std::int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    const std::int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const std::int64_t mp = (5 * doy + 2) / 153;
    d = static_cast<unsigned>(doy - (153 * mp + 2) / 5 + 1);
    m = static_cast<unsigned>(mp < 10 ? mp + 3 : mp - 9);
    y = yoe + era * 400 + (m <= 2 ? 1 : 0);
}

namespace {
bool fixed_digits(std::string_view s, std::size_t pos, std::size_t n, unsigned& out) {
    if (pos + n > s.size()) return false;
    unsigned v = 0;
    for (std::size_t k = 0; k < n; ++k) {
        char c = s[pos + k];
        if (c < '0' || c > '9') return false;
        v = v * 10 + static_cast<unsigned>(c - '0');
    }
    out = v;
    return true;
}
bool leap(std::int64_t y) { return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0; }
unsigned days_in_month(std::int64_t y, unsigned m) {
    static const unsigned dm[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    return m == 2 && leap(y) ? 29 : dm[m - 1];
}
}  // namespace

bool parse_iso8601_ms(std::string_view s, std::int64_t& out) {
    s = trim(s);
    unsigned Y, M, D, h, mi, sec;
    if (!fixed_digits(s, 0, 4, Y) || s.size() < 19 || s[4] != '-' || !fixed_digits(s, 5, 2, M) ||
        s[7] != '-' || !fixed_digits(s, 8, 2, D) || (s[10] != 'T' && s[10] != 't') || !fixed_digits(s, 11, 2, h) ||
        s[13] != ':' || !fixed_digits(s, 14, 2, mi) || s[16] != ':' || !fixed_digits(s, 17, 2, sec))
        return false;
    if (M < 1 || M > 12 || D < 1 || D > days_in_month(Y, M) || h > 23 || mi > 59 || sec > 59)
        return false;
    std::size_t p = 19;
    unsigned ms = 0;
    if (p < s.size() && s[p] == '.') {
        ++p;
        std::size_t start = p;
        unsigned scale = 100;
        while (p < s.size() && s[p] >= '0' && s[p] <= '9') {
            ms += static_cast<unsigned>(s[p] - '0') * scale;
            scale /= 10;
            ++p;
        }
        if (p == start) return false;
    }
    // 0.6: the designator is Z, z, +hh:mm or -hh:mm; the instant is converted to UTC.
    std::string_view zone = s.substr(p);
    std::int64_t offset_min = 0;
    if (zone != "Z" && zone != "z") {
        unsigned oh, om;
        if (zone.size() != 6 || (zone[0] != '+' && zone[0] != '-') || !fixed_digits(zone, 1, 2, oh) ||
            zone[3] != ':' || !fixed_digits(zone, 4, 2, om) || oh > 23 || om > 59)
            return false;
        offset_min = static_cast<std::int64_t>(oh) * 60 + om;
        if (zone[0] == '-') offset_min = -offset_min;
    }
    std::int64_t days = days_from_civil(Y, M, D);
    out = ((days * 24 + h) * 60 + mi - offset_min) * 60000 + static_cast<std::int64_t>(sec) * 1000 + ms;
    return true;
}

std::string format_iso8601_ms(std::int64_t ms) {
    // floor division so negative epochs land on the right civil second
    std::int64_t days = ms / 86400000;
    std::int64_t rem = ms % 86400000;
    if (rem < 0) {
        rem += 86400000;
        --days;
    }
    std::int64_t y;
    unsigned m, d;
    civil_from_days(days, y, m, d);
    if (y < 0 || y > 9999) throw std::domain_error("year outside 0000-9999");
    unsigned msec = static_cast<unsigned>(rem % 1000);
    std::int64_t secs = rem / 1000;
    unsigned hh = static_cast<unsigned>(secs / 3600), mm = static_cast<unsigned>((secs / 60) % 60),
             ss = static_cast<unsigned>(secs % 60);
    char buf[32];
    auto put = [&](std::size_t pos, unsigned v, int width) {
        for (int k = width - 1; k >= 0; --k) {
            buf[pos + static_cast<std::size_t>(k)] = static_cast<char>('0' + v % 10);
            v /= 10;
        }
    };
    put(0, static_cast<unsigned>(y), 4);
    buf[4] = '-';
    put(5, m, 2);
    buf[7] = '-';
    put(8, d, 2);
    buf[10] = 'T';
    put(11, hh, 2);
    buf[13] = ':';
    put(14, mm, 2);
    buf[16] = ':';
    put(17, ss, 2);
    buf[19] = '.';
    put(20, msec, 3);
    buf[23] = 'Z';
    return std::string(buf, 24);
}

void append_utf8(std::string& out, std::uint32_t cp) {
    if (cp < 0x80) {
        out += static_cast<char>(cp);
    } else if (cp < 0x800) {
        out += static_cast<char>(0xC0 | (cp >> 6));
        out += static_cast<char>(0x80 | (cp & 0x3F));
    } else if (cp < 0x10000) {
        out += static_cast<char>(0xE0 | (cp >> 12));
        out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
        out += static_cast<char>(0x80 | (cp & 0x3F));
    } else {
        out += static_cast<char>(0xF0 | (cp >> 18));
        out += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
        out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
        out += static_cast<char>(0x80 | (cp & 0x3F));
    }
}

}  // namespace goat_transformers::detail
