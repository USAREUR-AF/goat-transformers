// goat-xf: the command-line tool of the C++ engine (engine-spec.md, Version
// 0.23: the command-line contract).
//
//   goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options>
//   goat-xf list-formats <options>
//   goat-xf capability --from <format> --to <format> <options>
//   goat-xf matrix <options>
//   goat-xf licences [--json] <options>        (Version 0.29)
//   goat-xf help
//
// Exit status 0 on success, 1 on a load or call failure (standard error's
// first line is the failure's message, which begins with its kind), 2 on a
// usage error. Every argument is checked before anything is loaded.
#include <cstdint>
#include <cstdio>
#include <exception>
#include <iostream>
#include <iterator>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "goat_transformers/engine.hpp"

namespace gt = goat_transformers;

namespace {

const char kUsage[] =
    "usage: goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options>\n"
    "       goat-xf list-formats <options>\n"
    "       goat-xf capability --from <format> --to <format> <options>\n"
    "       goat-xf matrix <options>\n"
    "       goat-xf licences [--json] <options>\n"
    "       goat-xf help\n"
    "options, in any order, each at most once:\n"
    "  --packs <dir>                              the directory whose subdirectories are packs (default: packs)\n"
    "  --models <dir>                             the directory of model modules (default: <packs>/../model)\n"
    "  --packs-only <name>[,<name>...]            load only these subdirectories of --packs, in that order\n"
    "  --max-items <n>                            the limit on list items one decode holds (default: 100000)\n"
    "  --max-distribution public|controlled       the engine's distribution limit (default: controlled)\n"
    "  --profile open|open+copyleft|everything    load only the packs and modules of this licence profile\n"
    "                                             (default: none, every pack and module)\n"
    "--json, for licences only, takes no value.\n"
    "convert reads the message from standard input and writes the result to standard output.\n";

int usage_error(const std::string& why) {
    std::cerr << "goat-xf: " << why << "\n" << kUsage;
    return 2;
}

// One or more digits and no more than 2^63 - 1; leading zeros allowed.
bool parse_max_items(const std::string& text, std::uint64_t& out) {
    if (text.empty()) return false;
    for (char c : text)
        if (c < '0' || c > '9') return false;
    std::size_t first = text.find_first_not_of('0');
    if (first == std::string::npos) {
        out = 0;
        return true;
    }
    const std::string digits = text.substr(first);
    static const std::string kMax = "9223372036854775807";
    if (digits.size() > kMax.size() || (digits.size() == kMax.size() && digits > kMax)) return false;
    std::uint64_t v = 0;
    for (char c : digits) v = v * 10 + static_cast<std::uint64_t>(c - '0');
    out = v;
    return true;
}

// Well-formed UTF-8: no overlong form, no surrogate, nothing above U+10FFFF.
bool valid_utf8(const std::string& s) {
    std::size_t i = 0;
    const std::size_t n = s.size();
    while (i < n) {
        const unsigned char c = static_cast<unsigned char>(s[i]);
        if (c < 0x80) {
            ++i;
            continue;
        }
        std::size_t len;
        unsigned char lo = 0x80, hi = 0xBF;
        if (c >= 0xC2 && c <= 0xDF) len = 2;
        else if (c == 0xE0) len = 3, lo = 0xA0;
        else if (c >= 0xE1 && c <= 0xEC) len = 3;
        else if (c == 0xED) len = 3, hi = 0x9F;
        else if (c >= 0xEE && c <= 0xEF) len = 3;
        else if (c == 0xF0) len = 4, lo = 0x90;
        else if (c >= 0xF1 && c <= 0xF3) len = 4;
        else if (c == 0xF4) len = 4, hi = 0x8F;
        else return false;
        if (n - i < len) return false;
        for (std::size_t k = 1; k < len; ++k) {
            const unsigned char d = static_cast<unsigned char>(s[i + k]);
            if (d < (k == 1 ? lo : 0x80) || d > (k == 1 ? hi : 0xBF)) return false;
        }
        i += len;
    }
    return true;
}

std::string join(const std::vector<std::string>& v) {
    std::string out;
    for (std::size_t i = 0; i < v.size(); ++i) {
        if (i) out += ' ';
        out += v[i];
    }
    return out;
}

std::string capability_line(const gt::Engine& eng, const std::string& from, const std::string& to) {
    const gt::Capability c = eng.capability(from, to);
    return from + "\t" + to + "\t" + c.grade + "\t" + join(c.carried) + "\t" + join(c.dropped) + "\n";
}

int write_out(const std::string& out) {
    if (!out.empty() && std::fwrite(out.data(), 1, out.size(), stdout) != out.size()) return 1;
    return std::fflush(stdout) == 0 ? 0 : 1;
}

// A value of `licences --json` (0.29 ruling 4c).
std::string json_string(const std::string& s) {
    static const char kHex[] = "0123456789abcdef";
    std::string out = "\"";
    for (char ch : s) {
        const unsigned char c = static_cast<unsigned char>(ch);
        if (c == '"') out += "\\\"";
        else if (c == '\\') out += "\\\\";
        else if (c < 0x20) {
            out += "\\u00";
            out += kHex[c >> 4];
            out += kHex[c & 15];
        } else out += ch;
    }
    return out + "\"";
}

void require_format(const gt::Engine& eng, const std::string& format) {
    if (!eng.has_format(format))
        throw gt::Error(gt::ErrorKind::UnknownFormat, format, "", "no loaded pack defines the format");
}

}  // namespace

int main(int argc, char** argv) {
    std::vector<std::string> args(argv + 1, argv + argc);
    if (args.empty()) return usage_error("no subcommand");
    const std::string cmd = args[0];
    if (cmd == "help" || cmd == "-h" || cmd == "--help") {
        std::cout << kUsage;
        return std::fflush(stdout) == 0 ? 0 : 1;
    }
    const bool is_convert = cmd == "convert", is_capability = cmd == "capability";
    const bool is_licences = cmd == "licences";
    if (!is_convert && !is_capability && !is_licences && cmd != "list-formats" && cmd != "matrix")
        return usage_error("unknown subcommand '" + cmd + "'");

    // The names this subcommand takes.
    std::vector<std::string> names = {"--packs",      "--models",           "--packs-only",
                                      "--max-items",  "--max-distribution", "--profile"};
    if (is_licences) names.push_back("--json");
    if (is_convert || is_capability) {
        names.push_back("--from");
        names.push_back("--to");
    }
    if (is_convert) names.push_back("--set");

    std::map<std::string, std::string> opt;
    gt::Engine::TextContext context;  // the --set options: first place, last value
    bool have_context = false;
    bool json = false;
    for (std::size_t k = 1; k < args.size(); k += 2) {
        const std::string& name = args[k];
        bool known = false;
        for (const auto& n : names) known = known || n == name;
        if (!known) return usage_error("'" + name + "' is not an option of " + cmd);
        if (name == "--json") {  // the one option without a value (0.29 ruling 4b)
            if (json) return usage_error("--json is given twice");
            json = true;
            --k;
            continue;
        }
        if (k + 1 >= args.size()) return usage_error(name + " needs a value");
        const std::string& value = args[k + 1];
        if (name == "--set") {
            const std::size_t eq = value.find('=');
            if (eq == std::string::npos || eq == 0) return usage_error("--set needs <key>=<value>, got '" + value + "'");
            const std::string key = value.substr(0, eq);
            have_context = true;
            bool found = false;
            for (auto& kv : context)
                if (kv.first == key) {
                    kv.second = value.substr(eq + 1);
                    found = true;
                }
            if (!found) context.emplace_back(key, value.substr(eq + 1));
            continue;
        }
        if (opt.count(name)) return usage_error(name + " is given twice");
        opt[name] = value;
    }
    if ((is_convert || is_capability) && !opt.count("--from")) return usage_error(cmd + " needs --from");
    if ((is_convert || is_capability) && !opt.count("--to")) return usage_error(cmd + " needs --to");

    std::uint64_t max_items = gt::Engine::kDefaultMaxItems;
    if (opt.count("--max-items") && !parse_max_items(opt["--max-items"], max_items))
        return usage_error("--max-items needs digits 0 to 9, at most 9223372036854775807, got '" +
                           opt["--max-items"] + "'");

    auto limit = gt::Distribution::Controlled;
    if (opt.count("--max-distribution")) {
        const std::string& d = opt["--max-distribution"];
        if (d == "public") limit = gt::Distribution::Public;
        else if (d != "controlled") return usage_error("--max-distribution must be public or controlled, got '" + d + "'");
    }

    std::optional<std::string> profile;
    if (opt.count("--profile")) {
        if (!gt::Engine::is_profile(opt["--profile"]))
            return usage_error("--profile must be open, open+copyleft or everything, got '" + opt["--profile"] + "'");
        profile = opt["--profile"];
    }

    std::vector<std::string> only;
    if (opt.count("--packs-only")) {
        const std::string& list = opt["--packs-only"];
        for (std::size_t at = 0;;) {
            const std::size_t comma = list.find(',', at);
            only.push_back(list.substr(at, comma == std::string::npos ? std::string::npos : comma - at));
            if (only.back().empty()) return usage_error("--packs-only holds an empty name: '" + list + "'");
            if (comma == std::string::npos) break;
            at = comma + 1;
        }
    }

    const std::string packs = opt.count("--packs") ? opt["--packs"] : std::string("packs");
    const std::string models = opt.count("--models") ? opt["--models"] : packs + "/../model";

    try {
        gt::Engine eng = gt::Engine::load_tool(packs, models, opt.count("--packs-only") ? &only : nullptr, limit,
                                               profile, is_licences);
        eng.set_max_items(max_items);

        if (cmd == "list-formats") {
            std::string out;
            for (const auto& f : eng.formats()) {
                const gt::Pack& p = eng.pack(f);
                out += f + "\t" + p.version + "\t" + gt::wire_name(p.wire) + "\n";
            }
            return write_out(out);
        }
        if (is_licences) {
            std::string out = json ? "{\"packs\":[" : "";
            bool first = true;
            for (const auto& p : eng.pack_licences()) {
                if (json) {
                    if (!first) out += ',';
                    out += "{\"pack\":" + json_string(p.dir) + ",\"format\":" + json_string(p.format) +
                           ",\"licence\":" + json_string(p.licence) + ",\"profile\":" + json_string(p.profile) + "}";
                } else {
                    out += p.dir + "\t" + p.format + "\t" + p.licence + "\t" + p.profile + "\n";
                }
                first = false;
            }
            if (json) out += "]}\n";
            return write_out(out);
        }
        if (cmd == "matrix") {
            const std::vector<std::string> formats = eng.formats();
            std::string out = "from\tto\tgrade\tcarried\tdropped\n";
            for (const auto& from : formats)
                for (const auto& to : formats) out += capability_line(eng, from, to);
            return write_out(out);
        }
        const std::string& from = opt["--from"];
        const std::string& to = opt["--to"];
        require_format(eng, from);
        require_format(eng, to);
        if (is_capability) return write_out(capability_line(eng, from, to));

        // convert: standard input to its end, unchanged.
        std::string input((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
        if (!valid_utf8(input))
            throw gt::Error(gt::ErrorKind::MalformedWire, from, "", "the input is not valid UTF-8");
        const std::string out = have_context ? eng.convert_text_in_order(from, to, input, context)
                                             : eng.convert(from, to, input);
        return write_out(out);
    } catch (const gt::Error& e) {
        std::cerr << e.what() << "\n";
        return 1;
    } catch (const std::exception& e) {
        std::cerr << "io: " << e.what() << "\n";
        return 1;
    }
}
