#!/bin/bash
# Regenerate the RoboSense packs: packs/robosense-*/ and model/robosense.def, with
# tools/gen/robosense2pack.py.
#
# Usage: tools/gen/robosense-run.sh <checkout> <sources> [--fetch] [--check]
#
# <checkout> is a goat-transformers checkout; it is written. <sources> is a
# directory for the rs_driver tree, not kept in the repository. With --fetch the
# script downloads RoboSense-LiDAR/rs_driver, tag v1.5.20, commit
#   897b14d3bdb6186a75df27ba51b65b5bd5557723 (read 2026-11-20)
# from https://codeload.github.com/RoboSense-LiDAR/rs_driver/tar.gz/<commit>.
# The generator checks every file it reads against
# tools/gen/sources/robosense-PROVENANCE.md, which is what pins the input.
# License: BSD-3-Clause (LICENSE; quoted in each pack's PROVENANCE.md).
# With --check it writes nothing and reports any file that differs.
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
COMMIT=897b14d3bdb6186a75df27ba51b65b5bd5557723
shift 2
if [ "${1:-}" = "--fetch" ]; then
  shift
  mkdir -p "$SRC/rs_driver-$COMMIT"
  curl -sS -f -L "https://codeload.github.com/RoboSense-LiDAR/rs_driver/tar.gz/$COMMIT" | tar -xz -C "$SRC/rs_driver-$COMMIT" --strip-components=1
fi
python3 -I "$GEN/robosense2pack.py" --src "$SRC/rs_driver-$COMMIT" --out "$ROOT" "$@"
