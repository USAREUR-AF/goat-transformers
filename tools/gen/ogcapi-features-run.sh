#!/bin/bash
# Regenerate the OGC API - Features packs (Part 1 Core 1.0.1, Part 2 CRS by Reference 1.0.1).
# Usage: tools/gen/ogcapi-features-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds two checkouts of https://github.com/opengeospatial/ogcapi-features
# (the script checks each commit):
#   features-1.0.1        tag 1.0.1,        commit 4ff19a5734578cf1f815d03ab192e8e0dc407e9f
#   features-part2-1.0.1  tag part2-1.0.1,  commit eed9c9dbb722264c62353cec29b8de7dfb8a1b6e
# License: the repository's LICENSE, the OGC Software License (SHA-256
# b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1), quoted in each
# pack's PROVENANCE.md. The SHA-256 of every schema file read is in each pack.md.
#
# Part 3 (Filtering) defines queryables, a JSON Schema document about a collection, and
# CQL2 expressions: neither is a message of this kind. Part 4 (Create, Replace, Update and
# Delete) sends the Feature of Part 1 and adds no schema. Neither is generated.
#
# Writes model/ogcfeat*.def, packs/ogcapi-feature*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-ogcapi-feature.json and
# tools/gen/names/ogcapi-feature*.json. PROVENANCE.md is not generated. With --check
# nothing is written; every run is made and the exit status is 1 when any file differs.
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
check features-1.0.1 4ff19a5734578cf1f815d03ab192e8e0dc407e9f
check features-part2-1.0.1 eed9c9dbb722264c62353cec29b8de7dfb8a1b6e
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-features LICENSE); this pack is a modification that OGC has not approved or adopted"
cd "$W"

# gen <format> <module> <title> <source> [options...]
gen() {
  local fmt="$1" mod="$2" title="$3" source="$4"
  shift 4
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$source" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
P1="$SRC/features-1.0.1/core/openapi/schemas"
P2="$SRC/features-part2-1.0.1/extensions/crs/openapi/schemas"
S1="https://github.com/opengeospatial/ogcapi-features at tag 1.0.1, commit 4ff19a5734578cf1f815d03ab192e8e0dc407e9f, core/openapi/schemas"
S2="https://github.com/opengeospatial/ogcapi-features at tag part2-1.0.1, commit eed9c9dbb722264c62353cec29b8de7dfb8a1b6e, extensions/crs/openapi/schemas"
GEOM="$P1/geometryGeoJSON.yaml $P1/pointGeoJSON.yaml $P1/multipointGeoJSON.yaml $P1/linestringGeoJSON.yaml $P1/multilinestringGeoJSON.yaml $P1/polygonGeoJSON.yaml $P1/multipolygonGeoJSON.yaml $P1/geometrycollectionGeoJSON.yaml"
PART1="http://schemas.opengis.net/ogcapi/features/part1/1.0/openapi/schemas"
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"

# One Feature (Part 1, featureGeoJSON.yaml) on the geojson wire. `id` is a string or an
# integer, which no transform reads (pack.md).
# shellcheck disable=SC2086
gen ogcapi-feature ogcfeat "OGC API - Features - Part 1: Core 1.0.1, Feature (featureGeoJSON.yaml)" "$S1" \
  --schema "$P1/featureGeoJSON.yaml" "$P1/link.yaml" $GEOM \
  --message Feature="$P1/featureGeoJSON.yaml" --wire geojson --top-level-members id \
  --map Feature:geometry.lon=lon --map Feature:geometry.lat=lat --map Feature:geometry.alt=hae \
  --cross "$XG"

# The items response (Part 1, featureCollectionGeoJSON.yaml) on the json wire.
# shellcheck disable=SC2086
gen ogcapi-feature-collection ogcfeatfc "OGC API - Features - Part 1: Core 1.0.1, feature collection (featureCollectionGeoJSON.yaml)" "$S1" \
  --schema "$P1/featureCollectionGeoJSON.yaml" "$P1/featureGeoJSON.yaml" "$P1/link.yaml" $GEOM \
  --message FeatureCollection="$P1/featureCollectionGeoJSON.yaml"

# A collection description: Part 2 collection.yaml (Part 1 collection.yaml with storageCrs
# and storageCrsCoordinateEpoch). Its reference to Part 1 by URL resolves to the 1.0.1 file.
gen ogcapi-features-collection ogcfeatcoll "OGC API - Features - Part 2: Coordinate Reference Systems by Reference 1.0.1, collection (with Part 1 collection.yaml)" "$S2" \
  --source "$S1" \
  --schema "$P2/collection.yaml" "$P2/collectionExtensionCrs.yaml" "$P1/collection.yaml" "$P1/extent.yaml" "$P1/link.yaml" \
  --alias "$PART1/collection.yaml=$P1/collection.yaml" \
  --message Collection="$P2/collection.yaml"

# The collections response: Part 2 collections.yaml.
gen ogcapi-features-collections ogcfeatcolls "OGC API - Features - Part 2: Coordinate Reference Systems by Reference 1.0.1, collections (with Part 1 collections.yaml)" "$S2" \
  --source "$S1" \
  --schema "$P2/collections.yaml" "$P2/collectionsExtensionCrs.yaml" "$P1/collections.yaml" "$P1/collection.yaml" \
    "$P1/extent.yaml" "$P1/link.yaml" \
  --alias "$PART1/collections.yaml=$P1/collections.yaml" \
  --message Collections="$P2/collections.yaml"

exit "$STATUS"
