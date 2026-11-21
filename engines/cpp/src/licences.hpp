// Licence profiles (engine-spec.md, Version 0.29): the licence files an engine
// reads (ruling 1) and the profile of a licence (ruling 2a).
#pragma once

#include <map>
#include <string>
#include <vector>

namespace goat_transformers::detail {

// Profiles as ranks, in the order of the section: open < open+copyleft <
// everything < none. A profile holds every rank up to its own.
constexpr int kProfileOpen = 0;
constexpr int kProfileCopyleft = 1;
constexpr int kProfileEverything = 2;
constexpr int kProfileNone = 3;

// The rank of a profile name, or -1 for a text that is not one of the three.
int profile_rank(const std::string& name);
// `open`, `open+copyleft`, `everything` or `none`.
const char* profile_name(int rank);

// One row of `licences.toml` (ruling 1c), as ruling 2a reads it.
struct LicenceRow {
    bool commercial_yes = false;
    bool share_alike = false;
    bool field_of_use_empty = true;
    bool controlled = false;
};
using LicenceTable = std::map<std::string, LicenceRow>;

// Ruling 1c. A file that does not exist is the table of one row, Apache-2.0.
// Throws bad-licence.
LicenceTable read_licence_table(const std::string& path);
// Ruling 1a: the licence of `<packs>/<dir>/REUSE.toml`; Apache-2.0 when the
// file does not exist. Throws bad-licence.
std::string read_pack_licence(const std::string& path);
// Ruling 1b: the licence of `<models>/<file>.def.license`; Apache-2.0 when the
// file does not exist. Throws bad-licence.
std::string read_module_licence(const std::string& path);
// Ruling 2a: the profile rank of a licence id.
int licence_rank(const LicenceTable& table, const std::string& id);

// Ruling 2b: the `module` and `uses` lines of a module file or `pack.def`.
// A file that cannot be read, or is not UTF-8, has none.
struct DefLines {
    bool has_module = false;
    std::string module;  // the name of the first `module` line
    std::vector<std::string> uses;
};
DefLines read_def_lines(const std::string& path);

}  // namespace goat_transformers::detail
