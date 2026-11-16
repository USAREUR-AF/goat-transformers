#!/bin/sh
# Build the C ABI library (shared and static), compile test/test.c against
# each with cc, and run both.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
cd "$here"

cargo build --release

lib="$here/target/release"
out="$here/build"
mkdir -p "$out"
: "${CC:=cc}"
cflags="-std=c99 -Wall -Wextra -Werror -O1 -I$here"

case "$(uname -s)" in
Darwin)
    shared="$lib/libgoat_transformers_c.dylib"
    # what a static Rust std needs from the system
    syslibs="-lSystem -lc -lm -liconv"
    ;;
*)
    shared="$lib/libgoat_transformers_c.so"
    syslibs="-lgcc_s -lutil -lrt -lpthread -lm -ldl -lc"
    ;;
esac
static="$lib/libgoat_transformers_c.a"
test -f "$shared"
test -f "$static"

echo "== shared library: $shared"
$CC $cflags test/test.c -o "$out/test-shared" -L"$lib" -lgoat_transformers_c -Wl,-rpath,"$lib"
"$out/test-shared" "$root"

echo "== static library: $static"
$CC $cflags test/test.c "$static" $syslibs -o "$out/test-static"
"$out/test-static" "$root"

echo "bindings/c: ok (shared and static)"
