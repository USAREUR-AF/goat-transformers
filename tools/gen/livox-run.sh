#!/bin/bash
# Regenerate the Livox pack: packs/livox-point/ (the point cloud and IMU data
# packet of Livox SDK2), model/livox.def and tools/gen/names/livox.json, with
# tools/gen/cstruct2pack.py in packet mode and the config
# tools/gen/cstruct/livox.json.
#
# Usage: tools/gen/livox-run.sh <checkout> <sources> [--fetch] [--check]
#
# <checkout> is a goat-transformers checkout; it is written. <sources> is a
# directory for the SDK files, not kept in the repository. With --fetch the
# script downloads, from Livox SDK2
#   https://github.com/Livox-SDK/Livox-SDK2
#   tag v1.3.1, commit f5d9375f84efe2b15bc0a052d3e18482ed13adf4 (read 2026-11-20)
# the files below by
#   https://raw.githubusercontent.com/Livox-SDK/Livox-SDK2/<commit>/<path>
#   LICENSE.txt                                sha256 8a71b3149554ec5b7df17087e63affedc4c0dbc7fb65bfe5495cdf86224fa85f
#   include/livox_lidar_def.h                  sha256 4245e58b212f051e5d02181e995f830d227cdf5caa4819d0281ad0458676b7b1
#   samples/livox_lidar_quick_start/main.cpp   sha256 bf18eeb72ec637e23b738f2c9eac66c30da3c2d1249f730fe562810b5abd4f0e
# to <sources>/Livox-SDK2-<commit>/<path>. License: MIT for the portions
# LICENSE.txt lists, which include both files; quoted in
# packs/livox-point/PROVENANCE.md. The generator checks every file against
# tools/gen/sources/livox-PROVENANCE.md and stops when one differs. With
# --check it writes nothing and reports any file that differs from what it
# would write.
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
COMMIT=f5d9375f84efe2b15bc0a052d3e18482ed13adf4
SDK="$SRC/Livox-SDK2-$COMMIT"
shift 2
if [ "${1:-}" = "--fetch" ]; then
  shift
  while read -r sha path; do
    mkdir -p "$SDK/$(dirname "$path")"
    curl -sS -f -L -o "$SDK/$path" "https://raw.githubusercontent.com/Livox-SDK/Livox-SDK2/$COMMIT/$path"
    echo "$sha  $SDK/$path" | sha256sum -c -
  done <<'LIST'
8a71b3149554ec5b7df17087e63affedc4c0dbc7fb65bfe5495cdf86224fa85f LICENSE.txt
4245e58b212f051e5d02181e995f830d227cdf5caa4819d0281ad0458676b7b1 include/livox_lidar_def.h
bf18eeb72ec637e23b738f2c9eac66c30da3c2d1249f730fe562810b5abd4f0e samples/livox_lidar_quick_start/main.cpp
LIST
fi
python3 -I "$GEN/cstruct2pack.py" --config "$GEN/cstruct/livox.json" --src "$SDK" --out "$ROOT" "$@"
