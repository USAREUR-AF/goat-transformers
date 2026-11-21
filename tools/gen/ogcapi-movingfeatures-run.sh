#!/bin/bash
# Regenerate the OGC API - Moving Features packs (Part 1: Core; the MF-JSON Prism schemas the
# API's repository carries).
# Usage: tools/gen/ogcapi-movingfeatures-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/mf-head is a checkout of https://github.com/opengeospatial/ogcapi-movingfeatures
# at commit 889d086a468bf092e63d7bb356cf14866502bc22 (the script checks it); the repository's
# tags (0.01, 0.02, v0.0.3) are earlier drafts. License: the repository's LICENSE, the OGC
# Software License (SHA-256 b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1),
# quoted in each pack's PROVENANCE.md. The SHA-256 of every schema file read is in each
# pack.md.
#
# The API's own response schemas (openapi/schemas/movingFeature.yaml,
# temporalGeometrySequence.yaml, temporalProperties.yaml) refer to
# https://schemas.opengis.net/movingfeatures/1.0/MF-JSON_Prism.schema.json, which is not in
# the repository and carries no license statement of its own; they are not generated. The
# repository's copy of the Prism schemas (openapi/schemas/MF-JSON/Prism/) is read instead.
#
# Writes model/ogcmf*.def, packs/ogcapi-mf-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/ogcapi-mf-*.json. PROVENANCE.md is not generated. With --check nothing
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
got="$(git -C "$SRC/mf-head" rev-parse HEAD)"
[ "$got" = 889d086a468bf092e63d7bb356cf14866502bc22 ] || { echo "mf-head is at $got" >&2; exit 1; }
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-movingfeatures LICENSE); this pack is a modification that OGC has not approved or adopted"
SM="https://github.com/opengeospatial/ogcapi-movingfeatures at commit 889d086a468bf092e63d7bb356cf14866502bc22, openapi/schemas/MF-JSON/Prism"
M="$SRC/mf-head/openapi/schemas/MF-JSON/Prism"
cd "$W"

gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$SM" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
# shellcheck disable=SC2207
PRISM=($(cd "$M" && LC_ALL=C ls ./*.yaml | sed "s|^\./|$M/|"))
GEOM="https://schemas.opengis.net/ogcapi/features/part1/1.0/openapi/schemas/geometryGeoJSON.yaml"

# One moving feature (MF-JSON/Prism/movingFeature.yaml)
gen ogcapi-mf-moving-feature ogcmf "OGC API - Moving Features - Part 1: Core, moving feature (MF-JSON Prism movingFeature.yaml)" \
  --schema "${PRISM[@]}" --opaque "$GEOM" \
  --message MovingFeature="$M/movingFeature.yaml"

# A moving feature collection (MF-JSON/Prism/movingFeatureCollection.yaml)
gen ogcapi-mf-moving-feature-collection ogcmfc "OGC API - Moving Features - Part 1: Core, moving feature collection (MF-JSON Prism movingFeatureCollection.yaml)" \
  --schema "${PRISM[@]}" --opaque "$GEOM" \
  --message MovingFeatureCollection="$M/movingFeatureCollection.yaml"

exit "$STATUS"
