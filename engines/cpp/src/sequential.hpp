// Sequential binary layouts (engine-spec.md, Version 0.8): a `bits` pack with
// `layout sequential` is a tree of lines read, and written, in order from a
// cursor.
#pragma once

#include <functional>
#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"

namespace goat_transformers::detail {

// One line of a pack.def or model module split into tokens (pack.cpp). Returns
// false with `err` set on an unterminated or misplaced quote.
bool tokenize_line(const std::string& line, std::vector<std::string>& out, std::string& err);

// True when the text has a `layout sequential` line.
bool is_sequential_pack(const std::string& text);

// Parse the text of a pack.def that has `layout sequential`.
Pack parse_seq_pack(const std::string& text, const std::string& source);

// Every line of a sequential pack that names a model key or a list, in file
// order: each `field` and `also` binding, each `default`, each `group` and
// each `requires` key. A callback that is empty is skipped.
struct SeqVisitor {
    std::function<void(FieldLine&)> field;
    std::function<void(DefaultLine&)> default_line;
    std::function<void(SeqNode&)> group;
    std::function<void(std::string&)> requires_key;
    std::function<void(SeqKind&)> kind;          // v0.20: every kind, message and item kinds
    std::function<void(SeqNode&)> switch_node;   // v0.20: every `switch`
};
void seq_visit(SeqBody& body, const SeqVisitor& v);

// The model keys of a body, first appearance order: a list is `<list>[]` and
// an item key `<list>[].<key>`.
void seq_model_keys(const SeqBody& body, const std::string& prefix,
                    const std::function<void(const std::string&)>& add);

// Every `case` and `else` of the pack by id (0.20), for encode; the plan keeps it (0.25).
std::vector<const SeqCase*> seq_cases_by_id(const Pack& p);

Entity decode_seq(const Pack& p, const std::string& bytes);
std::string encode_seq(const Pack& p, const Entity& e);

}  // namespace goat_transformers::detail
