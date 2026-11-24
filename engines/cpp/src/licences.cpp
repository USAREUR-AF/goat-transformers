// Licence profiles (engine-spec.md, Version 0.29), read without a TOML library:
// each file is read by the exact line forms of ruling 1.
#include "licences.hpp"

#include <filesystem>
#include <fstream>
#include <iterator>
#include <set>
#include <string_view>

#include "goat_transformers/engine.hpp"

namespace goat_transformers::detail {

namespace fs = std::filesystem;

namespace {

[[noreturn]] void bad(const std::string& path, std::size_t line, const std::string& why) {
    std::string where = path;
    if (line) where += ":" + std::to_string(line);
    throw Error(ErrorKind::BadLicence, "", "", where + ": " + why);
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

bool read_all(const fs::path& p, std::string& out) {
    std::ifstream in(p, std::ios::binary);
    if (!in) return false;
    out.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    return !in.bad();
}

// Ruling 1, Where: false when the file does not exist (no entry of that name,
// or a part of the path before the last is not a directory or does not
// exist); any other failure to read it, or text that is not UTF-8, is
// bad-licence.
bool read_licence_file(const std::string& path, std::string& out) {
    std::error_code ec;
    const fs::file_status st = fs::status(path, ec);
    if (st.type() == fs::file_type::not_found) return false;
    if (ec) bad(path, 0, "cannot be read: " + ec.message());
    if (st.type() == fs::file_type::directory) bad(path, 0, "cannot be read: it is a directory");
    if (!read_all(path, out)) bad(path, 0, "cannot be read");
    if (!valid_utf8(out)) bad(path, 0, "is not valid UTF-8");
    return true;
}

// Ruling 1, Lines: cut at each line feed, one carriage return before it (or at
// the end of the file) removed, then trimmed of spaces and tabs.
std::vector<std::string> lines_of(const std::string& text) {
    std::vector<std::string> lines;
    std::size_t at = 0;
    for (;;) {
        const std::size_t lf = text.find('\n', at);
        std::string line = text.substr(at, lf == std::string::npos ? std::string::npos : lf - at);
        if (!line.empty() && line.back() == '\r') line.pop_back();
        std::size_t b = 0, e = line.size();
        while (b < e && (line[b] == ' ' || line[b] == '\t')) ++b;
        while (e > b && (line[e - 1] == ' ' || line[e - 1] == '\t')) --e;
        lines.push_back(line.substr(b, e - b));
        if (lf == std::string::npos) break;
        at = lf + 1;
    }
    return lines;
}

bool is_space(char c) { return c == ' ' || c == '\t'; }

bool is_licence_id(std::string_view s) {
    if (s.empty()) return false;
    for (char c : s)
        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '-' ||
              c == '+'))
            return false;
    return true;
}

bool is_name(std::string_view s) {
    if (s.empty()) return false;
    for (char c : s)
        if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-'))
            return false;
    return true;
}

bool starts_with(std::string_view s, std::string_view p) { return s.substr(0, p.size()) == p; }

std::size_t skip_space(std::string_view s, std::size_t i) {
    while (i < s.size() && is_space(s[i])) ++i;
    return i;
}

// `<key>`, any spaces or tabs, `=`, any spaces or tabs: the value after them,
// or false when the line is not of that form.
bool key_value(std::string_view line, std::string_view key, std::string_view& value) {
    if (!starts_with(line, key)) return false;
    std::size_t i = skip_space(line, key.size());
    if (i >= line.size() || line[i] != '=') return false;
    value = line.substr(skip_space(line, i + 1));
    return true;
}

// `<key>` followed by a space, a tab or `=`.
bool begins_with_key(std::string_view line, std::string_view key) {
    if (!starts_with(line, key) || line.size() == key.size()) return false;
    const char c = line[key.size()];
    return is_space(c) || c == '=';
}

// REUSE-IgnoreStart: the quoted licence lines below are data
const std::string kTag = "SPDX-License-Identifier";

}  // namespace

int profile_rank(const std::string& name) {
    if (name == "open") return kProfileOpen;
    if (name == "open+copyleft") return kProfileCopyleft;
    if (name == "everything") return kProfileEverything;
    return -1;
}

const char* profile_name(int rank) {
    switch (rank) {
        case kProfileOpen: return "open";
        case kProfileCopyleft: return "open+copyleft";
        case kProfileEverything: return "everything";
        default: return "none";
    }
}

LicenceTable read_licence_table(const std::string& path) {
    LicenceTable table;
    std::string text;
    if (!read_licence_file(path, text)) {
        table["Apache-2.0"] = LicenceRow{true, false, true, false};
        return table;
    }
    const std::vector<std::string> lines = lines_of(text);
    std::string row;  // the licence of the open row; empty before the first
    std::size_t row_line = 0;
    LicenceRow cur;
    std::set<std::string> seen;  // the lines of the open row, by key
    auto close_row = [&](std::size_t at) {
        if (row.empty()) return;
        for (const char* k : {"commercial", "share_alike", "field_of_use", "distribution"})
            if (!seen.count(k))
                bad(path, row_line, "the row of '" + row + "' has no '" + k + "' line (it ends at line " +
                                        std::to_string(at) + ")");
        table[row] = cur;
    };
    for (std::size_t i = 0; i < lines.size(); ++i) {
        const std::string_view line = lines[i];
        const std::size_t no = i + 1;
        if (line.empty() || line[0] == '#') continue;
        if (line[0] == '[') {
            const std::string_view open = "[licences.\"", shut = "\"]";
            if (line.size() > open.size() + shut.size() && starts_with(line, open) &&
                line.substr(line.size() - shut.size()) == shut) {
                const std::string_view id = line.substr(open.size(), line.size() - open.size() - shut.size());
                if (is_licence_id(id)) {
                    close_row(no);
                    row = std::string(id);
                    if (table.count(row)) bad(path, no, "a second row of '" + row + "'");
                    row_line = no;
                    cur = LicenceRow{};
                    seen.clear();
                    continue;
                }
            }
            bad(path, no, "'" + std::string(line) + "' is not a row header [licences.\"<id>\"]");
        }
        if (row.empty()) bad(path, no, "a line before the first row");
        std::string_view v;
        std::string key;
        if (key_value(line, "commercial", v)) {
            key = "commercial";
            if (v == "\"yes\"") cur.commercial_yes = true;
            else if (v == "\"no\"" || v == "\"unknown\"") cur.commercial_yes = false;
            else bad(path, no, "commercial is not \"yes\", \"no\" or \"unknown\"");
        } else if (key_value(line, "share_alike", v)) {
            key = "share_alike";
            if (v == "true") cur.share_alike = true;
            else if (v == "false") cur.share_alike = false;
            else bad(path, no, "share_alike is not true or false");
        } else if (key_value(line, "field_of_use", v)) {
            key = "field_of_use";
            if (v == "[]") cur.field_of_use_empty = true;
            else if (v.size() >= 4 && starts_with(v, "[\"") && v.substr(v.size() - 2) == "\"]")
                cur.field_of_use_empty = false;
            else bad(path, no, "field_of_use is not [] or [\"...\"]");
        } else if (key_value(line, "distribution", v)) {
            key = "distribution";
            if (v == "\"public\"") cur.controlled = false;
            else if (v == "\"controlled\"") cur.controlled = true;
            else bad(path, no, "distribution is not \"public\" or \"controlled\"");
        } else if (begins_with_key(line, "name")) {
            key = "name";
        } else if (begins_with_key(line, "url")) {
            key = "url";
        } else if (begins_with_key(line, "attribution")) {
            key = "attribution";
        } else {
            bad(path, no, "'" + std::string(line) + "' is not a line of a row");
        }
        if (!seen.insert(key).second) bad(path, no, "a second '" + key + "' line in the row of '" + row + "'");
    }
    close_row(lines.size());
    return table;
}

std::string read_pack_licence(const std::string& path) {
    std::string text;
    if (!read_licence_file(path, text)) return "Apache-2.0";
    std::string found;
    std::size_t count = 0;
    const std::vector<std::string> lines = lines_of(text);
    for (std::size_t i = 0; i < lines.size(); ++i) {
        const std::string_view line = lines[i];
        if (!begins_with_key(line, kTag)) continue;  // `SPDX-License-Identifier:` is passed over
        std::string_view v;
        if (key_value(line, kTag, v) && v.size() >= 3 && v.front() == '"' && v.back() == '"' &&
            is_licence_id(v.substr(1, v.size() - 2))) {
            found = std::string(v.substr(1, v.size() - 2));
            if (++count > 1) bad(path, i + 1, "a second licence line");
            continue;
        }
        bad(path, i + 1, "'" + std::string(line) + "' is not a licence line SPDX-License-Identifier = \"<id>\"");
    }
    if (count == 0) bad(path, 0, "has no licence line");
    return found;
}

std::string read_module_licence(const std::string& path) {
    std::string text;
    if (!read_licence_file(path, text)) return "Apache-2.0";
    std::string found;
    std::size_t count = 0;
    const std::string tag = kTag + ":";
    const std::vector<std::string> lines = lines_of(text);
    for (std::size_t i = 0; i < lines.size(); ++i) {
        const std::string_view line = lines[i];
        if (!starts_with(line, tag)) continue;  // `SPDX-License-Identifier =` is passed over
        const std::size_t at = skip_space(line, tag.size());
        if (at > tag.size() && is_licence_id(line.substr(at))) {
            found = std::string(line.substr(at));
            if (++count > 1) bad(path, i + 1, "a second licence line");
            continue;
        }
        bad(path, i + 1, "'" + std::string(line) + "' is not a licence line SPDX-License-Identifier: <id>");
        // REUSE-IgnoreEnd
    }
    if (count == 0) bad(path, 0, "has no licence line");
    return found;
}

int licence_rank(const LicenceTable& table, const std::string& id) {
    const auto it = table.find(id);
    if (it == table.end()) return kProfileEverything;
    const LicenceRow& r = it->second;
    if (r.controlled) return kProfileNone;
    if (r.commercial_yes && r.field_of_use_empty) return r.share_alike ? kProfileCopyleft : kProfileOpen;
    return kProfileEverything;
}

namespace {
DefLines def_lines_of(const std::string& text) {
    DefLines out;
    if (!valid_utf8(text)) return out;
    for (const std::string& l : lines_of(text)) {
        const std::string_view line = l;
        for (const std::string_view kw : {std::string_view("module"), std::string_view("uses")}) {
            if (!starts_with(line, kw)) continue;
            const std::size_t at = skip_space(line, kw.size());
            if (at == kw.size() || !is_name(line.substr(at))) continue;
            const std::string name(line.substr(at));
            if (kw == "uses") out.uses.push_back(name);
            else if (!out.has_module) {
                out.has_module = true;
                out.module = name;
            }
        }
    }
    return out;
}
}  // namespace

DefLines read_def_lines(const std::string& path) {
    std::string text;
    std::error_code ec;
    if (fs::is_directory(path, ec) || !read_all(path, text)) return DefLines{};
    return def_lines_of(text);
}

DefFile read_def_file(const std::string& path) {
    DefFile f;
    std::error_code ec;
    if (fs::is_directory(path, ec) || !read_all(path, f.text)) {
        f.text.clear();
        return f;
    }
    f.read = true;
    f.lines = def_lines_of(f.text);
    f.shown_public = shown_public(f.text);
    return f;
}

std::function<void(const std::string&, std::string&)> def_text_hook;

bool shown_public(const std::string& text) {
    if (!valid_utf8(text)) return false;
    for (std::size_t i = 0; i < text.size(); ++i) {
        const char c = text[i];
        if (c == '\0') return false;
        if (c == '\r' && i + 1 < text.size() && text[i + 1] != '\n') return false;
        if (c == '\xEF' && text.compare(i, 3, "\xEF\xBB\xBF") == 0) return false;  // U+FEFF
    }
    bool exact_seen = false;
    for (const std::string& l : lines_of(text)) {
        const std::string_view line = l;
        // The exact line: `distribution`, one or more spaces or tabs, `public`.
        bool exact = false;
        const std::string_view kw = "distribution";
        if (starts_with(line, kw)) {
            const std::size_t at = skip_space(line, kw.size());
            exact = at > kw.size() && line.substr(at) == "public";
        }
        if (exact) {
            exact_seen = true;
            continue;
        }
        // Doubtful: with every double quote removed, then spaces, tabs and
        // carriage returns removed at its ends, it begins with `distribution`.
        std::string bare;
        for (char d : line)
            if (d != '"') bare += d;
        std::size_t b = 0;
        while (b < bare.size() && (bare[b] == ' ' || bare[b] == '\t' || bare[b] == '\r')) ++b;
        if (std::string_view(bare).substr(b, kw.size()) == kw) return false;
    }
    return exact_seen;
}

}  // namespace goat_transformers::detail
