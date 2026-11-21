#!/bin/bash
# Regenerate the suricata-eve pack: Suricata EVE JSON records, one kind per event type.
#
# Usage: tools/gen/suricata-eve-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/suricata is a checkout of https://github.com/OISF/suricata at tag
# suricata-8.0.8, commit 89d2ac5e371873c32c8acbd7a02170a99c39bb0c (GPL-2.0; the script
# checks the commit). It reads etc/schema.json (sha256
# 960fa690efcbeeca50bc0f3122b449d01c62c2107f8021067b142968e04d7c2d), cuts it into one
# schema per event type with tools/gen/suricata-eve-schemas.py, and runs jsonschema2pack.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
[ "$#" -eq 2 ] || { echo "usage: $0 [--check] <sources> <checkout>" >&2; exit 2; }
SRC="$(cd "$1" && pwd)/suricata"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=89d2ac5e371873c32c8acbd7a02170a99c39bb0c
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "suricata is at $got, not $COMMIT" >&2; exit 1; }
echo "960fa690efcbeeca50bc0f3122b449d01c62c2107f8021067b142968e04d7c2d  $SRC/etc/schema.json" | sha256sum -c --quiet -
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
python3 -I "$GEN/suricata-eve-schemas.py" "$SRC/etc/schema.json" "$TMP"
ARGS=()
for e in alert flow dns http tls fileinfo anomaly stats; do
  ARGS+=(--message "$e=$TMP/$e.json" --kind-when "$e:event_type=$e")
done
cd "$W"
python3 -I "$GEN/jsonschema2pack.py" --schema "$TMP"/*.json "${ARGS[@]}" \
  --format suricata-eve --module suricataeve \
  --title "Suricata EVE JSON records (OISF Suricata etc/schema.json)" \
  --license "GPL-2.0 source (OISF/suricata); layouts restated, no code copied: Apache-2.0" \
  --source "https://github.com/OISF/suricata at tag suricata-8.0.8, commit $COMMIT, etc/schema.json (sha256 960fa690efcbeeca50bc0f3122b449d01c62c2107f8021067b142968e04d7c2d)" \
  --source "Suricata user guide, doc/userguide/output/eve/eve-json-format.rst at the same commit" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/suricata-eve.json" \
  --notes-file "$GEN/notes/suricata-eve.md" \
  ${CHECK:+"$CHECK"} > /dev/null
python3 -I "$GEN/suricata-eve-schemas.py" --provenance "$W" ${CHECK:+"$CHECK"}
[ -n "$CHECK" ] || echo suricata-eve
