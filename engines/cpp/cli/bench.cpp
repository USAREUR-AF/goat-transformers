// goat-bench: the benchmark of the C++ engine (engine-spec.md, Version 0.25,
// ruling 2).
//
//   goat-bench [<set.json>] [--packs <dir>] [--models <dir>]
//
// Paths in the set, and the defaults (bench/set.json, packs), are read
// relative to the current directory: run it from the repository root. It
// loads, into one engine, the packs the set's vectors name (each vector's
// `from` and `to`, a format name being its pack's directory, and the packs
// their `inner` lines name, transitively, a name with no directory under the
// packs skipped: Version 0.34) and the modules they use, and times the load. Then, for each vector in order, it converts
// the input once and checks the output against `expect` (a vector that
// differs, or fails, ends the run with exit status 1), then converts it
// `iterations` times and times that. Standard output holds one line per
// vector, then one line for the load, and nothing else; failures go to
// standard error.
#include <chrono>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"
#include "json.hpp"
#include "sequential.hpp"

namespace gt = goat_transformers;
namespace json = goat_transformers::json;

namespace {

bool read_file(const std::string& path, std::string& out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    std::ostringstream ss;
    ss << in.rdbuf();
    out = ss.str();
    return true;
}

bool base64_decode(const std::string& in, std::string& out) {
    auto val = [](char c) -> int {
        if (c >= 'A' && c <= 'Z') return c - 'A';
        if (c >= 'a' && c <= 'z') return c - 'a' + 26;
        if (c >= '0' && c <= '9') return c - '0' + 52;
        if (c == '+' || c == '-') return 62;
        if (c == '/' || c == '_') return 63;
        return -1;
    };
    out.clear();
    unsigned buf = 0;
    int bits = 0;
    for (char c : in) {
        if (c == '=' || c == '\n' || c == '\r' || c == ' ') continue;
        const int v = val(c);
        if (v < 0) return false;
        buf = (buf << 6) | static_cast<unsigned>(v);
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out += static_cast<char>((buf >> bits) & 0xFF);
        }
    }
    return true;
}

bool bytes_field(const json::Value& v, const char* text_key, const char* b64_key, std::string& out) {
    if (const json::Value* t = v.find(text_key)) {
        if (!t->is(json::Value::Kind::String)) return false;
        out = t->text;
        return true;
    }
    if (const json::Value* b = v.find(b64_key)) return b->is(json::Value::Kind::String) && base64_decode(b->text, out);
    return false;
}

struct BenchVector {
    std::string path;  // as in the set
    std::string from, to, input, expect;
    bool has_context = false;
    std::map<std::string, std::string> context;
};

std::string json_string(const std::string& s) { return json::quote(s); }

int fail(const std::string& why) {
    std::cerr << "goat-bench: " << why << "\n";
    return 1;
}

}  // namespace

int main(int argc, char** argv) {
    std::string set_path = "bench/set.json", packs_dir = "packs", models_dir;
    bool have_set = false;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        if ((a == "--packs" || a == "--models") && i + 1 < argc) {
            (a == "--packs" ? packs_dir : models_dir) = argv[++i];
        } else if (!a.empty() && a[0] != '-' && !have_set) {
            set_path = a;
            have_set = true;
        } else {
            std::cerr << "usage: goat-bench [<set.json>] [--packs <dir>] [--models <dir>]\n";
            return 2;
        }
    }

    // The set and its vectors are read before anything is timed.
    std::uint64_t iterations = 0;
    std::vector<BenchVector> vectors;
    std::vector<std::string> pack_names;
    try {
        std::string text;
        if (!read_file(set_path, text)) return fail("cannot read " + set_path);
        const json::Value set = json::parse(text);
        const json::Value* it = set.find("iterations");
        const json::Value* list = set.find("vectors");
        if (!it || !it->is(json::Value::Kind::Number) || !list || !list->is(json::Value::Kind::Array))
            return fail(set_path + ": needs a number `iterations` and an array `vectors`");
        try {
            iterations = std::stoull(it->text);
        } catch (const std::exception&) {
            return fail(set_path + ": `iterations` is not a whole number");
        }
        if (iterations == 0) return fail(set_path + ": `iterations` is 0");
        auto add_pack = [&](const std::string& n) {
            for (const auto& p : pack_names)
                if (p == n) return;
            pack_names.push_back(n);
        };
        for (const auto& entry : list->items) {
            if (!entry.is(json::Value::Kind::String)) return fail(set_path + ": a vector path is not a string");
            BenchVector bv;
            bv.path = entry.text;
            std::string vtext;
            if (!read_file(bv.path, vtext)) return fail("cannot read " + bv.path);
            const json::Value v = json::parse(vtext);
            const json::Value* from = v.find("from");
            const json::Value* to = v.find("to");
            if (!from || !to || !from->is(json::Value::Kind::String) || !to->is(json::Value::Kind::String))
                return fail(bv.path + ": lacks from or to");
            bv.from = from->text;
            bv.to = to->text;
            if (!bytes_field(v, "input", "input_b64", bv.input)) return fail(bv.path + ": lacks input");
            if (!bytes_field(v, "expect", "expect_b64", bv.expect))
                return fail(bv.path + ": lacks expect (a benchmark vector is a conversion with an expected output)");
            if (const json::Value* ctx = v.find("context")) {
                if (!ctx->is(json::Value::Kind::Object)) return fail(bv.path + ": context is not an object");
                bv.has_context = true;
                for (std::size_t k = 0; k < ctx->keys.size(); ++k)
                    bv.context[ctx->keys[k]] = ctx->items[k].is(json::Value::Kind::String)
                                                   ? ctx->items[k].text
                                                   : json::write(ctx->items[k]);
            }
            add_pack(bv.from);
            add_pack(bv.to);
            vectors.push_back(std::move(bv));
        }
    } catch (const json::ParseError& e) {
        return fail(std::string("JSON: ") + e.what());
    }
    // v0.34: the packs the `inner` lines of the loaded packs name, and theirs.
    for (std::size_t k = 0; k < pack_names.size(); ++k) {
        std::string text;
        if (!read_file(packs_dir + "/" + pack_names[k] + "/pack.def", text)) continue;
        std::istringstream lines(text);
        std::string line, err;
        while (std::getline(lines, line)) {
            std::vector<std::string> t;
            if (!goat_transformers::detail::tokenize_line(line, t, err) || (t.size() != 2 && t.size() != 3) || t[0] != "inner") continue;
            std::string probe;
            if (t[1].find('/') != std::string::npos || t[1] == "." || t[1] == ".." ||
                !read_file(packs_dir + "/" + t[1] + "/pack.def", probe))
                continue;  // no pack directory of that name: its use is unknown-format
            bool listed = false;
            for (const auto& n : pack_names) listed = listed || n == t[1];
            if (!listed) pack_names.push_back(t[1]);
        }
    }

    using clock = std::chrono::steady_clock;
    auto ns_since = [](clock::time_point t0) {
        return static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(clock::now() - t0).count());
    };

    gt::Engine eng;
    std::uint64_t load_ns = 0;
    try {
        const auto t0 = clock::now();
        eng = gt::Engine::load_packs(packs_dir, pack_names, models_dir);
        load_ns = ns_since(t0);
    } catch (const std::exception& e) {
        return fail(std::string("load: ") + e.what());
    }

    std::string out;
    for (const auto& bv : vectors) {
        auto convert = [&]() {
            return bv.has_context ? eng.convert_text(bv.from, bv.to, bv.input, bv.context)
                                  : eng.convert(bv.from, bv.to, bv.input);
        };
        std::uint64_t ns = 0;
        try {
            if (convert() != bv.expect) return fail(bv.path + ": the output differs from expect");
            std::size_t sink = 0;
            const auto t0 = clock::now();
            for (std::uint64_t n = 0; n < iterations; ++n) sink += convert().size();
            ns = ns_since(t0);
            if (sink != bv.expect.size() * iterations) return fail(bv.path + ": an output changed while timed");
        } catch (const std::exception& e) {
            return fail(bv.path + ": " + e.what());
        }
        out += "{\"vector\": " + json_string(bv.path) + ", \"iterations\": " + std::to_string(iterations) +
               ", \"ns_per_op\": " + std::to_string(ns / iterations) + "}\n";
    }
    out += "{\"load\": " + std::to_string(pack_names.size()) + ", \"ns\": " + std::to_string(load_ns) + "}\n";
    std::cout << out;
    return 0;
}
