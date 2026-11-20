#!/bin/sh
# The reduced-build check of the C++ engine (engine-spec.md, Version 0.24,
# "What pins it"). From the repository's root:
#
#   sh engines/cpp/tests/reduced-build.sh
#
# 1. Builds the engine with the wires xml, json and geojson
#    (engines/cpp/build-wires-reduced) and runs goat_transformers_vectors,
#    which in such a build loads only the packs on those wires, runs every
#    conversion, load and capability vector whose formats and packs are all on
#    them, and requires every pack on bits, protobuf, text, tlv and cbor to be refused
#    with unknown-wire, the wire named and this build's lack said.
# 2. Builds the library and goat-xf with all eight wires
#    (engines/cpp/build-wires-full) and prints the sizes of both builds.
#
# Exits non-zero on any failure. GT_JOBS sets the build's parallel jobs (4).
set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
jobs=${GT_JOBS:-4}
reduced="$here/build-wires-reduced"
full="$here/build-wires-full"

cmake -S "$here" -B "$reduced" -DCMAKE_BUILD_TYPE=Release -DGT_WIRES=xml,json,geojson -DGT_INSTALL=OFF >/dev/null
cmake --build "$reduced" -j "$jobs"
"$reduced/goat_transformers_vectors"

cmake -S "$here" -B "$full" -DCMAKE_BUILD_TYPE=Release -DGT_BUILD_TESTS=OFF -DGT_INSTALL=OFF >/dev/null
cmake --build "$full" -j "$jobs" --target goat_transformers goat-xf

size() { wc -c <"$1" | tr -d ' '; }
echo "sizes in bytes, Release        all eight wires   xml,json,geojson"
printf 'libgoat_transformers.a         %15s   %16s\n' "$(size "$full/libgoat_transformers.a")" "$(size "$reduced/libgoat_transformers.a")"
printf 'goat-xf                        %15s   %16s\n' "$(size "$full/goat-xf")" "$(size "$reduced/goat-xf")"
echo "reduced-build check: passed"
