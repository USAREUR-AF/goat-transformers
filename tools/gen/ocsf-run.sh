#!/bin/bash
# Regenerate the OCSF packs: one pack ocsf-<class> per event class of the Open
# Cybersecurity Schema Framework.
#
# Usage: tools/gen/ocsf-run.sh [--check] <ocsf-schema checkout> <goat-transformers checkout>
#
# Source: https://github.com/ocsf/ocsf-schema at tag 1.9.0, commit
# 856d462bd20dc46cc1ffed2dfffe3b91ef0fbeba (Apache-2.0; NOTICE: OCSF a Series of LF
# Projects, LLC). tools/gen/ocsf2pack.py checks the commit, resolves each class (extends,
# the dictionary, objects; profiles and extensions left out), and writes through
# tools/gen/jsonschema2pack.py. The SHA-256 of every file read is in each pack's
# PROVENANCE.md; the files every pack reads:
#   LICENSE          0cec06e0e55fbc3dc5cee4fca9b607f66cb8f4e4dbcf3b3c013594dd156732e9
#   NOTICE           990c6fa8d244c2334708b526d923cee8b4853a26fdd2c4f310e39d7c51fc4347
#   dictionary.json  d05f472d58802524679a03ad77ae1ac6b9eb2135013931bad15926da65e8d42d
#   categories.json  4ee3a5f8906c4bc49014e4da28a8bb9666cced4af944e3fab85777381bfb70cc
#
# Writes model/ocsf*.def, packs/ocsf-*/ (pack.def, pack.md, PROVENANCE.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-ocsf-device-config-state-change.json and
# tools/gen/names/ocsf-*.json.
#
# With --check nothing is written: every class is compared with the checkout, and the
# exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <ocsf-schema checkout> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
exec python3 -I "$W/tools/gen/ocsf2pack.py" ${CHECK:+"$CHECK"} "$SRC" "$W"
