#!/bin/bash
# Regenerate the adapt-* packs from the AgGateway ADAPT Standard JSON schema.
#
# Usage: tools/gen/adapt-run.sh [--check] <ADAPT Standard checkout> <goat-transformers checkout>
#
# <ADAPT Standard checkout>: github.com/AgGateway-ADAPT/Standard at tag 2.0.2 (commit
# 7790bb4611df627b37a443caa623f9b3331f55a2; the script checks); the run reads
# adapt-root-schema.json. MIT License, Copyright (c) 2024 AgGateway Corporation. Not kept in this
# repository; each pack's PROVENANCE.md has the SHA-256.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] <ADAPT Standard> <checkout>" >&2; exit 2; fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=7790bb4611df627b37a443caa623f9b3331f55a2
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "ADAPT Standard is at $got, not $COMMIT" >&2; exit 1; }
SCHEMA="$SRC/adapt-root-schema.json"
LICENSE="MIT License, Copyright (c) 2024 AgGateway Corporation"
SOURCE="https://github.com/AgGateway-ADAPT/Standard at tag 2.0.2, commit $COMMIT, adapt-root-schema.json"
STATUS=0
cd "$W"
# run <format suffix> <JSON pointer of the message> <title>
run() {
  local fmt="adapt-$1" mod
  mod="adapt$(printf '%s' "$1" | tr -d '-')"
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$SCHEMA" --message "$1=$SCHEMA$2" \
      --format "$fmt" --module "$mod" --title "ADAPT Standard 2.0.2: $3" \
      --license "$LICENSE" --source "$SOURCE" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/adapt.md" \
      ${CHECK:+"$CHECK"} > /dev/null; then
    echo "adapt-run: $fmt failed" >&2
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
run root "" "the adapt.json root (catalog and documents)"
for c in brand crop cropZone customDataTypeDefinition device deviceModel farm field fieldBoundary grower \
         guidanceGroup guidancePattern manufacturer party product season plan recommendation workOrder \
         workRecord referenceLayer; do
  kebab=$(printf '%s' "$c" | sed -E 's/([a-z0-9])([A-Z])/\1-\2/g' | tr 'A-Z' 'a-z')
  run "$kebab" "#/\$defs/$c" "the $c component"
done
exit "$STATUS"
