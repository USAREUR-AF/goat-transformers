// Licence profiles (engine-spec.md, Version 0.29): the licence files an engine
// reads (ruling 1) and the profile of a licence (ruling 2a).
#pragma once

#include <functional>
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

// A module file or pack.def read once for its profile (0.29 ruling 2b, 0.93
// ruling 1): `read` is false when it cannot be read; `text` is its bytes, the
// text that is then parsed; `lines` its `module` and `uses` lines (none when
// it is not UTF-8); `shown_public` ruling 1 of 0.93.
struct DefFile {
    bool read = false;
    std::string text;
    DefLines lines;
    bool shown_public = false;
};
DefFile read_def_file(const std::string& path);
// 0.93 ruling 1 on the bytes of a file: valid UTF-8, no NUL byte, no U+FEFF,
// no carriage return that is not before a line feed or at the end, at least
// one line `distribution<spaces or tabs>public` and no doubtful line.
bool shown_public(const std::string& text);
// A test hook (0.93 ruling 5): this engine reads each file once, so a file
// cannot change between its profile and its parse. When set, it is called
// with the path and the text of each module file and pack.def held by a load
// that read licences, after its profile and before its parse, and may change
// the text that is parsed. Empty outside tests.
extern std::function<void(const std::string& path, std::string& text)> def_text_hook;

}  // namespace goat_transformers::detail
