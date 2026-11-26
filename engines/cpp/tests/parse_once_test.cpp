// What an engine keeps (engine-spec.md 0.25, ruling 1): one instance, loaded
// once, keeps the parsed packs and the layouts computed from them, and nothing
// a conversion does is seen by another.
//
// Every conversion vector of every pack (with no `max_items`, an engine-wide
// setting) gives a result: the output or the error message of `convert`, and
// the entity `decode` gives for the input, or its error message. Then:
//
//   1. fresh: for each vector of bench/set.json, a new instance that loaded
//      only that vector's packs gives the result the shared instance gave
//      (ruling 1b);
//   2. order: the shared instance, after every vector was converted once, gives
//      the same result for every vector in reverse order, each conversion
//      after a failing one (the input cut in half, and an unknown format), so
//      a failure leaves nothing behind (1b);
//   3. threads: eight threads convert every vector on the shared instance at
//      once, each from another starting point, and every result is the one of
//      the first pass (1c).
//
// The first pass is also checked against each vector's `expect` or
// `expect_error`, as the conformance runner does.
#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "goat_transformers/engine.hpp"
#include "json.hpp"
#include "sequential.hpp"

#ifndef GT_PACKS_DIR
#error "GT_PACKS_DIR must be defined by the build"
#endif
#ifndef GT_REPO_ROOT
#error "GT_REPO_ROOT must be defined by the build"
#endif

namespace fs = std::filesystem;
namespace gt = goat_transformers;
namespace json = goat_transformers::json;

namespace {

std::string read_file(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

// The packs named and, transitively, the packs their `inner` lines name, a
// name with no pack directory skipped (engine-spec.md 0.34, Vectors).
std::vector<std::string> with_inner(const fs::path& packs, std::vector<std::string> names) {
    for (std::size_t k = 0; k < names.size(); ++k) {
        const fs::path def = packs / names[k] / "pack.def";
        if (!fs::is_regular_file(def)) continue;
        std::istringstream lines(read_file(def));
        std::string line, err;
        while (std::getline(lines, line)) {
            std::vector<std::string> t;
            if (!goat_transformers::detail::tokenize_line(line, t, err) || (t.size() != 2 && t.size() != 3) || t[0] != "inner") continue;
            if (t[1].find('/') != std::string::npos || !fs::is_regular_file(packs / t[1] / "pack.def")) continue;
            if (std::find(names.begin(), names.end(), t[1]) == names.end()) names.push_back(t[1]);
        }
    }
    return names;
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

struct Vec {
    std::string label;   // <pack>/<file>
    std::string path;    // as bench/set.json writes it: packs/<pack>/vectors/<file>
    std::string from, to, input;
    bool has_context = false;
    std::map<std::string, std::string> context;
    bool has_expect = false, has_error = false;
    std::string expect, error;
};

// Every model value bit for bit: a float as its exact hexadecimal form.
void dump_item(const gt::Item& it, std::string& out) {
    out += "{kind=" + it.kind.first + "/" + it.kind.second;
    for (const auto& kv : it.fields) {
        out += ";" + kv.first + "=";
        const gt::Value& v = kv.second;
        char buf[64];
        switch (v.kind) {
            case gt::Value::Kind::String: out += "s:" + v.s; break;
            case gt::Value::Kind::Int: out += "i:" + std::to_string(v.i); break;
            case gt::Value::Kind::Float:
                std::snprintf(buf, sizeof buf, "%a", v.f);
                out += std::string("f:") + buf;
                break;
        }
    }
    for (const auto& kv : it.lists) {
        out += ";" + kv.first + "[" + std::to_string(kv.second.size()) + "]";
        for (const auto& item : kv.second) dump_item(item, out);
    }
    out += "}";
}

std::string dump_entity(const gt::Entity& e) {
    std::string out;
    dump_item(e, out);
    for (const auto& r : e.residue)
        out += "|" + r.format + "|" + r.locator + "|" + r.value + (r.structured ? "|s" : "|t");
    return out;
}

// The result of one vector on `eng`: what convert gives, then what decode gives.
std::string result(const gt::Engine& eng, const Vec& v) {
    std::string out;
    try {
        out = "ok:" + (v.has_context ? eng.convert_text(v.from, v.to, v.input, v.context)
                                     : eng.convert(v.from, v.to, v.input));
    } catch (const gt::Error& e) {
        out = std::string("error:") + e.what();
    }
    out += "\n--decode--\n";
    try {
        out += dump_entity(eng.decode(v.from, v.input));
    } catch (const gt::Error& e) {
        out += std::string("error:") + e.what();
    }
    return out;
}

// A conversion that fails: the input cut in half, or a format no pack defines.
void fail_once(const gt::Engine& eng, const Vec& v, std::size_t n) {
    try {
        if (n % 2 == 0) (void)eng.convert(v.from, v.to, v.input.substr(0, v.input.size() / 2));
        else (void)eng.convert(v.from, "no-such-format", v.input);
    } catch (const gt::Error&) {
    }
}

}  // namespace

int main() {
    const fs::path packs = GT_PACKS_DIR;
    const fs::path root = GT_REPO_ROOT;

    std::vector<Vec> vecs;
    {
        std::vector<fs::path> files;
        for (const auto& d : fs::directory_iterator(packs)) {
            const fs::path vdir = d.path() / "vectors";
            if (!fs::is_directory(vdir)) continue;
            for (const auto& f : fs::directory_iterator(vdir))
                if (f.path().extension() == ".json") files.push_back(f.path());
        }
        std::sort(files.begin(), files.end());
        for (const auto& file : files) {
            json::Value j;
            try {
                j = json::parse(read_file(file));
            } catch (const json::ParseError&) {
                continue;  // the conformance runner reports it
            }
            const json::Value* from = j.find("from");
            const json::Value* to = j.find("to");
            if (!from || !to || !from->is(json::Value::Kind::String) || !to->is(json::Value::Kind::String)) continue;
            if (j.find("max_items")) continue;  // an engine-wide setting
            Vec v;
            v.label = file.parent_path().parent_path().filename().string() + "/" + file.filename().string();
            v.path = "packs/" + v.label.substr(0, v.label.find('/')) + "/vectors/" + file.filename().string();
            v.from = from->text;
            v.to = to->text;
            if (!bytes_field(j, "input", "input_b64", v.input)) continue;
            if (const json::Value* ctx = j.find("context")) {
                if (!ctx->is(json::Value::Kind::Object)) continue;
                v.has_context = true;
                for (std::size_t k = 0; k < ctx->keys.size(); ++k)
                    v.context[ctx->keys[k]] =
                        ctx->items[k].is(json::Value::Kind::String) ? ctx->items[k].text : json::write(ctx->items[k]);
            }
            if (j.find("run") || j.find("expect_results")) {
                // v0.92: an expectation on convert_run; convert's result is only compared with itself.
            } else if (const json::Value* x = j.find("expect_error")) {
                v.has_error = x->is(json::Value::Kind::String);
                if (v.has_error) v.error = x->text;
            } else {
                v.has_expect = bytes_field(j, "expect", "expect_b64", v.expect);
            }
            vecs.push_back(std::move(v));
        }
    }
    if (vecs.empty()) {
        std::cerr << "FAIL no vectors under " << packs << "\n";
        return 1;
    }

    gt::Engine eng;
    try {
        eng = gt::Engine::load(packs.string());
    } catch (const std::exception& e) {
        std::cerr << "FAIL loading packs: " << e.what() << "\n";
        return 1;
    }
    const gt::Engine& shared = eng;

    int failures = 0;
    auto fail = [&](const std::string& what) {
        if (++failures <= 20) std::cout << "FAIL " << what << "\n";
    };

    // The first pass, and the vectors' own expectations.
    std::vector<std::string> first(vecs.size());
    for (std::size_t k = 0; k < vecs.size(); ++k) {
        first[k] = result(shared, vecs[k]);
        const Vec& v = vecs[k];
        const std::string conv = first[k].substr(0, first[k].find("\n--decode--\n"));
        if (v.has_expect && conv != "ok:" + v.expect) fail(v.label + ": first pass differs from expect");
        if (v.has_error && conv.compare(0, 6 + v.error.size() + 1, "error:" + v.error + ":") != 0)
            fail(v.label + ": first pass is not " + v.error);
    }

    // 1. A fresh instance per vector of the benchmark set.
    int fresh = 0;
    try {
        const json::Value set = json::parse(read_file(root / "bench" / "set.json"));
        const json::Value* list = set.find("vectors");
        if (!list || !list->is(json::Value::Kind::Array)) throw std::runtime_error("bench/set.json has no vectors");
        for (const auto& entry : list->items) {
            std::size_t k = 0;
            while (k < vecs.size() && vecs[k].path != entry.text) ++k;
            if (k == vecs.size()) {
                fail("fresh: " + entry.text + " is not a vector of the packs");
                continue;
            }
            const gt::Engine one = gt::Engine::load_packs(packs.string(), with_inner(packs, {vecs[k].from, vecs[k].to}));
            if (result(one, vecs[k]) != first[k]) fail("fresh: " + vecs[k].label + " differs on a new instance");
            ++fresh;
        }
    } catch (const std::exception& e) {
        fail(std::string("fresh: ") + e.what());
    }

    // 2. Reverse order, each after a failing conversion.
    for (std::size_t n = 0; n < vecs.size(); ++n) {
        const std::size_t k = vecs.size() - 1 - n;
        fail_once(shared, vecs[(k * 7 + 3) % vecs.size()], n);
        if (result(shared, vecs[k]) != first[k]) fail("order: " + vecs[k].label + " differs after other conversions");
    }

    // 3. Eight threads at once, each from another starting point, failures interleaved.
    const unsigned kThreads = 8;
    std::vector<int> bad(kThreads, 0);  // each thread writes only its own entry
    std::vector<std::string> first_bad(kThreads);
    {
        std::vector<std::thread> pool;
        for (unsigned t = 0; t < kThreads; ++t)
            pool.emplace_back([&, t]() {
                const std::size_t start = vecs.size() * t / kThreads;
                for (std::size_t n = 0; n < vecs.size(); ++n) {
                    const std::size_t k = (start + n) % vecs.size();
                    if (n % 5 == t % 5) fail_once(shared, vecs[(k + t) % vecs.size()], n + t);
                    if (result(shared, vecs[k]) != first[k] && bad[t]++ == 0) first_bad[t] = vecs[k].label;
                }
            });
        for (auto& th : pool) th.join();
    }
    for (unsigned t = 0; t < kThreads; ++t)
        if (bad[t])
            fail("threads: thread " + std::to_string(t) + ": " + std::to_string(bad[t]) + " results differ, the first " +
                 first_bad[t]);

    std::cout << "parse once: " << vecs.size() << " vectors; " << fresh << " on a fresh instance; " << vecs.size()
              << " in reverse order after failures; " << kThreads << " threads x " << vecs.size()
              << " conversions at once; " << failures << " failures\n";
    return failures == 0 ? 0 : 1;
}
