#!/bin/sh
# The reduced-build check (engine-spec Version 0.24, "What pins it").
# From the repository root:  engines/erlang/reduced_check.sh
#
# Builds the engine twice under engines/erlang/_build/ (ebin/ is left alone):
# with every wire, and with only xml, json and geojson. On the reduced
# build it runs every conversion vector whose `from` and `to` packs are on
# those wires, loads every pack on bits, protobuf, text, tlv and cbor (each must
# be unknown-wire, its message naming the wire), and loads a pack whose wire
# is no wire at all. Then prints the size of both builds: the .beam files
# build.sh writes. Exits non-zero on any failure.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
packs=${1:-$here/../../packs}
models=${2:-$packs/../model}
wires=xml,json,geojson
full=$here/_build/full/ebin
reduced=$here/_build/reduced/ebin

"$here/build.sh" --out "$full"
"$here/build.sh" --wires "$wires" --out "$reduced"

status=0
erl -noshell -pa "$reduced" -eval "gt_test:run_reduced(\"$packs\", \"$models\", string:lexemes(\"$wires\", \",\"))" || status=$?

size() { cat "$1"/*.beam | wc -c | tr -d ' '; }
count() { ls "$1"/*.beam | wc -l | tr -d ' '; }
fs=$(size "$full"); rs=$(size "$reduced")
echo "size, full build (8 wires): $fs bytes in $(count "$full") .beam files"
echo "size, reduced build ($wires): $rs bytes in $(count "$reduced") .beam files ($((rs * 100 / fs))% of full)"
exit $status
