#!/usr/bin/env bash
# The benchmark of spec Version 0.25 (ruling 2) for the Zig engine.
#
#   engines/zig/bench.sh [<set.json>] [--packs <dir>] [--models <dir>]
#
# Run from the repository root. Builds zig-out/bin/gt-bench-zig (ReleaseFast;
# the build's own output goes to standard error), then runs it in the current
# directory: by default it reads bench/set.json, packs and model. Standard
# output holds the result lines of ruling 2c and nothing else; a vector whose
# output differs from its `expect` fails the run (exit 1).
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
(cd "$here" && zig build bench) 1>&2 || exit 2
exec "$here/zig-out/bin/gt-bench-zig" "$@"
