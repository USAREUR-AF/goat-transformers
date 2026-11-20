#!/bin/bash
# Regenerate the lidar packs: packs/ouster-*/, packs/velodyne-*/, model/ouster.def
# and model/velodyne.def, with tools/gen/lidar2pack.py.
#
# Usage: tools/gen/lidar-run.sh <checkout> <sources> [--fetch] [--check]
#
# <checkout> is a goat-transformers checkout; it is written. <sources> is a
# directory for the source trees, not kept in the repository. With --fetch the
# script downloads
#   Ouster SDK, tag v1.0.1, commit 46b7bceee7995914e2f3f3facf4d78418335b2d7
#     https://codeload.github.com/ouster-lidar/ouster-sdk/tar.gz/46b7bceee7995914e2f3f3facf4d78418335b2d7
#   ROS velodyne driver, tag 2.5.1, commit 0f2a3bb1dde4fa91cbafad8a3f9f89b66c2a1350
#     https://codeload.github.com/ros-drivers/velodyne/tar.gz/0f2a3bb1dde4fa91cbafad8a3f9f89b66c2a1350
#   ROS velodyne driver, branch gps_imu, commit 7f52dd39747a9f4d43c95c31a5c66f26ae9ae71a: COPYING,
#     velodyne_gps_imu/src/gpsimu_driver.h and .cc from
#     https://raw.githubusercontent.com/ros-drivers/velodyne/<commit>/<path>
# (read 2026-11-20). The generator checks every file it reads against
# tools/gen/sources/lidar-PROVENANCE.md, which is what pins the inputs; GitHub
# may rebuild an archive with other bytes. Licences: BSD-3-Clause (Ouster
# LICENSE; velodyne LICENSE and COPYING), quoted in each pack's PROVENANCE.md.
# With --check the generator writes nothing and reports any file that differs.
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
OUSTER=46b7bceee7995914e2f3f3facf4d78418335b2d7
VELODYNE=0f2a3bb1dde4fa91cbafad8a3f9f89b66c2a1350
GPSIMU=7f52dd39747a9f4d43c95c31a5c66f26ae9ae71a
shift 2
if [ "${1:-}" = "--fetch" ]; then
  shift
  mkdir -p "$SRC/ouster-$OUSTER" "$SRC/velodyne-$VELODYNE"
  curl -sS -f -L "https://codeload.github.com/ouster-lidar/ouster-sdk/tar.gz/$OUSTER" | tar -xz -C "$SRC/ouster-$OUSTER" --strip-components=1
  curl -sS -f -L "https://codeload.github.com/ros-drivers/velodyne/tar.gz/$VELODYNE" | tar -xz -C "$SRC/velodyne-$VELODYNE" --strip-components=1
  for f in COPYING velodyne_gps_imu/src/gpsimu_driver.h velodyne_gps_imu/src/gpsimu_driver.cc; do
    mkdir -p "$SRC/gpsimu-$GPSIMU/$(dirname "$f")"
    curl -sS -f -L -o "$SRC/gpsimu-$GPSIMU/$f" "https://raw.githubusercontent.com/ros-drivers/velodyne/$GPSIMU/$f"
  done
fi
python3 -I "$GEN/lidar2pack.py" --ouster "$SRC/ouster-$OUSTER" --velodyne "$SRC/velodyne-$VELODYNE" \
  --gpsimu "$SRC/gpsimu-$GPSIMU" --out "$ROOT" "$@"
