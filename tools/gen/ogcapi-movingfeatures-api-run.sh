#!/bin/bash
# Regenerate the OGC API - Moving Features response packs (the API's own response schemas,
# which refer to the MF-JSON Prism schema on schemas.opengis.net).
# Usage: tools/gen/ogcapi-movingfeatures-api-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds:
#   mf-head         https://github.com/opengeospatial/ogcapi-movingfeatures at commit
#                   889d086a468bf092e63d7bb356cf14866502bc22 (openapi/schemas/*.yaml; OGC
#                   Software License)
#   features-1.0.1  https://github.com/opengeospatial/ogcapi-features tag 1.0.1, commit
#                   4ff19a5734578cf1f815d03ab192e8e0dc407e9f (link.yaml, referred to by URL)
#   schemas-opengis-net-mf/MF-JSON_Prism.schema.json
#                   https://schemas.opengis.net/movingfeatures/1.0/MF-JSON_Prism.schema.json
#                   (OGC Moving Features Encoding Extension - JSON 1.0, Prism schema), read
#                   2026-11-20, SHA-256 below. The file states no licence, so these packs are
#                   labelled LicenseRef-unstated (REUSE.toml).
# The script checks both commits and the SHA-256. The SHA-256 of every schema file read is
# in each pack.md.
#
# Writes model/ogcmfapi*.def, packs/ogcapi-mf-api-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/ogcapi-mf-api-*.json. PROVENANCE.md is not generated. With --check nothing
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
check() {
  local got
  got="$(git -C "$SRC/$1" rev-parse HEAD)"
  [ "$got" = "$2" ] || { echo "$1 is at $got, not $2" >&2; exit 1; }
}
check mf-head 889d086a468bf092e63d7bb356cf14866502bc22
check features-1.0.1 4ff19a5734578cf1f815d03ab192e8e0dc407e9f
PRISM="$SRC/schemas-opengis-net-mf/MF-JSON_Prism.schema.json"
SHA=125b3b380c10850e5ee952803a797ed11dce7348df9d0c908393c8e30c4e2402
got="$(sha256sum "$PRISM" | cut -d' ' -f1)"
[ "$got" = "$SHA" ] || { echo "$PRISM: sha256 $got, expected $SHA" >&2; exit 1; }
LICENSE="no licence stated: the API schemas are under the OGC Software License, the MF-JSON Prism schema they refer to states none; this pack is a modification that OGC has not approved or adopted"
SM="https://github.com/opengeospatial/ogcapi-movingfeatures at commit 889d086a468bf092e63d7bb356cf14866502bc22, openapi/schemas"
SP="https://schemas.opengis.net/movingfeatures/1.0/MF-JSON_Prism.schema.json, read 2026-11-20"
M="$SRC/mf-head/openapi/schemas"
F="$SRC/features-1.0.1/core/openapi/schemas"
cd "$W"

gen() {
  local fmt="$1" mod="$2" file="$3" kind="$4"
  shift 4
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" \
      --title "OGC API - Moving Features - Part 1: Core, $kind response ($file)" \
      --license "$LICENSE" --source "$SM" --source "$SP" \
      --schema "$M/$file" "$PRISM" "$F/link.yaml" "$@" \
      --alias "https://schemas.opengis.net/movingfeatures/1.0/MF-JSON_Prism.schema.json=$PRISM" \
      --alias "https://schemas.opengis.net/ogcapi/features/part1/1.0/openapi/schemas/link.yaml=$F/link.yaml" \
      --opaque "https://schemas.opengis.net/ogcapi/features/part1/1.0/openapi/schemas/geometryGeoJSON.yaml" --opaque https://geojson.org/schema/ \
      --message "$kind=$M/$file" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
gen ogcapi-mf-api-feature ogcmfapif movingFeature.yaml MovingFeature
gen ogcapi-mf-api-features ogcmfapifs movingFeatures.yaml MovingFeatures "$M/movingFeature.yaml"
gen ogcapi-mf-api-collection ogcmfapic movingFeatureCollection.yaml MovingFeatureCollection
gen ogcapi-mf-api-tgsequence ogcmfapitg temporalGeometrySequence.yaml TemporalGeometrySequence
gen ogcapi-mf-api-tproperties ogcmfapitps temporalProperties.yaml TemporalProperties \
  "$M/temporalProperty.yaml" "$M/temporalPrimitiveValue.yaml"
gen ogcapi-mf-api-tproperty ogcmfapitp temporalProperty.yaml TemporalProperty "$M/temporalPrimitiveValue.yaml"
gen ogcapi-mf-api-tvalue-sequence ogcmfapitv temporalValueSequence.yaml TemporalValueSequence "$M/temporalPrimitiveValue.yaml"

exit "$STATUS"
