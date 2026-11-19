// Minimal XML reader and canonical writer: elements, attributes, text, CDATA,
// comments, processing instructions and a DOCTYPE are understood; namespaces are
// treated as part of the name.
#pragma once

#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace goat_transformers::xml {

struct ParseError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// A string to be written holds a character XML 1.0 cannot hold (0.11 ruling 1d).
struct WriteError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

struct Node {
    std::string name;
    std::vector<std::pair<std::string, std::string>> attrs;  // document order
    bool has_text = false;  // the element holds character data (0.11 ruling 1m: whitespace is text)
    std::string text;
    std::vector<Node> children;
};

Node parse(const std::string& src);  // throws ParseError
// Canonical form (0.11 ruling 1): no prolog, attributes as stored, one space between them,
// self-closing empty elements, text before child elements.
// Throws WriteError for a character XML 1.0 cannot hold (0.11 ruling 1d).
std::string write(const Node& root);

}  // namespace goat_transformers::xml
