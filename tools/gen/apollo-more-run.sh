#!/bin/bash
# Regenerate the Apollo packs of the second Apollo sweep: per-vehicle chassis details
# (modules/canbus_vehicle), GNSS receiver status and raw observations, radar, camera and
# ultrasonic sensor messages, the point cloud, perception messages and the HD map. One pack
# per message, apollo-<name>, module apollo<name without dashes>. The first 15 Apollo packs
# are written by tools/gen/protobuf-3-run.sh.
#
# Usage: tools/gen/apollo-more-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words
# (tools/gen/notes/apollo-common.md, and apollo-canbus-vehicle.md or apollo-map.md where it applies). The schema files are not kept in the repository; each
# pack's PROVENANCE.md has the license and the SHA-256 of every file it reads.
#
#   <sources>/apollo/<path>   ApolloAuto/apollo d53aa3da47a06a08e6d0cd175d5623a34fa0d6aa
#     https://raw.githubusercontent.com/ApolloAuto/apollo/<commit>/<path>
#     Each run reads the file that defines its envelope and the files it imports, directly
#     or through another (PACKS below). Several canbus_vehicle files define messages of one
#     name in one package, so the runs do not share one file list.
#
# Not generated: the lidar scans (velodyne, hesai, lslidar, robosense, seyond, vanjee, livox),
# the camera images and the microphone audio, whose content is `bytes` packets no transform
# reads; the component, model and driver configurations; the map data checker's service
# messages; the training features and model parameters of prediction. The chassis details of
# the transit and wey vehicle lines are held back: their generated modules do not pass the
# repository's full content check.
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
APOLLO=d53aa3da47a06a08e6d0cd175d5623a34fa0d6aa
APOLLO_LIC="LICENSE at that commit: Apache License, Version 2.0 (Copyright (c) 2018 Apollo Authors); the file headers that carry one: Copyright The Apollo Authors, Apache License, Version 2.0"
# <name>|<envelope>|<files: the envelope's file first, then its imports>
PACKS=(
  "ch|apollo.canbus.Ch|modules/canbus_vehicle/ch/proto/ch.proto"
  "demo|apollo.canbus.Demo|modules/canbus_vehicle/demo/proto/demo.proto"
  "devkit|apollo.canbus.Devkit|modules/canbus_vehicle/devkit/proto/devkit.proto"
  "ge3|apollo.canbus.Ge3|modules/canbus_vehicle/ge3/proto/ge3.proto"
  "gem|apollo.canbus.Gem|modules/canbus_vehicle/gem/proto/gem.proto"
  "lexus|apollo.canbus.Lexus|modules/canbus_vehicle/lexus/proto/lexus.proto"
  "lincoln|apollo.canbus.Lincoln|modules/canbus_vehicle/lincoln/proto/lincoln.proto modules/common_msgs/basic_msgs/vehicle_id.proto modules/common_msgs/basic_msgs/geometry.proto modules/common_msgs/chassis_msgs/chassis.proto modules/common_msgs/basic_msgs/drive_state.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/vehicle_signal.proto modules/common_msgs/basic_msgs/error_code.proto"
  "neolix-edu|apollo.canbus.Neolix_edu|modules/canbus_vehicle/neolix_edu/proto/neolix_edu.proto modules/common_msgs/chassis_msgs/chassis.proto modules/common_msgs/basic_msgs/drive_state.proto modules/common_msgs/basic_msgs/geometry.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/vehicle_id.proto modules/common_msgs/basic_msgs/vehicle_signal.proto modules/common_msgs/basic_msgs/error_code.proto"
  "zhongyun|apollo.canbus.Zhongyun|modules/canbus_vehicle/zhongyun/proto/zhongyun.proto"
  "gnss-status|apollo.drivers.gnss.GnssStatus|modules/drivers/gnss/proto/gnss_status.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "ins-status|apollo.drivers.gnss.InsStatus|modules/drivers/gnss/proto/gnss_status.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "gnss-stream-status|apollo.drivers.gnss.StreamStatus|modules/drivers/gnss/proto/gnss_status.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "gnss-epoch-observation|apollo.drivers.gnss.EpochObservation|modules/common_msgs/sensor_msgs/gnss_raw_observation.proto"
  "gnss-ephemeris|apollo.drivers.gnss.GnssEphemeris|modules/common_msgs/sensor_msgs/gnss_raw_observation.proto"
  "conti-radar|apollo.drivers.ContiRadar|modules/common_msgs/sensor_msgs/conti_radar.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "delphi-esr|apollo.drivers.DelphiESR|modules/common_msgs/sensor_msgs/delphi_esr.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "mobileye|apollo.drivers.Mobileye|modules/common_msgs/sensor_msgs/mobileye.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "nano-radar|apollo.drivers.NanoRadar|modules/common_msgs/sensor_msgs/nano_radar.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "oculii-point-cloud|apollo.drivers.OculiiPointCloud|modules/common_msgs/sensor_msgs/oculii_radar.proto modules/common_msgs/basic_msgs/error_code.proto modules/common_msgs/basic_msgs/header.proto"
  "racobit-radar|apollo.drivers.RacobitRadar|modules/common_msgs/sensor_msgs/racobit_radar.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "radar-obstacles|apollo.drivers.RadarObstacles|modules/common_msgs/sensor_msgs/radar.proto modules/common_msgs/basic_msgs/error_code.proto modules/common_msgs/basic_msgs/geometry.proto modules/common_msgs/basic_msgs/header.proto"
  "radar-point-cloud|apollo.drivers.RadarPointCloud|modules/common_msgs/sensor_msgs/radarpointcloud.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "ultrasonic|apollo.drivers.Ultrasonic|modules/common_msgs/sensor_msgs/ultrasonic_radar.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "smartereye-obstacles|apollo.drivers.SmartereyeObstacles|modules/common_msgs/sensor_msgs/smartereye.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "smartereye-lanemark|apollo.drivers.SmartereyeLanemark|modules/common_msgs/sensor_msgs/smartereye.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "point-cloud|apollo.drivers.PointCloud|modules/common_msgs/sensor_msgs/pointcloud.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "perception-barrier-gate|apollo.perception.PerceptionBarrierGate|modules/common_msgs/perception_msgs/perception_barrier_gate.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "perception-benchmark-frame|apollo.perception.PerceptionBenchmarkFrame|modules/common_msgs/perception_msgs/perception_benchmark.proto modules/common_msgs/basic_msgs/error_code.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/perception_msgs/perception_obstacle.proto modules/common_msgs/basic_msgs/geometry.proto modules/common_msgs/basic_msgs/pnc_point.proto modules/common_msgs/map_msgs/map_lane.proto modules/common_msgs/map_msgs/map_geometry.proto modules/common_msgs/map_msgs/map_id.proto"
  "perception-camera-debug|apollo.perception.camera.CameraDebug|modules/common_msgs/perception_msgs/perception_camera.proto modules/common_msgs/basic_msgs/geometry.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/perception_msgs/perception_obstacle.proto modules/common_msgs/basic_msgs/error_code.proto modules/common_msgs/basic_msgs/pnc_point.proto modules/common_msgs/map_msgs/map_lane.proto modules/common_msgs/map_msgs/map_geometry.proto modules/common_msgs/map_msgs/map_id.proto"
  "perception-lanes|apollo.perception.PerceptionLanes|modules/common_msgs/perception_msgs/perception_lane.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/perception_msgs/perception_camera.proto modules/common_msgs/basic_msgs/error_code.proto modules/common_msgs/basic_msgs/geometry.proto modules/common_msgs/perception_msgs/perception_obstacle.proto modules/common_msgs/basic_msgs/pnc_point.proto modules/common_msgs/map_msgs/map_lane.proto modules/common_msgs/map_msgs/map_geometry.proto modules/common_msgs/map_msgs/map_id.proto"
  "perception-motion-service|apollo.perception.MotionService|modules/perception/common/proto/motion_service.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/error_code.proto"
  "perception-impending-collision-edges|apollo.perception.ImpendingCollisionEdges|modules/perception/common/proto/perception_ultrasonic.proto modules/common_msgs/basic_msgs/header.proto modules/common_msgs/basic_msgs/geometry.proto modules/common_msgs/basic_msgs/error_code.proto"
  "map|apollo.hdmap.Map|modules/common_msgs/map_msgs/map.proto modules/common_msgs/map_msgs/map_clear_area.proto modules/common_msgs/map_msgs/map_crosswalk.proto modules/common_msgs/map_msgs/map_junction.proto modules/common_msgs/map_msgs/map_lane.proto modules/common_msgs/map_msgs/map_overlap.proto modules/common_msgs/map_msgs/map_parking_space.proto modules/common_msgs/map_msgs/map_pnc_junction.proto modules/common_msgs/map_msgs/map_road.proto modules/common_msgs/map_msgs/map_rsu.proto modules/common_msgs/map_msgs/map_signal.proto modules/common_msgs/map_msgs/map_speed_bump.proto modules/common_msgs/map_msgs/map_stop_sign.proto modules/common_msgs/map_msgs/map_yield_sign.proto modules/common_msgs/map_msgs/map_area.proto modules/common_msgs/map_msgs/map_barrier_gate.proto modules/common_msgs/map_msgs/map_geometry.proto modules/common_msgs/map_msgs/map_id.proto modules/common_msgs/basic_msgs/geometry.proto"
)
for spec in "${PACKS[@]}"; do
  IFS='|' read -r name envelope files <<< "$spec"
  proto=()
  for f in $files; do proto+=("$SRC/apollo/$f"); done
  set -- $files
  first="$1"; n="$#"
  notes="$TMP/notes-apollo-$name.md"
  cat "$GEN/notes/apollo-common.md" > "$notes"
  case "$name" in
    ch|demo|devkit|ge3|gem|lexus|lincoln|neolix-edu|zhongyun)
      cat "$GEN/notes/apollo-canbus-vehicle.md" >> "$notes" ;;
    map) cat "$GEN/notes/apollo-map.md" >> "$notes" ;;
  esac
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "${proto[@]}" \
    --envelope "$envelope" --format "apollo-$name" --module "apollo${name//-/}" \
    --source "Apollo protobuf definitions: github.com/ApolloAuto/apollo commit $APOLLO, $first and the files it imports, $n files in all; envelope $envelope; field numbers, names and types only" \
    --source "$APOLLO_LIC" \
    --names-file "$NAMES/apollo-$name.json" \
    --notes-file "$notes"
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "apollo-more-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "apollo-more-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
