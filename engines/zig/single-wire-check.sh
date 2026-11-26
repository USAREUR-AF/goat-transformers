#!/usr/bin/env bash
# The single-wire check of spec Version 0.24 for the Zig engine.
#
#   engines/zig/single-wire-check.sh            (from the repository root)
#
# For each of the eight wires:
#
# 1. Builds the harness and goat-xf with that wire alone (`-Dwires=<w>`), and
#    with every wire but it.
# 2. Runs both reduced harnesses over the packs directory. Zig analyses only
#    the code a program reaches, so a build alone proves little; the run is
#    the check. Every vector a build runs must pass, and the build of one wire
#    must have run at least one conversion vector. The harness runs on one
#    wire alone: it reads vectors with the standard library's JSON reader and
#    not with the codec of the `json` wire, so `json` need not be added.
#
# Exits non-zero at the first failure. GOAT_WIRES="xml cbor" names fewer wires
# to check. OPTIMIZE (default ReleaseSmall) chooses the optimize mode, and
# JOBS (default 4) the number of build jobs. Builds go to
# zig-out/single-wire/, which git ignores.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
packs="$root/packs"
optimize="${OPTIMIZE:-ReleaseSmall}"
jobs="${JOBS:-4}"
all="xml geojson json bits protobuf text tlv cbor"
wires="${GOAT_WIRES:-$all}"
out="$here/zig-out/single-wire"

note() { printf '%s\n' "$*"; }
die() { printf 'FAIL %s\n' "$*"; note "single-wire check: FAILED"; exit 1; }

cd "$here" || exit 2
mkdir -p "$out" || exit 2

# check <label> <comma-separated wires> <name of the build directory>
check() {
    local label="$1" set="$2" dir="$out/$3" ran got want
    rm -rf "${dir:?}"
    mkdir -p "$dir" || exit 2
    if ! zig build install cli "-j$jobs" "-Dwires=$set" -Doptimize="$optimize" --prefix "$dir" >"$dir/build.log" 2>&1; then
        cat "$dir/build.log"
        die "$label: the build (-Dwires=$set)"
    fi
    "$dir/bin/gt-engine-zig" "$packs" >"$dir/vectors.txt" 2>&1
    local status=$?
    if [ "$status" -ne 0 ]; then
        head -50 "$dir/vectors.txt"
        die "$label: the vectors (exit $status)"
    fi
    # the build has the wires it was asked for, and no other
    got="$(sed -n 's/^wires of this build: //p' "$dir/vectors.txt" | tr ' ' '\n' | sort | tr '\n' ' ')"
    want="$(printf '%s' "$set" | tr ',' '\n' | sort | tr '\n' ' ')"
    [ "$got" = "$want" ] || die "$label: the wires of the build are: $got"
    ran="$(sed -n 's/^vectors: \([0-9][0-9]*\)\/[0-9][0-9]* passed$/\1/p' "$dir/vectors.txt")"
    [ "${ran:-0}" -gt 0 ] || die "$label: no conversion vector ran"
    note "  ok   $label: $(grep -E '^(loaded|vectors|load vectors|capability vectors):' "$dir/vectors.txt" | paste -sd ';' | sed 's/;/; /g')"
}

# every name is a wire, before anything is built
count=0
for w in $wires; do
    case " $all " in
        *" $w "*) count=$((count + 1)) ;;
        *) die "GOAT_WIRES: $w is not a wire ($all)" ;;
    esac
done
[ "$count" -gt 0 ] || die "GOAT_WIRES names no wire"

note "single wires, -Doptimize=$optimize:"
for w in $wires; do
    but=""
    for x in $all; do
        [ "$x" = "$w" ] || but="${but:+$but,}$x"
    done
    check "$w alone" "$w" "$w"
    check "every wire but $w" "$but" "no-$w"
done

note ""
note "single-wire check: passed"
