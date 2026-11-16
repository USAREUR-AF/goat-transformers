#!/bin/sh
# Build the C ABI library (shared and static) and test it.
#
#   1. the Rust unit tests of the library (what C cannot reach: a panic)
#   2. the header, compiled alone as C99 and as C++17 with warnings as errors
#   3. the symbols the library exports against the functions the header declares
#   4. test/api.c, test/threads.c and test/vectors.c against the shared
#      library and against the static library
#   5. the same three under AddressSanitizer and UndefinedBehaviorSanitizer,
#      with leak detection, and test/threads.c under ThreadSanitizer
#
# The sanitizers instrument the C side: the test programs and every
# allocation and release that crosses the boundary. The library itself is
# built as it ships.
#
# Leak detection: LeakSanitizer where the compiler has it (Linux). On macOS,
# where it does not, `leaks --atExit` checks each program instead.
#
# GT_SANITIZE=0 skips step 5. CC and CXX choose the compilers.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
cd "$here"

: "${CC:=cc}"
: "${CXX:=c++}"
: "${GT_SANITIZE:=1}"
tests="api threads vectors"
warnings="-Wall -Wextra -Wpedantic -Werror"
cflags="-std=c99 $warnings -O1 -g -I$here"
lib="$here/target/release"
out="$here/build"
mkdir -p "$out"

echo "== Rust unit tests"
cargo test --release --quiet
cargo build --release

case "$(uname -s)" in
Darwin)
    shared="$lib/libgoat_transformers_c.dylib"
    # what a static Rust std needs from the system
    syslibs="-lc -lm -liconv"
    ;;
*)
    shared="$lib/libgoat_transformers_c.so"
    syslibs="-lgcc_s -lutil -lrt -lpthread -lm -ldl -lc"
    ;;
esac
static="$lib/libgoat_transformers_c.a"
test -f "$shared"
test -f "$static"

echo "== header as C99 and as C++17"
$CC -std=c99 $warnings -I"$here" -fsyntax-only test/header.c
$CXX -std=c++17 -x c++ $warnings -I"$here" -fsyntax-only test/header.c

echo "== exported symbols against the header"
# every `gt_` function the header declares, and every `gt_` symbol the shared
# library defines: the two lists must be the same
sed -n 's/^[a-z].*[ *]\(gt_[a-z_]*\)(.*/\1/p' goat_transformers.h | sort > "$out/declared.txt"
nm -g "$shared" | sed -n 's/^[0-9a-f]* T _\{0,1\}\(gt_[a-z_]*\)$/\1/p' | sort > "$out/exported.txt"
test -s "$out/declared.txt"
if ! diff "$out/declared.txt" "$out/exported.txt"; then
    echo "the header (<) and the library (>) do not name the same functions" >&2
    exit 1
fi
echo "$(wc -l < "$out/declared.txt" | tr -d ' ') functions declared and exported"

echo "== shared library: $shared"
for t in $tests; do
    $CC $cflags "test/$t.c" -o "$out/$t-shared" -L"$lib" -lgoat_transformers_c -lpthread -Wl,-rpath,"$lib"
    "$out/$t-shared" "$root"
done

echo "== static library: $static"
for t in $tests; do
    $CC $cflags "test/$t.c" "$static" $syslibs -o "$out/$t-static"
    "$out/$t-static" "$root"
done

if [ "$GT_SANITIZE" = 0 ]; then
    echo "bindings/c: ok (shared and static; sanitizers skipped)"
    exit 0
fi

# Can this compiler build a program with these flags? Nothing is run: a
# sanitizer that refuses to start aborts, and an abort is slow to report on
# some systems.
can_build() {
    printf 'int main(void) { return 0; }\n' > "$out/probe.c"
    $CC "$@" "$out/probe.c" -o "$out/probe" 2>/dev/null
}

echo "== AddressSanitizer and UndefinedBehaviorSanitizer"
sanitize="-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer"
if ! can_build $sanitize; then
    echo "$CC cannot build with $sanitize" >&2
    exit 1
fi
# A compiler that has LeakSanitizer on its own has it inside AddressSanitizer.
if can_build -fsanitize=leak; then
    leak_check=LeakSanitizer
    export ASAN_OPTIONS=detect_leaks=1
elif command -v leaks >/dev/null 2>&1; then
    leak_check=leaks
else
    leak_check=none
fi
for t in $tests; do
    $CC $cflags $sanitize "test/$t.c" "$static" $syslibs -o "$out/$t-asan"
    "$out/$t-asan" "$root"
done

case "$leak_check" in
LeakSanitizer) echo "leak detection: LeakSanitizer, in the runs above" ;;
leaks)
    echo "== leak detection: leaks --atExit (this compiler has no LeakSanitizer)"
    for t in $tests; do
        # leaks exits non-zero when the program leaked or failed
        if ! MallocStackLogging=1 leaks --atExit -- "$out/$t-static" "$root" > "$out/$t-leaks.txt" 2>&1; then
            cat "$out/$t-leaks.txt" >&2
            exit 1
        fi
        grep ' leaks for ' "$out/$t-leaks.txt"
    done
    ;;
none) echo "leak detection: not run (no LeakSanitizer and no leaks tool)" ;;
esac

echo "== ThreadSanitizer"
if can_build -fsanitize=thread; then
    $CC $cflags -fsanitize=thread "test/threads.c" "$static" $syslibs -o "$out/threads-tsan"
    TSAN_OPTIONS=halt_on_error=1 "$out/threads-tsan" "$root"
    thread_check="ThreadSanitizer"
else
    echo "not run: $CC cannot build with -fsanitize=thread"
    thread_check="no ThreadSanitizer"
fi

echo "bindings/c: ok (shared and static; AddressSanitizer, UndefinedBehaviorSanitizer, leak detection: $leak_check; $thread_check)"
