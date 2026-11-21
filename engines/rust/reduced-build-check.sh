#!/bin/sh
# Engine-spec 0.24, "What pins it": the reduced-build check of the Rust engine.
#
#   engines/rust/reduced-build-check.sh            (from the repository root)
#
# 1. builds the engine with only the wires xml, json and geojson (Cargo
#    features; GOAT_WIRES=<w>,<w>... names another set) and runs
#    tests/vectors.rs on it: every conversion, load and capability vector
#    whose packs are on those wires, with every pack on those wires loaded;
# 2. runs tests/reduced.rs: one pack of the repository on each wire the build
#    lacks must be `unknown-wire`, the message naming the wire;
# 3. builds `goat-xf` with all seven wires and with the reduced set, and prints
#    the size of each beside the other, and of each library (.rlib).
#
# The reduced build goes to target/reduced, so the full build in target/ is
# left as it was. Exits non-zero on any failure.
set -eu
cd "$(dirname "$0")"
wires="${GOAT_WIRES:-xml,json,geojson}"
reduced="--no-default-features --features $wires --target-dir target/reduced"

echo "== reduced build ($wires): vectors and unknown-wire loads"
status=0
# shellcheck disable=SC2086
log=$(cargo test --release $reduced --test vectors --test reduced -- --nocapture 2>&1) || status=$?
printf '%s\n' "$log" | grep -E '^(ran |left out |this build |  [a-z0-9-]+ \(wire |loaded |  FAIL)' || true
if [ "$status" -ne 0 ]; then
    printf '%s\n' "$log" | tail -40 >&2
    echo "reduced-build check: FAILED (cargo test --release $reduced --test vectors --test reduced)" >&2
    exit 1
fi

echo "== sizes (release)"
# shellcheck disable=SC2086
cargo build --release $reduced --bin goat-xf --lib -q
cargo build --release --bin goat-xf --lib -q
size() { wc -c <"$1" | tr -d ' '; }
full_bin=$(size target/release/goat-xf)
red_bin=$(size target/reduced/release/goat-xf)
full_lib=$(size target/release/libgoat_transformers.rlib)
red_lib=$(size target/reduced/release/libgoat_transformers.rlib)
printf '%-34s %12s %12s\n' "" "all seven" "$wires"
printf '%-34s %12s %12s\n' "goat-xf (bytes)" "$full_bin" "$red_bin"
printf '%-34s %12s %12s\n' "libgoat_transformers.rlib (bytes)" "$full_lib" "$red_lib"
echo "reduced-build check: passed"
