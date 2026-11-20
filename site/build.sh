#!/usr/bin/env bash
# build.sh: regenerate site/assets/engine/ from this tree.
#
# The page's demo runs the library's own WebAssembly module on a pinned set of
# packs. Nothing under site/assets/engine/ is written by hand and none of it is
# kept in git: this script builds the module, copies the packs and model
# modules, records what goat-xf prints for each sample, writes a manifest with
# the commit and SHA-256 of every file, and checks that site/index.html states
# the same numbers and outputs as the tree.
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

python3 -I "$here/bundle.py" \
  --wasm "$repo/bindings/wasm/target/wasm32-unknown-unknown/small/goat_transformers_wasm.wasm" \
  --goat-xf "$repo/engines/rust/target/release/goat-xf"

if [ "$clean" = 1 ]; then
  rm -rf "$repo/bindings/wasm/target" "$repo/engines/rust/target"
  echo "build.sh: removed the cargo target directories"
fi
