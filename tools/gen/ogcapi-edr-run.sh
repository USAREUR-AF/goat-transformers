#!/bin/bash
# Regenerate the OGC API - Environmental Data Retrieval (EDR) 1.1.0 packs.
# Usage: tools/gen/ogcapi-edr-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/edr-1.1.0 is a checkout of
# https://github.com/opengeospatial/ogcapi-environmental-data-retrieval at tag 1.1.0-final,
# commit 2810187e1bd78eeb7a88bb918d3f2759c9040ff4 (the script checks it). The OpenAPI
# document at that tag names the OGC License; the repository's LICENSE file, the OGC
# Software License, was added later (commit 6c43a72, SHA-256
# b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1); PROVENANCE.md quotes
# both. The SHA-256 of every schema file read is in each pack.md.
#
# Writes model/ogcedr*.def, packs/ogcapi-edr-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-ogcapi-edr-feature.json and
# tools/gen/names/ogcapi-edr-*.json. PROVENANCE.md is not generated. With --check nothing
# is written; every run is made and the exit status is 1 when any file differs.
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
got="$(git -C "$SRC/edr-1.1.0" rev-parse HEAD)"
[ "$got" = 2810187e1bd78eeb7a88bb918d3f2759c9040ff4 ] || { echo "edr-1.1.0 is at $got" >&2; exit 1; }
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-environmental-data-retrieval); this pack is a modification that OGC has not approved or adopted"
SE="https://github.com/opengeospatial/ogcapi-environmental-data-retrieval at tag 1.1.0-final, commit 2810187e1bd78eeb7a88bb918d3f2759c9040ff4, standard/openapi/schemas"
E="$SRC/edr-1.1.0/standard/openapi/schemas"
cd "$W"

gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$SE" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
# files <dir>: every .yaml file of the directory under $E, sorted
files() { (cd "$E/$1" && LC_ALL=C ls -- *.yaml) | sed "s|^|$E/$1/|"; }
# shellcheck disable=SC2207
GEOJSON=($(files geojson) "$E/edr-geojson/edrProperties.yaml" "$E/core/link.yaml")
# shellcheck disable=SC2207
EDRGJ=($(files edr-geojson) "$E/i18n.yaml" "$E/numberMatched.yaml" "$E/numberReturned.yaml")
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"

# One EDR location feature (geojson/featureGeoJSON.yaml with edrProperties.yaml)
gen ogcapi-edr-feature ogcedrf "OGC API - EDR 1.1.0, feature (geojson/featureGeoJSON.yaml, edr-geojson/edrProperties.yaml)" \
  --schema "${GEOJSON[@]}" \
  --message Feature="$E/geojson/featureGeoJSON.yaml" --wire geojson --top-level-members id \
  --map Feature:geometry.lon=lon --map Feature:geometry.lat=lat --map Feature:properties.label=callsign \
  --cross "$XG"

# The EDR GeoJSON feature collection (edr-geojson/edrFeatureCollectionGeoJSON.yaml)
# shellcheck disable=SC2046
gen ogcapi-edr-feature-collection ogcedrfc "OGC API - EDR 1.1.0, feature collection (edr-geojson/edrFeatureCollectionGeoJSON.yaml)" \
  --schema $(files geojson) "$E/core/link.yaml" "${EDRGJ[@]}" \
  --message FeatureCollection="$E/edr-geojson/edrFeatureCollectionGeoJSON.yaml"

# A CoverageJSON response (covjson/coverageJSON.yaml)
# shellcheck disable=SC2046
gen ogcapi-edr-coverage ogcedrcov "OGC API - EDR 1.1.0, CoverageJSON response (covjson/coverageJSON.yaml)" \
  --schema $(files covjson) "${EDRGJ[@]}" \
  --message Coverage="$E/covjson/coverageJSON.yaml"

# A collection description (collections/collection.yaml)
# shellcheck disable=SC2046
gen ogcapi-edr-collection ogcedrcoll "OGC API - EDR 1.1.0, collection (collections/collection.yaml)" \
  --schema $(files collections) "$E/core/link.yaml" "${EDRGJ[@]}" \
  --message Collection="$E/collections/collection.yaml"

exit "$STATUS"
