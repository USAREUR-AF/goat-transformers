// load_tree: the named packs of a tree and only the model modules they need.
#include "goat_transformers/tree.hpp"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <map>
#include <set>
#include <sstream>

namespace goat_transformers {

namespace fs = std::filesystem;

namespace {

std::string read_text(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) throw Error(ErrorKind::Io, "", "", "cannot read " + p.string());
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

struct ModuleFile {
    std::string origin;
    std::string text;
    std::vector<std::string> uses;
};

void place(Engine& engine, const std::string& name, const std::map<std::string, ModuleFile>& files,
           std::set<std::string>& placing) {
    // A module no file declares is left to the pack's load: unknown-module.
    auto it = files.find(name);
    if (engine.has_module(name) || it == files.end()) return;
    if (!placing.insert(name).second)
        throw Error(ErrorKind::BadDirective, "", "",
                    "the 'uses' lines of the modules form a cycle through '" + name + "' (" + it->second.origin + ")");
    for (const auto& used : it->second.uses)
        if (used != name) place(engine, used, files, placing);
    placing.erase(name);
    engine.load_model(it->second.text, it->second.origin);
}

}  // namespace

void load_tree(Engine& engine, const std::string& root, const std::vector<std::string>& packs) {
    const fs::path base(root);
    std::error_code ec;

    std::vector<Pack> chosen;
    std::set<std::string> named;
    for (const auto& name : packs) {
        if (!named.insert(name).second) continue;
        const fs::path def = base / "packs" / name / "pack.def";
        if (!fs::is_regular_file(def, ec))
            throw Error(ErrorKind::UnknownFormat, name, "", "no pack " + name + " under " + (base / "packs").string());
        chosen.push_back(parse_pack(read_text(def), def.string()));
    }

    // Every module file of the tree, by module name; the first file of a name
    // in byte order of file name.
    std::map<std::string, ModuleFile> files;
    const fs::path mdir = base / "model";
    if (fs::is_directory(mdir, ec)) {
        std::vector<std::string> names;
        for (const auto& ent : fs::directory_iterator(mdir, ec))
            if (ent.is_regular_file() && ent.path().extension() == ".def") names.push_back(ent.path().filename().string());
        if (ec) throw Error(ErrorKind::Io, "", "", "cannot list " + mdir.string() + ": " + ec.message());
        std::sort(names.begin(), names.end());
        for (const auto& n : names) {
            ModuleFile f;
            f.origin = (mdir / n).string();
            f.text = read_text(mdir / n);
            Module head = parse_model(f.text, f.origin);
            f.uses = head.uses;
            files.emplace(head.name, std::move(f));
        }
    }

    std::set<std::string> placing;
    place(engine, "core", files, placing);
    for (const auto& p : chosen)
        for (const auto& used : p.uses) place(engine, used, files, placing);
    for (auto& p : chosen) engine.add_pack(std::move(p));
}

}  // namespace goat_transformers
