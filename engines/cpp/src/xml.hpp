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

struct Node {
    std::string name;
    std::vector<std::pair<std::string, std::string>> attrs;  // document order
    bool has_text = false;  // true only when the element carries non-whitespace text
    std::string text;
    std::vector<Node> children;
};

Node parse(const std::string& src);  // throws ParseError
// Canonical form: no prolog, attributes as stored, one space between them,
// self-closing empty elements, text before child elements.
std::string write(const Node& root);

}  // namespace goat_transformers::xml
