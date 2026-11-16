#include "json.hpp"

#include "util.hpp"

namespace goat_transformers::json {

const Value* Value::find(const std::string& key) const {
    if (kind != Kind::Object) return nullptr;
    for (std::size_t k = 0; k < keys.size(); ++k)
        if (keys[k] == key) return &items[k];
    return nullptr;
}

namespace {

constexpr int kMaxDepth = 256;

class Parser {
public:
    explicit Parser(const std::string& s) : s_(s) {}

    Value document() {
        Value v = value(0);
        ws();
        if (i_ != s_.size()) fail("trailing content after JSON value");
        return v;
    }

private:
    const std::string& s_;
    std::size_t i_ = 0;

    [[noreturn]] void fail(const std::string& m) const {
        throw ParseError("offset " + std::to_string(i_) + ": " + m);
    }
    void ws() {
        while (i_ < s_.size() && (s_[i_] == ' ' || s_[i_] == '\t' || s_[i_] == '\n' || s_[i_] == '\r'))
            ++i_;
    }
    void expect(char c) {
        if (i_ >= s_.size() || s_[i_] != c) fail(std::string("expected '") + c + "'");
        ++i_;
    }
    void literal(const char* lit) {
        for (const char* p = lit; *p; ++p) {
            if (i_ >= s_.size() || s_[i_] != *p) fail(std::string("invalid literal, expected ") + lit);
            ++i_;
        }
    }

    Value value(int depth) {
        if (depth > kMaxDepth) fail("nesting too deep");
        ws();
        if (i_ >= s_.size()) fail("unexpected end of input");
        Value v;
        char c = s_[i_];
        if (c == '{') {
            v.kind = Value::Kind::Object;
            ++i_;
            ws();
            if (i_ < s_.size() && s_[i_] == '}') {
                ++i_;
                return v;
            }
            for (;;) {
                ws();
                if (i_ >= s_.size() || s_[i_] != '"') fail("expected member name");
                ++i_;
                v.keys.push_back(string_body());
                ws();
                expect(':');
                v.items.push_back(value(depth + 1));
                ws();
                if (i_ < s_.size() && s_[i_] == ',') {
                    ++i_;
                    continue;
                }
                expect('}');
                break;
            }
        } else if (c == '[') {
            v.kind = Value::Kind::Array;
            ++i_;
            ws();
            if (i_ < s_.size() && s_[i_] == ']') {
                ++i_;
                return v;
            }
            for (;;) {
                v.items.push_back(value(depth + 1));
                ws();
                if (i_ < s_.size() && s_[i_] == ',') {
                    ++i_;
                    continue;
                }
                expect(']');
                break;
            }
        } else if (c == '"') {
            ++i_;
            v.kind = Value::Kind::String;
            v.text = string_body();
        } else if (c == 't') {
            literal("true");
            v.kind = Value::Kind::Bool;
            v.b = true;
        } else if (c == 'f') {
            literal("false");
            v.kind = Value::Kind::Bool;
        } else if (c == 'n') {
            literal("null");
        } else if (c == '-' || (c >= '0' && c <= '9')) {
            v.kind = Value::Kind::Number;
            v.text = number();
        } else {
            fail(std::string("unexpected character '") + c + "'");
        }
        return v;
    }

    bool digit() const { return i_ < s_.size() && s_[i_] >= '0' && s_[i_] <= '9'; }

    std::string number() {
        std::size_t st = i_;
        if (s_[i_] == '-') ++i_;
        if (i_ < s_.size() && s_[i_] == '0') {
            ++i_;
        } else if (digit()) {
            while (digit()) ++i_;
        } else {
            fail("invalid number");
        }
        if (i_ < s_.size() && s_[i_] == '.') {
            ++i_;
            if (!digit()) fail("invalid number fraction");
            while (digit()) ++i_;
        }
        if (i_ < s_.size() && (s_[i_] == 'e' || s_[i_] == 'E')) {
            ++i_;
            if (i_ < s_.size() && (s_[i_] == '+' || s_[i_] == '-')) ++i_;
            if (!digit()) fail("invalid number exponent");
            while (digit()) ++i_;
        }
        return s_.substr(st, i_ - st);
    }

    unsigned hex4() {
        if (i_ + 4 > s_.size()) fail("truncated \\u escape");
        unsigned v = 0;
        for (int k = 0; k < 4; ++k) {
            char c = s_[i_++];
            v <<= 4;
            if (c >= '0' && c <= '9') v |= static_cast<unsigned>(c - '0');
            else if (c >= 'a' && c <= 'f') v |= static_cast<unsigned>(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') v |= static_cast<unsigned>(c - 'A' + 10);
            else fail("invalid \\u escape");
        }
        return v;
    }

    // Called after the opening quote.
    std::string string_body() {
        std::string out;
        for (;;) {
            if (i_ >= s_.size()) fail("unterminated string");
            char c = s_[i_++];
            if (c == '"') break;
            if (static_cast<unsigned char>(c) < 0x20) fail("control character in string");
            if (c != '\\') {
                out += c;
                continue;
            }
            if (i_ >= s_.size()) fail("unterminated escape");
            char e = s_[i_++];
            switch (e) {
                case '"': out += '"'; break;
                case '\\': out += '\\'; break;
                case '/': out += '/'; break;
                case 'b': out += '\b'; break;
                case 'f': out += '\f'; break;
                case 'n': out += '\n'; break;
                case 'r': out += '\r'; break;
                case 't': out += '\t'; break;
                case 'u': {
                    std::uint32_t cp = hex4();
                    if (cp >= 0xD800 && cp <= 0xDBFF) {
                        if (i_ + 2 > s_.size() || s_[i_] != '\\' || s_[i_ + 1] != 'u')
                            fail("unpaired surrogate");
                        i_ += 2;
                        std::uint32_t lo = hex4();
                        if (lo < 0xDC00 || lo > 0xDFFF) fail("invalid low surrogate");
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                        fail("unpaired surrogate");
                    }
                    detail::append_utf8(out, cp);
                    break;
                }
                default: fail("invalid escape");
            }
        }
        return out;
    }
};

// `lexemes` writes each number as its source lexeme, not in canonical form.
void write_to(std::string& out, const Value& v, bool lexemes = false) {
    switch (v.kind) {
        case Value::Kind::Null: out += "null"; break;
        case Value::Kind::Bool: out += v.b ? "true" : "false"; break;
        case Value::Kind::Number: out += lexemes ? v.text : canonical_number(v.text); break;
        case Value::Kind::String: out += quote(v.text); break;
        case Value::Kind::Array:
            out += '[';
            for (std::size_t k = 0; k < v.items.size(); ++k) {
                if (k) out += ',';
                write_to(out, v.items[k], lexemes);
            }
            out += ']';
            break;
        case Value::Kind::Object:
            out += '{';
            for (std::size_t k = 0; k < v.items.size(); ++k) {
                if (k) out += ',';
                out += quote(v.keys[k]);
                out += ':';
                write_to(out, v.items[k], lexemes);
            }
            out += '}';
            break;
    }
}

}  // namespace

Value parse(const std::string& src) { return Parser(src).document(); }

std::string quote(const std::string& s) {
    static const char* hex = "0123456789abcdef";
    std::string out;
    out.reserve(s.size() + 2);
    out += '"';
    for (char c : s) {
        unsigned char u = static_cast<unsigned char>(c);
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (u < 0x20) {
                    out += "\\u00";
                    out += hex[u >> 4];
                    out += hex[u & 0xF];
                } else {
                    out += c;
                }
        }
    }
    out += '"';
    return out;
}

std::string canonical_number(const std::string& lexeme) {
    if (lexeme.find_first_of(".eE") == std::string::npos) return lexeme;  // integer: exact
    double d = 0;
    if (!detail::parse_double(lexeme, d)) return lexeme;
    return detail::format_double(d);
}

std::string write(const Value& v) {
    std::string out;
    write_to(out, v);
    return out;
}

std::string write_as_written(const Value& v) {
    std::string out;
    write_to(out, v, true);
    return out;
}

}  // namespace goat_transformers::json
