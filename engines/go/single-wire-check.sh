#!/bin/sh
# The single-wire check of the Go engine (spec/engine-spec.md, Version 0.24).
# Run it from the repository root: sh engines/go/single-wire-check.sh
#
# For each wire W of the eight:
#
# 1. go vet and go build with W alone (go vet also type-checks the tests).
# 2. go vet and go build with every wire but W.
# 3. TestReducedBuild (reduced_test.go) in the build with W alone: every
#    conversion vector whose `from` and `to` packs are on W must pass, and
#    every pack on another wire must be unknown-wire. No second wire is
#    needed: the test reads its vector files with encoding/json, not with the
#    engine's json wire.
#
# The log of step 3 is read as well as its exit status, because go test exits 0
# when -run matches nothing or the test skips: the test must be reported as
# passed, nothing may be skipped, the build must have W and no other wire, and
# at least one conversion vector must have run, with none failed.
#
# GOAT_WIRES="xml cbor" checks only the wires it names; a name that is no wire,
# or a list with no name, is an error.
#
# Exits non-zero at the first failure.
set -eu

cd "$(dirname "$0")"
ALL="xml geojson json bits protobuf text tlv cbor"
WIRES=${GOAT_WIRES-$ALL}

named=0
for wire in $WIRES; do
	case " $ALL " in
	*" $wire "*) named=$((named + 1)) ;;
	*)
		echo "FAIL: GOAT_WIRES names \"$wire\", which is none of: $ALL"
		exit 1
		;;
	esac
done
if [ "$named" -eq 0 ]; then
	echo "FAIL: GOAT_WIRES names no wire"
	exit 1
fi

OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
trap 'exit 1' INT TERM
mkdir "$OUT/bin"

die() {
	echo "FAIL: $1"
	echo "single-wire check: FAILED"
	exit 1
}

# vet_build <what> <tags>: the trailing slash of -o makes go build link both
# commands instead of only compiling them.
vet_build() {
	echo "== go vet, go build: $1 (-tags $2)"
	go vet -tags "$2" ./... || die "go vet, $1"
	go build -tags "$2" -o "$OUT/bin/" ./... || die "go build, $1"
}

for wire in $WIRES; do
	alone=goat_wires,goat_wire_$wire
	without=goat_wires
	for w in $ALL; do
		if [ "$w" != "$wire" ]; then
			without=$without,goat_wire_$w
		fi
	done

	vet_build "$wire alone" "$alone"
	vet_build "every wire but $wire" "$without"

	echo "== TestReducedBuild: $wire alone"
	log=$OUT/test.log
	if ! go test -v -count=1 -tags "$alone" -run '^TestReducedBuild$' . >"$log" 2>&1; then
		grep -E '^(reduced build|unknown-wire load|--- FAIL|FAIL|panic:)|FAILED|\.go:[0-9]+:' "$log" | head -50
		die "TestReducedBuild, $wire alone"
	fi
	grep -q '^--- PASS: TestReducedBuild ' "$log" || die "TestReducedBuild did not run, $wire alone"
	if grep -Eq '^[[:space:]]*--- SKIP' "$log"; then
		die "TestReducedBuild skipped, $wire alone"
	fi
	grep -qx "reduced build: wires $wire" "$log" || die "the build does not have exactly the wire $wire"
	counts=$(grep -Eo 'conversion vectors: [0-9]+ run, [0-9]+ passed, [0-9]+ failed' "$log") || die "no vector count, $wire alone"
	printf '%s\n' "$counts" | grep -Eq '^conversion vectors: [1-9][0-9]* run, [1-9][0-9]* passed, 0 failed$' || die "$wire alone: $counts"
	echo "ok   $wire alone: $counts"
done

echo "single-wire check: passed ($named wires)"
