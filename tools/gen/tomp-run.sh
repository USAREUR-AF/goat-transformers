#!/bin/bash
# Regenerate the TOMP-API packs: tomp-<schema>, the message bodies of TOMP-API 2.0.0.
#
# Usage: tools/gen/tomp-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds a git checkout of https://github.com/TOMP-WG/TOMP-API at tag v2.0, commit
# 6afdc97e243daac977adaff9adb3a47c20de1145 (Apache-2.0; the script checks the commit). Every
# pack reads openapi.json, the merged OpenAPI 3.0 document.
#
# Shared keys (tools/gen/notes/tomp.md): supportTicket id = uid and timestamp = time_ms; the
# other messages are GeoJSON FeatureCollections whose features are list items, so nothing else.
#
# Writes model/tomp*.def, packs/tomp-*/ (pack.def, pack.md, vectors/gen-*, PROVENANCE.md through
# tools/gen/jsonmore-provenance.py) and tools/gen/names/tomp-*.json.
#
# With --check nothing is written; every run is made and the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] <sources> <goat-transformers checkout>" >&2; exit 2; fi
SRC="$(cd "$1" && pwd)/TOMP-API"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=6afdc97e243daac977adaff9adb3a47c20de1145
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "TOMP-API is at $got, not $COMMIT" >&2; exit 1; }
cd "$W"
STATUS=0
F="$SRC/openapi.json"

tomp_pack() {
  local fmt="$1" name="$2"; shift 2
  local module="$(echo "$fmt" | tr -d '-')"
  local args=(--schema "$F" --message "$name=$F#/components/schemas/$name" --format "$fmt" --module "$module"
    --title "TOMP-API 2.0.0 $name (OpenAPI, TOMP-WG/TOMP-API)" --license "Apache-2.0, TOMP-WG/TOMP-API"
    --source "https://github.com/TOMP-WG/TOMP-API at tag v2.0, commit $COMMIT, openapi.json#/components/schemas/$name"
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/tomp.md" "$@")
  if ! python3 -I "$GEN/jsonschema2pack.py" "${args[@]}" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1; [ -n "$CHECK" ] || { echo "tomp-run: $fmt failed" >&2; exit 1; }
  fi
  [ -n "$CHECK" ] || echo "$fmt"
}

tomp_pack tomp-package package
tomp_pack tomp-search-offer-request searchOfferRequest
tomp_pack tomp-offer-collection offerCollection
tomp_pack tomp-asset-collection assetCollection
tomp_pack tomp-travel-documents travelDocuments
tomp_pack tomp-support-ticket supportTicket \
  --map "supportTicket:id=uid" --evidence "supportTicket:id=openapi.json: the ticket's identifier, given when the ticket is created" \
  --map "supportTicket:timestamp=time_ms" --evidence "supportTicket:timestamp=openapi.json: when the support request was reported, a date-time"
tomp_pack tomp-customer-account customerAccount
python3 -I "$GEN/jsonmore-provenance.py" tomp ${CHECK:+"$CHECK"} "$SRC" "$W" || STATUS=1
exit "$STATUS"
