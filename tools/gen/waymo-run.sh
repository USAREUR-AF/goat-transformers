#!/bin/bash
# Regenerate the waymo-* packs of the Waymo Open Dataset schema other than waymo-frame and
# waymo-scenario (which tools/gen/protobuf-4-run.sh writes): one pack per top-level message of
# the 30 .proto files of src/waymo_open_dataset outside wdl_limited, at the same commit.
#
# Usage: tools/gen/waymo-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words
# (tools/gen/notes/waymo-schema.md). Only the schema is read: no value of the dataset is used.
#
# <sources>/src/waymo_open_dataset/{*.proto,protos/*.proto}: the 30 files at
# github.com/waymo-research/waymo-open-dataset commit 99a4cb3ff07e2fe06c2ce73da001f850f628e45a
# (the head of master on 2026-11-20, and the commit of waymo-frame), each
# https://raw.githubusercontent.com/waymo-research/waymo-open-dataset/<commit>/<path>. LICENSE:
# Apache-2.0 for the repository excluding src/waymo_open_dataset/wdl_limited, whose files are not
# read. Each pack's PROVENANCE.md has their SHA-256. Every run is given all 30 files.
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
COMMIT=99a4cb3ff07e2fe06c2ce73da001f850f628e45a
W="$SRC/src/waymo_open_dataset"
PROTO=("$W"/*.proto "$W"/protos/*.proto)
# <message>:<pack name suffix>
PACKS=(
  waymo.open_dataset.MatrixShape:matrix-shape
  waymo.open_dataset.MatrixFloat:matrix-float
  waymo.open_dataset.MatrixInt32:matrix-int32
  waymo.open_dataset.Transform:transform
  waymo.open_dataset.Velocity:velocity
  waymo.open_dataset.CameraCalibration:camera-calibration
  waymo.open_dataset.LaserCalibration:laser-calibration
  waymo.open_dataset.Context:context
  waymo.open_dataset.RangeImage:range-image
  waymo.open_dataset.CameraSegmentationLabel:camera-segmentation-label
  waymo.open_dataset.CameraImage:camera-image
  waymo.open_dataset.CameraLabels:camera-labels
  waymo.open_dataset.Laser:laser
  waymo.open_dataset.Label:label
  waymo.open_dataset.Polygon2dProto:polygon2d-proto
  waymo.open_dataset.Box2d:box2d
  waymo.open_dataset.Box3d:box3d
  waymo.open_dataset.Breakdown:breakdown
  waymo.open_dataset.CameraSegmentationFrame:camera-segmentation-frame
  waymo.open_dataset.CameraSegmentationFrameList:camera-segmentation-frame-list
  waymo.open_dataset.CameraSegmentationMetrics:camera-segmentation-metrics
  waymo.open_dataset.CameraSegmentationSubmission:camera-segmentation-submission
  waymo.open_dataset.CameraTokens:camera-tokens
  waymo.open_dataset.FrameCameraTokens:frame-camera-tokens
  waymo.open_dataset.Metadata:metadata
  waymo.open_dataset.DeltaEncodedData:delta-encoded-data
  waymo.open_dataset.CompressedLaser:compressed-laser
  waymo.open_dataset.CompressedFrameLaserData:compressed-frame-laser-data
  waymo.open_dataset.MotionExampleConversionConfig:motion-example-conversion-config
  waymo.open_dataset.E2EDFrame:e2ed-frame
  waymo.open_dataset.EgoTrajectoryStates:ego-trajectory-states
  waymo.open_dataset.E2EDMetrics:e2ed-metrics
  waymo.open_dataset.TrajectoryPrediction:trajectory-prediction
  waymo.open_dataset.FrameTrajectoryPredictions:frame-trajectory-predictions
  waymo.open_dataset.E2EDChallengeSubmission:e2ed-challenge-submission
  waymo.open_dataset.keypoints.KeypointVisibility:keypoints-keypoint-visibility
  waymo.open_dataset.keypoints.Keypoint2d:keypoints-keypoint2d
  waymo.open_dataset.keypoints.Keypoint3d:keypoints-keypoint3d
  waymo.open_dataset.keypoints.CameraKeypoint:keypoints-camera-keypoint
  waymo.open_dataset.keypoints.CameraKeypoints:keypoints-camera-keypoints
  waymo.open_dataset.keypoints.LaserKeypoint:keypoints-laser-keypoint
  waymo.open_dataset.keypoints.LaserKeypoints:keypoints-laser-keypoints
  waymo.open_dataset.keypoints.KeypointGroupMetric:keypoints-keypoint-group-metric
  waymo.open_dataset.keypoints.KeypointThresholdMetric:keypoints-keypoint-threshold-metric
  waymo.open_dataset.keypoints.KeypointMetrics:keypoints-keypoint-metrics
  waymo.open_dataset.keypoints.PoseEstimation:keypoints-pose-estimation
  waymo.open_dataset.keypoints.PoseEstimationSubmission:keypoints-pose-estimation-submission
  waymo.open_dataset.Map:map
  waymo.open_dataset.DynamicState:dynamic-state
  waymo.open_dataset.TrafficSignalLaneState:traffic-signal-lane-state
  waymo.open_dataset.MapFeature:map-feature
  waymo.open_dataset.MapPoint:map-point
  waymo.open_dataset.BoundarySegment:boundary-segment
  waymo.open_dataset.LaneNeighbor:lane-neighbor
  waymo.open_dataset.LaneCenter:lane-center
  waymo.open_dataset.RoadEdge:road-edge
  waymo.open_dataset.RoadLine:road-line
  waymo.open_dataset.StopSign:stop-sign
  waymo.open_dataset.Crosswalk:crosswalk
  waymo.open_dataset.SpeedBump:speed-bump
  waymo.open_dataset.Driveway:driveway
  waymo.open_dataset.Object:object
  waymo.open_dataset.NoLabelZoneObject:no-label-zone-object
  waymo.open_dataset.Objects:objects
  waymo.open_dataset.Difficulty:difficulty
  waymo.open_dataset.Config:config
  waymo.open_dataset.DetectionMeasurement:detection-measurement
  waymo.open_dataset.DetectionMeasurements:detection-measurements
  waymo.open_dataset.DetectionMetrics:detection-metrics
  waymo.open_dataset.TrackingMeasurement:tracking-measurement
  waymo.open_dataset.TrackingMeasurements:tracking-measurements
  waymo.open_dataset.TrackingMetrics:tracking-metrics
  waymo.open_dataset.SingleTrajectory:single-trajectory
  waymo.open_dataset.JointTrajectories:joint-trajectories
  waymo.open_dataset.MultimodalPrediction:multimodal-prediction
  waymo.open_dataset.ScenarioPredictions:scenario-predictions
  waymo.open_dataset.MotionMetricsBundle:motion-metrics-bundle
  waymo.open_dataset.MotionMetrics:motion-metrics
  waymo.open_dataset.MotionMetricsConfig:motion-metrics-config
  waymo.open_dataset.Trajectory:trajectory
  waymo.open_dataset.ScoredTrajectory:scored-trajectory
  waymo.open_dataset.SingleObjectPrediction:single-object-prediction
  waymo.open_dataset.PredictionSet:prediction-set
  waymo.open_dataset.ObjectTrajectory:object-trajectory
  waymo.open_dataset.ScoredJointTrajectory:scored-joint-trajectory
  waymo.open_dataset.JointPrediction:joint-prediction
  waymo.open_dataset.ChallengeScenarioPredictions:challenge-scenario-predictions
  waymo.open_dataset.MotionChallengeSubmission:motion-challenge-submission
  waymo.open_dataset.OccupancyFlowTaskConfig:occupancy-flow-task-config
  waymo.open_dataset.OccupancyFlowMetrics:occupancy-flow-metrics
  waymo.open_dataset.occupancy_flow.ScenarioPrediction:occupancy-flow-scenario-prediction
  waymo.open_dataset.occupancy_flow.ChallengeSubmission:occupancy-flow-challenge-submission
  waymo.open_dataset.ObjectState:object-state
  waymo.open_dataset.Track:track
  waymo.open_dataset.DynamicMapState:dynamic-map-state
  waymo.open_dataset.RequiredPrediction:required-prediction
  waymo.open_dataset.SegmentationFrame:segmentation-frame
  waymo.open_dataset.SegmentationFrameList:segmentation-frame-list
  waymo.open_dataset.SegmentationMetricsConfig:segmentation-metrics-config
  waymo.open_dataset.SegmentationMeasurements:segmentation-measurements
  waymo.open_dataset.SegmentationMetrics:segmentation-metrics
  waymo.open_dataset.SemanticSegmentationSubmission:semantic-segmentation-submission
  waymo.open_dataset.SimAgentMetricsConfig:sim-agent-metrics-config
  waymo.open_dataset.SimAgentMetrics:sim-agent-metrics
  waymo.open_dataset.SimAgentsBucketedMetrics:sim-agents-bucketed-metrics
  waymo.open_dataset.SimulatedTrajectory:simulated-trajectory
  waymo.open_dataset.JointScene:joint-scene
  waymo.open_dataset.ScenarioRollouts:scenario-rollouts
  waymo.open_dataset.SimAgentsChallengeSubmission:sim-agents-challenge-submission
  waymo.open_dataset.Submission:submission
  waymo.open_dataset.Vector2d:vector2d
  waymo.open_dataset.Vector3d:vector3d
)
for spec in "${PACKS[@]}"; do
  msg="${spec%%:*}"; name="${spec#*:}"
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "${PROTO[@]}" \
    --envelope "$msg" --format "waymo-$name" --module "waymo${name//-/}" \
    --source "Waymo Open Dataset protobuf definitions: github.com/waymo-research/waymo-open-dataset commit $COMMIT, src/waymo_open_dataset (30 .proto files, none under wdl_limited); envelope $msg; field numbers, names and types only; no dataset content" \
    --source "LICENSE at that commit: Apache License, Version 2.0, for the repository excluding src/waymo_open_dataset/wdl_limited; file headers: Copyright The Waymo Open Dataset Authors, Apache License, Version 2.0" \
    --names-file "$NAMES/waymo-$name.json" \
    --notes-file "$GEN/notes/waymo-schema.md" > /dev/null
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "waymo-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "waymo-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
