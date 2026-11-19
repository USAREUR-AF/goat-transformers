#!/bin/bash
# Regenerate the px4-ulog-<topic> packs: one `bits` pack per PX4 uORB topic, as the
# data of a ULog 'D' message.
#
# Usage: tools/gen/uorb2pack-run.sh <checkout> <sources> [--check]
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def,
# tools/gen/sources/px4-ulog-PROVENANCE.md, tools/gen/names/px4-ulog.json) and
# written: model/px4ulog.def, packs/px4-ulog-*/, the
# packs/geojson/vectors/gen-geojson-to-px4-ulog-*.json vectors and the names file.
#
# <sources>/px4 is a sparse checkout of https://github.com/PX4/PX4-Autopilot at tag
# v1.17.0, commit d6f12ad1c4f70ad3230afd7d86e971421e02fef4, made by this script
# when absent: msg/, Tools/msg/, docs/en/dev_log/ and docs/LICENSE. The licence is
# `LICENSE` at the root, the BSD 3-Clause License (Copyright (c) 2012 - 2023, PX4
# Development Team); the documentation is CC BY 4.0 (`docs/LICENSE`). The files are
# not kept in the repository; tools/gen/sources/px4-ulog-PROVENANCE.md holds the
# SHA-256 of every file read, and the generator stops when one differs.
#
# To compare the layout with PX4's own generator (as was done for this commit), run
# PX4's Tools/msg/px_generate_uorb_topic_files.py with --json on msg/*.msg and
# msg/versioned/*.msg (it needs the empy 3 and genmsg Python packages, which this
# repository does not use) into a directory, and set PX4_JSON to it.
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
shift 2
GEN="$(cd "$(dirname "$0")" && pwd)"
TAG=v1.17.0
COMMIT=d6f12ad1c4f70ad3230afd7d86e971421e02fef4

if [ ! -d "$SRC/px4" ]; then
  git -c advice.detachedHead=false clone -q --depth 1 --filter=blob:none --sparse -b "$TAG" \
    https://github.com/PX4/PX4-Autopilot "$SRC/px4"
  git -C "$SRC/px4" sparse-checkout set --skip-checks msg Tools/msg docs/en/dev_log docs/LICENSE
fi
got="$(git -C "$SRC/px4" rev-parse HEAD)"
if [ "$got" != "$COMMIT" ]; then
  echo "uorb2pack-run: $SRC/px4 is at $got, want $COMMIT" >&2
  exit 1
fi

MORE=()
if [ -n "${PX4_JSON:-}" ]; then
  MORE+=(--compare-formats "$PX4_JSON")
fi
python3 -I "$GEN/uorb2pack.py" --px4 "$SRC/px4" --out "$ROOT" --date-read 2026-11-19 "${MORE[@]}" "$@"
