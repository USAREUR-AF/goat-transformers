// Sequential binary layouts (engine-spec.md, Version 0.8): the pack grammar,
// decode from a cursor and the two-pass encode.
#include "sequential.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <map>
#include <set>
#include <stdexcept>
#include <unordered_map>

#include "codecs.hpp"
#include "linecheck.hpp"
#include "transforms.hpp"
#include "util.hpp"
#include "wires.hpp"

namespace goat_transformers::detail {

namespace {

using Type = SeqNode::Type;
using Repeat = SeqNode::Repeat;

bool parse_u32(const std::string& s, std::uint32_t& out) {
    if (s.empty()) return false;
    std::uint64_t v = 0;
    for (char c : s) {
        if (c < '0' || c > '9') return false;
        v = v * 10 + static_cast<std::uint64_t>(c - '0');
        if (v > 0xFFFFFFFFull) return false;
    }
    out = static_cast<std::uint32_t>(v);
    return true;
}

bool parse_u64(const std::string& s, std::uint64_t& out) {
    if (s.empty()) return false;
    std::uint64_t v = 0;
    for (char c : s) {
        if (c < '0' || c > '9') return false;
        const std::uint64_t d = static_cast<std::uint64_t>(c - '0');
        if (v > (~std::uint64_t{0} - d) / 10) return false;
        v = v * 10 + d;
    }
    out = v;
    return true;
}

// `plus <n>`: integer text (0.11 ruling 2c, by 2a): an optional `-`, no `+`.
bool parse_i64(const std::string& s, std::int64_t& out) { return parse_int_text(s, out); }

// v0.19, a number of a UPER line (ruling 15): an optional `-` and digits with
// no leading zero, `-0` refused, within 64 signed bits.
bool parse_uper_num(const std::string& s, std::int64_t& out) {
    const bool neg = !s.empty() && s[0] == '-';
    const std::string digits = neg ? s.substr(1) : s;
    if (digits.empty() || (digits.size() > 1 && digits[0] == '0') || (neg && digits == "0")) return false;
    std::uint64_t v = 0;
    if (!parse_u64(digits, v)) return false;
    if (neg) {
        if (v > static_cast<std::uint64_t>(INT64_MAX) + 1) return false;
        out = v == static_cast<std::uint64_t>(INT64_MAX) + 1 ? INT64_MIN : -static_cast<std::int64_t>(v);
    } else {
        if (v > static_cast<std::uint64_t>(INT64_MAX)) return false;
        out = static_cast<std::int64_t>(v);
    }
    return true;
}

// The numbers of `choice`, `alt` and `group ... size` lines (ruling 15): digits
// with no leading zero, no sign.
bool parse_uper_count(const std::string& s, std::int64_t& out) {
    return !s.empty() && s[0] != '-' && parse_uper_num(s, out);
}

std::vector<std::string> split_colons(const std::string& s) {
    std::vector<std::string> out(1);
    for (char c : s) {
        if (c == ':') out.emplace_back();
        else out.back() += c;
    }
    return out;
}

bool is_uper_locator(const std::string& loc) {
    return loc.compare(0, 4, "int:") == 0 || loc.compare(0, 5, "enum:") == 0 || loc.compare(0, 6, "chars:") == 0 ||
           loc.compare(0, 7, "octets:") == 0;
}

// The UPER locator forms (0.19, Locators). False when the text is none of them.
bool parse_uper_locator(const std::string& loc, SeqNode& n) {
    const std::vector<std::string> t = split_colons(loc);
    using U = SeqNode::Uper;
    if (t[0] == "int") {
        if (t.size() == 3 && t[1].empty() && t[2].empty()) {
            n.uper = U::IntUn;
            return true;
        }
        if (t.size() == 3 && t[2].empty()) {
            n.uper = U::IntSemi;
            return parse_uper_num(t[1], n.lb);
        }
        if (t.size() == 3 || (t.size() == 4 && t[3] == "ext")) {
            n.uper = t.size() == 4 ? U::IntExt : U::Int;
            return parse_uper_num(t[1], n.lb) && parse_uper_num(t[2], n.ub) && n.lb <= n.ub;
        }
        return false;
    }
    if (t[0] == "enum") {
        if (t.size() != 2 && !(t.size() == 3 && t[2] == "ext")) return false;
        std::int64_t count = 0;
        if (!parse_uper_num(t[1], count) || count < 1 || count > 65536) return false;
        n.uper = t.size() == 3 ? U::EnumExt : U::Enum;
        n.lb = 0;
        n.ub = count - 1;
        return true;
    }
    // chars and octets
    n.uper = t[0] == "chars" ? U::Chars : U::Octets;
    if (t.size() == 2 && t[1].empty()) return true;
    if (t.size() != 3) return false;
    n.bounded = true;
    return parse_uper_num(t[1], n.lb) && parse_uper_num(t[2], n.ub) && 0 <= n.lb && n.lb <= n.ub && n.ub < 65536;
}

// v0.21 ruling 16: `plus <n>` of a count line, an optional `-` then digits
// (leading zeros allowed) within signed 64 bits.
bool parse_plus(const std::string& s, std::int64_t& out) {
    const bool neg = !s.empty() && s[0] == '-';
    std::uint64_t v = 0;
    if (!parse_u64(neg ? s.substr(1) : s, v)) return false;
    const std::uint64_t top = static_cast<std::uint64_t>(INT64_MAX);
    if (neg) {
        if (v > top + 1) return false;
        out = v == top + 1 ? INT64_MIN : -static_cast<std::int64_t>(v);
    } else {
        if (v > top) return false;
        out = static_cast<std::int64_t>(v);
    }
    return true;
}

template <class Lines, class Fn>
void each_node(Lines& lines, Fn&& fn) {
    for (auto& n : lines) {
        fn(n);
        each_node(n.inner.lines, fn);
        for (auto& k : n.inner.kinds) each_node(k.lines, fn);
        for (auto& c : n.cases) each_node(c.body.lines, fn);
    }
}

// A list in two groups of one scope (0.8 rulings 23 and 33). A scope is the
// common lines of a body with the lines of one of its kinds; a group's items
// are a scope of their own. Two groups of one list are allowed only when each
// sits in an `if` or `opt` block and neither group's block, the innermost
// one, encloses the other's; a block encloses itself. When both are on the
// wire, decode keeps the later group's items.
struct ListUse {
    const SeqNode* group;
    // The `if` and `opt` blocks and the cases (0.20 ruling 10) of the scope
    // that hold the group, outermost first.
    std::vector<const void*> blocks;
};

void check_lists_once(const Pack& p, const SeqBody& body, const std::string& source);

void collect_groups(const Pack& p, const std::vector<SeqNode>& lines, std::vector<const void*>& blocks,
                    const std::string& source, std::vector<ListUse>& out) {
    for (const auto& n : lines) {
        if (n.type == Type::Group) {
            out.push_back({&n, blocks});
            check_lists_once(p, n.inner, source);  // the items are a scope of their own
        } else if (n.type == Type::If || n.type == Type::Opt || n.type == Type::Alt) {
            blocks.push_back(&n);
            collect_groups(p, n.inner.lines, blocks, source, out);
            blocks.pop_back();
        } else if (n.type == Type::Switch) {
            for (const auto& c : n.cases) {
                blocks.push_back(&c);
                collect_groups(p, c.body.lines, blocks, source, out);
                blocks.pop_back();
            }
        } else {
            collect_groups(p, n.inner.lines, blocks, source, out);
        }
    }
}

void check_lists_once(const Pack& p, const SeqBody& body, const std::string& source) {
    std::vector<const void*> blocks;
    std::vector<ListUse> common;
    collect_groups(p, body.lines, blocks, source, common);
    // Does the innermost block of `a` enclose the innermost block of `b`?
    auto encloses = [](const ListUse& a, const ListUse& b) {
        return std::find(b.blocks.begin(), b.blocks.end(), a.blocks.back()) != b.blocks.end();
    };
    auto check = [&](const std::vector<ListUse>& uses) {
        for (std::size_t b = 1; b < uses.size(); ++b)
            for (std::size_t a = 0; a < b; ++a) {
                if (uses[a].group->list != uses[b].group->list) continue;
                if (!uses[a].blocks.empty() && !uses[b].blocks.empty() && !encloses(uses[a], uses[b]) &&
                    !encloses(uses[b], uses[a]))
                    continue;
                throw Error(ErrorKind::BadDirective, p.format, "",
                            source + ":" + std::to_string(uses[b].group->line) + ": the list '" + uses[b].group->list +
                                "' is mapped by two groups of one scope (the other at line " +
                                std::to_string(uses[a].group->line) +
                                ") that are not in 'if' or 'opt' blocks neither of which encloses the other");
            }
    };
    if (body.kinds.empty()) check(common);
    for (const auto& k : body.kinds) {
        std::vector<ListUse> uses = common;
        collect_groups(p, k.lines, blocks, source, uses);
        check(uses);
    }
}

// ---- v0.21: count references and `rest` placement

// The numbers of references to the count `id` over the reading paths of
// `lines` from `from`, each capped at 2. Paths split at kinds and at the cases
// of a switch only (rulings 2 and 33).
std::set<int> ref_paths(const std::vector<SeqNode>& lines, std::size_t from, int id);

std::set<int> add_paths(const std::set<int>& a, const std::set<int>& b) {
    std::set<int> out;
    for (int x : a)
        for (int y : b) out.insert(std::min(x + y, 2));
    return out;
}

std::set<int> node_refs(const SeqNode& n, int id) {
    switch (n.type) {
        case Type::Group: return {n.repeat == Repeat::CountRef && (n.count_id == id || n.count_id2 == id) ? 1 : 0};
        case Type::Switch: {
            std::set<int> out;
            for (const auto& c : n.cases) {
                const std::set<int> r = ref_paths(c.body.lines, 0, id);
                out.insert(r.begin(), r.end());
            }
            if (out.empty()) out.insert(0);
            return out;
        }
        case Type::If:
        case Type::Opt:
        case Type::Chain: return ref_paths(n.inner.lines, 0, id);
        // v0.83 ruling 1: a `length @` is a reference, as a group is.
        case Type::Length: return add_paths({n.unit_size && n.count_id == id ? 1 : 0}, ref_paths(n.inner.lines, 0, id));
        default: return {0};
    }
}

std::set<int> ref_paths(const std::vector<SeqNode>& lines, std::size_t from, int id) {
    std::set<int> out{0};
    for (std::size_t k = from; k < lines.size(); ++k) out = add_paths(out, node_refs(lines[k], id));
    return out;
}

void check_count_refs(const Pack& p, const std::vector<SeqNode>& lines, const std::vector<SeqKind>* kinds,
                      const std::string& source);

void check_count_refs_body(const Pack& p, const SeqBody& body, const std::string& source) {
    check_count_refs(p, body.lines, body.kinds.empty() ? nullptr : &body.kinds, source);
    for (const auto& k : body.kinds) check_count_refs(p, k.lines, nullptr, source);
}

// Every count line is referenced by exactly one group in each reading path
// from its line to the end of its block (v0.21 ruling 2).
void check_count_refs(const Pack& p, const std::vector<SeqNode>& lines, const std::vector<SeqKind>* kinds,
                      const std::string& source) {
    for (std::size_t i = 0; i < lines.size(); ++i) {
        const SeqNode& n = lines[i];
        if (n.type == Type::Count) {
            std::set<int> paths = ref_paths(lines, i + 1, n.count_id);
            if (kinds) {
                std::set<int> all;
                for (const auto& k : *kinds) {
                    const std::set<int> r = add_paths(paths, ref_paths(k.lines, 0, n.count_id));
                    all.insert(r.begin(), r.end());
                }
                paths = all;
            }
            if (paths != std::set<int>{1})
                throw Error(ErrorKind::BadDirective, p.format, "",
                            source + ":" + std::to_string(n.line) + ": the count '" + n.count_name +
                                "' is not referenced by exactly one 'group ... count @" + n.count_name +
                                "' or 'length @" + n.count_name + "' in every reading path after it");
        }
        if (n.type == Type::Group) check_count_refs_body(p, n.inner, source);
        else if (n.type == Type::Switch)
            for (const auto& c : n.cases) check_count_refs(p, c.body.lines, nullptr, source);
        else check_count_refs(p, n.inner.lines, nullptr, source);
    }
}

// Does the line read or write bits (rulings 26 and 32)? An `if`, `switch` or
// `chain` is one only when it holds one.
bool is_wire_line(const SeqNode& n) {
    switch (n.type) {
        case Type::If:
        case Type::Chain:
            for (const auto& l : n.inner.lines)
                if (is_wire_line(l)) return true;
            return false;
        case Type::Switch:
            for (const auto& c : n.cases)
                for (const auto& l : c.body.lines)
                    if (is_wire_line(l)) return true;
            return false;
        // 0.21 ruling 41: an `ext` reads its extension bit, so it always is; a
        // `choice` is one with `ext`, more than one root alternative (its index
        // has bits), or an `alt` holding a wire line.
        case Type::Choice:
            if (n.uext || n.number > 1) return true;
            for (const auto& a : n.inner.lines)
                if (is_wire_line(a)) return true;
            return false;
        case Type::Alt:
            for (const auto& l : n.inner.lines)
                if (is_wire_line(l)) return true;
            return false;
        default: return true;
    }
}

// Where a `rest` group may be (rulings 10, 11 and 27): `in_item` is true inside
// a group body outside any `length` block of it, `rest_item` when that group
// is itself `rest`.
struct RestPlace {
    bool in_item = false;
    bool rest_item = false;
};

bool check_rest_body(const Pack& p, const SeqBody& body, bool after_rest, RestPlace at, const std::string& source);

// Walks `lines` in reading order; `after_rest` is true when a `rest` group
// came earlier in the same extent. Returns that state after the lines.
bool check_rest_lines(const Pack& p, const std::vector<SeqNode>& lines, bool after_rest, RestPlace at,
                      const std::string& source) {
    for (const auto& n : lines) {
        if (after_rest && is_wire_line(n))
            throw Error(ErrorKind::BadDirective, p.format, "",
                        source + ":" + std::to_string(n.line) +
                            ": a line after a 'rest' group or an 'inner' line in the same extent (each is the last "
                            "line of its extent)");
        switch (n.type) {
            // v0.34: an `inner` line is the last wire line of its extent, as a
            // `rest` group is (rulings 11, 26 and 32 of 0.21).
            case Type::Inner: after_rest = true; break;
            case Type::Group:
                if (n.repeat == Repeat::Rest) {
                    if (at.in_item && !at.rest_item)
                        throw Error(ErrorKind::BadDirective, p.format, "",
                                    source + ":" + std::to_string(n.line) + ": the 'rest' group '" + n.list +
                                        "' is inside an item, neither within a 'length' block of the item nor the "
                                        "last line of an outer 'rest' item");
                    after_rest = true;
                }
                check_rest_body(p, n.inner, false, RestPlace{true, n.repeat == Repeat::Rest}, source);
                break;
            case Type::Length: check_rest_lines(p, n.inner.lines, false, RestPlace{}, source); break;
            case Type::If:
            case Type::Opt:
            case Type::Chain: after_rest = check_rest_lines(p, n.inner.lines, after_rest, at, source); break;
            case Type::Switch: {
                bool any = false;
                for (const auto& c : n.cases) any = check_rest_lines(p, c.body.lines, after_rest, at, source) || any;
                after_rest = any;
                break;
            }
            // 0.21 ruling 42: an `ext` body is the extent around it, as an `if`
            // body is; each `alt` of a `choice` is checked as a `switch` case is.
            case Type::Ext: after_rest = check_rest_lines(p, n.inner.lines, after_rest, at, source); break;
            case Type::Choice: {
                bool any = false;
                for (const auto& a : n.inner.lines) any = check_rest_lines(p, a.inner.lines, after_rest, at, source) || any;
                after_rest = any;
                break;
            }
            default: break;
        }
    }
    return after_rest;
}

bool check_rest_body(const Pack& p, const SeqBody& body, bool after_rest, RestPlace at, const std::string& source) {
    const bool common = check_rest_lines(p, body.lines, after_rest, at, source);
    if (body.kinds.empty()) return common;
    bool any = false;
    for (const auto& k : body.kinds) any = check_rest_lines(p, k.lines, common, at, source) || any;
    return any;
}

// v0.30 ruling 9: in one reading path (a body's common lines plus one of its
// kinds), a key is named by one `when ... as` line at most, and a key named
// by `as` is mapped by no `field` or `also` line. A group body is a scope of
// its own (rulings 21 and 33).
void as_mapped(const std::vector<SeqNode>& lines, std::map<std::string, std::size_t>& fields,
               std::vector<const SeqBody*>& groups) {
    for (const auto& n : lines) {
        if (n.type == Type::Field) {
            fields.emplace(n.field.key, n.field.line);
            for (const auto& a : n.also) fields.emplace(a.key, a.line);
        } else if (n.type == Type::Group) {
            groups.push_back(&n.inner);
        } else {
            as_mapped(n.inner.lines, fields, groups);
            for (const auto& c : n.cases) as_mapped(c.body.lines, fields, groups);
        }
    }
}

// v0.33: is each window of a kind's `when ... at` lines fixed in the kind?
// Walk the kind's lines from its first, skipping the look-ahead `when` lines,
// summing the widths of `when` (plain), `const`, `pad` and bit-length `field`
// lines until the sum reaches the window's end. Any other line walked, or
// running out of lines first, makes the window not fixed. On success the kind
// keeps the number of lines the farthest window walked (for encode).
void settle_windows_of(Pack& p, SeqKind& k, const std::string& source) {
    std::size_t walked = 0;
    for (const auto& w : k.lines) {
        if (w.type != Type::When) break;
        if (!w.has_at) continue;
        const std::uint64_t end = w.at + w.len;
        bool fixed = w.at <= ~std::uint64_t{0} - w.len;
        std::uint64_t sum = 0;
        std::size_t i = 0;
        for (; fixed && i < k.lines.size() && sum < end; ++i) {
            const SeqNode& n = k.lines[i];
            if (n.type == Type::When && n.has_at) continue;
            const bool plain = n.type == Type::When || n.type == Type::Const || n.type == Type::Pad ||
                               (n.type == Type::Field && n.uper == SeqNode::Uper::None && !n.field.until);
            if (!plain) fixed = false;
            else sum += n.len;
        }
        if (fixed && sum < end) fixed = false;
        if (!fixed) {
            if (p.window_error.empty())
                p.window_error = source + ":" + std::to_string(w.line) + ": the window of 'when " +
                                 std::to_string(w.len) + " ... at " + std::to_string(w.at) +
                                 "' is not fixed in the kind '" + k.name + "'";
            return;
        }
        walked = std::max(walked, i);
    }
    k.window_lines = walked;
}

void check_windows(Pack& p, SeqBody& body, const std::string& source);

void check_windows_lines(Pack& p, std::vector<SeqNode>& lines, const std::string& source) {
    for (auto& n : lines) {
        if (n.type == Type::Group) check_windows(p, n.inner, source);
        else {
            check_windows_lines(p, n.inner.lines, source);
            for (auto& c : n.cases) check_windows_lines(p, c.body.lines, source);
        }
    }
}

void check_windows(Pack& p, SeqBody& body, const std::string& source) {
    check_windows_lines(p, body.lines, source);
    for (auto& k : body.kinds) {
        settle_windows_of(p, k, source);
        check_windows_lines(p, k.lines, source);
    }
}

void check_as_bans(const Pack& p, const SeqBody& body, const std::string& source) {
    auto refuse = [&](std::size_t line, const std::string& why) {
        throw Error(ErrorKind::BadDirective, p.format, "", source + ":" + std::to_string(line) + ": " + why);
    };
    auto as_lines = [&](const std::vector<SeqNode>& lines, std::map<std::string, std::size_t>& keys,
                        const std::map<std::string, std::size_t>* common) {
        for (const auto& n : lines) {
            if (n.type != Type::When || !n.has_as) continue;
            if (keys.count(n.field.key) || (common && common->count(n.field.key)))
                refuse(n.line, "two 'when ... as' lines of one reading path name '" + n.field.key + "'");
            keys.emplace(n.field.key, n.line);
        }
    };
    std::vector<const SeqBody*> groups;
    std::map<std::string, std::size_t> common_as, common_fields;
    as_lines(body.lines, common_as, nullptr);
    as_mapped(body.lines, common_fields, groups);
    for (const auto& a : common_as)
        if (common_fields.count(a.first))
            refuse(a.second, "the 'as' key '" + a.first + "' is also mapped by a 'field' or 'also' line");
    for (const auto& k : body.kinds) {
        std::map<std::string, std::size_t> kind_as, kind_fields;
        as_lines(k.lines, kind_as, &common_as);
        as_mapped(k.lines, kind_fields, groups);
        for (const auto& a : kind_as)
            if (common_fields.count(a.first) || kind_fields.count(a.first))
                refuse(a.second, "the 'as' key '" + a.first + "' is also mapped by a 'field' or 'also' line");
        for (const auto& a : common_as)
            if (kind_fields.count(a.first))
                refuse(a.second, "the 'as' key '" + a.first + "' is also mapped by a 'field' or 'also' line of kind '" +
                                     k.name + "'");
    }
    for (const SeqBody* g : groups) check_as_bans(p, *g, source);
}

// v0.92 ruling 16, in a pack with `framing self`: a `rest` group whose extent is
// the message needs a `length ... whole` line before it that is read whenever it
// is. `whole`: one stands before the lines, outside their block or in it.
// Returns that state after the lines.
bool check_framing_rest(const Pack& p, const std::vector<SeqNode>& lines, bool whole, const std::string& source) {
    for (const auto& n : lines) {
        switch (n.type) {
            case Type::LengthWhole: whole = true; break;
            case Type::Group:
                if (n.repeat == Repeat::Rest && !whole)
                    throw Error(ErrorKind::BadDirective, p.format, "",
                                source + ":" + std::to_string(n.line) + ": the 'rest' group '" + n.list +
                                    "' of a pack with 'framing self' runs to the end of the message, and no "
                                    "'length ... whole' is read before it");
                break;
            case Type::Length: break;  // an extent of its own
            case Type::Switch:
                for (const auto& c : n.cases) check_framing_rest(p, c.body.lines, whole, source);
                break;
            default: check_framing_rest(p, n.inner.lines, whole, source); break;
        }
    }
    return whole;
}

// v0.34: the `inner` lines of `lines` and the `length` blocks in them (the
// only blocks that may hold one), and the last of them.
std::size_t count_inner(const std::vector<SeqNode>& lines, std::size_t& last) {
    std::size_t n = 0;
    for (const auto& l : lines) {
        if (l.type == Type::Inner) {
            ++n;
            last = l.line;
        } else if (l.type == Type::Length) {
            n += count_inner(l.inner.lines, last);
        }
    }
    return n;
}

// v0.34: at most one `inner` line on any reading path (ruling 33 of 0.21):
// the common lines with each kind.
void check_inner_paths(const Pack& p, const SeqBody& body, const std::string& source) {
    std::size_t last = 0;
    const std::size_t common = count_inner(body.lines, last);
    auto fail = [&](std::size_t line) {
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(line) + ": a second 'inner' line on one reading path");
    };
    if (common > 1) fail(last);
    for (const auto& k : body.kinds) {
        std::size_t at = last;
        if (common + count_inner(k.lines, at) > 1) fail(at);
    }
}

}  // namespace

bool is_sequential_pack(const std::string& text) {
    static const std::string word = "layout";
    std::size_t at = 0;
    while ((at = text.find(word, at)) != std::string::npos) {
        // The first token of its line?
        std::size_t start = at;
        while (start > 0 && (text[start - 1] == ' ' || text[start - 1] == '\t')) --start;
        if (start == 0 || text[start - 1] == '\n') {
            std::size_t end = text.find('\n', at);
            if (end == std::string::npos) end = text.size();
            std::vector<std::string> t;
            std::string err;
            if (tokenize_line(text.substr(start, end - start), t, err) && t.size() >= 2 && t[0] == word &&
                t[1] == "sequential")
                return true;
        }
        at += word.size();
    }
    return false;
}

// ---------------------------------------------------------------- pack grammar

Pack parse_seq_pack(const std::string& text, const std::string& source) {
    Pack p;
    p.source = source;
    p.sequential = true;
    bool have_format = false, have_version = false, have_wire = false, have_distribution = false,
         have_bit_order = false, have_layout = false;
    std::set<std::string> natives;
    std::unordered_map<std::string, int> table_index;

    // The blocks that are open at this line, outermost first: the message, then
    // every `if`, `opt`, `chain`, `length` and `group` not yet closed. A block
    // stays the last line of its parent while it is open, so the pointers hold.
    struct Frame {
        Type type = Type::Pad;  // Pad stands for the message
        bool is_body = false;   // the message or a group: may hold kinds, `requires` and common `when` lines
        SeqBody* body = nullptr;
        std::size_t line = 0;
        std::string what;
        std::map<std::string, int> names;       // presence names declared in this block
        std::map<std::string, int> kind_names;  // those declared in the kind that is open
        // v0.21: count names declared in this block, and in the kind that is open.
        std::map<std::string, int> counts, kind_counts;
        bool declares(const std::string& n) const {
            return names.count(n) || kind_names.count(n) || counts.count(n) || kind_counts.count(n);
        }
        std::set<std::string> kinds;
        // v0.20. A body: the keys its `field` and `also` lines have mapped so
        // far, in the common lines and in the kind that is open.
        std::set<std::string> common_keys, kind_keys;
        // v0.20. A `switch` before its first `case`, and a `case` or `else`.
        bool is_switch = false, is_case = false, is_else = false;
        SeqNode* sw = nullptr;  // a switch: its node
        int parent_case = -1;   // a switch: the innermost case of its body holding it
        int case_id = -1;       // a case
    };
    std::vector<Frame> stack(1);
    stack[0].is_body = true;
    stack[0].body = &p.seq;
    stack[0].what = "the message";

    // The `field` an `also` line may follow: the last line, when it was a
    // `field` or an `also`.
    SeqNode* also_target = nullptr;
    std::size_t lineno = 0, pos = 0;
    // v0.14: `armor <hex | sixbit>`, checked after the file is read (ruling 10
    // of 0.10): the first error of its lines, and the first `kind` and
    // `length ... whole` lines.
    std::size_t armor_line = 0, first_kind_line = 0, whole_line = 0;
    std::string armor_error;
    // v0.19: `encoding <none | uper>`, checked after the file is read, and the
    // first UPER line (ruling 9), refused after the file is read when the pack
    // has no `encoding uper`.
    std::size_t encoding_line = 0, uper_line = 0;
    std::string encoding_error, uper_what;
    std::size_t framing_line = 0;  // v0.92
    // v0.30: the first syntax error of a `when ... as` line (ruling 16).
    std::string as_error;
    // v0.34: the first `inner` line, and the first one under a block other
    // than `length`, both checked after the file is read.
    std::size_t inner_line = 0;
    std::string inner_block_error;
    auto note_uper = [&](std::size_t line, const std::string& what) {
        if (uper_line == 0) {
            uper_line = line;
            uper_what = what;
        }
    };

    auto lines_of = [](Frame& f) -> std::vector<SeqNode>& {
        return f.body->kinds.empty() ? f.body->lines : f.body->kinds.back().lines;
    };
    auto body_frame = [&]() -> Frame& {
        for (std::size_t k = stack.size(); k-- > 0;)
            if (stack[k].is_body) return stack[k];
        return stack[0];
    };
    // v0.20: the innermost case of the innermost body; -1 when none. With
    // `across`, the innermost case at any depth.
    auto innermost_case = [&](bool across) -> int {
        for (std::size_t k = stack.size(); k-- > 0;) {
            if (stack[k].is_case) return stack[k].case_id;
            if (stack[k].is_body && !across) return -1;
        }
        return -1;
    };
    // v0.20: a key mapped by a `field` or `also` line, for the `switch` lines after it.
    auto mapped_key = [&](const std::string& key) {
        Frame& f = body_frame();
        (f.body->kinds.empty() ? f.common_keys : f.kind_keys).insert(key);
    };
    // A `when` before the first `kind` of a body with no `kind` (0.5 ruling 8).
    auto check_common_when = [&](const Frame& f) {
        if (!f.is_body || !f.body->kinds.empty()) return;
        for (const auto& n : f.body->lines)
            if (n.type == Type::When)
                throw Error(ErrorKind::BadDirective, p.format, "",
                            source + ":" + std::to_string(n.line) + ": 'when' in a body with no 'kind' line");
    };

    while (pos <= text.size()) {
        std::size_t nl = text.find('\n', pos);
        std::string line = text.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
        pos = nl == std::string::npos ? text.size() + 1 : nl + 1;
        ++lineno;

        std::vector<std::string> t;
        std::string err;
        if (!tokenize_line(line, t, err))
            throw Error(tokenize_kind(err), p.format, "", source + ":" + std::to_string(lineno) + ": " + err);
        if (t.empty()) continue;

        const std::string where = source + ":" + std::to_string(lineno);
        const std::string& kw = t[0];
        auto bad = [&](const std::string& why) -> Error {
            return Error(ErrorKind::BadDirective, p.format, "", where + ": " + why);
        };
        auto arity = [&](std::size_t n) {
            if (t.size() != n + 1)
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": '" + kw + "' takes " + std::to_string(n) + " argument(s), got " +
                                std::to_string(t.size() - 1));
        };
        auto once = [&](bool& seen) {
            if (seen) throw Error(ErrorKind::BadDirective, p.format, "", where + ": duplicate '" + kw + "'");
            seen = true;
        };
        // A bit length of 1 to 64 (0.8 ruling 14).
        auto small_len = [&](const std::string& s, const std::string& what) {
            std::uint32_t n = 0;
            if (s.find(':') != std::string::npos)
                throw bad("a positional <word>:<pos>:<len> locator in a sequential pack: '" + s + "'");
            if (!parse_u32(s, n) || n < 1 || n > 64) throw bad(what + " is 1 to 64 bits, not '" + s + "'");
            return n;
        };
        auto add = [&](SeqNode n) -> SeqNode& {
            n.line = lineno;
            std::vector<SeqNode>& lines = lines_of(stack.back());
            lines.push_back(std::move(n));
            return lines.back();
        };
        auto open = [&](SeqNode n, const std::string& what) {
            const Type type = n.type;
            SeqNode& node = add(std::move(n));
            Frame f;
            f.type = type;
            f.is_body = type == Type::Group;
            f.body = &node.inner;
            f.line = lineno;
            f.what = what;
            stack.push_back(std::move(f));
        };

        // v0.21: the count line `name` visible here, in the same group body
        // (rulings 9, 12, 15 and 24), as `form` (`count @`, `length @`) names it.
        auto visible_count = [&](const std::string& name, const std::string& form) -> int {
            if (name.empty()) throw bad("'" + form + "' names no count");
            for (std::size_t d = stack.size(); d-- > 0;) {
                const Frame& f = stack[d];
                auto it = f.kind_counts.find(name);
                if (it != f.kind_counts.end()) return it->second;
                it = f.counts.find(name);
                if (it != f.counts.end()) return it->second;
                if (f.kind_names.count(name) || f.names.count(name))
                    throw bad("'" + form + name + "' names a presence, not a count");
                if (f.is_body) break;  // a reference stays in its group body
            }
            throw bad("'" + form + name + "' names no count line visible here in the same group body");
        };

        SeqNode* const prev_field = also_target;
        also_target = nullptr;

        // v0.46: its errors, its place among them, are found after the file is read.
        if (kw == "charset") {
            add_charset(p, t, lineno, stack.size() > 1 || !p.seq.kinds.empty());
            continue;
        }

        // v0.20 ruling 20: the lines between `switch` and its first `case`.
        if (stack.back().is_switch && kw != "case" && kw != "end")
            throw bad("'" + kw + "' between 'switch' and its first 'case'");

        // Header and table directives describe the pack, not a part of the
        // message: inside any block they are bad-directive (0.8 ruling 24).
        if (stack.size() > 1 &&
            (kw == "format" || kw == "version" || kw == "distribution" || kw == "source" || kw == "uses" ||
             kw == "wire" || kw == "layout" || kw == "bit_order" || kw == "armor" || kw == "encoding" || kw == "map" ||
             kw == "typemap" || kw == "framing"))
            throw bad("'" + kw + "' is not allowed inside " + stack.back().what);
        // v0.19: a `choice` holds `alt` lines only.
        if (stack.back().type == Type::Choice && kw != "alt" && kw != "end")
            throw bad("'" + kw + "' between 'choice' and its first 'alt'");

        if (kw == "format") {
            arity(1);
            once(have_format);
            p.format = t[1];
        } else if (kw == "version") {
            arity(1);
            once(have_version);
            p.version = t[1];
        } else if (kw == "distribution") {
            arity(1);
            once(have_distribution);
            if (t[1] == "public") p.distribution = Distribution::Public;
            else if (t[1] == "controlled") p.distribution = Distribution::Controlled;
            else throw Error(ErrorKind::BadDirective, p.format, "", where + ": distribution '" + t[1] + "'");
        } else if (kw == "source") {
            arity(1);
            p.sources.push_back(t[1]);
        } else if (kw == "uses") {
            arity(1);
            if (std::find(p.uses.begin(), p.uses.end(), t[1]) == p.uses.end()) p.uses.push_back(t[1]);
        } else if (kw == "wire") {
            arity(1);
            once(have_wire);
            std::string why;
            if (!parse_wire_value(t[1], p.wire, why))
                throw Error(ErrorKind::UnknownWire, p.format, "", where + ": " + why);
        } else if (kw == "layout") {
            arity(1);
            once(have_layout);
            if (t[1] != "sequential") throw bad("layout '" + t[1] + "' in a pack that also has 'layout sequential'");
        } else if (kw == "word_bytes") {
            throw bad("'word_bytes' is not used in a sequential pack");
        } else if (kw == "checksum" && t.size() == 3 && (t[1] == "sum16" || t[1] == "crc32")) {
            throw bad("'checksum " + t[1] + "' applies to wire tlv only");
        } else if (kw == "delimiter" || kw == "start" || kw == "checksum") {
            throw bad("'" + kw + "' applies to wire text only");
        } else if (kw == "tag" || kw == "key") {
            throw bad("'" + kw + "' applies to wire tlv only");
        } else if (kw == "root") {
            throw bad("'root' applies to wire xml only");
        } else if (kw == "armor") {
            std::string why;
            if (t.size() != 2) why = "'armor' takes one value: hex or sixbit";
            else if (t[1] != "hex" && t[1] != "sixbit") why = "'armor' is hex or sixbit, not '" + t[1] + "'";
            else if (armor_line != 0) why = "'armor' appears twice";
            else if (first_kind_line != 0) why = "'armor' after the first 'kind'";
            if (!why.empty()) {
                if (armor_error.empty()) armor_error = where + ": " + why;
            } else {
                p.armor_sixbit = t[1] == "sixbit";
            }
            if (armor_line == 0) armor_line = lineno;
        } else if (kw == "framing") {
            // v0.92 ruling 16.
            arity(1);
            if (t[1] != "self") throw bad("'framing' is self, not '" + t[1] + "'");
            if (framing_line != 0) throw bad("a second 'framing' line");
            if (!p.seq.kinds.empty()) throw bad("'framing' after the first 'kind' of the message");
            framing_line = lineno;
            p.framing_self = true;
        } else if (kw == "encoding") {
            std::string why;
            if (t.size() != 2) why = "'encoding' takes one value: none or uper";
            else if (t[1] != "none" && t[1] != "uper") why = "'encoding' is none or uper, not '" + t[1] + "'";
            else if (encoding_line != 0) why = "'encoding' appears twice";
            else if (first_kind_line != 0) why = "'encoding' after the first 'kind'";
            if (!why.empty()) {
                if (encoding_error.empty()) encoding_error = where + ": " + why;
            } else {
                p.uper = t[1] == "uper";
            }
            if (encoding_line == 0) encoding_line = lineno;
        } else if (kw == "bit_order") {
            arity(1);
            once(have_bit_order);
            if (t[1] == "lsb") p.bit_order = BitOrder::Lsb;
            else if (t[1] == "msb") p.bit_order = BitOrder::Msb;
            else if (t[1] == "msb-lsb") p.bit_order = BitOrder::MsbLsb;  // v0.22
            else throw bad("bit_order '" + t[1] + "' is not lsb, msb or msb-lsb");
        } else if (kw == "map") {
            arity(3);
            auto it = table_index.find(t[1]);
            if (it == table_index.end()) {
                it = table_index.emplace(t[1], static_cast<int>(p.tables.size())).first;
                p.tables.emplace_back();
                p.tables.back().name = t[1];
            }
            p.tables[static_cast<std::size_t>(it->second)].entries.emplace_back(t[2], t[3]);
        } else if (kw == "typemap") {
            arity(2);
            if (!natives.insert(t[1]).second)
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": duplicate typemap code '" + t[1] + "'");
            p.typemap.emplace_back(t[1], t[2]);
        } else if (kw == "kind") {
            // A kind of the message, or of a group's items (Items by kind).
            Frame& f = stack.back();
            if (!f.is_body) throw bad("'kind' inside " + f.what);
            arity(1);
            if (!f.kinds.insert(t[1]).second)
                throw Error(ErrorKind::DuplicateKind, p.format, "",
                            where + ": kind '" + t[1] + "' is declared twice in " + f.what);
            f.body->kinds.emplace_back();
            f.body->kinds.back().name = t[1];
            f.body->kinds.back().line = lineno;
            f.kind_names.clear();
            if (first_kind_line == 0) first_kind_line = lineno;
            f.kind_counts.clear();
            f.kind_keys.clear();
        } else if (kw == "when") {
            // The `when` lines of a kind are its first lines; a `when` before
            // the first `kind` is a common one (0.8 ruling 10).
            Frame& f = stack.back();
            if (!f.is_body) throw bad("'when' inside " + f.what);
            // v0.30: `as <model-key>` after the values, and v0.33: `at <n>`
            // before it. Their errors are found after the file (0.30 ruling
            // 16; 0.33 ruling 10: the `at` form after the module checks); any
            // other third token is bad-directive here (0.20 ruling 23).
            std::string as_key;
            bool has_at = false, as_optional = false;
            std::uint64_t at_off = 0;
            auto at_form = [&](const std::string& why) {
                if (p.at_error.empty()) p.at_error = where + ": " + why;
            };
            if (t.size() > 3) {
                if (t[3] != "as" && t[3] != "at")
                    throw bad("'when' takes a bit length and one value list; a list has no spaces");
                if (when_holds_at(t)) {
                    // v0.33, v0.52: exactly `at <n> [as <k> [optional]]`. Any other
                    // order is an `at` form error and its key is not read (0.33
                    // rulings 27 and 28, 0.52 rulings 3 and 15).
                    const std::size_t n = t.size();
                    const bool ordered =
                        t[3] == "at" && n >= 5 && t[4] != "at" && t[4] != "as" && t[4] != "optional" &&
                        (n == 5 || ((n == 7 || (n == 8 && t[7] == "optional")) && t[5] == "as" && t[6] != "as"));
                    if (!ordered) {
                        at_form("the tokens of a 'when' line with 'at' are not "
                                "'when <len> <values> at <n> [as <key> [optional]]'");
                    } else {
                        has_at = true;
                        if (!parse_u64(t[4], at_off))
                            at_form("'at " + t[4] + "' is not plain decimal digits that fit 64 bits");
                        if (f.body->kinds.empty()) at_form("'when ... at' on a common 'when'");
                        if (n >= 7) as_key = t[6];  // read and checked even when the offset is bad
                        as_optional = n == 8;
                    }
                } else {
                    // v0.30: `as <model-key>`, v0.52: `[optional]`.
                    std::string why;
                    if (t.size() == 4) why = "'as' takes a model key";
                    for (std::size_t k = 4; k < t.size() && why.empty(); ++k)
                        if (t[k] == "as") why = "'as' twice on one 'when' line";  // 0.30 ruling 31
                    as_optional = t.size() > 5 && t[5] == "optional";
                    const std::size_t most = as_optional ? 6 : 5;
                    if (why.empty() && t.size() > most) why = "a token after the key of 'as': '" + t[most] + "'";
                    if (why.empty() && as_optional && f.body->kinds.empty())
                        why = "'optional' on a common 'when'";
                    if (why.empty()) as_key = t[4];
                    else if (as_error.empty()) as_error = where + ": " + why;
                }
            } else {
                arity(2);
            }
            for (const auto& n : lines_of(f))
                if (!f.body->kinds.empty() && n.type != Type::When)
                    throw bad("'when' after another line of its kind");
            SeqNode n;
            n.type = Type::When;
            n.len = small_len(t[1], "a 'when'");
            // v0.20: values and ranges.
            std::string why;
            if (!parse_when_numbers(t[2], n.len, n.ranges, why)) throw bad("'when' " + why);
            n.number = n.ranges.front().first;
            n.has_at = has_at;
            n.at = at_off;
            if (!as_key.empty()) {
                n.has_as = true;
                n.as_optional = as_optional;
                n.field.key = as_key;
                n.field.locator = t[1];
                n.field.line = lineno;
                n.field.transform = Transform::Uint;
                // Ruling 2: the key counts as mapped for a `switch` from here
                // (a kind's `when` lines are its first lines).
                mapped_key(as_key);
            }
            add(std::move(n));
        } else if (kw == "requires") {
            Frame& f = stack.back();
            if (!f.is_body) throw bad("'requires' inside " + f.what);
            if (f.body->kinds.empty()) throw bad("'requires' before the first 'kind'");
            if (t.size() < 2)
                throw Error(ErrorKind::BadDirective, p.format, "", where + ": 'requires' takes at least 1 argument");
            for (std::size_t k = 1; k < t.size(); ++k) {
                RequiresTerm term;
                std::string why;
                if (!parse_requires_term(t[k], lineno, term, why)) throw bad(why);
                f.body->kinds.back().requires_keys.push_back(term.key);
                f.body->kinds.back().requires_terms.push_back(std::move(term));
            }
        } else if (kw == "default") {
            // A `default` inside a block belongs to the message or item that holds the block.
            arity(2);
            DefaultLine d;
            d.key = t[1];
            d.text = t[2];
            d.line = lineno;
            // Inside a case it belongs to the innermost case (0.20 ruling 7).
            Frame* target = nullptr;
            for (std::size_t k = stack.size(); k-- > 0 && !target;)
                if (stack[k].is_case || stack[k].is_body) target = &stack[k];
            Frame& f = *target;
            if (f.is_case) f.body->defaults.push_back(std::move(d));
            else (f.body->kinds.empty() ? f.body->defaults : f.body->kinds.back().defaults).push_back(std::move(d));
        } else if (kw == "field") {
            if (t.size() < 4)
                throw Error(ErrorKind::BadDirective, p.format, "",
                            where + ": 'field' takes a key, a bit length and a transform, got " +
                                std::to_string(t.size() - 1) + " argument(s)");
            SeqNode n;
            n.type = Type::Field;
            FieldLine& f = n.field;
            f.key = t[1];
            f.locator = t[2];
            f.line = lineno;
            f.scase = innermost_case(false);
            if (is_uper_locator(f.locator)) {
                // v0.19: a locator whose bit length follows from its ASN.1 constraint.
                if (!parse_uper_locator(f.locator, n)) throw bad("'" + f.locator + "' is not a valid UPER locator");
                note_uper(lineno, "the locator '" + f.locator + "'");
                // The transform's name and parameters were checked as the line
                // was read (0.11 ruling 5b, step 7); a known transform the
                // locator does not take is bad-directive here (0.19 ruling 19).
                std::string terr;
                const int ptf = parse_any_transform(t[3], f, terr);
                if (ptf == -2)
                    throw Error(ErrorKind::UnknownTransform, p.format, f.locator,
                                where + ": " + terr + " for field '" + f.key + "'");
                if (ptf == -1) throw bad(terr + " for field '" + f.key + "'");
                using U = SeqNode::Uper;
                const Transform tf = f.transform;
                bool ok = false;
                switch (n.uper) {
                    case U::Int:
                    case U::IntExt:
                    case U::IntSemi:
                    case U::IntUn:
                        ok = tf == Transform::Uint || tf == Transform::Twos || tf == Transform::Uscale ||
                             tf == Transform::Sscale;
                        break;
                    case U::Enum:
                    case U::EnumExt: ok = tf == Transform::Uint; break;
                    case U::Chars: ok = tf == Transform::Ascii; break;
                    case U::Octets: ok = tf == Transform::Hex || tf == Transform::Utf8; break;
                    case U::None: break;
                }
                if (!ok)
                    throw bad("transform '" + std::string(transform_name(tf)) + "' does not apply to the locator '" +
                              f.locator + "'");
                for (std::size_t k = 4; k < t.size(); ++k) {
                    if (t[k] == "via") {
                        if (k + 1 >= t.size() || t[k + 1].empty() || !f.via.empty())
                            throw bad("'via' takes one table name, once");
                        f.via = t[++k];
                        continue;
                    }
                    // v0.18: `with` is a field option on every wire; a suppressed
                    // UPER field writes what an absent key writes (0.19 ruling 1).
                    if (t[k] == "with") {
                        if (k + 1 >= t.size() || t[k + 1].empty() || !f.with.empty())
                            throw bad("'with' takes one key, once");
                        f.with = t[++k];
                        continue;
                    }
                    // Ruling 22 of 0.19: the bits of a UPER locator depend on its
                    // value, so 0.9's raw value is not stated for it.
                    if (t[k] == "absent")
                        throw bad("'absent' does not apply to the UPER locator '" + f.locator + "'");
                    throw bad("'" + t[k] + "' is not a field option of a UPER locator, or is given twice");
                }
                mapped_key(t[1]);  // a `switch` key (0.20)
                also_target = &add(std::move(n));
                continue;
            }
            if (f.locator.compare(0, 6, "until:") == 0) {
                // v0.22: the characters up to a terminator code.
                f.until = true;
                if (!parse_term_code(f.locator.substr(6), f.until_code))
                    throw bad("the code of '" + f.locator + "' is not plain decimal digits");
            } else {
                if (f.locator.find(':') != std::string::npos)
                    throw bad("a positional <word>:<pos>:<len> locator in a sequential pack: '" + f.locator + "'");
                if (!parse_u32(f.locator, n.len))
                    throw bad("the locator of a sequential field is a bit length, not '" + f.locator + "'");
            }
            std::string terr;
            const int tf = parse_any_transform(t[3], f, terr);
            if (tf == -2)
                throw Error(ErrorKind::UnknownTransform, p.format, f.locator,
                            where + ": " + terr + " for field '" + f.key + "'");
            if (tf == -1) throw bad(terr + " for field '" + f.key + "'");
            // A transform of the text wire (v0.10) is bad-directive on another wire.
            if (transform_is_text_only(f.transform)) throw bad("transform '" + t[3] + "' applies to wire text only");
            // So is one of the tlv wire (v0.13).
            if (transform_is_tlv_only(f.transform)) throw bad("transform '" + t[3] + "' applies to wire tlv only");
            if (!transform_is_bits(f.transform))
                throw Error(ErrorKind::BadDirective, p.format, f.locator,
                            where + ": transform '" + std::string(transform_name(f.transform)) +
                                "' is not valid on wire bits");
            for (std::size_t k = 4; k < t.size(); ++k) {
                if (t[k] == "via") {
                    if (k + 1 >= t.size() || t[k + 1].empty() || !f.via.empty())
                        throw bad("'via' takes one table name, once");
                    f.via = t[++k];
                    continue;
                }
                // v0.9: `absent <value>[,<value>...]`; the next token is always its argument.
                if (t[k] == "absent") {
                    if (k + 1 >= t.size() || f.has_absent) throw bad("'absent' takes one argument, once");
                    f.has_absent = true;
                    f.absent_arg = t[++k];
                    continue;
                }
                // v0.18: `with <other-key>`, once.
                if (t[k] == "with") {
                    if (k + 1 >= t.size() || t[k + 1].empty() || !f.with.empty())
                        throw bad("'with' takes one key, once");
                    f.with = t[++k];
                    continue;
                }
                // v0.22: `stop <code>`, once.
                if (t[k] == "stop") {
                    if (k + 1 >= t.size() || f.has_stop || !parse_term_code(t[k + 1], f.stop_code))
                        throw bad("'stop' takes one code of plain decimal digits, once");
                    f.has_stop = true;
                    ++k;
                    continue;
                }
                bool* flag = t[k] == "swap" ? &f.swap : t[k] == "trim" ? &f.trim : nullptr;
                if (t[k] == "optional") throw bad("the field option 'optional' is not allowed in a sequential pack");
                if (!flag || *flag) throw bad("'" + t[k] + "' is not a field option, or is given twice");
                *flag = true;
            }
            // v0.22: `until:` takes `chars:<set>` and a code its width holds, and
            // no `absent`, `swap`, `trim` or `stop`; `stop` takes a `chars` field.
            if (f.until) {
                const unsigned w = chars_width(f.transform);
                if (!w) throw bad("the locator '" + f.locator + "' takes a 'chars:<set>' transform only");
                if (f.until_code >> w)
                    throw bad("the code of '" + f.locator + "' does not fit " + std::to_string(w) + " bits");
                if (f.has_absent || f.swap || f.trim || f.has_stop)
                    throw bad("the locator '" + f.locator + "' takes no 'absent', 'swap', 'trim' or 'stop'");
                n.len = w;  // its shortest form: the terminator alone
            }
            if (f.has_stop) {
                const unsigned w = chars_width(f.transform);
                if (!w) throw bad("option 'stop' applies to a 'chars' transform only");
                if (f.stop_code >> w)
                    throw bad("the 'stop' code " + std::to_string(f.stop_code) + " does not fit " + std::to_string(w) + " bits");
            }
            // The bit lengths a transform allows, and what `swap` and `trim` need.
            if (!f.until && !bits_len_allowed(f.transform, n.len))
                throw bad("transform '" + std::string(transform_name(f.transform)) + "' does not allow a length of " +
                          std::to_string(n.len) + " bits");
            if (f.trim && f.transform != Transform::Ascii && f.transform != Transform::Sixbit)
                throw bad("option 'trim' applies to transforms ascii and sixbit only");
            if (f.swap && (f.transform == Transform::Sixbit || chars_width(f.transform) || f.transform == Transform::Octal ||
                           f.transform == Transform::Hex))
                throw bad("option 'swap' does not apply to transform " + std::string(transform_name(f.transform)));
            if (f.swap && n.len % 8 != 0)
                throw bad("option 'swap' needs a length that is a multiple of 8 bits, not " + std::to_string(n.len));
            mapped_key(t[1]);
            also_target = &add(std::move(n));
        } else if (kw == "also") {
            // A second key on one field (0.8 ruling 13): the same bits through
            // the same transform, with a table of its own.
            if (!prev_field) throw bad("'also' is allowed directly after a 'field' line only");
            if (t.size() != 2 && !(t.size() == 4 && t[2] == "via" && !t[3].empty()))
                throw bad("'also' takes a key and, optionally, 'via <table>'");
            FieldLine f = prev_field->field;
            f.key = t[1];
            f.line = lineno;
            f.via = t.size() == 4 ? t[3] : std::string();
            f.table = -1;
            f.with.clear();  // `with` belongs to the field line (0.18 ruling 5)
            prev_field->also.push_back(std::move(f));
            mapped_key(t[1]);
            also_target = prev_field;
        } else if (kw == "const") {
            if (t.size() > 3 && t[3] == "with") throw bad("'with' applies to a 'field' line only");
            arity(2);
            SeqNode n;
            n.type = Type::Const;
            n.len = small_len(t[1], "a 'const'");
            if (!parse_u64(t[2], n.number))
                throw bad("'const' value '" + t[2] + "' is not an unsigned decimal integer");
            if (n.len < 64 && (n.number >> n.len) != 0)
                throw bad("'const' value " + t[2] + " does not fit " + std::to_string(n.len) + " bits");
            add(std::move(n));
        } else if (kw == "pad") {
            arity(1);
            SeqNode n;
            n.type = Type::Pad;
            if (!parse_u32(t[1], n.len)) throw bad("'pad' takes a number of bits, not '" + t[1] + "'");
            add(std::move(n));
        } else if (kw == "align") {
            arity(1);
            SeqNode n;
            n.type = Type::Align;
            if (!parse_u32(t[1], n.len) || n.len == 0) throw bad("'align' takes a positive number of bits, not '" + t[1] + "'");
            add(std::move(n));
        } else if (kw == "presence") {
            arity(2);
            Frame& f = stack.back();
            if (f.type == Type::Ext && !lines_of(f).empty())
                throw bad("a 'presence' line inside an 'ext' block is its first line");
            if (t[1].empty() || f.declares(t[1]))
                throw bad("the presence '" + t[1] + "' is declared twice in " + f.what);
            SeqPresence pr;
            pr.name = t[1];
            pr.line = lineno;
            if (t[2] == "fx") pr.fx = true;
            else pr.bits = small_len(t[2], "a presence");
            SeqNode n;
            n.type = Type::Presence;
            n.len = pr.bits;
            n.presence = static_cast<int>(p.seq_presences.size());
            (f.is_body && !f.body->kinds.empty() ? f.kind_names : f.names).emplace(t[1], n.presence);
            p.seq_presences.push_back(std::move(pr));
            add(std::move(n));
        } else if (kw == "if") {
            if (t.size() < 2) throw bad("'if' takes at least one <name>.<i>");
            SeqNode n;
            n.type = Type::If;
            n.in_case = innermost_case(true);
            for (std::size_t k = 1; k < t.size(); ++k) {
                SeqCond c;
                std::string s = t[k];
                if (!s.empty() && s[0] == '!') {
                    c.negated = true;
                    s.erase(0, 1);
                }
                const std::size_t dot = s.rfind('.');
                if (dot == std::string::npos || dot == 0 || !parse_u32(s.substr(dot + 1), c.bit) || c.bit == 0)
                    throw bad("'" + t[k] + "' is not <name>.<i> or !<name>.<i>");
                // The name is visible from its `presence` line to the end of the
                // block that holds it; a nested block may hide it.
                const std::string name = s.substr(0, dot);
                std::size_t found = 0;
                for (std::size_t d = stack.size(); d-- > 0 && c.presence < 0;) {
                    // v0.21 ruling 15: counts and presences share one namespace.
                    if (stack[d].kind_counts.count(name) || stack[d].counts.count(name))
                        throw bad("'if' names '" + name + "', which is a count, not a presence");
                    auto it = stack[d].kind_names.find(name);
                    if (it == stack[d].kind_names.end()) {
                        it = stack[d].names.find(name);
                        if (it == stack[d].names.end()) continue;
                    }
                    c.presence = it->second;
                    found = d;
                }
                // The innermost case that holds the `if` and not the presence,
                // across group bodies (0.20 rulings 21 and 30); -1 when none.
                int in_case = -1;
                if (c.presence >= 0)
                    for (std::size_t d = stack.size(); d-- > found + 1 && in_case < 0;)
                        if (stack[d].is_case) in_case = stack[d].case_id;
                if (c.presence < 0) throw bad("'if' names the presence '" + name + "', which is not visible here");
                SeqPresence& pr = p.seq_presences[static_cast<std::size_t>(c.presence)];
                if (!pr.fx && c.bit > pr.bits)
                    throw bad("'if' names bit " + std::to_string(c.bit) + " of the presence '" + name + "', which has " +
                              std::to_string(pr.bits));
                // An `if` inside a case counts only when that case is read (0.20 ruling 21).
                if (in_case >= 0) {
                    if (pr.case_named.size() < c.bit) pr.case_named.resize(c.bit);
                    pr.case_named[c.bit - 1].push_back(in_case);
                } else {
                    if (pr.named.size() < c.bit) pr.named.resize(c.bit, false);
                    pr.named[c.bit - 1] = true;
                }
                pr.max_named = std::max(pr.max_named, c.bit);
                n.conds.push_back(c);
            }
            open(std::move(n), "an 'if' block");
        } else if (kw == "opt") {
            arity(0);
            SeqNode n;
            n.type = Type::Opt;
            open(std::move(n), "an 'opt' block");
        } else if (kw == "chain") {
            arity(0);
            SeqNode n;
            n.type = Type::Chain;
            open(std::move(n), "a 'chain'");
        } else if (kw == "fx") {
            if (stack.back().type != Type::Chain) throw bad("'fx' is a line of a 'chain'");
            arity(0);
            SeqNode n;
            n.type = Type::Fx;
            add(std::move(n));
        } else if (kw == "length") {
            // `length <len> [bytes|bits] [plus <n>]` and a block, or
            // `length <len> [bytes] [plus <n>] whole` (0.8 ruling 8).
            if (t.size() < 2) throw bad("'length' takes a bit length");
            SeqNode n;
            n.type = Type::Length;
            if ((!t[1].empty() && t[1][0] == '@') || std::find(t.begin() + 1, t.end(), "units") != t.end()) {
                // v0.83: `length @<name> units <u>`, sized by a count line.
                std::uint64_t u = 0;
                if (t.size() != 4 || t[1].empty() || t[1][0] != '@' || t[2] != "units")
                    throw bad("a 'length' sized by a count is 'length @<name> units <u>'");
                if (!parse_u64(t[3], u) || u < 1 || u > 65535)
                    throw bad("'units' takes plain digits from 1 to 65535, not '" + t[3] + "'");
                n.count_id = visible_count(t[1].substr(1), "length @");
                n.unit_size = static_cast<std::uint32_t>(u);
                n.unit_bits = u % 8 != 0;
                open(std::move(n), "a 'length' block");
                continue;
            }
            n.len = small_len(t[1], "a length field");
            bool unit = false, plus = false, whole = false;
            for (std::size_t k = 2; k < t.size(); ++k) {
                if ((t[k] == "bytes" || t[k] == "bits") && !unit) {
                    unit = true;
                    n.unit_bits = t[k] == "bits";
                } else if (t[k] == "plus" && !plus && k + 1 < t.size() && parse_i64(t[k + 1], n.plus)) {
                    plus = true;
                    ++k;
                } else if (t[k] == "whole" && !whole) {
                    whole = true;
                } else {
                    throw bad("after its bit length a 'length' takes 'bytes' or 'bits', 'plus <n>' and 'whole', each once; got '" +
                              t[k] + "'");
                }
            }
            if (whole) {
                if (n.unit_bits) throw bad("'length ... whole' counts bytes; 'bits' is not allowed with it");
                n.type = Type::LengthWhole;
                add(std::move(n));
                if (whole_line == 0) whole_line = lineno;
            } else {
                open(std::move(n), "a 'length' block");
            }
        } else if (kw == "group") {
            // `group <list> count <len>`, or `group <list> while | more | fx`.
            SeqNode n;
            n.type = Type::Group;
            if (t.size() >= 2) n.list = t[1];
            if (t.size() >= 4 && t[2] == "count" && ((!t[3].empty() && t[3][0] == '@') || t.size() > 4)) {
                // v0.21: `count @<name>`, a count line visible here in the same
                // group body (rulings 9, 12, 15 and 24). v0.31: `count @<a> @<b>`,
                // two such count lines, which must agree.
                if (t.size() > 5) throw bad("'count' on a group takes one or two '@<name>', not " +
                                            std::to_string(t.size() - 3) + " tokens");
                n.repeat = Repeat::CountRef;
                std::vector<std::string> names;
                for (std::size_t k = 3; k < t.size(); ++k) {
                    if (t[k].empty() || t[k][0] != '@')
                        throw bad("a token after 'count' on a group is '@<name>', not '" + t[k] + "'");
                    const std::string name = t[k].substr(1);
                    if (std::find(names.begin(), names.end(), name) != names.end())
                        throw bad("'count @" + name + " @" + name + "' names one count twice");
                    names.push_back(name);
                    (k == 3 ? n.count_id : n.count_id2) = visible_count(name, "count @");
                }
            } else if (t.size() == 4 && t[2] == "count") {
                n.repeat = Repeat::Count;
                n.len = small_len(t[3], "a count");
            } else if (t.size() == 3 && (t[2] == "while" || t[2] == "more" || t[2] == "fx" || t[2] == "rest" ||
                                         t[2] == "last")) {
                n.repeat = t[2] == "while" ? Repeat::While
                           : t[2] == "more" ? Repeat::More
                           : t[2] == "fx"   ? Repeat::Fx
                           : t[2] == "rest" ? Repeat::Rest
                                            : Repeat::Last;
            } else if ((t.size() == 3 || t.size() == 5) && t[2] == "size") {
                // v0.19: SEQUENCE OF, `size <lb> <ub>` or no size constraint.
                n.repeat = Repeat::Size;
                if (t.size() == 5) {
                    n.bounded = true;
                    if (!parse_uper_count(t[3], n.lb) || !parse_uper_count(t[4], n.ub) || n.lb < 0 || n.lb > n.ub ||
                        n.ub >= 65536)
                        throw bad("'size <lb> <ub>' needs 0 <= lb <= ub < 65536");
                }
                note_uper(lineno, "'group ... size'");
            } else {
                throw bad("a group of a sequential pack is 'group <list> count <len> | count @<name>' or "
                          "'group <list> while | more | fx | rest | last'");
            }
            open(std::move(n), "the group '" + t[1] + "'");
        } else if (kw == "ext") {
            // v0.19: a SEQUENCE with an extension marker.
            arity(0);
            note_uper(lineno, "'ext'");
            SeqNode n;
            n.type = Type::Ext;
            open(std::move(n), "an 'ext' block");
        } else if (kw == "choice") {
            // v0.19: `choice <n> [ext]`, then `alt <i>` lines.
            if (t.size() != 2 && !(t.size() == 3 && t[2] == "ext"))
                throw bad("'choice' takes a number of alternatives and, optionally, 'ext'");
            std::int64_t count = 0;
            if (!parse_uper_count(t[1], count) || count < 1 || count > 65536)
                throw bad("'choice' takes 1 to 65536 alternatives, not '" + t[1] + "'");
            note_uper(lineno, "'choice'");
            SeqNode n;
            n.type = Type::Choice;
            n.number = static_cast<std::uint64_t>(count);
            n.uext = t.size() == 3;
            open(std::move(n), "a 'choice'");
        } else if (kw == "alt") {
            arity(1);
            if (stack.back().type == Type::Alt) stack.pop_back();
            if (stack.back().type != Type::Choice) throw bad("'alt' outside a 'choice'");
            std::int64_t index = 0;
            const std::vector<SeqNode>& alts = lines_of(stack.back());
            // The choice node: the last line of the block that holds it.
            Frame& outer = stack[stack.size() - 2];
            const SeqNode& ch = lines_of(outer).back();
            if (!parse_uper_count(t[1], index) || static_cast<std::uint64_t>(index) >= ch.number)
                throw bad("'alt " + t[1] + "' is not an index from 0 to " + std::to_string(ch.number - 1));
            for (const auto& a : alts)
                if (a.number == static_cast<std::uint64_t>(index)) throw bad("'alt " + t[1] + "' is given twice");
            note_uper(lineno, "'alt'");
            SeqNode n;
            n.type = Type::Alt;
            n.number = static_cast<std::uint64_t>(index);
            open(std::move(n), "an 'alt'");
        } else if (kw == "count") {
            // v0.21: `count <name> <len> [plus <n>]`.
            if (t.size() < 3) throw bad("'count' takes a name and a bit length");
            const std::string& name = t[1];
            if (name.empty() || name.find_first_of(".!@") != std::string::npos)
                throw bad("the count name '" + name + "' is empty or holds '.', '!' or '@'");
            Frame& f = stack.back();
            if (f.declares(name)) throw bad("the name '" + name + "' is declared twice in " + f.what);
            SeqNode n;
            n.type = Type::Count;
            n.count_name = name;
            n.len = small_len(t[2], "a count");
            bool plus = false;
            for (std::size_t k = 3; k < t.size(); ++k) {
                if (t[k] == "plus" && !plus && k + 1 < t.size() && parse_plus(t[k + 1], n.plus)) {
                    plus = true;
                    ++k;
                } else {
                    throw bad("after its bit length a 'count' takes 'plus <n>' once, a signed decimal integer; got '" +
                              t[k] + (k + 1 < t.size() ? " " + t[k + 1] : std::string()) + "'");
                }
            }
            n.count_id = static_cast<int>(p.seq_count_lines++);
            (f.is_body && !f.body->kinds.empty() ? f.kind_counts : f.counts).emplace(name, n.count_id);
            add(std::move(n));
        } else if (kw == "switch") {
            // v0.20: `switch <model-key>`, a key mapped earlier in the scope.
            if (t.size() != 2 || t[1].empty()) throw bad("'switch' takes one model key");
            Frame& bf = body_frame();
            if (!bf.common_keys.count(t[1]) && !bf.kind_keys.count(t[1]))
                throw bad("the 'switch' key '" + t[1] + "' is not mapped by a 'field' or 'also' line before it in " +
                          bf.what);
            SeqNode n;
            n.type = Type::Switch;
            n.field.key = t[1];
            n.field.line = lineno;
            const int parent_case = innermost_case(false);
            SeqNode& node = add(std::move(n));
            Frame f;
            f.type = Type::Switch;
            f.is_switch = true;
            f.sw = &node;
            f.body = &node.inner;
            f.parent_case = parent_case;
            f.line = lineno;
            f.what = "a 'switch'";
            stack.push_back(std::move(f));
        } else if (kw == "case" || kw == "else") {
            const bool is_else = kw == "else";
            if (stack.back().is_case) {
                if (stack.back().is_else)
                    throw bad(is_else ? "a 'switch' with two 'else'" : "'case' after the 'else' of its switch");
                stack.pop_back();
            }
            if (!stack.back().is_switch) throw bad("'" + kw + "' outside a 'switch'");
            Frame& sf = stack.back();
            if (is_else && sf.sw->cases.empty()) throw bad("'else' before the first 'case'");
            SeqCase c;
            c.is_else = is_else;
            c.line = lineno;
            if (is_else) {
                if (t.size() != 1) throw bad("'else' takes no argument");
            } else {
                if (t.size() != 2) throw bad("'case' takes one value list; a list has no spaces");
                if (!split_value_list(t[1], c.values)) throw bad("the 'case' list '" + t[1] + "' has an empty value");
            }
            c.id = static_cast<int>(p.seq_cases.size());
            p.seq_cases.push_back(SeqCaseScope{sf.parent_case});
            sf.sw->cases.push_back(std::move(c));
            Frame f;
            f.type = Type::Switch;
            f.is_case = true;
            f.is_else = is_else;
            f.case_id = sf.sw->cases.back().id;
            f.body = &sf.sw->cases.back().body;
            f.line = lineno;
            f.what = is_else ? "an 'else'" : "a 'case'";
            stack.push_back(std::move(f));
        } else if (kw == "end") {
            if (stack.size() < 2) throw bad("'end' with no open block");
            arity(0);
            if (stack.back().is_switch) throw bad("a 'switch' with no 'case'");
            if (stack.back().type == Type::Choice) throw bad("a 'choice' with no 'alt' line");
            if (stack.back().is_case) {
                stack.pop_back();  // the last case; `end` closes its switch (0.20)
                stack.pop_back();
            } else {
                if (stack.back().type == Type::Alt) stack.pop_back();  // the `end` closes the choice (0.19)
                check_common_when(stack.back());
                stack.pop_back();
            }
        } else if (kw == "inner") {
            // v0.34: `inner <format> [partial]`, in the common lines, a kind and `length`
            // blocks only; the format is looked up when the line is reached.
            if (t.size() != 3) arity(1);
            if (t.size() == 3 && t[2] != "partial" && t[2] != "run" && inner_block_error.empty())
                inner_block_error = where + ": 'inner' takes a format and 'partial' or 'run', got '" + t[2] + "'";
            if (inner_block_error.empty())
                for (std::size_t k = 1; k < stack.size(); ++k)
                    if (stack[k].type != Type::Length) {
                        inner_block_error = where + ": 'inner' inside " + stack[k].what +
                                            " (it stands in the common lines, a kind or 'length' blocks only)";
                        break;
                    }
            if (inner_line == 0) inner_line = lineno;
            SeqNode n;
            n.type = Type::Inner;
            n.inner_format = t[1];
            n.inner_partial = t.size() == 3 && t[2] == "partial";
            n.inner_run = t.size() == 3 && t[2] == "run";  // v0.92
            p.carrier = p.carrier || n.inner_run;
            p.inner_formats.push_back(t[1]);
            add(std::move(n));
        } else if (kw == "element") {
            throw bad("'element' applies to wire xml only");
        } else {
            throw Error(ErrorKind::UnknownDirective, p.format, "", where + ": directive '" + kw + "'");
        }
    }

    // Checks that need the whole file, before `missing-distribution`.
    if (!have_format || p.format.empty()) throw Error(ErrorKind::MissingFormat, "", "", source + ": missing 'format'");
    if (!have_wire) throw Error(ErrorKind::MissingWire, p.format, "", source + ": missing 'wire'");
    // v0.30 ruling 16: the syntax of `as`, then the bans that need only key names.
    if (!as_error.empty()) throw Error(ErrorKind::BadDirective, p.format, "", as_error);
    check_as_bans(p, p.seq, source);
    check_windows(p, p.seq, source);  // v0.33: raised by Engine::add_pack (ruling 10)
    if (stack.size() > 1) {
        const Frame& f = stack.back().is_case ? stack[stack.size() - 2] : stack.back();
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(f.line) + ": " + f.what + " has no 'end'");
    }
    check_common_when(stack[0]);
    if (have_wire && p.wire != Wire::Bits)
        throw Error(ErrorKind::BadDirective, p.format, "", source + ": 'layout sequential' applies to wire bits only");
    if (!armor_error.empty()) throw Error(ErrorKind::BadDirective, p.format, "", armor_error);
    if (p.armor_sixbit && p.bit_order != BitOrder::Msb)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(armor_line) + ": 'armor sixbit' needs 'bit_order msb'");
    // v0.19: `encoding uper` and the lines it allows.
    if (!encoding_error.empty()) throw Error(ErrorKind::BadDirective, p.format, "", encoding_error);
    if (p.uper && p.bit_order != BitOrder::Msb)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(encoding_line) + ": 'encoding uper' needs 'bit_order msb'");
    if (p.uper && p.armor_sixbit)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(encoding_line) + ": 'encoding uper' with 'armor sixbit'");
    if (!p.uper && uper_line != 0)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(uper_line) + ": " + uper_what + " needs 'encoding uper'");
    // Ruling 3 of 0.14: the armored text has no whole-byte length.
    if (p.armor_sixbit && whole_line != 0)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(whole_line) + ": 'length ... whole' in a pack with 'armor sixbit'");
    // v0.34: where an `inner` line stands, and the packs that may hold one.
    if (!inner_block_error.empty()) throw Error(ErrorKind::BadDirective, p.format, "", inner_block_error);
    // `armor hex`, the default, is not armor in this sense.
    if (inner_line != 0 && (p.armor_sixbit || p.uper))
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(inner_line) + ": 'inner' in a pack with " +
                        (p.armor_sixbit ? "'armor sixbit'" : "'encoding uper'"));
    if (inner_line != 0) check_inner_paths(p, p.seq, source);
    if (p.framing_self) {
        if (p.armor_sixbit || p.uper)
            throw Error(ErrorKind::BadDirective, p.format, "",
                        source + ":" + std::to_string(framing_line) + ": 'framing self' in a pack with " +
                            (p.armor_sixbit ? "'armor sixbit'" : "'encoding uper'"));
        const bool whole = check_framing_rest(p, p.seq.lines, false, source);
        for (const auto& k : p.seq.kinds) check_framing_rest(p, k.lines, whole, source);
    }
    check_lists_once(p, p.seq, source);
    check_count_refs_body(p, p.seq, source);
    check_rest_body(p, p.seq, false, RestPlace{}, source);
    // `via` names a table of the pack; a `map` line may follow the field.
    auto resolve = [&](FieldLine& f) {
        if (f.via.empty()) return;
        auto it = table_index.find(f.via);
        if (it == table_index.end())
            throw Error(ErrorKind::BadDirective, p.format, f.locator,
                        source + ":" + std::to_string(f.line) + ": 'via " + f.via + "' names a table with no 'map' line");
        f.table = it->second;
    };
    check_charsets(p);
    auto resolve_node = [&](SeqNode& n) {
        if (n.type != Type::Field) return;
        resolve_code_sets(p, n.field, n.uper == SeqNode::Uper::None ? &n.len : nullptr);
        for (auto& a : n.also) resolve_code_sets(p, a, n.uper == SeqNode::Uper::None ? &n.len : nullptr);
        resolve(n.field);
        resolve_absent(p, Wire::Bits, n.field, n.len);
        for (auto& a : n.also) {
            resolve(a);
            resolve_absent(p, Wire::Bits, a, n.len);
        }
    };
    each_node(p.seq.lines, resolve_node);
    for (auto& k : p.seq.kinds) each_node(k.lines, resolve_node);

    if (!have_distribution)
        throw Error(ErrorKind::MissingDistribution, p.format, "", source + ": pack has no 'distribution'");
    if (p.sources.empty()) throw Error(ErrorKind::MissingSource, p.format, "", source + ": pack has no 'source'");
    return p;
}

// ---------------------------------------------------------------- walks

namespace {
void visit_lines(std::vector<SeqNode>& lines, const SeqVisitor& v);

void visit_body(SeqBody& body, const SeqVisitor& v) {
    visit_lines(body.lines, v);
    if (v.default_line)
        for (auto& d : body.defaults) v.default_line(d);
    for (auto& k : body.kinds) {
        if (v.kind) v.kind(k);
        if (v.requires_key)
            for (auto& r : k.requires_keys) v.requires_key(r);
        visit_lines(k.lines, v);
        if (v.default_line)
            for (auto& d : k.defaults) v.default_line(d);
    }
}

void visit_lines(std::vector<SeqNode>& lines, const SeqVisitor& v) {
    for (auto& n : lines) {
        if (n.type == Type::Field && v.field) {
            v.field(n.field);
            for (auto& a : n.also) v.field(a);
        }
        if (n.type == Type::When && n.has_as && v.field) v.field(n.field);  // v0.30
        if (n.type == Type::Group && v.group) v.group(n);
        if (n.type == Type::Switch && v.switch_node) v.switch_node(n);
        visit_body(n.inner, v);
        for (auto& c : n.cases) visit_body(c.body, v);
    }
}

void keys_of_lines(const std::vector<SeqNode>& lines, const std::string& prefix,
                   const std::function<void(const std::string&)>& add,
                   const std::function<void(const std::string&)>* inner) {
    for (const auto& n : lines) {
        if (n.type == Type::Field) {
            add(prefix + n.field.key);
            for (const auto& a : n.also) add(prefix + a.key);
        } else if (n.type == Type::When) {
            if (n.has_as) add(prefix + n.field.key);  // v0.30 ruling 5
        } else if (n.type == Type::Group) {
            add(prefix + n.list + "[]");
            seq_model_keys(n.inner, prefix + n.list + "[].", add, inner);
        } else if (n.type == Type::Inner) {
            if (inner) (*inner)(n.inner_format);  // v0.34: at its place in reading order
        } else {
            keys_of_lines(n.inner.lines, prefix, add, inner);
            for (const auto& c : n.cases) keys_of_lines(c.body.lines, prefix, add, inner);  // 0.20 ruling 13
        }
    }
}
}  // namespace

void seq_visit(SeqBody& body, const SeqVisitor& v) { visit_body(body, v); }

void seq_model_keys(const SeqBody& body, const std::string& prefix,
                    const std::function<void(const std::string&)>& add,
                    const std::function<void(const std::string&)>* inner) {
    keys_of_lines(body.lines, prefix, add, inner);
    for (const auto& k : body.kinds) keys_of_lines(k.lines, prefix, add, inner);
}

// The codec of the sequential layout is part of the bits wire (0.24 ruling 1d);
// the pack grammar above is read in every build.
#if GT_WIRE_BITS

// ---------------------------------------------------------------- decode

namespace {

const std::uint64_t kNoExtent = ~std::uint64_t{0};

struct SeqIn {
    const Pack& p;
    const std::string& data;
    BitMode msb;
    std::uint64_t have;                // bits of input, or of the message a `length ... whole` states
    std::uint64_t ext = kNoExtent;     // where the innermost `length` block ends
    std::uint64_t cur = 0;             // the cursor
    std::vector<std::vector<bool>> presence;  // by SeqPresence index: the bits last read
    // The first transform failure. It is kept until the whole message has been
    // read, so that input that is too short is malformed-wire first.
    bool failed = false;
    std::string fail_locator, fail_detail;
    // v0.20 ruling 21: a presence bit that is 1 and that only `if` lines inside
    // cases name holds when one of those cases is read after the bit.
    struct Pending {
        int presence;
        std::size_t bit;  // from 0
        std::uint64_t tick;
    };
    std::vector<Pending> pending;
    std::vector<std::uint64_t> case_read;  // by case id: the tick it was last read at; 0 = never
    std::vector<int> open_cases;           // the cases being read, outermost first
    std::uint64_t tick = 0;
    bool ext_bits = false;                 // v0.21: the innermost `length` block is counted in bits
    // v0.21, by count line: whether its last reading was on the wire (0 when
    // it lay at or past the end of its extent), and the items it stated.
    std::vector<char> count_set{};
    std::vector<std::uint64_t> counts{};
    // v0.34: what serves the `inner` lines, and the message being decoded.
    const InnerHost* host = nullptr;
    Entity* root = nullptr;
    // v0.83: a `length @` block is around the line. By count line: a `length @`
    // block of it was read, and one was passed over. The count lines read in
    // the bodies being read, in order.
    bool in_units = false;
    std::vector<char> units_read{}, units_passed{};
    std::vector<const SeqNode*> counts_read{};
    // v0.92: where the message starts in `data`, in bits (a whole byte); every
    // place counts from there. `strict`: a message of a run, in which a `switch`
    // on a key one of whose lines failed ends the decode, forgiven or not (ruling 3).
    std::uint64_t base = 0;
    bool strict = false;
    bool whole = false;  // v0.34 ruling 13: a `length ... whole` was read; `have` is what it states

    [[noreturn]] void malformed(const std::string& why) const {
        throw Error(ErrorKind::MalformedWire, p.format, "", why + " (at bit " + std::to_string(cur) + " of " +
                                                                std::to_string(data.size()) + " bytes)");
    }
    // Are `len` bits at the cursor there to read? False when the line starts at
    // or after the end of a `length` extent and so reads as absent; a line that
    // straddles that end, or the end of the input, is malformed-wire.
    bool need(std::uint64_t len, const char* what) const {
        if (ext != kNoExtent) {
            if (cur >= ext) return false;
            if (len > ext - cur) malformed(std::string(what) + " runs past the end of its 'length' extent");
        }
        if (cur > have || len > have - cur) malformed(std::string("the input ends inside ") + what);
        return true;
    }
    std::uint64_t take(std::uint32_t len) {
        const std::uint64_t v = read_bits(data, base + cur, len, msb);
        cur += len;
        return v;
    }
    bool bit(const SeqCond& c) const {
        const std::vector<bool>& v = presence[static_cast<std::size_t>(c.presence)];
        return c.bit <= v.size() && v[c.bit - 1];
    }
    // v0.19. Has the cursor reached the end of the `length` extent, so that the
    // line reads as absent?
    bool at_extent_end() const { return ext != kNoExtent && cur >= ext; }
    // The bits left before the end of the input or of the extent.
    std::uint64_t left() const {
        const std::uint64_t end = ext != kNoExtent ? std::min(ext, have) : have;
        return cur < end ? end - cur : 0;
    }
    // The bits a count is compared with (0.8 ruling 14): those of the extent,
    // and of the input too inside a `length @` block, which a whole length may cut.
    std::uint64_t bits_left() const {
        if (ext == kNoExtent || in_units) return left();
        return cur < ext ? ext - cur : 0;
    }
    // `len` bits (0 to 64) that the input must hold.
    std::uint64_t must(std::uint32_t len, const char* what) {
        if (len == 0) return 0;
        if (len > left()) malformed(std::string("the input ends inside ") + what);
        return take(len);
    }
    // Skip `bits` bits that the input must hold.
    void skip(std::uint64_t bits, const char* what) {
        if (bits > left()) malformed(std::string("the input cannot hold ") + what);
        cur += bits;
    }
    // A failure that belongs to no field (an extension index beyond 64 bits).
    void fail(const std::string& why) {
        if (failed) return;
        failed = true;
        fail_locator.clear();
        fail_detail = why;
    }
};

// ---------------------------------------------------------------- X.691 terms (0.19)

// The fewest bits that hold `range`: 0 for 0.
std::uint32_t bits_for(std::uint64_t range) {
    std::uint32_t b = 0;
    while (b < 64 && (range >> b) != 0) ++b;
    return b;
}

// A 64-bit pattern as the signed value it holds in two's complement.
std::int64_t as_signed(std::uint64_t u) {
    return u <= static_cast<std::uint64_t>(INT64_MAX) ? static_cast<std::int64_t>(u)
                                                       : -static_cast<std::int64_t>(~u) - 1;
}

std::uint64_t as_unsigned(std::int64_t v) {
    return v >= 0 ? static_cast<std::uint64_t>(v) : ~static_cast<std::uint64_t>(-(v + 1));
}

// A constrained whole number in lb..ub; above ub is malformed-wire.
std::int64_t read_constrained(SeqIn& in, std::int64_t lb, std::int64_t ub, const char* what) {
    const std::uint64_t range = as_unsigned(ub) - as_unsigned(lb);
    const std::uint64_t off = in.must(bits_for(range), what);
    if (off > range) in.malformed(std::string(what) + " lies outside its constraint");
    return as_signed(as_unsigned(lb) + off);
}

// A length determinant; a fragmented length is malformed-wire.
std::uint64_t read_length(SeqIn& in, const char* what) {
    if (in.must(1, what) == 0) return in.must(7, what);
    if (in.must(1, what) == 0) return in.must(14, what);
    in.malformed(std::string("a fragmented length for ") + what);
}

// The octet count of an integer, then its octets: false, the octets skipped,
// when there are more than 8; an octet count of 0 is malformed-wire.
bool read_int_octets(SeqIn& in, std::uint64_t& raw, std::uint32_t& octets, const char* what) {
    const std::uint64_t n = read_length(in, what);
    // In order (ruling 20): the input holds the octets, the count is not 0, then
    // (for the caller) the value fits.
    if (n * 8 > in.left()) in.malformed(std::string("the input cannot hold the octets of ") + what);
    if (n == 0) in.malformed(std::string("an integer of 0 octets for ") + what);
    if (n > 8) {
        in.skip(n * 8, what);
        return false;
    }
    octets = static_cast<std::uint32_t>(n);
    raw = in.must(octets * 8, what);
    return true;
}

std::int64_t sign_extend_octets(std::uint64_t raw, std::uint32_t octets) {
    if (octets < 8 && (raw >> (8 * octets - 1)) & 1u) raw |= ~std::uint64_t{0} << (8 * octets);
    return as_signed(raw);
}

// A normally small non-negative whole number: false when its long form has
// more than 8 octets.
bool read_small(SeqIn& in, std::uint64_t& out, const char* what) {
    if (in.must(1, what) == 0) {
        out = in.must(6, what);
        return true;
    }
    std::uint32_t octets = 0;
    return read_int_octets(in, out, octets, what);
}

// An open type: skipped.
void skip_open_type(SeqIn& in) {
    const std::uint64_t n = read_length(in, "the length of an open type");
    in.skip(n * 8, "the octets of an open type");
}

// After an extension bit 1: the additions, skipped (rulings 8 and 16).
void skip_additions(SeqIn& in) {
    std::uint64_t m = 0;
    if (in.must(1, "the number of extension additions") == 0) m = in.must(6, "the number of extension additions") + 1;
    else m = read_length(in, "the number of extension additions");
    if (m > in.left()) in.malformed("the input cannot hold the presence bits of the extension additions");
    std::vector<bool> present;
    for (std::uint64_t k = 0; k < m; ++k) present.push_back(in.take(1) == 1);
    for (bool b : present)
        if (b) skip_open_type(in);
}

void decode_uper_field(SeqIn& in, const SeqNode& n, Decoder& d) {
    using U = SeqNode::Uper;
    if (in.at_extent_end()) return;
    const FieldLine& f = n.field;
    const char* what = "a UPER field";
    std::string why;  // a transform failure
    Value v;
    std::uint64_t raw = 0;
    std::uint32_t octets = 0;
    try {
        switch (n.uper) {
            case U::Int: v = decode_uper_int(f, read_constrained(in, n.lb, n.ub, what)); break;
            case U::IntExt:
                if (in.must(1, what) == 0) {
                    v = decode_uper_int(f, read_constrained(in, n.lb, n.ub, what));
                } else if (read_int_octets(in, raw, octets, what)) {
                    v = decode_uper_int(f, sign_extend_octets(raw, octets));
                } else {
                    why = "an integer of more than 8 octets";
                }
                break;
            case U::IntUn:
                if (read_int_octets(in, raw, octets, what)) v = decode_uper_int(f, sign_extend_octets(raw, octets));
                else why = "an integer of more than 8 octets";
                break;
            case U::IntSemi: {
                if (!read_int_octets(in, raw, octets, what)) {
                    why = "an integer of more than 8 octets";
                    break;
                }
                // lb + raw within 64 signed bits.
                const std::uint64_t sum = as_unsigned(n.lb) + raw;
                const bool fits = n.lb >= 0 ? raw <= static_cast<std::uint64_t>(INT64_MAX - n.lb)
                                            : raw <= static_cast<std::uint64_t>(INT64_MAX) + as_unsigned(-(n.lb + 1)) + 1;
                if (!fits) why = "the value does not fit a signed 64-bit integer";
                else v = decode_uper_int(f, as_signed(sum));
                break;
            }
            case U::Enum: v = Value::of_int(read_constrained(in, 0, n.ub, what)); break;
            case U::EnumExt:
                if (in.must(1, what) == 0) {
                    v = Value::of_int(read_constrained(in, 0, n.ub, what));
                } else if (!read_small(in, raw, what)) {
                    why = "an extension index of more than 8 octets";
                } else if (raw > static_cast<std::uint64_t>(INT64_MAX - (n.ub + 1))) {
                    why = "an extension index that does not fit 64 signed bits";
                } else {
                    v = Value::of_int(n.ub + 1 + static_cast<std::int64_t>(raw));
                }
                break;
            case U::Chars:
            case U::Octets: {
                const std::uint64_t count = n.bounded ? static_cast<std::uint64_t>(read_constrained(in, n.lb, n.ub, what))
                                                      : read_length(in, what);
                const std::uint32_t width = n.uper == U::Chars ? 7 : 8;
                if (count * width > in.left()) in.malformed("the input cannot hold the count of a UPER string");
                std::string text;
                for (std::uint64_t k = 0; k < count; ++k) text += static_cast<char>(in.take(width));
                if (n.uper == U::Chars || f.transform == Transform::Utf8) {
                    if (n.uper == U::Octets && !utf8_is_valid(text)) why = "the value is not valid UTF-8";
                    else v = Value::of_string(text);
                } else {
                    v = Value::of_string(bytes_to_hex(text));
                }
                break;
            }
            case U::None: break;
        }
        if (why.empty()) {
            d.put(f, v);
            for (const auto& a : n.also) d.put(a, v);
            return;
        }
    } catch (const std::invalid_argument& ex) {
        why = ex.what();
    }
    d.fail(f, why);
    for (const auto& a : n.also) d.fail(a, why);
}

void decode_body(SeqIn& in, const SeqBody& body, Item& out);

// The value of a `field` line's bits at `start`, into every key bound to them,
// each through its own table; nothing for a sentinel (0.9).
void read_field(const std::string& data, std::uint64_t start, const SeqNode& n, BitMode msb, Decoder& d) {
    const FieldLine& f = n.field;
    if (f.has_absent) {
        // The raw value after `swap` (0.9 ruling 2); every key bound to the bits is absent.
        std::uint64_t raw = read_bits(data, start, n.len, msb);
        if (f.swap) raw = swap_bytes(raw, n.len);
        if (sentinel_num(f, raw)) return;
    }
    try {
        Value v;
        // ascii, sixbit (0.14) and chars (0.15) through the shared reader.
        if (!decode_bits_text(f, data, start, n.len, msb, v)) {
            std::uint64_t raw = read_bits(data, start, n.len, msb);
            if (f.swap) raw = swap_bytes(raw, n.len);
            v = decode_bits_value(f, raw, n.len);
        }
        d.put(f, v);
        for (const auto& a : n.also) d.put(a, v);
    } catch (const std::invalid_argument& ex) {
        d.fail(f, ex.what());
        for (const auto& a : n.also) d.fail(a, ex.what());
    }
}

// v0.20: a line's written bits, from `start` to `end`, read back as decode
// reads them, for the switches. A UPER locator (0.19) is read by its own
// reader, whose length follows from the value.
// v0.22: an `until:<code>` field at the cursor. A field that starts at the end
// of a `length` extent is absent; the terminator is found first, from the codes
// alone (no terminator within 2040 bits, or before the extent or input ends, is
// malformed-wire); then the characters are decoded (rulings 4, 5 and 8).
void decode_until_field(SeqIn& in, const SeqNode& n, Decoder& d) {
    const FieldLine& f = n.field;
    if (in.at_extent_end()) return;
    const unsigned w = chars_width(f.transform);
    const std::size_t max = 2040 / w;
    std::vector<std::uint8_t> codes;
    for (;;) {
        const std::uint64_t c = in.must(w, "a field that ends at a terminator");
        if (c == f.until_code) break;
        if (codes.size() == max) in.malformed("no terminator " + std::to_string(f.until_code) + " within 2040 bits");
        codes.push_back(static_cast<std::uint8_t>(c));
    }
    try {
        const Value v = decode_chars_exact(f.transform, codes);
        d.put(f, v);
        for (const auto& a : n.also) d.put(a, v);
    } catch (const std::invalid_argument& ex) {
        d.fail(f, ex.what());
        for (const auto& a : n.also) d.fail(a, ex.what());
    }
}

void read_back(const Pack& p, const std::string& data, std::uint64_t start, std::uint64_t end, const SeqNode& n,
               BitMode msb, Decoder& d) {
    if (n.uper == SeqNode::Uper::None && !n.field.until) {
        read_field(data, start, n, msb, d);
        return;
    }
    // A UPER locator (0.19) and `until:` (0.22): their length follows from the value.
    SeqIn in{p, data, msb, end, kNoExtent, start, std::vector<std::vector<bool>>(p.seq_presences.size()),
             false, {}, {}, {}, {}, {}, 0};
    if (n.field.until) decode_until_field(in, n, d);
    else decode_uper_field(in, n, d);
}

// v0.20: the case a switch selects from the value its key holds in `item`
// (after `via` and `typemap`, as canonical text); the `else` when no case holds
// it or the key is absent; null when there is no `else` either.
const SeqCase* select_case(const Pack& p, const SeqNode& n, const Item& item) {
    const SeqCase* fallback = !n.cases.empty() && n.cases.back().is_else ? &n.cases.back() : nullptr;
    auto it = item.fields.find(n.field.key);
    if (it == item.fields.end()) return fallback;
    Value v = it->second;
    if (n.field.key == "type" && !p.typemap.empty() && v.kind == Value::Kind::String)
        for (const auto& tm : p.typemap)
            if (tm.first == v.s) {
                v.s = tm.second;
                break;
            }
    std::string text;
    try {
        text = value_canonical_text(v);
    } catch (const std::invalid_argument&) {
        return fallback;
    }
    for (const auto& c : n.cases)
        if (!c.is_else && std::find(c.canon.begin(), c.canon.end(), text) != c.canon.end()) return &c;
    return fallback;
}

void decode_lines(SeqIn& in, const std::vector<SeqNode>& lines, std::size_t from, Item& out, Decoder& d);

// The length a `length` field states, less `plus`: false when it is negative.
bool stated_units(std::uint64_t field, std::int64_t plus, std::uint64_t& units) {
    if (plus >= 0) {
        if (field < static_cast<std::uint64_t>(plus)) return false;
        units = field - static_cast<std::uint64_t>(plus);
        return true;
    }
    const std::uint64_t add = static_cast<std::uint64_t>(-(plus + 1)) + 1;
    if (field > ~std::uint64_t{0} - add) return false;
    units = field + add;
    return true;
}

void decode_group(SeqIn& in, const SeqNode& n, Item& target) {
    // v0.34: a list a layered decode discards (step 4 of Decode) is read into
    // a scratch item, and its items are not counted.
    const DiscardGuard discarded(target, n.list);
    Item scratch;
    Item& out = discarded.active() ? scratch : target;
    auto item = [&](std::vector<Item>& items) {
        take_items(in.p, n.list, 1);  // 0.11 ruling 7a
        items.emplace_back();
        decode_body(in, n.inner, items.back());
    };
    // The list the group fills: a later group of one list replaces the items
    // of an earlier one, which are then no longer held (0.11 ruling 7g).
    auto list = [&]() -> std::vector<Item>& {
        std::vector<Item>& items = out.lists[n.list];
        give_back_items(count_items(items));
        items.clear();
        return items;
    };
    switch (n.repeat) {
        case Repeat::Rest: {
            // v0.21: items while bits remain in the enclosing extent: at least
            // 8 when it is counted in bytes, 1 when in bits. Fewer are padding.
            const bool in_length = in.ext != kNoExtent;
            const std::uint64_t end = in_length ? in.ext : in.have;
            const std::uint64_t unit = in_length && in.ext_bits ? 1 : 8;
            std::vector<Item>& items = list();
            while (in.cur <= end && end - in.cur >= unit) {
                const std::uint64_t start = in.cur;
                item(items);
                if (in.cur == start) in.malformed("an item of the 'rest' group '" + n.list + "' reads no bits");
            }
            return;
        }
        case Repeat::Last: {
            // v0.21: each item is preceded by one bit, 1 for the last item. A
            // first bit at the end of the extent gives an absent list (ruling
            // 34 of 0.8); a later one there is malformed-wire (ruling 13).
            if (!in.need(1, "the bit before an item")) return;
            std::vector<Item>& items = list();
            for (;;) {
                if (!in.need(1, "the bit before an item"))
                    in.malformed("the bit before an item of the 'last' group '" + n.list +
                                 "' lies at the end of its 'length' extent");
                const bool last = in.take(1) == 1;
                item(items);
                if (last) return;
            }
        }
        case Repeat::CountRef: {
            // v0.21: the count line's value; absent when the group or its count
            // line lies at or past the end of a `length` extent (ruling 6).
            if (in.ext != kNoExtent && in.cur >= in.ext) return;
            const std::size_t id = static_cast<std::size_t>(n.count_id);
            if (!in.count_set[id]) return;
            const std::uint64_t count = in.counts[id];
            // v0.31: the second count must give the same number of items,
            // checked before the bits left (ruling 4).
            if (n.count_id2 >= 0) {
                const std::size_t id2 = static_cast<std::size_t>(n.count_id2);
                if (!in.count_set[id2]) return;
                if (in.counts[id2] != count)
                    in.malformed("the two counts of the group '" + n.list + "' disagree: " + std::to_string(count) +
                                 " and " + std::to_string(in.counts[id2]) + " items");
            }
            // Ruling 20: compared with the bits left at the group.
            if (count > in.bits_left())
                in.malformed("the count " + std::to_string(count) + " of the group '" + n.list +
                             "' is larger than the bits left");
            std::vector<Item>& items = list();
            // 0.11 ruling 7d, as for a `count` in the group itself.
            take_items(in.p, n.list, count, true);
            for (std::uint64_t k = 0; k < count; ++k) {
                items.emplace_back();
                decode_body(in, n.inner, items.back());
            }
            return;
        }
        case Repeat::Count: {
            if (!in.need(n.len, "a count")) return;  // beyond the extent: an absent list
            const std::uint64_t count = in.take(n.len);
            // A count larger than the bits left is malformed-wire before any item is read.
            if (count > in.bits_left())
                in.malformed("the count " + std::to_string(count) + " of the group '" + n.list +
                             "' is larger than the bits left");
            std::vector<Item>& items = list();
            // The count is compared with what the limit still allows before
            // any item is read (0.11 ruling 7d).
            take_items(in.p, n.list, count, true);
            for (std::uint64_t k = 0; k < count; ++k) {
                items.emplace_back();
                decode_body(in, n.inner, items.back());
            }
            return;
        }
        case Repeat::Size: {
            if (in.at_extent_end()) return;  // an absent list
            const std::uint64_t count = n.bounded ? static_cast<std::uint64_t>(read_constrained(in, n.lb, n.ub, "a count"))
                                                  : read_length(in, "a count");
            if (count > in.left())
                in.malformed("the count " + std::to_string(count) + " of the group '" + n.list +
                             "' is larger than the bits left");
            std::vector<Item>& items = list();
            for (std::uint64_t k = 0; k < count; ++k) item(items);
            return;
        }
        case Repeat::While: {
            if (!in.need(1, "the bit before an item")) return;
            std::vector<Item>& items = list();
            while (in.need(1, "the bit before an item") && in.take(1) == 1) item(items);
            return;
        }
        case Repeat::More: {
            if (!in.need(1, "the bit before an item")) return;
            std::vector<Item>& items = list();
            for (;;) {
                // An indicator bit at or after the end of the extent reads as
                // 0: the item it precedes is the last (0.8 ruling 21).
                const bool more = in.need(1, "the bit before an item") && in.take(1) == 1;
                item(items);
                if (!more) return;
            }
        }
        case Repeat::Fx: {
            if (in.ext != kNoExtent && in.cur >= in.ext) return;
            std::vector<Item>& items = list();
            for (;;) {
                item(items);
                if (!in.need(1, "the bit after an item") || in.take(1) == 0) return;
            }
        }
    }
}

// v0.92: the `inner ... run` line of `lines`, in `length` blocks included; null when none.
const SeqNode* run_line_of(const std::vector<SeqNode>& lines) {
    for (const auto& n : lines) {
        if (n.type == Type::Inner && n.inner_run) return &n;
        if (n.type != Type::Length) continue;
        if (const SeqNode* in = run_line_of(n.inner.lines)) return in;
    }
    return nullptr;
}

// v0.83 ruling 9: the counts whose `length @` block stands in `lines`, which
// are not read; a block in any case of a switch there is one.
std::set<int> unit_counts(const std::vector<SeqNode>& lines, std::size_t from = 0) {
    std::set<int> out;
    for (std::size_t k = from; k < lines.size(); ++k) {
        const SeqNode& n = lines[k];
        if (n.type == Type::Group) continue;  // a reference stays in its body
        if (n.type == Type::Length && n.unit_size) out.insert(n.count_id);
        for (const auto& c : n.cases) {
            const std::set<int> in_case = unit_counts(c.body.lines);
            out.insert(in_case.begin(), in_case.end());
        }
        const std::set<int> inner = unit_counts(n.inner.lines);
        out.insert(inner.begin(), inner.end());
    }
    return out;
}

// Lines that decode does not read.
void pass_over(SeqIn& in, const std::vector<SeqNode>& lines, std::size_t from = 0) {
    if (in.units_passed.empty()) return;  // no count line in the pack
    for (int id : unit_counts(lines, from)) in.units_passed[static_cast<std::size_t>(id)] = 1;
}

// v0.92 ruling 4: a `length` block that reads as absent, its `run` line passed.
void pass_over_block(SeqIn& in, const SeqNode& n) {
    pass_over(in, n.inner.lines);
    if (in.host && in.host->sink() && run_line_of(n.inner.lines)) in.host->sink()->passed = true;
}

void pass_over_line(SeqIn& in, const SeqNode& n) {
    in.units_passed[static_cast<std::size_t>(n.count_id)] = 1;
    pass_over_block(in, n);
}

// Is the line among `lines`, or in a block of them?
bool holds_line(const std::vector<SeqNode>& lines, const SeqNode& n) {
    for (const auto& l : lines)
        if (&l == &n || holds_line(l.inner.lines, n)) return true;
    return false;
}

void check_run_with(const std::vector<SeqNode>& lines, const std::string& prefix, const std::set<std::string>& theirs,
                    const Pack& outer, const Pack& inner);

// 0.52 ruling 20, the fifth check where an `inner` line is reached: no key that
// the lines in reach map is a mapped key of the inner pack. The lines in reach
// of a line in a kind are the common lines and the kind's; of one in the common
// lines, the common lines and those of every kind.
void check_shared_keys(const InnerHost& host, const Pack& outer, const Pack& inner, const SeqNode& n) {
    const std::vector<std::string> keys = host.model_keys(inner);
    const std::set<std::string> theirs(keys.begin(), keys.end());
    auto check = [&](const std::string& key) {
        if (theirs.count(key))
            throw Error(ErrorKind::BadDirective, outer.format, "",
                        outer.source + ":" + std::to_string(n.line) + ": the key '" + key +
                            "' is mapped by the outer pack and by the inner pack " + inner.format +
                            " of an 'inner' line");
    };
    const bool common = holds_line(outer.seq.lines, n);
    keys_of_lines(outer.seq.lines, "", check, nullptr);
    for (const auto& k : outer.seq.kinds)
        if (common || holds_line(k.lines, n)) keys_of_lines(k.lines, "", check, nullptr);
    if (!n.inner_run) return;
    check_run_with(outer.seq.lines, "", theirs, outer, inner);  // v0.92 ruling 9
    for (const auto& k : outer.seq.kinds)
        if (common || holds_line(k.lines, n)) check_run_with(k.lines, "", theirs, outer, inner);
}

// The message at byte `from` of `data`, `bytes` bytes (`have` bits) long; `stop`
// receives its end in bytes from there.
Entity decode_seq_at(const Pack& p, const std::string& data, std::uint64_t from, std::uint64_t bytes,
                     const InnerHost* host, bool exact, bool strict, std::uint64_t* stop);
Entity decode_seq_bits(const Pack& p, const std::string& data, std::uint64_t from, std::uint64_t have,
                       const InnerHost* host, bool exact, bool strict, std::uint64_t* end_byte);

// v0.92: where a message of a run ends, in bytes from its start, of the `left`
// bytes of the extent.
void check_message_end(const Pack& inner, std::uint64_t stop, std::uint64_t left) {
    if (stop == 0 || stop > left)
        throw Error(ErrorKind::MalformedWire, inner.format, "",
                    stop == 0 ? std::string("a message of a run reads no bytes")
                              : "a message of a run ends at byte " + std::to_string(stop) + " of " + std::to_string(left));
}

// v0.92, the run operations: the messages of the extent, each decoded on its own.
void decode_run_messages(SeqIn& in, const SeqNode& n, const Pack& inner, RunSink& sink, std::uint64_t end) {
    sink.reached = true;
    sink.inner_format = n.inner_format;
    // The budget the outer lines read before the run left (ruling 5).
    const DecodeScope* outer = current_decode();
    const std::uint64_t budget = outer ? outer->limit - std::min(outer->limit, outer->held) : sink.max_items;
    std::uint64_t at = in.cur / 8;
    const std::uint64_t to = end / 8;
    while (at < to) {
        if (sink.messages.size() >= sink.max_items) {
            if (DecodeScope* s = current_decode()) s->has_failure_ = false;
            in.failed = false;
            in.malformed("the run of " + inner.format + " holds more than " + std::to_string(sink.max_items) + " messages");
        }
        sink.messages.emplace_back();
        RunMessage& m = sink.messages.back();
        DecodeScope scope(budget);
        std::uint64_t stop = 0;
        try {
            m.entity = decode_seq_at(inner, in.data, in.base / 8 + at, to - at, nullptr, false, true, &stop);
            check_message_end(inner, stop, to - at);
        } catch (const Error& ex) {
            m.error = ex;
            m.stopped = true;
            break;
        }
        m.items = scope.held;
        try {
            scope.raise_failure();
        } catch (const Error& ex) {
            m.error = ex;
        }
        at += stop;
    }
    in.cur = end;
}

// v0.92 ruling 9: an outer line in reach whose `with` names a mapped key of the
// inner pack of a run would be written as absent.
void check_run_with(const std::vector<SeqNode>& lines, const std::string& prefix, const std::set<std::string>& theirs,
                    const Pack& outer, const Pack& inner) {
    for (const auto& n : lines) {
        if (n.type == Type::Field && !n.field.with.empty() &&
            (theirs.count(prefix + n.field.with) || theirs.count(prefix + n.field.with + "[]")))
            throw Error(ErrorKind::BadDirective, outer.format, n.field.locator,
                        outer.source + ":" + std::to_string(n.field.line) + ": 'with " + n.field.with +
                            "' names a key of the inner pack " + inner.format + " of an 'inner ... run' line");
        const std::string under = n.type == Type::Group ? prefix + n.list + "[]." : prefix;
        check_run_with(n.inner.lines, under, theirs, outer, inner);
        for (const auto& k : n.inner.kinds) check_run_with(k.lines, under, theirs, outer, inner);
        for (const auto& c : n.cases) check_run_with(c.body.lines, under, theirs, outer, inner);
    }
}

// v0.34: an `inner` line reached by decode. The checks made where the line is
// reached, then the inner input decoded by the inner pack, whose keys join the
// message's: the first value read is kept, an outer list read first whole.
void decode_inner(SeqIn& in, const SeqNode& n, Item& out, Decoder& d) {
    const Pack* inner = nullptr;
    try {
        if (!in.host)
            throw Error(ErrorKind::UnknownFormat, n.inner_format, "", "no loaded pack defines this format");
        inner = &in.host->reach(in.p, n.inner_format, n.inner_run);
        check_shared_keys(*in.host, in.p, *inner, n);
    } catch (const Error&) {
        // A failed check is reported ahead of a transform-decode found before it.
        if (DecodeScope* s = current_decode()) s->has_failure_ = false;
        in.failed = false;
        throw;
    }
    if (in.cur % 8 != 0) in.malformed("the 'inner' line does not stand on a whole byte");
    // At message level the cursor may stand past the length a `length ... whole`
    // states: bytes beyond it are not part of the inner input (0.34 ruling 3,
    // 0.83 ruling 16), so it is empty.
    const std::uint64_t end = in.ext != kNoExtent ? in.ext : std::max(in.have, in.cur);
    if (in.ext != kNoExtent && end > in.have) in.malformed("the extent of the 'inner' line ends beyond the input");
    if (end % 8 != 0) in.malformed("the 'length ... bits' extent of the 'inner' line does not end on a whole byte");
    if (n.inner_run && in.host->sink()) {
        decode_run_messages(in, n, *inner, *in.host->sink(), end);
        return;
    }
    // v0.92 ruling 1: exactly one message, ahead of any transform-decode.
    auto not_one = [&](const std::string& why) {
        if (DecodeScope* s = current_decode()) s->has_failure_ = false;
        in.failed = false;
        throw Error(ErrorKind::MessageCount, in.p.format, "",
                    "the run of " + inner->format + " messages " + why + ", and this operation takes exactly one");
    };
    if (n.inner_run && end == in.cur) not_one("is empty");
    const std::string hex =
        end == in.cur ? std::string()
                      : bytes_to_hex(in.data.substr(static_cast<std::size_t>(in.cur / 8),
                                                    static_cast<std::size_t>((end - in.cur) / 8)));
    // The lists the message holds already: the inner lists of those names are
    // discarded, and not counted (7g).
    DecodeScope* s = current_decode();
    if (s) {
        s->discard.clear();
        for (const auto& kv : out.lists) s->discard.insert(kv.first);
        s->discard_root = nullptr;
        s->discard_claim = true;
        s->inner_root = nullptr;
        s->inner_failures.clear();
    }
    // Keys a table failure closed before the line: no later line is tried for them.
    const std::vector<std::string> outer_closed = d.closed;
    Entity e;
    try {
        if (n.inner_run) {
            const std::string bytes = in.data.substr(static_cast<std::size_t>(in.cur / 8),
                                                     static_cast<std::size_t>((end - in.cur) / 8));
            std::uint64_t stop = 0;
            e = decode_seq_at(*inner, bytes, 0, bytes.size(), nullptr, false, true, &stop);
            check_message_end(*inner, stop, bytes.size());
            if (stop < bytes.size()) not_one("has more than one message");
        } else {
            e = in.host->decode(*inner, hex, n.inner_partial);
        }
    } catch (const Error& ex) {
        if (s) {
            s->discard_claim = false;
            s->discard_root = nullptr;
            s->discard.clear();
            s->inner_root = nullptr;
        }
        // An error that stops the decode, in either pack, is reported ahead of
        // a transform-decode read before it; among transform-decode errors the
        // earliest wins (the message's failed fields are not yet recorded).
        if (ex.kind() != ErrorKind::TransformDecode) {
            if (s) s->has_failure_ = false;
            in.failed = false;
        }
        throw;
    }
    in.cur = end;  // with `partial`, bytes the inner message does not read are ignored
    // The inner message's failed fields join the message's own, under the rule
    // of 0.6 for one key at several locators (ruling 23): a failed transform is
    // forgiven when the key has a value, a table with no entry is not.
    if (s) {
        s->inner_root = nullptr;
        for (auto& f : s->inner_failures) {
            if (std::find(d.closed.begin(), d.closed.end(), f.key) != d.closed.end()) continue;
            if (!f.table && out.fields.count(f.key)) continue;
            if (f.table) d.closed.push_back(f.key);
            d.failures.push_back(std::move(f));
        }
        s->inner_failures.clear();
    }
    for (auto& kv : e.fields)
        if (std::find(outer_closed.begin(), outer_closed.end(), kv.first) == outer_closed.end() &&
            out.fields.emplace(kv.first, std::move(kv.second)).second)
            d.joined.insert(kv.first);
    std::set<std::string> kept;
    for (auto& kv : e.lists)
        if (out.lists.emplace(kv.first, std::move(kv.second)).second) kept.insert(kv.first);
    // No later line of the message replaces a list the inner message gave it.
    if (s) {
        s->discard_claim = false;
        s->discard = std::move(kept);
        s->discard_root = &out;
    }
    if (in.root && !e.kind.second.empty()) in.root->inner_kind = e.kind;
}

void decode_node(SeqIn& in, const SeqNode& n, Item& out, Decoder& d) {
    const Pack& p = in.p;
    switch (n.type) {
        case Type::Inner: decode_inner(in, n, out, d); return;
        case Type::Field: {
            if (n.uper != SeqNode::Uper::None) {
                decode_uper_field(in, n, d);
                return;
            }
            if (n.field.until) {
                decode_until_field(in, n, d);
                return;
            }
            if (!in.need(n.len, "a field")) return;
            const std::uint64_t start = in.cur;
            in.cur += n.len;
            read_field(in.data, in.base + start, n, in.msb, d);
            return;
        }
        case Type::Switch: {
            // v0.20: the case the key's value selects, read at the cursor. A
            // key whose line failed its transform or table fails the decode
            // (ruling 35). So does a table with no entry beside a line that
            // gave the key its value (0.64 ruling 26).
            for (const auto& f : d.failures)
                if (f.key == n.field.key && (in.strict || f.table || !out.fields.count(n.field.key)))  // in.strict: 0.92 ruling 3
                        throw Error(ErrorKind::TransformDecode, p.format, f.locator,
                                    "the 'switch' key " + f.key + " failed: " + f.why);
            const SeqCase* c = select_case(p, n, out);
            if (!c)
                throw Error(ErrorKind::NoKind, p.format, "",
                            "no 'case' of the switch on '" + n.field.key + "' (line " + std::to_string(n.field.line) +
                                ") holds its value, and it has no 'else'");
            in.case_read[static_cast<std::size_t>(c->id)] = ++in.tick;
            in.open_cases.push_back(c->id);
            decode_lines(in, c->body.lines, 0, out, d);
            in.open_cases.pop_back();
            return;
        }
        case Type::Const:
            if (in.need(n.len, "a const")) in.cur += n.len;  // read and ignored
            return;
        case Type::Pad:
            if (in.need(n.len, "a pad")) in.cur += n.len;
            return;
        case Type::Align: {
            // It stops at the end of the input or of the extent without
            // error (0.8 ruling 20).
            const std::uint64_t end = in.ext != kNoExtent ? std::min(in.ext, in.have) : in.have;
            const std::uint64_t to = std::min((in.cur + n.len - 1) / n.len * n.len, end);
            if (to > in.cur) in.cur = to;
            return;
        }
        case Type::When: {
            // A common `when`: it must hold for any message of the format.
            const std::uint64_t start = in.cur;
            if (in.cur > in.have || n.len > in.have - in.cur || (in.ext != kNoExtent && in.cur + n.len > in.ext) ||
                !n.holds(in.take(n.len)))
                throw Error(ErrorKind::NoKind, p.format, "",
                            "the common 'when " + std::to_string(n.len) + " " + std::to_string(n.number) +
                                "' does not hold");
            // v0.30: `as` sets its key whenever the message (or item) decodes.
            if (n.has_as) read_field(in.data, in.base + start, n, in.msb, d);
            return;
        }
        case Type::Presence: {
            const SeqPresence& pr = p.seq_presences[static_cast<std::size_t>(n.presence)];
            std::vector<bool>& bits = in.presence[static_cast<std::size_t>(n.presence)];
            bits.clear();
            if (!pr.fx) {
                if (in.need(pr.bits, "a presence"))
                    for (std::uint32_t k = 0; k < pr.bits; ++k) bits.push_back(in.take(1) == 1);
            } else if (in.need(8, "a presence octet")) {
                // Octets of 7 presence bits, each followed by an extension bit.
                for (;;) {
                    for (int k = 0; k < 7; ++k) bits.push_back(in.take(1) == 1);
                    if (in.take(1) == 0) break;
                    if (!in.need(8, "a presence octet"))
                        in.malformed("a presence octet runs past the end of its 'length' extent");
                }
            }
            // A bit that is 1 and that no `if` names: the message holds a part
            // the pack does not describe (0.8 ruling 1).
            for (std::size_t k = 0; k < bits.size(); ++k) {
                if (!bits[k] || (k < pr.named.size() && pr.named[k])) continue;
                if (k < pr.case_named.size() && !pr.case_named[k].empty()) {
                    // A case being read names it, or one read later may.
                    bool open = false;
                    for (int id : pr.case_named[k])
                        open = open || std::find(in.open_cases.begin(), in.open_cases.end(), id) != in.open_cases.end();
                    if (!open) in.pending.push_back({n.presence, k, in.tick});
                    continue;
                }
                in.malformed("bit " + std::to_string(k + 1) + " of the presence '" + pr.name +
                             "' is 1 and no 'if' block names it");
            }
            return;
        }
        case Type::If: {
            for (const auto& c : n.conds)
                if (in.bit(c) == c.negated) return pass_over(in, n.inner.lines);
            decode_lines(in, n.inner.lines, 0, out, d);
            return;
        }
        case Type::Opt:
            if (in.need(1, "the bit of an 'opt'") && in.take(1) == 1) decode_lines(in, n.inner.lines, 0, out, d);
            else pass_over(in, n.inner.lines);
            return;
        case Type::Chain: {
            // At the end of a `length` extent a chain is still walked (0.21
            // ruling 31): its lines read as absent, its `fx` bits as 0.
            const std::vector<SeqNode>& lines = n.inner.lines;
            for (std::size_t k = 0; k < lines.size(); ++k) {
                if (lines[k].type != Type::Fx) {
                    decode_node(in, lines[k], out, d);
                    continue;
                }
                // A 0 bit ends the chain.
                if (!in.need(1, "an 'fx' bit") || in.take(1) == 0) return pass_over(in, lines, k + 1);
                if (k + 1 == lines.size())
                    in.malformed("the last 'fx' bit of a chain is 1 and the chain has no further part");  // ruling 3
            }
            return;
        }
        case Type::Fx: return;  // a line of a chain, read there
        case Type::Length: {
            if (n.unit_size) {
                // v0.83: the extent the count line states. Absent at the end of
                // the enclosing one, whatever the count states (ruling 4).
                const std::size_t id = static_cast<std::size_t>(n.count_id);
                if (in.at_extent_end() || !in.count_set[id]) return pass_over_line(in, n);
                // Within the enclosing extent and the input (rulings 4 and 5),
                // the product exact: a count that does not fit 64 bits is held
                // as the largest, which no input has.
                const std::uint64_t to = in.ext != kNoExtent ? std::min(in.ext, in.have) : in.have;
                if (in.cur > to || in.counts[id] > (to - in.cur) / n.unit_size)
                    in.malformed("the extent of a 'length @' block of " + std::to_string(in.counts[id]) + " units of " +
                                 std::to_string(n.unit_size) + " bits runs past the extent around it or the input");
                in.units_read[id] = 1;
                const std::uint64_t saved = in.ext;
                const bool saved_bits = in.ext_bits, saved_units = in.in_units;
                const std::uint64_t stop = in.cur + in.counts[id] * n.unit_size;
                in.ext = stop;
                in.ext_bits = n.unit_bits;
                in.in_units = true;
                decode_lines(in, n.inner.lines, 0, out, d);
                in.cur = stop;  // content of the extent no line read is skipped
                in.ext = saved;
                in.ext_bits = saved_bits;
                in.in_units = saved_units;
                return;
            }
            if (!in.need(n.len, "a length field")) return pass_over_block(in, n);
            const std::uint64_t stated = in.take(n.len);
            std::uint64_t units = 0;
            if (!stated_units(stated, n.plus, units) || units > (kNoExtent >> 4))
                in.malformed("the stated length " + std::to_string(stated) + " is below 'plus " +
                             std::to_string(n.plus) + "', or too large");
            const std::uint64_t bits = n.unit_bits ? units : units * 8;
            const std::uint64_t outer = in.ext != kNoExtent ? in.ext : in.have;
            // Also against the input, which a whole length inside the block
            // around this one may have cut (0.83 rulings 16 and 17).
            if (bits > outer - in.cur || in.cur > in.have || bits > in.have - in.cur)
                in.malformed("a 'length' extent of " + std::to_string(bits) + " bits runs past the input");
            const std::uint64_t saved = in.ext;
            const bool saved_bits = in.ext_bits;
            in.ext = in.cur + bits;
            in.ext_bits = n.unit_bits;
            decode_lines(in, n.inner.lines, 0, out, d);
            in.cur = in.ext;  // content of the extent no line read is skipped
            in.ext = saved;
            in.ext_bits = saved_bits;
            return;
        }
        case Type::LengthWhole: {
            if (!in.need(n.len, "a length field")) return;
            const std::uint64_t stated = in.take(n.len);
            std::uint64_t bytes = 0;
            if (!stated_units(stated, n.plus, bytes) || bytes > (kNoExtent >> 4))
                in.malformed("the stated length " + std::to_string(stated) + " is below 'plus " +
                             std::to_string(n.plus) + "', or too large");
            if (bytes * 8 < in.cur)
                in.malformed("the stated length of " + std::to_string(bytes) + " bytes is shorter than what was already read");
            if (bytes * 8 > in.have)
                in.malformed("the input is shorter than the stated length of " + std::to_string(bytes) + " bytes");
            in.have = bytes * 8;  // input beyond it is ignored
            in.whole = true;
            return;
        }
        case Type::Group: decode_group(in, n, out); return;
        case Type::Ext: {
            // v0.19: the extension bit, the root components, then the additions.
            if (in.at_extent_end()) return;
            const bool extended = in.must(1, "an extension bit") == 1;
            decode_lines(in, n.inner.lines, 0, out, d);
            if (extended) skip_additions(in);
            return;
        }
        case Type::Choice: {
            if (in.at_extent_end()) return;
            if (n.uext && in.must(1, "the extension bit of a choice") == 1) {
                // An extension alternative: its index and an open type, skipped.
                std::uint64_t index = 0;
                if (!read_small(in, index, "the index of an extension alternative"))
                    in.fail("the index of an extension alternative has more than 8 octets");
                skip_open_type(in);
                return;
            }
            const std::uint64_t index = static_cast<std::uint64_t>(
                read_constrained(in, 0, static_cast<std::int64_t>(n.number - 1), "the index of a choice"));
            for (const auto& a : n.inner.lines)
                if (a.number == index) {
                    decode_lines(in, a.inner.lines, 0, out, d);
                    return;
                }
            in.malformed("the choice index " + std::to_string(index) + " has no 'alt'");
        }
        case Type::Alt: return;  // read by its choice
        case Type::Count: {
            // v0.21: the value less `plus`; below `plus` is malformed-wire here.
            const std::size_t id = static_cast<std::size_t>(n.count_id);
            in.count_set[id] = 0;
            if (!in.need(n.len, "a count")) return;
            const std::uint64_t v = in.take(n.len);
            std::uint64_t items = 0;
            if (!stated_units(v, n.plus, items)) {
                if (n.plus >= 0)
                    in.malformed("the count '" + n.count_name + "' holds " + std::to_string(v) + ", below its 'plus " +
                                 std::to_string(n.plus) + "'");
                items = ~std::uint64_t{0};  // more than any bits left
            }
            in.counts[id] = items;
            in.count_set[id] = 1;
            in.units_read[id] = in.units_passed[id] = 0;
            in.counts_read.push_back(&n);
            return;
        }
    }
}

void decode_lines(SeqIn& in, const std::vector<SeqNode>& lines, std::size_t from, Item& out, Decoder& d) {
    for (std::size_t k = from; k < lines.size(); ++k) decode_node(in, lines[k], out, d);
}

// The message, or one item of a group: the common lines, then the lines of the
// first kind whose `when` lines all hold at the cursor.
void decode_body(SeqIn& in, const SeqBody& body, Item& out) {
    const Pack& p = in.p;
    const std::size_t first_count = in.counts_read.size();
    Decoder d(p, out);
    decode_lines(in, body.lines, 0, out, d);
    if (!body.kinds.empty()) {
        const SeqKind* selected = nullptr;
        std::size_t whens = 0;
        const std::uint64_t end = in.ext != kNoExtent ? std::min(in.ext, in.have) : in.have;
        for (const auto& k : body.kinds) {
            // v0.33: kind start is where the common lines ended; a `when ... at`
            // reads at kind start plus its offset and does not move the cursor.
            const std::uint64_t kind_start = in.cur;
            std::uint64_t at = in.cur;
            std::size_t i = 0;
            bool holds = true;
            std::vector<std::uint64_t> where;  // the position each `when` read
            for (; i < k.lines.size() && k.lines[i].type == Type::When && holds; ++i) {
                const SeqNode& w = k.lines[i];
                const bool ahead = w.has_at;
                const std::uint64_t pos = ahead ? kind_start + w.at : at;
                const bool wrapped = ahead && w.at > ~std::uint64_t{0} - kind_start;
                // A `when` any of whose bits lies beyond the input or the
                // extent does not hold (0.33 rulings 6 and 7).
                if (wrapped || pos > end || w.len > end - pos || !w.holds(read_bits(in.data, in.base + pos, w.len, in.msb))) {
                    holds = false;
                } else {
                    where.push_back(pos);
                    if (!ahead) at += w.len;
                }
            }
            if (!holds) continue;
            selected = &k;
            whens = i;
            // v0.30: the `when ... as` lines of the selected kind set their
            // keys; a kind tested and not selected sets nothing (ruling 12).
            for (std::size_t j = 0; j < i; ++j)
                if (k.lines[j].has_as) read_field(in.data, in.base + where[j], k.lines[j], in.msb, d);
            in.cur = at;
            break;
        }
        if (!selected)
            throw Error(ErrorKind::NoKind, p.format, "",
                        "the " + std::string(&body == &p.seq ? "message" : "item") + " matches no kind (at bit " +
                            std::to_string(in.cur) + ")");
        out.kind = {p.format, selected->name};
        // v0.92 ruling 4: a kind with no `run` line in its reach.
        if (&body == &p.seq && in.host && in.host->sink() && !run_line_of(body.lines) && !run_line_of(selected->lines))
            in.host->sink()->passed = true;
        decode_lines(in, selected->lines, whens, out, d);
    }
    // 0.83 ruling 9: a count of the message, or of this item, that states units
    // of which no block was read.
    for (std::size_t k = first_count; k < in.counts_read.size(); ++k) {
        const std::size_t id = static_cast<std::size_t>(in.counts_read[k]->count_id);
        if (in.count_set[id] && in.counts[id] != 0 && in.units_passed[id] && !in.units_read[id])
            in.malformed("the count '" + in.counts_read[k]->count_name +
                         "' states units and no 'length @' block of it is read");
    }
    in.counts_read.resize(first_count);
    try {
        d.finish();
    } catch (const Error& ex) {
        if (!in.failed) {
            in.failed = true;
            in.fail_locator = ex.locator();
            in.fail_detail = ex.detail();
        }
    }
}

}  // namespace

Entity decode_seq(const Pack& p, const std::string& bytes, const InnerHost* host, bool exact) {
    // Hex text, or under `armor sixbit` six bits a character, every one checked
    // before any line is read (0.14). The armored message is any number of bits.
    std::uint64_t armored = 0;
    const std::string data = p.armor_sixbit ? armor_to_bytes(p, bytes, armored) : hex_to_bytes(p, bytes);
    if (p.armor_sixbit) return decode_seq_bits(p, data, 0, armored, host, exact, false, nullptr);
    return decode_seq_at(p, data, 0, data.size(), host, exact, false, nullptr);
}

namespace {
Entity decode_seq_at(const Pack& p, const std::string& data, std::uint64_t from, std::uint64_t bytes,
                     const InnerHost* host, bool exact, bool strict, std::uint64_t* stop) {
    return decode_seq_bits(p, data, from, bytes * 8, host, exact, strict, stop);
}

// The message at byte `from` of `data`, `have` bits long. `stop`, when given,
// receives its end in bytes from there (0.34 ruling 13).
Entity decode_seq_bits(const Pack& p, const std::string& data, std::uint64_t from, std::uint64_t have,
                       const InnerHost* host, bool exact, bool strict, std::uint64_t* end_byte) {
    SeqIn in{p, data, bit_mode(p.bit_order), have, kNoExtent, 0,
             std::vector<std::vector<bool>>(p.seq_presences.size()), false, {}, {}, {}, {}, {}, 0};
    in.base = from * 8;
    in.strict = strict;
    in.case_read.assign(p.seq_cases.size(), 0);
    in.count_set.assign(p.seq_count_lines, 0);
    in.counts.assign(p.seq_count_lines, 0);
    in.units_read.assign(p.seq_count_lines, 0);
    in.units_passed.assign(p.seq_count_lines, 0);
    Entity e;
    begin_message(e);  // v0.34: the inner message of a layered decode
    in.host = host;
    in.root = &e;
    decode_body(in, p.seq, e);
    // A presence bit named only inside cases none of which was read after it (0.20 ruling 21).
    for (const auto& pend : in.pending) {
        const SeqPresence& pr = p.seq_presences[static_cast<std::size_t>(pend.presence)];
        bool read = false;
        for (int id : pr.case_named[pend.bit]) read = read || in.case_read[static_cast<std::size_t>(id)] > pend.tick;
        if (!read)
            throw Error(ErrorKind::MalformedWire, p.format, "",
                        "bit " + std::to_string(pend.bit + 1) + " of the presence '" + pr.name +
                            "' is 1 and no 'if' block of the lines read names it");
    }
    // v0.34 ruling 13: the stated length, or the cursor up to a whole byte.
    const std::uint64_t stop = in.whole ? in.have / 8 : (in.cur + 7) / 8;
    if (end_byte) *end_byte = stop;
    if (exact) {
        if (data.size() > stop)
            throw Error(ErrorKind::MalformedWire, p.format, "",
                        "the message ends at byte " + std::to_string(stop) + " of " + std::to_string(data.size()) +
                            " of an 'inner' line without 'partial'");
    }
    // Input beyond the last line, whole bytes included, is ignored (0.8 ruling 9).
    if (in.failed) throw Error(ErrorKind::TransformDecode, p.format, in.fail_locator, in.fail_detail);
    return e;
}
}  // namespace

// ---------------------------------------------------------------- encode

namespace {

// v0.20: what the encoder knows of the switches. The case a switch selects is
// the one decode would read from the bits its key's line wrote; presence,
// `opt` and `fx` bits are computed before those bits are written, from a
// prediction, and the encode is repeated until every prediction it used is the
// case selected.
struct SwitchState {
    using Key = std::pair<const Item*, const SeqNode*>;
    const std::vector<const SeqCase*>* cases = nullptr;  // by id: the plan's, or own_cases
    std::vector<const SeqCase*> own_cases;
    std::map<Key, int> guess;           // the predicted case index; -1: none
    std::map<Key, int> used;            // the predictions this pass relied on
    std::map<Key, int> actual;          // the cases this pass selected
};

// What one message or item is written from: its keys and lists, its kind, and
// the `default` lines in scope (the kind's, then the common ones of its body).
struct Scope {
    const Pack& p;
    const Item& item;
    const SeqBody& body;
    const SeqKind* kind;
    EncodeSource src;
    SwitchState* sw;
    // v0.20: the written bits read back as decode reads them, for the switches.
    mutable Item shadow;
    mutable Decoder shadow_d;
    mutable std::set<std::string> switch_keys;  // v0.64: the keys of the switches written

    Scope(const Pack& pack, const Item& it, const SeqBody& b, const SeqKind* k, SwitchState* state)
        : p(pack), item(it), body(b), kind(k), src(pack, static_cast<const Kind*>(nullptr), it), sw(state),
          shadow(), shadow_d(pack, shadow), switch_keys() {
        src.defaults = Defaults{k ? &k->defaults : nullptr, &b.defaults};
    }
    // v0.20: the default of a case holding the line, the innermost first
    // (rulings 7 and 22); null when none.
    const DefaultLine* case_default(const FieldLine& f) const {
        for (int c = f.scase; c >= 0; c = p.seq_cases[static_cast<std::size_t>(c)].parent)
            for (const auto& d : (*sw->cases)[static_cast<std::size_t>(c)]->body.defaults)
                if (d.key == f.key) return &d;
        return nullptr;
    }
    // A key with a `default` in scope counts as present (0.8 ruling 2).
    // In a UPER pack no `default` counts (rulings 2 and 19 of 0.19), a case's included.
    bool present(const FieldLine& f) const {
        if (item.fields.count(f.key)) return true;
        if (src.p.uper) return false;
        if (case_default(f)) return true;
        for (const std::vector<DefaultLine>* defs : {src.defaults.first, src.defaults.second}) {
            if (!defs) continue;
            for (const auto& d : *defs)
                if (d.key == f.key) return true;
        }
        return false;
    }
    // The value a line writes: the item's, else a case default, else the kind's
    // or the body's default. False when it has none. Throws transform-encode.
    bool value(const FieldLine& f, Value& out) const {
        if (!item.fields.count(f.key))
            if (const DefaultLine* d = case_default(f)) {
                out = typemapped_out(p, f, d->value);
                if (f.table >= 0) {
                    try {
                        out = table_encode(p, f, out);
                    } catch (const std::invalid_argument& ex) {
                        throw Error(ErrorKind::TransformEncode, p.format, f.locator, f.key + ": " + ex.what());
                    }
                }
                return true;
            }
        return src.value(f, out);
    }
};

// v0.30 ruling 7: the item's value of an `as` key as an unsigned 64-bit
// pattern; false when it is not an integer.
bool as_pattern(const Value& v, std::uint64_t& u) {
    if (v.kind == Value::Kind::Int) {
        u = static_cast<std::uint64_t>(v.i);
        return true;
    }
    if (v.kind == Value::Kind::Float && std::isfinite(v.f) && v.f == std::floor(v.f) && v.f >= -9223372036854775808.0 &&
        v.f < 9223372036854775808.0) {
        u = static_cast<std::uint64_t>(static_cast<std::int64_t>(v.f));
        return true;
    }
    return false;
}

// v0.30: the implicit `requires` term of a kind's `when ... as` lines: the item
// holds each key (a `default` does not count, ruling 6) with a value the
// `when` matches.
bool as_terms_hold(const SeqKind& k, const Item& item) {
    for (const auto& n : k.lines) {
        if (n.type != Type::When) break;
        if (!n.has_as) continue;
        auto it = item.fields.find(n.field.key);
        std::uint64_t u = 0;
        if (it == item.fields.end() && n.as_optional) continue;  // v0.52
        if (it == item.fields.end() || !as_pattern(it->second, u) || !n.holds(u)) return false;
    }
    return true;
}

// Encode: the kind the item names, when it names this format and a kind the
// body has, else the first kind whose `requires` keys are all present. Null for a body with no kinds; throws no-kind.
const SeqKind* select_kind(const Pack& p, const SeqBody& body, const Item& item) {
    if (body.kinds.empty()) return nullptr;
    if (item.kind.first == p.format) {
        for (const auto& k : body.kinds)
            if (k.name == item.kind.second) return &k;
        // The message names a kind the format does not have. An item is
        // selected by its kind only when the group has it; otherwise by
        // `requires` (0.8 ruling 26).
        if (&body == &p.seq)
            throw Error(ErrorKind::NoKind, p.format, "",
                        "the kind '" + item.kind.second + "' is not one of the format's kinds");
    }
    for (const auto& k : body.kinds)
        if (requires_hold(k.requires_terms, k.requires_keys, item) && as_terms_hold(k, item)) return &k;
    throw Error(ErrorKind::NoKind, p.format, "", "the entity or item has the 'requires' keys of no kind");
}

int predicted_case(const SeqNode& n, const Scope& s);

// Would the line write a present key, a non-empty list, or a nested presence
// that is not all zero?
bool content(const SeqNode& n, const Scope& s) {
    switch (n.type) {
        case Type::Field:
            // A line suppressed by `with` is not content, nor is its default
            // (0.18 ruling 1); its `also` keys still are (ruling 5).
            if (s.present(n.field) && !s.src.suppressed(n.field)) return true;
            for (const auto& a : n.also)
                if (s.present(a)) return true;
            return false;
        case Type::Switch: {
            // Only the selected case counts (0.20).
            const int c = predicted_case(n, s);
            if (c < 0) return false;
            for (const auto& line : n.cases[static_cast<std::size_t>(c)].body.lines)
                if (content(line, s)) return true;
            return false;
        }
        case Type::Group: {
            auto it = s.item.lists.find(n.list);
            return it != s.item.lists.end() && !it->second.empty();
        }
        case Type::If:
        case Type::Opt:
        case Type::Chain:
        case Type::Length:
        case Type::Ext:     // v0.19 ruling 3
        case Type::Choice:
        case Type::Alt:
            for (const auto& c : n.inner.lines)
                if (content(c, s)) return true;
            return false;
        default: return false;
    }
}

struct SeqOut {
    const Pack& p;
    std::string data;
    BitMode msb;
    std::uint64_t cur = 0;
    std::vector<std::vector<bool>> presence;  // by SeqPresence index: the bits last computed
    struct Whole {
        std::uint64_t at;
        const SeqNode* node;
    };
    std::vector<Whole> wholes;  // `length ... whole` fields, written last
    SwitchState* sw = nullptr;
    // v0.21: every count line written, filled in when the message is finished
    // (ruling 30); `at_count[id]` is the last one written for a count line.
    struct CountField {
        std::uint64_t at;
        const SeqNode* node;
        std::uint64_t items;
    };
    std::vector<CountField> count_fields{};
    std::map<int, std::size_t> at_count{};
    // v0.21 ruling 4: the first bit of each `rest` item, by extent being laid
    // out; the message's is the first. `counted_in_bytes` per extent.
    struct Extent {
        std::uint64_t start;
        bool bytes;
        std::vector<std::uint64_t> item_starts;
    };
    std::vector<Extent> extents{Extent{0, true, {}}};
    bool rest_ran = false;  // a `rest` group of the current extent was written
    // v0.33: while the fixed lines of a kind with windows are written, the
    // bits each `field` line wrote for a key the item holds (ruling 12).
    bool track_held = false;
    std::vector<std::pair<std::uint64_t, std::uint64_t>> held{};
    // v0.34: what serves the `inner` lines, and the entity being written.
    const InnerHost* host = nullptr;
    const Entity* root = nullptr;

    void reach(std::uint64_t bits) {
        const std::size_t bytes = static_cast<std::size_t>((bits + 7) / 8);
        if (data.size() < bytes) data.resize(bytes, '\0');
    }
    void put(std::uint64_t raw, std::uint32_t len) {
        reach(cur + len);
        write_bits(data, cur, len, raw, msb);
        cur += len;
    }
    void zeros(std::uint64_t n) {
        reach(cur + n);
        cur += n;
    }
    bool bit(const SeqCond& c) const {
        const std::vector<bool>& v = presence[static_cast<std::size_t>(c.presence)];
        return c.bit <= v.size() && v[c.bit - 1];
    }
};

void encode_body(SeqOut& out, const SeqBody& body, const Item& item);
void encode_lines(SeqOut& out, const std::vector<SeqNode>& lines, const Scope& s, const std::vector<SeqNode>* tail);

// First pass for one presence: every `if` block after its line that names one
// of its bits without `!` sets the bit when the block has content. A block
// inside a group item is looked at for every item of the list.
void compute_presence(const Pack& p, int id, const std::vector<SeqNode>& lines, std::size_t from, const Scope& s,
                      std::vector<bool>& bits) {
    for (std::size_t k = from; k < lines.size(); ++k) {
        const SeqNode& n = lines[k];
        if (n.type == Type::Group) {
            auto it = s.item.lists.find(n.list);
            if (it == s.item.lists.end()) continue;
            for (const Item& item : it->second) {
                // A group that is not written may hold kinds none of which
                // the item selects: only its common lines are looked at then.
                const SeqKind* kind = nullptr;
                try {
                    kind = select_kind(p, n.inner, item);
                } catch (const Error&) {
                }
                const Scope inner(p, item, n.inner, kind, s.sw);
                compute_presence(p, id, n.inner.lines, 0, inner, bits);
                if (inner.kind) compute_presence(p, id, inner.kind->lines, 0, inner, bits);
            }
            continue;
        }
        if (n.type == Type::Switch) {
            const int c = predicted_case(n, s);
            if (c >= 0) compute_presence(p, id, n.cases[static_cast<std::size_t>(c)].body.lines, 0, s, bits);
            continue;
        }
        if (n.type == Type::If) {
            bool names = false;
            for (const auto& c : n.conds)
                if (c.presence == id && !c.negated) names = true;
            if (names && content(n, s))
                for (const auto& c : n.conds)
                    if (c.presence == id && !c.negated) {
                        if (bits.size() < c.bit) bits.resize(c.bit, false);
                        bits[c.bit - 1] = true;
                    }
        }
        compute_presence(p, id, n.inner.lines, 0, s, bits);
    }
}

// The value of the earliest bound key the item holds; when it holds none, the
// default of the earliest key that has one (0.8 ruling 16). Null for none.
const FieldLine* field_value(const SeqNode& n, const Scope& s, Value& mv) {
    for (const bool held : {true, false})
        for (std::size_t k = 0; k <= n.also.size(); ++k) {
            const FieldLine& line = k == 0 ? n.field : n.also[k - 1];
            if (k == 0 && s.src.suppressed(line)) continue;  // 0.18 rulings 1 and 5
            if (held && !s.item.fields.count(line.key)) continue;
            if (s.value(line, mv)) return &line;
        }
    return nullptr;
}

// v0.30: a `when ... as` line writes the item's value of its key when the
// `when` matches it, the first listed value when the item does not hold the
// key, and is transform-encode otherwise (the output would decode another value).
void encode_when(SeqOut& out, const SeqNode& n, const Scope& s) {
    auto it = s.item.fields.find(n.field.key);
    if (it == s.item.fields.end()) {
        out.put(n.number, n.len);
        return;
    }
    std::uint64_t u = 0;
    if (!as_pattern(it->second, u) || !n.holds(u)) {
        std::string shown;
        try {
            shown = value_canonical_text(it->second);
        } catch (const std::invalid_argument&) {
            shown = it->second.s;
        }
        throw Error(ErrorKind::TransformEncode, s.p.format, n.field.locator,
                    n.field.key + ": the value " + shown + " is not one the 'when' on line " +
                        std::to_string(n.line) + " holds for");
    }
    out.put(u, n.len);
}

// ---- v0.19 writers. Each throws std::invalid_argument (transform-encode).

void put_any(SeqOut& out, std::uint64_t raw, std::uint32_t len) {
    if (len > 0) out.put(raw, len);
}

void put_constrained(SeqOut& out, std::int64_t lb, std::int64_t ub, std::int64_t v) {
    if (v < lb || v > ub)
        throw std::invalid_argument(std::to_string(v) + " is outside " + std::to_string(lb) + ".." + std::to_string(ub));
    put_any(out, as_unsigned(v) - as_unsigned(lb), bits_for(as_unsigned(ub) - as_unsigned(lb)));
}

void put_length(SeqOut& out, std::uint64_t n) {
    if (n < 128) out.put(n, 8);
    else if (n < 16384) out.put(0x8000u | n, 16);
    else throw std::invalid_argument("a length of " + std::to_string(n) + " needs a fragmented length");
}

// The fewest octets, at least one, of an unsigned number.
std::uint32_t unsigned_octets(std::uint64_t u) { return std::max<std::uint32_t>(1, (bits_for(u) + 7) / 8); }

// The fewest octets of a two's-complement number.
std::uint32_t signed_octets(std::int64_t v) {
    for (std::uint32_t n = 1; n < 8; ++n) {
        const std::int64_t half = std::int64_t{1} << (8 * n - 1);
        if (v >= -half && v < half) return n;
    }
    return 8;
}

void put_signed(SeqOut& out, std::int64_t v) {
    const std::uint32_t n = signed_octets(v);
    put_length(out, n);
    out.put(as_unsigned(v), 8 * n);
}

void put_small(SeqOut& out, std::uint64_t n) {
    if (n <= 63) {
        out.put(0, 1);
        out.put(n, 6);
        return;
    }
    out.put(1, 1);
    const std::uint32_t octets = unsigned_octets(n);
    put_length(out, octets);
    out.put(n, 8 * octets);
}

void encode_uper_field(SeqOut& out, const SeqNode& n, const Scope& s) {
    using U = SeqNode::Uper;
    Value mv;
    const FieldLine* f = field_value(n, s, mv);
    if (!f) {
        // An absent key (ruling 1).
        switch (n.uper) {
            case U::IntExt:
            case U::EnumExt: out.put(0, 1); [[fallthrough]];
            case U::Int:
            case U::Enum: put_constrained(out, n.lb, n.ub, n.lb); return;
            case U::IntSemi:
            case U::IntUn:
                put_length(out, 1);
                out.put(0, 8);
                return;
            case U::Chars:
            case U::Octets:
                if (n.bounded) put_constrained(out, n.lb, n.ub, n.lb);
                else put_length(out, 0);
                out.zeros(static_cast<std::uint64_t>(n.lb) * (n.uper == U::Chars ? 7 : 8));
                return;
            case U::None: return;
        }
        return;
    }
    try {
        switch (n.uper) {
            case U::Int: put_constrained(out, n.lb, n.ub, encode_uper_int(*f, mv)); return;
            case U::IntExt: {
                const std::int64_t v = encode_uper_int(*f, mv);
                if (v >= n.lb && v <= n.ub) {
                    out.put(0, 1);
                    put_constrained(out, n.lb, n.ub, v);
                } else {
                    out.put(1, 1);
                    put_signed(out, v);
                }
                return;
            }
            case U::IntSemi: {
                const std::int64_t v = encode_uper_int(*f, mv);
                if (v < n.lb) throw std::invalid_argument(std::to_string(v) + " is below " + std::to_string(n.lb));
                const std::uint64_t u = as_unsigned(v) - as_unsigned(n.lb);
                const std::uint32_t octets = unsigned_octets(u);
                put_length(out, octets);
                out.put(u, 8 * octets);
                return;
            }
            case U::IntUn: put_signed(out, encode_uper_int(*f, mv)); return;
            case U::Enum:
            case U::EnumExt: {
                const std::int64_t v = model_int(mv);
                if (v < 0) throw std::invalid_argument("a negative enumeration index");
                if (v <= n.ub) {
                    if (n.uper == U::EnumExt) out.put(0, 1);
                    put_constrained(out, 0, n.ub, v);
                } else if (n.uper == U::EnumExt) {
                    out.put(1, 1);
                    put_small(out, static_cast<std::uint64_t>(v - n.ub - 1));
                } else {
                    throw std::invalid_argument("the index " + std::to_string(v) + " is outside the root of " +
                                                std::to_string(n.ub + 1) + " values");
                }
                return;
            }
            case U::Chars:
            case U::Octets: {
                FieldLine as_string;  // the model value as the `string` transform writes it
                as_string.transform = Transform::String;
                const std::string text = encode_value(as_string, mv);
                std::string bytes;
                if (n.uper == U::Chars) {
                    for (unsigned char c : text)
                        if (c > 127) throw std::invalid_argument("a character above 127");
                    bytes = text;
                } else if (f->transform == Transform::Hex) {
                    if (!hex_text_bytes(text, bytes))
                        throw std::invalid_argument("\"" + text + "\" is not hex text of an even number of digits");
                } else {
                    if (!utf8_is_valid(text)) throw std::invalid_argument("the text is not valid UTF-8");
                    bytes = text;
                }
                const std::uint64_t count = bytes.size();
                if (n.bounded) {
                    if (count < static_cast<std::uint64_t>(n.lb) || count > static_cast<std::uint64_t>(n.ub))
                        throw std::invalid_argument("a count of " + std::to_string(count) + " is outside " +
                                                    std::to_string(n.lb) + ".." + std::to_string(n.ub));
                    put_constrained(out, n.lb, n.ub, static_cast<std::int64_t>(count));
                } else {
                    put_length(out, count);
                }
                const std::uint32_t width = n.uper == U::Chars ? 7 : 8;
                for (unsigned char c : bytes) out.put(c, width);
                return;
            }
            case U::None: return;
        }
    } catch (const std::invalid_argument& ex) {
        throw Error(ErrorKind::TransformEncode, out.p.format, f->locator, f->key + ": " + ex.what());
    }
}

void encode_field(SeqOut& out, const SeqNode& n, const Scope& s) {
    const Pack& p = out.p;
    if (n.uper != SeqNode::Uper::None) {
        encode_uper_field(out, n, s);
        return;
    }
    if (n.field.until) {
        // v0.22: the text's characters, then the terminator; an absent key (no
        // default applying, ruling 10) writes the terminator alone.
        const unsigned w = chars_width(n.field.transform);
        Value mv;
        const FieldLine* f = field_value(n, s, mv);
        std::vector<std::uint8_t> codes;
        if (f) {
            try {
                codes = encode_chars_until(f->transform, mv, 2040 / w, static_cast<unsigned>(f->until_code));
            } catch (const std::invalid_argument& ex) {
                throw Error(ErrorKind::TransformEncode, p.format, f->locator, f->key + ": " + ex.what());
            }
        }
        for (std::uint8_t c : codes) out.put(c, w);
        out.put(n.field.until_code, w);
        return;
    }
    // No key and no default: zero bits.
    Value mv;
    const FieldLine* f = field_value(n, s, mv);
    if (!f) {
        // The first sentinel in place of the zero bits (0.9); it is never
        // content for a presence, `opt` or `fx` bit (ruling 4).
        if (n.field.has_absent && !s.src.suppressed(n.field)) {
            std::uint64_t raw = n.field.absent_num.front();
            if (n.field.swap) raw = swap_bytes(raw, n.len);
            out.put(raw, n.len);
        } else {
            out.zeros(n.len);
        }
        return;
    }
    try {
        out.reach(out.cur + n.len);
        if (encode_bits_text(*f, mv, out.data, out.cur, n.len, out.msb)) {
            out.cur += n.len;
        } else {
            std::uint64_t raw = encode_bits_value(*f, mv, n.len);
            if (f->swap) raw = swap_bytes(raw, n.len);
            out.put(raw, n.len);
        }
    } catch (const std::invalid_argument& ex) {
        throw Error(ErrorKind::TransformEncode, p.format, f->locator, f->key + ": " + ex.what());
    }
}

// v0.21 ruling 4: each `rest` item of a byte-counted extent starts at least 8
// bits before the extent's byte-padded end.
void check_rest_items(const Pack& p, const SeqOut::Extent& e, std::uint64_t end) {
    if (!e.bytes) return;
    for (std::uint64_t at : e.item_starts)
        if (end < at || end - at < 8)
            throw Error(ErrorKind::TransformEncode, p.format, "",
                        "a 'rest' item starts " + std::to_string(end < at ? 0 : end - at) +
                            " bits before the byte-padded end of its extent; decode would not read it");
}

void encode_group(SeqOut& out, const SeqNode& n, const Scope& s) {
    const Pack& p = out.p;
    auto it = s.item.lists.find(n.list);
    static const std::vector<Item> none;
    const std::vector<Item>& items = it == s.item.lists.end() ? none : it->second;
    const std::size_t count = items.size();
    switch (n.repeat) {
        case Repeat::Rest: {
            // Items back to back; an empty or absent list writes nothing.
            for (std::size_t k = 0; k < count; ++k) {
                const std::uint64_t start = out.cur;
                out.extents.back().item_starts.push_back(start);
                out.rest_ran = false;
                encode_body(out, n.inner, items[k]);
                if (out.cur == start)
                    throw Error(ErrorKind::TransformEncode, p.format, "",
                                "an item of the 'rest' group '" + n.list + "' writes no bits");
                // Ruling 10: an item that ends with a `rest` group of its own
                // reads to the end of the extent; no item can follow it.
                if (out.rest_ran && k + 1 < count)
                    throw Error(ErrorKind::TransformEncode, p.format, "",
                                "item " + std::to_string(k) + " of the list '" + n.list +
                                    "' ends with a 'rest' group, and another item follows it");
            }
            out.rest_ran = true;
            return;
        }
        case Repeat::Last:
            if (count == 0)
                throw Error(ErrorKind::TransformEncode, p.format, "",
                            "the list '" + n.list + "' is absent or empty, and its 'last' group needs at least one item");
            for (std::size_t k = 0; k < count; ++k) {
                out.put(k + 1 == count ? 1 : 0, 1);
                encode_body(out, n.inner, items[k]);
            }
            return;
        case Repeat::CountRef: {
            auto at = out.at_count.find(n.count_id);
            if (at == out.at_count.end())
                throw Error(ErrorKind::TransformEncode, p.format, "",
                            "the count of the list '" + n.list + "' was not written before it");
            out.count_fields[at->second].items = count;
            // v0.31: the second count holds the same number of items, each with its own `plus`.
            if (n.count_id2 >= 0) {
                auto at2 = out.at_count.find(n.count_id2);
                if (at2 == out.at_count.end())
                    throw Error(ErrorKind::TransformEncode, p.format, "",
                                "the second count of the list '" + n.list + "' was not written before it");
                out.count_fields[at2->second].items = count;
            }
            for (const Item& item : items) encode_body(out, n.inner, item);
            return;
        }
        case Repeat::Count:
            // An absent list writes a count of 0 (0.7 ruling 14).
            if (n.len < 64 && (static_cast<std::uint64_t>(count) >> n.len) != 0)
                throw Error(ErrorKind::TransformEncode, p.format, "",
                            "the list '" + n.list + "' has " + std::to_string(count) + " items, which does not fit the " +
                                std::to_string(n.len) + " bits of its count");
            out.put(count, n.len);
            for (const Item& item : items) encode_body(out, n.inner, item);
            return;
        case Repeat::Size: {
            // v0.19: an absent list is lb items with no keys.
            static const Item empty_item;
            const std::size_t written = it == s.item.lists.end() && n.bounded ? static_cast<std::size_t>(n.lb) : count;
            try {
                if (n.bounded) put_constrained(out, n.lb, n.ub, static_cast<std::int64_t>(written));
                else put_length(out, written);
            } catch (const std::invalid_argument& ex) {
                throw Error(ErrorKind::TransformEncode, p.format, "",
                            "the list '" + n.list + "' has " + std::to_string(written) + " items: " + ex.what());
            }
            if (it == s.item.lists.end())
                for (std::size_t k = 0; k < written; ++k) encode_body(out, n.inner, empty_item);
            else
                for (const Item& item : items) encode_body(out, n.inner, item);
            return;
        }
        case Repeat::While:
            for (const Item& item : items) {
                out.put(1, 1);
                encode_body(out, n.inner, item);
            }
            out.put(0, 1);
            return;
        case Repeat::More:
        case Repeat::Fx:
            // At least one item on the wire (0.8 ruling 6).
            if (count == 0)
                throw Error(ErrorKind::TransformEncode, p.format, "",
                            "the list '" + n.list + "' is absent or empty, and its group needs at least one item");
            for (std::size_t k = 0; k < count; ++k) {
                if (n.repeat == Repeat::More) out.put(k + 1 < count ? 1 : 0, 1);
                encode_body(out, n.inner, items[k]);
                if (n.repeat == Repeat::Fx) out.put(k + 1 < count ? 1 : 0, 1);
            }
            return;
    }
}

// 0.64 ruling 31: a line of a `switch` key read back after that switch was
// written, whose table has no entry, makes the encode fail at that line.
void check_after_switch(const Pack& p, const Scope& s, std::size_t before) {
    for (std::size_t i = before; i < s.shadow_d.failures.size(); ++i) {
        const auto& f = s.shadow_d.failures[i];
        if (f.table && s.switch_keys.count(f.key))
            throw Error(ErrorKind::TransformEncode, p.format, f.locator,
                        "the 'switch' key " + f.key + " does not read back from the bits written: " + f.why);
    }
}

void encode_node(SeqOut& out, const std::vector<SeqNode>& lines, std::size_t index, const Scope& s,
                 const std::vector<SeqNode>* tail) {
    const Pack& p = out.p;
    const SeqNode& n = lines[index];
    switch (n.type) {
        case Type::Field: {
            // The bits written are read back as decode reads them (0.20).
            const std::uint64_t start = out.cur;
            bool held = false;
            if (out.track_held) {
                try {
                    Value mv;
                    const FieldLine* line = field_value(n, s, mv);
                    held = line && s.item.fields.count(line->key);
                } catch (const Error&) {
                }
            }
            encode_field(out, n, s);
            if (held) out.held.emplace_back(start, out.cur);
            const std::size_t before = s.shadow_d.failures.size();
            read_back(p, out.data, start, out.cur, n, out.msb, s.shadow_d);
            check_after_switch(p, s, before);
            return;
        }
        case Type::Switch: {
            // A key whose written bits do not read back (ruling 31).
            // Every line of the key counts (0.64 ruling 31): one after the switch
            // fails where it is read back (check_after_switch).
            s.switch_keys.insert(n.field.key);
            for (const auto& f : s.shadow_d.failures)
                if (f.key == n.field.key && (f.table || !s.shadow.fields.count(n.field.key)))
                        throw Error(ErrorKind::TransformEncode, p.format, f.locator,
                                    "the 'switch' key " + f.key + " does not read back from the bits written: " + f.why);
            const SeqCase* c = select_case(p, n, s.shadow);
            const int index = c ? static_cast<int>(c - n.cases.data()) : -1;
            s.sw->actual.emplace(SwitchState::Key{&s.item, &n}, index);
            if (!c)
                throw Error(ErrorKind::NoKind, p.format, "",
                            "no 'case' of the switch on '" + n.field.key + "' (line " + std::to_string(n.field.line) +
                                ") holds the value its line wrote, and it has no 'else'");
            encode_lines(out, c->body.lines, s, nullptr);
            return;
        }
        case Type::Const: out.put(n.number, n.len); return;
        case Type::When: {
            if (n.has_at) return;  // v0.33: a window, settled after the kind's fixed lines
            if (!n.has_as) {
                out.put(n.number, n.len);
                return;
            }
            // v0.30: the bits are read back for a switch on the key (ruling 19).
            const std::uint64_t start = out.cur;
            encode_when(out, n, s);
            // 0.52 ruling 16: bits of a held key, for the windows.
            if (out.track_held && s.item.fields.count(n.field.key)) out.held.emplace_back(start, out.cur);
            const std::size_t before = s.shadow_d.failures.size();
            read_back(p, out.data, start, out.cur, n, out.msb, s.shadow_d);
            check_after_switch(p, s, before);
            return;
        }
        case Type::Pad: out.zeros(n.len); return;
        case Type::Align: out.zeros((out.cur + n.len - 1) / n.len * n.len - out.cur); return;
        case Type::Presence: {
            const SeqPresence& pr = p.seq_presences[static_cast<std::size_t>(n.presence)];
            std::vector<bool>& bits = out.presence[static_cast<std::size_t>(n.presence)];
            bits.assign(pr.bits, false);
            // The name is visible to the end of the block: the lines after this
            // one and, from the common lines of a body, the lines of its kind.
            compute_presence(p, n.presence, lines, index + 1, s, bits);
            if (tail) compute_presence(p, n.presence, *tail, 0, s, bits);
            if (!pr.fx) {
                for (std::uint32_t k = 0; k < pr.bits; ++k) out.put(bits[k] ? 1 : 0, 1);
                return;
            }
            // Trailing octets that are all zero are not written, and at least one is.
            std::size_t top = 0;
            for (std::size_t k = 0; k < bits.size(); ++k)
                if (bits[k]) top = k + 1;
            const std::size_t octets = std::max<std::size_t>(1, (top + 6) / 7);
            for (std::size_t o = 0; o < octets; ++o) {
                for (std::size_t k = o * 7; k < o * 7 + 7; ++k) out.put(k < bits.size() && bits[k] ? 1 : 0, 1);
                out.put(o + 1 < octets ? 1 : 0, 1);
            }
            return;
        }
        case Type::If:
            // Written when every bit it names is 1, and every bit named with `!` is 0.
            for (const auto& c : n.conds)
                if (out.bit(c) == c.negated) return;
            encode_lines(out, n.inner.lines, s, nullptr);
            return;
        case Type::Opt: {
            const bool has = content(n, s);
            out.put(has ? 1 : 0, 1);
            if (has) encode_lines(out, n.inner.lines, s, nullptr);
            return;
        }
        case Type::Chain: {
            const std::vector<SeqNode>& chain = n.inner.lines;
            for (std::size_t k = 0; k < chain.size(); ++k) {
                if (chain[k].type != Type::Fx) {
                    encode_node(out, chain, k, s, nullptr);
                    continue;
                }
                // 1 when any line after it in the chain would write a present key.
                bool more = false;
                for (std::size_t j = k + 1; j < chain.size() && !more; ++j) more = content(chain[j], s);
                out.put(more ? 1 : 0, 1);
                if (!more) return;
            }
            return;
        }
        case Type::Fx: return;  // a line of a chain, written there
        case Type::Length: {
            // The block, then the length. A block counted in bytes is padded
            // with zero bits to a whole byte.
            const std::uint64_t at = out.cur;
            out.zeros(n.len);
            const std::uint64_t start = out.cur;
            out.extents.push_back({start, !n.unit_bits, {}});
            const bool rest_ran = out.rest_ran;
            encode_lines(out, n.inner.lines, s, nullptr);
            out.rest_ran = rest_ran;
            if (!n.unit_bits) out.zeros((8 - (out.cur - start) % 8) % 8);
            check_rest_items(p, out.extents.back(), out.cur);
            out.extents.pop_back();
            if (n.unit_size) {
                // v0.83: a whole number of units, which the count line holds.
                const std::uint64_t bits = out.cur - start;
                if (bits % n.unit_size != 0)
                    throw Error(ErrorKind::TransformEncode, p.format, "",
                                "the block of " + std::to_string(bits) + " bits is not a whole number of units of " +
                                    std::to_string(n.unit_size) + " bits");
                auto at_count = out.at_count.find(n.count_id);
                if (at_count == out.at_count.end())
                    throw Error(ErrorKind::TransformEncode, p.format, "",
                                "the count of a 'length @' block was not written before it");
                out.count_fields[at_count->second].items = bits / n.unit_size;
                return;
            }
            const std::uint64_t units = n.unit_bits ? out.cur - start : (out.cur - start) / 8;
            const std::int64_t stated = static_cast<std::int64_t>(units) + n.plus;
            if (stated < 0 || (n.len < 64 && (static_cast<std::uint64_t>(stated) >> n.len) != 0))
                throw Error(ErrorKind::TransformEncode, p.format, "",
                            "the length " + std::to_string(stated) + " does not fit the " + std::to_string(n.len) +
                                " bits of its field");
            write_bits(out.data, at, n.len, static_cast<std::uint64_t>(stated), out.msb);
            return;
        }
        case Type::LengthWhole:
            out.wholes.push_back({out.cur, &n});
            out.zeros(n.len);
            return;
        case Type::Group: encode_group(out, n, s); return;
        case Type::Ext:
            out.put(0, 1);  // no extension additions are written
            encode_lines(out, n.inner.lines, s, nullptr);
            return;
        case Type::Choice: {
            // The first alt, in line order, with content; else the first alt.
            const SeqNode* alt = &n.inner.lines.front();
            for (const auto& a : n.inner.lines)
                if (content(a, s)) {
                    alt = &a;
                    break;
                }
            if (n.uext) out.put(0, 1);
            put_any(out, alt->number, bits_for(n.number - 1));
            encode_lines(out, alt->inner.lines, s, nullptr);
            return;
        }
        case Type::Alt: return;  // written by its choice
        case Type::Inner: {
            // v0.34: the checks made where the line is reached, the cursor on a
            // whole byte, then the inner pack's encode of the same entity.
            if (!out.host || !out.root)
                throw Error(ErrorKind::UnknownFormat, n.inner_format, "", "no loaded pack defines this format");
            const Pack& inner = out.host->reach(p, n.inner_format, n.inner_run);
            check_shared_keys(*out.host, p, inner, n);
            if (out.cur % 8 != 0)
                throw Error(ErrorKind::TransformEncode, p.format, "",
                            "the 'inner' line does not stand on a whole byte (at bit " + std::to_string(out.cur) + ")");
            // v0.92: the messages of a run, or the one the entity is.
            const RunSource* run = n.inner_run ? out.host->source() : nullptr;
            const std::size_t count = run ? run->count : 1;
            for (std::size_t k = 0; k < count; ++k) {
                const std::string bytes =
                    hex_to_bytes(inner, run ? run->hex(inner, k) : out.host->encode(inner, *out.root));
                if (n.inner_run && bytes.empty())  // v0.92 ruling 8
                    throw Error(ErrorKind::TransformEncode, p.format, "",
                                "a message of a run of " + inner.format + " writes no bytes");
                for (const char c : bytes) out.put(static_cast<unsigned char>(c), 8);
            }
            return;
        }
        case Type::Count:
            // v0.21: filled in when the message is finished; an absent list holds `plus`.
            out.at_count[n.count_id] = out.count_fields.size();
            out.count_fields.push_back({out.cur, &n, 0});
            out.zeros(n.len);
            return;
    }
}

void encode_lines(SeqOut& out, const std::vector<SeqNode>& lines, const Scope& s, const std::vector<SeqNode>* tail) {
    for (std::size_t k = 0; k < lines.size(); ++k) encode_node(out, lines, k, s, tail);
}

// v0.20: the case a switch is predicted to select. The first prediction is
// what the first line of the scope that maps the key would write, read back.
int predicted_case(const SeqNode& n, const Scope& s) {
    const SwitchState::Key key{&s.item, &n};
    auto it = s.sw->guess.find(key);
    int index = -1;
    if (it != s.sw->guess.end()) {
        index = it->second;
    } else {
        const SeqNode* line = nullptr;
        std::function<void(const std::vector<SeqNode>&)> find = [&](const std::vector<SeqNode>& lines) {
            for (const auto& l : lines) {
                if (line) return;
                if (l.type == Type::Field) {
                    if (l.field.key == n.field.key) line = &l;
                    for (const auto& a : l.also)
                        if (a.key == n.field.key) line = &l;
                } else if (l.type == Type::When) {
                    if (l.has_as && l.field.key == n.field.key) line = &l;  // v0.30 ruling 19
                } else if (l.type != Type::Group) {
                    find(l.inner.lines);
                    for (const auto& c : l.cases) find(c.body.lines);
                }
            }
        };
        find(s.body.lines);
        if (!line && s.kind) find(s.kind->lines);
        Item back;
        if (line) {
            SeqOut tmp{s.p, std::string(), bit_mode(s.p.bit_order), 0, {}, {}, s.sw};
            try {
                if (line->type == Type::When) encode_when(tmp, *line, s);
                else encode_field(tmp, *line, s);
                Decoder d(s.p, back);
                read_back(s.p, tmp.data, 0, tmp.cur, *line, tmp.msb, d);
            } catch (const Error&) {
            }
        }
        const SeqCase* c = select_case(s.p, n, back);
        index = c ? static_cast<int>(c - n.cases.data()) : -1;
        s.sw->guess.emplace(key, index);
    }
    s.sw->used.emplace(key, index);
    return index;
}

// v0.33: settle each window of the kind, in line order, over the bits its
// fixed lines wrote from kind start (Encode, rulings 1, 12, 13 and 26).
void settle_windows(SeqOut& out, const Scope& s, const SeqKind& k, std::uint64_t kind_start) {
    const Pack& p = out.p;
    for (const auto& w : k.lines) {
        if (w.type != Type::When) break;
        if (!w.has_at) continue;
        const std::uint64_t pos = kind_start + w.at;
        const std::uint64_t end = pos + w.len;
        const std::uint64_t bits = read_bits(out.data, pos, w.len, out.msb);
        bool held_as = false;
        std::uint64_t u = 0;
        if (w.has_as) {
            auto it = s.item.fields.find(w.field.key);
            if (it != s.item.fields.end()) {
                if (!as_pattern(it->second, u) || !w.holds(u))
                    throw Error(ErrorKind::TransformEncode, p.format, w.field.locator,
                                w.field.key + ": the value is not one the 'when' on line " + std::to_string(w.line) +
                                    " holds for");
                held_as = true;
            }
        }
        // 0.52 ruling 16: bits of a held key for the later windows, whether
        // they stand or are written; a window takes no bit away from a held key.
        if (w.holds(bits) && (!held_as || bits == u)) {  // the bits stand
            if (held_as) out.held.emplace_back(pos, end);
            continue;
        }
        const std::uint64_t value = held_as ? u : w.number;
        // Only the bits a held key wrote are compared with the window's value.
        std::string written = out.data;
        write_bits(written, pos, w.len, value, out.msb);
        for (const auto& h : out.held) {
            const std::uint64_t lo = std::max(h.first, pos), hi = std::min(h.second, end);
            for (std::uint64_t b = lo; b < hi; ++b)
                if (read_bits(written, b, 1, out.msb) != read_bits(out.data, b, 1, out.msb))
                    throw Error(ErrorKind::TransformEncode, p.format, "",
                                "the window of 'when " + std::to_string(w.len) + " ... at " + std::to_string(w.at) +
                                    "' (line " + std::to_string(w.line) +
                                    ") would change bits a key the entity holds wrote; the output would decode "
                                    "another value");
        }
        out.data.swap(written);
        if (held_as) out.held.emplace_back(pos, end);
    }
}

void encode_kind(SeqOut& out, const Scope& s);

void encode_body(SeqOut& out, const SeqBody& body, const Item& item) {
    const Scope s(out.p, item, body, select_kind(out.p, body, item), out.sw);
    encode_lines(out, body.lines, s, s.kind ? &s.kind->lines : nullptr);
    if (s.kind) encode_kind(out, s);
}

// The lines of the selected kind.
void encode_kind(SeqOut& out, const Scope& s) {
    const SeqKind& k = *s.kind;
    if (k.window_lines == 0) {
        encode_lines(out, k.lines, s, nullptr);
        return;
    }
    // v0.33: the fixed lines that hold the windows, then the windows, then
    // the rest; a switch reads its key from the bits as settled.
    const std::uint64_t kind_start = out.cur;
    out.held.clear();
    out.track_held = true;
    // What the common lines read back as: an earlier line of a key keeps it.
    const std::map<std::string, Value> common_fields = s.shadow.fields;
    const std::size_t common_failures = s.shadow_d.failures.size(), common_closed = s.shadow_d.closed.size();
    std::vector<std::uint64_t> starts;
    for (std::size_t i = 0; i < k.window_lines; ++i) {
        starts.push_back(out.cur);
        encode_node(out, k.lines, i, s, nullptr);
    }
    starts.push_back(out.cur);
    out.track_held = false;
    settle_windows(out, s, k, kind_start);
    out.held.clear();
    // The keys of those lines read back again from the settled bits.
    s.shadow.fields = common_fields;
    s.shadow_d.failures.resize(common_failures);
    s.shadow_d.closed.resize(common_closed);
    // A window's line may stand after the lines its window covers.
    for (std::size_t i = 0; i < k.lines.size() && (i < k.window_lines || k.lines[i].type == Type::When); ++i) {
        const SeqNode& n = k.lines[i];
        if (i >= k.window_lines && !n.has_at) continue;
        const std::size_t before = s.shadow_d.failures.size();
        if (n.type == Type::Field || (n.type == Type::When && n.has_as && !n.has_at))
            read_back(out.p, out.data, starts[i], starts[i + 1], n, out.msb, s.shadow_d);
        else if (n.type == Type::When && n.has_as)
            read_back(out.p, out.data, kind_start + n.at, kind_start + n.at + n.len, n, out.msb, s.shadow_d);
        check_after_switch(out.p, s, before);
    }
    for (std::size_t i = k.window_lines; i < k.lines.size(); ++i) encode_node(out, k.lines, i, s, nullptr);
}

}  // namespace

namespace {
std::string finish_seq(const Pack& p, SeqOut& out);
}

std::vector<const SeqCase*> seq_cases_by_id(const Pack& p) {
    std::vector<const SeqCase*> cases(p.seq_cases.size(), nullptr);
    std::function<void(const std::vector<SeqNode>&)> walk = [&](const std::vector<SeqNode>& lines) {
        for (const auto& n : lines) {
            walk(n.inner.lines);
            for (const auto& k : n.inner.kinds) walk(k.lines);
            for (const auto& c : n.cases) {
                cases[static_cast<std::size_t>(c.id)] = &c;
                walk(c.body.lines);
            }
        }
    };
    walk(p.seq.lines);
    for (const auto& k : p.seq.kinds) walk(k.lines);
    return cases;
}

RunLine seq_run_line(const Pack& p, const Entity& e) {
    RunLine r;
    r.kind = select_kind(p, p.seq, e);
    r.line = run_line_of(p.seq.lines);
    if (!r.line && r.kind) r.line = run_line_of(r.kind->lines);
    return r;
}

std::string encode_seq(const Pack& p, const Entity& e, const InnerHost* host) {
    SwitchState state;
    if (const PackPlan* plan = plan_of(p)) {
        state.cases = &plan->seq_cases;
    } else {
        state.own_cases = seq_cases_by_id(p);
        state.cases = &state.own_cases;
    }
    // The encode is repeated while a switch selects another case than the one
    // its presence, `opt` and `fx` bits were computed from (a few passes at most).
    for (int pass = 0;; ++pass) {
        SeqOut out{p, std::string(), bit_mode(p.bit_order), 0,
                   std::vector<std::vector<bool>>(p.seq_presences.size()), {}, &state};
        out.host = host;
        out.root = &e;
        state.used.clear();
        state.actual.clear();
        auto mispredicted = [&]() {
            bool changed = false;
            for (const auto& a : state.actual) {
                auto u = state.used.find(a.first);
                if (u != state.used.end() && u->second != a.second) changed = true;
                state.guess[a.first] = a.second;
            }
            if (changed && pass >= 8)
                throw Error(ErrorKind::TransformEncode, p.format, "",
                            "the cases of the switches do not settle (ruling 33)");
            return changed;
        };
        try {
            encode_body(out, p.seq, e);
        } catch (const Error&) {
            if (mispredicted()) continue;
            throw;
        }
        if (mispredicted()) continue;
        return finish_seq(p, out);
    }
}

namespace {
std::string finish_seq(const Pack& p, SeqOut& out) {
    // A message is a whole number of bytes: the last byte's remaining bits are
    // zero. A UPER encoding of no bits is one octet 00 (0.19).
    out.data.resize(static_cast<std::size_t>((out.cur + 7) / 8), '\0');
    check_rest_items(p, out.extents.front(), (out.cur + 7) / 8 * 8);
    // v0.21: each count holds its items plus `n` (ruling 30: checked here).
    for (const auto& c : out.count_fields) {
        const SeqNode& n = *c.node;
        const bool fits = n.plus >= 0
                              ? c.items <= ~std::uint64_t{0} - static_cast<std::uint64_t>(n.plus)
                              : true;
        std::uint64_t value = 0;
        bool ok = fits;
        if (fits) {
            if (n.plus >= 0) {
                value = c.items + static_cast<std::uint64_t>(n.plus);
            } else {
                const std::uint64_t sub = static_cast<std::uint64_t>(-(n.plus + 1)) + 1;
                ok = c.items >= sub;
                value = ok ? c.items - sub : 0;
            }
        }
        if (ok && n.len < 64 && (value >> n.len) != 0) ok = false;
        if (!ok)
            throw Error(ErrorKind::TransformEncode, p.format, "",
                        "the count '" + n.count_name + "' of " + std::to_string(c.items) + " items plus " +
                            std::to_string(n.plus) + " does not fit 0 to 2^" + std::to_string(n.len) + " - 1");
        write_bits(out.data, c.at, n.len, value, bit_mode(p.bit_order));
    }
    // Under armor, L is the cursor after the last line, not rounded to a byte
    // (0.14), once the counts are filled in (0.21); `length ... whole` is
    // refused at load.
    if (p.armor_sixbit) return bytes_to_armor(out.data, out.cur);
    if (p.uper && out.data.empty()) out.data.assign(1, '\0');
    for (const auto& w : out.wholes) {
        const std::int64_t stated = static_cast<std::int64_t>(out.data.size()) + w.node->plus;
        if (stated < 0 || (w.node->len < 64 && (static_cast<std::uint64_t>(stated) >> w.node->len) != 0))
            throw Error(ErrorKind::TransformEncode, p.format, "",
                        "the length " + std::to_string(stated) + " of the whole message does not fit the " +
                            std::to_string(w.node->len) + " bits of its field");
        write_bits(out.data, w.at, w.node->len, static_cast<std::uint64_t>(stated), bit_mode(p.bit_order));
    }
    return bytes_to_hex(out.data);
}
}  // namespace

#endif  // GT_WIRE_BITS

}  // namespace goat_transformers::detail
