#!/bin/bash
# Regenerate the OGC API - Common packs (Part 1: Core exception; Part 2: Geospatial Data
# 1.0.0 collection descriptions).
# Usage: tools/gen/ogcapi-common-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/common-part2-1.0.0 is a checkout of https://github.com/opengeospatial/ogcapi-common
# at tag part2-1.0.0, commit 08d2d3c059158a1e0ef289e5d91183eee7058c59 (the script checks
# it). License: the repository's LICENSE, the OGC Software License (SHA-256
# b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1), quoted in each
# pack's PROVENANCE.md. The SHA-256 of every schema file read is in each pack.md.
#
# Not generated: the landing page (a title, a description and links) and the conformance
# declaration (a list of URIs) carry no data of their own.
#
# Writes model/ogccom*.def, packs/ogcapi-common-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/ogcapi-common-*.json. PROVENANCE.md is not generated. With --check nothing
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
got="$(git -C "$SRC/common-part2-1.0.0" rev-parse HEAD)"
[ "$got" = 08d2d3c059158a1e0ef289e5d91183eee7058c59 ] || { echo "common-part2-1.0.0 is at $got" >&2; exit 1; }
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-common LICENSE); this pack is a modification that OGC has not approved or adopted"
SO="https://github.com/opengeospatial/ogcapi-common at tag part2-1.0.0, commit 08d2d3c059158a1e0ef289e5d91183eee7058c59, collections/openapi/schemas"
O="$SRC/common-part2-1.0.0/collections/openapi/schemas"
cd "$W"

gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$SO" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
GEO=("$O/common-geodata/collectionDesc.yaml" "$O/common-geodata/collectionProperties.yaml" "$O/common-geodata/extent.yaml"
  "$O/common-geodata/spatialExtent.yaml" "$O/common-geodata/temporalExtent.yaml" "$O/common-geodata/additionalDimensionExtent.yaml"
  "$O/common-geodata/grid.yaml" "$O/common-geodata/regularGrid.yaml" "$O/common-geodata/irregularGrid.yaml"
  "$O/common-geodata/dataType.yaml" "$O/common-core/link.yaml" "$O/records-core/contact.yaml" "$O/records-core/roles.yaml"
  "$O/records-core/format.yaml" "$O/records-core/language.yaml" "$O/records-core/theme.yaml")

# An exception (common-core/exception.yaml), the problem details object of IETF RFC 7807
gen ogcapi-common-exception ogccomexc "OGC API - Common (Part 2 1.0.0 tree), exception (common-core/exception.yaml)" \
  --schema "$O/common-core/exception.yaml" \
  --message Exception="$O/common-core/exception.yaml"

# A collection description (common-geodata/collectionDesc.yaml)
gen ogcapi-common-collection ogccomcoll "OGC API - Common - Part 2: Geospatial Data 1.0.0, collection (common-geodata/collectionDesc.yaml)" \
  --schema "${GEO[@]}" \
  --message Collection="$O/common-geodata/collectionDesc.yaml"

# The collections response (common-geodata/collections.yaml)
gen ogcapi-common-collections ogccomcolls "OGC API - Common - Part 2: Geospatial Data 1.0.0, collections (common-geodata/collections.yaml)" \
  --schema "$O/common-geodata/collections.yaml" "$O/common-geodata/collectionDesc-UAD.yaml" "$O/common-geodata/extent-UAD.yaml" \
    "$O/common-geodata/numberMatched.yaml" "$O/common-geodata/numberReturned.yaml" "${GEO[@]}" \
  --message Collections="$O/common-geodata/collections.yaml"

exit "$STATUS"
