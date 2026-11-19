#!/bin/bash
# Regenerate the protobuf packs of the third public family: 15 Apollo message packs
# (apollo-*), 8 KUKSA.val API packs (kuksa-val-v1-*, kuksa-val-v2-*) and 4 Tesla Fleet
# Telemetry record packs (tesla-fleet-*).
#
# Usage: tools/gen/protobuf-3-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words (tools/gen/notes/).
# The schema files are not kept in the repository; each pack's PROVENANCE.md has the
# license and the SHA-256 of every file. Each file is
# https://raw.githubusercontent.com/<repository>/<commit>/<path>:
#
#   <sources>/apollo/<path>   ApolloAuto/apollo d53aa3da47a06a08e6d0cd175d5623a34fa0d6aa
#     the 53 files of modules/common_msgs listed in APOLLO_FILES below: the files that
#     define the 15 envelopes and every file they import, directly or through another.
#   <sources>/kuksa/kuksa/val/{v1,v2}/{val,types}.proto
#     eclipse-kuksa/kuksa-proto 28bf76ae57085dad425eedd95bc7bd442e1314a7 (the commit the
#     submodule `proto` of eclipse-kuksa/kuksa-databroker
#     fce05ac2cabca7db68ef454bcd81ac5b948fb2c4 points at)
#   <sources>/tesla/protos/{vehicle_alert,vehicle_connectivity,vehicle_error,vehicle_metric}.proto
#     teslamotors/fleet-telemetry bb7c8a931e46da3b3eb6d20a67541c8f755f1ee6
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
P2P=(python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0)

# ---- Apollo -------------------------------------------------------------------------
APOLLO=d53aa3da47a06a08e6d0cd175d5623a34fa0d6aa
APOLLO_FILES=(
  "modules/common_msgs/basic_msgs/drive_state.proto"
  "modules/common_msgs/basic_msgs/error_code.proto"
  "modules/common_msgs/basic_msgs/geometry.proto"
  "modules/common_msgs/basic_msgs/header.proto"
  "modules/common_msgs/basic_msgs/pnc_point.proto"
  "modules/common_msgs/basic_msgs/vehicle_id.proto"
  "modules/common_msgs/basic_msgs/vehicle_signal.proto"
  "modules/common_msgs/chassis_msgs/chassis.proto"
  "modules/common_msgs/control_msgs/control_cmd.proto"
  "modules/common_msgs/control_msgs/input_debug.proto"
  "modules/common_msgs/control_msgs/pad_msg.proto"
  "modules/common_msgs/dreamview_msgs/chart.proto"
  "modules/common_msgs/localization_msgs/localization.proto"
  "modules/common_msgs/localization_msgs/localization_status.proto"
  "modules/common_msgs/localization_msgs/pose.proto"
  "modules/common_msgs/map_msgs/map_area.proto"
  "modules/common_msgs/map_msgs/map_barrier_gate.proto"
  "modules/common_msgs/map_msgs/map_clear_area.proto"
  "modules/common_msgs/map_msgs/map_crosswalk.proto"
  "modules/common_msgs/map_msgs/map_geometry.proto"
  "modules/common_msgs/map_msgs/map_id.proto"
  "modules/common_msgs/map_msgs/map_junction.proto"
  "modules/common_msgs/map_msgs/map_lane.proto"
  "modules/common_msgs/map_msgs/map_overlap.proto"
  "modules/common_msgs/map_msgs/map_parking_space.proto"
  "modules/common_msgs/map_msgs/map_pnc_junction.proto"
  "modules/common_msgs/map_msgs/map.proto"
  "modules/common_msgs/map_msgs/map_road.proto"
  "modules/common_msgs/map_msgs/map_rsu.proto"
  "modules/common_msgs/map_msgs/map_signal.proto"
  "modules/common_msgs/map_msgs/map_speed_bump.proto"
  "modules/common_msgs/map_msgs/map_stop_sign.proto"
  "modules/common_msgs/map_msgs/map_yield_sign.proto"
  "modules/common_msgs/perception_msgs/perception_obstacle.proto"
  "modules/common_msgs/perception_msgs/traffic_light_detection.proto"
  "modules/common_msgs/planning_msgs/decision.proto"
  "modules/common_msgs/planning_msgs/navigation.proto"
  "modules/common_msgs/planning_msgs/planning_internal.proto"
  "modules/common_msgs/planning_msgs/planning.proto"
  "modules/common_msgs/planning_msgs/sl_boundary.proto"
  "modules/common_msgs/prediction_msgs/feature.proto"
  "modules/common_msgs/prediction_msgs/lane_graph.proto"
  "modules/common_msgs/prediction_msgs/prediction_obstacle.proto"
  "modules/common_msgs/prediction_msgs/prediction_point.proto"
  "modules/common_msgs/prediction_msgs/scenario.proto"
  "modules/common_msgs/routing_msgs/geometry.proto"
  "modules/common_msgs/routing_msgs/poi.proto"
  "modules/common_msgs/routing_msgs/routing.proto"
  "modules/common_msgs/sensor_msgs/gnss_best_pose.proto"
  "modules/common_msgs/sensor_msgs/gnss.proto"
  "modules/common_msgs/sensor_msgs/heading.proto"
  "modules/common_msgs/sensor_msgs/imu.proto"
  "modules/common_msgs/sensor_msgs/ins.proto"
)
APOLLO_PROTO=()
for f in "${APOLLO_FILES[@]}"; do APOLLO_PROTO+=("$SRC/apollo/$f"); done
APOLLO_LIC="LICENSE at that commit: Apache License, Version 2.0 (Copyright (c) 2018 Apollo Authors); the file headers that carry one: Copyright The Apollo Authors, Apache License, Version 2.0"
# <format suffix>:<envelope>; the module is `apollo` and the suffix without dashes.
APOLLO_PACKS=(
  gnss:apollo.drivers.gnss.Gnss
  ins:apollo.drivers.gnss.Ins
  gnss-best-pose:apollo.drivers.gnss.GnssBestPose
  heading:apollo.drivers.gnss.Heading
  imu:apollo.drivers.gnss.Imu
  localization:apollo.localization.LocalizationEstimate
  localization-status:apollo.localization.LocalizationStatus
  perception-obstacles:apollo.perception.PerceptionObstacles
  traffic-light-detection:apollo.perception.TrafficLightDetection
  prediction-obstacles:apollo.prediction.PredictionObstacles
  planning-trajectory:apollo.planning.ADCTrajectory
  chassis:apollo.canbus.Chassis
  control-command:apollo.control.ControlCommand
  routing-request:apollo.routing.RoutingRequest
  routing-response:apollo.routing.RoutingResponse
)
for pair in "${APOLLO_PACKS[@]}"; do
  name="${pair%%:*}"; envelope="${pair#*:}"
  notes="$TMP/notes-apollo-$name.md"
  cat "$GEN/notes/apollo-common.md" > "$notes"
  EXTRA=()
  case "$name" in
    gnss)
      cat "$GEN/notes/apollo-gnss.md" >> "$notes"
      EXTRA=(--map 4.1=lon --map 4.2=lat --map 4.3=hae
             --map 5.1=track.sigma_east_m --map 5.2=track.sigma_north_m --map 5.3=track.sigma_up_m
             --map 6.1=track.vel_east_ms --map 6.2=track.vel_north_ms --map 6.3=track.vel_up_ms
             --cross-text "$ROOT/packs/geojson/pack.def"
             --cross-omit 5.1 --cross-omit 5.2 --cross-omit 5.3 --cross-omit 6.1 --cross-omit 6.2) ;;
    ins)
      cat "$GEN/notes/apollo-ins.md" >> "$notes"
      EXTRA=(--map 4.1=lon --map 4.2=lat --map 4.3=hae
             --map 6.1=track.vel_east_ms --map 6.2=track.vel_north_ms --map 6.3=track.vel_up_ms
             --cross-text "$ROOT/packs/geojson/pack.def" --cross-omit 6.1 --cross-omit 6.2) ;;
    gnss-best-pose)
      cat "$GEN/notes/apollo-gnss-best-pose.md" >> "$notes"
      EXTRA=(--map 5=lat --map 6=lon
             --map 10=track.sigma_north_m --map 11=track.sigma_east_m --map 12=track.sigma_up_m
             --const gnss_best_pose:9=61
             --cross-text "$ROOT/packs/geojson/pack.def"
             --cross-omit 10 --cross-omit 11 --cross-omit 12) ;;
  esac
  "${P2P[@]}" \
    --proto "${APOLLO_PROTO[@]}" \
    --envelope "$envelope" --format "apollo-$name" --module "apollo${name//-/}" \
    --source "Apollo common_msgs protobuf definitions: github.com/ApolloAuto/apollo commit $APOLLO, modules/common_msgs (the 53 files tools/gen/protobuf-3-run.sh lists); envelope $envelope; field numbers, names and types only" \
    --source "$APOLLO_LIC" \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    --names-file "$NAMES/apollo-$name.json" \
    --notes-file "$notes"
done

# ---- KUKSA.val --------------------------------------------------------------------------
KUKSA=28bf76ae57085dad425eedd95bc7bd442e1314a7
K="$SRC/kuksa/kuksa/val"
KUKSA_PACKS=(
  v1:get-response:GetResponse v1:set-request:SetRequest v1:subscribe-response:SubscribeResponse
  v2:get-value-response:GetValueResponse v2:get-values-response:GetValuesResponse
  v2:publish-value-request:PublishValueRequest v2:actuate-request:ActuateRequest
  v2:list-metadata-response:ListMetadataResponse
)
for spec in "${KUKSA_PACKS[@]}"; do
  IFS=: read -r ver name envelope <<< "$spec"
  "${P2P[@]}" \
    --proto "$K/$ver/val.proto" "$K/$ver/types.proto" \
    --envelope "kuksa.val.$ver.$envelope" --format "kuksa-val-$ver-$name" --module "kuksaval$ver${name//-/}" \
    --source "KUKSA.val API protobuf definitions: github.com/eclipse-kuksa/kuksa-proto commit $KUKSA, kuksa/val/$ver/val.proto and types.proto; envelope kuksa.val.$ver.$envelope; field numbers, names and types only" \
    --source "File headers at that commit: Copyright (c) Contributors to the Eclipse Foundation; Apache License 2.0 (SPDX-License-Identifier: Apache-2.0)" \
    --names-file "$NAMES/kuksa-val-$ver-$name.json" \
    --notes-file "$GEN/notes/kuksa.md"
done

# ---- Tesla Fleet Telemetry records ---------------------------------------------------------
TESLA=bb7c8a931e46da3b3eb6d20a67541c8f755f1ee6
TESLA_PACKS=(
  alerts:vehicle_alert:telemetry.vehicle_alerts.VehicleAlerts
  connectivity:vehicle_connectivity:telemetry.vehicle_connectivity.VehicleConnectivity
  errors:vehicle_error:telemetry.vehicle_error.VehicleErrors
  metrics:vehicle_metric:telemetry.vehicle_metrics.VehicleMetrics
)
for spec in "${TESLA_PACKS[@]}"; do
  IFS=: read -r name file envelope <<< "$spec"
  "${P2P[@]}" \
    --proto "$SRC/tesla/protos/$file.proto" \
    --envelope "$envelope" --format "tesla-fleet-$name" --module "teslafleet$name" \
    --source "Tesla Fleet Telemetry $file.proto: github.com/teslamotors/fleet-telemetry commit $TESLA, file protos/$file.proto; field numbers, names and types only" \
    --source "LICENSE at that commit: Apache License, Version 2.0" \
    --names-file "$NAMES/tesla-fleet-$name.json" \
    --notes-file "$GEN/notes/tesla-records.md"
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "protobuf-3-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "protobuf-3-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
