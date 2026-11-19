#!/bin/bash
# Regenerate the JSON Schema packs: mds, stac-item, wzdx-device.
# Usage: tools/gen/jsonschema2pack-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds three git checkouts, each at the commit below (the script checks):
#   mds-openapi  https://github.com/openmobilityfoundation/mds-openapi  branch v2.0,
#                commit 0c07bc3d294237dd41c6273f059efb11b8149c66 (CC-BY-4.0)
#   stac-spec    https://github.com/radiantearth/stac-spec  tag v1.1.0,
#                commit ec002bb93dbfa47976822def8f11b2861775b662 (Apache-2.0)
#   wzdx         https://github.com/usdot-jpo-ode/wzdx  tag v4.2,
#                commit 42b98fcdd837e897ae3e208780c45ce61f7fc12a (CC0-1.0)
# The SHA-256 of every schema file read is in each pack's pack.md and PROVENANCE.md.
#
# Writes model/{mds,stac,wzdx}.def, packs/{mds,stac-item,wzdx-device}/ (pack.def, pack.md,
# vectors/gen-*), packs/geojson/vectors/gen-geojson-to-{mds,stac-item,wzdx-device}.json and
# tools/gen/names/{mds,stac-item,wzdx-device}.json. PROVENANCE.md is not generated.
#
# With --check nothing is written: each of the three runs compares what it would write
# with the checkout and its names file, all three runs are made, and the exit status is
# 1 when any file differs. Without it the script stops at the first run that fails.
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

# One run of the generator. The three runs do not read one another's output.
jsonschema2pack() {
  if ! python3 -I "$GEN/jsonschema2pack.py" "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
check() {
  local got
  got="$(git -C "$SRC/$1" rev-parse HEAD)"
  [ "$got" = "$2" ] || { echo "$1 is at $got, not $2" >&2; exit 1; }
}
check mds-openapi 0c07bc3d294237dd41c6273f059efb11b8149c66
check stac-spec ec002bb93dbfa47976822def8f11b2861775b662
check wzdx 42b98fcdd837e897ae3e208780c45ce61f7fc12a
cd "$W"

# MDS 2.0: five data models, one kind each, selected by a member only that model has.
M="$SRC/mds-openapi/models"
jsonschema2pack \
  --schema $(cd "$SRC" && find mds-openapi/models -name '*.yaml' | LC_ALL=C sort | sed "s|^|$SRC/|") \
  --message VehicleStatus="$M/vehicle-status.yaml" --message Trip="$M/trip.yaml" \
  --message Event="$M/event.yaml" --message Telemetry="$M/telemetry.yaml" --message Vehicle="$M/vehicle.yaml" \
  --kind-when VehicleStatus:last_telemetry=present --kind-when Trip:trip_id=present \
  --kind-when Event:event_id=present --kind-when Telemetry:telemetry_id=present \
  --kind-when Vehicle:vehicle_type=present \
  --map '*:device_id=uid' \
  --map Telemetry:timestamp=time_ms --map Telemetry:location.lat=lat \
  --map Telemetry:location.lng=lon --map Telemetry:location.speed=speed_ms \
  --map Event:timestamp=time_ms --map Event:location.lat=lat \
  --map Event:location.lng=lon --map Event:location.speed=speed_ms \
  --map VehicleStatus:last_telemetry.timestamp=time_ms --map VehicleStatus:last_telemetry.location.lat=lat \
  --map VehicleStatus:last_telemetry.location.lng=lon --map VehicleStatus:last_telemetry.location.speed=speed_ms \
  --format mds --module mds \
  --title "Mobility Data Specification (MDS) 2.0 data models (Open Mobility Foundation, mds-openapi)" \
  --license "CC-BY-4.0, Open Mobility Foundation" \
  --source "https://github.com/openmobilityfoundation/mds-openapi at commit 0c07bc3d294237dd41c6273f059efb11b8149c66" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/mds.json" --notes-file "$GEN/notes/mds.md" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input@mds.telemetry_id=0f1e2d3c-4b5a-4968-8776-655443322110"

# STAC Item 1.1.0, a GeoJSON Feature. common.json declares a mistyped $id; the alias
# points the references at the file. The geojson.org schemas are the wire's own structure.
J="$SRC/stac-spec/item-spec/json-schema"
jsonschema2pack \
  --schema $(cd "$SRC" && ls stac-spec/item-spec/json-schema/*.json | LC_ALL=C sort | sed "s|^|$SRC/|") \
  --opaque https://geojson.org/schema/ \
  --alias "https://schemas.stacspec.org/v1.1.0/item-spec/json-schema/common.json=$J/common.json" \
  --message Item="$J/item.json" \
  --map Item:id=uid --map Item:geometry.lon=lon --map Item:geometry.lat=lat --map Item:geometry.alt=hae \
  --map Item:properties.datetime=time_ms \
  --wire geojson --top-level-members id --format stac-item --module stac \
  --title "SpatioTemporal Asset Catalog (STAC) Item 1.1.0 JSON Schema" \
  --license "Apache-2.0, radiantearth/stac-spec" \
  --source "https://github.com/radiantearth/stac-spec at tag v1.1.0, commit ec002bb93dbfa47976822def8f11b2861775b662" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/stac-item.json" --notes-file "$GEN/notes/stac-item.md" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"

# WZDx 4.2 Device Feed: one FieldDeviceFeature, a GeoJSON Feature with a Point geometry.
Z="$SRC/wzdx/schemas/4.2"
jsonschema2pack \
  --schema "$Z/DeviceFeed.json" "$Z/Direction.json" "$Z/BoundingBox.json" "$Z/FeedInfo.json" \
  --opaque https://geojson.org/schema/ \
  --message FieldDevice="$Z/DeviceFeed.json#/definitions/FieldDeviceFeature" \
  --map FieldDevice:id=uid --map FieldDevice:geometry.lon=lon --map FieldDevice:geometry.lat=lat \
  --wire geojson --top-level-members id --format wzdx-device --module wzdx \
  --title "Work Zone Data Exchange (WZDx) 4.2 Device Feed: FieldDeviceFeature JSON Schema" \
  --license "CC0-1.0, U.S. Department of Transportation (usdot-jpo-ode/wzdx)" \
  --source "https://github.com/usdot-jpo-ode/wzdx at tag v4.2, commit 42b98fcdd837e897ae3e208780c45ce61f7fc12a" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/wzdx-device.json" --notes-file "$GEN/notes/wzdx-device.md" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"

exit "$STATUS"
