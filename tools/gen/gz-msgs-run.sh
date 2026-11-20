#!/bin/bash
# Regenerate the gz-msgs-* packs: one pack per message of Gazebo's gz-msgs (package gz.msgs),
# release gz-msgs12_12.0.0, in its protobuf form.
#
# Usage: tools/gen/gz-msgs-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words (tools/gen/notes/).
#
# <sources>/proto/gz/msgs/*.proto: the 212 files of proto/gz/msgs at
# github.com/gazebosim/gz-msgs tag gz-msgs12_12.0.0 (commit
# 989f1fd4603ac794c9581b63b860219dbaa7c092), each
# https://raw.githubusercontent.com/gazebosim/gz-msgs/<commit>/proto/gz/msgs/<name>.proto.
# Each file carries an Apache License 2.0 header; LICENSE is Apache-2.0. They are not kept in
# the repository; each pack's PROVENANCE.md has their SHA-256. Every run is given all 212
# files; google/protobuf/any.proto is the generator's built-in copy.
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
TAG=gz-msgs12_12.0.0
COMMIT=989f1fd4603ac794c9581b63b860219dbaa7c092
PROTO=("$SRC"/proto/gz/msgs/*.proto)
# <message>:<pack name suffix>; the suffix is the file's name where the file holds the message
PACKS=(
  Actor:actor
  Actuators:actuators
  AirPressureSensor:air-pressure-sensor
  AirSpeed:air-speed
  AirSpeedSensor:air-speed-sensor
  Altimeter:altimeter
  AltimeterSensor:altimeter-sensor
  AnnotatedAxisAligned2DBox:annotated-axis-aligned-2d-box
  AnnotatedAxisAligned2DBox_V:annotated-axis-aligned-2d-box-v
  AnnotatedOriented3DBox:annotated-oriented-3d-box
  AnnotatedOriented3DBox_V:annotated-oriented-3d-box-v
  Any:any
  Atmosphere:atmosphere
  Axis:axis
  AxisAligned2DBox:axis-aligned-2d-box
  AxisAlignedBox:axis-aligned-box
  Battery:battery
  BatteryState:battery-state
  Boolean:boolean
  BoxGeom:boxgeom
  Bytes:bytes
  CameraCmd:camera-cmd
  CameraInfo:camera-info
  CameraLens:camera-lens
  CameraSensor:camerasensor
  CameraTrack:cameratrack
  CapsuleGeom:capsulegeom
  Cessna:cessna
  Clock:clock
  CmdVel2D:cmd-vel2d
  Collision:collision
  Color:color
  ConeGeom:conegeom
  Contact:contact
  Contacts:contacts
  ContactSensor:contactsensor
  CylinderGeom:cylindergeom
  DataLoadPathOptions:data-load-path-options
  Dataframe:dataframe
  Density:density
  Diagnostics:diagnostics
  Discovery:discovery
  Distortion:distortion
  Double:double
  Double_V:double-v
  Duration:duration
  DVLBeamState:dvl-beam-state
  DVLKinematicEstimate:dvl-kinematic-estimate
  DVLRangeEstimate:dvl-range-estimate
  DVLTrackingTarget:dvl-tracking-target
  DVLVelocityTracking:dvl-velocity-tracking
  EllipsoidGeom:ellipsoidgeom
  Empty:empty
  Entity:entity
  EntityFactory:entity-factory
  EntityFactory_V:entity-factory-v
  EntityPlugin_V:entity-plugin-v
  EntityWrench:entity-wrench
  EntityWrenchMap:entity-wrench-map
  Float:float
  Float_V:float-v
  Fluid:fluid
  FluidPressure:fluid-pressure
  Fog:fog
  Friction:friction
  FuelMetadata:fuel-metadata
  Geometry:geometry
  GPS:gps
  GPSSensor:gps-sensor
  GUI:gui
  GUICamera:gui-camera
  Header:header
  HeightmapGeom:heightmapgeom
  Hydra:hydra
  Image:image
  ImageGeom:imagegeom
  IMU:imu
  IMUSensor:imu-sensor
  Inertial:inertial
  Int32:int32
  Int32_V:int32-v
  Int64:int64
  Int64_V:int64-v
  Joint:joint
  JointAnimation:joint-animation
  JointCmd:joint-cmd
  JointTrajectory:joint-trajectory
  JointTrajectoryPoint:joint-trajectory-point
  JointWrench:joint-wrench
  Joy:joy
  Joystick:joystick
  LaserScan:laserscan
  Lens:lens
  LidarSensor:lidar-sensor
  Light:light
  Link:link
  LinkData:link-data
  LogControl:log-control
  LogPlaybackControl:log-playback-control
  LogPlaybackStatistics:log-playback-statistics
  LogStatus:log-status
  LogicalCameraImage:logical-camera-image
  LogicalCameraSensor:logical-camera-sensor
  Magnetometer:magnetometer
  MagnetometerSensor:magnetometer-sensor
  Marker:marker
  Marker_V:marker-v
  Material:material
  MaterialColor:material-color
  MeshGeom:meshgeom
  Model:model
  ModelConfiguration:model-configuration
  Model_V:model-v
  NavSat:navsat
  NavSatSensor:navsat-sensor
  NavSatWithCovariance:navsat-with-covariance
  OccupancyGrid:occupancy-grid
  Odometry:odometry
  OdometryWithCovariance:odometry-with-covariance
  Oriented3DBox:oriented-3d-box
  Packet:packet
  Param:param
  Param_V:param-v
  Parameter:parameter
  ParameterDeclaration:parameter-declaration
  ParameterDeclarations:parameter-declarations
  ParameterError:parameter-error
  ParameterName:parameter-name
  ParameterValue:parameter-value
  ParticleEmitter:particle-emitter
  ParticleEmitter_V:particle-emitter-v
  PerformanceSensorMetrics:performance-sensor-metrics
  Physics:physics
  PID:pid
  PlaneGeom:planegeom
  Plugin:plugin
  Plugin_V:plugin-v
  PointCloud:pointcloud
  PointCloudPacked:pointcloud-packed
  Polyline:polyline
  Pose:pose
  PoseAnimation:pose-animation
  PoseTrajectory:pose-trajectory
  Pose_V:pose-v
  PoseWithCovariance:pose-with-covariance
  Projector:projector
  PropagationGrid:propagation-grid
  PropagationParticle:propagation-particle
  Publish:publish
  Publishers:publishers
  Quaternion:quaternion
  RaySensor:raysensor
  Request:request
  Response:response
  RestLogin:rest-login
  RestLogout:rest-logout
  RestPost:rest-post
  RestResponse:rest-response
  Road:road
  Scene:scene
  SdfGeneratorConfig:sdf-generator-config
  Selection:selection
  Sensor:sensor
  SensorNoise:sensor-noise
  Sensor_V:sensor-v
  SerializedComponent:serialized-component
  SerializedEntity:serialized-entity
  SerializedState:serialized-state
  SerializedStep:serialized-step
  SerializedEntityMap:serialized-entity-map
  SerializedStateMap:serialized-state-map
  SerializedStepMap:serialized-step-map
  ServerControl:server-control
  Shadows:shadows
  SimEvent:sim-event
  Sky:sky
  Sonar:sonar
  SphereGeom:spheregeom
  SphericalCoordinates:spherical-coordinates
  Statistic:statistic
  StatisticsGroup:statistics-group
  Metric:metric
  StringMsg:stringmsg
  StringMsg_V:stringmsg-v
  Subscribe:subscribe
  Surface:surface
  Tactile:tactile
  Test:test
  Time:time
  TopicInfo:topic-info
  TrackVisual:track-visual
  Twist:twist
  TwistWithCovariance:twist-with-covariance
  UInt32:uint32
  UInt32_V:uint32-v
  UInt64:uint64
  UInt64_V:uint64-v
  UndoRedo:undo-redo
  UserCmd:user-cmd
  UserCmdStats:user-cmd-stats
  Vector2d:vector2d
  Vector3d:vector3d
  Version:version
  VersionRange:version-range
  VersionedName:versioned-name
  VideoRecord:video-record
  Visual:visual
  Visual_V:visual-v
  WebRequest:web-request
  WheelSlipParametersCmd:wheel-slip-parameters-cmd
  Wind:wind
  WirelessNode:wireless-node
  WirelessNodes:wireless-nodes
  WorldControl:world-control
  WorldControlState:world-control-state
  WorldModify:world-modify
  WorldReset:world-reset
  WorldStatistics:world-statistics
  Wrench:wrench
)
for spec in "${PACKS[@]}"; do
  msg="${spec%%:*}"; name="${spec#*:}"
  notes="$TMP/notes-$name.md"
  cat "$GEN/notes/gz-msgs.md" > "$notes"
  EXTRA=()
  case "$msg" in
    NavSat)
      cat "$GEN/notes/gz-msgs-navsat.md" >> "$notes"
      EXTRA=(--map 2=lat --map 3=lon --map 5=track.vel_east_ms --map 6=track.vel_north_ms --map 7=track.vel_up_ms
             --cross-text "$ROOT/packs/geojson/pack.def" --cross-omit 5 --cross-omit 6) ;;
    NavSatWithCovariance)
      cat "$GEN/notes/gz-msgs-navsat.md" >> "$notes"
      EXTRA=(--map 2=lat --map 3=lon --map 7=track.vel_east_ms --map 8=track.vel_north_ms --map 9=track.vel_up_ms
             --cross-text "$ROOT/packs/geojson/pack.def" --cross-omit 7 --cross-omit 8) ;;
    Any|EntityFactory|Packet)
      EXTRA=(--one-layout) ;;
  esac
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "${PROTO[@]}" \
    --envelope "gz.msgs.$msg" --format "gz-msgs-$name" --module "gzmsgs${name//-/}" \
    --source "Gazebo gz-msgs $TAG protobuf definitions: github.com/gazebosim/gz-msgs commit $COMMIT, proto/gz/msgs (212 .proto files); envelope gz.msgs.$msg; field numbers, names and types only" \
    --source "File headers and LICENSE at that commit: Apache License, Version 2.0 (Copyright Open Source Robotics Foundation and others)" \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    --names-file "$NAMES/gz-msgs-$name.json" \
    --notes-file "$notes" > /dev/null
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "gz-msgs-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "gz-msgs-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
