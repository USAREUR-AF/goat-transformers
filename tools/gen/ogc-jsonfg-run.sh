#!/bin/bash
# Regenerate the OGC Features and Geometries JSON (JSON-FG) 1.0.0 packs.
# Usage: tools/gen/ogc-jsonfg-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/ogc-feat-geo-json is a checkout of https://github.com/opengeospatial/ogc-feat-geo-json
# at tag v1.0.0, commit 2572fda3ddfd83a55e4c2a04c2e9e4c5daa6c20d (the script checks it), whose
# core/schemas/ are the schemas posted at https://schemas.opengis.net/json-fg/. License: the
# repository's LICENSE, the Apache License 2.0 (SHA-256
# b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1); core/schemas/README.md
# carries "Copyright (c) 2026 Open Geospatial Consortium". The SHA-256 of every schema file read
# is in each pack.md.
#
# A JSON-FG Feature is read twice: on the geojson wire (the Point geometry to lon, lat, hae) and
# on the json wire (the instant `time.timestamp` to time_ms, and the JSON-FG members `place`,
# `coordRefSys`, `featureType`). The geojson wire addresses no member of a top-level object, so
# no one pack carries both; pack.md says so.
#
# Writes model/ogcjfg*.def, packs/ogc-jsonfg-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-ogc-jsonfg-feature.json and
# tools/gen/names/ogc-jsonfg-*.json. PROVENANCE.md is not generated. With --check nothing is
# written; every run is made and the exit status is 1 when any file differs.
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
check ogc-feat-geo-json 2572fda3ddfd83a55e4c2a04c2e9e4c5daa6c20d
LICENSE="Apache-2.0, Open Geospatial Consortium (opengeospatial/ogc-feat-geo-json)"
SOURCE="https://github.com/opengeospatial/ogc-feat-geo-json at tag v1.0.0, commit 2572fda3ddfd83a55e4c2a04c2e9e4c5daa6c20d, core/schemas"
J="$SRC/ogc-feat-geo-json/core/schemas"
SCHEMAS=("$J/feature.json" "$J/featurecollection.json" "$J/time.json" "$J/place.json" "$J/geometry.json"
  "$J/geometry-object.json" "$J/coordrefsys.json" "$J/measures.json" "$J/featuretype.json" "$J/featureschema.json"
  "$J/link.json" "$J/conformsto.json")
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
cd "$W"

# One feature on the geojson wire
gen ogc-jsonfg-feature ogcjfgf "OGC Features and Geometries JSON (JSON-FG) 1.0.0, Feature (feature.json), geojson wire" \
  --schema "${SCHEMAS[@]}" --message Feature="$J/feature.json" --wire geojson --top-level-members id \
  --map Feature:geometry.lon=lon --map Feature:geometry.lat=lat --map Feature:geometry.alt=hae --cross "$XG"

# One feature on the json wire: time and the JSON-FG members
gen ogc-jsonfg-feature-json ogcjfgj "OGC Features and Geometries JSON (JSON-FG) 1.0.0, Feature (feature.json), json wire" \
  --schema "${SCHEMAS[@]}" --message Feature="$J/feature.json" \
  --date-time Feature:time.timestamp --map Feature:time.timestamp=time_ms

# A feature collection on the json wire
gen ogc-jsonfg-featurecollection ogcjfgfc "OGC Features and Geometries JSON (JSON-FG) 1.0.0, feature collection (featurecollection.json)" \
  --schema "${SCHEMAS[@]}" --message FeatureCollection="$J/featurecollection.json"

exit "$STATUS"
