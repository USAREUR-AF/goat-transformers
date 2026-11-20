#!/bin/bash
# Regenerate the osi-* packs: one pack per top-level message of ASAM OSI (Open Simulation
# Interface) in its protobuf form, release v3.8.0.
#
# Usage: tools/gen/osi-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words (tools/gen/notes/).
#
# <sources> holds the files of github.com/OpenSimulationInterface/open-simulation-interface
# at tag v3.8.0 (commit 083481d67cd7abec49302f6df42fc8ab229bd075), each
# https://raw.githubusercontent.com/OpenSimulationInterface/open-simulation-interface/<commit>/<name>:
# the 31 osi_*.proto files, osi_version.proto.in and VERSION. They are not kept in the
# repository; each pack's PROVENANCE.md has the licence (LICENSE: MPL-2.0) and their SHA-256.
# osi_version.proto is made here from osi_version.proto.in and VERSION, as the project's
# CMakeLists.txt does with configure_file.
set -euo pipefail
CHECK=0
if [ "${1:-}" = "--check" ]; then
  CHECK=1
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <checkout> <sources>" >&2
  exit 2
fi
CHECKOUT="$(cd "$1" && pwd)"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ROOT="$CHECKOUT"
NAMES="$GEN/names"
if [ "$CHECK" = 1 ]; then
  ROOT="$TMP/checkout"
  NAMES="$ROOT/tools/gen/names"
  mkdir -p "$ROOT/tools/gen"
  cp -R "$CHECKOUT/model" "$CHECKOUT/packs" "$ROOT/"
  cp -R "$GEN/names" "$NAMES"
fi
TAG=v3.8.0
COMMIT=083481d67cd7abec49302f6df42fc8ab229bd075
mkdir -p "$TMP/proto"
cp "$SRC"/osi_*.proto "$TMP/proto/"
major=$(sed -n 's/^VERSION_MAJOR *= *\([0-9]*\).*/\1/p' "$SRC/VERSION")
minor=$(sed -n 's/^VERSION_MINOR *= *\([0-9]*\).*/\1/p' "$SRC/VERSION")
patch=$(sed -n 's/^VERSION_PATCH *= *\([0-9]*\).*/\1/p' "$SRC/VERSION")
sed -e "s/@VERSION_MAJOR@/$major/; s/@VERSION_MINOR@/$minor/; s/@VERSION_PATCH@/$patch/" \
  "$SRC/osi_version.proto.in" > "$TMP/proto/osi_version.proto"
PROTO=("$TMP"/proto/*.proto)
# <format suffix>:<envelope>
PACKS=(sensor-view:SensorView sensor-view-configuration:SensorViewConfiguration sensor-data:SensorData
       ground-truth:GroundTruth traffic-update:TrafficUpdate traffic-command:TrafficCommand
       traffic-command-update:TrafficCommandUpdate host-vehicle-data:HostVehicleData
       motion-request:MotionRequest streaming-update:StreamingUpdate
       sensor-data-series:SensorDataSeries sensor-data-series-list:SensorDataSeriesList)
for spec in "${PACKS[@]}"; do
  name="${spec%%:*}"; env="${spec#*:}"
  notes="$TMP/notes-$name.md"
  cat "$GEN/notes/osi.md" > "$notes"
  EXTRA=()
  case "$env" in
    HostVehicleData)
      cat "$GEN/notes/osi-host-vehicle.md" >> "$notes"
      EXTRA=(--map 8.3.2=lat --map 8.3.1=lon --cross-text "$ROOT/packs/geojson/pack.def") ;;
    SensorView)
      cat "$GEN/notes/osi-host-vehicle.md" >> "$notes"
      EXTRA=(--map 6.8.3.2=lat --map 6.8.3.1=lon --cross-text "$ROOT/packs/geojson/pack.def") ;;
  esac
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "${PROTO[@]}" \
    --envelope "osi3.$env" --format "osi-$name" --module "osi${name//-/}" \
    --source "ASAM OSI $TAG protobuf definitions: github.com/OpenSimulationInterface/open-simulation-interface commit $COMMIT (31 osi_*.proto files and osi_version.proto made from osi_version.proto.in and VERSION); envelope osi3.$env; field numbers, names and types only" \
    --source "LICENSE at that commit: Copyright (C) 2016 BMW AG; Mozilla Public License, v. 2.0" \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    --names-file "$NAMES/osi-$name.json" \
    --notes-file "$notes"
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "osi-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "osi-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
