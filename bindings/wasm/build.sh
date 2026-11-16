#!/bin/sh
# Build the WebAssembly module and put the small build where the npm package
# expects it: dist/goat_transformers.wasm, beside goat_transformers.mjs.
# After this, `npm pack` in this directory writes a tarball that works when
# installed. Needs: rustup target add wasm32-unknown-unknown.
#
# Usage: ./build.sh [--release]    --release ships the faster, larger build
set -eu
cd "$(dirname "$0")"
profile=small
if [ "${1:-}" = "--release" ]; then profile=release; fi
if [ "$profile" = release ]; then
    cargo build --release --target wasm32-unknown-unknown
else
    cargo build --profile small --target wasm32-unknown-unknown
fi
mkdir -p dist
cp "target/wasm32-unknown-unknown/$profile/goat_transformers_wasm.wasm" dist/goat_transformers.wasm
echo "dist/goat_transformers.wasm ($profile build):"
ls -l dist/goat_transformers.wasm
