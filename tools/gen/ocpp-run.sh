#!/bin/bash
# Regenerate the OCPP packs: one pack per message payload of OCPP 1.6 (JSON) and of
# OCPP 2.0.1, requests and responses.
#
# Usage: tools/gen/ocpp-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/ocpp is a git checkout of https://github.com/mobilityhouse/ocpp at tag 2.1.0,
# commit 91f4f89140a2198dc5a300cfea88d947ac91ae28 (the script checks). That library
# carries copies of the Open Charge Alliance's JSON schemas: ocpp/v16/schemas (OCPP 1.6
# JSON) and ocpp/v201/schemas (OCPP 2.0.1). The Alliance publishes the schemas with the
# specification at no charge after an account registration. The schema files state no
# licence (the library's own MIT licence covers its code, not the Alliance's schemas).
# The packs are labelled LicenseRef-unstated.
#
# An OCPP-J call is a JSON array [type, id, action, payload]; the json wire reads one
# object, so each pack is the payload of one action, and the array frame is not mapped.
# Pack names: ocpp16-<action>[-response], ocpp201-<action>-request|-response, the
# action in lower case with hyphens between its words.
#
# Writes model/ocpp*.def, packs/ocpp16-*/ and packs/ocpp201-*/ (pack.def, pack.md,
# vectors/gen-*) and tools/gen/names/ocpp*.json. PROVENANCE.md is not generated. With
# --check nothing is written (jsonschema2pack --check per run); every run is made and the
# exit status is 1 when any file differs.
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
COMMIT=91f4f89140a2198dc5a300cfea88d947ac91ae28
got="$(git -C "$SRC/ocpp" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "ocpp is at $got, not $COMMIT" >&2; exit 1; }
STATUS=0
LICENSE="LicenseRef-unstated: Open Charge Alliance schemas, no licence stated in the files"
SOURCE="https://github.com/mobilityhouse/ocpp at tag 2.1.0, commit $COMMIT (copies of the Open Charge Alliance JSON schemas)"
cd "$W"

# ocpp <prefix> <version text> <dir> <file name without .json>
ocpp() {
  local pre="$1" ver="$2" dir="$3" name="$4" fmt mod
  fmt="$pre-$(printf '%s' "$name" | sed -E 's/([a-z0-9])([A-Z])/\1-\2/g; s/([A-Z]+)([A-Z][a-z])/\1-\2/g' | tr 'A-Z' 'a-z')"
  mod="$pre$(printf '%s' "$name" | tr 'A-Z' 'a-z')"
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$dir/$name.json" \
      --message "$name=$dir/$name.json" \
      --format "$fmt" --module "$mod" --title "OCPP $ver JSON schema $name.json (Open Charge Alliance)" \
      --license "$LICENSE" --source "$SOURCE" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/ocpp.md" \
      ${CHECK:+"$CHECK"} > /dev/null; then
    echo "ocpp-run: $fmt failed" >&2
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

for v in 16 201; do
  D="$SRC/ocpp/ocpp/v$v/schemas"
  case $v in 16) VER=1.6 ;; 201) VER=2.0.1 ;; esac
  for f in $(cd "$D" && ls *.json | LC_ALL=C sort); do
    ocpp "ocpp$v" "$VER" "$D" "${f%.json}"
  done
done

exit "$STATUS"
