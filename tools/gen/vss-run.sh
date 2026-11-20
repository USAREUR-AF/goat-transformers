#!/bin/bash
# Regenerate the COVESA VSS pack: vss-vehicle, the signal tree as one JSON document.
#
# Usage: tools/gen/vss-run.sh [--check] <vehicle_signal_specification checkout> <goat-transformers checkout>
#
# Source: https://github.com/COVESA/vehicle_signal_specification at tag v6.1, commit
# 2817646d1808fc7c470c0432fc7f4ed685e5c9e3 (MPL-2.0, Contributors to COVESA).
# tools/gen/vss2pack.py checks the commit, reads spec/VehicleSignalSpecification.vspec and
# every file it includes (the SHA-256 of each is in packs/vss-vehicle/PROVENANCE.md), and
# writes through tools/gen/jsonschema2pack.py.
#   LICENSE                                1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5
#   spec/VehicleSignalSpecification.vspec  d50b06de941f61b24844a4b0f900b77212f15a8843a41ef58512a3975d6ae78c
#
# Writes model/vssvehicle.def, packs/vss-vehicle/ (pack.def, pack.md, PROVENANCE.md,
# vectors/gen-*), packs/geojson/vectors/gen-geojson-to-vss-vehicle.json and
# tools/gen/names/vss-vehicle.json.
#
# With --check nothing is written; the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <vehicle_signal_specification checkout> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
printf '%s  %s\n%s  %s\n' 1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5 "$SRC/LICENSE" d50b06de941f61b24844a4b0f900b77212f15a8843a41ef58512a3975d6ae78c "$SRC/spec/VehicleSignalSpecification.vspec" \
  | sha256sum --quiet --strict -c - || { echo "a source file differs from its pinned SHA-256" >&2; exit 1; }
exec python3 -I "$W/tools/gen/vss2pack.py" ${CHECK:+"$CHECK"} "$SRC" "$W"
