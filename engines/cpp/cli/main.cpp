// goat-xf: command-line front end to the C++ engine.
//   goat-xf convert --from X --to Y --packs DIR [--set KEY=VALUE ...]   (stdin -> stdout)
//   goat-xf list-formats --packs DIR
// Both take --models DIR (default <packs>/../model) and
// --max-distribution public|controlled (default controlled).
// --set supplies a model key the message lacks (engine-spec.md 0.6, Caller-supplied
// keys); it is repeatable, and the value is read as the key's declared type.
#include <cstdio>
#include <iostream>
#include <iterator>
#include <map>
#include <string>

#include "goat_transformers/engine.hpp"

namespace {

int usage() {
    std::cerr << "usage: goat-xf convert --from <format> --to <format> --packs <dir> [--set <key>=<value> ...]\n"
                 "       goat-xf list-formats --packs <dir>\n"
                 "options: --models <dir>                         default <packs>/../model\n"
                 "         --max-distribution public|controlled   default controlled\n"
                 "         --set <key>=<value>                    convert: a model key the caller supplies; repeatable\n";
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) return usage();
    std::string cmd = argv[1];
    std::map<std::string, std::string> opt, context;
    bool have_context = false;
    for (int k = 2; k < argc; ++k) {
        std::string a = argv[k];
        if (a == "--set") {
            if (k + 1 >= argc) {
                std::cerr << "goat-xf: --set needs <key>=<value>\n";
                return usage();
            }
            const std::string kv = argv[++k];
            const std::size_t eq = kv.find('=');
            if (eq == std::string::npos || eq == 0) {
                std::cerr << "goat-xf: --set needs <key>=<value>, got " << kv << "\n";
                return usage();
            }
            context[kv.substr(0, eq)] = kv.substr(eq + 1);
            have_context = true;
            continue;
        }
        if (a != "--from" && a != "--to" && a != "--packs" && a != "--models" && a != "--max-distribution") {
            std::cerr << "goat-xf: unknown option " << a << "\n";
            return usage();
        }
        if (k + 1 >= argc) {
            std::cerr << "goat-xf: " << a << " needs a value\n";
            return usage();
        }
        opt[a] = argv[++k];
    }
    if (!opt.count("--packs")) return usage();

    auto limit = goat_transformers::Distribution::Controlled;
    if (opt.count("--max-distribution")) {
        const std::string& d = opt["--max-distribution"];
        if (d == "public") limit = goat_transformers::Distribution::Public;
        else if (d != "controlled") {
            std::cerr << "goat-xf: --max-distribution must be public or controlled\n";
            return usage();
        }
    }

    try {
        auto eng = goat_transformers::Engine::load(opt["--packs"], opt["--models"], limit);
        if (cmd == "list-formats") {
            for (const auto& f : eng.formats()) std::cout << f << "\n";
            return 0;
        }
        if (cmd == "convert") {
            if (!opt.count("--from") || !opt.count("--to")) return usage();
            std::string input((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
            std::string out = have_context ? eng.convert_text(opt["--from"], opt["--to"], input, context)
                                           : eng.convert(opt["--from"], opt["--to"], input);
            std::fwrite(out.data(), 1, out.size(), stdout);
            return std::fflush(stdout) == 0 ? 0 : 1;
        }
        std::cerr << "goat-xf: unknown command " << cmd << "\n";
        return usage();
    } catch (const goat_transformers::Error& e) {
        std::cerr << "goat-xf: " << e.what() << "\n";
        return 1;
    }
}
