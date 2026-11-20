#!/bin/bash
# Regenerate the OGC API - Joins Part 1 (draft) packs.
# Usage: tools/gen/ogc-joins-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/ogcapi-joins is a checkout of https://github.com/opengeospatial/ogcapi-joins at
# commit 049eb007240204686c33548cd7944d0e84798da4 (the script checks it; the repository has no
# tag: a draft). License: the repository's LICENSE, the OGC Software License (SHA-256
# b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1), quoted in each
# PROVENANCE.md. The SHA-256 of every schema file read is in each pack.md.
#
# Writes model/ogcjoin*.def, packs/ogc-joins-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/ogc-joins-*.json. PROVENANCE.md is not generated. With --check nothing is
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
check ogcapi-joins 049eb007240204686c33548cd7944d0e84798da4
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-joins LICENSE); this pack is a modification that OGC has not approved or adopted"
SOURCE="https://github.com/opengeospatial/ogcapi-joins at commit 049eb007240204686c33548cd7944d0e84798da4 (draft), sources/core/openapi/schemas"
J="$SRC/ogcapi-joins/sources/core/openapi/schemas"
FILES=("$J/link.yaml" "$J/joinObject.yaml" "$J/joinInformationObject.yaml" "$J/joinInputsObject.yaml" "$J/joinsObject.yaml"
  "$J/keyObject.yaml" "$J/collectionKeysObject.yaml")
cd "$W"

gen ogc-joins-join ogcjoin "OGC API - Joins Part 1 (draft), a join (join.yaml)" \
  --schema "$J/join.yaml" "${FILES[@]}" --message Join="$J/join.yaml"
gen ogc-joins-joins ogcjoins "OGC API - Joins Part 1 (draft), the list of joins (joins.yaml)" \
  --schema "$J/joins.yaml" "${FILES[@]}" --message Joins="$J/joins.yaml"

exit "$STATUS"
