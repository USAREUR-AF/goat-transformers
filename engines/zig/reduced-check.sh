#!/usr/bin/env bash
# The reduced-build check of spec Version 0.24 for the Zig engine.
#
#   engines/zig/reduced-check.sh            (from the repository root)
#
# 1. Builds the engine with the wires xml, json and geojson only
#    (`zig build -Dwires=xml,json,geojson`), and with all seven.
# 2. Runs the reduced harness over the packs directory: it loads every pack on
#    those three wires, leaves out (and counts) every pack on another wire,
#    and runs every conversion, load and capability vector whose packs it
#    loaded. Every one must pass.
# 3. Loads one pack on bits (fixed layout), one on bits (sequential layout),
#    one on protobuf, one on text and one on tlv in the reduced build: each
#    must be `unknown-wire`, with a message that names the wire and says this
#    build does not have it.
# 4. Prints the size of the reduced build beside the full build: the harness
#    gt-engine-zig and the command-line tool goat-xf.
#
# Exits non-zero on any failure. OPTIMIZE (default ReleaseSmall) chooses the
# optimize mode of both builds.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
packs="$root/packs"
optimize="${OPTIMIZE:-ReleaseSmall}"
wires="xml,json,geojson"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

fail=0
note() { printf '%s\n' "$*"; }
bad() { printf 'FAIL %s\n' "$*"; fail=1; }

cd "$here" || exit 2

note "building: full (all seven wires), -Doptimize=$optimize"
if ! zig build install cli -Doptimize="$optimize" --prefix "$out/full" >"$out/full.log" 2>&1; then
    cat "$out/full.log"
    bad "the full build"
    exit 1
fi
note "building: reduced (-Dwires=$wires), -Doptimize=$optimize"
if ! zig build install cli -Dwires="$wires" -Doptimize="$optimize" --prefix "$out/reduced" >"$out/reduced.log" 2>&1; then
    cat "$out/reduced.log"
    bad "the reduced build"
    exit 1
fi

harness="$out/reduced/bin/gt-engine-zig"

# 2. the vectors of the packs on the three wires
note ""
note "vectors on the reduced build:"
"$harness" "$packs" >"$out/vectors.txt" 2>&1
status=$?
grep -v '^FAIL ' "$out/vectors.txt" | sed 's/^/  /'
grep '^FAIL ' "$out/vectors.txt" | head -50
if [ "$status" -ne 0 ]; then
    bad "the reduced build's vectors (exit $status)"
fi
if ! grep -q '^left out: [1-9]' "$out/vectors.txt"; then
    bad "the reduced build left out no pack: is it reduced?"
fi

# 3. a pack on each wire the reduced build lacks
note ""
note "packs on a wire the reduced build does not have:"
for pair in bits:conformance-absent-bits bits:conformance-absent-seq protobuf:conformance-absent-protobuf text:conformance-text tlv:conformance-tlv; do
    wire="${pair%%:*}"
    pack="${pair#*:}"
    if [ ! -f "$packs/$pack/pack.def" ]; then
        bad "$pack: no such pack"
        continue
    fi
    msg="$("$harness" "$packs" --packs-only "$pack" 2>&1)"
    st=$?
    line="$(printf '%s\n' "$msg" | grep -m1 'load error:' || true)"
    if [ "$st" -ne 0 ] \
        && printf '%s' "$line" | grep -q 'load error: unknown-wire: ' \
        && printf '%s' "$line" | grep -q "wire $wire " \
        && printf '%s' "$line" | grep -q 'this build does not have'; then
        note "  ok   $pack ($wire): ${line#load error: }"
    else
        bad "$pack ($wire): expected unknown-wire naming $wire, got: $msg"
    fi
done

# 4. sizes
size() { stat -c %s "$1" 2>/dev/null || stat -f %z "$1"; }
note ""
note "sizes (-Doptimize=$optimize), bytes:"
printf '  %-14s %12s %12s %8s\n' "binary" "full" "reduced" "reduced/full"
for bin in gt-engine-zig goat-xf; do
    f="$(size "$out/full/bin/$bin")"
    r="$(size "$out/reduced/bin/$bin")"
    printf '  %-14s %12s %12s %7s%%\n' "$bin" "$f" "$r" "$((r * 100 / f))"
done

note ""
if [ "$fail" -ne 0 ]; then
    note "reduced-build check: FAILED"
    exit 1
fi
note "reduced-build check: passed"
