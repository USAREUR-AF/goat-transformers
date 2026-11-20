#!/bin/bash
# Regenerate the mavsdk-* packs: one pack per subscription response of a MAVSDK plugin
# (each `Subscribe…` call of a plugin's gRPC service and the message it streams), in its
# protobuf form.
#
# Usage: tools/gen/mavsdk-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words (tools/gen/notes/).
#
# <sources>/protos/<plugin>/<plugin>.proto and <sources>/protos/mavsdk_options.proto: files of
# github.com/mavlink/MAVSDK-Proto commit df90b7ebba3c9c73d2e43c87885709fd34c7eb25, each
# https://raw.githubusercontent.com/mavlink/MAVSDK-Proto/<commit>/protos/<path>.
# The repository states no licence (no licence file, no licence line in a schema file, none
# in the repository's metadata): the packs are labelled LicenseRef-unstated. MAVSDK, which
# pins this repository as a submodule, is BSD-3-Clause. The files are not kept in this
# repository; each pack's PROVENANCE.md has the SHA-256 of the files its run reads.
# google/protobuf/descriptor.proto, imported by mavsdk_options.proto for its custom
# options only, is not needed (the generator ignores that import).
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
COMMIT=df90b7ebba3c9c73d2e43c87885709fd34c7eb25
# <plugin>:<response message>:<pack name>
PACKS=(
  action_server:ArmDisarmResponse:mavsdk-action-server-arm-disarm
  action_server:FlightModeChangeResponse:mavsdk-action-server-flight-mode-change
  action_server:LandResponse:mavsdk-action-server-land
  action_server:RebootResponse:mavsdk-action-server-reboot
  action_server:ShutdownResponse:mavsdk-action-server-shutdown
  action_server:TakeoffResponse:mavsdk-action-server-takeoff
  action_server:TerminateResponse:mavsdk-action-server-terminate
  arm_authorizer_server:ArmAuthorizationResponse:mavsdk-arm-authorizer-server-arm-authorization
  calibration:CalibrateAccelerometerResponse:mavsdk-calibration-calibrate-accelerometer
  calibration:CalibrateGimbalAccelerometerResponse:mavsdk-calibration-calibrate-gimbal-accelerometer
  calibration:CalibrateGyroResponse:mavsdk-calibration-calibrate-gyro
  calibration:CalibrateLevelHorizonResponse:mavsdk-calibration-calibrate-level-horizon
  calibration:CalibrateMagnetometerResponse:mavsdk-calibration-calibrate-magnetometer
  camera:CameraListResponse:mavsdk-camera-camera-list
  camera:CaptureInfoResponse:mavsdk-camera-capture-info
  camera:CurrentSettingsResponse:mavsdk-camera-current-settings
  camera:ModeResponse:mavsdk-camera-mode
  camera:PossibleSettingOptionsResponse:mavsdk-camera-possible-setting-options
  camera_server:CaptureStatusResponse:mavsdk-camera-server-capture-status
  camera_server:FocusAutoContinuousResponse:mavsdk-camera-server-focus-auto-continuous
  camera_server:FocusAutoResponse:mavsdk-camera-server-focus-auto
  camera_server:FocusAutoSingleResponse:mavsdk-camera-server-focus-auto-single
  camera_server:FocusInStartResponse:mavsdk-camera-server-focus-in-start
  camera_server:FocusInStepResponse:mavsdk-camera-server-focus-in-step
  camera_server:FocusMetersResponse:mavsdk-camera-server-focus-meters
  camera_server:FocusOutStartResponse:mavsdk-camera-server-focus-out-start
  camera_server:FocusOutStepResponse:mavsdk-camera-server-focus-out-step
  camera_server:FocusRangeResponse:mavsdk-camera-server-focus-range
  camera_server:FocusStopResponse:mavsdk-camera-server-focus-stop
  camera_server:FormatStorageResponse:mavsdk-camera-server-format-storage
  camera_server:ResetSettingsResponse:mavsdk-camera-server-reset-settings
  camera_server:SetModeResponse:mavsdk-camera-server-set-mode
  camera_server:StartVideoResponse:mavsdk-camera-server-start-video
  camera_server:StartVideoStreamingResponse:mavsdk-camera-server-start-video-streaming
  camera_server:StopVideoResponse:mavsdk-camera-server-stop-video
  camera_server:StopVideoStreamingResponse:mavsdk-camera-server-stop-video-streaming
  camera_server:StorageInformationResponse:mavsdk-camera-server-storage-information
  camera_server:TakePhotoResponse:mavsdk-camera-server-take-photo
  camera_server:TrackingOffCommandResponse:mavsdk-camera-server-tracking-off-command
  camera_server:TrackingPointCommandResponse:mavsdk-camera-server-tracking-point-command
  camera_server:TrackingRectangleCommandResponse:mavsdk-camera-server-tracking-rectangle-command
  camera_server:ZoomInStartResponse:mavsdk-camera-server-zoom-in-start
  camera_server:ZoomOutStartResponse:mavsdk-camera-server-zoom-out-start
  camera_server:ZoomRangeResponse:mavsdk-camera-server-zoom-range
  camera_server:ZoomStopResponse:mavsdk-camera-server-zoom-stop
  camera:StorageResponse:mavsdk-camera-storage
  camera:VideoStreamInfoResponse:mavsdk-camera-video-stream-info
  component_metadata:MetadataAvailableResponse:mavsdk-component-metadata-metadata-available
  core:ConnectionStateResponse:mavsdk-core-connection-state
  events:EventsResponse:mavsdk-events-events
  events:HealthAndArmingChecksResponse:mavsdk-events-health-and-arming-checks
  ftp:DownloadResponse:mavsdk-ftp-download
  ftp:UploadResponse:mavsdk-ftp-upload
  gimbal:AttitudeResponse:mavsdk-gimbal-attitude
  gimbal:ControlStatusResponse:mavsdk-gimbal-control-status
  gimbal:GimbalListResponse:mavsdk-gimbal-gimbal-list
  info:FlightInformationResponse:mavsdk-info-flight-information
  log_files:DownloadLogFileResponse:mavsdk-log-files-download-log-file
  log_streaming:LogStreamingRawResponse:mavsdk-log-streaming-log-streaming-raw
  mavlink_direct:MessageResponse:mavsdk-mavlink-direct-message
  mavlink_direct_server:CommandResponse:mavsdk-mavlink-direct-server-command
  mavlink_direct_server:MessageResponse:mavsdk-mavlink-direct-server-message
  mission:DownloadMissionWithProgressResponse:mavsdk-mission-download-mission-with-progress
  mission:MissionProgressResponse:mavsdk-mission-mission-progress
  mission_raw:MissionChangedResponse:mavsdk-mission-raw-mission-changed
  mission_raw:MissionProgressResponse:mavsdk-mission-raw-mission-progress
  mission_raw_server:ClearAllResponse:mavsdk-mission-raw-server-clear-all
  mission_raw_server:CurrentItemChangedResponse:mavsdk-mission-raw-server-current-item-changed
  mission_raw_server:IncomingMissionResponse:mavsdk-mission-raw-server-incoming-mission
  mission_raw:UploadMissionWithProgressResponse:mavsdk-mission-raw-upload-mission-with-progress
  mission:UploadMissionWithProgressResponse:mavsdk-mission-upload-mission-with-progress
  modes:AvailableModesResponse:mavsdk-modes-available-modes
  modes:CurrentModeResponse:mavsdk-modes-current-mode
  modes_server:ModeRequestedResponse:mavsdk-modes-server-mode-requested
  param_server:ChangedParamCustomResponse:mavsdk-param-server-changed-param-custom
  param_server:ChangedParamFloatResponse:mavsdk-param-server-changed-param-float
  param_server:ChangedParamIntResponse:mavsdk-param-server-changed-param-int
  shell:ReceiveResponse:mavsdk-shell-receive
  telemetry:ActuatorControlTargetResponse:mavsdk-telemetry-actuator-control-target
  telemetry:ActuatorOutputStatusResponse:mavsdk-telemetry-actuator-output-status
  telemetry:AltitudeResponse:mavsdk-telemetry-altitude
  telemetry:ArmedResponse:mavsdk-telemetry-armed
  telemetry:AttitudeAngularVelocityBodyResponse:mavsdk-telemetry-attitude-angular-velocity-body
  telemetry:AttitudeEulerResponse:mavsdk-telemetry-attitude-euler
  telemetry:AttitudeQuaternionResponse:mavsdk-telemetry-attitude-quaternion
  telemetry:BatteryResponse:mavsdk-telemetry-battery
  telemetry:DistanceSensorResponse:mavsdk-telemetry-distance-sensor
  telemetry:FixedwingMetricsResponse:mavsdk-telemetry-fixedwing-metrics
  telemetry:FlightModeResponse:mavsdk-telemetry-flight-mode
  telemetry:GpsInfoResponse:mavsdk-telemetry-gps-info
  telemetry:GroundTruthResponse:mavsdk-telemetry-ground-truth
  telemetry:HeadingResponse:mavsdk-telemetry-heading
  telemetry:HealthAllOkResponse:mavsdk-telemetry-health-all-ok
  telemetry:HealthResponse:mavsdk-telemetry-health
  telemetry:HomeResponse:mavsdk-telemetry-home
  telemetry:ImuResponse:mavsdk-telemetry-imu
  telemetry:InAirResponse:mavsdk-telemetry-in-air
  telemetry:LandedStateResponse:mavsdk-telemetry-landed-state
  telemetry:OdometryResponse:mavsdk-telemetry-odometry
  telemetry:PositionResponse:mavsdk-telemetry-position
  telemetry:PositionVelocityNedResponse:mavsdk-telemetry-position-velocity-ned
  telemetry:RawGpsResponse:mavsdk-telemetry-raw-gps
  telemetry:RawImuResponse:mavsdk-telemetry-raw-imu
  telemetry:RcStatusResponse:mavsdk-telemetry-rc-status
  telemetry:ScaledImuResponse:mavsdk-telemetry-scaled-imu
  telemetry:ScaledPressureResponse:mavsdk-telemetry-scaled-pressure
  telemetry:StatusTextResponse:mavsdk-telemetry-status-text
  telemetry:UnixEpochTimeResponse:mavsdk-telemetry-unix-epoch-time
  telemetry:VelocityNedResponse:mavsdk-telemetry-velocity-ned
  telemetry:VtolStateResponse:mavsdk-telemetry-vtol-state
  telemetry:WindResponse:mavsdk-telemetry-wind
  transponder:TransponderResponse:mavsdk-transponder-transponder
  winch:StatusResponse:mavsdk-winch-status
)
for spec in "${PACKS[@]}"; do
  plugin="${spec%%:*}"; rest="${spec#*:}"; msg="${rest%%:*}"; name="${rest#*:}"
  notes="$TMP/notes-$name.md"
  cat "$GEN/notes/mavsdk.md" > "$notes"
  EXTRA=()
  case "$plugin:$msg" in
    telemetry:PositionResponse|telemetry:GroundTruthResponse)
      cat "$GEN/notes/mavsdk-position.md" >> "$notes"
      EXTRA=(--map 1.1=lat --map 1.2=lon --cross-text "$ROOT/packs/geojson/pack.def") ;;
    telemetry:HomeResponse)
      cat "$GEN/notes/mavsdk-home.md" >> "$notes"
      EXTRA=(--map 1.2=lat --map 1.3=lon --cross-text "$ROOT/packs/geojson/pack.def") ;;
    telemetry:RawGpsResponse)
      cat "$GEN/notes/mavsdk-raw-gps.md" >> "$notes"
      EXTRA=(--map 1.2=lat --map 1.3=lon --cross-text "$ROOT/packs/geojson/pack.def") ;;
    telemetry:VelocityNedResponse)
      cat "$GEN/notes/mavsdk-velocity-ned.md" >> "$notes"
      EXTRA=(--map 1.1=track.vel_north_ms --map 1.2=track.vel_east_ms) ;;
  esac
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "$SRC/protos/$plugin/$plugin.proto" "$SRC/protos/mavsdk_options.proto" \
    --envelope "mavsdk.rpc.$plugin.$msg" --format "$name" --module "${name//-/}" \
    --source "MAVSDK-Proto: github.com/mavlink/MAVSDK-Proto commit $COMMIT, protos/$plugin/$plugin.proto and protos/mavsdk_options.proto; envelope mavsdk.rpc.$plugin.$msg (stream of Subscribe call); field numbers, names and types only" \
    --source "Licence: none stated in that repository (LicenseRef-unstated); see PROVENANCE.md" \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    --names-file "$NAMES/$name.json" \
    --notes-file "$notes" > /dev/null
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "mavsdk-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "mavsdk-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
