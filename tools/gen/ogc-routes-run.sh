#!/bin/bash
# Regenerate the OGC API - Routes Route Exchange Model (REM) packs.
# Usage: tools/gen/ogc-routes-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/ogcapi-routes is a checkout of https://github.com/opengeospatial/ogcapi-routes at
# commit c9b74b570326b83ec608f977aa381ccfe9d4cfa8 (the script checks it; the repository's only
# tag, v1.0.0-draft.1, is older), file rem/standard/code/rem-json-schema.json. License: the
# rem/ directory's LICENSE, the Apache License 2.0 (SHA-256
# b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1); the repository root
# LICENSE is the OGC Software License. The SHA-256 of the schema is in each pack.md.
#
# The route (a GeoJSON feature collection) is read on the json wire; its start, end and
# intermediate waypoints and its segments (each a Feature with a Point geometry) on the geojson
# wire. The REM text fixes WGS 84 horizontal coordinates and heights above mean sea level, so
# the third coordinate is not hae and is not bound.
#
# Writes model/ogcrem*.def, packs/ogc-routes-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-ogc-routes-*.json and tools/gen/names/ogc-routes-*.json.
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
check() {
  local got
  got="$(git -C "$SRC/$1" rev-parse HEAD)"
  [ "$got" = "$2" ] || { echo "$1 is at $got, not $2" >&2; exit 1; }
}
# gen <format> <module> <title> [options...]
gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$SOURCE" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
check ogcapi-routes c9b74b570326b83ec608f977aa381ccfe9d4cfa8
LICENSE="Apache-2.0, Open Geospatial Consortium (opengeospatial/ogcapi-routes, rem/LICENSE)"
SOURCE="https://github.com/opengeospatial/ogcapi-routes at commit c9b74b570326b83ec608f977aa381ccfe9d4cfa8, rem/standard/code/rem-json-schema.json"
R="$SRC/ogcapi-routes/rem/standard/code/rem-json-schema.json"
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
cd "$W"

gen ogc-routes-route ogcrem "OGC API - Routes, Route Exchange Model: a route (rem-json-schema.json)" \
  --schema "$R" --message Route="$R"
gen ogc-routes-waypoint ogcremwp "OGC API - Routes, Route Exchange Model: start, end or intermediate waypoint (rem-json-schema.json, Waypoint)" \
  --schema "$R" --message Waypoint="$R#/\$defs/Waypoint" --wire geojson --top-level-members id \
  --map Waypoint:geometry.lon=lon --map Waypoint:geometry.lat=lat --cross "$XG"
gen ogc-routes-segment ogcremseg "OGC API - Routes, Route Exchange Model: route segment (rem-json-schema.json, Segment)" \
  --schema "$R" --message Segment="$R#/\$defs/Segment" --wire geojson --top-level-members id \
  --map Segment:geometry.lon=lon --map Segment:geometry.lat=lat --cross "$XG"

exit "$STATUS"
