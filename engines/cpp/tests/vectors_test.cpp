// Conformance runner: loads model/*.def and every pack under GT_PACKS_DIR, runs
// every conversion vector (the `expect_error` vectors, the `context` vectors and
// the "@kind" and "@complete" checks and the list checks among them), then every load vector under
// conformance/load-vectors
// (spec/vector-format.md). Every failure is reported, with its pack and vector
// name, before the counts; exit status is non-zero on any mismatch or when
// either set of vectors is empty.
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"
#include "json.hpp"
#include "util.hpp"

#ifndef GT_PACKS_DIR
#error "GT_PACKS_DIR must be defined by the build"
#endif

namespace fs = std::filesystem;
using goat_transformers::Engine;
using goat_transformers::Entity;
using goat_transformers::Value;
namespace json = goat_transformers::json;
namespace detail = goat_transformers::detail;

namespace {

std::string read_file(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
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
        int v = val(c);
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

std::string show(const Value& v) {
    switch (v.kind) {
        case Value::Kind::String: return "\"" + v.s + "\"";
        case Value::Kind::Int: return std::to_string(v.i);
        case Value::Kind::Float: return detail::format_double(v.f);
    }
    return "?";
}

// Floats compare within 1e-9; on a completed entity ("@complete") within 1e-9
// relative: |got - want| < 1e-9 * max(|got|, |want|), or equal.
bool model_matches(const Value& got, const std::string& want, bool relative) {
    switch (got.kind) {
        case Value::Kind::String: return got.s == want;
        case Value::Kind::Int: {
            std::int64_t w;
            return detail::parse_int(want, w) && w == got.i;
        }
        case Value::Kind::Float: {
            double w;
            if (!detail::parse_double(want, w)) return false;
            if (!relative) return std::fabs(w - got.f) <= 1e-9;
            return w == got.f || std::fabs(got.f - w) < 1e-9 * std::max(std::fabs(got.f), std::fabs(w));
        }
    }
    return false;
}

// One `model` check that is not "@kind" or "@complete": a model key, or a list
// check (vector-format.md, Lists in `model`): "<list>.#" is the number of items
// or "absent", and "<list>[<i>].<key>" a value of item <i>, with further steps
// for nested lists. Returns an empty string on a pass.
std::string check_model_key(const goat_transformers::Item& entity, const std::string& key, const std::string& want,
                            bool relative) {
    const goat_transformers::Item* cur = &entity;
    std::string rest = key;
    for (;;) {
        const std::size_t open = rest.find('[');
        if (open == std::string::npos) break;
        const std::size_t close = rest.find(']', open);
        std::int64_t index = -1;
        if (close == std::string::npos || !detail::parse_int(rest.substr(open + 1, close - open - 1), index) ||
            index < 0 || rest.compare(close, 2, "].") != 0)
            return "model." + key + ": not a list check this runner understands";
        auto list = cur->lists.find(rest.substr(0, open));
        if (list == cur->lists.end()) return "model." + key + ": the list " + rest.substr(0, open) + " is absent";
        if (static_cast<std::size_t>(index) >= list->second.size())
            return "model." + key + ": the list " + rest.substr(0, open) + " has " +
                   std::to_string(list->second.size()) + " items";
        cur = &list->second[static_cast<std::size_t>(index)];
        rest = rest.substr(close + 2);
    }
    if (rest.size() > 2 && rest.compare(rest.size() - 2, 2, ".#") == 0) {
        auto list = cur->lists.find(rest.substr(0, rest.size() - 2));
        if (want == "absent")
            return list == cur->lists.end() ? "" : "model." + key + " has " + std::to_string(list->second.size()) +
                                                       " items, expected the list to be absent";
        if (list == cur->lists.end()) return "model." + key + ": the list is absent, expected " + want + " items";
        std::int64_t n = -1;
        if (!detail::parse_int(want, n) || n < 0 || static_cast<std::size_t>(n) != list->second.size())
            return "model." + key + " = " + std::to_string(list->second.size()) + ", expected " + want;
        return "";
    }
    auto it = cur->fields.find(rest);
    if (it == cur->fields.end()) return "model." + key + " absent, expected " + want;
    if (!model_matches(it->second, want, relative)) return "model." + key + " = " + show(it->second) + ", expected " + want;
    return "";
}

// One load vector: a fresh engine, the limit, the modules in order, then the pack,
// stopping at the first failure. Returns an empty string on a pass.
std::string run_load_vector(const json::Value& v) {
    const json::Value* models = v.find("models");
    const json::Value* pack = v.find("pack");
    if (!models || !models->is(json::Value::Kind::Array) || !pack || !pack->is(json::Value::Kind::String))
        return "vector lacks models/pack";
    std::string want;
    if (const json::Value* x = v.find("expect_error")) {
        if (!x->is(json::Value::Kind::String)) return "expect_error is not a string";
        want = x->text;
    }

    Engine eng;
    if (const json::Value* m = v.find("max_distribution")) {
        if (m->is(json::Value::Kind::String) && m->text == "public")
            eng.set_max_distribution(goat_transformers::Distribution::Public);
        else if (m->is(json::Value::Kind::String) && m->text == "controlled")
            eng.set_max_distribution(goat_transformers::Distribution::Controlled);
        else
            return "max_distribution is not public or controlled";
    }

    std::string got, message;
    try {
        std::size_t n = 0;
        for (const auto& m : models->items) {
            if (!m.is(json::Value::Kind::String)) return "a models entry is not a string";
            eng.load_model(m.text, "models[" + std::to_string(n++) + "]");
        }
        eng.add_pack(goat_transformers::parse_pack(pack->text, "pack"));
    } catch (const goat_transformers::Error& e) {
        got = goat_transformers::error_kind_name(e.kind());
        message = e.what();
    }

    if (want.empty()) return got.empty() ? "" : "expected every load to succeed, got " + message;
    if (got.empty()) return "expected " + want + ", every load succeeded";
    if (got != want) return "expected " + want + ", got " + message;
    if (message.compare(0, want.size() + 1, want + ":") != 0)
        return "message does not begin with '" + want + ":': " + message;
    return "";
}

}  // namespace

int main() {
    const fs::path packs = GT_PACKS_DIR;
    int ran = 0, failed = 0, error_vectors = 0, kind_checks = 0, context_vectors = 0, complete_checks = 0,
        list_checks = 0;

    Engine eng;
    try {
        eng = Engine::load(packs.string());
    } catch (const std::exception& e) {
        std::cerr << "FAIL loading packs from " << packs << ": " << e.what() << "\n";
        return 1;
    }

    std::vector<fs::path> files;
    for (const auto& d : fs::directory_iterator(packs)) {
        fs::path vdir = d.path() / "vectors";
        if (!fs::is_directory(vdir)) continue;
        for (const auto& f : fs::directory_iterator(vdir))
            if (f.path().extension() == ".json") files.push_back(f.path());
    }
    std::sort(files.begin(), files.end());

    for (const auto& file : files) {
        ++ran;
        std::string label = file.parent_path().parent_path().filename().string() + "/" + file.filename().string();
        std::vector<std::string> errs;
        try {
            json::Value v = json::parse(read_file(file));
            const json::Value* from = v.find("from");
            const json::Value* to = v.find("to");
            std::string input, expect, want_error;
            if (!from || !to || !from->is(json::Value::Kind::String) || !to->is(json::Value::Kind::String))
                throw std::runtime_error("vector lacks from/to");
            if (const json::Value* n = v.find("name"))
                if (n->is(json::Value::Kind::String)) label += " (" + n->text + ")";
            if (!bytes_field(v, "input", "input_b64", input)) throw std::runtime_error("vector lacks input");
            const json::Value* xe = v.find("expect_error");
            if (xe) {
                if (!xe->is(json::Value::Kind::String) || xe->text.empty())
                    throw std::runtime_error("expect_error is not a non-empty string");
                if (v.find("expect") || v.find("expect_b64"))
                    throw std::runtime_error("vector has both expect and expect_error");
                want_error = xe->text;
            } else if (!bytes_field(v, "expect", "expect_b64", expect)) {
                throw std::runtime_error("vector lacks expect");
            }

            // `context`: the caller-supplied keys, values in string form.
            const json::Value* ctx = v.find("context");
            std::map<std::string, std::string> ctx_text;
            if (ctx) {
                if (!ctx->is(json::Value::Kind::Object)) throw std::runtime_error("context is not an object");
                ++context_vectors;
                for (std::size_t k = 0; k < ctx->keys.size(); ++k)
                    ctx_text[ctx->keys[k]] = ctx->items[k].is(json::Value::Kind::String) ? ctx->items[k].text
                                                                                         : json::write(ctx->items[k]);
            }
            auto convert = [&]() {
                if (!ctx) return eng.convert(from->text, to->text, input);
                return eng.convert_text(from->text, to->text, input, ctx_text);
            };

            if (xe) {
                ++error_vectors;
                // convert must fail, and the message must begin with the kind and a colon.
                try {
                    std::string got = convert();
                    errs.push_back("expected error " + want_error + ", convert returned: " + got);
                } catch (const goat_transformers::Error& e) {
                    const std::string message = e.what();
                    if (message.compare(0, want_error.size() + 1, want_error + ":") != 0)
                        errs.push_back("expected error " + want_error + ", got: " + message);
                }
            } else {
                std::string got = convert();
                if (got != expect) errs.push_back("convert mismatch\n    expect: " + expect + "\n    got:    " + got);
            }

            if (const json::Value* model = v.find("model")) {
                if (!model->is(json::Value::Kind::Object)) throw std::runtime_error("model is not an object");
                Entity e = eng.decode(from->text, input);
                // "@complete": true moves the checks to the entity as convert hands it
                // to the encoder: the absent keys filled from context, then the derivations.
                bool complete = false;
                if (const json::Value* c = model->find("@complete")) {
                    if (!c->is(json::Value::Kind::Bool)) throw std::runtime_error("@complete is not a boolean");
                    complete = c->b;
                }
                if (complete) {
                    ++complete_checks;
                    if (ctx) eng.apply_context(e, eng.context_from_text(ctx_text));
                    eng.complete(e);
                }
                for (std::size_t k = 0; k < model->keys.size(); ++k) {
                    const std::string& key = model->keys[k];
                    const json::Value& want = model->items[k];
                    std::string wtext = want.is(json::Value::Kind::String) ? want.text : json::write(want);
                    if (key == "@complete") continue;  // not a model key
                    if (key == "@kind") {
                        // Not a model key: the kind name decode must select.
                        ++kind_checks;
                        if (e.kind.first != from->text || e.kind.second != wtext)
                            errs.push_back("@kind = (" + e.kind.first + ", " + e.kind.second + "), expected (" +
                                           from->text + ", " + wtext + ")");
                        continue;
                    }
                    if (key.find('[') != std::string::npos ||
                        (key.size() > 2 && key.compare(key.size() - 2, 2, ".#") == 0))
                        ++list_checks;
                    const std::string err = check_model_key(e, key, wtext, complete);
                    if (!err.empty()) errs.push_back(err);
                }
            }
        } catch (const std::exception& e) {
            errs.push_back(std::string("error: ") + e.what());
        }
        if (!errs.empty()) {
            ++failed;
            std::cout << "FAIL " << label << "\n";
            for (const auto& m : errs) std::cout << "  " << m << "\n";
        }
    }

    std::vector<fs::path> load_files;
    const fs::path ldir = packs / "conformance" / "load-vectors";
    if (fs::is_directory(ldir))
        for (const auto& f : fs::directory_iterator(ldir))
            if (f.path().extension() == ".json") load_files.push_back(f.path());
    std::sort(load_files.begin(), load_files.end());

    int load_ran = 0, load_failed = 0;
    for (const auto& file : load_files) {
        ++load_ran;
        std::string label = "load-vectors/" + file.filename().string();
        std::string err;
        try {
            err = run_load_vector(json::parse(read_file(file)));
        } catch (const std::exception& e) {
            err = std::string("error: ") + e.what();
        }
        if (!err.empty()) {
            ++load_failed;
            std::cout << "FAIL " << label << "\n  " << err << "\n";
        }
    }

    std::cout << "conversion vectors: " << ran << " run, " << (ran - failed) << " passed, " << failed << " failed ("
              << error_vectors << " expect_error, " << kind_checks << " @kind checks, " << context_vectors
              << " with context, " << complete_checks << " @complete, " << list_checks << " list checks)\n";
    std::cout << "load vectors: " << load_ran << " run, " << (load_ran - load_failed) << " passed, " << load_failed
              << " failed\n";
    if (ran == 0) {
        std::cout << "no vectors found under " << packs << "\n";
        return 1;
    }
    if (load_ran == 0) {
        std::cout << "no load vectors found under " << ldir << "\n";
        return 1;
    }
    return failed == 0 && load_failed == 0 ? 0 : 1;
}
