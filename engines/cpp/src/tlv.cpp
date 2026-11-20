// The `tlv` wire (engine-spec.md, "Version 0.13: the `tlv` wire").
//
// A message is a set of items, each a tag, a length and a value, optionally
// after a fixed key and a length, and optionally ending with a sum16 checksum
// item. A value may itself be a set; it is read as one only when a line of the
// selected scope walks into it. A locator is a path of tags (`48.2`) with an
// optional size in bytes (`:<n>`). Residue is every item of a set read whose
// tag no line names at that place, keyed by its path, holding its value as hex.
//
// Every length read from the input is compared with the bytes left in its set
// before it is used: no offset is computed from an unchecked length.
#include <cstdint>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "codecs.hpp"
#include "transforms.hpp"
#include "util.hpp"

namespace goat_transformers::detail {

namespace {

constexpr std::uint32_t kBerOidMax = (1u << 28) - 1;

// ---------------------------------------------------------------- load checks

[[noreturn]] void bad(const Pack& p, const std::string& locator, std::size_t line, const std::string& why) {
    throw Error(ErrorKind::BadDirective, p.format, locator, p.source + ":" + std::to_string(line) + ": " + why);
}

// The highest tag + 1 the pack's `tag` encoding can write from a pack line.
std::uint64_t tag_limit(const Pack& p) {
    return p.tlv_tag_bytes == 0 ? std::uint64_t{kBerOidMax} + 1 : std::uint64_t{1} << (8 * p.tlv_tag_bytes);
}

// `<tag>[.<tag>...][:<n>]`. `size` is 0 when no `:<n>` is written.
bool parse_tlv_locator(const Pack& p, const std::string& loc, std::vector<std::uint32_t>& path, std::uint32_t& size) {
    path.clear();
    size = 0;
    std::string body = loc;
    const std::size_t colon = loc.find(':');
    if (colon != std::string::npos) {
        const std::string n = loc.substr(colon + 1);
        // Ruling 6 of 0.13: one digit from 1 to 8.
        if (n.size() != 1 || n[0] < '1' || n[0] > '8') return false;
        size = static_cast<std::uint32_t>(n[0] - '0');
        body = loc.substr(0, colon);
    }
    const std::uint64_t limit = tag_limit(p);
    std::size_t at = 0;
    for (;;) {
        const std::size_t dot = body.find('.', at);
        std::uint32_t tag = 0;
        if (!parse_tlv_tag(body.substr(at, dot == std::string::npos ? std::string::npos : dot - at), tag)) return false;
        if (tag >= limit) return false;
        path.push_back(tag);
        if (dot == std::string::npos) break;
        at = dot + 1;
    }
    return true;
}

bool parse_u64_text(const std::string& s, std::uint64_t& out) {
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

bool fits_bytes(std::uint64_t v, std::uint32_t n) { return n >= 8 || (v >> (8 * n)) == 0; }

void check_field_line(const Pack& p, FieldLine& f) {
    if (!parse_tlv_locator(p, f.locator, f.tlv_path, f.tlv_size))
        bad(p, f.locator, f.line, "not a tlv path: tags from 0 to " + std::to_string(tag_limit(p) - 1) +
                                      " with no leading zero, separated by '.', and an optional ':<n>' of 1 to 8");
    const char* name = transform_name(f.transform);
    switch (f.transform) {
        case Transform::Uint:
        case Transform::Twos:
        case Transform::Uscale:
        case Transform::Sscale:
            if (f.tlv_size == 0) bad(p, f.locator, f.line, std::string("transform '") + name + "' needs a size ':<n>'");
            break;
        case Transform::F32:
            if (f.tlv_size != 0 && f.tlv_size != 4) bad(p, f.locator, f.line, "transform 'f32' takes no size or ':4'");
            break;
        case Transform::F64:
            if (f.tlv_size != 0 && f.tlv_size != 8) bad(p, f.locator, f.line, "transform 'f64' takes no size or ':8'");
            break;
        case Transform::Utf8:
        case Transform::Hex:
            if (f.tlv_size != 0) bad(p, f.locator, f.line, std::string("transform '") + name + "' takes no size");
            break;
        default:
            bad(p, f.locator, f.line, std::string("transform '") + name + "' is not valid on wire tlv");
    }
    if (f.swap || f.trim || f.optional) bad(p, f.locator, f.line, "options 'swap', 'trim' and 'optional' are not valid on wire tlv");
    if (p.tlv_checksum && f.tlv_path.front() == p.tlv_checksum_tag)
        bad(p, f.locator, f.line, "a field whose first tag is the checksum tag");
}

void check_fixed_line(const Pack& p, WhenLine& w, const char* word) {
    const std::string what = std::string("'") + word + "'";
    if (!parse_tlv_locator(p, w.locator, w.tlv_path, w.tlv_size))
        bad(p, w.locator, w.line, "not a tlv path for " + what);
    w.present = false;
    if (w.value == "present") {
        if (std::string(word) == "const") bad(p, w.locator, w.line, "'const <path> present'");
        if (w.tlv_size != 0) bad(p, w.locator, w.line, "'when <path> present' takes no size");
        w.present = true;
    } else {
        if (w.tlv_size == 0) bad(p, w.locator, w.line, "a numeric " + what + " needs a size ':<n>'");
        if (!parse_u64_text(w.value, w.number))
            bad(p, w.locator, w.line, what + " value '" + w.value + "' is not an unsigned decimal integer or 'present'");
        if (!fits_bytes(w.number, w.tlv_size))
            bad(p, w.locator, w.line, what + " value " + w.value + " does not fit " + std::to_string(w.tlv_size) + " bytes");
    }
    if (p.tlv_checksum && w.tlv_path.front() == p.tlv_checksum_tag)
        bad(p, w.locator, w.line, what + " whose first tag is the checksum tag");
}

// Ruling 5 of 0.13: in one scope, no line at a path under another line's path.
void check_scope(const Pack& p, const Kind* k) {
    struct Line {
        const std::vector<std::uint32_t>* path;
        const std::string* locator;
        std::size_t line;
    };
    std::vector<Line> lines;
    auto add = [&](const std::vector<FieldLine>& fs, const std::vector<WhenLine>& ws, const std::vector<WhenLine>& cs) {
        for (const auto& f : fs) lines.push_back({&f.tlv_path, &f.locator, f.line});
        for (const auto& w : ws) lines.push_back({&w.tlv_path, &w.locator, w.line});
        for (const auto& c : cs) lines.push_back({&c.tlv_path, &c.locator, c.line});
    };
    add(p.fields, p.whens, p.consts);
    if (k) add(k->fields, k->whens, k->consts);
    std::set<std::vector<std::uint32_t>> prefixes;
    for (const auto& l : lines)
        for (std::size_t n = 1; n < l.path->size(); ++n)
            prefixes.insert(std::vector<std::uint32_t>(l.path->begin(), l.path->begin() + static_cast<std::ptrdiff_t>(n)));
    for (const auto& l : lines)
        if (prefixes.count(*l.path))
            bad(p, *l.locator, l.line, "a line at a path under which another line of the scope reads a set");
}

// ---------------------------------------------------------------- reading

struct TItem {
    std::uint32_t tag = 0;
    std::size_t off = 0;  // the value's first byte in the input
    std::size_t len = 0;  // the value's length
};
using TSet = std::vector<TItem>;

[[noreturn]] void malformed(const Pack& p, const std::string& why) {
    throw Error(ErrorKind::MalformedWire, p.format, "", why);
}

// One tag at `pos`, not past `end`. False with `why` set when it is malformed.
bool read_tag(const Pack& p, const std::string& d, std::size_t& pos, std::size_t end, std::uint32_t& tag,
              std::string& why) {
    if (p.tlv_tag_bytes == 0) {
        std::uint32_t v = 0;
        for (int k = 0;; ++k) {
            if (k == 4) {
                why = "a BER-OID tag of more than four bytes";
                return false;
            }
            if (pos >= end) {
                why = "a tag cut short at offset " + std::to_string(pos);
                return false;
            }
            const unsigned char b = static_cast<unsigned char>(d[pos++]);
            if (k == 0 && b == 0x80) {
                why = "a BER-OID tag whose first byte is 0x80";
                return false;
            }
            v = (v << 7) | (b & 0x7Fu);
            if (!(b & 0x80)) break;
        }
        tag = v;
        return true;
    }
    const std::size_t n = p.tlv_tag_bytes;
    if (end - pos < n) {
        why = "a tag cut short at offset " + std::to_string(pos);
        return false;
    }
    std::uint32_t v = 0;
    for (std::size_t k = 0; k < n; ++k) v = (v << 8) | static_cast<unsigned char>(d[pos++]);
    tag = v;
    return true;
}

// One length at `pos`, not past `end`.
bool read_length(const Pack& p, const std::string& d, std::size_t& pos, std::size_t end, std::uint64_t& len,
                 std::string& why) {
    std::size_t n = p.tlv_length_bytes;
    if (n == 0) {
        if (pos >= end) {
            why = "a length cut short at offset " + std::to_string(pos);
            return false;
        }
        const unsigned char b = static_cast<unsigned char>(d[pos++]);
        if (b < 0x80) {
            len = b;
            return true;
        }
        if (b == 0x80 || b > 0x88) {
            why = "a BER length whose first byte is 0x" + bytes_to_hex(std::string(1, static_cast<char>(b)));
            return false;
        }
        n = b - 0x80u;
    }
    if (end - pos < n) {
        why = "a length cut short at offset " + std::to_string(pos);
        return false;
    }
    std::uint64_t v = 0;
    for (std::size_t k = 0; k < n; ++k) v = (v << 8) | static_cast<unsigned char>(d[pos++]);
    len = v;
    return true;
}

// The items of the set [begin, end) of `d`, read whole.
bool read_set(const Pack& p, const std::string& d, std::size_t begin, std::size_t end, TSet& out, std::string& why) {
    out.clear();
    std::size_t pos = begin;
    while (pos < end) {
        TItem it;
        std::uint64_t len = 0;
        if (!read_tag(p, d, pos, end, it.tag, why) || !read_length(p, d, pos, end, len, why)) return false;
        if (len > end - pos) {  // compared with the bytes left, never added to the offset first
            why = "an item of tag " + std::to_string(it.tag) + " states " + std::to_string(len) + " bytes with " +
                  std::to_string(end - pos) + " left in its set";
            return false;
        }
        it.off = pos;
        it.len = static_cast<std::size_t>(len);
        pos += it.len;
        out.push_back(it);
    }
    return true;
}

const TItem* first_of(const TSet& s, std::uint32_t tag) {
    for (const auto& it : s)
        if (it.tag == tag) return &it;
    return nullptr;
}

// A value of 1 to 8 bytes as an unsigned big-endian integer.
std::uint64_t be_value(const std::string& d, const TItem& it) {
    std::uint64_t v = 0;
    for (std::size_t k = 0; k < it.len; ++k) v = (v << 8) | static_cast<unsigned char>(d[it.off + k]);
    return v;
}

// A set read while decoding: its items, the tags lines name in it, and the
// nested sets lines walk into (the first occurrence of each tag).
struct DNode {
    TSet items;
    std::set<std::uint32_t> named;
    std::map<std::uint32_t, std::unique_ptr<DNode>> children;
};

bool valid_utf8(const std::string& s) {
    std::size_t i = 0;
    while (i < s.size()) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        std::size_t n;
        std::uint32_t cp;
        if (c < 0x80) {
            ++i;
            continue;
        } else if (c >= 0xC2 && c <= 0xDF) {
            n = 1;
            cp = c & 0x1Fu;
        } else if (c >= 0xE0 && c <= 0xEF) {
            n = 2;
            cp = c & 0x0Fu;
        } else if (c >= 0xF0 && c <= 0xF4) {
            n = 3;
            cp = c & 0x07u;
        } else {
            return false;
        }
        if (s.size() - i - 1 < n) return false;
        for (std::size_t k = 1; k <= n; ++k) {
            const unsigned char cc = static_cast<unsigned char>(s[i + k]);
            if ((cc & 0xC0) != 0x80) return false;
            cp = (cp << 6) | (cc & 0x3Fu);
        }
        if ((n == 2 && cp < 0x800) || (n == 3 && cp < 0x10000) || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF))
            return false;
        i += n + 1;
    }
    return true;
}

// The model value of a field's item. Throws std::invalid_argument (transform-decode).
Value decode_item(const FieldLine& f, const std::string& value) {
    const std::size_t n = value.size();
    switch (f.transform) {
        case Transform::Uint:
        case Transform::Twos:
        case Transform::Uscale:
        case Transform::Sscale: {
            if (n > 8)
                throw std::invalid_argument("a value of " + std::to_string(n) + " bytes; an integer has 1 to 8");
            std::uint64_t raw = 0;
            for (unsigned char b : value) raw = (raw << 8) | b;
            // At its own length, whatever `:<n>` states; the sign from the first byte.
            return decode_bits_value(f, raw, static_cast<std::uint32_t>(8 * n));
        }
        case Transform::F32:
        case Transform::F64: {
            const std::size_t want = f.transform == Transform::F32 ? 4 : 8;
            if (n != want)
                throw std::invalid_argument("a value of " + std::to_string(n) + " bytes; " + transform_name(f.transform) +
                                            " takes exactly " + std::to_string(want));
            std::uint64_t raw = 0;
            for (unsigned char b : value) raw = (raw << 8) | b;
            return decode_bits_value(f, raw, static_cast<std::uint32_t>(8 * n));
        }
        case Transform::Utf8:
            if (!valid_utf8(value)) throw std::invalid_argument("the value is not valid UTF-8");
            return Value::of_string(value);
        case Transform::Hex: return Value::of_string(bytes_to_hex(value));
        default: break;
    }
    throw std::invalid_argument("not a tlv transform");
}

// ---------------------------------------------------------------- writing

struct ONode;
struct OSlot {
    std::uint32_t tag = 0;
    bool named = false;      // a field, a numeric `when`, a `const`, or a set on the path of a line
    bool is_set = false;
    std::unique_ptr<ONode> child;
    bool has_value = false;
    bool fixed = false;      // the value is a `when` or `const` value
    bool present = false;    // a `when <path> present` names it
    std::string value;
};
struct ONode {
    std::vector<OSlot> slots;
    std::map<std::uint32_t, std::size_t> index;
    std::vector<std::pair<std::uint32_t, std::string>> residue;
    std::set<std::uint32_t> residue_tags;

    OSlot& slot(std::uint32_t tag) {
        auto it = index.find(tag);
        if (it != index.end()) return slots[it->second];
        index.emplace(tag, slots.size());
        slots.emplace_back();
        slots.back().tag = tag;
        return slots.back();
    }
};

std::string be_bytes(std::uint64_t v, std::uint32_t n) {
    std::string out(n, '\0');
    for (std::uint32_t k = 0; k < n; ++k) out[n - 1 - k] = static_cast<char>((v >> (8 * k)) & 0xFF);
    return out;
}

void put_tag(const Pack& p, std::string& out, std::uint32_t tag) {
    if (p.tlv_tag_bytes == 0) {
        if (tag > kBerOidMax)
            throw Error(ErrorKind::TransformEncode, p.format, std::to_string(tag),
                        "the tag does not fit four BER-OID bytes");
        char buf[4];
        int n = 0;
        std::uint32_t v = tag;
        do {
            buf[n++] = static_cast<char>(v & 0x7F);
            v >>= 7;
        } while (v);
        for (int k = n - 1; k >= 0; --k) out += static_cast<char>(buf[k] | (k ? 0x80 : 0));
        return;
    }
    if (!fits_bytes(tag, p.tlv_tag_bytes))
        throw Error(ErrorKind::TransformEncode, p.format, std::to_string(tag),
                    "the tag does not fit " + std::to_string(p.tlv_tag_bytes) + " bytes");
    out += be_bytes(tag, p.tlv_tag_bytes);
}

void put_length(const Pack& p, std::string& out, std::size_t len_sz, const std::string& where) {
    const std::uint64_t len = len_sz;
    if (p.tlv_length_bytes == 0) {
        if (len < 0x80) {
            out += static_cast<char>(len);
            return;
        }
        std::uint32_t n = 1;
        while (n < 8 && (len >> (8 * n)) != 0) ++n;
        out += static_cast<char>(0x80 + n);
        out += be_bytes(len, n);
        return;
    }
    if (!fits_bytes(len, p.tlv_length_bytes))
        throw Error(ErrorKind::TransformEncode, p.format, where,
                    "a length of " + std::to_string(len) + " does not fit " + std::to_string(p.tlv_length_bytes) +
                        " bytes");
    out += be_bytes(len, p.tlv_length_bytes);
}

void put_item(const Pack& p, std::string& out, std::uint32_t tag, const std::string& value) {
    put_tag(p, out, tag);
    put_length(p, out, value.size(), std::to_string(tag));
    out += value;
}

int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

// Hex text, an even number of digits in either case, to bytes.
bool hex_text(const std::string& s, std::string& out) {
    if (s.size() % 2) return false;
    out.clear();
    for (std::size_t k = 0; k < s.size(); k += 2) {
        const int hi = hex_digit(s[k]), lo = hex_digit(s[k + 1]);
        if (hi < 0 || lo < 0) return false;
        out += static_cast<char>((hi << 4) | lo);
    }
    return true;
}

// A model value as text, as the `string` transform writes it.
std::string string_text(const Value& v) {
    FieldLine as_string;
    as_string.transform = Transform::String;
    return encode_value(as_string, v);
}

// A field's model value as its item's bytes. Throws std::invalid_argument (transform-encode).
std::string encode_item(const FieldLine& f, const Value& v) {
    const std::uint32_t n = f.tlv_size;
    switch (f.transform) {
        case Transform::Uint: {
            const std::int64_t x = model_int(v);
            // Ruling 3 of 0.13; ruling 2 of 0.5 covers an 8-byte uint only.
            if (n < 8 && (x < 0 || !fits_bytes(static_cast<std::uint64_t>(x), n)))
                throw std::invalid_argument(std::to_string(x) + " does not fit an unsigned integer of " +
                                            std::to_string(n) + " bytes");
            return be_bytes(static_cast<std::uint64_t>(x), n);
        }
        case Transform::Twos: {
            const std::int64_t x = model_int(v);
            if (n < 8) {
                const std::int64_t half = std::int64_t{1} << (8 * n - 1);
                if (x < -half || x >= half)
                    throw std::invalid_argument(std::to_string(x) + " does not fit a two's-complement integer of " +
                                                std::to_string(n) + " bytes");
            }
            return be_bytes(static_cast<std::uint64_t>(x), n);
        }
        case Transform::Uscale:
        case Transform::Sscale: return be_bytes(encode_bits_value(f, v, 8 * n), n);
        case Transform::F32: return be_bytes(encode_bits_value(f, v, 32), 4);
        case Transform::F64: return be_bytes(encode_bits_value(f, v, 64), 8);
        case Transform::Utf8: {
            std::string s = string_text(v);
            if (!valid_utf8(s)) throw std::invalid_argument("the text is not valid UTF-8");
            return s;
        }
        case Transform::Hex: {
            const std::string s = string_text(v);
            std::string out;
            if (!hex_text(s, out))
                throw std::invalid_argument("\"" + s + "\" is not hex text of an even number of digits");
            return out;
        }
        default: break;
    }
    throw std::invalid_argument("not a tlv transform");
}

std::string write_set(const Pack& p, const ONode& n) {
    std::string out;
    for (const auto& s : n.slots) {
        if (s.is_set) {
            const std::string inner = write_set(p, *s.child);
            if (!inner.empty()) put_item(p, out, s.tag, inner);  // a nested set with no items is not written
        } else if (s.has_value) {
            put_item(p, out, s.tag, s.value);
        } else if (s.present && !n.residue_tags.count(s.tag)) {
            put_item(p, out, s.tag, std::string());
        }
    }
    for (const auto& r : n.residue) put_item(p, out, r.first, r.second);
    return out;
}

// A residue path: decimal tags separated by '.'.
bool parse_residue_path(const std::string& s, std::vector<std::uint32_t>& path) {
    path.clear();
    std::size_t at = 0;
    for (;;) {
        const std::size_t dot = s.find('.', at);
        const std::string part = s.substr(at, dot == std::string::npos ? std::string::npos : dot - at);
        std::uint64_t v = 0;
        if (part.empty() || part.size() > 10 || !parse_u64_text(part, v) || v > 0xFFFFFFFFull) return false;
        path.push_back(static_cast<std::uint32_t>(v));
        if (dot == std::string::npos) return true;
        at = dot + 1;
    }
}

// One line of a scope: its path, and whether it names the last tag of it.
struct PathLine {
    const std::vector<std::uint32_t>* path;
    bool names_last;
};

PathLine path_of(const LineRef& line) {
    if (line.field) return {&line.field->tlv_path, true};
    const WhenLine* w = line.fixed();
    return {&w->tlv_path, !w->present};
}

std::uint16_t sum16(const std::string& d, std::size_t end) {
    std::uint32_t sum = 0;
    for (std::size_t i = 0; i < end; ++i) {
        const std::uint32_t b = static_cast<unsigned char>(d[i]);
        sum = (sum + (i % 2 == 0 ? b * 256 : b)) & 0xFFFF;
    }
    return static_cast<std::uint16_t>(sum);
}

}  // namespace

bool parse_tlv_tag(const std::string& text, std::uint32_t& out) {
    if (text.empty() || text.size() > 9) return false;
    if (text.size() > 1 && text[0] == '0') return false;
    std::uint64_t v = 0;
    for (char c : text) {
        if (c < '0' || c > '9') return false;
        v = v * 10 + static_cast<std::uint64_t>(c - '0');
    }
    if (v > kBerOidMax) return false;
    out = static_cast<std::uint32_t>(v);
    return true;
}

void check_tlv_pack(Pack& p) {
    if (p.tlv_checksum && p.tlv_checksum_tag >= tag_limit(p))
        throw Error(ErrorKind::BadDirective, p.format, "",
                    p.source + ": the checksum tag " + std::to_string(p.tlv_checksum_tag) + " does not fit 'tag " +
                        std::to_string(p.tlv_tag_bytes) + "'");
    auto scope = [&](std::vector<FieldLine>& fs, std::vector<WhenLine>& ws, std::vector<WhenLine>& cs) {
        for (auto& f : fs) check_field_line(p, f);
        for (auto& w : ws) check_fixed_line(p, w, "when");
        for (auto& c : cs) check_fixed_line(p, c, "const");
    };
    scope(p.fields, p.whens, p.consts);
    for (auto& k : p.kinds) scope(k.fields, k.whens, k.consts);
    if (!p.groups.empty()) bad(p, p.groups.front().locator, p.groups.front().line, "'group' on wire tlv");
    for (const auto& k : p.kinds)
        if (!k.groups.empty()) bad(p, k.groups.front().locator, k.groups.front().line, "'group' on wire tlv");
    check_scope(p, nullptr);
    for (const auto& k : p.kinds) check_scope(p, &k);
}

Entity decode_tlv(const Pack& p, const std::string& text) {
    const std::string d = hex_to_bytes(p, text);
    std::string why;

    // Step 2: the key and the length of the set.
    std::size_t begin = 0, end = d.size();
    if (p.tlv_has_key) {
        const std::string& key = p.tlv_key;
        if (d.size() < key.size() || d.compare(0, key.size(), key) != 0) malformed(p, "the input does not begin with the key");
        std::size_t pos = key.size();
        std::uint64_t len = 0;
        if (!read_length(p, d, pos, d.size(), len, why)) malformed(p, why + " (the length of the set)");
        if (len > d.size() - pos)
            malformed(p, "the set states " + std::to_string(len) + " bytes with " + std::to_string(d.size() - pos) +
                             " left in the input");
        begin = pos;
        end = pos + static_cast<std::size_t>(len);
    }

    // Step 3: the top set, read whole.
    DNode root;
    if (!read_set(p, d, begin, end, root.items, why)) malformed(p, why);

    // Step 4: the checksum item.
    if (p.tlv_checksum) {
        const std::uint32_t t = p.tlv_checksum_tag;
        if (root.items.empty()) malformed(p, "no checksum item");
        const TItem last = root.items.back();
        if (last.tag != t) malformed(p, "the last item is not the checksum item of tag " + std::to_string(t));
        if (last.len != 2) malformed(p, "the checksum item's value is not two bytes");
        root.items.pop_back();
        for (const auto& it : root.items)
            if (it.tag == t) malformed(p, "an item of the checksum tag " + std::to_string(t) + " before the last");
        const std::uint16_t want = sum16(d, last.off);
        const std::uint16_t got = static_cast<std::uint16_t>(be_value(d, last));
        if (want != got)
            malformed(p, "the checksum is " + std::to_string(got) + " and the bytes sum to " + std::to_string(want));
    }

    // The kind, before any nested set is read for the scope's lines. A `when`
    // whose item lies in a value that is not a well-formed set does not hold.
    auto find_item = [&](const std::vector<std::uint32_t>& path, TItem& out) {
        const TSet* cur = &root.items;
        TSet held;
        for (std::size_t i = 0; i < path.size(); ++i) {
            const TItem* it = first_of(*cur, path[i]);
            if (!it) return false;
            if (i + 1 == path.size()) {
                out = *it;
                return true;
            }
            TSet next;
            std::string ignored;
            if (!read_set(p, d, it->off, it->off + it->len, next, ignored)) return false;
            held = std::move(next);
            cur = &held;
        }
        return false;
    };
    const Kind* kind = select_decode_kind(p, [&](const WhenLine& w) {
        TItem it;
        if (!find_item(w.tlv_path, it)) return false;
        if (w.present) return true;
        if (it.len == 0 || it.len > 8) return false;
        return be_value(d, it) == w.number;
    });

    // Walk into every set on the path of a line of the selected scope.
    const std::vector<LineRef> lines = active_lines(p, kind);
    for (const auto& line : lines) {
        const PathLine pl = path_of(line);
        const std::vector<std::uint32_t>& path = *pl.path;
        DNode* n = &root;
        for (std::size_t i = 0; i < path.size(); ++i) {
            const bool last = i + 1 == path.size();
            if (!last || pl.names_last) n->named.insert(path[i]);
            if (last) break;
            auto c = n->children.find(path[i]);
            if (c == n->children.end()) {
                const TItem* it = first_of(n->items, path[i]);
                if (!it) break;
                auto child = std::make_unique<DNode>();
                if (!read_set(p, d, it->off, it->off + it->len, child->items, why))
                    malformed(p, why + " (in the set of the path " + line.locator() + ")");
                c = n->children.emplace(path[i], std::move(child)).first;
            }
            n = c->second.get();
        }
    }

    Entity e;
    Decoder dec(p, e);
    for (const auto& line : lines) {
        if (!line.field) continue;
        const FieldLine& f = *line.field;
        if (!dec.wants(f)) continue;
        const DNode* n = &root;
        const std::vector<std::uint32_t>& path = f.tlv_path;
        for (std::size_t i = 0; n && i + 1 < path.size(); ++i) {
            auto c = n->children.find(path[i]);
            n = c == n->children.end() ? nullptr : c->second.get();
        }
        if (!n) continue;
        const TItem* it = first_of(n->items, path.back());
        if (!it) continue;  // absent
        if (it->len == 0 && f.transform != Transform::Utf8 && f.transform != Transform::Hex) continue;  // absent
        Value v;
        try {
            v = decode_item(f, d.substr(it->off, it->len));
        } catch (const std::invalid_argument& ex) {
            dec.fail(f, ex.what());
            continue;
        }
        dec.put(f, std::move(v));
    }

    // Residue: every item no line names at its place, every occurrence, in input order.
    struct Residue {
        const Pack& p;
        const std::string& d;
        Entity& e;
        void operator()(const DNode& n, const std::string& prefix) {
            std::set<std::uint32_t> walked;
            for (const auto& it : n.items) {
                if (n.named.count(it.tag)) {
                    auto c = n.children.find(it.tag);
                    if (c != n.children.end() && walked.insert(it.tag).second)
                        (*this)(*c->second, prefix + std::to_string(it.tag) + ".");
                    continue;
                }
                e.residue.push_back({p.format, prefix + std::to_string(it.tag), bytes_to_hex(d.substr(it.off, it.len))});
            }
        }
    } residue{p, d, e};
    residue(root, "");

    dec.finish();
    if (kind) e.kind = {p.format, kind->name};
    return e;
}

std::string encode_tlv(const Pack& p, const Entity& e) {
    const Kind* kind = select_encode_kind(p, e);
    const EncodeSource src(p, kind, e);
    const std::vector<LineRef> lines = active_lines(p, kind);

    // Ruling 9 of 0.13: on a path a numeric `when` or a `const` names, the item
    // holds the earliest of their values and no `field` on it is encoded.
    std::set<std::vector<std::uint32_t>> fixed_paths;
    for (const auto& line : lines)
        if (const WhenLine* w = line.fixed())
            if (!w->present) fixed_paths.insert(w->tlv_path);

    ONode root;
    for (const auto& line : lines) {
        const PathLine pl = path_of(line);
        const std::vector<std::uint32_t>& path = *pl.path;
        ONode* n = &root;
        for (std::size_t i = 0; i + 1 < path.size(); ++i) {
            OSlot& s = n->slot(path[i]);
            s.named = true;
            s.is_set = true;
            if (!s.child) s.child = std::make_unique<ONode>();
            n = s.child.get();
        }
        OSlot& s = n->slot(path.back());
        if (line.field) {
            s.named = true;
            if (s.fixed || s.has_value || fixed_paths.count(path)) continue;  // another line writes the item
            Value v;
            // A line suppressed by `with` writes nothing, its default included (0.18 ruling 1).
            if (src.suppressed(*line.field) || !src.value(*line.field, v)) continue;
            try {
                s.value = encode_item(*line.field, v);
            } catch (const std::invalid_argument& ex) {
                throw Error(ErrorKind::TransformEncode, p.format, line.field->locator, line.field->key + ": " + ex.what());
            }
            s.has_value = true;
            continue;
        }
        const WhenLine& w = *line.fixed();
        if (w.present) {
            s.present = true;
            continue;
        }
        s.named = true;
        if (!s.fixed) {  // the first `when` or `const` on the path; over any field
            s.fixed = true;
            s.has_value = true;
            s.value = be_bytes(w.number, w.tlv_size);
        }
    }

    // Residue of this format, into the sets the scope writes, at tags no line names there.
    std::vector<std::uint32_t> path;
    for (const auto& r : e.residue) {
        if (r.format != p.format || !parse_residue_path(r.locator, path)) continue;
        ONode* n = &root;
        for (std::size_t i = 0; n && i + 1 < path.size(); ++i) {
            auto it = n->index.find(path[i]);
            n = it != n->index.end() && n->slots[it->second].is_set ? n->slots[it->second].child.get() : nullptr;
        }
        if (!n) continue;
        const std::uint32_t tag = path.back();
        auto it = n->index.find(tag);
        if (it != n->index.end() && n->slots[it->second].named) continue;
        if (n == &root && p.tlv_checksum && tag == p.tlv_checksum_tag) continue;
        std::string bytes;
        if (!hex_text(r.value, bytes)) continue;
        n->residue.emplace_back(tag, std::move(bytes));
        n->residue_tags.insert(tag);
    }

    std::string set = write_set(p, root);
    std::size_t checksum_at = 0;
    if (p.tlv_checksum) {
        put_tag(p, set, p.tlv_checksum_tag);
        put_length(p, set, 2, std::to_string(p.tlv_checksum_tag));
        checksum_at = set.size();
        set += std::string(2, '\0');
    }
    std::string out;
    if (p.tlv_has_key) {
        out = p.tlv_key;
        put_length(p, out, set.size(), "");
    }
    const std::size_t set_at = out.size();
    out += set;
    if (p.tlv_checksum) {
        const std::size_t at = set_at + checksum_at;
        const std::uint16_t sum = sum16(out, at);
        out[at] = static_cast<char>(sum >> 8);
        out[at + 1] = static_cast<char>(sum & 0xFF);
    }
    return bytes_to_hex(out);
}

}  // namespace goat_transformers::detail
