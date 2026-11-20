#!/bin/bash
# Regenerate the OSDM packs: osdm-<object>, the message objects of the OSDM online API that
# carry a place or a time.
#
# Usage: tools/gen/osdm-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds a git checkout of https://github.com/UnionInternationalCheminsdeFer/OSDM at
# tag v3.11, commit d198a80259b9399754cec68cd60278892fe04cfe (Apache-2.0; the script checks the
# commit). Every pack reads specification/OSDM-online-api.yml and specification/schemas/**/*.yml.
#
# Shared keys (tools/gen/notes/osdm.md): Place and StopPlace id = uid and geoPosition
# latitude/longitude = lat/lon (WGS 84 degrees). No time is bound.
#
# Writes model/osdm*.def, packs/osdm-*/ (pack.def, pack.md, vectors/gen-*, PROVENANCE.md through
# tools/gen/jsonmore-provenance.py), packs/geojson/vectors/gen-geojson-to-osdm-place.json and
# tools/gen/names/osdm-*.json.
#
# With --check nothing is written; every run is made and the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] <sources> <goat-transformers checkout>" >&2; exit 2; fi
SRC="$(cd "$1" && pwd)/OSDM"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=d198a80259b9399754cec68cd60278892fe04cfe
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "OSDM is at $got, not $COMMIT" >&2; exit 1; }
cd "$W"
STATUS=0
API="$SRC/specification/OSDM-online-api.yml"
mapfile -t SCHEMAS < <(cd "$SRC/specification/schemas" && find . -name '*.yml' | LC_ALL=C sort | sed "s|^\./|$SRC/specification/schemas/|")
EV_ID="schemas/ojp/place.yml: the place's identifier, a URN (UIC station codes and others)"
EV_LAT="schemas/ojp/_common.yml: GeoPosition is a WGS 84 position; latitude in decimal degrees, -90 to 90"
EV_LON="schemas/ojp/_common.yml: GeoPosition is a WGS 84 position; longitude in decimal degrees, -180 to 180"

osdm_pack() {
  local fmt="$1" name="$2"; shift 2
  local module="$(echo "$fmt" | tr -d '-')"
  local args=(--schema "$API" "${SCHEMAS[@]}" --message "$name=$API#/components/schemas/$name"
    --format "$fmt" --module "$module"
    --title "OSDM online API $name (OpenAPI, UIC OSDM v3.11)" --license "Apache-2.0, UIC (UnionInternationalCheminsdeFer/OSDM)"
    --source "https://github.com/UnionInternationalCheminsdeFer/OSDM at tag v3.11, commit $COMMIT, specification/OSDM-online-api.yml#/components/schemas/$name"
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/osdm.md" "$@")
  if ! python3 -I "$GEN/jsonschema2pack.py" "${args[@]}" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1; [ -n "$CHECK" ] || { echo "osdm-run: $fmt failed" >&2; exit 1; }
  fi
  [ -n "$CHECK" ] || echo "$fmt"
}

PLACE=(--evidence "X:id=$EV_ID" --evidence "X:geoPosition.latitude=$EV_LAT" --evidence "X:geoPosition.longitude=$EV_LON")
osdm_pack osdm-place Place --map Place:id=uid --map Place:geoPosition.latitude=lat --map Place:geoPosition.longitude=lon \
  "${PLACE[@]//X:/Place:}" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
osdm_pack osdm-stop-place StopPlace --map StopPlace:id=uid --map StopPlace:geoPosition.latitude=lat \
  --map StopPlace:geoPosition.longitude=lon "${PLACE[@]//X:/StopPlace:}"
osdm_pack osdm-trip Trip
osdm_pack osdm-booking Booking
osdm_pack osdm-offer Offer
python3 -I "$GEN/jsonmore-provenance.py" osdm ${CHECK:+"$CHECK"} "$SRC" "$W" || STATUS=1
exit "$STATUS"
