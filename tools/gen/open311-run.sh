#!/bin/bash
# Regenerate the Open311 GeoReport v2 packs: open311-request, open311-request-response,
# open311-service.
#
# Usage: tools/gen/open311-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds a git checkout of https://github.com/open311/open311.github.io at commit
# d65f0b9a6fb527bcb1836b1f986c5375c39541e1 (the document states CC BY 3.0 in info.license;
# the script checks the commit). Every pack reads data/georeport_v2-1.yaml (Swagger 2.0).
#
# Shared keys (tools/gen/notes/open311.md): Request service_request_id = uid,
# requested_datetime = time_ms, lat/long = lat/lon (WGS 84).
#
# Writes model/open311*.def, packs/open311-*/ (pack.def, pack.md, vectors/gen-*, PROVENANCE.md
# through tools/gen/jsonmore-provenance.py), packs/geojson/vectors/gen-geojson-to-open311-request.json
# and tools/gen/names/open311-*.json.
#
# With --check nothing is written; every run is made and the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] <sources> <goat-transformers checkout>" >&2; exit 2; fi
SRC="$(cd "$1" && pwd)/open311.github.io"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=d65f0b9a6fb527bcb1836b1f986c5375c39541e1
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "open311.github.io is at $got, not $COMMIT" >&2; exit 1; }
cd "$W"
STATUS=0
F="$SRC/data/georeport_v2-1.yaml"

o311_pack() {
  local fmt="$1" name="$2"; shift 2
  local module="$(echo "$fmt" | tr -d '-')"
  local args=(--schema "$F" --message "$name=$F#/definitions/$name" --format "$fmt" --module "$module"
    --title "Open311 GeoReport v2 $name (Swagger 2.0, open311.github.io)" --license "CC-BY-3.0, Open311 community"
    --source "https://github.com/open311/open311.github.io at commit $COMMIT, data/georeport_v2-1.yaml#/definitions/$name"
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/open311.md" "$@")
  if ! python3 -I "$GEN/jsonschema2pack.py" "${args[@]}" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1; [ -n "$CHECK" ] || { echo "open311-run: $fmt failed" >&2; exit 1; }
  fi
  [ -n "$CHECK" ] || echo "$fmt"
}

o311_pack open311-request Request \
  --map Request:service_request_id=uid --evidence "Request:service_request_id=georeport_v2-1.yaml: the unique identifier of the service request" \
  --map Request:requested_datetime=time_ms --evidence "Request:requested_datetime=georeport_v2-1.yaml: when the service request was made, a date-time" \
  --map Request:lat=lat --evidence "Request:lat=georeport_v2-1.yaml: latitude in WGS 84" \
  --map Request:long=lon --evidence "Request:long=georeport_v2-1.yaml: longitude in WGS 84" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
o311_pack open311-request-response RequestResponse \
  --map RequestResponse:service_request_id=uid --evidence "RequestResponse:service_request_id=georeport_v2-1.yaml: the unique identifier of the service request created"
o311_pack open311-service Service
python3 -I "$GEN/jsonmore-provenance.py" open311 ${CHECK:+"$CHECK"} "$SRC" "$W" || STATUS=1
exit "$STATUS"
