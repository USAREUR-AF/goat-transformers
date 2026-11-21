#!/bin/bash
# Regenerate the OGC API - Tiles - Part 1: Core 1.0.0 packs (tile set metadata and the
# tile matrix set of OGC Two Dimensional Tile Matrix Set and Tile Set Metadata 2.0, which
# the API's schemas carry).
# Usage: tools/gen/ogcapi-tiles-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/tiles-1.0.0 is a checkout of https://github.com/opengeospatial/ogcapi-tiles at
# tag 1.0.0, commit bcc9e01766e577b5c766b5877ac101b03862853c (the script checks it).
# License: the repository's LICENSE, the OGC Software License text with an AsciiDoc header
# (SHA-256 3f660d0f2255ab5e6f59a55552666a7bee1fe25b79392a31fe4a203031cbe50d), quoted in each
# pack's PROVENANCE.md. The SHA-256 of every schema file read is in each pack.md.
#
# OGC API - Maps - Part 1: Core 1.0.0 (opengeospatial/ogcapi-maps, tag v1.0.0) carries the
# same tms/ schemas (only tms/propertiesSchema.yaml differs); its own responses are images
# and its projections document is keyed by method name, so no Maps pack is generated.
#
# Writes model/ogctiles*.def, packs/ogcapi-tiles-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/ogcapi-tiles-*.json. PROVENANCE.md is not generated. With --check nothing
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
got="$(git -C "$SRC/tiles-1.0.0" rev-parse HEAD)"
[ "$got" = bcc9e01766e577b5c766b5877ac101b03862853c ] || { echo "tiles-1.0.0 is at $got" >&2; exit 1; }
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-tiles LICENSE); this pack is a modification that OGC has not approved or adopted"
ST="https://github.com/opengeospatial/ogcapi-tiles at tag 1.0.0, commit bcc9e01766e577b5c766b5877ac101b03862853c, openapi/schemas"
O="$SRC/tiles-1.0.0/openapi"
T="$O/schemas"
cd "$W"

gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$ST" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
BASE=("$T/common-core/link.yaml" "$T/common-geodata/crs.yaml" "$T/common-geodata/projJSON.yaml"
  "$T/common-geodata/dataType.yaml" "$T/common-geodata/timeStamp.yaml" "$T/tms/2DPoint.yaml" "$T/tms/2DBoundingBox.yaml")

# Tile set metadata (tms/tileSet.yaml)
gen ogcapi-tiles-tileset ogctileset "OGC API - Tiles - Part 1: Core 1.0.0, tile set metadata (tms/tileSet.yaml)" \
  --schema "$T/tms/tileSet.yaml" "${BASE[@]}" "$T/tms/geospatialData.yaml" "$T/tms/propertiesSchema.yaml" \
    "$T/tms/style.yaml" "$T/tms/tileMatrixLimits.yaml" "$T/tms/tilePoint.yaml" \
  --message TileSet="$T/tms/tileSet.yaml"

# The list of tile sets (responses/tiles-core/rTileSetsList.yaml, JSON body)
gen ogcapi-tiles-tileset-list ogctilesets "OGC API - Tiles - Part 1: Core 1.0.0, tile set list (responses/tiles-core/rTileSetsList.yaml)" \
  --schema "$O/responses/tiles-core/rTileSetsList.yaml" "$T/tms/tileSet-item.yaml" "${BASE[@]}" \
  --message TileSets="$O/responses/tiles-core/rTileSetsList.yaml#/content/application~1json/schema"

# A tile matrix set definition (tms/tileMatrixSet.yaml)
gen ogcapi-tiles-tilematrixset ogctms "OGC API - Tiles - Part 1: Core 1.0.0, tile matrix set (tms/tileMatrixSet.yaml)" \
  --schema "$T/tms/tileMatrixSet.yaml" "$T/tms/tileMatrix.yaml" "$T/tms/variableMatrixWidth.yaml" "${BASE[@]}" \
  --message TileMatrixSet="$T/tms/tileMatrixSet.yaml"

exit "$STATUS"
