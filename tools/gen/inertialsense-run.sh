#!/bin/bash
# Regenerate the Inertial Sense packs: packs/inertialsense-<group>/ (ten `bits`
# packs, one kind per data set id), model/inertialsense.def and
# tools/gen/names/inertialsense.json, with tools/gen/cstruct2pack.py and the
# config tools/gen/cstruct/inertialsense.json.
#
# Usage: tools/gen/inertialsense-run.sh <checkout> <sources> [--fetch] [--check]
#
# <checkout> is a goat-transformers checkout; it is written. <sources> is a
# directory for the SDK files, not kept in the repository. With --fetch the
# script downloads, from the Inertial Sense SDK
#   https://github.com/inertialsense/inertial-sense-sdk
#   commit ad5cb161e28ac838112a2ec130dfaab269613672 (branch main, read 2026-11-20)
# the files below by
#   https://raw.githubusercontent.com/inertialsense/inertial-sense-sdk/<commit>/<path>
#   LICENSE               sha256 3dc5f55f200b29992e9701571eab9a625a8fef3e09c58d5d68b32255668ca264
#   src/data_sets.h       sha256 2355db8f030fee5c3dfbbf1695e760aa3d72b4898d1fbe3dfc690df2a1f77174
#   src/ISConstants.h     sha256 21af5573b4b600748f290c77932107814fa09e36cf3ce442a8606458df455a1e
#   src/rtk_defines.h     sha256 02dc1b98cde8aeebbd3fb840c4bbf172384791607eac554d03a7cb4d574d6c94
#   src/core/base_port.h  sha256 311303e0af2832522cf5f0e3ef68905504b91899b2c7ebb1bfa7ea2e0090aa19
#   src/ISComm.h          sha256 c0f1b69d0e64862dd698e259730be674e76699bf9c889d5fb2d0db6795971793
# to <sources>/inertial-sense-sdk-<commit>/<path>. License: MIT (LICENSE, and the
# header of src/data_sets.h); quoted in packs/inertialsense-*/PROVENANCE.md.
# The generator checks every file against tools/gen/sources/inertialsense-PROVENANCE.md
# and stops when one differs. With --check it writes nothing and reports any
# file that differs from what it would write.
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
COMMIT=ad5cb161e28ac838112a2ec130dfaab269613672
SDK="$SRC/inertial-sense-sdk-$COMMIT"
shift 2
if [ "${1:-}" = "--fetch" ]; then
  shift
  while read -r sha path; do
    mkdir -p "$SDK/$(dirname "$path")"
    curl -sS -f -L -o "$SDK/$path" "https://raw.githubusercontent.com/inertialsense/inertial-sense-sdk/$COMMIT/$path"
    echo "$sha  $SDK/$path" | sha256sum -c -
  done <<'LIST'
3dc5f55f200b29992e9701571eab9a625a8fef3e09c58d5d68b32255668ca264 LICENSE
2355db8f030fee5c3dfbbf1695e760aa3d72b4898d1fbe3dfc690df2a1f77174 src/data_sets.h
21af5573b4b600748f290c77932107814fa09e36cf3ce442a8606458df455a1e src/ISConstants.h
02dc1b98cde8aeebbd3fb840c4bbf172384791607eac554d03a7cb4d574d6c94 src/rtk_defines.h
311303e0af2832522cf5f0e3ef68905504b91899b2c7ebb1bfa7ea2e0090aa19 src/core/base_port.h
c0f1b69d0e64862dd698e259730be674e76699bf9c889d5fb2d0db6795971793 src/ISComm.h
LIST
fi
python3 -I "$GEN/cstruct2pack.py" --config "$GEN/cstruct/inertialsense.json" --src "$SDK" --out "$ROOT" "$@"
