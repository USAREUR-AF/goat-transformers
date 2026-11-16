#!/bin/sh
# Build the C library and install it under a prefix:
#
#   <prefix>/include/goat_transformers.h
#   <prefix>/lib/libgoat_transformers_c.so   (.dylib on macOS)
#   <prefix>/lib/libgoat_transformers_c.a
#   <prefix>/lib/pkgconfig/goat_transformers.pc
#
# Usage: ./install.sh [PREFIX]    (default /usr/local; DESTDIR and GT_TARGET are honored)
#
# Then: cc app.c $(pkg-config --cflags --libs goat_transformers)
# To link the static library, name the .a and add the system libraries it
# needs, which the file lists as Libs.private (pkg-config --libs --static).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
prefix="${1:-/usr/local}"
dest="${DESTDIR:-}$prefix"
version=0.8.0

cd "$here"
# GT_TARGET names a Rust target to build for; without it, the host.
if [ -n "${GT_TARGET:-}" ]; then
    cargo build --release --target "$GT_TARGET"
    lib="${CARGO_TARGET_DIR:-$here/target}/$GT_TARGET/release"
else
    cargo build --release
    lib="${CARGO_TARGET_DIR:-$here/target}/release"
fi

case "$(uname -s)" in
Darwin)
    shared=libgoat_transformers_c.dylib
    # what a static Rust std needs from the system
    syslibs="-lSystem -lc -lm -liconv"
    ;;
*)
    shared=libgoat_transformers_c.so
    syslibs="-lgcc_s -lutil -lrt -lpthread -lm -ldl -lc"
    ;;
esac

mkdir -p "$dest/include" "$dest/lib/pkgconfig"
cp goat_transformers.h "$dest/include/goat_transformers.h"
cp "$lib/$shared" "$dest/lib/$shared"
cp "$lib/libgoat_transformers_c.a" "$dest/lib/libgoat_transformers_c.a"
if [ "$(uname -s)" = Darwin ]; then
    # a program linked against the library finds it at the prefix
    install_name_tool -id "$prefix/lib/$shared" "$dest/lib/$shared"
fi

printf '%s\n' \
    "prefix=$prefix" \
    'includedir=${prefix}/include' \
    'libdir=${prefix}/lib' \
    '' \
    'Name: goat-transformers' \
    'Description: Convert messages between formats that are described by data files (C ABI of the Rust reference engine)' \
    'URL: https://github.com/USAREUR-AF/goat-transformers' \
    "Version: $version" \
    'Cflags: -I${includedir}' \
    'Libs: -L${libdir} -lgoat_transformers_c' \
    "Libs.private: $syslibs" \
    > "$dest/lib/pkgconfig/goat_transformers.pc"

echo "installed under $dest: include/goat_transformers.h lib/$shared lib/libgoat_transformers_c.a lib/pkgconfig/goat_transformers.pc"
