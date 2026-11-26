#!/bin/sh
# The single-wire check (engine-spec Version 0.24, ruling 1).
# From the repository root:  engines/erlang/single_wire_check.sh
#   GOAT_WIRES="tlv cbor"    only these wires (default: all eight)
#
# For each wire, under engines/erlang/_build/single/ (ebin/ is left alone):
#   - builds the engine with that wire alone and with every wire but it; a
#     compiler warning the full build does not print fails;
#   - in both builds, no module calls a function that is not in the build
#     (gt_undefined_calls.erl): Erlang resolves calls when they run, so a
#     missing helper compiles;
#   - on the build with the wire alone, every conversion vector whose `from`
#     and `to` packs are on it passes, and at least one ran; every pack on
#     another wire is `unknown-wire`, its message naming the wire; a `wire`
#     value that is no wire is `unknown-wire` too (gt_test:run_reduced/3).
# The build with every wire but one is compiled and its calls checked; its
# vectors are not run.
#
# The wire is tested alone on all eight, without json. The vectors are JSON,
# and a build without json and geojson has no gt_json or gt_test, so the runner
# is compiled on its own, with its modules renamed (gt_json to gt_sw_json,
# gt_test to gt_sw_test): an engine module that calls gt_json in a build without
# it still fails. Exits non-zero at the first failure.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
packs=${1:-$here/../../packs}
models=${2:-$packs/../model}
all="xml geojson json bits protobuf text tlv cbor"
wires=${GOAT_WIRES:-$all}
work=$here/_build/single

for w in $wires; do
    case " $all " in
        *" $w "*) ;;
        *) echo "single_wire_check.sh: $w is not a wire (one of: $all)" >&2; exit 2 ;;
    esac
done
[ -n "$(echo $wires)" ] || { echo "single_wire_check.sh: GOAT_WIRES names no wire" >&2; exit 2; }

# build <name> <wire list>: into $work/<name>; the warnings of the compiler,
# without those of the full build, must be none
build() {
    if ! "$here/build.sh" --wires "$2" --out "$work/$1" > "$work/$1.log" 2>&1; then
        cat "$work/$1.log"
        echo "FAIL $1: does not build"
        exit 1
    fi
    grep 'Warning:' "$work/$1.log" > "$work/$1.warnings" || true
    if [ "$1" != full ] && grep -vxFf "$work/full.warnings" "$work/$1.warnings"; then
        echo "FAIL $1: the warnings above are not in the full build"
        exit 1
    fi
    erl -noshell -pa "$work/runner" -s gt_undefined_calls main -extra "$work/$1" || {
        echo "FAIL $1: a call to a function that is not in the build"
        exit 1
    }
}

mkdir -p "$work/runner"
rm -f "$work"/runner/*.beam
erlc -Wall -o "$work/runner" "$here/gt_undefined_calls.erl"
build full "$(echo $all | tr ' ' ',')"

for m in gt_json gt_test; do
    sed 's/gt_json/gt_sw_json/g; s/gt_test/gt_sw_test/g' "$here/src/$m.erl" \
        > "$work/runner/$(echo $m | sed 's/^gt_/gt_sw_/').erl"
done
erlc -I "$here/src" -o "$work/runner" "$work"/runner/gt_sw_json.erl "$work"/runner/gt_sw_test.erl

for w in $wires; do
    start=$(date +%s)
    rest=""
    for o in $all; do [ "$o" = "$w" ] || rest="$rest${rest:+,}$o"; done
    echo "== $w alone"
    build "only-$w" "$w"
    erl -noshell -pa "$work/runner" -pa "$work/only-$w" \
        -eval "gt_sw_test:run_reduced(\"$packs\", \"$models\", [\"$w\"])" || {
        echo "FAIL only-$w: the vectors"
        exit 1
    }
    echo "== every wire but $w"
    build "no-$w" "$rest"
    echo "$w: ok, $(($(date +%s) - start)) s"
done
echo "single-wire check: passed ($(echo $wires))"
