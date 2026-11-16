// goat-transformers C++ engine: load a chosen set of packs from a tree.
#pragma once

#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"

namespace goat_transformers {

// Load the named packs from `<root>/packs/<name>/pack.def`, and before them the
// model modules they need from `<root>/model/*.def`: `core`, every module a
// named pack `uses`, and every module one of those `uses`, each after the
// modules it uses. Nothing else in the tree is loaded. A module the engine
// already holds is not loaded again, so the call can be repeated with more
// packs. The engine's distribution limit applies.
//
// A tree is a directory holding `model/` and `packs/`: a checkout of the
// library, or a bundle written by `tools/goat-pkg bundle`.
//
//     goat_transformers::Engine engine;
//     goat_transformers::load_tree(engine, "vendor/goat", {"cot-xml", "geojson"});
//
// Throws Error: UnknownFormat for a pack the tree does not hold, Io for a file
// that cannot be read, and whatever the load of a module or pack throws.
void load_tree(Engine& engine, const std::string& root, const std::vector<std::string>& packs);

}  // namespace goat_transformers
