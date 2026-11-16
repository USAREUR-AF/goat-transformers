// Minimal JSON reader/writer (RFC 8259 subset sufficient for GeoJSON and vectors).
#pragma once

#include <stdexcept>
#include <string>
#include <vector>

namespace goat_transformers::json {

struct ParseError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

struct Value {
    enum class Kind { Null, Bool, Number, String, Array, Object };
    Kind kind = Kind::Null;
    bool b = false;
    std::string text;               // Number: source lexeme; String: decoded contents
    std::vector<Value> items;       // Array elements, or Object member values
    std::vector<std::string> keys;  // Object member names, parallel to items

    bool is(Kind k) const { return kind == k; }
    const Value* find(const std::string& key) const;  // first member with that name
};

Value parse(const std::string& src);        // throws ParseError
std::string quote(const std::string& s);    // JSON string literal
std::string canonical_number(const std::string& lexeme);
std::string write(const Value& v);          // compact, member order preserved
// The same, with every number as its source lexeme: a value as it was written.
std::string write_as_written(const Value& v);

}  // namespace goat_transformers::json
