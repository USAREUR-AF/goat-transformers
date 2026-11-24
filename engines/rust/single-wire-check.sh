#!/bin/sh
# Engine-spec 0.24: the Rust engine builds with each wire alone.
#
#   engines/rust/single-wire-check.sh              (from the repository root)
#
# For each wire feature of Cargo.toml's default set: the library and goat-xf
# build with that feature only and with every feature but it, with no warning,
# and tests/reduced.rs passes on the build with it only. tests/vectors.rs reads
# the vector files with the engine's own json codec, so it runs on the build
# with the wire and json.
# GOAT_WIRES="<wire> ..." names fewer wires. The builds go to target/single.
# Exits non-zero at the first failure.
set -eu
cd "$(dirname "$0")"
all=$(sed -n 's/^default = \[\(.*\)\]$/\1/p' Cargo.toml | tr -d '" ' | tr ',' ' ')
[ -n "$all" ] || { echo "single-wire check: no default features in Cargo.toml" >&2; exit 1; }
target="${CARGO_TARGET_DIR:-target}/single"
quiet() { log=$(RUSTFLAGS="-D warnings" "$@" 2>&1) || { printf '%s\n' "$log" | tail -40 >&2; echo "single-wire check: FAILED ($*)" >&2; exit 1; }; }
for wire in ${GOAT_WIRES:-$all}; do
    others=$(for w in $all; do [ "$w" = "$wire" ] || printf '%s,' "$w"; done)
    quiet cargo check --no-default-features --features "${others%,}" --lib --bin goat-xf --target-dir "$target"
    quiet cargo check --no-default-features --features "$wire" --lib --bin goat-xf --target-dir "$target"
    quiet cargo test --no-default-features --features "$wire" --test reduced --target-dir "$target" -- --nocapture
    quiet cargo test --no-default-features --features "$wire,json" --test vectors --target-dir "$target" -- --nocapture
    printf '%s: ' "$wire"
    printf '%s\n' "$log" | grep -E '^ran [0-9]+ conversion' || { echo "no conversion vector ran" >&2; exit 1; }
done
echo "single-wire check: passed"
