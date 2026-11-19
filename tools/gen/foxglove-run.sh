#!/bin/bash
# Regenerate the foxglove-proto-* packs: one pack per Foxglove schema message in its protobuf
# form, except LocationFix and LocationFixes, whose packs (foxglove-location-fix,
# foxglove-location-fixes) tools/gen/protobuf-2-run.sh writes.
#
# Usage: tools/gen/foxglove-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words
# (tools/gen/notes/foxglove-proto.md). The schema files are not kept in the repository; each
# pack's PROVENANCE.md has the license and the SHA-256 of every file.
#
#   <sources>/foxglove/<Name>.proto   the 48 files of schemas/proto/foxglove at
#     github.com/foxglove/foxglove-sdk commit 8cebcc575cea4a2dfb3622948936a8a2f2552820 (the
#     commit of foxglove-location-fix; the 48 files are byte for byte the same at
#     3f2faa010e84de414627bbd545491f2b75b02414, the head of main on 2026-11-19). Each is
#     https://raw.githubusercontent.com/foxglove/foxglove-sdk/<commit>/schemas/proto/foxglove/<Name>.proto
#     Every run is given all 48 files; google/protobuf/timestamp.proto and duration.proto are
#     the generator's built-in copies.
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
FOX=8cebcc575cea4a2dfb3622948936a8a2f2552820
ALL=(ArrowPrimitive CameraCalibration CircleAnnotation Color CompressedAudio CompressedImage
     CompressedPointCloud CompressedVideo CubePrimitive CylinderPrimitive Event FrameTransform
     FrameTransforms GeoJSON Grid ImageAnnotations JointState JointStates KeyValuePair LaserScan
     LinePrimitive LocationFix LocationFixes Log ModelPrimitive Odometry PackedElementField Point2
     Point3 Point3InFrame PointCloud PointsAnnotation Pose PoseInFrame PosesInFrame Quaternion
     RawAudio RawImage SceneEntity SceneEntityDeletion SceneUpdate SpherePrimitive TextAnnotation
     TextPrimitive TriangleListPrimitive Vector2 Vector3 VoxelGrid)
PROTO=()
for n in "${ALL[@]}"; do PROTO+=("$SRC/foxglove/$n.proto"); done
for n in "${ALL[@]}"; do
  case "$n" in LocationFix|LocationFixes) continue ;; esac
  # ArrowPrimitive -> arrow-primitive; Point3InFrame -> point3-in-frame; GeoJSON -> geojson
  kebab=$(echo "$n" | sed -E 's/([a-z0-9])([A-Z])/\1-\2/g; s/([A-Z])([A-Z][a-z])/\1-\2/g' | tr 'A-Z' 'a-z')
  [ "$n" = GeoJSON ] && kebab=geojson
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "${PROTO[@]}" \
    --envelope "foxglove.$n" --format "foxglove-proto-$kebab" --module "foxgloveproto${kebab//-/}" \
    --source "Foxglove schemas, protobuf: github.com/foxglove/foxglove-sdk commit $FOX, schemas/proto/foxglove (48 .proto files); envelope foxglove.$n; field numbers, names and types only" \
    --source "LICENSE at that commit: MIT License, Copyright (c) Foxglove Technologies Inc" \
    --names-file "$NAMES/foxglove-proto-$kebab.json" \
    --notes-file "$GEN/notes/foxglove-proto.md"
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "foxglove-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "foxglove-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
