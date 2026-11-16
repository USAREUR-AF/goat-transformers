// Derived keys (engine-spec.md, Version 0.6): the `derive` lines of a model
// module and the fixed function table they may name.
#pragma once

#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"

namespace goat_transformers::detail {

// Parse a model module with `core` as loaded (null when it is not loaded): a
// `derive` line that names a key of `core` is checked against it before
// `missing-distribution` (0.6 ruling 9).
Module parse_model_with_core(const std::string& text, const std::string& origin, const Module* core);

// Parse one `derive` line from its tokens (`derive` itself included). Checks the
// function name, its parameter and the argument count. Throws bad-directive;
// `where` names the file and line.
DeriveLine parse_derive(const std::vector<std::string>& tokens, const std::string& where);

// Check the keys and types of every `derive` line of `m` (bad-directive), and
// settle integer arithmetic for `offset`. A key is one of `core` or of `m`.
// With `core` null and `m` not the core module, a line that names a core key
// cannot be settled and is left for the call that has `core`, unless
// `require_core` is set, when the key is undeclared.
void check_derives(Module& m, const Module* core, bool require_core);

// Apply one line: when the target is absent and every argument is present, set
// the target. Returns true when it set the target. A result that is not finite
// leaves the target absent.
bool apply_derive(const DeriveLine& d, Entity& e);

}  // namespace goat_transformers::detail
