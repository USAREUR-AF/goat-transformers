#!/bin/bash
# Regenerate the WMO WIS2 Notification Message pack (wis2-notification), a GeoJSON Feature.
#
# Usage: tools/gen/wis2-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/wis2-notification-message is a git checkout of
# https://github.com/wmo-im/wis2-notification-message at tag 1.3.0, commit
# 64a79fc3ec92584054c4194d2862ca71b9a3d4df (the script checks). The script reads
# schemas/wis2-notification-message-bundled.json. The repository has no LICENSE file and
# the schema states no licence; the standard's front matter states the copyright of the
# World Meteorological Organization. The pack is labelled LicenseRef-unstated.
#
# Writes model/wis2.def, packs/wis2-notification/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-wis2-notification.json and
# tools/gen/names/wis2-notification.json. PROVENANCE.md is not generated. With --check
# nothing is written and the exit status is 1 when any file differs.
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
COMMIT=64a79fc3ec92584054c4194d2862ca71b9a3d4df
got="$(git -C "$SRC/wis2-notification-message" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "wis2-notification-message is at $got, not $COMMIT" >&2; exit 1; }
F="$SRC/wis2-notification-message/schemas/wis2-notification-message-bundled.json"
cd "$W"

M=Notification
python3 -I "$GEN/jsonschema2pack.py" --schema "$F" --message "$M=$F" \
  --wire geojson --top-level-members id \
  --map $M:id=uid --map $M:geometry.lon=lon --map $M:geometry.lat=lat --map $M:properties.datetime=time_ms \
  --evidence "$M:id=a UUID that identifies the notification message" \
  --evidence "$M:properties.datetime=the time of the data the notification announces, an RFC 3339 date-time" \
  --format wis2-notification --module wis2 \
  --title "WMO WIS2 Notification Message 1.3.0 JSON Schema (bundled)" \
  --license "LicenseRef-unstated: no licence stated; copyright World Meteorological Organization" \
  --source "https://github.com/wmo-im/wis2-notification-message at tag 1.3.0, commit $COMMIT" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/wis2-notification.json" \
  --notes-file "$GEN/notes/wis2-notification.md" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input" \
  ${CHECK:+"$CHECK"}
