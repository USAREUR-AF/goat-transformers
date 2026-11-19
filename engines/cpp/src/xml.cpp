#include "xml.hpp"

#include <cstring>

#include "util.hpp"

namespace goat_transformers::xml {

namespace {

// Elements nested deeper than this are malformed (0.8 ruling 35): the root
// element is level 1, and exactly 64 levels parse.
constexpr int kMaxDepth = 64;

bool is_ws(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }

class Parser {
public:
    explicit Parser(const std::string& s) : s_(s) {}

    Node document() {
        if (s_.compare(0, 3, "\xEF\xBB\xBF") == 0) i_ = 3;  // UTF-8 BOM
        skip_misc();
        if (i_ >= s_.size() || s_[i_] != '<') fail("no root element");
        Node root = element(1);
        // Only whitespace, comments and processing instructions follow the root.
        skip_misc();
        if (i_ != s_.size()) fail("content after the root element");
        return root;
    }

private:
    const std::string& s_;
    std::size_t i_ = 0;

    [[noreturn]] void fail(const std::string& m) const {
        throw ParseError("offset " + std::to_string(i_) + ": " + m);
    }
    bool starts(const char* p) const { return s_.compare(i_, std::strlen(p), p) == 0; }
    void skip_ws() {
        while (i_ < s_.size() && is_ws(s_[i_])) ++i_;
    }
    void skip_past(const char* term, const char* what) {
        std::size_t e = s_.find(term, i_);
        if (e == std::string::npos) fail(std::string("unterminated ") + what);
        i_ = e + std::strlen(term);
    }
    // Whitespace, comments and processing instructions. A document type
    // declaration is refused wherever it stands (0.8 ruling 40): `element`
    // fails on any other `<!`.
    void skip_misc() {
        for (;;) {
            skip_ws();
            if (starts("<?")) skip_past("?>", "processing instruction");
            else if (starts("<!--")) skip_past("-->", "comment");
            else return;
        }
    }
    // The characters XML 1.0 allows (production 2, Char).
    static bool xml_char(std::uint32_t cp) {
        return cp == 0x9 || cp == 0xA || cp == 0xD || (cp >= 0x20 && cp <= 0xD7FF) || (cp >= 0xE000 && cp <= 0xFFFD) ||
               (cp >= 0x10000 && cp <= 0x10FFFF);
    }
    std::string name() {
        std::size_t st = i_;
        while (i_ < s_.size() && !is_ws(s_[i_]) && std::strchr("/>=<\"'", s_[i_]) == nullptr) ++i_;
        if (i_ == st) fail("expected a name");
        return s_.substr(st, i_ - st);
    }

    std::string decode(const std::string& raw) {
        std::string out;
        out.reserve(raw.size());
        for (std::size_t k = 0; k < raw.size(); ++k) {
            if (raw[k] != '&') {
                out += raw[k];
                continue;
            }
            std::size_t semi = raw.find(';', k);
            if (semi == std::string::npos) fail("unterminated entity reference");
            std::string ent = raw.substr(k + 1, semi - k - 1);
            if (ent == "lt") out += '<';
            else if (ent == "gt") out += '>';
            else if (ent == "amp") out += '&';
            else if (ent == "quot") out += '"';
            else if (ent == "apos") out += '\'';
            else if (ent.size() > 1 && ent[0] == '#') {
                bool hex = ent[1] == 'x';  // XML 1.0: a lower-case x only
                std::size_t p = hex ? 2 : 1;
                if (p >= ent.size()) fail("empty character reference");
                std::uint32_t cp = 0;
                for (; p < ent.size(); ++p) {
                    char c = ent[p];
                    unsigned dv;
                    if (c >= '0' && c <= '9') dv = static_cast<unsigned>(c - '0');
                    else if (hex && c >= 'a' && c <= 'f') dv = static_cast<unsigned>(c - 'a' + 10);
                    else if (hex && c >= 'A' && c <= 'F') dv = static_cast<unsigned>(c - 'A' + 10);
                    else fail("invalid character reference");
                    cp = cp * (hex ? 16u : 10u) + dv;
                    if (cp > 0x10FFFF) fail("character reference out of range");
                }
                if (!xml_char(cp)) fail("character reference to a character XML 1.0 does not allow");
                detail::append_utf8(out, cp);
            } else {
                fail("unknown entity &" + ent + ";");
            }
            k = semi;
        }
        return out;
    }

    // `depth` is the level of the element: 1 for the root.
    Node element(int depth) {
        if (depth > kMaxDepth) fail("nesting deeper than " + std::to_string(kMaxDepth) + " levels");
        ++i_;  // '<'
        // `<!DOCTYPE`, another declaration, or a stray `<?` or `<!`: not an element.
        if (i_ < s_.size() && (s_[i_] == '!' || s_[i_] == '?'))
            fail(starts("!DOCTYPE") ? "a document type declaration is not accepted" : "expected an element name");
        Node n;
        n.name = name();
        for (;;) {
            skip_ws();
            if (i_ >= s_.size()) fail("unterminated start tag <" + n.name);
            if (s_[i_] == '/') {
                if (!starts("/>")) fail("expected '/>'");
                i_ += 2;
                return n;
            }
            if (s_[i_] == '>') {
                ++i_;
                break;
            }
            std::string an = name();
            skip_ws();
            if (i_ >= s_.size() || s_[i_] != '=') fail("expected '=' after attribute " + an);
            ++i_;
            skip_ws();
            if (i_ >= s_.size() || (s_[i_] != '"' && s_[i_] != '\'')) fail("expected quoted value");
            char q = s_[i_++];
            std::size_t e = s_.find(q, i_);
            if (e == std::string::npos) fail("unterminated attribute value");
            std::string raw = s_.substr(i_, e - i_);
            if (raw.find('<') != std::string::npos) fail("'<' in attribute value");
            // 0.11 ruling 1i: a tab or line feed written literally is read as a
            // space; one written as a reference is kept (decode comes after).
            for (char& c : raw)
                if (c == '\t' || c == '\n') c = ' ';
            i_ = e + 1;
            for (const auto& a : n.attrs)
                if (a.first == an) fail("duplicate attribute " + an);
            n.attrs.emplace_back(an, decode(raw));
        }
        std::string text;
        for (;;) {
            if (i_ >= s_.size()) fail("unterminated element <" + n.name + ">");
            if (starts("</")) {
                i_ += 2;
                std::string cn = name();
                if (cn != n.name) fail("mismatched end tag </" + cn + "> for <" + n.name + ">");
                skip_ws();
                if (i_ >= s_.size() || s_[i_] != '>') fail("expected '>'");
                ++i_;
                break;
            }
            if (starts("<!--")) {
                skip_past("-->", "comment");
            } else if (starts("<![CDATA[")) {
                i_ += 9;
                std::size_t e = s_.find("]]>", i_);
                if (e == std::string::npos) fail("unterminated CDATA");
                text += s_.substr(i_, e - i_);
                i_ = e + 3;
            } else if (starts("<?")) {
                skip_past("?>", "processing instruction");
            } else if (s_[i_] == '<') {
                n.children.push_back(element(depth + 1));
            } else {
                std::size_t e = s_.find('<', i_);
                if (e == std::string::npos) fail("unterminated element <" + n.name + ">");
                text += decode(s_.substr(i_, e - i_));
                i_ = e;
            }
        }
        // 0.11 ruling 1m: all character data directly inside the element, kept
        // exactly; whitespace is text. No character data is no text.
        if (!text.empty()) {
            n.has_text = true;
            n.text = std::move(text);
        }
        return n;
    }
};

void escape(std::string& out, const std::string& s, bool attr) {
    for (char c : s) {
        switch (c) {
            case '&': out += "&amp;"; break;
            case '<': out += "&lt;"; break;
            case '>': out += "&gt;"; break;
            case '"':
                if (attr) out += "&quot;";
                else out += c;
                break;
            case '\n':
                if (attr) out += "&#10;";
                else out += c;
                break;
            case '\t':
                if (attr) out += "&#9;";
                else out += c;
                break;
            case '\r': out += "&#13;"; break;
            default: out += c;
        }
    }
}

void write_to(std::string& out, const Node& n) {
    out += '<';
    out += n.name;
    for (const auto& a : n.attrs) {
        out += ' ';
        out += a.first;
        out += "=\"";
        escape(out, a.second, true);
        out += '"';
    }
    // 0.11 ruling 1e: the empty text writes the element with no content.
    if ((!n.has_text || n.text.empty()) && n.children.empty()) {
        out += "/>";
        return;
    }
    out += '>';
    if (n.has_text) escape(out, n.text, false);
    for (const auto& c : n.children) write_to(out, c);
    out += "</";
    out += n.name;
    out += '>';
}

}  // namespace

Node parse(const std::string& src) {
    // 0.11 ruling 1h: before anything else is read, a carriage return followed
    // by a line feed, and one that stands alone, is one line feed.
    if (src.find('\r') == std::string::npos) return Parser(src).document();
    std::string norm;
    norm.reserve(src.size());
    for (std::size_t k = 0; k < src.size(); ++k) {
        if (src[k] != '\r') {
            norm += src[k];
            continue;
        }
        norm += '\n';
        if (k + 1 < src.size() && src[k + 1] == '\n') ++k;
    }
    return Parser(norm).document();
}

namespace {
// 0.11 ruling 1d: a character XML 1.0 cannot hold.
bool writable(const std::string& s) {
    for (std::size_t k = 0; k < s.size(); ++k) {
        const unsigned char c = static_cast<unsigned char>(s[k]);
        if (c < 0x20 && c != '\t' && c != '\n' && c != '\r') return false;
        // U+FFFE and U+FFFF are EF BF BE and EF BF BF in UTF-8.
        if (c == 0xEF && k + 2 < s.size() && static_cast<unsigned char>(s[k + 1]) == 0xBF &&
            (static_cast<unsigned char>(s[k + 2]) == 0xBE || static_cast<unsigned char>(s[k + 2]) == 0xBF))
            return false;
    }
    return true;
}
void check_writable(const Node& n) {
    for (const auto& a : n.attrs)
        if (!writable(a.second)) throw WriteError("the attribute " + a.first + " holds a character XML 1.0 cannot hold");
    if (n.has_text && !writable(n.text))
        throw WriteError("the text of <" + n.name + "> holds a character XML 1.0 cannot hold");
    for (const auto& c : n.children) check_writable(c);
}
}  // namespace

std::string write(const Node& root) {
    check_writable(root);
    std::string out;
    write_to(out, root);
    return out;
}

}  // namespace goat_transformers::xml
