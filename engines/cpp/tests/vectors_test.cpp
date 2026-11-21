// Conformance runner: loads model/*.def and every pack under GT_PACKS_DIR, runs
// every conversion vector (the `expect_error` vectors, the `context` vectors and
// the "@kind" and "@complete" checks and the list checks among them, each with
// its `max_items`), then every load vector under conformance/load-vectors and
// every capability vector under conformance/capability-vectors
// (spec/vector-format.md). Every failure is reported, with its pack and vector
// name, before the counts; exit status is non-zero on any mismatch or when
// either set of vectors is empty.
//
// In a build with fewer wires (engine-spec.md 0.24) it is the reduced-build
// check: it loads only the packs on the build's wires, runs only the vectors
// whose formats, and whose packs, are all on them, and requires every pack on a
// wire of the specification the build lacks to be refused with unknown-wire,
// with a message that names the wire and says this build does not have it.
#include <algorithm>
#include <cstdint>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <sstream>
#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"
#include "json.hpp"
#include "sequential.hpp"
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

// A vector whose `model` holds a value its grammar refuses is invalid (0.11
// ruling 2c): a member named by a model key or an item path is read as that
// key's declared type, by integer text (2a) or number text (2b).
struct InvalidVector : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// Floats compare within 1e-9; on a completed entity ("@complete") within 1e-9
// relative: |got - want| < 1e-9 * max(|got|, |want|), or within 1e-7 absolute
// (Version 0.16), or equal.
bool model_matches(const Value& got, const std::string& want, bool relative) {
    switch (got.kind) {
        case Value::Kind::String: return got.s == want;
        case Value::Kind::Int: {
            std::int64_t w;
            return detail::parse_int_text(want, w) && w == got.i;
        }
        case Value::Kind::Float: {
            double w;
            if (!detail::parse_number_text(want, w)) return false;
            if (!relative) return std::fabs(w - got.f) <= 1e-9;
            return w == got.f || std::fabs(got.f - w) < 1e-9 * std::max(std::fabs(got.f), std::fabs(w)) ||
                   std::fabs(got.f - w) < 1e-7;
        }
    }
    return false;
}

// One `model` check that is not "@kind" or "@complete": a model key, or a list
// check (vector-format.md, Lists in `model`): "<list>.#" is the number of items
// or "absent", and "<list>[<i>].<key>" a value of item <i>, with further steps
// for nested lists; "<list>[<i>].@kind" is the kind item <i> recorded (0.8).
// Returns an empty string on a pass.
std::string check_model_key(const Engine& eng, const goat_transformers::Item& entity, const std::string& format,
                            const std::string& key, const std::string& want, bool relative) {
    const goat_transformers::Item* cur = &entity;
    // The value is read by the grammar of what the member names (0.11 ruling 2c).
    {
        std::string last = key;
        const std::size_t close = key.rfind("].");
        if (close != std::string::npos) last = key.substr(close + 2);
        if (last.size() > 2 && last.compare(last.size() - 2, 2, ".#") == 0) {
            std::uint64_t n = 0;
            if (want != "absent" && !detail::parse_unsigned_text(want, n))
                throw InvalidVector("model." + key + ": '" + want + "' is not an unsigned decimal integer or 'absent'");
        } else if (last != "@kind") {
            if (const goat_transformers::ModelKey* k = eng.find_key(last)) {
                std::int64_t i = 0;
                double d = 0;
                if (k->type == goat_transformers::KeyType::Int && !detail::parse_int_text(want, i))
                    throw InvalidVector("model." + key + ": '" + want + "' is not integer text");
                if (k->type == goat_transformers::KeyType::Float && !detail::parse_number_text(want, d))
                    throw InvalidVector("model." + key + ": '" + want + "' is not number text");
            }
        }
    }
    std::string rest = key;
    for (;;) {
        const std::size_t open = rest.find('[');
        if (open == std::string::npos) break;
        const std::size_t close = rest.find(']', open);
        std::uint64_t index = 0;
        if (close == std::string::npos || !detail::parse_unsigned_text(rest.substr(open + 1, close - open - 1), index) ||
            rest.compare(close, 2, "].") != 0)
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
        std::uint64_t n = 0;
        if (!detail::parse_unsigned_text(want, n) || n != list->second.size())
            return "model." + key + " = " + std::to_string(list->second.size()) + ", expected " + want;
        return "";
    }
    if (rest == "@kind") {
        // Not a model key: the kind the item recorded when it was decoded (0.8).
        // It fails for an item that recorded no kind.
        if (cur->kind.second.empty()) return "model." + key + ": the item recorded no kind, expected " + want;
        if (cur->kind.first != format || cur->kind.second != want)
            return "model." + key + " = (" + cur->kind.first + ", " + cur->kind.second + "), expected (" + format +
                   ", " + want + ")";
        return "";
    }
    auto it = cur->fields.find(rest);
    if (it == cur->fields.end()) return "model." + key + " absent, expected " + want;
    if (!model_matches(it->second, want, relative)) return "model." + key + " = " + show(it->second) + ", expected " + want;
    return "";
}

// One "@absent" entry (0.9): a model key the entity lacks, "<list>[<i>].<key>"
// for an item that exists and lacks the key, or a list name the entity lacks
// (as "<list>.#": "absent"). Returns an empty string on a pass.
std::string check_absent_key(const goat_transformers::Item& entity, const std::string& key) {
    const goat_transformers::Item* cur = &entity;
    std::string rest = key;
    for (;;) {
        const std::size_t open = rest.find('[');
        if (open == std::string::npos) break;
        const std::size_t close = rest.find(']', open);
        std::uint64_t index = 0;
        if (close == std::string::npos || !detail::parse_unsigned_text(rest.substr(open + 1, close - open - 1), index) ||
            rest.compare(close, 2, "].") != 0)
            return "@absent " + key + ": not an entry this runner understands";
        auto list = cur->lists.find(rest.substr(0, open));
        if (list == cur->lists.end()) return "@absent " + key + ": the list " + rest.substr(0, open) + " is absent";
        if (static_cast<std::size_t>(index) >= list->second.size())
            return "@absent " + key + ": the list " + rest.substr(0, open) + " has " +
                   std::to_string(list->second.size()) + " items";
        cur = &list->second[static_cast<std::size_t>(index)];
        rest = rest.substr(close + 2);
    }
    auto it = cur->fields.find(rest);
    if (it != cur->fields.end()) return "@absent " + key + ": present with the value " + show(it->second);
    auto list = cur->lists.find(rest);
    if (list != cur->lists.end())
        return "@absent " + key + ": the list is present with " + std::to_string(list->second.size()) + " items";
    return "";
}

// One load vector: a fresh engine, the limit, the modules in order, then the
// pack, or each pack of `packs` in order (0.11), stopping at the first
// failure. Returns an empty string on a pass.
std::string run_load_vector(const json::Value& v) {
    const json::Value* models = v.find("models");
    const json::Value* pack = v.find("pack");
    const json::Value* packs = v.find("packs");
    if (!models || !models->is(json::Value::Kind::Array)) return "vector lacks models";
    if ((pack != nullptr) == (packs != nullptr)) return "vector has neither or both of pack and packs";
    std::vector<std::string> pack_texts;
    if (pack) {
        if (!pack->is(json::Value::Kind::String)) return "pack is not a string";
        pack_texts.push_back(pack->text);
    } else {
        if (!packs->is(json::Value::Kind::Array)) return "packs is not an array";
        for (const auto& p : packs->items) {
            if (!p.is(json::Value::Kind::String)) return "a packs entry is not a string";
            pack_texts.push_back(p.text);
        }
    }
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
        n = 0;
        for (const auto& text : pack_texts)
            eng.add_pack(goat_transformers::parse_pack(text, pack ? "pack" : "packs[" + std::to_string(n++) + "]"));
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

// One capability vector (0.11 ruling 6): the report of `from` against `to`,
// with the engine that loaded every pack. Returns an empty string on a pass.
std::string run_capability_vector(const Engine& eng, const json::Value& v) {
    const json::Value* from = v.find("from");
    const json::Value* to = v.find("to");
    const json::Value* grade = v.find("grade");
    if (!from || !to || !grade || !from->is(json::Value::Kind::String) || !to->is(json::Value::Kind::String) ||
        !grade->is(json::Value::Kind::String))
        return "vector lacks from, to or grade";
    auto entries = [&](const char* name, std::vector<std::string>& out) {
        const json::Value* a = v.find(name);
        if (!a || !a->is(json::Value::Kind::Array)) return false;
        for (const auto& e : a->items) {
            if (!e.is(json::Value::Kind::String)) return false;
            out.push_back(e.text);
        }
        return true;
    };
    std::vector<std::string> carried, dropped;
    if (!entries("carried", carried) || !entries("dropped", dropped)) return "carried or dropped is not an array of strings";
    const goat_transformers::Capability c = eng.capability(from->text, to->text);
    auto join = [](const std::vector<std::string>& xs) {
        std::string out = "[";
        for (std::size_t k = 0; k < xs.size(); ++k) out += (k ? ", " : "") + xs[k];
        return out + "]";
    };
    std::string err;
    if (c.grade != grade->text) err += "grade " + c.grade + ", expected " + grade->text + "\n  ";
    if (c.carried != carried) err += "carried " + join(c.carried) + ", expected " + join(carried) + "\n  ";
    if (c.dropped != dropped) err += "dropped " + join(c.dropped) + ", expected " + join(dropped) + "\n  ";
    return err;
}

// The first `format` and `wire` values of a pack text, read line by line.
void header_values(const std::string& text, std::string& format, std::vector<std::string>& wires) {
    std::istringstream in(text);
    std::string line, err;
    while (std::getline(in, line)) {
        std::vector<std::string> t;
        if (!detail::tokenize_line(line, t, err) || t.size() < 2) continue;
        if (t[0] == "format" && format.empty()) format = t[1];
        if (t[0] == "wire") wires.push_back(t[1]);
    }
}

const std::vector<std::string> kSpecWires = {"xml", "geojson", "json", "bits", "protobuf", "text", "tlv"};

// A wire of the specification that this build lacks, or an empty string.
std::string lacked_wire(const std::vector<std::string>& wires, const std::vector<std::string>& built) {
    for (const auto& w : wires)
        if (std::find(kSpecWires.begin(), kSpecWires.end(), w) != kSpecWires.end() &&
            std::find(built.begin(), built.end(), w) == built.end())
            return w;
    return "";
}

}  // namespace

int main() {
    const fs::path packs = GT_PACKS_DIR;
    int ran = 0, failed = 0, error_vectors = 0, kind_checks = 0, context_vectors = 0, complete_checks = 0,
        list_checks = 0, absent_checks = 0, limit_vectors = 0;

    const std::vector<std::string> built = goat_transformers::built_wires();
    const bool reduced = built.size() != kSpecWires.size();
    // Reduced build: the formats of the packs on a wire it lacks, whose vectors
    // are not run, and the refusals of those packs.
    std::set<std::string> lacked_formats;
    int skipped = 0, refused = 0, refusal_failed = 0;
    std::map<std::string, int> refused_by_wire;

    Engine eng;
    try {
        if (!reduced) {
            eng = Engine::load(packs.string());
        } else {
            std::string list;
            for (const auto& w : built) list += (list.empty() ? "" : ",") + w;
            std::cout << "reduced build: wires " << list << "\n";
            std::vector<fs::path> dirs;
            for (const auto& d : fs::directory_iterator(packs))
                if (d.is_directory() && fs::is_regular_file(d.path() / "pack.def")) dirs.push_back(d.path());
            std::sort(dirs.begin(), dirs.end());
            std::vector<std::string> names;
            for (const auto& d : dirs) {
                const std::string text = read_file(d / "pack.def");
                std::string format;
                std::vector<std::string> wires;
                header_values(text, format, wires);
                const std::string wire = lacked_wire(wires, built);
                if (wire.empty()) {
                    names.push_back(d.filename().string());
                    continue;
                }
                lacked_formats.insert(format);
                // 0.24 ruling 1c: unknown-wire, the wire named, and this build's lack said.
                std::string got;
                try {
                    (void)goat_transformers::parse_pack(text, (d / "pack.def").string());
                    got = "the pack loaded";
                } catch (const goat_transformers::Error& e) {
                    const std::string m = e.what();
                    if (e.kind() != goat_transformers::ErrorKind::UnknownWire || m.compare(0, 13, "unknown-wire:") != 0)
                        got = "expected unknown-wire, got " + m;
                    else if (m.find("'" + wire + "'") == std::string::npos ||
                             m.find("this build does not have") == std::string::npos)
                        got = "the message does not name the wire and say this build lacks it: " + m;
                    else if (refused_by_wire[wire] == 0)
                        std::cout << "unknown-wire load (" << wire << "): " << m << "\n";
                }
                if (got.empty()) {
                    ++refused;
                    ++refused_by_wire[wire];
                } else {
                    ++refusal_failed;
                    std::cout << "FAIL " << d.filename().string() << "/pack.def\n  " << got << "\n";
                }
            }
            // Every module, as Engine::load, then the packs on the build's wires.
            eng = Engine::load_tool(packs.string(), (packs / ".." / "model").string(), &names);
            std::cout << "packs loaded: " << names.size() << "\n";
            // 0.24 ruling 1e: a format that did not load is unknown-format.
            for (const auto& f : lacked_formats) {
                std::string got = "convert returned";
                try {
                    (void)eng.convert(f, f, "");
                } catch (const goat_transformers::Error& e) {
                    got = e.kind() == goat_transformers::ErrorKind::UnknownFormat ? "" : e.what();
                }
                if (!got.empty()) {
                    ++refusal_failed;
                    std::cout << "FAIL convert of the refused format " << f << ": expected unknown-format, " << got
                              << "\n";
                }
            }
        }
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
            if (lacked_formats.count(from->text) || lacked_formats.count(to->text)) {
                --ran;
                ++skipped;
                continue;
            }
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

            // `max_items` (0.11 ruling 7b): the limit on list items for this vector.
            eng.set_max_items(Engine::kDefaultMaxItems);
            if (const json::Value* m = v.find("max_items")) {
                std::uint64_t n = 0;
                if (!m->is(json::Value::Kind::Number) || !detail::parse_unsigned_text(m->text, n))
                    throw InvalidVector("max_items is not an integer of 0 or more");
                eng.set_max_items(n);
                ++limit_vectors;
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
                    if (key == "@absent") {
                        // Not a model key: keys the entity must not have (0.9). A listed
                        // key that is also a member of `model` makes the vector invalid.
                        ++absent_checks;
                        if (!want.is(json::Value::Kind::Array)) {
                            errs.push_back("invalid vector: @absent is not an array");
                            continue;
                        }
                        for (const auto& entry : want.items) {
                            if (!entry.is(json::Value::Kind::String)) {
                                errs.push_back("invalid vector: an @absent entry is not a string");
                                continue;
                            }
                            if (model->find(entry.text)) {
                                errs.push_back("invalid vector: " + entry.text + " is in @absent and in model");
                                continue;
                            }
                            const std::string err = check_absent_key(e, entry.text);
                            if (!err.empty()) errs.push_back(err);
                        }
                        continue;
                    }
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
                    if (key.size() > 7 && key.compare(key.size() - 7, 7, "].@kind") == 0) ++kind_checks;
                    const std::string err = check_model_key(eng, e, from->text, key, wtext, complete);
                    if (!err.empty()) errs.push_back(err);
                }
            }
        } catch (const InvalidVector& e) {
            errs.push_back(std::string("invalid vector: ") + e.what());
        } catch (const std::exception& e) {
            errs.push_back(std::string("error: ") + e.what());
        }
        if (!errs.empty()) {
            ++failed;
            std::cout << "FAIL " << label << "\n";
            for (const auto& m : errs) std::cout << "  " << m << "\n";
        }
    }

    eng.set_max_items(Engine::kDefaultMaxItems);

    std::vector<fs::path> load_files;
    const fs::path ldir = packs / "conformance" / "load-vectors";
    if (fs::is_directory(ldir))
        for (const auto& f : fs::directory_iterator(ldir))
            if (f.path().extension() == ".json") load_files.push_back(f.path());
    std::sort(load_files.begin(), load_files.end());

    int load_ran = 0, load_failed = 0, load_skipped = 0;
    for (const auto& file : load_files) {
        ++load_ran;
        std::string label = "load-vectors/" + file.filename().string();
        std::string err;
        try {
            const json::Value v = json::parse(read_file(file));
            if (reduced) {
                // A pack text on a wire this build lacks is not this build's case.
                std::vector<std::string> wires;
                std::string format;
                if (const json::Value* one = v.find("pack"))
                    if (one->is(json::Value::Kind::String)) header_values(one->text, format, wires);
                if (const json::Value* many = v.find("packs"))
                    for (const auto& t : many->items)
                        if (t.is(json::Value::Kind::String)) header_values(t.text, format, wires);
                if (!lacked_wire(wires, built).empty()) {
                    --load_ran;
                    ++load_skipped;
                    continue;
                }
            }
            err = run_load_vector(v);
        } catch (const std::exception& e) {
            err = std::string("error: ") + e.what();
        }
        if (!err.empty()) {
            ++load_failed;
            std::cout << "FAIL " << label << "\n  " << err << "\n";
        }
    }

    std::vector<fs::path> cap_files;
    const fs::path cdir = packs / "conformance" / "capability-vectors";
    if (fs::is_directory(cdir))
        for (const auto& f : fs::directory_iterator(cdir))
            if (f.path().extension() == ".json") cap_files.push_back(f.path());
    std::sort(cap_files.begin(), cap_files.end());

    int cap_ran = 0, cap_failed = 0, cap_skipped = 0;
    for (const auto& file : cap_files) {
        ++cap_ran;
        std::string label = "capability-vectors/" + file.filename().string();
        std::string err;
        try {
            const json::Value v = json::parse(read_file(file));
            const json::Value* from = v.find("from");
            const json::Value* to = v.find("to");
            if ((from && from->is(json::Value::Kind::String) && lacked_formats.count(from->text)) ||
                (to && to->is(json::Value::Kind::String) && lacked_formats.count(to->text))) {
                --cap_ran;
                ++cap_skipped;
                continue;
            }
            err = run_capability_vector(eng, v);
        } catch (const std::exception& e) {
            err = std::string("error: ") + e.what();
        }
        if (!err.empty()) {
            ++cap_failed;
            std::cout << "FAIL " << label << "\n  " << err << "\n";
        }
    }

    std::cout << "conversion vectors: " << ran << " run, " << (ran - failed) << " passed, " << failed << " failed ("
              << error_vectors << " expect_error, " << kind_checks << " @kind checks, " << context_vectors
              << " with context, " << complete_checks << " @complete, " << list_checks << " list checks, "
              << absent_checks << " @absent, " << limit_vectors << " with max_items)\n";
    std::cout << "load vectors: " << load_ran << " run, " << (load_ran - load_failed) << " passed, " << load_failed
              << " failed\n";
    std::cout << "capability vectors: " << cap_ran << " run, " << (cap_ran - cap_failed) << " passed, " << cap_failed
              << " failed\n";
    if (reduced) {
        std::cout << "skipped, a format or pack on a wire this build lacks: " << skipped << " conversion, "
                  << load_skipped << " load, " << cap_skipped << " capability vectors\n";
        std::cout << "packs on a wire this build lacks: " << refused << " refused with unknown-wire (";
        bool first = true;
        for (const auto& w : kSpecWires) {
            if (std::find(built.begin(), built.end(), w) != built.end()) continue;
            std::cout << (first ? "" : ", ") << w << " " << refused_by_wire[w];
            first = false;
        }
        std::cout << "), each then unknown-format in convert; " << refusal_failed << " failed\n";
        for (const auto& w : kSpecWires)
            if (std::find(built.begin(), built.end(), w) == built.end() && refused_by_wire[w] == 0) {
                std::cout << "FAIL no pack on wire " << w << " was refused: nothing pins ruling 1c for it\n";
                ++refusal_failed;
            }
        if (refusal_failed != 0) return 1;
    }
    if (ran == 0) {
        std::cout << "no vectors found under " << packs << "\n";
        return 1;
    }
    if (load_ran == 0 && !reduced) {  // a reduced build may have none on its wires
        std::cout << "no load vectors found under " << ldir << "\n";
        return 1;
    }
    if (cap_ran == 0 && !reduced) {  // a reduced build may have none on its wires
        std::cout << "no capability vectors found under " << cdir << "\n";
        return 1;
    }
    return failed == 0 && load_failed == 0 && cap_failed == 0 ? 0 : 1;
}
