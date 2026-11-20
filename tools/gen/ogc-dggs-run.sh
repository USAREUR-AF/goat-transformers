#!/bin/bash
# Regenerate the OGC API - Discrete Global Grid Systems (DGGS) Part 1 packs.
# Usage: tools/gen/ogc-dggs-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/ogcapi-discrete-global-grid-systems is a checkout of
# https://github.com/opengeospatial/ogcapi-discrete-global-grid-systems at commit
# b1637533e4132e7a656b712c11ac055052a3804e (the script checks it; tags 1.0.0-rc1 to rc4 are
# earlier). License: the repository's LICENSE, the OGC Software License (SHA-256
# b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1), quoted in each
# PROVENANCE.md. The SHA-256 of every schema file read is in each pack.md.
#
# Writes model/ogcdggs*.def, packs/ogc-dggs-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/ogc-dggs-*.json. PROVENANCE.md is not generated. With --check nothing is
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
check ogcapi-discrete-global-grid-systems b1637533e4132e7a656b712c11ac055052a3804e
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-discrete-global-grid-systems LICENSE); this pack is a modification that OGC has not approved or adopted"
SOURCE="https://github.com/opengeospatial/ogcapi-discrete-global-grid-systems at commit b1637533e4132e7a656b712c11ac055052a3804e"
D="$SRC/ogcapi-discrete-global-grid-systems"
O="$D/openapi/schemas"
cd "$W"

# Zone information (openapi/schemas/dggs-core/zone-info.yaml)
gen ogc-dggs-zone ogcdggsz "OGC API - DGGS Part 1, zone information (dggs-core/zone-info.yaml)" \
  --schema "$O/dggs-core/zone-info.yaml" "$O/common-core/link.yaml" "$O/geojson/PolygonFeature.yaml" "$O/geojson/PolygonGeometry.yaml" \
  --message Zone="$O/dggs-core/zone-info.yaml"
# The zone list (responses/dggs-core/rZonesList.yaml, JSON body)
gen ogc-dggs-zones ogcdggszl "OGC API - DGGS Part 1, zone list (responses/dggs-core/rZonesList.yaml, JSON body)" \
  --schema "$D/openapi/responses/dggs-core/rZonesList.yaml" "$O/common-core/link.yaml" "$O/geojson/FeatureCollection.yaml" \
    "$O/geojson/Feature.yaml" \
  --message Zones="$D/openapi/responses/dggs-core/rZonesList.yaml#/content/application~1json/schema"
# Zone data in DGGS-JSON (core/schemas/dggs-json/dggs-json.yaml)
gen ogc-dggs-zone-data ogcdggsd "OGC API - DGGS Part 1, zone data in DGGS-JSON (core/schemas/dggs-json/dggs-json.yaml)" \
  --schema "$D/core/schemas/dggs-json/dggs-json.yaml" "$D/core/schemas/dggs-json/schema.yaml" \
  --message ZoneData="$D/core/schemas/dggs-json/dggs-json.yaml"

exit "$STATUS"
