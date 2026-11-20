#!/bin/bash
# Regenerate the NASA cFE packs: cfe-es, cfe-evs, cfe-sb, cfe-tbl, cfe-time (payload
# little-endian) and cfe-es-be, cfe-evs-be, cfe-sb-be, cfe-tbl-be, cfe-time-be (big-endian).
# Usage: tools/gen/cfe-run.sh [--check] <cFE checkout> <goat-transformers checkout>
#
# <cFE checkout>: https://github.com/nasa/cFE at tag v7.0.2-rc1,
#   commit 73f6fe102eae7949fc5f550e6818fec60319ddea (Apache-2.0); cfe2pack.py checks the
#   commit. A sparse checkout of modules/*/config, modules/*/fsw/inc,
#   modules/*/fsw/src/*dispatch*, modules/msg and modules/resourceid/option_inc is enough.
#   Each pack's pack.md lists every file read with its size and SHA-256.
#
# Step 1 (needs the checkout): cfe2pack.py writes model/cfemsg.def, model/cfe<m>.def,
#   packs/cfe-<m>[-be]/pack.def and pack.md, tools/gen/names/cfe.json and
#   tools/gen/cfe/layout.json. PROVENANCE.md is not generated.
# Step 2 (needs no checkout; CI runs it with --check): cfe-vectors.py writes
#   packs/cfe-<m>[-be]/vectors/gen-*.json from layout.json.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <cFE checkout> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
python3 -I "$W/tools/gen/cfe2pack.py" --src "$SRC" --out "$W" ${CHECK:+"$CHECK"}
python3 -I "$W/tools/gen/cfe-vectors.py" --out "$W" ${CHECK:+"$CHECK"}
