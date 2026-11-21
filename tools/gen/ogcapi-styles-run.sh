#!/bin/bash
# Regenerate the OGC API - Styles packs (Part 1: Core, draft).
# Usage: tools/gen/ogcapi-styles-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/styles-head is a checkout of https://github.com/opengeospatial/ogcapi-styles at
# commit 51c63a33d3e5bfe4135cb6ca32bc5aa9cdf01f9c (the script checks it). The repository has
# no release tag (part1-1.0.0-draft.1 and v1.0.0rc1 are drafts); this commit is a draft of
# Part 1. License: the repository's LICENSE, the OGC Software License (SHA-256
# b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1), quoted in each
# pack's PROVENANCE.md. The SHA-256 of every schema file read is in each pack.md.
#
# Writes model/ogcstyle*.def, packs/ogcapi-style*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/ogcapi-style*.json. PROVENANCE.md is not generated. With --check nothing
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
got="$(git -C "$SRC/styles-head" rev-parse HEAD)"
[ "$got" = 51c63a33d3e5bfe4135cb6ca32bc5aa9cdf01f9c ] || { echo "styles-head is at $got" >&2; exit 1; }
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-styles LICENSE); this pack is a modification that OGC has not approved or adopted"
SS="https://github.com/opengeospatial/ogcapi-styles at commit 51c63a33d3e5bfe4135cb6ca32bc5aa9cdf01f9c (draft), standard/openapi/schemas"
Y="$SRC/styles-head/standard/openapi/schemas"
cd "$W"

gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$SS" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
BASE=("$Y/styles-core/styleDescription.yaml" "$Y/common-core/link.yaml" "$Y/records-core/contact.yaml"
  "$Y/records-core/roles.yaml" "$Y/records-core/format.yaml" "$Y/records-core/theme.yaml" "$Y/records-core/language.yaml")

# Style metadata (styles-core/styleDescription.yaml)
gen ogcapi-style-metadata ogcstyle "OGC API - Styles - Part 1: Core (draft), style metadata (styles-core/styleDescription.yaml)" \
  --schema "${BASE[@]}" \
  --message StyleMetadata="$Y/styles-core/styleDescription.yaml"

# The list of styles (styles-core/styles.yaml)
gen ogcapi-styles-list ogcstyles "OGC API - Styles - Part 1: Core (draft), style list (styles-core/styles.yaml)" \
  --schema "$Y/styles-core/styles.yaml" "$Y/styles-core/numberMatched.yaml" "$Y/styles-core/numberReturned.yaml" "${BASE[@]}" \
  --message Styles="$Y/styles-core/styles.yaml"

exit "$STATUS"
