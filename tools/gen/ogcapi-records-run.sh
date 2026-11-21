#!/bin/bash
# Regenerate the OGC API - Records - Part 1: Core 1.0.0 packs.
# Usage: tools/gen/ogcapi-records-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds (the script checks each commit):
#   records-1.0.0   https://github.com/opengeospatial/ogcapi-records  tag 1.0.0,
#                   commit df95f9cfebe732cbcb5178a934bb0e040c957c74
#   features-1.0.1  https://github.com/opengeospatial/ogcapi-features tag 1.0.1,
#                   commit 4ff19a5734578cf1f815d03ab192e8e0dc407e9f (catalog.yaml refers to
#                   the Features Part 1 collection.yaml by its schemas.opengis.net address)
# License: each repository's LICENSE, the OGC Software License (SHA-256
# b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1), quoted in each
# pack's PROVENANCE.md. The SHA-256 of every schema file read is in each pack.md.
#
# Writes model/ogcrec*.def, packs/ogcapi-record*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-ogcapi-record.json and tools/gen/names/ogcapi-record*.json.
# PROVENANCE.md is not generated. With --check nothing is written; every run is made and
# the exit status is 1 when any file differs.
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
check records-1.0.0 df95f9cfebe732cbcb5178a934bb0e040c957c74
check features-1.0.1 4ff19a5734578cf1f815d03ab192e8e0dc407e9f
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-records LICENSE); this pack is a modification that OGC has not approved or adopted"
cd "$W"

gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$SR" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
R="$SRC/records-1.0.0/core/openapi/schemas"
F="$SRC/features-1.0.1/core/openapi/schemas"
SR="https://github.com/opengeospatial/ogcapi-records at tag 1.0.0, commit df95f9cfebe732cbcb5178a934bb0e040c957c74, core/openapi/schemas"
SF="https://github.com/opengeospatial/ogcapi-features at tag 1.0.1, commit 4ff19a5734578cf1f815d03ab192e8e0dc407e9f, core/openapi/schemas"
PART1="https://schemas.opengis.net/ogcapi/features/part1/1.0/openapi/schemas"
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
RECORD_FILES=("$R/recordGeoJSON.yaml" "$R/recordCommonProperties.yaml" "$R/time.yaml" "$R/link.yaml" "$R/linkBase.yaml"
  "$R/linkTemplate.yaml" "$R/language.yaml" "$R/license.yaml" "$R/theme.yaml" "$R/format.yaml" "$R/contact.yaml"
  "$R/roles.yaml")

# One record (recordGeoJSON.yaml), a GeoJSON Feature. The geometry is the wire's own
# structure (--opaque).
gen ogcapi-record ogcrec "OGC API - Records - Part 1: Core 1.0.0, record (recordGeoJSON.yaml)" \
  --schema "${RECORD_FILES[@]}" --opaque "$PART1/geometryGeoJSON.yaml" \
  --message Record="$R/recordGeoJSON.yaml" --wire geojson --top-level-members id \
  --map Record:id=uid --map Record:geometry.lon=lon --map Record:geometry.lat=lat --map Record:geometry.alt=hae \
  --cross "$XG"

# A catalog (catalog.yaml): a Features collection with the catalog's common properties.
gen ogcapi-records-catalog ogcreccat "OGC API - Records - Part 1: Core 1.0.0, catalog (catalog.yaml, with Features Part 1 collection.yaml)" \
  --source "$SF" \
  --schema "$R/catalog.yaml" "$R/catalogCommonProperties.yaml" "$R/recordCommonProperties.yaml" "$R/time.yaml" \
    "$R/link.yaml" "$R/linkBase.yaml" "$R/linkTemplate.yaml" "$R/language.yaml" "$R/license.yaml" "$R/theme.yaml" \
    "$R/format.yaml" "$R/contact.yaml" "$R/roles.yaml" "$R/defaultSortOrder.yaml" "$R/schema.yaml" "$R/scheme.yaml" \
    "$F/collection.yaml" "$F/extent.yaml" "$F/link.yaml" \
  --alias "$PART1/collection.yaml=$F/collection.yaml" \
  --message Catalog="$R/catalog.yaml"

exit "$STATUS"
