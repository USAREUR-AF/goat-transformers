// Deterministic malformed-input test (engine-spec.md, "Malformed input (0.8)").
//
// Every vector input of every pack under GT_PACKS_DIR is cut at prefixes and
// changed one byte at a time, and each result is given to `convert`. A call
// passes when it returns, or when it throws goat_transformers::Error with a
// message that begins with the name of its kind and a colon. Any other
// exception fails the test; a crash or an out-of-bounds read is for the
// sanitizers to report (build with -fsanitize=address,undefined).
//
// The cases are the same on every run: positions are spread evenly over an
// input longer than the cap, and the replacement bytes come from a fixed
// generator.
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"
#include "json.hpp"

#ifndef GT_PACKS_DIR
#error "GT_PACKS_DIR must be defined by the build"
#endif

namespace fs = std::filesystem;
using goat_transformers::Engine;
namespace json = goat_transformers::json;

namespace {

// Prefixes, and mutated positions, per input. GT_FUZZ_POSITIONS (2 or more)
// sets another number, for a slow build or a loaded machine.
std::size_t kMaxPositions = 96;

std::string read_file(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

// Up to kMaxPositions offsets in [0, n), evenly spread, first and last included.
std::vector<std::size_t> positions(std::size_t n) {
    std::vector<std::size_t> out;
    if (n == 0) return out;
    if (n <= kMaxPositions) {
        for (std::size_t k = 0; k < n; ++k) out.push_back(k);
        return out;
    }
    for (std::size_t k = 0; k < kMaxPositions; ++k) out.push_back(k * (n - 1) / (kMaxPositions - 1));
    out.erase(std::unique(out.begin(), out.end()), out.end());
    return out;
}

struct Rng {
    std::uint64_t s = 0x9E3779B97F4A7C15ull;
    std::uint64_t next() {
        s ^= s << 13;
        s ^= s >> 7;
        s ^= s << 17;
        return s;
    }
};

// The bytes of hex text (space, tab, CR and LF ignored); false when the text
// is not hex, or holds no digit.
bool hex_bytes(const std::string& text, std::string& out) {
    out.clear();
    int hi = -1;
    for (char c : text) {
        if (c == ' ' || c == '\t' || c == '\r' || c == '\n') continue;
        int n = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
        if (n < 0) return false;
        if (hi < 0) {
            hi = n;
        } else {
            out += static_cast<char>((hi << 4) | n);
            hi = -1;
        }
    }
    return hi < 0 && !out.empty();
}

std::string to_hex(const std::string& data) {
    static const char* hex = "0123456789abcdef";
    std::string out;
    for (unsigned char c : data) {
        out += hex[c >> 4];
        out += hex[c & 0xF];
    }
    return out;
}

// Six-bit armor (0.14): is every character of the text one of the 64 that
// stand for six bits, `0` to `W` and `` ` `` to `w`?
bool armor_text(const std::string& text) {
    if (text.empty()) return false;
    for (char c : text)
        if (!((c >= 0x30 && c <= 0x57) || (c >= 0x60 && c <= 0x77))) return false;
    return true;
}

// The armor character that stands for `v` (0 to 63).
char armor_char(unsigned v) { return static_cast<char>(v < 40 ? 0x30 + v : 0x38 + v); }

struct Tally {
    std::uint64_t calls = 0, returned = 0, refused = 0, bad = 0;
};

void run_one(const Engine& eng, const std::string& from, const std::string& to, const std::string& input,
             const std::string& label, Tally& t) {
    ++t.calls;
    std::string why;
    try {
        (void)eng.convert(from, to, input);
        ++t.returned;
        return;
    } catch (const goat_transformers::Error& e) {
        const std::string kind = goat_transformers::error_kind_name(e.kind());
        const std::string message = e.what();
        if (!kind.empty() && kind != "?" && message.compare(0, kind.size() + 1, kind + ":") == 0) {
            ++t.refused;
            return;
        }
        why = "the error message does not begin with its kind and a colon: " + message;
    } catch (const std::exception& e) {
        why = std::string("an exception that is not the engine's error: ") + e.what();
    } catch (...) {
        why = "an exception that is not a std::exception";
    }
    if (++t.bad <= 20) {
        std::cout << "FAIL " << label << "\n  " << why << "\n  input (" << input.size() << " bytes):";
        static const char* hex = "0123456789abcdef";
        for (std::size_t k = 0; k < input.size() && k < 200; ++k) {
            const unsigned char c = static_cast<unsigned char>(input[k]);
            std::cout << ' ' << hex[c >> 4] << hex[c & 0xF];
        }
        std::cout << "\n";
    }
}

// ---- the cbor wire (0.28): random and hostile data items

void put_head(std::string& out, unsigned major, std::uint64_t arg) {
    const unsigned m = major << 5;
    unsigned bytes = 0;
    if (arg < 24) {
        out += static_cast<char>(m | static_cast<unsigned>(arg));
        return;
    }
    if (arg <= 0xFF) {
        out += static_cast<char>(m | 24u);
        bytes = 1;
    } else if (arg <= 0xFFFF) {
        out += static_cast<char>(m | 25u);
        bytes = 2;
    } else if (arg <= 0xFFFFFFFFull) {
        out += static_cast<char>(m | 26u);
        bytes = 4;
    } else {
        out += static_cast<char>(m | 27u);
        bytes = 8;
    }
    for (unsigned k = bytes; k-- > 0;) out += static_cast<char>((arg >> (8 * k)) & 0xFF);
}

// A random data item, mostly well formed: integers of every head length,
// strings (definite and in chunks, some not UTF-8), arrays and maps (definite
// and indefinite, keys drawn from a small set so that paths of the packs meet
// them and keys repeat), tags, simple values and floats. Now and then a byte
// that is not well formed. `depth` bounds the nesting it makes.
void random_item(Rng& rng, std::string& out, int depth) {
    const std::uint64_t r = rng.next();
    const unsigned pick = static_cast<unsigned>(r % (depth > 0 ? 16 : 9));
    auto small_key = [&]() {
        const std::uint64_t k = rng.next() % 14;
        if (k < 10) put_head(out, 0, k);
        else if (k == 10) put_head(out, 1, 0);
        else {
            static const char* names[] = {"flag", "n", "name"};
            const std::string t = names[k - 11];
            put_head(out, 3, t.size());
            out += t;
        }
    };
    switch (pick) {
        case 0: put_head(out, 0, rng.next() >> (rng.next() % 64)); break;
        case 1: put_head(out, 1, rng.next() >> (rng.next() % 64)); break;
        case 2:
        case 3: {
            const unsigned major = pick;
            const std::size_t n = rng.next() % 6;
            std::string bytes;
            for (std::size_t k = 0; k < n; ++k) bytes += static_cast<char>(rng.next() % (rng.next() % 4 ? 0x80 : 0x100));
            if (rng.next() % 4 == 0) {
                out += static_cast<char>((major << 5) | 31u);
                for (std::size_t k = 0; k < bytes.size(); ++k) {
                    put_head(out, major, 1);
                    out += bytes[k];
                }
                out += static_cast<char>(0xFF);
            } else {
                put_head(out, major, bytes.size());
                out += bytes;
            }
            break;
        }
        case 4: {
            static const unsigned char simple[] = {0xF4, 0xF5, 0xF6, 0xF7, 0xE0, 0xF0};
            out += static_cast<char>(simple[rng.next() % sizeof simple]);
            break;
        }
        case 5: {
            // 1.5, a NaN, an infinity, 100000.0, 0.1, -0.0, and 1.5 as a double.
            static const std::string floats[] = {std::string("\xf9\x3e\x00", 3), std::string("\xf9\x7e\x00", 3),
                                                 std::string("\xf9\x7c\x00", 3), std::string("\xfa\x47\xc3\x50\x00", 5),
                                                 std::string("\xfb\x3f\xb9\x99\x99\x99\x99\x99\x9a", 9),
                                                 std::string("\xf9\x80\x00", 3),
                                                 std::string("\xfb\x3f\xf8\x00\x00\x00\x00\x00\x00", 9)};
            out += floats[rng.next() % 7];
            break;
        }
        case 6: {
            // Not well formed: reserved information, a break, a short simple value, a cut head,
            // a chunk of another type, an indefinite integer.
            static const std::string bad[] = {std::string("\x1c", 1), std::string("\xff", 1), std::string("\xf8\x10", 2),
                                              std::string("\x1b\x00", 2), std::string("\x5f\x60\xff", 3),
                                              std::string("\x3f", 1)};
            out += bad[rng.next() % 6];
            break;
        }
        case 7:
        case 8: small_key(); break;
        case 9:
        case 10:
        case 11: {
            const std::size_t n = rng.next() % 5;
            const bool indefinite = rng.next() % 4 == 0;
            if (indefinite) out += static_cast<char>(0x9F);
            else put_head(out, 4, n);
            for (std::size_t k = 0; k < n; ++k) random_item(rng, out, depth - 1);
            if (indefinite) out += static_cast<char>(0xFF);
            break;
        }
        case 12:
        case 13:
        case 14: {
            const std::size_t n = rng.next() % 5;
            const bool indefinite = rng.next() % 4 == 0;
            if (indefinite) out += static_cast<char>(0xBF);
            else put_head(out, 5, n);
            for (std::size_t k = 0; k < n; ++k) {
                if (rng.next() % 6 == 0) random_item(rng, out, depth - 1);
                else small_key();
                random_item(rng, out, depth - 1);
            }
            if (indefinite) out += static_cast<char>(0xFF);
            break;
        }
        default:
            put_head(out, 6, rng.next() % 3 == 0 ? 18 : rng.next() % 70000);
            random_item(rng, out, depth - 1);
    }
}

// Inputs no sender should be able to crash an engine with: nesting far past
// the limit through arrays, maps and tags, declared lengths and counts far
// past the input, and indefinite items that never end.
std::vector<std::string> hostile_cbor() {
    std::vector<std::string> out;
    auto rep = [](const std::string& unit, std::size_t n) {
        std::string s;
        for (std::size_t k = 0; k < n; ++k) s += unit;
        return s;
    };
    for (std::size_t n : {63, 64, 65, 200, 5000}) {
        out.push_back(rep("\x81", n) + std::string(1, '\0'));
        out.push_back(rep("\xa1\x00", n) + std::string(1, '\0'));
        out.push_back(rep("\xc1", n) + std::string(1, '\0'));
        out.push_back(rep("\xd9\xd9\xf7", n) + "\xa0");
        out.push_back(rep("\x9f", n) + rep("\xff", n));
        out.push_back(rep("\xbf\x00", n) + std::string(1, '\0') + rep("\xff", n));
        out.push_back(rep("\x81\xa1\x00\xc1", n) + std::string(1, '\0'));
        out.push_back("\xd2" + rep("\x81", n) + std::string(1, '\0'));
    }
    // Lengths and counts of 2^64-1, 2^32-1 and 2^16-1 with little or nothing after them.
    for (const char* h : {"\x5b", "\x7b", "\x9b", "\xbb", "\xdb"}) {
        out.push_back(std::string(h) + std::string(8, '\xff'));
        out.push_back(std::string(h) + std::string(8, '\xff') + "\x00\x00");
    }
    for (const char* h : {"\x5a", "\x7a", "\x9a", "\xba"}) out.push_back(std::string(h) + std::string(4, '\xff') + "\x00");
    for (const char* h : {"\x59", "\x79", "\x99", "\xb9"}) out.push_back(std::string(h) + std::string(2, '\xff') + "\x00");
    out.push_back("\xa2\x00\x01\x0a\x9b" + std::string(8, '\xff'));
    out.push_back("\x82\x00\x5b" + std::string(8, '\x7f') + "\x00");
    // Indefinite items with no break: empty chunks, elements, members.
    out.push_back("\x5f" + rep("\x40", 4000));
    out.push_back("\x7f" + rep("\x61\x61", 4000));
    out.push_back("\x9f" + rep("\x00", 4000));
    out.push_back("\xbf" + rep("\x00\x00", 4000));
    out.push_back("\xa1\x00\x01\x0a\x9f" + rep("\x9f", 60));
    out.push_back("\xd2\x9f" + rep("\x40", 100));
    // A long definite array of small items, and a map with many keys.
    out.push_back("\x9a\x00\x01\x86\xa0" + rep(std::string(1, '\0'), 100000));
    {
        std::string m;
        put_head(m, 5, 20000);
        for (std::uint64_t k = 0; k < 20000; ++k) {
            put_head(m, 0, k);
            m += '\0';
        }
        out.push_back(m);
        std::string dup;  // the same members and the key 24 once more
        put_head(dup, 5, 20001);
        dup += m.substr(3);
        put_head(dup, 0, 24);
        dup += '\0';
        out.push_back(dup);
    }
    return out;
}

}  // namespace

int main() {
    const fs::path packs = GT_PACKS_DIR;
    if (const char* env = std::getenv("GT_FUZZ_POSITIONS")) {
        std::size_t n = 0;
        for (const char* c = env; *c >= '0' && *c <= '9' && n < 100000; ++c) n = n * 10 + static_cast<std::size_t>(*c - '0');
        if (n >= 2) kMaxPositions = n;
    }
    Engine eng;
    try {
        eng = Engine::load(packs.string());
    } catch (const std::exception& e) {
        std::cerr << "FAIL loading packs from " << packs << ": " << e.what() << "\n";
        return 1;
    }

    std::vector<fs::path> files;
    for (const auto& d : fs::directory_iterator(packs)) {
        const fs::path vdir = d.path() / "vectors";
        if (!fs::is_directory(vdir)) continue;
        for (const auto& f : fs::directory_iterator(vdir))
            if (f.path().extension() == ".json") files.push_back(f.path());
    }
    std::sort(files.begin(), files.end());

    // Bytes that matter to one wire or another, then two generated ones.
    static const char kStructural[] = {'<', '>', '"', '\\', '{', '[', ']', '}', ',', ':', '&', '-', '+', '.', '0', 'g'};
    Rng rng;
    Tally t;
    int inputs = 0;
    for (const auto& file : files) {
        std::string from, to, input;
        try {
            const json::Value v = json::parse(read_file(file));
            const json::Value* f = v.find("from");
            const json::Value* o = v.find("to");
            const json::Value* i = v.find("input");
            if (!f || !o || !i || !f->is(json::Value::Kind::String) || !o->is(json::Value::Kind::String) ||
                !i->is(json::Value::Kind::String))
                continue;  // an input given another way: the vector test reads it
            from = f->text;
            to = o->text;
            input = i->text;
        } catch (const std::exception& e) {
            std::cout << "FAIL reading " << file << ": " << e.what() << "\n";
            ++t.bad;
            continue;
        }
        ++inputs;
        const std::string label = file.parent_path().parent_path().filename().string() + "/" + file.filename().string();

        run_one(eng, from, to, input, label + " as written", t);
        // Truncated: the first `n` bytes, the empty input included.
        for (std::size_t n : positions(input.size()))
            run_one(eng, from, to, input.substr(0, n), label + " cut to " + std::to_string(n) + " bytes", t);
        // One byte changed: flipped low bit, flipped high bit, a structural
        // byte and a generated byte.
        for (std::size_t at : positions(input.size())) {
            const char was = input[at];
            const std::uint64_t r = rng.next();
            const char with[] = {static_cast<char>(was ^ 0x01), static_cast<char>(was ^ 0x80),
                                 kStructural[r % sizeof kStructural], static_cast<char>((r >> 8) & 0xFF)};
            for (char c : with) {
                if (c == was) continue;
                std::string m = input;
                m[at] = c;
                run_one(eng, from, to, m, label + " byte " + std::to_string(at) + " changed", t);
            }
        }
        // Hex input (bits, protobuf, tlv): the same on the bytes it holds, so
        // that the cases reach the wire's own structure (tags, lengths,
        // checksums) and not only the hex text. Lengths of all ones and of
        // the BER long forms are among the replacement bytes.
        std::string data;
        if (hex_bytes(input, data)) {
            for (std::size_t n : positions(data.size()))
                run_one(eng, from, to, to_hex(data.substr(0, n)), label + " cut to " + std::to_string(n) + " input bytes", t);
            static const unsigned char kBinary[] = {0x00, 0x01, 0x02, 0x7F, 0x80, 0x81, 0x82, 0x88, 0x89, 0xFF};
            for (std::size_t at : positions(data.size())) {
                const char was = data[at];
                const std::uint64_t r = rng.next();
                const char with[] = {static_cast<char>(was ^ 0x01), static_cast<char>(was ^ 0x80),
                                     static_cast<char>(kBinary[r % sizeof kBinary]), static_cast<char>((r >> 8) & 0xFF)};
                for (char c : with) {
                    if (c == was) continue;
                    std::string m = data;
                    m[at] = c;
                    run_one(eng, from, to, to_hex(m), label + " input byte " + std::to_string(at) + " changed", t);
                }
                // Eight bytes of 0xFF from here: a length of 2^64-1 under a long form.
                std::string m = data;
                for (std::size_t k = at; k < m.size() && k < at + 8; ++k) m[k] = static_cast<char>(0xFF);
                run_one(eng, from, to, to_hex(m), label + " input bytes from " + std::to_string(at) + " set to ff", t);
            }
            // UPER (0.19) is unaligned: a length, a count or an index can start
            // at any bit, so every bit of the chosen bytes is flipped as well.
            if (eng.has_format(from) && eng.pack(from).uper) {
                for (std::size_t at : positions(data.size()))
                    for (int b = 0; b < 8; ++b) {
                        std::string m = data;
                        m[at] = static_cast<char>(m[at] ^ (1 << b));
                        run_one(eng, from, to, to_hex(m),
                                label + " input byte " + std::to_string(at) + " bit " + std::to_string(b) + " flipped", t);
                    }
            }
        }
        // Armored text (a pack with `armor sixbit`): characters replaced by other valid ones, so that the
        // cases reach the lines of the message and not only the character
        // check; and the text with characters added (all ones, all zeros).
        if (eng.has_format(from) && eng.pack(from).armor_sixbit && armor_text(input)) {
            for (std::size_t at : positions(input.size())) {
                const std::uint64_t r = rng.next();
                const unsigned v = input[at] <= 0x57 ? static_cast<unsigned>(input[at] - 0x30)
                                                     : static_cast<unsigned>(input[at] - 0x38);
                const char with[] = {armor_char(v ^ 0x01), armor_char(v ^ 0x20), armor_char(63), armor_char(0),
                                     armor_char(static_cast<unsigned>(r % 64))};
                for (char c : with) {
                    if (c == input[at]) continue;
                    std::string m = input;
                    m[at] = c;
                    run_one(eng, from, to, m, label + " armor character " + std::to_string(at) + " changed", t);
                }
            }
            for (std::size_t extra : {1, 7, 64}) {
                run_one(eng, from, to, input + std::string(extra, 'w'), label + " with " + std::to_string(extra) + " w added", t);
                run_one(eng, from, to, input + std::string(extra, '0'), label + " with " + std::to_string(extra) + " 0 added", t);
            }
        }
    }

    // The cbor wire: hostile items and random items through every cbor pack,
    // bare and inside the pack's tag and a top item of the pack's type.
    {
        const std::vector<std::string> hostile = hostile_cbor();
        for (const std::string& format : eng.formats()) {
            const goat_transformers::Pack& p = eng.pack(format);
            if (p.wire != goat_transformers::Wire::Cbor) continue;
            std::string prefix;
            if (p.cbor_tag) put_head(prefix, 6, p.cbor_tag_value);
            for (std::size_t k = 0; k < hostile.size(); ++k) {
                run_one(eng, format, format, to_hex(hostile[k]), format + " hostile cbor " + std::to_string(k), t);
                run_one(eng, format, format, to_hex(prefix + hostile[k]), format + " hostile cbor " + std::to_string(k) + " tagged", t);
                const std::string wrapped = p.cbor_top_array ? "\x82" + hostile[k] + hostile[k]
                                                             : "\xa2\x07" + hostile[k] + "\x09" + hostile[k];
                run_one(eng, format, format, to_hex(prefix + wrapped), format + " hostile cbor " + std::to_string(k) + " inside", t);
            }
            const std::size_t count = kMaxPositions * 20;
            for (std::size_t k = 0; k < count; ++k) {
                std::string item;
                const std::size_t members = 1 + rng.next() % 8;
                if (p.cbor_top_array) {
                    put_head(item, 4, members);
                    for (std::size_t m = 0; m < members; ++m) random_item(rng, item, 6);
                } else {
                    put_head(item, 5, members);
                    for (std::size_t m = 0; m < members; ++m) {
                        put_head(item, 0, m < 10 ? m : rng.next() % 12);
                        random_item(rng, item, 6);
                    }
                }
                run_one(eng, format, format, to_hex(prefix + item), format + " random cbor " + std::to_string(k), t);
                run_one(eng, format, "geojson", to_hex(prefix + item), format + " random cbor " + std::to_string(k) + " to geojson", t);
            }
        }
    }

    std::cout << "malformed-input test: " << inputs << " vector inputs, " << t.calls << " convert calls, "
              << t.returned << " returned, " << t.refused << " refused with a named error, " << t.bad << " failed\n";
    if (inputs == 0) {
        std::cout << "no vectors found under " << packs << "\n";
        return 1;
    }
    return t.bad == 0 ? 0 : 1;
}
