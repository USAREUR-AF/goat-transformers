#!/bin/sh
# The benchmark of engine-spec Version 0.25 (ruling 2), from the repository root:
#   engines/erlang/bench.sh [<set.json>]        (default bench/set.json)
# Builds the engine first if ebin/ holds no module (the build's own output goes
# to standard error), then runs src/gt_bench.erl: standard output holds only
# the result lines of ruling 2c.
dir=$(dirname "$0")
if ! ls "$dir"/ebin/*.beam >/dev/null 2>&1; then
    "$dir/build.sh" >&2 || exit 1
fi
exec erl -noshell -pa "$dir/ebin" -s gt_bench main -extra "$@"
