#!/bin/sh
# The reduced-build check of the Go engine (spec/engine-spec.md, Version
# 0.24, "What pins it"). Run it from anywhere: sh engines/go/reduced-check.sh
#
# 1. Builds the engine with only the wires xml, json and geojson and runs
#    TestReducedBuild in that build: every conversion vector whose `from` and
#    `to` packs are on those wires must pass, and every pack on bits,
#    protobuf, text and tlv must fail to load with unknown-wire naming its
#    wire.
# 2. Builds goat-xf twice, with all seven wires and with the three, and loads
#    one pack on each of bits, protobuf, text and tlv with the reduced tool:
#    each must exit 1 with unknown-wire and a message that names the wire.
# 3. Checks that the reduced tool carries no decoder or encoder of the four
#    wires it lacks, and prints the size of both tools.
#
# Exits non-zero on any failure.
set -eu

cd "$(dirname "$0")"
TAGS=goat_wires,goat_wire_xml,goat_wire_json,goat_wire_geojson
PACKS=../../packs
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT INT TERM
fail=0

echo "== go vet -tags $TAGS"
go vet -tags "$TAGS" ./...

echo "== TestReducedBuild (-tags $TAGS)"
if go test -v -count=1 -tags "$TAGS" -run '^TestReducedBuild$' . >"$OUT/test.log" 2>&1; then
	grep -E '^(reduced build|unknown-wire load)' "$OUT/test.log"
else
	grep -E '^(reduced build|unknown-wire load|--- FAIL|FAIL|ok)|FAILED|\.go:[0-9]+:' "$OUT/test.log" | head -50
	echo "FAIL: TestReducedBuild"
	fail=1
fi

echo "== goat-xf, full and reduced"
go build -o "$OUT/goat-xf-full" ./cmd/goat-xf
go build -tags "$TAGS" -o "$OUT/goat-xf-reduced" ./cmd/goat-xf

for wire in bits protobuf text tlv; do
	pack=
	for def in "$PACKS"/*/pack.def; do
		if grep -Eq "^[[:space:]]*wire[[:space:]]+$wire[[:space:]]*\$" "$def"; then
			pack=$(basename "$(dirname "$def")")
			break
		fi
	done
	if [ -z "$pack" ]; then
		echo "FAIL: no pack on wire $wire"
		fail=1
		continue
	fi
	status=0
	"$OUT/goat-xf-reduced" list-formats --packs "$PACKS" --packs-only "$pack" >"$OUT/out" 2>"$OUT/err" || status=$?
	msg=$(cat "$OUT/err")
	case "$msg" in
	"unknown-wire: "*"wire \"$wire\""*"this build does not have it"*)
		if [ "$status" -eq 1 ]; then
			echo "ok   unknown-wire, wire $wire, pack $pack: $msg"
		else
			echo "FAIL wire $wire, pack $pack: exit status $status, want 1"
			fail=1
		fi
		;;
	*)
		echo "FAIL wire $wire, pack $pack: exit status $status, message: $msg"
		fail=1
		;;
	esac
done

# The reduced tool must not carry the codec of a wire it lacks, and must
# carry the codec of each wire it has.
nm_reduced=$(go tool nm "$OUT/goat-xf-reduced")
for sym in decodeBits encodeBits decodeSeq encodeSeq parseSixbitArmor decodeProtobuf encodeProtobuf decodeText encodeText decodeTLV encodeTLV; do
	if printf '%s\n' "$nm_reduced" | grep -Eq "engines/go\.$sym\$"; then
		echo "FAIL: the reduced tool carries $sym"
		fail=1
	fi
done
for sym in decodeXML encodeXML decodeJSONWire encodeJSONWire decodeGeoJSON encodeGeoJSON; do
	if ! printf '%s\n' "$nm_reduced" | grep -Eq "engines/go\.$sym\$"; then
		echo "FAIL: the reduced tool lacks $sym"
		fail=1
	fi
done

full=$(wc -c <"$OUT/goat-xf-full" | tr -d ' ')
reduced=$(wc -c <"$OUT/goat-xf-reduced" | tr -d ' ')
echo "size of goat-xf: full (7 wires) $full bytes, reduced (xml json geojson) $reduced bytes, $((full - reduced)) bytes less ($(go env GOOS)/$(go env GOARCH), $(go env GOVERSION))"

if [ "$fail" -ne 0 ]; then
	echo "reduced-build check: FAILED"
	exit 1
fi
echo "reduced-build check: passed"
