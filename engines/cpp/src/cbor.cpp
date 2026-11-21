// The `cbor` wire (engine-spec.md, "Version 0.28: the `cbor` wire").
//
// A message is one CBOR data item (RFC 8949), given as hex text. A path is
// steps of integer keys, text keys and `[i]` array positions separated by
// `.`. The input is read whole before any line is: it must be one well-formed
// item, with valid UTF-8 in every text chunk, no two equal keys in a map, and
// at most 64 levels of arrays, maps and tags. Every declared length and count
// is compared with the bytes left before it is used, and nothing is reserved
// from a declared count, so no input takes memory or stack without bound.
//
// Output is the core deterministic encoding of RFC 8949 4.2.1: shortest
// heads, shortest exact floats, definite lengths, and map members sorted by
// the bytes of their encoded keys. Residue is every member or element no line
// maps or walks into, keyed by its path, holding the hex of the item as it
// stood in the input; on write it is re-encoded deterministically.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "codecs.hpp"
#include "transforms.hpp"
#include "util.hpp"

namespace goat_transformers::detail {

namespace {

constexpr unsigned kMaxDepth = 64;
constexpr std::uint32_t kMaxPosition = 65535;
constexpr std::uint64_t kInt64Max = static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());

// ---------------------------------------------------------------- heads and floats

void put_head(std::string& out, unsigned major, std::uint64_t arg) {
    const unsigned m = major << 5;
    auto put_be = [&](unsigned bytes) {
        for (unsigned k = bytes; k-- > 0;) out += static_cast<char>((arg >> (8 * k)) & 0xFF);
    };
    if (arg < 24) {
        out += static_cast<char>(m | static_cast<unsigned>(arg));
    } else if (arg <= 0xFF) {
        out += static_cast<char>(m | 24u);
        put_be(1);
    } else if (arg <= 0xFFFF) {
        out += static_cast<char>(m | 25u);
        put_be(2);
    } else if (arg <= 0xFFFFFFFFull) {
        out += static_cast<char>(m | 26u);
        put_be(4);
    } else {
        out += static_cast<char>(m | 27u);
        put_be(8);
    }
}

constexpr std::uint64_t kMant52 = (std::uint64_t{1} << 52) - 1;

// The bits of the double that a half or a single holds, exactly, NaN payloads included.
std::uint64_t half_to_double_bits(std::uint64_t h) {
    const std::uint64_t sign = ((h >> 15) & 1u) << 63;
    const unsigned e = static_cast<unsigned>((h >> 10) & 0x1F);
    const std::uint64_t m = h & 0x3FF;
    if (e == 31) return sign | (std::uint64_t{0x7FF} << 52) | (m << 42);
    if (e == 0) {
        if (m == 0) return sign;
        int top = 9;
        while (((m >> top) & 1u) == 0) --top;
        const std::uint64_t exp = static_cast<std::uint64_t>(top - 24 + 1023);
        return sign | (exp << 52) | ((m << (52 - top)) & kMant52);
    }
    return sign | (static_cast<std::uint64_t>(e - 15 + 1023) << 52) | (m << 42);
}

std::uint64_t single_to_double_bits(std::uint64_t s) {
    const std::uint64_t sign = ((s >> 31) & 1u) << 63;
    const unsigned e = static_cast<unsigned>((s >> 23) & 0xFF);
    const std::uint64_t m = s & 0x7FFFFF;
    if (e == 255) return sign | (std::uint64_t{0x7FF} << 52) | (m << 29);
    if (e == 0) {
        if (m == 0) return sign;
        int top = 22;
        while (((m >> top) & 1u) == 0) --top;
        const std::uint64_t exp = static_cast<std::uint64_t>(top - 149 + 1023);
        return sign | (exp << 52) | ((m << (52 - top)) & kMant52);
    }
    return sign | (static_cast<std::uint64_t>(e - 127 + 1023) << 52) | (m << 29);
}

// The half that holds the double exactly, subnormal halves included.
bool to_half(std::uint64_t b, std::uint64_t& h) {
    const std::uint64_t sign = (b >> 63) << 15;
    const unsigned exp = static_cast<unsigned>((b >> 52) & 0x7FF);
    const std::uint64_t mant = b & kMant52;
    const std::uint64_t low42 = (std::uint64_t{1} << 42) - 1;
    if (exp == 0x7FF) {
        if (mant & low42) return false;
        h = sign | 0x7C00u | (mant >> 42);
        return true;
    }
    if (exp == 0) {
        if (mant != 0) return false;  // a subnormal double is below every half
        h = sign;
        return true;
    }
    const int e = static_cast<int>(exp) - 1023;
    const std::uint64_t sig = (std::uint64_t{1} << 52) | mant;
    if (e >= -14 && e <= 15) {
        if (mant & low42) return false;
        h = sign | (static_cast<std::uint64_t>(e + 15) << 10) | (mant >> 42);
        return true;
    }
    if (e >= -24 && e < -14) {
        const unsigned sh = static_cast<unsigned>(28 - e);  // 43 to 52
        if (sig & ((std::uint64_t{1} << sh) - 1)) return false;
        h = sign | (sig >> sh);
        return true;
    }
    return false;
}

bool to_single(std::uint64_t b, std::uint64_t& s) {
    const std::uint64_t sign = (b >> 63) << 31;
    const unsigned exp = static_cast<unsigned>((b >> 52) & 0x7FF);
    const std::uint64_t mant = b & kMant52;
    const std::uint64_t low29 = (std::uint64_t{1} << 29) - 1;
    if (exp == 0x7FF) {
        if (mant & low29) return false;
        s = sign | 0x7F800000u | (mant >> 29);
        return true;
    }
    if (exp == 0) {
        if (mant != 0) return false;
        s = sign;
        return true;
    }
    const int e = static_cast<int>(exp) - 1023;
    const std::uint64_t sig = (std::uint64_t{1} << 52) | mant;
    if (e >= -126 && e <= 127) {
        if (mant & low29) return false;
        s = sign | (static_cast<std::uint64_t>(e + 127) << 23) | (mant >> 29);
        return true;
    }
    if (e >= -149 && e < -126) {
        const unsigned sh = static_cast<unsigned>(-e - 97);  // 30 to 52
        if (sig & ((std::uint64_t{1} << sh) - 1)) return false;
        s = sign | (sig >> sh);
        return true;
    }
    return false;
}

// A float at the shortest of half, single and double that holds it exactly (RFC 8949 4.2.2).
void put_float(std::string& out, std::uint64_t bits) {
    std::uint64_t v = 0;
    unsigned bytes = 8;
    if (to_half(bits, v)) {
        out += static_cast<char>(0xF9);
        bytes = 2;
    } else if (to_single(bits, v)) {
        out += static_cast<char>(0xFA);
        bytes = 4;
    } else {
        out += static_cast<char>(0xFB);
        v = bits;
    }
    for (unsigned k = bytes; k-- > 0;) out += static_cast<char>((v >> (8 * k)) & 0xFF);
}

std::uint64_t double_bits(double d) {
    std::uint64_t b = 0;
    std::memcpy(&b, &d, sizeof b);
    return b;
}

double bits_double(std::uint64_t b) {
    double d = 0;
    std::memcpy(&d, &b, sizeof d);
    return d;
}

// ---------------------------------------------------------------- items

// One data item as read. Strings hold their chunks joined; a map's `kids` are
// its keys and values in turn, and `keys` the core deterministic encoding of
// each key; a tag's one kid is the item it encloses.
struct CItem {
    unsigned major = 0;
    bool fl = false;          // major 7: a float, `arg` the bits of the double it is
    std::uint64_t arg = 0;    // 0, 1: the argument; 6: the tag number; 7: the simple value or float bits
    std::string str;          // 2, 3
    std::vector<CItem> kids;  // 4, 5, 6
    std::vector<std::string> keys;
    std::size_t begin = 0, end = 0;  // the bytes of the input the item stood in, its tags included
};

bool is_null(const CItem* it) { return it->major == 7 && !it->fl && (it->arg == 22 || it->arg == 23); }

// The item a chain of tags encloses.
const CItem* untag(const CItem* it) {
    while (it->major == 6) it = &it->kids[0];
    return it;
}

void canon(const CItem& it, std::string& out);

void canon_map(const CItem& it, std::string& out) {
    const std::size_t n = it.keys.size();
    std::vector<std::size_t> order(n);
    for (std::size_t k = 0; k < n; ++k) order[k] = k;
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) { return it.keys[a] < it.keys[b]; });
    put_head(out, 5, n);
    for (std::size_t k : order) {
        out += it.keys[k];
        canon(it.kids[2 * k + 1], out);
    }
}

// The core deterministic encoding (Writing, step 1).
void canon(const CItem& it, std::string& out) {
    switch (it.major) {
        case 0:
        case 1: put_head(out, it.major, it.arg); break;
        case 2:
        case 3:
            put_head(out, it.major, it.str.size());
            out += it.str;
            break;
        case 4:
            put_head(out, 4, it.kids.size());
            for (const auto& k : it.kids) canon(k, out);
            break;
        case 5: canon_map(it, out); break;
        case 6:
            put_head(out, 6, it.arg);
            canon(it.kids[0], out);
            break;
        default:
            if (it.fl) put_float(out, it.arg);
            else if (it.arg < 24) out += static_cast<char>(0xE0 | static_cast<unsigned>(it.arg));
            else {
                out += static_cast<char>(0xF8);
                out += static_cast<char>(it.arg);
            }
    }
}

// Reading a message, steps 1 to 5: one well-formed item (RFC 8949 Appendix C).
class Reader {
public:
    Reader(const Pack& p, const std::string& data) : p_(p), d_(data) {}

    void read_all(CItem& out) {
        read(out, 0);
        if (i_ != d_.size()) bad("bytes stand after the one data item");
    }

private:
    const Pack& p_;
    const std::string& d_;
    std::size_t i_ = 0;

    [[noreturn]] void bad(const std::string& why) const {
        throw Error(ErrorKind::MalformedWire, p_.format, "", why + " (at byte " + std::to_string(i_) + ")");
    }
    std::size_t left() const { return d_.size() - i_; }
    unsigned byte_at(std::size_t k) const { return static_cast<unsigned char>(d_[k]); }

    // A head: the major type, the additional information and the argument.
    void head(unsigned& major, unsigned& ai, std::uint64_t& arg) {
        if (i_ >= d_.size()) bad("the input ends where an item stands");
        const unsigned b = byte_at(i_++);
        major = b >> 5;
        ai = b & 31u;
        arg = ai;
        if (ai < 24 || ai == 31) return;
        if (ai > 27) bad("additional information " + std::to_string(ai) + " is reserved");
        const std::size_t n = std::size_t{1} << (ai - 24);
        if (left() < n) bad("a head runs past the input");
        arg = 0;
        for (std::size_t k = 0; k < n; ++k) arg = (arg << 8) | byte_at(i_++);
    }

    void chunk(CItem& it, std::uint64_t len) {
        if (len > left()) bad("a string declares " + std::to_string(len) + " bytes and " + std::to_string(left()) +
                              " are left");
        const std::string part = d_.substr(i_, static_cast<std::size_t>(len));
        if (it.major == 3 && !utf8_is_valid(part)) bad("a text string is not valid UTF-8");
        it.str += part;
        i_ += static_cast<std::size_t>(len);
    }

    bool at_break() const { return i_ < d_.size() && byte_at(i_) == 0xFF; }

    void read_key_value(CItem& it, unsigned level, std::set<std::string>& seen) {
        it.kids.emplace_back();
        read(it.kids.back(), level);
        std::string enc;
        canon(it.kids.back(), enc);
        if (!seen.insert(enc).second) bad("a map holds two equal keys");
        it.keys.push_back(std::move(enc));
        it.kids.emplace_back();
        read(it.kids.back(), level);
    }

    // `level`: the arrays, maps and tags that enclose the item.
    void read(CItem& it, unsigned level) {
        it.begin = i_;
        unsigned major = 0, ai = 0;
        std::uint64_t arg = 0;
        head(major, ai, arg);
        it.major = major;
        switch (major) {
            case 0:
            case 1:
                if (ai == 31) bad("an integer with indefinite length");
                it.arg = arg;
                break;
            case 2:
            case 3:
                if (ai != 31) {
                    chunk(it, arg);
                    break;
                }
                for (;;) {
                    if (i_ >= d_.size()) bad("an indefinite string has no break");
                    if (at_break()) {
                        ++i_;
                        break;
                    }
                    unsigned cm = 0, cai = 0;
                    std::uint64_t carg = 0;
                    head(cm, cai, carg);
                    if (cm != major || cai == 31) bad("a chunk of an indefinite string is not a definite string of its type");
                    chunk(it, carg);
                }
                break;
            case 4:
            case 5: {
                if (level + 1 > kMaxDepth) bad("the nesting is deeper than 64 levels");
                std::set<std::string> seen;
                if (ai == 31) {
                    for (;;) {
                        if (i_ >= d_.size()) bad("an indefinite array or map has no break");
                        if (at_break()) {
                            ++i_;
                            break;
                        }
                        if (major == 4) {
                            it.kids.emplace_back();
                            read(it.kids.back(), level + 1);
                        } else {
                            read_key_value(it, level + 1, seen);
                        }
                    }
                    break;
                }
                // Each element takes one byte at least, each member two: a count is
                // compared with the bytes left before any element is read.
                if (major == 4 ? arg > left() : arg > left() / 2)
                    bad("an array or map declares " + std::to_string(arg) + " items and " + std::to_string(left()) +
                        " bytes are left");
                for (std::uint64_t k = 0; k < arg; ++k) {
                    if (major == 4) {
                        it.kids.emplace_back();
                        read(it.kids.back(), level + 1);
                    } else {
                        read_key_value(it, level + 1, seen);
                    }
                }
                break;
            }
            case 6:
                if (ai == 31) bad("a tag with indefinite length");
                if (level + 1 > kMaxDepth) bad("the nesting is deeper than 64 levels");
                it.arg = arg;
                it.kids.emplace_back();
                read(it.kids.back(), level + 1);
                break;
            default:
                if (ai == 31) bad("a break where an item stands");
                if (ai == 24) {
                    if (arg < 32) bad("a simple value below 32 in two bytes");
                    it.arg = arg;
                } else if (ai == 25) {
                    it.fl = true;
                    it.arg = half_to_double_bits(arg);
                } else if (ai == 26) {
                    it.fl = true;
                    it.arg = single_to_double_bits(arg);
                } else if (ai == 27) {
                    it.fl = true;
                    it.arg = arg;
                } else {
                    it.arg = arg;
                }
        }
        it.end = i_;
    }
};

// ---------------------------------------------------------------- paths

struct Step {
    bool pos = false;
    std::uint32_t index = 0;
    std::string key;   // a key step: the core deterministic encoding of the key
    std::string text;  // the step as written
};
using Path = std::vector<Step>;

bool is_letter(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
bool is_digit(char c) { return c >= '0' && c <= '9'; }

// A text key the step grammar can write.
bool text_key_valid(std::string_view s) {
    if (s.empty() || !(is_letter(s[0]) || s[0] == '_')) return false;
    for (char c : s)
        if (!(is_letter(c) || is_digit(c) || c == '_' || c == '-')) return false;
    return true;
}

// Decimal digits with no leading zero, at most `max`.
bool decimal_no_zero(std::string_view s, std::uint64_t max, std::uint64_t& out) {
    if (s.empty() || (s.size() > 1 && s[0] == '0')) return false;
    std::uint64_t v = 0;
    for (char c : s) {
        if (!is_digit(c)) return false;
        const std::uint64_t d = static_cast<std::uint64_t>(c - '0');
        if (v > (max - d) / 10) return false;
        v = v * 10 + d;
    }
    out = v;
    return true;
}

bool parse_step(std::string_view s, Step& st) {
    st = Step();
    st.text = std::string(s);
    if (s.empty()) return false;
    if (s[0] == '[') {
        std::uint64_t v = 0;
        if (s.size() < 3 || s.back() != ']' || !decimal_no_zero(s.substr(1, s.size() - 2), kMaxPosition, v))
            return false;
        st.pos = true;
        st.index = static_cast<std::uint32_t>(v);
        return true;
    }
    if (s[0] == '-' || is_digit(s[0])) {
        const bool neg = s[0] == '-';
        std::uint64_t v = 0;
        const std::uint64_t max = neg ? kInt64Max + 1 : std::numeric_limits<std::uint64_t>::max();
        if (!decimal_no_zero(neg ? s.substr(1) : s, max, v)) return false;
        if (neg && v == 0) return false;  // `-0`
        put_head(st.key, neg ? 1 : 0, neg ? v - 1 : v);
        return true;
    }
    if (!text_key_valid(s)) return false;
    put_head(st.key, 3, s.size());
    st.key += std::string(s);
    return true;
}

bool parse_path(const std::string& loc, Path& out) {
    out.clear();
    std::size_t st = 0;
    for (;;) {
        const std::size_t dot = loc.find('.', st);
        Step step;
        if (!parse_step(std::string_view(loc).substr(st, dot == std::string::npos ? std::string::npos : dot - st), step))
            return false;
        out.push_back(std::move(step));
        if (dot == std::string::npos) return true;
        st = dot + 1;
    }
}

// The path of a line: empty for `.`, the item itself or the top item.
Path path_of(const std::string& loc) {
    Path path;
    if (loc != "." && !parse_path(loc, path)) path.clear();  // validated at load
    return path;
}

// The text of an addressable key, as a step writes it; false when the key is
// not addressable (another type, a tag, an integer below -2^63, a text the
// step grammar cannot write).
bool key_step_text(const CItem& key, std::string& out) {
    switch (key.major) {
        case 0: out = std::to_string(key.arg); return true;
        case 1:
            if (key.arg > kInt64Max) return false;  // ruling 17
            out = "-" + std::to_string(key.arg + 1);
            return true;
        case 3:
            if (!text_key_valid(key.str)) return false;
            out = key.str;
            return true;
        default: return false;
    }
}

// Hex text of a whole item, read as one item; false when it is not one.
bool read_hex_item(const Pack& p, const std::string& hex, CItem& out) {
    try {
        const std::string data = hex_to_bytes(p, hex);
        Reader r(p, data);
        r.read_all(out);
        return true;
    } catch (const Error&) {
        return false;
    }
}

// A residue locator: the steps of a path, and `#<hex>` for a key that is not
// addressable, re-encoded with the core deterministic encoding (ruling 16).
bool parse_residue_path(const Pack& p, const std::string& loc, Path& out) {
    out.clear();
    std::size_t st = 0;
    for (;;) {
        const std::size_t dot = loc.find('.', st);
        const std::string s = loc.substr(st, dot == std::string::npos ? std::string::npos : dot - st);
        Step step;
        if (!s.empty() && s[0] == '#') {
            CItem key;
            if (!read_hex_item(p, s.substr(1), key)) return false;
            step.text = s;
            canon(key, step.key);
        } else if (!parse_step(s, step)) {
            return false;
        }
        out.push_back(std::move(step));
        if (dot == std::string::npos) return true;
        st = dot + 1;
    }
}

// The member or element a step names in a container of its type; null when none.
const CItem* child(const CItem& c, const Step& s) {
    if (s.pos) return s.index < c.kids.size() ? &c.kids[s.index] : nullptr;
    for (std::size_t k = 0; k < c.keys.size(); ++k)
        if (c.keys[k] == s.key) return &c.kids[2 * k + 1];
    return nullptr;
}

// The item at `path` under `base`, its tags passed over. Null when it is
// absent: a member or element is missing, or `null` or `undefined` stands on
// the way (ruling 12) or at the end. An item on the way of the wrong type for
// the next step is malformed-wire with `strict` (Reading, step 8), and with
// `wrong` set otherwise (step 7).
const CItem* walk(const Pack& p, const CItem* base, const Path& path, const std::string& locator, bool strict,
                  bool* wrong) {
    const CItem* cur = untag(base);
    for (const Step& s : path) {
        if (is_null(cur)) return nullptr;
        const unsigned need = s.pos ? 4 : 5;
        if (cur->major != need) {
            if (strict)
                throw Error(ErrorKind::MalformedWire, p.format, locator,
                            std::string("the path needs ") + (s.pos ? "an array" : "a map") + " before '" + s.text +
                                "' and the item there is not one");
            if (wrong) *wrong = true;
            return nullptr;
        }
        const CItem* next = child(*cur, s);
        if (!next) return nullptr;
        cur = untag(next);
    }
    return is_null(cur) ? nullptr : cur;
}

// ---------------------------------------------------------------- what the lines walk into

// The places the lines of one scope name: a node is mapped by a line at its
// path, and walked into by a line under it.
struct Trie {
    std::map<std::string, Trie> keys;     // by the encoded key
    std::map<std::uint32_t, Trie> elems;  // by position
    bool mapped = false;
};

void trie_add(Trie& root, const Path& path, bool map_last) {
    Trie* n = &root;
    for (std::size_t k = 0; k < path.size(); ++k) {
        if (k + 1 == path.size() && !map_last) return;  // `when ... present` does not walk into its item (ruling 15)
        n = path[k].pos ? &n->elems[path[k].index] : &n->keys[path[k].key];
    }
    if (map_last) n->mapped = true;
}

Trie scope_trie(const std::vector<LineRef>& lines) {
    Trie t;
    for (const auto& line : lines) {
        const bool present = line.when && line.when->present;
        trie_add(t, path_of(line.locator()), !present);
    }
    return t;
}

// Does a group body address its element as an array (its paths begin with positions)?
bool body_is_array(const GroupLine& g) {
    for (const auto& line : group_lines(g)) {
        if (line.locator() == ".") continue;
        const Path path = path_of(line.locator());
        if (!path.empty()) return path[0].pos;
    }
    return false;
}

// ---------------------------------------------------------------- decode

// One field's item (tags passed over, not `null` or `undefined`) through its transform.
void decode_field(Decoder& d, const FieldLine& f, const CItem& v) {
    auto refuse = [&](const std::string& why) { d.fail(f, why); };
    switch (f.transform) {
        case Transform::Uint:
            if (v.major != 0) return refuse("the item is not of major type 0, which transform 'uint' reads");
            if (v.arg > kInt64Max) return refuse("the integer " + std::to_string(v.arg) + " lies above 2^63-1");
            return d.put(f, Value::of_int(static_cast<std::int64_t>(v.arg)));
        case Transform::Int:
            if (v.major == 0) {
                if (v.arg > kInt64Max) return refuse("the integer " + std::to_string(v.arg) + " lies above 2^63-1");
                return d.put(f, Value::of_int(static_cast<std::int64_t>(v.arg)));
            }
            if (v.major == 1) {
                if (v.arg > kInt64Max) return refuse("the integer lies below -2^63");
                return d.put(f, Value::of_int(-1 - static_cast<std::int64_t>(v.arg)));
            }
            return refuse("the item is not an integer, which transform 'int' reads");
        case Transform::Float: {
            double x = 0;
            if (v.major == 7 && v.fl) {
                x = bits_double(v.arg);
                if (!std::isfinite(x)) return refuse("the float is a NaN or an infinity");
            } else if (v.major == 0) {
                x = static_cast<double>(v.arg);
            } else if (v.major == 1) {
                x = v.arg == std::numeric_limits<std::uint64_t>::max() ? -18446744073709551616.0
                                                                       : -static_cast<double>(v.arg + 1);
            } else {
                return refuse("the item is not a float or an integer, which transform 'float' reads");
            }
            return d.put(f, Value::of_float(x));
        }
        case Transform::CborText:
            if (v.major != 3) return refuse("the item is not a text string, which transform 'text' reads");
            return d.put(f, Value::of_string(v.str));
        case Transform::CborBytes:
            if (v.major != 2) return refuse("the item is not a byte string, which transform 'bytes' reads");
            return d.put(f, Value::of_string(bytes_to_hex(v.str)));
        case Transform::Bool:
            if (v.major != 7 || v.fl || (v.arg != 20 && v.arg != 21))
                return refuse("the item is not false or true, which transform 'bool' reads");
            return d.put(f, Value::of_int(v.arg == 21 ? 1 : 0));
        case Transform::EpochS: {
            // Ruling 7: the range applies to the product.
            constexpr std::int64_t kMaxS = std::numeric_limits<std::int64_t>::max() / 1000;
            constexpr std::int64_t kMinS = std::numeric_limits<std::int64_t>::min() / 1000;
            std::int64_t s = 0;
            if (v.major == 0) {
                if (v.arg > static_cast<std::uint64_t>(kMaxS)) return refuse("the seconds times 1000 lie above 2^63-1");
                s = static_cast<std::int64_t>(v.arg);
            } else if (v.major == 1) {
                if (v.arg > kInt64Max) return refuse("the seconds times 1000 lie below -2^63");
                s = -1 - static_cast<std::int64_t>(v.arg);
                if (s < kMinS) return refuse("the seconds times 1000 lie below -2^63");
            } else {
                return refuse("the item is not an integer, which transform 'epoch_s' reads");
            }
            return d.put(f, Value::of_int(s * 1000));
        }
        default: return refuse("transform '" + std::string(transform_name(f.transform)) + "' is not a cbor transform");
    }
}

std::vector<Item> decode_items(const Pack& p, const GroupLine& g, const CItem& arr);

// The lines of a scope read from its container `base` (the top item, or the
// element of a group item), into `out`. Every line's path is walked, whether
// or not its key is still wanted, so a path through an item of the wrong
// type is malformed-wire on every line (Reading, step 8).
void read_lines(const Pack& p, Decoder& d, Item& out, const std::vector<LineRef>& lines, const CItem& base) {
    for (const auto& line : lines) {
        if (line.when) continue;  // the kind is selected: its `when` lines hold
        const std::string& loc = line.locator();
        if (line.group) {
            const CItem* arr = loc == "." ? untag(&base) : walk(p, &base, path_of(loc), loc, true, nullptr);
            if (!arr) continue;  // absent, `null` or `undefined`: an absent list
            if (arr->major != 4)
                throw Error(ErrorKind::MalformedWire, p.format, loc,
                            "the item at the path of the group '" + line.group->list + "' is not an array");
            out.lists[line.group->list] = decode_items(p, *line.group, *arr);
            continue;
        }
        const CItem* v = walk(p, &base, path_of(loc), loc, true, nullptr);
        if (!line.field || !v || !d.wants(*line.field)) continue;
        decode_field(d, *line.field, *v);
    }
}

std::vector<Item> decode_items(const Pack& p, const GroupLine& g, const CItem& arr) {
    take_items(p, g.list, arr.kids.size());  // 0.11 ruling 7a
    const std::vector<LineRef> lines = group_lines(g);
    const unsigned need = body_is_array(g) ? 4 : 5;
    std::vector<Item> items;
    for (const CItem& raw : arr.kids) {
        items.emplace_back();
        Item& item = items.back();
        Decoder d(p, item);
        const CItem* el = untag(&raw);
        if (g.scalar) {
            // A body of only `.`: the element through the transform, which
            // refuses a map or an array (ruling 14); `null` is an item with no value.
            if (!is_null(el))
                for (const auto& line : lines)
                    if (line.field && d.wants(*line.field)) decode_field(d, *line.field, *el);
        } else if (el->major == need) {
            read_lines(p, d, item, lines, *el);
        }  // else an element of the wrong type: an item with no keys (ruling 12 of 0.7)
        d.finish();
    }
    return items;
}

bool when_holds(const Pack& p, const WhenLine& w, const CItem& top) {
    bool wrong = false;
    const CItem* v = walk(p, &top, path_of(w.locator), w.locator, false, &wrong);
    if (!v) return false;
    if (w.present) return true;
    switch (w.cbor_type) {
        case WhenLine::CborType::Int: return v->major == (w.cbor_negative ? 1u : 0u) && v->arg == w.number;
        case WhenLine::CborType::Bool: return v->major == 7 && !v->fl && v->arg == (w.number ? 21u : 20u);
        case WhenLine::CborType::Text: return v->major == 3 && v->str == w.text;
    }
    return false;
}

struct ResidueWalk {
    const Pack& p;
    const std::string& data;
    Entity& e;

    void add(const std::string& path, const CItem& v) {
        e.residue.push_back({p.format, path, bytes_to_hex(data.substr(v.begin, v.end - v.begin)), false});
    }

    void visit(const CItem& v, const Trie* node, const std::string& path) {
        if (!node) return add(path, v);
        if (node->mapped) return;
        const CItem* u = untag(&v);
        if (is_null(u)) return;  // walked into: not residue (ruling 12)
        const bool as_map = !node->keys.empty(), as_array = !node->elems.empty();
        if ((u->major == 5 && as_map && !as_array) || (u->major == 4 && as_array && !as_map)) return collect(*u, *node, path);
        add(path, v);
    }

    void collect(const CItem& c, const Trie& node, const std::string& base) {
        auto sub = [&](const std::string& step) { return base.empty() ? step : base + "." + step; };
        if (c.major == 5) {
            for (std::size_t k = 0; k < c.keys.size(); ++k) {
                const CItem& key = c.kids[2 * k];
                std::string step;
                const Trie* next = nullptr;
                if (key_step_text(key, step)) {
                    auto it = node.keys.find(c.keys[k]);
                    if (it != node.keys.end()) next = &it->second;
                } else {
                    step = "#" + bytes_to_hex(data.substr(key.begin, key.end - key.begin));  // ruling 16
                }
                visit(c.kids[2 * k + 1], next, sub(step));
            }
        } else if (c.major == 4) {
            for (std::size_t k = 0; k < c.kids.size() && k <= kMaxPosition; ++k) {  // ruling 18
                auto it = node.elems.find(static_cast<std::uint32_t>(k));
                visit(c.kids[k], it == node.elems.end() ? nullptr : &it->second, sub("[" + std::to_string(k) + "]"));
            }
        }
    }
};

// ---------------------------------------------------------------- encode

// The output tree: a value already encoded, or a map or an array of nodes.
struct Out {
    enum class K { None, Value, Map, Array };
    K k = K::None;
    std::string value;
    int prio = 0;  // a Value: 0 residue, 1 a field or a group, 2 a `when` or `const`
    std::map<std::string, Out> members;  // by the encoded key: the bytewise order of 4.2.1
    std::map<std::uint32_t, Out> elems;
};

bool has_content(const Out& n);

// The node at `path`, its containers made on the way; null when the path runs
// through a value or a container of the other type (for residue, ruling 33:
// it is dropped).
Out* slot(Out& root, const Path& path) {
    Out* n = &root;
    for (const Step& s : path) {
        const Out::K want = s.pos ? Out::K::Array : Out::K::Map;
        if (n->k == Out::K::None) n->k = want;
        else if (n->k != want) return nullptr;
        n = s.pos ? &n->elems[s.index] : &n->members[s.key];
    }
    return n;
}

void put_value(Out* n, std::string enc, int prio) {
    if (!n || n->k == Out::K::Map || n->k == Out::K::Array) return;
    if (n->k == Out::K::Value && n->prio >= prio) return;
    n->k = Out::K::Value;
    n->value = std::move(enc);
    n->prio = prio;
}

bool has_content(const Out& n) {
    switch (n.k) {
        case Out::K::Value: return true;
        case Out::K::Map:
            for (const auto& m : n.members)
                if (has_content(m.second)) return true;
            return false;
        case Out::K::Array:
            for (const auto& m : n.elems)
                if (has_content(m.second)) return true;
            return false;
        case Out::K::None: return false;
    }
    return false;
}

// Writing, steps 2 and 3 and ruling 23: a container with nothing in it is not
// written; a position below the highest present one with nothing to write is
// `a0` or `80` when the lines walk into it as a map or an array, else `f6`.
void write_out(const Out& n, const Trie* t, std::string& out, bool top, bool top_array) {
    Out::K k = n.k;
    if (k == Out::K::Value) {
        out += n.value;
        return;
    }
    if (k == Out::K::None) k = top && top_array ? Out::K::Array : Out::K::Map;
    if (k == Out::K::Map) {
        std::size_t count = 0;
        for (const auto& m : n.members) count += has_content(m.second) ? 1 : 0;
        put_head(out, 5, count);
        for (const auto& m : n.members) {
            if (!has_content(m.second)) continue;
            const Trie* sub = nullptr;
            if (t) {
                auto it = t->keys.find(m.first);
                if (it != t->keys.end()) sub = &it->second;
            }
            out += m.first;
            write_out(m.second, sub, out, false, false);
        }
        return;
    }
    std::uint64_t length = 0;
    for (const auto& m : n.elems)
        if (has_content(m.second)) length = std::uint64_t{m.first} + 1;
    put_head(out, 4, length);
    for (std::uint64_t i = 0; i < length; ++i) {
        const std::uint32_t at = static_cast<std::uint32_t>(i);
        const Trie* sub = nullptr;
        if (t) {
            auto it = t->elems.find(at);
            if (it != t->elems.end()) sub = &it->second;
        }
        auto el = n.elems.find(at);
        if (el != n.elems.end() && has_content(el->second)) {
            write_out(el->second, sub, out, false, false);
        } else if (sub && !sub->keys.empty()) {
            out += static_cast<char>(0xA0);
        } else if (sub && !sub->elems.empty()) {
            out += static_cast<char>(0x80);
        } else {
            out += static_cast<char>(0xF6);
        }
    }
}

std::string text_item(const std::string& s) {
    std::string out;
    put_head(out, 3, s.size());
    out += s;
    return out;
}

std::string int_item(bool negative, std::uint64_t arg) {
    std::string out;
    put_head(out, negative ? 1 : 0, arg);
    return out;
}

std::string int_item(std::int64_t v) {
    return v >= 0 ? int_item(false, static_cast<std::uint64_t>(v)) : int_item(true, static_cast<std::uint64_t>(-(v + 1)));
}

// A `when` value or a `const`, written with its type (Kinds).
std::string fixed_item(const WhenLine& w) {
    switch (w.cbor_type) {
        case WhenLine::CborType::Int: return int_item(w.cbor_negative, w.number);
        case WhenLine::CborType::Bool: return std::string(1, static_cast<char>(w.number ? 0xF5 : 0xF4));
        case WhenLine::CborType::Text: return text_item(w.text);
    }
    return std::string();
}

// One field's value (through the default, the type mapping and the table) as an item.
std::string field_item(const Pack& p, const FieldLine& f, const Value& v) {
    try {
        auto text_of = [&]() -> const std::string& {
            if (v.kind != Value::Kind::String) throw std::invalid_argument("the value is not text");
            return v.s;
        };
        switch (f.transform) {
            case Transform::Uint: {
                const std::int64_t n = model_int(v);
                if (n < 0) throw std::invalid_argument("uint writes no negative value, not " + std::to_string(n));
                return int_item(n);
            }
            case Transform::Int: return int_item(model_int(v));
            case Transform::Float: {
                const double x = model_double(v);
                if (!std::isfinite(x)) throw std::invalid_argument("float writes no NaN or infinity");  // ruling 20
                std::string out;
                put_float(out, double_bits(x));
                return out;
            }
            case Transform::CborText: {
                const std::string& s = text_of();
                if (!utf8_is_valid(s)) throw std::invalid_argument("the text is not valid UTF-8");
                return text_item(s);
            }
            case Transform::CborBytes: {
                const std::string& s = text_of();
                if (s.size() % 2 != 0) throw std::invalid_argument("bytes takes an even number of hex digits");
                std::string bytes;
                for (std::size_t k = 0; k < s.size(); k += 2) {
                    auto nib = [](char c) { return c <= '9' ? c - '0' : c - 'a' + 10; };
                    for (std::size_t j = k; j < k + 2; ++j)
                        if (!is_digit(s[j]) && !(s[j] >= 'a' && s[j] <= 'f'))
                            throw std::invalid_argument("bytes takes lowercase hex digits, not '" + s + "'");
                    bytes += static_cast<char>((nib(s[k]) << 4) | nib(s[k + 1]));
                }
                std::string out;
                put_head(out, 2, bytes.size());
                return out + bytes;
            }
            case Transform::Bool: {
                const std::int64_t n = model_int(v);
                if (n != 0 && n != 1) throw std::invalid_argument("bool writes 1 or 0, not " + std::to_string(n));
                return std::string(1, static_cast<char>(n ? 0xF5 : 0xF4));
            }
            case Transform::EpochS: {
                const std::int64_t ms = model_int(v);
                std::int64_t q = ms / 1000;
                const std::int64_t r = ms % 1000;
                if (r >= 500) ++q;
                else if (r <= -500) --q;  // half away from zero
                return int_item(q);
            }
            default: throw std::invalid_argument("not a cbor transform");
        }
    } catch (const std::invalid_argument& ex) {
        throw Error(ErrorKind::TransformEncode, p.format, f.locator, f.key + ": " + ex.what());
    }
}

std::string encode_items(const Pack& p, const GroupLine& g, const std::vector<Item>& items);

// The lines of a scope written into `root`, in line order: the earliest field
// with a value at a path, a `when` or `const` value over any field (Writing,
// step 1; ruling 16 of 0.5). `when ... present` writes nothing.
template <class Source>
void write_lines(const Pack& p, const Source& src, const std::vector<LineRef>& lines, Out& root) {
    // Ruling 29: a field at a path a `when` value or a `const` names is not encoded.
    std::set<std::string> fixed;
    for (const auto& line : lines)
        if (const WhenLine* w = line.fixed())
            if (!w->present) fixed.insert(w->locator == "." ? std::string() : w->locator);
    for (const auto& line : lines) {
        const std::string& loc = line.locator();
        const Path path = path_of(loc);
        if (const WhenLine* w = line.fixed()) {
            if (w->present) continue;
            put_value(slot(root, path), fixed_item(*w), 2);
            continue;
        }
        if (line.group) {
            const std::vector<Item>* items = src.list(*line.group);
            if (!items) continue;  // an absent list writes nothing
            Out* n = slot(root, path);
            if (!n || n->k != Out::K::None) continue;
            put_value(n, encode_items(p, *line.group, *items), 1);
            continue;
        }
        const FieldLine& f = *line.field;
        if (src.suppressed(f)) continue;  // 0.18 ruling 1
        if (!fixed.empty() && fixed.count(loc)) continue;
        Out* n = slot(root, path);
        if (!n || n->k != Out::K::None) continue;  // an earlier line gives the value
        Value v;
        if (!src.value(f, v)) continue;
        put_value(n, field_item(p, f, v), 1);
    }
}

std::string encode_items(const Pack& p, const GroupLine& g, const std::vector<Item>& items) {
    const std::vector<LineRef> lines = group_lines(g);
    const Trie trie = scope_trie(lines);
    const bool as_array = body_is_array(g);
    std::string out;
    put_head(out, 4, items.size());
    for (const Item& item : items) {
        const EncodeSource src(p, g, item);
        if (g.scalar) {
            // A scalar item with no value is `null` (Writing, step 4).
            std::string enc = "\xF6";
            for (const auto& line : lines) {
                if (!line.field || src.suppressed(*line.field)) continue;
                Value v;
                if (!src.value(*line.field, v)) continue;
                enc = field_item(p, *line.field, v);
                break;
            }
            out += enc;
            continue;
        }
        Out root;
        write_lines(p, src, lines, root);
        write_out(root, &trie, out, true, as_array);
    }
    return out;
}

// ---------------------------------------------------------------- load checks

[[noreturn]] void bad(const Pack& p, const std::string& locator, std::size_t line, const std::string& why) {
    throw Error(ErrorKind::BadDirective, p.format, locator, p.source + ":" + std::to_string(line) + ": " + why);
}

// The type of a `when` or `const` value (Kinds; rulings 8 and 19).
void resolve_fixed(const Pack& p, WhenLine& w, bool is_const) {
    w.present = false;
    w.cbor_negative = false;
    w.number = 0;
    if (w.value == "present") {
        if (is_const) bad(p, w.locator, w.line, "'const <path> present'");
        w.present = true;
        return;
    }
    // Integer text of 2a: a sign and leading zeros allowed, from -2^63 to 2^64-1.
    const std::string& v = w.value;
    const bool neg = !v.empty() && v[0] == '-';
    const std::string_view digits = std::string_view(v).substr(neg ? 1 : 0);
    bool integer = !digits.empty();
    std::uint64_t mag = 0;
    for (char c : digits) {
        if (!is_digit(c)) {
            integer = false;
            break;
        }
        const std::uint64_t d = static_cast<std::uint64_t>(c - '0');
        if (mag > (std::numeric_limits<std::uint64_t>::max() - d) / 10) {
            integer = false;
            break;
        }
        mag = mag * 10 + d;
    }
    if (integer && neg && mag > kInt64Max + 1) integer = false;
    if (integer) {
        w.cbor_type = WhenLine::CborType::Int;
        if (neg && mag != 0) {
            w.cbor_negative = true;
            w.number = mag - 1;
        } else {
            w.number = mag;
        }
        return;
    }
    if (v == "true" || v == "false") {
        w.cbor_type = WhenLine::CborType::Bool;
        w.number = v == "true" ? 1 : 0;
        return;
    }
    w.cbor_type = WhenLine::CborType::Text;
    w.text = !v.empty() && v[0] == '=' ? v.substr(1) : v;
}

void check_field_line(const Pack& p, const FieldLine& f) {
    switch (f.transform) {
        case Transform::Uint:
        case Transform::Int:
        case Transform::Float:
        case Transform::CborText:
        case Transform::CborBytes:
        case Transform::Bool:
        case Transform::EpochS: break;
        default:
            bad(p, f.locator, f.line, std::string("transform '") + transform_name(f.transform) + "' is not valid on wire cbor");
    }
    if (f.swap || f.trim || f.optional || f.has_absent)
        bad(p, f.locator, f.line, "options 'absent', 'swap', 'trim' and 'optional' are not valid on wire cbor");
}

// One line of a scope for the checks of Paths and ruling 13.
struct PLine {
    enum class K { Field, When, Present, Const, Group };
    K k = K::Field;
    std::string loc;
    std::size_t line = 0;
    bool dot = false;
    Path path;
    std::vector<std::string> tokens;  // one per step, comparable between lines
};

std::string step_token(const Step& s) { return s.pos ? "p" + std::to_string(s.index) : "k" + bytes_to_hex(s.key); }

PLine make_line(PLine::K k, const std::string& loc, std::size_t line) {
    PLine l;
    l.k = k;
    l.loc = loc;
    l.line = line;
    l.dot = loc == ".";
    l.path = path_of(loc);
    for (const auto& s : l.path) l.tokens.push_back(step_token(s));
    return l;
}

template <class Scope>
void scope_lines(std::vector<PLine>& out, const Scope& s, const std::vector<WhenLine>* whens) {
    for (const auto& f : s.fields) out.push_back(make_line(PLine::K::Field, f.locator, f.line));
    if (whens)
        for (const auto& w : *whens)
            out.push_back(make_line(w.present ? PLine::K::Present : PLine::K::When, w.locator, w.line));
    for (const auto& c : s.consts) out.push_back(make_line(PLine::K::Const, c.locator, c.line));
    for (const auto& g : s.groups) out.push_back(make_line(PLine::K::Group, g.locator, g.line));
}

bool starts_with(const std::vector<std::string>& a, const std::vector<std::string>& prefix) {
    if (prefix.size() > a.size()) return false;
    for (std::size_t k = 0; k < prefix.size(); ++k)
        if (a[k] != prefix[k]) return false;
    return true;
}

// The checks of one scope (the common lines with one kind's, or one group
// body): a step's item used as a map and as an array, a line at or under a
// group's path, and a path that is a proper prefix of another (ruling 13).
void check_scope(const Pack& p, const std::vector<PLine>& lines, bool body) {
    std::map<std::string, bool> used;  // prefix -> used as an array
    for (const auto& l : lines) {
        std::string prefix;
        for (std::size_t k = 0; k < l.path.size(); ++k) {
            auto it = used.emplace(prefix, l.path[k].pos).first;
            if (it->second != l.path[k].pos)
                bad(p, l.loc, l.line, "an item on the path '" + l.loc + "' is used both as a map and as an array");
            prefix += l.tokens[k] + "/";
        }
    }
    for (std::size_t a = 0; a < lines.size(); ++a)
        for (std::size_t b = 0; b < lines.size(); ++b) {
            if (a == b) continue;
            const PLine& x = lines[a];
            const PLine& y = lines[b];
            if (x.k == PLine::K::Group && starts_with(y.tokens, x.tokens))
                bad(p, y.loc, y.line, "the line at '" + y.loc + "' stands at or under the path '" + x.loc +
                                          "' of a group of the same scope");
            if (x.k != PLine::K::Present && x.tokens.size() < y.tokens.size() && starts_with(y.tokens, x.tokens))
                bad(p, y.loc, y.line, "the path '" + x.loc + "' is both a value and a container of '" + y.loc + "'");
        }
    if (body) {
        bool dot = false, other = false;
        for (const auto& l : lines) (l.dot && l.k == PLine::K::Field ? dot : other) = true;
        if (dot && other) bad(p, lines.front().loc, lines.front().line, "a group body mixes '.' with other paths");
    }
}

void check_bodies(const Pack& p, const std::vector<GroupLine>& groups) {
    for (const auto& g : groups) {
        std::vector<PLine> lines;
        scope_lines(lines, g, nullptr);
        if (!lines.empty()) check_scope(p, lines, true);
        check_bodies(p, g.groups);
    }
}

}  // namespace

bool cbor_path_valid(const std::string& loc) {
    Path path;
    return parse_path(loc, path);
}

bool parse_cbor_tag(const std::string& text, std::uint64_t& out) {
    return decimal_no_zero(text, std::numeric_limits<std::uint64_t>::max(), out);
}

namespace {

template <class Fn>
void each_field_in(const std::vector<FieldLine>& fs, const std::vector<WhenLine>& cs, const std::vector<GroupLine>& gs,
                   Fn&& fn) {
    for (const auto& f : fs) fn(&f, nullptr);
    for (const auto& c : cs) fn(nullptr, &c);
    for (const auto& g : gs) each_field_in(g.fields, g.consts, g.groups, fn);
}

void resolve_consts(const Pack& p, std::vector<WhenLine>& cs, std::vector<GroupLine>& gs) {
    for (auto& c : cs) resolve_fixed(p, c, true);
    for (auto& g : gs) resolve_consts(p, g.consts, g.groups);
}

}  // namespace

void check_cbor_pack(Pack& p) {
    auto fields = [&](const FieldLine* f, const WhenLine*) {
        if (f) check_field_line(p, *f);
    };
    each_field_in(p.fields, p.consts, p.groups, fields);
    for (const auto& k : p.kinds) each_field_in(k.fields, k.consts, k.groups, fields);
    for (auto& w : p.whens) resolve_fixed(p, w, false);
    resolve_consts(p, p.consts, p.groups);
    for (auto& k : p.kinds) {
        for (auto& w : k.whens) resolve_fixed(p, w, false);
        resolve_consts(p, k.consts, k.groups);
    }

    // Types: the first step of every path outside a group body decides the top item.
    std::vector<PLine> all;
    scope_lines(all, p, &p.whens);
    for (const auto& k : p.kinds) scope_lines(all, k, &k.whens);
    const PLine* first = nullptr;
    for (const auto& l : all) {
        if (l.path.empty() && !(l.dot && l.k == PLine::K::Group)) continue;
        const bool array = l.path.empty() || l.path[0].pos;
        if (!first) {
            first = &l;
            p.cbor_top_array = array;
        } else if (array != p.cbor_top_array) {
            bad(p, l.loc, l.line, "the path '" + l.loc + "' decides the top item as " +
                                      (array ? "an array" : "a map") + ", and '" + first->loc + "' as " +
                                      (array ? "a map" : "an array"));
        }
    }

    // One scope: the common lines with one kind's, and each group body.
    std::vector<PLine> common;
    scope_lines(common, p, &p.whens);
    if (p.kinds.empty()) {
        check_scope(p, common, false);
    } else {
        for (const auto& k : p.kinds) {
            std::vector<PLine> lines = common;
            scope_lines(lines, k, &k.whens);
            check_scope(p, lines, false);
        }
    }
    check_bodies(p, p.groups);
    for (const auto& k : p.kinds) check_bodies(p, k.groups);
}

Entity decode_cbor(const Pack& p, const std::string& text) {
    const std::string data = hex_to_bytes(p, text);
    CItem root;
    Reader(p, data).read_all(root);
    const CItem* top = &root;
    if (p.cbor_tag) {
        if (top->major != 6 || top->arg != p.cbor_tag_value)
            throw Error(ErrorKind::MalformedWire, p.format, "",
                        "the message does not begin with tag " + std::to_string(p.cbor_tag_value));
        top = &top->kids[0];
    }
    top = untag(top);
    if (top->major != (p.cbor_top_array ? 4u : 5u))
        throw Error(ErrorKind::MalformedWire, p.format, "",
                    std::string("the top item is not ") + (p.cbor_top_array ? "an array" : "a map"));

    const Kind* kind = select_decode_kind(p, [&](const WhenLine& w) { return when_holds(p, w, *top); });
    const std::vector<LineRef> lines = active_lines(p, kind);
    Entity e;
    Decoder d(p, e);
    read_lines(p, d, e, lines, *top);
    const Trie trie = scope_trie(lines);
    ResidueWalk rw{p, data, e};
    if (!trie.mapped) rw.collect(*top, trie, "");
    d.finish();
    if (kind) e.kind = {p.format, kind->name};
    return e;
}

std::string encode_cbor(const Pack& p, const Entity& e) {
    const Kind* kind = select_encode_kind(p, e);
    const EncodeSource src(p, kind, e);
    const std::vector<LineRef> lines = active_lines(p, kind);
    Out root;
    write_lines(p, src, lines, root);
    // Residue goes back into its own map or array, re-encoded; a line wins over
    // it (ruling 21).
    for (const auto& r : e.residue) {
        if (r.format != p.format) continue;
        Path path;
        CItem v;
        if (!parse_residue_path(p, r.locator, path) || path.empty() || !read_hex_item(p, r.value, v)) continue;
        Out* n = slot(root, path);
        // The line wins (ruling 21); a container the lines walked into and
        // left empty takes the residue back whole (ruling 31).
        if (!n || n->k == Out::K::Value || has_content(*n)) continue;
        *n = Out();
        std::string enc;
        canon(v, enc);
        put_value(n, std::move(enc), 0);
    }
    const Trie trie = scope_trie(lines);
    std::string out;
    if (p.cbor_tag) put_head(out, 6, p.cbor_tag_value);
    write_out(root, &trie, out, true, p.cbor_top_array);
    return bytes_to_hex(out);
}

}  // namespace goat_transformers::detail
