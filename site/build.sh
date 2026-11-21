#!/usr/bin/env bash
# build.sh: regenerate site/assets/engine/ from this tree.
#
# The page's demo runs the library's own WebAssembly module on a pinned set of
# packs. Nothing under site/assets/engine/ is written by hand and none of it is
# kept in git: this script builds the module, copies the packs and model
# modules, records what goat-xf prints for each sample, writes a manifest with
# the commit and SHA-256 of every file, writes the tree's counts into
# site/index.html, and checks that the page shows the outputs the tree gives.
#
# Needs: a Rust toolchain with the wasm32-unknown-unknown target, python3, git.
#
#   site/build.sh              build everything
#   site/build.sh --clean      also delete the two cargo target directories afterwards
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$here")"
clean=0
[ "${1:-}" = "--clean" ] && clean=1

echo "build.sh: the WebAssembly module (bindings/wasm, profile small)"
( cd "$repo/bindings/wasm" && cargo build --profile small --target wasm32-unknown-unknown )

echo "build.sh: the command-line tool (engines/rust, release)"
( cd "$repo/engines/rust" && cargo build --release )

# The counts move with every merged pack: the page is given the tree's counts
# at build time, so a deployed page is never behind the tree it was built from.
echo "build.sh: the page's counts, from the tree"
python3 -I "$here/bundle.py" --counts-only --write

# The catalog chart (the page's first section) is drawn from the family table
# and packs/ on every build, as the counts are, so it is never behind the tree.
# It stops the build when a pack has no family.
echo "build.sh: the catalog chart, from tools/catalog-families and packs/"
python3 -I "$repo/tools/catalog-radial.py" --site

python3 -I "$here/bundle.py" \
  --wasm "$repo/bindings/wasm/target/wasm32-unknown-unknown/small/goat_transformers_wasm.wasm" \
  --goat-xf "$repo/engines/rust/target/release/goat-xf"

if [ "$clean" = 1 ]; then
  rm -rf "$repo/bindings/wasm/target" "$repo/engines/rust/target"
  echo "build.sh: removed the cargo target directories"
fi
