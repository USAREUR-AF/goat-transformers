#!/bin/bash
# Regenerate the OGC SWE Common 3.0 and SensorML 3.0 JSON packs: swe-common-3-json, sensorml-3-json.
# Usage: tools/gen/ogc-swe-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds one git checkout, at the commit below (the script checks):
#   ogcapi-connected-systems  https://github.com/opengeospatial/ogcapi-connected-systems
#                             commit fb858be23aa03e2b824ec50b5a97ac2c2a1d3fec
#                             (OGC Software License, the file LICENSE at that commit)
# The files read are swecommon/schemas/json/*.json, sensorml/schemas/json/*.json and
# common/*.json; the same SWE Common files are published at
# https://schemas.opengis.net/sweCommon/3.0/json/ (byte for byte; the SensorML files there
# differ only in their relative $ref paths). A sparse checkout of those three directories
# and LICENSE is enough. The SHA-256 of every schema file read is in each pack's pack.md;
# PROVENANCE.md is not generated.
#
# Writes model/{swecommon3,sensorml3}.def, packs/{swe-common-3-json,sensorml-3-json}/
# (pack.def, pack.md, vectors/gen-*) and tools/gen/names/{swe-common-3-json,sensorml-3-json}.json.
#
# With --check nothing is written: each run compares what it would write with the
# checkout and its names file, both runs are made, and the exit status is 1 when any
# file differs. Without it the script stops at the first run that fails.
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

jsonschema2pack() {
  if ! python3 -I "$GEN/jsonschema2pack.py" "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
got="$(git -C "$SRC/ogcapi-connected-systems" rev-parse HEAD)"
[ "$got" = fb858be23aa03e2b824ec50b5a97ac2c2a1d3fec ] || { echo "ogcapi-connected-systems is at $got" >&2; exit 1; }
cd "$W"
R="$SRC/ogcapi-connected-systems"
SWE="$R/swecommon/schemas/json"
SML="$R/sensorml/schemas/json"
LIC="OGC Software License (LICENSE of opengeospatial/ogcapi-connected-systems); this pack is a change OGC has not approved"
SRCLINE="https://github.com/opengeospatial/ogcapi-connected-systems at commit fb858be23aa03e2b824ec50b5a97ac2c2a1d3fec"
DEPTH="SWE Common aggregates (DataRecord, DataArray, DataChoice, Matrix, DataStream) hold components of any type, which hold aggregates again without bound; four levels hold a record of records of simple components, and deeper parts are not mapped"

# SWE Common 3.0: one kind per data component and DataStream, chosen by the member type.
SWEMSG=()
for t in Boolean Count Quantity Time Category Text CountRange QuantityRange TimeRange CategoryRange \
         DataRecord Vector DataArray Matrix DataChoice Geometry DataStream; do
  SWEMSG+=(--message "$t=$SWE/$t.json" --kind-when "$t:type=$t")
done
jsonschema2pack \
  --schema $(cd "$R" && ls swecommon/schemas/json/*.json common/*.json | LC_ALL=C sort | sed "s|^|$R/|") \
  --opaque https://geojson.org/schema/ \
  "${SWEMSG[@]}" \
  --format swe-common-3-json --module swecommon3 \
  --title "OGC SWE Common Data Model 3.0, JSON encoding: data component descriptions" \
  --license "$LIC" --source "$SRCLINE, swecommon/schemas/json" \
  --max-depth 4 --limit-reason "$DEPTH" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/swe-common-3-json.json" \
  --notes-file "$GEN/notes/swe-common-3-json.md"

# SensorML 3.0: one kind per concrete process or deployment, chosen by the member type.
SMLMSG=()
for t in PhysicalSystem PhysicalComponent SimpleProcess AggregateProcess Deployment; do
  SMLMSG+=(--message "$t=$SML/$t.json" --kind-when "$t:type=$t")
done
jsonschema2pack \
  --schema $(cd "$R" && ls sensorml/schemas/json/*.json swecommon/schemas/json/*.json common/*.json | LC_ALL=C sort | sed "s|^|$R/|") \
  --opaque https://geojson.org/schema/ \
  "${SMLMSG[@]}" \
  --map "*:uniqueId=uid" --evidence "*:uniqueId=the URI that identifies the described system, component, process or deployment worldwide (usually a URN): the stable identifier of the entity" \
  --map "*:label=callsign" --evidence "*:label=the name of the described object for people to read" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input" \
  --format sensorml-3-json --module sensorml3 \
  --title "OGC SensorML 3.0, JSON encoding: system, component, process and deployment descriptions" \
  --license "$LIC" --source "$SRCLINE, sensorml/schemas/json" \
  --max-depth 4 --limit-reason "$DEPTH" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/sensorml-3-json.json" \
  --notes-file "$GEN/notes/sensorml-3-json.md"

exit "$STATUS"
