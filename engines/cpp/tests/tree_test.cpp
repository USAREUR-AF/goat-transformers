// load_tree: the named packs and only the model modules they need.
// Usage: goat_transformers_tree <root>   (the directory holding model/ and packs/)
#include <iostream>
#include <string>
#include <vector>

#include "goat_transformers/tree.hpp"

namespace gt = goat_transformers;

namespace {

int failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        ++failures;
        std::cout << "FAIL " << what << "\n";
    }
}

std::string joined(const std::vector<std::string>& v) {
    std::string out;
    for (const auto& s : v) out += s + " ";
    return out;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: goat_transformers_tree <root>\n";
        return 2;
    }
    const std::string root = argv[1];
    try {
        gt::Engine e;
        gt::load_tree(e, root, {"cot-xml", "geojson"});
        check(joined(e.formats()) == "cot-xml geojson ", "formats: " + joined(e.formats()));
        check(joined(e.modules()) == "core ", "modules: " + joined(e.modules()));
        const std::string cot =
            "<event version=\"2.0\" uid=\"J-01334\" type=\"a-f-G-U-C\" time=\"2021-02-27T20:00:00.000Z\" how=\"m-g\">"
            "<point lat=\"30.0090027\" lon=\"-85.9578182\" hae=\"-42.6\" ce=\"45.3\" le=\"99.5\"/></event>";
        const std::string want =
            "{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[-85.9578182,30.0090027,-42.6]},"
            "\"properties\":{\"type\":\"a-f-G-U-C\",\"time_ms\":1614456000000,\"how\":\"m-g\",\"ce\":45.3,\"le\":99.5},"
            "\"id\":\"J-01334\"}";
        check(e.convert("cot-xml", "geojson", cot) == want, "convert: " + e.convert("cot-xml", "geojson", cot));

        // asterix-cat062 uses cat062, and cat062 uses track
        gt::Engine a;
        gt::load_tree(a, root, {"asterix-cat062"});
        check(joined(a.modules()) == "cat062 core track ", "modules through a module: " + joined(a.modules()));
        gt::load_tree(a, root, {"canonical-track-v2"});
        check(a.formats().size() == 2 && a.modules().size() == 3, "a second load adds a pack");

        bool refused = false;
        try {
            gt::Engine n;
            gt::load_tree(n, root, {"no-such-format"});
        } catch (const gt::Error& err) {
            refused = err.kind() == gt::ErrorKind::UnknownFormat;
        }
        check(refused, "a pack the tree does not hold is unknown-format");
    } catch (const std::exception& ex) {
        std::cout << "FAIL " << ex.what() << "\n";
        return 1;
    }
    std::cout << (failures == 0 ? "tree: ok\n" : "tree: failed\n");
    return failures == 0 ? 0 : 1;
}
