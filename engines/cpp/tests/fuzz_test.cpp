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
