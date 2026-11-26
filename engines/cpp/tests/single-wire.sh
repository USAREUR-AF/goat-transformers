#!/bin/sh
# Every wire alone, and every wire left out (engine-spec.md, Version 0.24,
# rulings 1a to 1d). From the repository's root:
#
#   sh engines/cpp/tests/single-wire.sh
#
# First, with all eight wires, the library, goat-xf and
# goat_transformers_vectors are built: the warnings of that build are the ones
# the builds below may have. Then, for each wire:
#
# 1. With that wire alone: the library, goat-xf and goat_transformers_vectors
#    build, with no new warning. goat_transformers_vectors passes: in such a
#    build it loads the packs on that wire, runs the conversion, load and
#    capability vectors whose formats and packs are all on it, and requires
#    every pack on another wire to be refused with unknown-wire. It reads the
#    vector files with its own copy of the JSON reader, so the wire alone is
#    enough and json is not added. No conversion vector between two formats
#    of the wire is a failure: a vector that pins unknown-format runs in every
#    build and is not counted.
# 2. With every wire but that one: the library and goat-xf build, with no new
#    warning.
#
# The builds are engines/cpp/build-wire-all, build-wire-only-<wire> and
# build-wire-no-<wire>, each with its output in build.log. Every build starts
# clean, since a file that is not compiled again gives no warning.
#
# Exits non-zero at the first failure. GT_JOBS sets the build's parallel jobs
# (4). GOAT_WIRES names fewer wires, separated by spaces: GOAT_WIRES="cbor tlv".
set -eu
LC_ALL=C
export LC_ALL

here=$(cd "$(dirname "$0")/.." && pwd)
jobs=${GT_JOBS:-4}
all="xml geojson json bits protobuf text tlv cbor"
wires=${GOAT_WIRES:-$all}
baseline="$here/build-wire-all/warnings.txt"

fail() {
    echo "single-wire check: FAILED: $1" >&2
    exit 1
}

# build <directory> <wire set> <target>...: a clean build; its warnings, sorted,
# in warnings.txt.
build() {
    dir=$1
    set_of_wires=$2
    shift 2
    mkdir -p "$dir"
    if ! cmake -S "$here" -B "$dir" -DCMAKE_BUILD_TYPE=Release "-DGT_WIRES=$set_of_wires" \
        -DGT_INSTALL=OFF >"$dir/build.log" 2>&1 ||
        ! cmake --build "$dir" -j "$jobs" --clean-first --target "$@" >>"$dir/build.log" 2>&1; then
        grep -E 'rror|undefined reference' "$dir/build.log" | head -n 40 >&2 || true
        fail "the build with wires ${set_of_wires:-(all)} (see $dir/build.log)"
    fi
    grep -iE 'warning[: ]' "$dir/build.log" | sort -u >"$dir/warnings.txt" || true
}

# no_new_warning <directory> <wire set>
no_new_warning() {
    comm -13 "$baseline" "$1/warnings.txt" >"$1/new-warnings.txt"
    if [ -s "$1/new-warnings.txt" ]; then
        cat "$1/new-warnings.txt" >&2
        fail "new warnings in the build with wires $2 (see $1/build.log)"
    fi
}

for wire in $wires; do
    case " $all " in
        *" $wire "*) ;;
        *) fail "GOAT_WIRES: '$wire' is not a wire; the wires are $all" ;;
    esac
done

build "$here/build-wire-all" "" goat_transformers goat-xf goat_transformers_vectors
echo "all wires: built, $(wc -l <"$baseline" | tr -d ' ') warnings"

checked=0
for wire in $wires; do
    only="$here/build-wire-only-$wire"
    build "$only" "$wire" goat_transformers goat-xf goat_transformers_vectors
    no_new_warning "$only" "$wire"
    if ! "$only/goat_transformers_vectors" >"$only/vectors.log" 2>&1; then
        grep -A 4 '^FAIL' "$only/vectors.log" | head -n 60 >&2 || true
        fail "the vectors with wire $wire alone (see $only/vectors.log)"
    fi
    run=$(sed -n 's/^conversion vectors with both formats loaded: //p' "$only/vectors.log")
    [ "${run:-0}" -gt 0 ] || fail "no conversion vector ran on wire $wire"

    others=""
    for w in $all; do
        [ "$w" = "$wire" ] || others="$others${others:+,}$w"
    done
    without="$here/build-wire-no-$wire"
    build "$without" "$others" goat_transformers goat-xf
    no_new_warning "$without" "$others"
    echo "$wire: alone built, $run conversion vectors passed; every wire but $wire built"
    checked=$((checked + 1))
done

[ "$checked" -gt 0 ] || fail "GOAT_WIRES names no wire"
echo "single-wire check: passed, $checked wires"
