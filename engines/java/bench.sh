#!/usr/bin/env bash
# The benchmark of spec 0.25 (ruling 2) for the Java engine. From the repository root:
#
#   engines/java/bench.sh [SET]        (default bench/set.json)
#
# It compiles goat.transformers.Bench against the engine classes of build/main (running ./build.sh --no-test
# first when they are missing), then runs it. Standard output is the result lines of ruling 2c and nothing else;
# what the build prints goes to standard error. Exits 1 when a vector's output differs from its expect.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -d "$here/build/main/goat/transformers" ]; then
  "$here/build.sh" --no-test >&2
fi
out="$here/build/bench"
rm -rf "$out"
mkdir -p "$out"
javac --release 17 -Xlint:all -Werror -cp "$here/build/main" -d "$out" "$here/src/bench/java/goat/transformers/Bench.java" >&2
exec java -cp "$here/build/main:$out" goat.transformers.Bench "$@"
