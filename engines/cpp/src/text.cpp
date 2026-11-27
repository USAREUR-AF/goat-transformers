// The `text` wire (engine-spec.md, "Version 0.10: the `text` wire").
//
// A message is one record of ASCII text: an optional start text, fields
// separated by a delimiter (or one field with `delimiter none`), and an
// optional `nmea` checksum. A locator addresses a field, a column of a field,
// or a pair of fields. Residue is every non-empty field no line addresses,
// keyed by its index in decimal.
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "codecs.hpp"
#include "transforms.hpp"
#include "util.hpp"

namespace goat_transformers::detail {

namespace {

using Loc = TextLocator;

bool parse_index(std::string_view s, std::uint32_t& out) {
    if (s.empty() || s.size() > 10) return false;
    std::uint64_t v = 0;
    for (char c : s) {
        if (c < '0' || c > '9') return false;
        v = v * 10 + static_cast<std::uint64_t>(c - '0');
    }
    if (v > 0xFFFFFFFFull) return false;
    out = static_cast<std::uint32_t>(v);
    return true;
}

bool two_part(Transform t) { return t == Transform::Dm || t == Transform::HmsDmy; }

// The numeric transforms of "Locators": a column's leading spaces are removed
// for them, and encode pads their columns on the left with `0`.
bool numeric(Transform t) {
    return t == Transform::Int || t == Transform::IntW || t == Transform::Float || t == Transform::Dec;
}

bool valid_on_text(Transform t) {
    switch (t) {
        case Transform::String:
        case Transform::Int:
        case Transform::Float:
        case Transform::Iso8601Ms:
        case Transform::Iso8601S:
        case Transform::IntW:
        case Transform::Dec:
        case Transform::Dm:
        case Transform::Hms:
        case Transform::HmsDmy:
        case Transform::CodeStr:  // v0.46
        case Transform::CodeNum: return true;
        default: return false;
    }
}

std::uint32_t highest_index(const Loc& l) { return l.kind == Loc::Kind::Pair && l.j > l.i ? l.j : l.i; }

bool is_digit(char c) { return c >= '0' && c <= '9'; }

int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

// ---------------------------------------------------------------- numbers

// An optional sign and one or more digits, from -2^63 to 2^63-1.
bool text_int(std::string_view s, std::int64_t& out) {
    std::size_t k = 0;
    bool neg = false;
    if (k < s.size() && (s[k] == '+' || s[k] == '-')) neg = s[k++] == '-';
    if (k >= s.size()) return false;
    const std::uint64_t limit = neg ? (std::uint64_t{1} << 63) : (std::uint64_t{1} << 63) - 1;
    std::uint64_t mag = 0;
    for (; k < s.size(); ++k) {
        if (!is_digit(s[k])) return false;
        const std::uint64_t d = static_cast<std::uint64_t>(s[k] - '0');
        if (mag > (limit - d) / 10) return false;
        mag = mag * 10 + d;
    }
    if (neg) out = mag == (std::uint64_t{1} << 63) ? INT64_MIN : -static_cast<std::int64_t>(mag);
    else out = static_cast<std::int64_t>(mag);
    return true;
}

// An optional sign, then digits with at most one `.`, at least one digit; no
// exponent. The double nearest the decimal; not finite is refused.
bool text_decimal(std::string_view s, double& out) {
    std::size_t k = 0;
    if (k < s.size() && (s[k] == '+' || s[k] == '-')) ++k;
    std::size_t digits = 0, dots = 0;
    for (std::size_t i = k; i < s.size(); ++i) {
        if (is_digit(s[i])) ++digits;
        else if (s[i] == '.') ++dots;
        else return false;
    }
    if (digits == 0 || dots > 1) return false;
    std::string body(s.substr(s[0] == '+' ? 1 : 0));
    double v = 0;
    auto r = std::from_chars(body.data(), body.data() + body.size(), v, std::chars_format::fixed);
    if (r.ec == std::errc::result_out_of_range) {
        // Underflow is a number (its nearest double is tiny or zero); overflow is not finite.
        char* end = nullptr;
        v = std::strtod(body.c_str(), &end);
        if (end != body.c_str() + body.size()) return false;
    } else if (r.ec != std::errc() || r.ptr != body.data() + body.size()) {
        return false;
    }
    if (!std::isfinite(v)) return false;
    out = v;
    return true;
}

// `n` decimal digits from `s[at]`.
bool fixed_number(std::string_view s, std::size_t at, std::size_t n, unsigned& out) {
    if (at + n > s.size()) return false;
    unsigned v = 0;
    for (std::size_t k = 0; k < n; ++k) {
        if (!is_digit(s[at + k])) return false;
        v = v * 10 + static_cast<unsigned>(s[at + k] - '0');
    }
    out = v;
    return true;
}

// From `at` on: nothing, or `.` and one or more digits.
bool optional_fraction(std::string_view s, std::size_t at) {
    if (at == s.size()) return true;
    if (s[at] != '.' || at + 1 == s.size()) return false;
    for (std::size_t k = at + 1; k < s.size(); ++k)
        if (!is_digit(s[k])) return false;
    return true;
}

// `hhmmss[.f+]`: hours, minutes, and the seconds' text (`ss[.f+]`).
void hms_parts(std::string_view s, unsigned& h, unsigned& m, std::string_view& sec) {
    unsigned whole = 0;
    if (!fixed_number(s, 0, 2, h) || !fixed_number(s, 2, 2, m) || !fixed_number(s, 4, 2, whole) ||
        !optional_fraction(s, 6))
        throw std::invalid_argument("not hhmmss[.f]: \"" + std::string(s) + "\"");
    if (h >= 24 || m >= 60 || whole >= 60) throw std::invalid_argument("not a time of day: \"" + std::string(s) + "\"");
    sec = s.substr(4);
}

bool leap_year(std::int64_t y) { return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0; }

unsigned month_days(std::int64_t y, unsigned m) {
    static const unsigned dm[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    return m == 2 && leap_year(y) ? 29 : dm[m - 1];
}

const double kPow10[] = {1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9};
const std::uint64_t kIntPow10[] = {1ull, 10ull, 100ull, 1000ull, 10000ull, 100000ull, 1000000ull,
                                   10000000ull, 100000000ull, 1000000000ull};
const double kTwo53 = 9007199254740992.0;

std::string digits_of(std::uint64_t v, std::size_t width) {
    std::string s = std::to_string(v);
    if (s.size() < width) s.insert(0, width - s.size(), '0');
    return s;
}

// The rounded value of rule 2 of "Rules for these transforms": half away from
// zero; 2^53 or more, or not finite, is refused.
double rounded(double y) {
    const double n = std::round(y);
    if (!std::isfinite(n) || std::fabs(n) >= kTwo53) throw std::invalid_argument("the value is too large to write");
    return n;
}

double finite_model(const Value& v) {
    const double x = model_double(v);
    if (!std::isfinite(x)) throw std::invalid_argument("the value is not finite");
    return x;
}

// ---------------------------------------------------------------- transforms

// Decode the text of a field line: `a`, and `b` for a pair. Throws std::invalid_argument.
Value text_decode(const FieldLine& f, const std::string& a, const std::string& b) {
    switch (f.transform) {
        case Transform::String: return Value::of_string(a);
        case Transform::CodeStr:
        case Transform::CodeNum: return decode_value(f, a);  // v0.46
        case Transform::Int:
        case Transform::IntW: {
            std::int64_t n;
            if (!text_int(a, n)) throw std::invalid_argument("not an integer: \"" + a + "\"");
            return Value::of_int(n);
        }
        case Transform::Float:
        case Transform::Dec: {
            double d;
            if (!text_decimal(a, d)) throw std::invalid_argument("not a decimal number: \"" + a + "\"");
            return Value::of_float(d);
        }
        case Transform::Iso8601Ms:
        case Transform::Iso8601S: {
            std::int64_t ms;
            if (!parse_iso8601_ms(a, ms)) throw std::invalid_argument("not an ISO 8601 time: \"" + a + "\"");
            return Value::of_int(ms);
        }
        case Transform::Dm: {
            const std::size_t d = static_cast<std::size_t>(f.text_d);
            unsigned degrees = 0, minutes = 0;
            if (!fixed_number(a, 0, d, degrees) || !fixed_number(a, d, 2, minutes) || !optional_fraction(a, d + 2))
                throw std::invalid_argument("not " + std::to_string(d) + " digits of degrees and mm[.f]: \"" + a + "\"");
            if (minutes >= 60) throw std::invalid_argument("minutes of 60 or more: \"" + a + "\"");
            if (b.size() != 1 || (b[0] != f.text_p && b[0] != f.text_n))
                throw std::invalid_argument("the letter is not " + std::string(1, f.text_p) + " or " +
                                            std::string(1, f.text_n) + ": \"" + b + "\"");
            double mins;
            if (!text_decimal(std::string_view(a).substr(d), mins)) throw std::invalid_argument("bad minutes: \"" + a + "\"");
            double value = static_cast<double>(degrees) + mins / 60.0;
            if (b[0] == f.text_n) value = -value;
            return Value::of_float(value);
        }
        case Transform::Hms: {
            unsigned h, m;
            std::string_view sec;
            hms_parts(a, h, m, sec);
            double s;
            if (!text_decimal(sec, s)) throw std::invalid_argument("bad seconds: \"" + a + "\"");
            return Value::of_float(static_cast<double>(h * 3600 + m * 60) + s);
        }
        case Transform::HmsDmy: {
            unsigned h, m;
            std::string_view sec;
            hms_parts(a, h, m, sec);
            unsigned s = 0, ms = 0;
            fixed_number(sec, 0, 2, s);
            // Fraction digits beyond milliseconds are truncated.
            for (std::size_t k = 0, scale = 100; k < 3 && 3 + k < sec.size(); ++k, scale /= 10)
                ms += static_cast<unsigned>(sec[3 + k] - '0') * static_cast<unsigned>(scale);
            unsigned dd, mm, yy;
            if (b.size() != 6 || !fixed_number(b, 0, 2, dd) || !fixed_number(b, 2, 2, mm) || !fixed_number(b, 4, 2, yy))
                throw std::invalid_argument("not ddmmyy: \"" + b + "\"");
            const std::int64_t year = yy >= 80 ? 1900 + yy : 2000 + yy;
            if (mm < 1 || mm > 12 || dd < 1 || dd > month_days(year, mm))
                throw std::invalid_argument("a date that does not exist: \"" + b + "\"");
            const std::int64_t days = days_from_civil(year, mm, dd);
            return Value::of_int(days * 86400000 + static_cast<std::int64_t>(h * 3600 + m * 60 + s) * 1000 + ms);
        }
        default: break;
    }
    throw std::invalid_argument("not a transform of wire text");
}

// The text a field line writes: `a`, and `b` for a pair. Throws std::invalid_argument.
void text_encode(const FieldLine& f, const Value& v, std::string& a, std::string& b) {
    switch (f.transform) {
        case Transform::String:
        case Transform::Int:
        case Transform::Float:
        case Transform::Iso8601Ms:
        case Transform::Iso8601S:
        case Transform::CodeStr:  // v0.46
        case Transform::CodeNum: a = encode_value(f, v); return;
        case Transform::IntW: {
            const std::int64_t n = model_int(v);
            const std::uint64_t mag = n < 0 ? 0 - static_cast<std::uint64_t>(n) : static_cast<std::uint64_t>(n);
            a = (n < 0 ? "-" : "") + digits_of(mag, static_cast<std::size_t>(f.text_w));
            return;
        }
        case Transform::Dec: {
            const int fd = f.text_f;
            const double n = rounded(finite_model(v) * kPow10[fd]);
            std::string digits = digits_of(static_cast<std::uint64_t>(std::fabs(n)), static_cast<std::size_t>(fd) + 1);
            if (fd > 0) digits.insert(digits.size() - static_cast<std::size_t>(fd), 1, '.');
            if (f.text_w > 0 && digits.size() < static_cast<std::size_t>(f.text_w))
                digits.insert(0, static_cast<std::size_t>(f.text_w) - digits.size(), '0');
            a = (n < 0 ? "-" : "") + digits;
            return;
        }
        case Transform::Dm: {
            const int fd = f.text_f;
            const double x = finite_model(v);
            const std::uint64_t m = static_cast<std::uint64_t>(rounded(std::fabs(x) * 60.0 * kPow10[fd]));
            const std::uint64_t unit = 60 * kIntPow10[fd];
            const std::uint64_t degrees = m / unit, rest = m % unit;
            std::string deg = std::to_string(degrees);
            if (deg.size() > static_cast<std::size_t>(f.text_d))
                throw std::invalid_argument("degrees " + deg + " do not fit " + std::to_string(f.text_d) + " digits");
            a = digits_of(degrees, static_cast<std::size_t>(f.text_d)) + digits_of(rest / kIntPow10[fd], 2);
            if (fd > 0) a += "." + digits_of(rest % kIntPow10[fd], static_cast<std::size_t>(fd));
            b = std::string(1, x < 0 && m > 0 ? f.text_n : f.text_p);
            return;
        }
        case Transform::Hms: {
            const int fd = f.text_f;
            const double n = rounded(finite_model(v) * kPow10[fd]);
            if (!(n >= 0) || n >= 86400.0 * kPow10[fd])
                throw std::invalid_argument("not a time of day: " + format_double(finite_model(v)));
            const std::uint64_t u = static_cast<std::uint64_t>(n);
            const std::uint64_t secs = u / kIntPow10[fd];
            a = digits_of(secs / 3600, 2) + digits_of(secs / 60 % 60, 2) + digits_of(secs % 60, 2);
            if (fd > 0) a += "." + digits_of(u % kIntPow10[fd], static_cast<std::size_t>(fd));
            return;
        }
        case Transform::HmsDmy: {
            const std::int64_t ms = model_int(v);
            std::int64_t days = ms / 86400000, rem = ms % 86400000;
            if (rem < 0) {
                rem += 86400000;
                --days;
            }
            std::int64_t y;
            unsigned mo, d;
            civil_from_days(days, y, mo, d);
            if (y < 1980 || y > 2079) throw std::invalid_argument("a year outside 1980 to 2079: " + std::to_string(y));
            const std::uint64_t r = static_cast<std::uint64_t>(rem);
            const std::uint64_t secs = r / 1000;
            a = digits_of(secs / 3600, 2) + digits_of(secs / 60 % 60, 2) + digits_of(secs % 60, 2);
            const int fd = f.text_f;
            if (fd > 0) a += "." + digits_of(r % 1000 / kIntPow10[3 - fd], static_cast<std::size_t>(fd));
            b = digits_of(d, 2) + digits_of(mo, 2) + digits_of(static_cast<std::uint64_t>(y % 100), 2);
            return;
        }
        default: break;
    }
    throw std::invalid_argument("not a transform of wire text");
}

// ---------------------------------------------------------------- reading a record

using Record = std::vector<std::string>;

// Steps 1 to 5 of "Reading a record". Throws malformed-wire.
Record read_record(const Pack& p, const std::string& bytes) {
    std::string_view s(bytes);
    if (s.size() >= 2 && s.substr(s.size() - 2) == "\r\n") s.remove_suffix(2);
    else if (!s.empty() && s.back() == '\n') s.remove_suffix(1);
    for (std::size_t k = 0; k < s.size(); ++k) {
        const unsigned char c = static_cast<unsigned char>(s[k]);
        if (c < 0x20 || c > 0x7E)
            throw Error(ErrorKind::MalformedWire, p.format, "",
                        "byte " + std::to_string(k) + " is " + std::to_string(c) + ", outside 0x20 to 0x7E");
    }
    if (!p.start.empty()) {
        if (s.substr(0, p.start.size()) != p.start)
            throw Error(ErrorKind::MalformedWire, p.format, "", "the record does not begin with '" + p.start + "'");
        s.remove_prefix(p.start.size());
    }
    if (p.checksum_nmea) {
        const std::size_t n = s.size();
        if (n < 3 || s[n - 3] != '*' || hex_value(s[n - 2]) < 0 || hex_value(s[n - 1]) < 0)
            throw Error(ErrorKind::MalformedWire, p.format, "", "the record does not end with '*' and two hex digits");
        unsigned x = 0;
        for (std::size_t k = 0; k + 3 < n; ++k) x ^= static_cast<unsigned char>(s[k]);
        const unsigned want = static_cast<unsigned>(hex_value(s[n - 2]) * 16 + hex_value(s[n - 1]));
        if (x != want)
            throw Error(ErrorKind::MalformedWire, p.format, "",
                        "the checksum is " + std::to_string(want) + ", the text's XOR is " + std::to_string(x));
        s.remove_suffix(3);
        if (s.find('*') != std::string_view::npos)
            throw Error(ErrorKind::MalformedWire, p.format, "", "a '*' before the checksum");
    }
    Record rec;
    if (p.delimiter_none) {
        rec.emplace_back(s);
        return rec;
    }
    std::size_t at = 0;
    for (;;) {
        const std::size_t d = s.find(p.delimiter, at);
        rec.emplace_back(s.substr(at, d == std::string_view::npos ? std::string_view::npos : d - at));
        if (d == std::string_view::npos) break;
        at = d + 1;
    }
    return rec;
}

// The text at field `idx` (whole), or at a column of it; false when absent.
bool read_part(const Record& rec, std::uint64_t idx, const Loc& l, bool numeric_text, std::string& out) {
    if (idx >= rec.size()) return false;
    const std::string& fld = rec[idx];
    if (l.kind != Loc::Kind::Column) {
        if (fld.empty()) return false;
        out = fld;
        return true;
    }
    if (l.from >= fld.size()) return false;
    out = fld.substr(l.from, l.len);
    while (!out.empty() && out.back() == ' ') out.pop_back();
    if (numeric_text) {
        std::size_t k = 0;
        while (k < out.size() && out[k] == ' ') ++k;
        out.erase(0, k);
    }
    return !out.empty();
}

// Read one field line relative to `base` (an item's first field).
void decode_field(Decoder& d, const FieldLine& f, const Record& rec, std::uint64_t base) {
    if (!d.wants(f)) return;
    const Loc& l = f.text_loc;
    std::string a, b;
    if (!read_part(rec, base + l.i, l, numeric(f.transform), a)) return;
    if (l.kind == Loc::Kind::Pair && !read_part(rec, base + l.j, l, false, b)) return;  // a pair with a half absent
    Value v;
    try {
        v = text_decode(f, a, b);
    } catch (const std::invalid_argument& ex) {
        d.fail(f, ex.what());
        return;
    }
    d.put(f, std::move(v));
}

void mark(std::set<std::uint64_t>& addressed, const Loc& l, std::uint64_t base) {
    addressed.insert(base + l.i);
    if (l.kind == Loc::Kind::Pair) addressed.insert(base + l.j);
}

std::vector<Item> decode_items(const Pack& p, const GroupLine& g, const Record& rec) {
    std::vector<Item> items;
    const std::uint64_t i = g.text_index, n = g.text_item;
    const std::uint64_t count = (rec.size() - i + n - 1) / n;
    // 0.11 ruling 7d: compared with the limit before any field is read.
    take_items(p, g.list, count);
    std::vector<LineRef> lines_tmp;
    const std::vector<LineRef>& lines = body_lines(p, g, lines_tmp);
    items.reserve(static_cast<std::size_t>(count));
    for (std::uint64_t t = 0; t < count; ++t) {
        items.emplace_back();
        Decoder d(p, items.back());
        for (const auto& line : lines)
            if (line.field) decode_field(d, *line.field, rec, i + t * n);
        d.finish();
    }
    return items;
}

// ---------------------------------------------------------------- writing a record

struct Slot {
    bool whole_set = false;   // a whole-field line (or residue) wrote the field
    std::string whole;
    std::string cols;         // columns of field lines; characters no column wrote are spaces
    std::vector<bool> col_mask;
    bool fixed_whole_set = false;  // a whole-field `when` or `const`
    std::string fixed_whole;
    std::string fixed_cols;        // `when` and `const` columns written before any whole one
    std::vector<bool> fixed_mask;

    std::string text() const {
        std::string base = fixed_whole_set ? fixed_whole : whole_set ? whole : cols;
        if (base.size() < fixed_cols.size()) base.resize(fixed_cols.size(), ' ');
        for (std::size_t k = 0; k < fixed_cols.size(); ++k)
            if (fixed_mask[k]) base[k] = fixed_cols[k];
        return base;
    }
};

// Earlier characters stand.
void write_columns(std::string& buf, std::vector<bool>& mask, std::size_t from, const std::string& text) {
    if (buf.size() < from + text.size()) {
        buf.resize(from + text.size(), ' ');
        mask.resize(from + text.size(), false);
    }
    for (std::size_t k = 0; k < text.size(); ++k)
        if (!mask[from + k]) {
            buf[from + k] = text[k];
            mask[from + k] = true;
        }
}

struct Writer {
    const Pack& p;
    std::map<std::uint64_t, Slot> slots;
    // Field index -> every line that addresses it carries `optional`.
    std::map<std::uint64_t, bool> optional_only;
    std::uint64_t count = 0;  // fields in the record

    explicit Writer(const Pack& pack) : p(pack) {}

    void address(std::uint64_t idx, bool optional) {
        auto r = optional_only.emplace(idx, optional);
        if (!r.second) r.first->second = r.first->second && optional;
        if (idx + 1 > count) count = idx + 1;
    }

    // Text from a transform: no delimiter, no `*` under `nmea`, only 0x20 to 0x7E.
    void check_text(const FieldLine& f, const std::string& text) const {
        for (char ch : text) {
            const unsigned char c = static_cast<unsigned char>(ch);
            if (c < 0x20 || c > 0x7E || (!p.delimiter_none && ch == p.delimiter) || (p.checksum_nmea && ch == '*'))
                throw Error(ErrorKind::TransformEncode, p.format, f.locator,
                            f.key + ": the text \"" + text + "\" holds a character the record cannot carry");
        }
    }

    void field(const EncodeSource& src, const FieldLine& f, std::uint64_t base) {
        const Loc& l = f.text_loc;
        address(base + l.i, f.optional);
        if (l.kind == Loc::Kind::Pair) address(base + l.j, f.optional);
        Value v;
        // A line suppressed by `with` is a line whose key is absent, with no
        // default (0.18 ruling 1).
        if (src.suppressed(f) || !src.value(f, v)) return;
        std::string a, b;
        try {
            text_encode(f, v, a, b);
        } catch (const std::invalid_argument& ex) {
            throw Error(ErrorKind::TransformEncode, p.format, f.locator, f.key + ": " + ex.what());
        }
        check_text(f, a);
        if (l.kind == Loc::Kind::Pair) check_text(f, b);
        switch (l.kind) {
            case Loc::Kind::Field: {
                Slot& s = slots[base + l.i];
                if (!s.whole_set) {
                    s.whole_set = true;
                    s.whole = a;
                }
                break;
            }
            case Loc::Kind::Pair: {
                Slot& s1 = slots[base + l.i];
                if (!s1.whole_set) {
                    s1.whole_set = true;
                    s1.whole = a;
                }
                Slot& s2 = slots[base + l.j];
                if (!s2.whole_set) {
                    s2.whole_set = true;
                    s2.whole = b;
                }
                break;
            }
            case Loc::Kind::Column: {
                if (a.size() > l.len)
                    throw Error(ErrorKind::TransformEncode, p.format, f.locator,
                                f.key + ": the text \"" + a + "\" is longer than its column of " +
                                    std::to_string(l.len) + " characters");
                if (a.size() < l.len) {
                    const std::size_t pad = l.len - a.size();
                    if (numeric(f.transform)) a.insert(!a.empty() && a[0] == '-' ? 1 : 0, pad, '0');
                    else a.append(pad, ' ');
                }
                Slot& s = slots[base + l.i];
                write_columns(s.cols, s.col_mask, l.from, a);
                break;
            }
        }
    }

    void fixed(const WhenLine& w, std::uint64_t base) {
        if (w.present) return;  // addresses nothing and writes nothing
        const Loc& l = w.text_loc;
        address(base + l.i, false);
        Slot& s = slots[base + l.i];
        if (s.fixed_whole_set) return;  // an earlier `when` or `const` wrote the whole field
        if (l.kind == Loc::Kind::Column) {
            std::string text = w.text;
            if (text.size() < l.len) text.append(l.len - text.size(), ' ');
            write_columns(s.fixed_cols, s.fixed_mask, l.from, text);
        } else {
            s.fixed_whole_set = true;
            s.fixed_whole = w.text;
        }
    }

    void group(const EncodeSource& src, const GroupLine& g) {
        const std::vector<Item>* items = src.list(g);
        if (!items || items->empty()) return;
        std::vector<LineRef> lines_tmp;
        const std::vector<LineRef>& lines = body_lines(p, g, lines_tmp);
        const std::uint64_t n = g.text_item;
        for (std::size_t t = 0; t < items->size(); ++t) {
            const std::uint64_t base = g.text_index + t * n;
            const EncodeSource item_src(p, g, (*items)[t]);
            for (const auto& line : lines) {
                if (line.field) field(item_src, *line.field, base);
                else if (line.konst) fixed(*line.konst, base);
            }
            for (std::uint64_t k = 0; k < n; ++k) address(base + k, false);
        }
    }
};

// The group of a scope (at most one); null when it has none.
const GroupLine* scope_group(const std::vector<LineRef>& lines) {
    for (const auto& line : lines)
        if (line.group) return line.group;
    return nullptr;
}

[[noreturn]] void bad(const Pack& p, const std::string& locator, std::size_t line, const std::string& why) {
    throw Error(ErrorKind::BadDirective, p.format, locator, p.source + ":" + std::to_string(line) + ": " + why);
}

// ---- load checks

void check_field_line(const Pack& p, const FieldLine& f, const GroupLine* g) {
    const Loc& l = f.text_loc;
    if (!valid_on_text(f.transform))
        bad(p, f.locator, f.line, std::string("transform '") + transform_name(f.transform) + "' is not valid on wire text");
    const bool pair = l.kind == Loc::Kind::Pair;
    if (pair && !two_part(f.transform))
        bad(p, f.locator, f.line, std::string("a pair on transform '") + transform_name(f.transform) +
                                      "', which does not take two parts");
    if (!pair && two_part(f.transform))
        bad(p, f.locator, f.line, std::string("transform '") + transform_name(f.transform) + "' takes a pair");
    if (pair && l.i == l.j) bad(p, f.locator, f.line, "a pair whose two indexes are equal");
    if (p.delimiter_none && highest_index(l) != 0)
        bad(p, f.locator, f.line, "a locator of a field other than 0 under 'delimiter none'");
    if (g) {
        if (highest_index(l) >= g->text_item)
            bad(p, f.locator, f.line, "the locator lies beyond 'item " + std::to_string(g->text_item) + "'");
        if (f.optional) bad(p, f.locator, f.line, "'optional' inside a group");
    }
}

void check_fixed_line(const Pack& p, const WhenLine& w, const char* word, const GroupLine* g) {
    const Loc& l = w.text_loc;
    const std::string what = std::string("'") + word + "'";
    if (l.kind == Loc::Kind::Pair) bad(p, w.locator, w.line, what + " takes a field or a column, not a pair");
    if (p.delimiter_none && l.i != 0)
        bad(p, w.locator, w.line, "a locator of a field other than 0 under 'delimiter none'");
    if (g && l.i >= g->text_item)
        bad(p, w.locator, w.line, "the locator lies beyond 'item " + std::to_string(g->text_item) + "'");
    if (w.present) return;
    const std::string& v = w.text;
    if (v.empty()) bad(p, w.locator, w.line, what + " value is empty");
    for (char ch : v) {
        const unsigned char c = static_cast<unsigned char>(ch);
        if (c < 0x20 || c > 0x7E) bad(p, w.locator, w.line, what + " value holds a character outside 0x20 to 0x7E");
        if (!p.delimiter_none && ch == p.delimiter) bad(p, w.locator, w.line, what + " value holds the delimiter");
        if (p.checksum_nmea && ch == '*') bad(p, w.locator, w.line, what + " value holds '*' under 'checksum nmea'");
    }
    if (v.front() == ' ' || v.back() == ' ') bad(p, w.locator, w.line, what + " value begins or ends with a space");
    if (l.kind == Loc::Kind::Column && v.size() > l.len)
        bad(p, w.locator, w.line, what + " value is longer than its column");
}

void check_group(const Pack& p, const GroupLine& g) {
    if (p.delimiter_none) bad(p, g.locator, g.line, "a group under 'delimiter none'");
    for (const auto& f : g.fields) check_field_line(p, f, &g);
    for (const auto& c : g.consts) check_fixed_line(p, c, "const", &g);
    if (!g.groups.empty()) bad(p, g.groups.front().locator, g.groups.front().line, "a group nested in a group");
}

// One scope: the common lines, plus a kind's when `k` is not null.
void check_scope(const Pack& p, const Kind* k) {
    std::vector<const GroupLine*> groups;
    for (const auto& g : p.groups) groups.push_back(&g);
    if (k)
        for (const auto& g : k->groups) groups.push_back(&g);
    if (groups.empty()) return;
    if (groups.size() > 1) bad(p, groups[1]->locator, groups[1]->line, "a second group in one scope");
    const GroupLine& g = *groups[0];
    const std::uint32_t at = g.text_index;
    auto beyond = [&](const std::string& locator, const Loc& l, std::size_t line) {
        if (highest_index(l) >= at)
            bad(p, locator, line, "a line at index " + std::to_string(highest_index(l)) + ", at or beyond the group '" +
                                      g.list + "' at index " + std::to_string(at));
    };
    auto lines = [&](const std::vector<FieldLine>& fs, const std::vector<WhenLine>* ws, const std::vector<WhenLine>& cs) {
        for (const auto& f : fs) beyond(f.locator, f.text_loc, f.line);
        if (ws)
            for (const auto& w : *ws) beyond(w.locator, w.text_loc, w.line);
        for (const auto& c : cs) beyond(c.locator, c.text_loc, c.line);
    };
    lines(p.fields, &p.whens, p.consts);
    if (k) lines(k->fields, &k->whens, k->consts);
}

}  // namespace

bool parse_text_locator(const std::string& loc, TextLocator& out) {
    TextLocator t;
    const std::size_t plus = loc.find('+'), colon = loc.find(':');
    if (plus != std::string::npos) {
        if (colon != std::string::npos) return false;
        t.kind = TextLocator::Kind::Pair;
        if (!parse_index(std::string_view(loc).substr(0, plus), t.i) ||
            !parse_index(std::string_view(loc).substr(plus + 1), t.j))
            return false;
    } else if (colon != std::string::npos) {
        const std::size_t c2 = loc.find(':', colon + 1);
        if (c2 == std::string::npos) return false;
        t.kind = TextLocator::Kind::Column;
        const std::string_view s(loc);
        if (!parse_index(s.substr(0, colon), t.i) || !parse_index(s.substr(colon + 1, c2 - colon - 1), t.from) ||
            !parse_index(s.substr(c2 + 1), t.len) || t.len == 0)
            return false;
    } else {
        if (!parse_index(loc, t.i)) return false;
    }
    out = t;
    return true;
}

void parse_text_locators(Pack& p) {
    auto invalid = [&](const std::string& locator, std::size_t line, const char* what) {
        // Ruling 14 of 0.10: a locator not of the three forms is bad-directive.
        throw Error(ErrorKind::BadDirective, p.format, locator,
                    p.source + ":" + std::to_string(line) + ": not a text " + what + " locator");
    };
    auto fields = [&](std::vector<FieldLine>& fs) {
        for (auto& f : fs)
            if (!parse_text_locator(f.locator, f.text_loc)) invalid(f.locator, f.line, "field");
    };
    auto fixed = [&](std::vector<WhenLine>& ws) {
        for (auto& w : ws)
            if (!parse_text_locator(w.locator, w.text_loc)) invalid(w.locator, w.line, "'when' or 'const'");
    };
    struct Groups {
        decltype(fields)& f;
        decltype(fixed)& c;
        decltype(invalid)& inv;
        void operator()(std::vector<GroupLine>& gs) {
            for (auto& g : gs) {
                if (!parse_index(g.locator, g.text_index)) inv(g.locator, g.line, "group");
                f(g.fields);
                c(g.consts);
                (*this)(g.groups);
            }
        }
    } groups{fields, fixed, invalid};
    fields(p.fields);
    fixed(p.whens);
    fixed(p.consts);
    groups(p.groups);
    for (auto& k : p.kinds) {
        fields(k.fields);
        fixed(k.whens);
        fixed(k.consts);
        groups(k.groups);
    }
}

void check_text_pack(const Pack& p) {
    if (!p.delimiter_none && p.start.find(p.delimiter) != std::string::npos)
        throw Error(ErrorKind::BadDirective, p.format, "", p.source + ": the 'start' text holds the delimiter");
    if (p.checksum_nmea && !p.delimiter_none && p.delimiter == '*')
        throw Error(ErrorKind::BadDirective, p.format, "", p.source + ": 'delimiter \"*\"' with 'checksum nmea'");
    auto scope_lines = [&](const std::vector<FieldLine>& fs, const std::vector<WhenLine>& ws,
                           const std::vector<WhenLine>& cs, const std::vector<GroupLine>& gs) {
        for (const auto& f : fs) check_field_line(p, f, nullptr);
        for (const auto& w : ws) check_fixed_line(p, w, "when", nullptr);
        for (const auto& c : cs) check_fixed_line(p, c, "const", nullptr);
        for (const auto& g : gs) check_group(p, g);
    };
    scope_lines(p.fields, p.whens, p.consts, p.groups);
    for (const auto& k : p.kinds) scope_lines(k.fields, k.whens, k.consts, k.groups);
    check_scope(p, nullptr);
    for (const auto& k : p.kinds) check_scope(p, &k);
}

Entity decode_text(const Pack& p, const std::string& bytes) {
    const Record rec = read_record(p, bytes);
    const Kind* kind = select_decode_kind(p, [&](const WhenLine& w) {
        std::string text;
        if (!read_part(rec, w.text_loc.i, w.text_loc, false, text)) return false;
        return w.present || text == w.text;
    });

    Entity e;
    Decoder d(p, e);
    std::set<std::uint64_t> addressed;
    std::vector<LineRef> lines_tmp;
    const std::vector<LineRef>& lines = scope_lines(p, kind, lines_tmp);
    const GroupLine* group = scope_group(lines);
    for (const auto& line : lines) {
        if (line.group) {
            if (rec.size() > line.group->text_index) e.lists[line.group->list] = decode_items(p, *line.group, rec);
            continue;
        }
        if (const WhenLine* w = line.fixed()) {
            if (line.maps()) mark(addressed, w->text_loc, 0);
            continue;
        }
        mark(addressed, line.field->text_loc, 0);
        decode_field(d, *line.field, rec, 0);
    }
    for (std::size_t idx = 0; idx < rec.size(); ++idx) {
        if (group && idx >= group->text_index) break;
        if (rec[idx].empty() || addressed.count(idx)) continue;
        e.residue.push_back({p.format, std::to_string(idx), rec[idx]});
    }
    d.finish();
    if (kind) e.kind = {p.format, kind->name};
    return e;
}

std::string encode_text(const Pack& p, const Entity& e) {
    const Kind* kind = select_encode_kind(p, e);
    const EncodeSource src(p, kind, e);
    std::vector<LineRef> lines_tmp;
    const std::vector<LineRef>& lines = scope_lines(p, kind, lines_tmp);
    const GroupLine* group = scope_group(lines);
    Writer w(p);
    std::set<std::uint64_t> addressed;  // by a line of the scope other than a group
    for (const auto& line : lines) {
        if (line.group) continue;
        if (const WhenLine* fx = line.fixed()) {
            if (line.maps()) mark(addressed, fx->text_loc, 0);
            w.fixed(*fx, 0);
            continue;
        }
        mark(addressed, line.field->text_loc, 0);
        w.field(src, *line.field, 0);
    }
    if (group) w.group(src, *group);
    // Residue of this format, at fields no line of the scope addresses.
    std::set<std::uint64_t> residue_written;
    for (const auto& r : e.residue) {
        std::uint32_t idx;
        if (r.format != p.format || !parse_index(r.locator, idx)) continue;
        if (addressed.count(idx) || (group && idx >= group->text_index) || !residue_written.insert(idx).second) continue;
        if (p.delimiter_none && idx != 0) continue;
        Slot& s = w.slots[idx];
        s.whole_set = true;
        s.whole = r.value;
        if (idx + 1u > w.count) w.count = idx + 1u;
    }
    // Trailing empty fields that only `optional` lines address are removed.
    std::vector<std::string> fields(static_cast<std::size_t>(w.count));
    for (const auto& kv : w.slots)
        if (kv.first < w.count) fields[static_cast<std::size_t>(kv.first)] = kv.second.text();
    while (!fields.empty() && fields.back().empty()) {
        auto it = w.optional_only.find(fields.size() - 1);
        if (it == w.optional_only.end() || !it->second) break;
        fields.pop_back();
    }
    std::string body;
    for (std::size_t k = 0; k < fields.size(); ++k) {
        if (k && !p.delimiter_none) body += p.delimiter;
        body += fields[k];
    }
    std::string out = p.start + body;
    if (p.checksum_nmea) {
        unsigned x = 0;
        for (char c : body) x ^= static_cast<unsigned char>(c);
        static const char* hex = "0123456789ABCDEF";
        out += '*';
        out += hex[(x >> 4) & 0xF];
        out += hex[x & 0xF];
    }
    return out;
}

}  // namespace goat_transformers::detail
