// Sequential binary layouts (engine-spec.md, Version 0.8): the pack grammar,
// decode from a cursor and the two-pass encode.
#include "sequential.hpp"

#include <algorithm>
#include <cstdint>
#include <map>
#include <set>
#include <stdexcept>
#include <unordered_map>

#include "codecs.hpp"
#include "transforms.hpp"

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

// A signed decimal integer: `plus <n>`.
bool parse_i64(const std::string& s, std::int64_t& out) {
    const bool neg = !s.empty() && s[0] == '-';
    const std::size_t from = !s.empty() && (s[0] == '-' || s[0] == '+') ? 1 : 0;
    std::uint64_t v = 0;
    if (!parse_u64(s.substr(from), v)) return false;
    if (v > static_cast<std::uint64_t>(INT64_MAX)) return false;
    out = neg ? -static_cast<std::int64_t>(v) : static_cast<std::int64_t>(v);
    return true;
}

template <class Lines, class Fn>
void each_node(Lines& lines, Fn&& fn) {
    for (auto& n : lines) {
        fn(n);
        each_node(n.inner.lines, fn);
        for (auto& k : n.inner.kinds) each_node(k.lines, fn);
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
    std::vector<const SeqNode*> blocks;  // the `if` and `opt` blocks of the scope that hold the group, outermost first
};

void check_lists_once(const Pack& p, const SeqBody& body, const std::string& source);

void collect_groups(const Pack& p, const std::vector<SeqNode>& lines, std::vector<const SeqNode*>& blocks,
                    const std::string& source, std::vector<ListUse>& out) {
    for (const auto& n : lines) {
        if (n.type == Type::Group) {
            out.push_back({&n, blocks});
            check_lists_once(p, n.inner, source);  // the items are a scope of their own
        } else if (n.type == Type::If || n.type == Type::Opt) {
            blocks.push_back(&n);
            collect_groups(p, n.inner.lines, blocks, source, out);
            blocks.pop_back();
        } else {
            collect_groups(p, n.inner.lines, blocks, source, out);
        }
    }
}

void check_lists_once(const Pack& p, const SeqBody& body, const std::string& source) {
    std::vector<const SeqNode*> blocks;
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
        std::set<std::string> kinds;
    };
    std::vector<Frame> stack(1);
    stack[0].is_body = true;
    stack[0].body = &p.seq;
    stack[0].what = "the message";

    // The `field` an `also` line may follow: the last line, when it was a
    // `field` or an `also`.
    SeqNode* also_target = nullptr;
    std::size_t lineno = 0, pos = 0;

    auto lines_of = [](Frame& f) -> std::vector<SeqNode>& {
        return f.body->kinds.empty() ? f.body->lines : f.body->kinds.back().lines;
    };
    auto body_frame = [&]() -> Frame& {
        for (std::size_t k = stack.size(); k-- > 0;)
            if (stack[k].is_body) return stack[k];
        return stack[0];
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
            throw Error(ErrorKind::InvalidPack, p.format, "", source + ":" + std::to_string(lineno) + ": " + err);
        if (t.empty()) continue;

        const std::string where = source + ":" + std::to_string(lineno);
        const std::string& kw = t[0];
        auto bad = [&](const std::string& why) -> Error {
            return Error(ErrorKind::BadDirective, p.format, "", where + ": " + why);
        };
        auto arity = [&](std::size_t n) {
            if (t.size() != n + 1)
                throw Error(ErrorKind::InvalidPack, p.format, "",
                            where + ": '" + kw + "' takes " + std::to_string(n) + " argument(s), got " +
                                std::to_string(t.size() - 1));
        };
        auto once = [&](bool& seen) {
            if (seen) throw Error(ErrorKind::InvalidPack, p.format, "", where + ": duplicate '" + kw + "'");
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

        SeqNode* const prev_field = also_target;
        also_target = nullptr;

        // Header and table directives describe the pack, not a part of the
        // message: inside any block they are bad-directive (0.8 ruling 24).
        if (stack.size() > 1 &&
            (kw == "format" || kw == "version" || kw == "distribution" || kw == "source" || kw == "uses" ||
             kw == "wire" || kw == "layout" || kw == "bit_order" || kw == "map" || kw == "typemap"))
            throw bad("'" + kw + "' is not allowed inside " + stack.back().what);

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
            else throw Error(ErrorKind::InvalidPack, p.format, "", where + ": distribution '" + t[1] + "'");
        } else if (kw == "source") {
            arity(1);
            p.sources.push_back(t[1]);
        } else if (kw == "uses") {
            arity(1);
            if (std::find(p.uses.begin(), p.uses.end(), t[1]) == p.uses.end()) p.uses.push_back(t[1]);
        } else if (kw == "wire") {
            arity(1);
            once(have_wire);
            if (t[1] == "xml") p.wire = Wire::Xml;
            else if (t[1] == "geojson") p.wire = Wire::GeoJson;
            else if (t[1] == "bits") p.wire = Wire::Bits;
            else if (t[1] == "protobuf") p.wire = Wire::Protobuf;
            else if (t[1] == "json") p.wire = Wire::Json;
            else throw Error(ErrorKind::UnknownWire, p.format, "", where + ": wire '" + t[1] + "'");
        } else if (kw == "layout") {
            arity(1);
            once(have_layout);
            if (t[1] != "sequential") throw bad("layout '" + t[1] + "' in a pack that also has 'layout sequential'");
        } else if (kw == "word_bytes") {
            throw bad("'word_bytes' is not used in a sequential pack");
        } else if (kw == "root") {
            throw bad("'root' applies to wire xml only");
        } else if (kw == "bit_order") {
            arity(1);
            once(have_bit_order);
            if (t[1] == "lsb") p.bit_order = BitOrder::Lsb;
            else if (t[1] == "msb") p.bit_order = BitOrder::Msb;
            else throw bad("bit_order '" + t[1] + "' is not lsb or msb");
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
                throw Error(ErrorKind::InvalidPack, p.format, "", where + ": duplicate typemap code '" + t[1] + "'");
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
        } else if (kw == "when") {
            // The `when` lines of a kind are its first lines; a `when` before
            // the first `kind` is a common one (0.8 ruling 10).
            Frame& f = stack.back();
            if (!f.is_body) throw bad("'when' inside " + f.what);
            arity(2);
            for (const auto& n : lines_of(f))
                if (!f.body->kinds.empty() && n.type != Type::When)
                    throw bad("'when' after another line of its kind");
            SeqNode n;
            n.type = Type::When;
            n.len = small_len(t[1], "a 'when'");
            if (!parse_u64(t[2], n.number))
                throw bad("'when' value '" + t[2] + "' is not an unsigned decimal integer");
            if (n.len < 64 && (n.number >> n.len) != 0)
                throw bad("'when' value " + t[2] + " does not fit " + std::to_string(n.len) + " bits");
            add(std::move(n));
        } else if (kw == "requires") {
            Frame& f = stack.back();
            if (!f.is_body) throw bad("'requires' inside " + f.what);
            if (f.body->kinds.empty()) throw bad("'requires' before the first 'kind'");
            if (t.size() < 2)
                throw Error(ErrorKind::InvalidPack, p.format, "", where + ": 'requires' takes at least 1 argument");
            for (std::size_t k = 1; k < t.size(); ++k) f.body->kinds.back().requires_keys.push_back(t[k]);
        } else if (kw == "default") {
            // A `default` inside a block belongs to the message or item that holds the block.
            arity(2);
            DefaultLine d;
            d.key = t[1];
            d.text = t[2];
            d.line = lineno;
            Frame& f = body_frame();
            (f.body->kinds.empty() ? f.body->defaults : f.body->kinds.back().defaults).push_back(std::move(d));
        } else if (kw == "field") {
            if (t.size() < 4)
                throw Error(ErrorKind::InvalidPack, p.format, "",
                            where + ": 'field' takes a key, a bit length and a transform, got " +
                                std::to_string(t.size() - 1) + " argument(s)");
            SeqNode n;
            n.type = Type::Field;
            FieldLine& f = n.field;
            f.key = t[1];
            f.locator = t[2];
            f.line = lineno;
            if (f.locator.find(':') != std::string::npos)
                throw bad("a positional <word>:<pos>:<len> locator in a sequential pack: '" + f.locator + "'");
            if (!parse_u32(f.locator, n.len)) throw bad("the locator of a sequential field is a bit length, not '" + f.locator + "'");
            std::string terr;
            if (!parse_transform(t[3], f, terr))
                throw Error(ErrorKind::UnknownTransform, p.format, f.locator,
                            where + ": " + terr + " for field '" + f.key + "'");
            if (!transform_is_bits(f.transform))
                throw Error(ErrorKind::InvalidPack, p.format, f.locator,
                            where + ": transform '" + std::string(transform_name(f.transform)) +
                                "' is not valid on wire bits");
            for (std::size_t k = 4; k < t.size(); ++k) {
                if (t[k] == "via") {
                    if (k + 1 >= t.size() || t[k + 1].empty() || !f.via.empty())
                        throw bad("'via' takes one table name, once");
                    f.via = t[++k];
                    continue;
                }
                bool* flag = t[k] == "swap" ? &f.swap : t[k] == "trim" ? &f.trim : nullptr;
                if (t[k] == "optional") throw bad("the field option 'optional' is not allowed in a sequential pack");
                if (!flag || *flag) throw bad("'" + t[k] + "' is not a field option, or is given twice");
                *flag = true;
            }
            // The bit lengths a transform allows, and what `swap` and `trim` need.
            bool ok = false;
            switch (f.transform) {
                case Transform::F32: ok = n.len == 32; break;
                case Transform::F64: ok = n.len == 64; break;
                case Transform::Ascii: ok = n.len >= 8 && n.len <= 2040 && n.len % 8 == 0; break;
                default: ok = n.len >= 1 && n.len <= 64; break;
            }
            if (!ok)
                throw bad("transform '" + std::string(transform_name(f.transform)) + "' does not allow a length of " +
                          std::to_string(n.len) + " bits");
            if (f.trim && f.transform != Transform::Ascii) throw bad("option 'trim' applies to transform ascii only");
            if (f.swap && n.len % 8 != 0)
                throw bad("option 'swap' needs a length that is a multiple of 8 bits, not " + std::to_string(n.len));
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
            prev_field->also.push_back(std::move(f));
            also_target = prev_field;
        } else if (kw == "const") {
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
            if (t[1].empty() || f.names.count(t[1]) || f.kind_names.count(t[1]))
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
                for (std::size_t d = stack.size(); d-- > 0 && c.presence < 0;) {
                    auto it = stack[d].kind_names.find(name);
                    if (it == stack[d].kind_names.end()) {
                        it = stack[d].names.find(name);
                        if (it == stack[d].names.end()) continue;
                    }
                    c.presence = it->second;
                }
                if (c.presence < 0) throw bad("'if' names the presence '" + name + "', which is not visible here");
                SeqPresence& pr = p.seq_presences[static_cast<std::size_t>(c.presence)];
                if (!pr.fx && c.bit > pr.bits)
                    throw bad("'if' names bit " + std::to_string(c.bit) + " of the presence '" + name + "', which has " +
                              std::to_string(pr.bits));
                if (pr.named.size() < c.bit) pr.named.resize(c.bit, false);
                pr.named[c.bit - 1] = true;
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
            } else {
                open(std::move(n), "a 'length' block");
            }
        } else if (kw == "group") {
            // `group <list> count <len>`, or `group <list> while | more | fx`.
            SeqNode n;
            n.type = Type::Group;
            if (t.size() >= 2) n.list = t[1];
            if (t.size() == 4 && t[2] == "count") {
                n.repeat = Repeat::Count;
                n.len = small_len(t[3], "a count");
            } else if (t.size() == 3 && (t[2] == "while" || t[2] == "more" || t[2] == "fx")) {
                n.repeat = t[2] == "while" ? Repeat::While : t[2] == "more" ? Repeat::More : Repeat::Fx;
            } else {
                throw bad("a group of a sequential pack is 'group <list> count <len>' or 'group <list> while | more | fx'");
            }
            open(std::move(n), "the group '" + t[1] + "'");
        } else if (kw == "end") {
            if (stack.size() < 2) throw bad("'end' with no open block");
            arity(0);
            check_common_when(stack.back());
            stack.pop_back();
        } else {
            throw Error(ErrorKind::UnknownDirective, p.format, "", where + ": directive '" + kw + "'");
        }
    }

    // Checks that need the whole file, before `missing-distribution`.
    if (stack.size() > 1)
        throw Error(ErrorKind::BadDirective, p.format, "",
                    source + ":" + std::to_string(stack.back().line) + ": " + stack.back().what + " has no 'end'");
    check_common_when(stack[0]);
    if (have_wire && p.wire != Wire::Bits)
        throw Error(ErrorKind::BadDirective, p.format, "", source + ": 'layout sequential' applies to wire bits only");
    check_lists_once(p, p.seq, source);
    // `via` names a table of the pack; a `map` line may follow the field.
    auto resolve = [&](FieldLine& f) {
        if (f.via.empty()) return;
        auto it = table_index.find(f.via);
        if (it == table_index.end())
            throw Error(ErrorKind::BadDirective, p.format, f.locator,
                        source + ":" + std::to_string(f.line) + ": 'via " + f.via + "' names a table with no 'map' line");
        f.table = it->second;
    };
    auto resolve_node = [&](SeqNode& n) {
        if (n.type != Type::Field) return;
        resolve(n.field);
        for (auto& a : n.also) resolve(a);
    };
    each_node(p.seq.lines, resolve_node);
    for (auto& k : p.seq.kinds) each_node(k.lines, resolve_node);

    if (!have_distribution)
        throw Error(ErrorKind::MissingDistribution, p.format, "", source + ": pack has no 'distribution'");
    if (p.sources.empty()) throw Error(ErrorKind::MissingSource, p.format, "", source + ": pack has no 'source'");
    if (!have_format || p.format.empty()) throw Error(ErrorKind::InvalidPack, "", "", source + ": missing 'format'");
    if (!have_wire) throw Error(ErrorKind::InvalidPack, p.format, "", source + ": missing 'wire'");
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
        if (n.type == Type::Group && v.group) v.group(n);
        visit_body(n.inner, v);
    }
}

void keys_of_lines(const std::vector<SeqNode>& lines, const std::string& prefix,
                   const std::function<void(const std::string&)>& add) {
    for (const auto& n : lines) {
        if (n.type == Type::Field) {
            add(prefix + n.field.key);
            for (const auto& a : n.also) add(prefix + a.key);
        } else if (n.type == Type::Group) {
            add(prefix + n.list + "[]");
            seq_model_keys(n.inner, prefix + n.list + "[].", add);
        } else {
            keys_of_lines(n.inner.lines, prefix, add);
        }
    }
}
}  // namespace

void seq_visit(SeqBody& body, const SeqVisitor& v) { visit_body(body, v); }

void seq_model_keys(const SeqBody& body, const std::string& prefix,
                    const std::function<void(const std::string&)>& add) {
    keys_of_lines(body.lines, prefix, add);
    for (const auto& k : body.kinds) keys_of_lines(k.lines, prefix, add);
}

// ---------------------------------------------------------------- decode

namespace {

const std::uint64_t kNoExtent = ~std::uint64_t{0};

struct SeqIn {
    const Pack& p;
    const std::string& data;
    bool msb;
    std::uint64_t have;                // bits of input, or of the message a `length ... whole` states
    std::uint64_t ext = kNoExtent;     // where the innermost `length` block ends
    std::uint64_t cur = 0;             // the cursor
    std::vector<std::vector<bool>> presence;  // by SeqPresence index: the bits last read
    // The first transform failure. It is kept until the whole message has been
    // read, so that input that is too short is malformed-wire first.
    bool failed = false;
    std::string fail_locator, fail_detail;

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
        const std::uint64_t v = read_bits(data, cur, len, msb);
        cur += len;
        return v;
    }
    bool bit(const SeqCond& c) const {
        const std::vector<bool>& v = presence[static_cast<std::size_t>(c.presence)];
        return c.bit <= v.size() && v[c.bit - 1];
    }
};

void decode_body(SeqIn& in, const SeqBody& body, Item& out);
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

void decode_group(SeqIn& in, const SeqNode& n, Item& out) {
    auto item = [&](std::vector<Item>& items) {
        items.emplace_back();
        decode_body(in, n.inner, items.back());
    };
    switch (n.repeat) {
        case Repeat::Count: {
            if (!in.need(n.len, "a count")) return;  // beyond the extent: an absent list
            const std::uint64_t count = in.take(n.len);
            // A count larger than the bits left is malformed-wire before any item is read.
            const std::uint64_t end = in.ext != kNoExtent ? in.ext : in.have;
            if (count > end - in.cur)
                in.malformed("the count " + std::to_string(count) + " of the group '" + n.list +
                             "' is larger than the bits left");
            std::vector<Item>& items = out.lists[n.list];
            items.clear();
            for (std::uint64_t k = 0; k < count; ++k) item(items);
            return;
        }
        case Repeat::While: {
            if (!in.need(1, "the bit before an item")) return;
            std::vector<Item>& items = out.lists[n.list];
            items.clear();
            while (in.need(1, "the bit before an item") && in.take(1) == 1) item(items);
            return;
        }
        case Repeat::More: {
            if (!in.need(1, "the bit before an item")) return;
            std::vector<Item>& items = out.lists[n.list];
            items.clear();
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
            std::vector<Item>& items = out.lists[n.list];
            items.clear();
            for (;;) {
                item(items);
                if (!in.need(1, "the bit after an item") || in.take(1) == 0) return;
            }
        }
    }
}

void decode_node(SeqIn& in, const SeqNode& n, Item& out, Decoder& d) {
    const Pack& p = in.p;
    switch (n.type) {
        case Type::Field: {
            if (!in.need(n.len, "a field")) return;
            const FieldLine& f = n.field;
            const std::uint64_t start = in.cur;
            in.cur += n.len;
            // Every key bound to the bits takes the value, each through its own table.
            try {
                Value v;
                if (f.transform == Transform::Ascii) {
                    std::string text;
                    for (std::uint32_t k = 0; k < n.len / 8; ++k)
                        text += static_cast<char>(read_bits(in.data, start + 8ull * k, 8, in.msb));
                    if (f.swap) std::reverse(text.begin(), text.end());
                    v = decode_ascii(text, f.trim);
                } else {
                    std::uint64_t raw = read_bits(in.data, start, n.len, in.msb);
                    if (f.swap) raw = swap_bytes(raw, n.len);
                    v = decode_bits_value(f, raw, n.len);
                }
                d.put(f, v);
                for (const auto& a : n.also) d.put(a, v);
            } catch (const std::invalid_argument& ex) {
                d.fail(f, ex.what());
                for (const auto& a : n.also) d.fail(a, ex.what());
            }
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
        case Type::When:
            // A common `when`: it must hold for any message of the format.
            if (in.cur > in.have || n.len > in.have - in.cur || (in.ext != kNoExtent && in.cur + n.len > in.ext) ||
                in.take(n.len) != n.number)
                throw Error(ErrorKind::NoKind, p.format, "",
                            "the common 'when " + std::to_string(n.len) + " " + std::to_string(n.number) +
                                "' does not hold");
            return;
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
            for (std::size_t k = 0; k < bits.size(); ++k)
                if (bits[k] && (k >= pr.named.size() || !pr.named[k]))
                    in.malformed("bit " + std::to_string(k + 1) + " of the presence '" + pr.name +
                                 "' is 1 and no 'if' block names it");
            return;
        }
        case Type::If: {
            for (const auto& c : n.conds)
                if (in.bit(c) == c.negated) return;
            decode_lines(in, n.inner.lines, 0, out, d);
            return;
        }
        case Type::Opt:
            if (in.need(1, "the bit of an 'opt'") && in.take(1) == 1) decode_lines(in, n.inner.lines, 0, out, d);
            return;
        case Type::Chain: {
            if (in.ext != kNoExtent && in.cur >= in.ext) return;
            const std::vector<SeqNode>& lines = n.inner.lines;
            for (std::size_t k = 0; k < lines.size(); ++k) {
                if (lines[k].type != Type::Fx) {
                    decode_node(in, lines[k], out, d);
                    continue;
                }
                // A 0 bit ends the chain.
                if (!in.need(1, "an 'fx' bit") || in.take(1) == 0) return;
                if (k + 1 == lines.size())
                    in.malformed("the last 'fx' bit of a chain is 1 and the chain has no further part");  // ruling 3
            }
            return;
        }
        case Type::Fx: return;  // a line of a chain, read there
        case Type::Length: {
            if (!in.need(n.len, "a length field")) return;
            const std::uint64_t stated = in.take(n.len);
            std::uint64_t units = 0;
            if (!stated_units(stated, n.plus, units) || units > (kNoExtent >> 4))
                in.malformed("the stated length " + std::to_string(stated) + " is below 'plus " +
                             std::to_string(n.plus) + "', or too large");
            const std::uint64_t bits = n.unit_bits ? units : units * 8;
            const std::uint64_t outer = in.ext != kNoExtent ? in.ext : in.have;
            if (bits > outer - in.cur) in.malformed("a 'length' extent of " + std::to_string(bits) + " bits runs past the input");
            const std::uint64_t saved = in.ext;
            in.ext = in.cur + bits;
            decode_lines(in, n.inner.lines, 0, out, d);
            in.cur = in.ext;  // content of the extent no line read is skipped
            in.ext = saved;
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
            return;
        }
        case Type::Group: decode_group(in, n, out); return;
    }
}

void decode_lines(SeqIn& in, const std::vector<SeqNode>& lines, std::size_t from, Item& out, Decoder& d) {
    for (std::size_t k = from; k < lines.size(); ++k) decode_node(in, lines[k], out, d);
}

// The message, or one item of a group: the common lines, then the lines of the
// first kind whose `when` lines all hold at the cursor.
void decode_body(SeqIn& in, const SeqBody& body, Item& out) {
    const Pack& p = in.p;
    Decoder d(p, out);
    decode_lines(in, body.lines, 0, out, d);
    if (!body.kinds.empty()) {
        const SeqKind* selected = nullptr;
        std::size_t whens = 0;
        const std::uint64_t end = in.ext != kNoExtent ? std::min(in.ext, in.have) : in.have;
        for (const auto& k : body.kinds) {
            std::uint64_t at = in.cur;
            std::size_t i = 0;
            bool holds = true;
            for (; i < k.lines.size() && k.lines[i].type == Type::When && holds; ++i) {
                const SeqNode& w = k.lines[i];
                // A `when` any of whose bits lies beyond the input does not hold.
                if (at > end || w.len > end - at || read_bits(in.data, at, w.len, in.msb) != w.number) holds = false;
                else at += w.len;
            }
            if (!holds) continue;
            selected = &k;
            whens = i;
            in.cur = at;
            break;
        }
        if (!selected)
            throw Error(ErrorKind::NoKind, p.format, "",
                        "the " + std::string(&body == &p.seq ? "message" : "item") + " matches no kind (at bit " +
                            std::to_string(in.cur) + ")");
        out.kind = {p.format, selected->name};
        decode_lines(in, selected->lines, whens, out, d);
    }
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

Entity decode_seq(const Pack& p, const std::string& bytes) {
    const std::string data = hex_to_bytes(p, bytes);
    SeqIn in{p, data, p.bit_order == BitOrder::Msb, static_cast<std::uint64_t>(data.size()) * 8, kNoExtent, 0,
             std::vector<std::vector<bool>>(p.seq_presences.size()), false, {}, {}};
    Entity e;
    decode_body(in, p.seq, e);
    // Input beyond the last line, whole bytes included, is ignored (0.8 ruling 9).
    if (in.failed) throw Error(ErrorKind::TransformDecode, p.format, in.fail_locator, in.fail_detail);
    return e;
}

// ---------------------------------------------------------------- encode

namespace {

// What one message or item is written from: its keys and lists, its kind, and
// the `default` lines in scope (the kind's, then the common ones of its body).
struct Scope {
    const Item& item;
    const SeqBody& body;
    const SeqKind* kind;
    EncodeSource src;

    Scope(const Pack& p, const Item& it, const SeqBody& b, const SeqKind* k)
        : item(it), body(b), kind(k), src(p, static_cast<const Kind*>(nullptr), it) {
        src.defaults = Defaults{k ? &k->defaults : nullptr, &b.defaults};
    }
    // A key with a `default` in scope counts as present (0.8 ruling 2).
    bool present(const std::string& key) const {
        if (item.fields.count(key)) return true;
        for (const std::vector<DefaultLine>* defs : {src.defaults.first, src.defaults.second}) {
            if (!defs) continue;
            for (const auto& d : *defs)
                if (d.key == key) return true;
        }
        return false;
    }
};

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
    for (const auto& k : body.kinds) {
        bool all = true;
        for (const auto& key : k.requires_keys) {
            if (item.fields.count(key)) continue;
            auto list = item.lists.find(key);
            if (list == item.lists.end() || list->second.empty()) {
                all = false;
                break;
            }
        }
        if (all) return &k;
    }
    throw Error(ErrorKind::NoKind, p.format, "", "the entity or item has the 'requires' keys of no kind");
}

// Would the line write a present key, a non-empty list, or a nested presence
// that is not all zero?
bool content(const SeqNode& n, const Scope& s) {
    switch (n.type) {
        case Type::Field:
            if (s.present(n.field.key)) return true;
            for (const auto& a : n.also)
                if (s.present(a.key)) return true;
            return false;
        case Type::Group: {
            auto it = s.item.lists.find(n.list);
            return it != s.item.lists.end() && !it->second.empty();
        }
        case Type::If:
        case Type::Opt:
        case Type::Chain:
        case Type::Length:
            for (const auto& c : n.inner.lines)
                if (content(c, s)) return true;
            return false;
        default: return false;
    }
}

struct SeqOut {
    const Pack& p;
    std::string data;
    bool msb;
    std::uint64_t cur = 0;
    std::vector<std::vector<bool>> presence;  // by SeqPresence index: the bits last computed
    struct Whole {
        std::uint64_t at;
        const SeqNode* node;
    };
    std::vector<Whole> wholes;  // `length ... whole` fields, written last

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
                const Scope inner(p, item, n.inner, kind);
                compute_presence(p, id, n.inner.lines, 0, inner, bits);
                if (inner.kind) compute_presence(p, id, inner.kind->lines, 0, inner, bits);
            }
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

void encode_field(SeqOut& out, const SeqNode& n, const Scope& s) {
    const Pack& p = out.p;
    // The value of the earliest bound key the item holds; when it holds none,
    // the default of the earliest key that has one (0.8 ruling 16). No key and
    // no default: zero bits.
    Value mv;
    const FieldLine* f = nullptr;
    for (const bool held : {true, false}) {
        for (std::size_t k = 0; !f && k <= n.also.size(); ++k) {
            const FieldLine& line = k == 0 ? n.field : n.also[k - 1];
            if (held && !s.item.fields.count(line.key)) continue;
            if (s.src.value(line, mv)) f = &line;
        }
        if (f) break;
    }
    if (!f) {
        out.zeros(n.len);
        return;
    }
    try {
        if (f->transform == Transform::Ascii) {
            std::string text = encode_ascii(mv, n.len / 8);
            if (f->swap) std::reverse(text.begin(), text.end());
            for (std::uint32_t k = 0; k < n.len / 8; ++k) out.put(static_cast<std::uint8_t>(text[k]), 8);
        } else {
            std::uint64_t raw = encode_bits_value(*f, mv, n.len);
            if (f->swap) raw = swap_bytes(raw, n.len);
            out.put(raw, n.len);
        }
    } catch (const std::invalid_argument& ex) {
        throw Error(ErrorKind::TransformEncode, p.format, f->locator, f->key + ": " + ex.what());
    }
}

void encode_group(SeqOut& out, const SeqNode& n, const Scope& s) {
    const Pack& p = out.p;
    auto it = s.item.lists.find(n.list);
    static const std::vector<Item> none;
    const std::vector<Item>& items = it == s.item.lists.end() ? none : it->second;
    const std::size_t count = items.size();
    switch (n.repeat) {
        case Repeat::Count:
            // An absent list writes a count of 0 (0.7 ruling 14).
            if (n.len < 64 && (static_cast<std::uint64_t>(count) >> n.len) != 0)
                throw Error(ErrorKind::TransformEncode, p.format, "",
                            "the list '" + n.list + "' has " + std::to_string(count) + " items, which does not fit the " +
                                std::to_string(n.len) + " bits of its count");
            out.put(count, n.len);
            for (const Item& item : items) encode_body(out, n.inner, item);
            return;
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

void encode_node(SeqOut& out, const std::vector<SeqNode>& lines, std::size_t index, const Scope& s,
                 const std::vector<SeqNode>* tail) {
    const Pack& p = out.p;
    const SeqNode& n = lines[index];
    switch (n.type) {
        case Type::Field: encode_field(out, n, s); return;
        case Type::Const:
        case Type::When: out.put(n.number, n.len); return;
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
            encode_lines(out, n.inner.lines, s, nullptr);
            if (!n.unit_bits) out.zeros((8 - (out.cur - start) % 8) % 8);
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
    }
}

void encode_lines(SeqOut& out, const std::vector<SeqNode>& lines, const Scope& s, const std::vector<SeqNode>* tail) {
    for (std::size_t k = 0; k < lines.size(); ++k) encode_node(out, lines, k, s, tail);
}

void encode_body(SeqOut& out, const SeqBody& body, const Item& item) {
    const Scope s(out.p, item, body, select_kind(out.p, body, item));
    encode_lines(out, body.lines, s, s.kind ? &s.kind->lines : nullptr);
    if (s.kind) encode_lines(out, s.kind->lines, s, nullptr);
}

}  // namespace

std::string encode_seq(const Pack& p, const Entity& e) {
    SeqOut out{p, std::string(), p.bit_order == BitOrder::Msb, 0,
               std::vector<std::vector<bool>>(p.seq_presences.size()), {}};
    encode_body(out, p.seq, e);
    // A message is a whole number of bytes: the last byte's remaining bits are zero.
    out.data.resize(static_cast<std::size_t>((out.cur + 7) / 8), '\0');
    for (const auto& w : out.wholes) {
        const std::int64_t stated = static_cast<std::int64_t>(out.data.size()) + w.node->plus;
        if (stated < 0 || (w.node->len < 64 && (static_cast<std::uint64_t>(stated) >> w.node->len) != 0))
            throw Error(ErrorKind::TransformEncode, p.format, "",
                        "the length " + std::to_string(stated) + " of the whole message does not fit the " +
                            std::to_string(w.node->len) + " bits of its field");
        write_bits(out.data, w.at, w.node->len, static_cast<std::uint64_t>(stated), p.bit_order == BitOrder::Msb);
    }
    return bytes_to_hex(out.data);
}

}  // namespace goat_transformers::detail
