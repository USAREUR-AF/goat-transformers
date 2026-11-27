// The line checks of a pack or a module file (engine-spec.md, Version 0.11,
// ruling 5b). Every line is checked in the order of 5b before any other check
// of the file runs, so the first line that fails a line check gives the error
// of the load, whatever a later line holds.
#pragma once

#include <string>

#include "goat_transformers/engine.hpp"

namespace goat_transformers::detail {

// The kind of a tokenizer failure: unterminated-quote for a value that begins
// with `"` and has no closing `"` on its line, bad-directive otherwise.
ErrorKind tokenize_kind(const std::string& err);

// A pack: for each line, unterminated-quote; unknown-directive; the number of
// arguments; missing-wire; a repeated header line; the `wire` and
// `distribution` values; the transform's name and parameters; the locator
// form; the field options; the values of an `absent` option. Then
// missing-format, missing-version and missing-wire.
// Does a `when` line hold the word `at` (0.33 ruling 27)? The third token on; the
// token after the first `as` is a key and not that word (0.52 rulings 4 and 14).
bool when_holds_at(const std::vector<std::string>& t);
// v0.64 ruling 23: `const <locator> part... <text>`, a const of three arguments.
bool is_const_part(const std::vector<std::string>& t);
void check_pack_lines(const std::string& text, const std::string& source);

// A module: for each line, unterminated-quote; unknown-directive; the number
// of arguments; a repeated header line; the `distribution` value. The parse
// then checks every other cause of a module line, then missing-module and
// missing-version (parse_model_impl).
void check_module_lines(const std::string& text, const std::string& origin);

}  // namespace goat_transformers::detail
