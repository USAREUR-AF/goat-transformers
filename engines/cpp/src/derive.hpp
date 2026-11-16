// Derived keys (engine-spec.md, Version 0.6): the `derive` lines of a model
// module and the fixed function table they may name.
#pragma once

#include <functional>
#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"

namespace goat_transformers::detail {

// The module of a name among the modules loaded so far; null when it is not loaded.
using ModuleLookup = std::function<const Module*(const std::string&)>;

// Parse a model module and leave the keys and types of its `derive` lines
// unchecked. The checks of a module run in this order (0.8 ruling 29):
// `missing-distribution`, `missing-source`, `distribution-refused`,
// `unknown-module`, `distribution-violation`, the `derive` checks,
// `duplicate-module`. The parse makes the first two, and before them checks
// each `derive` line as a line (`parse_derive`; 0.6 ruling 9). Engine::add_model
// makes the rest, `check_derives` among them.
Module parse_model_unchecked(const std::string& text, const std::string& origin);

// Parse one `derive` line from its tokens (`derive` itself included). Checks the
// function name, its parameter and the argument count. Throws bad-directive;
// `where` names the file and line.
DeriveLine parse_derive(const std::vector<std::string>& tokens, const std::string& where);

// Check the keys and types of every `derive` line of `m` (bad-directive), and
// settle integer arithmetic for `offset`. A target is a key of `core` or of
// `m`; an argument may also be a key of a module `m` uses (0.8). A line that
// names a key of `core` while `core` is not loaded cannot be settled and is
// left for a later call, unless `require_core` is set, when the key is
// undeclared. A line that names a key of a used module that is not loaded is
// always left: that load fails with unknown-module.
void check_derives(Module& m, const ModuleLookup& loaded, bool require_core);

// Apply one line: when the target is absent and every argument is present, set
// the target. Returns true when it set the target. A result that is not finite
// leaves the target absent.
bool apply_derive(const DeriveLine& d, Entity& e);

}  // namespace goat_transformers::detail
