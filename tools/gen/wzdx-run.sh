#!/bin/bash
# Regenerate the WZDx feed packs (work zone, device and road restriction feeds, 4.0 to 4.2)
# and the WZDx 4.0 and 4.1 device feature packs. The WZDx 4.2 device feature pack
# (wzdx-device) is made by tools/gen/jsonschema2pack-run.sh.
#
# Usage: tools/gen/wzdx-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/wzdx is a git checkout of https://github.com/usdot-jpo-ode/wzdx at tag v4.2,
# commit 42b98fcdd837e897ae3e208780c45ce61f7fc12a (the script checks); it holds the
# schemas of every 4.x version under schemas/4.0, schemas/4.1 and schemas/4.2. CC0-1.0.
# The SHA-256 of every schema file read is in each pack's pack.md.
#
# Writes model/wzdx*.def, packs/wzdx-*-feed*/ and packs/wzdx-device-4.{0,1}/ (pack.def,
# pack.md, vectors/gen-*), packs/geojson/vectors/gen-geojson-to-wzdx-device-4.{0,1}.json
# and tools/gen/names/<format>.json. PROVENANCE.md is not generated. With --check nothing
# is written (jsonschema2pack --check per run); every run is made and the exit status is 1
# when any file differs.
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
COMMIT=42b98fcdd837e897ae3e208780c45ce61f7fc12a
got="$(git -C "$SRC/wzdx" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "wzdx is at $got, not $COMMIT" >&2; exit 1; }
Z="$SRC/wzdx/schemas"
STATUS=0
LICENSE="CC0-1.0, U.S. Department of Transportation (usdot-jpo-ode/wzdx)"
SOURCE="https://github.com/usdot-jpo-ode/wzdx at tag v4.2, commit $COMMIT"
cd "$W"

# wzdx <format> <module> <version> <message file[#pointer]> <wire> <title> [options...]
wzdx() {
  local fmt="$1" mod="$2" ver="$3" msg="$4" wire="$5" title="$6"
  shift 6
  if ! python3 -I "$GEN/jsonschema2pack.py" \
      --schema $(ls "$Z/$ver"/*.json | LC_ALL=C sort) --opaque https://geojson.org/schema/ \
      --message "Feed=$Z/$ver/$msg" --wire "$wire" \
      --format "$fmt" --module "$mod" --title "$title" --license "$LICENSE" --source "$SOURCE" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
T="time_ms"
wzdx wzdx-work-zone-feed wzdxwzf 4.2 WorkZoneFeed.json json \
  "Work Zone Data Exchange (WZDx) 4.2 Work Zone Feed JSON Schema" --map Feed:feed_info.update_date=$T
wzdx wzdx-work-zone-feed-4.1 wzdxwzf41 4.1 WorkZoneFeed.json json \
  "Work Zone Data Exchange (WZDx) 4.1 Work Zone Feed JSON Schema" --map Feed:feed_info.update_date=$T
wzdx wzdx-work-zone-feed-4.0 wzdxwzf40 4.0 WZDxFeed.json json \
  "Work Zone Data Exchange (WZDx) 4.0 WZDx Feed (work zone feed) JSON Schema" --map Feed:road_event_feed_info.update_date=$T
wzdx wzdx-device-feed wzdxdevf 4.2 DeviceFeed.json json \
  "Work Zone Data Exchange (WZDx) 4.2 Device Feed JSON Schema" --map Feed:feed_info.update_date=$T
wzdx wzdx-device-feed-4.1 wzdxdevf41 4.1 DeviceFeed.json json \
  "Work Zone Data Exchange (WZDx) 4.1 Device Feed JSON Schema" --map Feed:feed_info.update_date=$T
wzdx wzdx-device-feed-4.0 wzdxdevf40 4.0 SwzDeviceFeed.json json \
  "Work Zone Data Exchange (WZDx) 4.0 Smart Work Zone Device Feed JSON Schema" --map Feed:feed_info.update_date=$T
wzdx wzdx-road-restriction-feed-4.0 wzdxrrf40 4.0 RoadRestrictionFeed.json json \
  "Work Zone Data Exchange (WZDx) 4.0 Road Restriction Feed JSON Schema" --map Feed:feed_info.update_date=$T

XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
DEV="--top-level-members id --map Feed:id=uid --map Feed:geometry.lon=lon --map Feed:geometry.lat=lat --cross $XG"
# shellcheck disable=SC2086
wzdx wzdx-device-4.1 wzdxdev41 4.1 "DeviceFeed.json#/definitions/FieldDeviceFeature" geojson \
  "Work Zone Data Exchange (WZDx) 4.1 Device Feed: FieldDeviceFeature JSON Schema" $DEV
# shellcheck disable=SC2086
wzdx wzdx-device-4.0 wzdxdev40 4.0 "SwzDeviceFeed.json#/definitions/FieldDeviceFeature" geojson \
  "Work Zone Data Exchange (WZDx) 4.0 Smart Work Zone Device Feed: FieldDeviceFeature JSON Schema" $DEV

exit "$STATUS"
