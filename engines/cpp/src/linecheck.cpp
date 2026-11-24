// The line checks of 0.11 ruling 5b. A pack or a module is read twice: this
// pass runs the checks of every line in the order of 5b, then the parse of
// pack.cpp or sequential.cpp runs every other check. A check the parse makes
// as it reads a line is therefore made after every line has passed these.
#include "linecheck.hpp"

#include <set>
#include <string>
#include <vector>

#include "codecs.hpp"
#include "sequential.hpp"
#include "transforms.hpp"
#include "util.hpp"
#include "wires.hpp"

namespace goat_transformers::detail {

ErrorKind tokenize_kind(const std::string& err) {
    return err.compare(0, 12, "unterminated") == 0 ? ErrorKind::UnterminatedQuote : ErrorKind::BadDirective;
}

namespace {

const std::set<std::string>& pack_directives() {
    static const std::set<std::string> s{"format", "version", "distribution", "source", "uses",   "wire",
                                         "root",   "field",   "when",         "const",  "kind",   "requires",
                                         "default", "map",    "typemap",      "group",  "end",    "word_bytes",
                                         "bit_order", "layout", "also",       "pad",    "align",  "presence",
                                         "if",     "opt",     "chain",        "fx",     "length", "delimiter",
                                         "start",  "checksum",
                                         // v0.13, the tlv wire
                                         "tag",    "key",
                                         // v0.14, six-bit armor of the bits wire. Its value, its
                                         // wire, `bit_order msb`, a second line and its place before
                                         // the first `kind` are checked after the file is read.
                                         "armor",
                                         // v0.18, the xml wire. Its wire and its path are checked
                                         // after the file is read.
                                         "element",
                                         // v0.19, ASN.1 unaligned PER (ruling 21: directives on
                                         // every wire). Whether they fit their pack is checked
                                         // after the file is read (rulings 9 and 21).
                                         "encoding", "ext", "choice", "alt",
                                         // v0.20, sequential layouts. Their argument counts
                                         // are line checks (0.20 ruling 39); their structure
                                         // and values are checked as the pack is read.
                                         "switch", "case", "else",
                                         // v0.21, sequential layouts: `count <name> <len> [plus <n>]`,
                                         // checked as the pack is read.
                                         "count",
                                         // v0.34, `inner <format> [partial]`: where it stands and the
                                         // pack that holds it are checked after the file is read.
                                         "inner",
                                         // v0.92, `framing self`
                                         "framing",
                                         // v0.46: what it holds and its place are checked after the file.
                                         "charset"};
    return s;
}

// The lines that stand after the `wire` line (5b).
const std::set<std::string>& after_wire() {
    static const std::set<std::string> s{"root", "field", "when",  "const", "group", "end",   "word_bytes",
                                         "bit_order", "layout", "also", "pad", "align", "presence", "if",
                                         "opt",  "chain", "fx",    "length",
                                         // v0.34
                                         "inner",
                                         // v0.92 ruling 16
                                         "framing"};
    return s;
}

// The directives that take exactly one argument (5e).
const std::set<std::string>& one_argument() {
    static const std::set<std::string> s{"format",     "version",   "distribution", "source", "uses",
                                         "wire",       "root",      "kind",         "word_bytes",
                                         "bit_order",  "layout",    "pad",          "align",  "delimiter",
                                         "start",      "checksum",
                                         // v0.14 ruling 13
                                         "armor",
                                         // v0.18 ruling 25
                                         "element",
                                         // v0.19: a pack directive of one value, as `armor`
                                         "encoding",
                                         "framing",  // v0.92
                                         // v0.20 ruling 39
                                         "switch", "case",
                                         // v0.28: `tag <n>` on cbor, and the `tag` of tlv (0.13)
                                         "tag"};
    return s;
}

bool digits_only(const std::string& s) {
    return !s.empty() && s.find_first_not_of("0123456789") == std::string::npos;
}

// v0.19: the UPER locator forms (ruling 24: a locator that begins `int:`,
// `enum:`, `chars:` or `octets:`). Their numbers, their use on a `when` or
// `const` line, and their use outside a UPER pack are bad-directive checked
// after the file is read (rulings 9, 19, 24 and 26), so 5a does not refuse
// them as a line is read, in either layout.
bool uper_locator_form(const std::string& loc) {
    return loc.compare(0, 4, "int:") == 0 || loc.compare(0, 5, "enum:") == 0 || loc.compare(0, 6, "chars:") == 0 ||
           loc.compare(0, 7, "octets:") == 0;
}

struct LineChecker {
    std::string source;
    std::string format;  // for messages, once the `format` line is read
    std::size_t lineno = 0;
    std::string where() const { return source + ":" + std::to_string(lineno); }
    [[noreturn]] void fail(ErrorKind k, const std::string& what, const std::string& locator = "") const {
        throw Error(k, format, locator, where() + ": " + what);
    }
};

// 5a: the form of a locator on a `field`, `when` or `const` line. `in_group`:
// inside a group, where a geojson pack uses the json locators and `.` is the
// item. Cases earlier versions name stay for the checks after the file.
void check_locator(const LineChecker& c, Wire wire, bool sequential, bool in_group, bool is_field,
                   const std::string& loc) {
    auto bad = [&](const std::string& why) { c.fail(ErrorKind::BadLocator, why, loc); };
    Wire w = in_group && wire == Wire::GeoJson ? Wire::Json : wire;
    switch (w) {
        case Wire::Xml: {
            XmlLocator x;
            if (!parse_xml_locator(loc, x)) bad("not an xml locator");
            if (x.kind == XmlLocator::Kind::Element) bad("an xml locator of this line ends in @name or #text");
            return;
        }
        case Wire::Json: {
            if (loc == ".") return;  // the item itself; outside a group, bad-directive later
            std::vector<std::string> path;
            if (!parse_json_locator(loc, path)) bad("a json locator with an empty member name");
            return;
        }
        case Wire::GeoJson: {
            if (loc == ".") return;
            GeoLocator g;
            if (!parse_geo_locator(loc, g)) bad("not a geojson locator");
            if (!is_field && g.kind != GeoLocator::Kind::Property && g.kind != GeoLocator::Kind::Member)
                bad("a geojson 'when' or 'const' locator names a property or a member");
            return;
        }
        case Wire::Protobuf: {
            if (loc == ".") return;
            ProtobufLocator pb;
            if (!parse_protobuf_locator(loc, pb)) bad("not a protobuf locator");
            return;
        }
        case Wire::Bits: {
            // 0.19 rulings 24 and 26: any line, either layout.
            if (uper_locator_form(loc)) return;
            if (sequential) {
                // A bit length; a <word>:<pos>:<len> locator is bad-directive later.
                if (loc.find(':') != std::string::npos) return;
                if (!digits_only(loc)) bad("the locator of a sequential line is a bit length");
                std::uint64_t n = 0;
                if (parse_unsigned_text(loc, n) && n == 0) bad("a bit length of 0");
                return;
            }
            // A bit length for a locator is a line of a sequential layout: bad-directive
            // later; so is `until:<code>` (0.22).
            if (digits_only(loc) || loc.compare(0, 6, "until:") == 0) return;
            BitsLocator b;
            if (!parse_bits_locator(loc, b)) bad("not <word>:<pos>:<len> of three unsigned decimal integers");
            if (b.len == 0) bad("a bit length of 0");
            return;
        }
        case Wire::Tlv:
            // 0.13: a path and its size are checked after the file is read (bad-directive).
            return;
        case Wire::Cbor:
            // 0.28 Paths and ruling 22: `.` is a path only on a `field` in a group body.
            if (loc == ".") {
                if (!is_field || !in_group) bad("'.' is a cbor path only on a field in a group body");
                return;
            }
#if GT_WIRE_CBOR
            if (!cbor_path_valid(loc)) bad("not a cbor path of integer keys, text keys and [i] positions");
#endif
            return;
        case Wire::Text: {
#if GT_WIRE_TEXT
            TextLocator t;
            if (!parse_text_locator(loc, t))
                c.fail(ErrorKind::BadDirective, "'" + loc + "' is not a locator of wire text", loc);
#endif
            return;  // without the text wire a text pack stops at its `wire` line (0.24)
        }
    }
}

// 5a: the form of a `group` line's locator, a line check like every other
// locator (5b step 8): an empty step on xml, an empty member name on json and
// geojson, and the steps of protobuf. The forms a group locator may end in
// are not ruled and are left to the checks after the file, as is the bits
// `<word>:<pos>` and the text index.
void check_group_locator(const LineChecker& c, Wire wire, bool in_group, const std::string& loc) {
    auto bad = [&](const std::string& why) { c.fail(ErrorKind::BadLocator, why, loc); };
    auto empty_step = [&](char sep) {
        if (loc.empty()) return true;
        std::size_t st = 0;
        for (;;) {
            const std::size_t e = loc.find(sep, st);
            if (e == st || (e == std::string::npos && st == loc.size())) return true;
            if (e == std::string::npos) return false;
            st = e + 1;
        }
    };
    switch (wire) {
        case Wire::Xml:
            if (empty_step('/')) bad("an xml group locator with an empty step");
            return;
        case Wire::Json:
        case Wire::GeoJson:
            if (empty_step('.')) bad("a group locator with an empty member name");
            return;
        case Wire::Protobuf: {
            // `rest` and `last` are bad-directive, checked with the pack (0.21
            // rulings 37 and 44); any other step that is not a path stays 5a.
            if (loc == "rest" || loc == "last") return;
            ProtobufLocator pb;
            if (!parse_protobuf_locator(loc, pb)) bad("not a protobuf locator");
            return;
        }
        case Wire::Cbor:
            // 0.28 ruling 22: `group <list> .` names the top item, outside a body only.
            if (loc == ".") {
                if (in_group) bad("'.' is a cbor group path only outside a group body");
                return;
            }
#if GT_WIRE_CBOR
            if (!cbor_path_valid(loc)) bad("not a cbor path of integer keys, text keys and [i] positions");
#endif
            return;
        default: return;
    }
}

}  // namespace

bool when_holds_at(const std::vector<std::string>& t) {
    bool seen_as = false;
    for (std::size_t k = 3; k < t.size(); ++k) {
        if (t[k] == "as" && !seen_as) {
            seen_as = true;
            ++k;  // its key
        } else if (t[k] == "at") {
            return true;
        }
    }
    return false;
}

void check_pack_lines(const std::string& text, const std::string& source) {
    LineChecker c;
    c.source = source;
    const bool sequential = is_sequential_pack(text);
    bool have_format = false, have_version = false, have_wire = false, have_distribution = false;
    bool listed_before_layout = false;  // a line that `layout sequential` stands before
    Wire wire = Wire::Xml;
    int group_depth = 0;  // fixed layout: the groups open at this line
    // Fixed layout: the blocks open at this line, true for a `group`. A gate
    // block (0.17), and an `ext` or `choice` (0.19) outside a UPER pack, which
    // is refused after the file, is closed by its `end` here, not a group.
    std::vector<bool> blocks;
    std::size_t pos = 0;
    while (pos <= text.size()) {
        const std::size_t nl = text.find('\n', pos);
        const std::string line = text.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
        pos = nl == std::string::npos ? text.size() + 1 : nl + 1;
        ++c.lineno;

        // 1. unterminated-quote
        std::vector<std::string> t;
        std::string err;
        if (!tokenize_line(line, t, err)) c.fail(tokenize_kind(err), err);
        if (t.empty()) continue;
        const std::string& kw = t[0];
        const std::size_t nargs = t.size() - 1;

        // 2. unknown-directive
        if (!pack_directives().count(kw)) c.fail(ErrorKind::UnknownDirective, "directive '" + kw + "'");
        // 0.13 ruling 11: only a `key` line of one argument is the directive of
        // the tlv wire; any other is the model-module form, unknown in a pack.
        if (kw == "key" && nargs != 1)
            c.fail(ErrorKind::UnknownDirective, "'key' with " + std::to_string(nargs) +
                                                    " arguments is a line of a model module, not of a pack");

        // 3. the number of arguments
        auto count = [&](bool ok, const std::string& what) {
            if (!ok)
                c.fail(ErrorKind::BadDirective,
                       "'" + kw + "' takes " + what + ", got " + std::to_string(nargs) + " argument(s)");
        };
        if (kw == "checksum" && nargs == 2 && (t[1] == "sum16" || t[1] == "crc32")) {
            // v0.13: `checksum sum16 <tag>`, v0.27 (ruling 2): `checksum crc32 <tag>`;
            // whether the wire is tlv is checked after the file.
        } else if (one_argument().count(kw)) count(nargs == 1, "exactly one argument");
        else if (kw == "field") count(nargs >= 3, "a key, a locator and a transform");
        // v0.30: `when <loc> <values> as ...`; whether `as` is allowed, and its
        // key, are checked after the file (ruling 16).
        // v0.33: `at <n>` likewise (ruling 10).
        else if (kw == "when" && nargs >= 3 && (t[3] == "as" || t[3] == "at")) {
        } else if (kw == "when" || kw == "const" || kw == "default") count(nargs == 2, "two arguments");
        // v0.34: the word after the format is checked after the file.
        else if (kw == "inner") count(nargs == 1 || nargs == 2, "one or two arguments");
        else if (kw == "map") count(nargs == 3, "three arguments");
        else if (kw == "charset") count(nargs == 2 || nargs == 3, "two or three arguments");  // v0.46
        else if (kw == "typemap") count(nargs == 2, "two arguments");
        else if (kw == "end" || kw == "else") count(nargs == 0, "no argument");
        // v0.19 ruling 23: `ext` none, `choice` one or two, `alt` one (`encoding`
        // is in the one-argument list); their values are checked after the file.
        else if (kw == "ext") count(nargs == 0, "no argument");
        else if (kw == "choice") count(nargs == 1 || nargs == 2, "one or two arguments");
        else if (kw == "alt") count(nargs == 1, "one argument");
        else if (kw == "requires") count(nargs >= 1, "at least one argument");
        // v0.17 ruling 13: an `if` line with no argument at all is refused as
        // the line is read; its other errors are found after the file.
        else if (kw == "if") count(nargs >= 1, "at least one argument");

        // 4. missing-wire
        if (after_wire().count(kw) && !have_wire)
            c.fail(ErrorKind::MissingWire, "'" + kw + "' stands before the 'wire' line");
        if (kw == "layout" && t[1] == "sequential" && listed_before_layout)
            c.fail(ErrorKind::BadDirective, "'layout sequential' stands after a line it must stand before");
        if (after_wire().count(kw) && kw != "layout") listed_before_layout = true;

        // 5. a repeated header line
        auto once = [&](bool& seen) {
            if (seen) c.fail(ErrorKind::BadDirective, "a second '" + kw + "' line");
            seen = true;
        };
        if (kw == "format") {
            once(have_format);
            c.format = t[1];
        } else if (kw == "version") {
            once(have_version);
        } else if (kw == "distribution") {
            once(have_distribution);
            // 6. the distribution value
            if (t[1] != "public" && t[1] != "controlled")
                c.fail(ErrorKind::BadDirective, "distribution '" + t[1] + "' is not public or controlled");
        } else if (kw == "wire") {
            once(have_wire);
            // 6. the wire value
            // 0.24 ruling 1c: a wire this build lacks is refused here too.
            std::string why;
            if (!parse_wire_value(t[1], wire, why)) c.fail(ErrorKind::UnknownWire, why);
        }

        if (kw == "group") {
            // 8. the locator form
            if (!sequential && nargs >= 2) check_group_locator(c, wire, group_depth > 0, t[2]);
            if (!sequential) {
                ++group_depth;
                blocks.push_back(true);
            }
            continue;
        }
        if (kw == "ext" || kw == "choice" || kw == "if") {
            if (!sequential) blocks.push_back(false);
            continue;
        }
        if (kw == "end") {
            if (!blocks.empty()) {
                if (blocks.back() && group_depth > 0) --group_depth;
                blocks.pop_back();
            }
            continue;
        }
        if (kw == "when" || kw == "const") {
            // 8. the locator form
            check_locator(c, wire, sequential, group_depth > 0, false, t[1]);
            continue;
        }
        if (kw != "field") continue;

        // 7. the transform's name and its parameters
        FieldLine f;
        f.key = t[1];
        f.locator = t[2];
        f.line = c.lineno;
        const int tf = parse_any_transform(t[3], f, err);
        // On tlv a transform that does not parse is bad-directive, checked
        // after the file is read (0.13 ruling 8): not a line check there.
        // 0.28 rulings 25 and 34: on cbor, as on tlv, the whole transform check is after the file.
        if (wire != Wire::Tlv && wire != Wire::Cbor) {
            if (tf == -2) c.fail(ErrorKind::UnknownTransform, err + " for field '" + f.key + "'", f.locator);
            if (tf == -1) c.fail(ErrorKind::BadDirective, err + " for field '" + f.key + "'", f.locator);
        }
        // 8. the locator form
        check_locator(c, wire, sequential, group_depth > 0, true, f.locator);
        // 9. the field options
        bool swap = false, trim = false, optional = false;
        for (std::size_t k = 4; k < t.size(); ++k) {
            if (t[k] == "via") {
                if (k + 1 >= t.size() || t[k + 1].empty() || !f.via.empty())
                    c.fail(ErrorKind::BadDirective, "'via' takes one table name, once", f.locator);
                f.via = t[++k];
                continue;
            }
            // v0.22: `stop <code>`, once; its code and its transform are checked
            // with the pack.
            if (t[k] == "stop") {
                if (k + 1 >= t.size() || f.has_stop)
                    c.fail(ErrorKind::BadDirective, "'stop' takes one code, once", f.locator);
                f.has_stop = true;
                ++k;
                continue;
            }
            // v0.18: `with <other-key>`, once.
            if (t[k] == "with") {
                if (k + 1 >= t.size() || t[k + 1].empty() || !f.with.empty())
                    c.fail(ErrorKind::BadDirective, "'with' takes one key, once", f.locator);
                f.with = t[++k];
                continue;
            }
            if (t[k] == "absent") {
                if (k + 1 >= t.size() || f.has_absent)
                    c.fail(ErrorKind::BadDirective, "'absent' takes one argument, once", f.locator);
                f.has_absent = true;
                f.absent_arg = t[++k];
                continue;
            }
            bool* flag = t[k] == "swap" ? &swap : t[k] == "trim" ? &trim : t[k] == "optional" ? &optional : nullptr;
            if (!flag || *flag)
                c.fail(ErrorKind::BadDirective, "'" + t[k] + "' is not a field option, or is given twice", f.locator);
            *flag = true;
        }
        // 10. the values of an `absent` option, except on a bits field longer than 64 bits (4d)
        if (!f.has_absent) continue;
        // 0.13 ruling 14: `absent` does not fit the tlv wire, which is checked after the file.
        if (wire == Wire::Tlv) continue;
        // 0.28 ruling 10: nor the cbor wire; its values are not checked there.
        if (wire == Wire::Cbor) continue;
        // 0.19 ruling 22: `absent` on a UPER locator, whose bits depend on its
        // value, is bad-directive after the file; it has no raw value to check here.
        if (wire == Wire::Bits && uper_locator_form(f.locator)) continue;
        std::uint32_t len = 0;
        if (wire == Wire::Bits) {
            std::uint64_t n = 0;
            BitsLocator b;
            if (sequential && parse_unsigned_text(f.locator, n)) len = n > 0xFFFFFFFFull ? 0xFFFFFFFFu : static_cast<std::uint32_t>(n);
            else if (!sequential && parse_bits_locator(f.locator, b)) len = b.len;
            if (len > 64) continue;
        }
        Pack p;
        p.format = c.format;
        p.source = source;
        p.wire = wire;
        const bool coordinate = wire == Wire::GeoJson && group_depth == 0 && f.locator.compare(0, 9, "geometry.") == 0;
        resolve_absent(p, wire, f, len, coordinate);
    }
    if (!have_format) throw Error(ErrorKind::MissingFormat, "", "", source + ": the pack has no 'format' line");
    if (!have_version) throw Error(ErrorKind::MissingVersion, c.format, "", source + ": the pack has no 'version' line");
    if (!have_wire) throw Error(ErrorKind::MissingWire, c.format, "", source + ": the pack has no 'wire' line");
}

void check_module_lines(const std::string& text, const std::string& origin) {
    LineChecker c;
    c.source = origin;
    static const std::set<std::string> directives{"module", "version", "distribution", "source",
                                                  "uses",   "key",     "list",         "derive"};
    bool have_module = false, have_version = false, have_distribution = false;
    std::size_t pos = 0;
    while (pos <= text.size()) {
        const std::size_t nl = text.find('\n', pos);
        const std::string line = text.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
        pos = nl == std::string::npos ? text.size() + 1 : nl + 1;
        ++c.lineno;
        std::vector<std::string> t;
        std::string err;
        if (!tokenize_line(line, t, err)) c.fail(tokenize_kind(err), err);
        if (t.empty()) continue;
        const std::string& kw = t[0];
        const std::size_t nargs = t.size() - 1;
        if (!directives.count(kw)) c.fail(ErrorKind::UnknownDirective, "directive '" + kw + "'");
        auto count = [&](bool ok, const std::string& what) {
            if (!ok)
                c.fail(ErrorKind::BadDirective,
                       "'" + kw + "' takes " + what + ", got " + std::to_string(nargs) + " argument(s)");
        };
        if (kw == "module" || kw == "version" || kw == "distribution" || kw == "source" || kw == "uses")
            count(nargs == 1, "exactly one argument");
        else if (kw == "key") count(nargs == 3 || nargs == 4, "three or four arguments");
        else if (kw == "list") count(nargs == 1 || nargs == 2, "one or two arguments");
        auto once = [&](bool& seen) {
            if (seen) c.fail(ErrorKind::BadDirective, "a second '" + kw + "' line");
            seen = true;
        };
        if (kw == "module") {
            once(have_module);
        } else if (kw == "version") {
            once(have_version);
        } else if (kw == "distribution") {
            once(have_distribution);
            if (t[1] != "public" && t[1] != "controlled")
                c.fail(ErrorKind::BadDirective, "distribution '" + t[1] + "' is not public or controlled");
        }
    }
    // missing-module and missing-version come after the other causes of a
    // module line, which the parse checks once this pass is done (5b).
    (void)have_module;
    (void)have_version;
}

}  // namespace goat_transformers::detail
