#!/bin/bash
# Regenerate the OpenTripPlanner and hafas-client packs (public transport JSON APIs).
# Usage: tools/gen/transit-run.sh [--check] <sources> <goat-transformers checkout>
#
# Neither API publishes a JSON Schema. This project restated the objects it maps in its own
# files under tools/gen/transit/ (no text of the sources is copied); this script generates the
# packs from them. The sources the restatements were made from, checked by SHA-256:
#   <sources>/otp-schema.graphqls  OpenTripPlanner tag v2.10.0 (commit
#     521cd5d8acaae628878f43bf5946f4942c118548),
#     application/src/main/resources/org/opentripplanner/apis/gtfs/schema.graphqls; LGPL-3.0
#   <sources>/hafas-client/docs/radar.md  hafas-client tag 6.3.6 (commit
#     3f5049d47401bec509b8caab69a1fc68086fe972); ISC
# The packs restate member names and types and carry the project's licence, Apache-2.0.
#
# Writes model/otp*.def, model/hafas*.def, packs/otp-*/, packs/hafas-*/ (pack.def, pack.md,
# vectors/gen-*), packs/geojson/vectors/gen-geojson-to-*.json and the names files.
# PROVENANCE.md is not generated. With --check nothing is written; every run is made and the
# exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <sources> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
STATUS=0
while read -r sha f; do
  got="$(sha256sum "$SRC/$f" | cut -d' ' -f1)"
  [ "$got" = "$sha" ] || { echo "$f: sha256 $got, expected $sha" >&2; exit 1; }
done <<'SUMS'
ee5c42d5fd6346b6062d057030f8cb2062517b31e93add66ca5a92cae247aac4 otp-schema.graphqls
e1ffd42b9d34d3c56b53cd238317e626bb35eb59fdfbc1f26776941ec2a1a66c hafas-client/docs/radar.md
SUMS
OTP="$GEN/transit/otp-2.10-objects.json"
HAF="$GEN/transit/hafas-client-6-objects.json"
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
cd "$W"

# gen <file> <object> <format> <module> <title> <license> <source> [options...]
gen() {
  local file="$1" obj="$2" fmt="$3" mod="$4" title="$5" lic="$6" src="$7"
  shift 7
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$file" --message "$obj=$file#/\$defs/$obj" \
      --format "$fmt" --module "$mod" --title "$title" --license "$lic" --source "$src" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
OL="Apache-2.0 (this project's restatement of the OpenTripPlanner GTFS GraphQL API; OpenTripPlanner is LGPL-3.0)"
OS="OpenTripPlanner v2.10.0, commit 521cd5d8acaae628878f43bf5946f4942c118548, apis/gtfs/schema.graphqls, restated in tools/gen/transit/otp-2.10-objects.json"
HL="Apache-2.0 (this project's restatement of hafas-client results; hafas-client is ISC)"
HS="hafas-client 6.3.6, commit 3f5049d47401bec509b8caab69a1fc68086fe972, docs/radar.md, restated in tools/gen/transit/hafas-client-6-objects.json"

gen "$OTP" VehiclePosition otp-vehicle-position otpvehpos \
  "OpenTripPlanner 2.10 GTFS GraphQL API, a vehicle position (VehiclePosition)" "$OL" "$OS" \
  --map VehiclePosition:lat=lat --map VehiclePosition:lon=lon --map VehiclePosition:lastUpdate=time_ms \
  --map VehiclePosition:speed=speed_ms --map VehiclePosition:vehicleId=uid --map VehiclePosition:label=callsign \
  --cross "$XG"
gen "$OTP" Itinerary otp-itinerary otpitin \
  "OpenTripPlanner 2.10 GTFS GraphQL API, an itinerary of a plan (Itinerary)" "$OL" "$OS"
gen "$HAF" Movement hafas-movement hafasmove \
  "hafas-client 6 radar(), one movement of a vehicle" "$HL" "$HS" \
  --map Movement:location.latitude=lat --map Movement:location.longitude=lon --cross "$XG"
gen "$HAF" Radar hafas-radar hafasradar \
  "hafas-client 6 radar(), the result: movements and the realtime update time" "$HL" "$HS"

exit "$STATUS"
