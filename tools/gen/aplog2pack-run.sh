#!/bin/bash
# Regenerate the ardupilot-log-<name> packs: one `bits` pack per ArduPilot DataFlash
# log message, as the payload of a log record.
#
# Usage: tools/gen/aplog2pack-run.sh <checkout> <sources> [--check]
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def,
# tools/gen/sources/ardupilot-log-PROVENANCE.md, tools/gen/names/ardupilot-log.json)
# and written: model/aplog.def, packs/ardupilot-log-*/, the
# packs/geojson/vectors/gen-geojson-to-ardupilot-log-*.json vectors and the names file.
#
# <sources>/ardupilot is a checkout of https://github.com/ArduPilot/ardupilot at tag
# Copter-4.6.2 (the same commit as Plane-4.6.2, Rover-4.6.2 and Tracker-4.6.2),
# commit 1ebd4d996e8b6bbeb1462a9655c00aa861d5beef, made by this script when absent.
# Its licence is the GNU General Public License, version 3 (COPYING.txt). The files
# are not kept in the repository; tools/gen/sources/ardupilot-log-PROVENANCE.md holds
# the SHA-256 of every file a definition comes from, and the generator stops when one
# differs.
#
# The definitions are read from the source, as the firmware writes them into the FMT
# records of a log, not from the LogMessages.xml files ArduPilot publishes: those
# take the field names from the order of the documentation comments, which differs
# from the order of the fields for some messages (GPA, HRSC, PM and RATE at this
# commit). To compare with them, run Tools/autotest/logger_metadata/parse.py
# --vehicle <Vehicle> of the same checkout (it needs the lxml package, which this
# repository does not use) in <dir>/<Vehicle>/ for Copter, Plane, Rover, Sub and
# Tracker, and set APLOG_XML to <dir>.
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
shift 2
GEN="$(cd "$(dirname "$0")" && pwd)"
TAG=Copter-4.6.2
COMMIT=1ebd4d996e8b6bbeb1462a9655c00aa861d5beef

if [ ! -d "$SRC/ardupilot" ]; then
  git -c advice.detachedHead=false clone -q --depth 1 --filter=blob:none -b "$TAG" \
    https://github.com/ArduPilot/ardupilot "$SRC/ardupilot"
fi
got="$(git -C "$SRC/ardupilot" rev-parse HEAD)"
if [ "$got" != "$COMMIT" ]; then
  echo "aplog2pack-run: $SRC/ardupilot is at $got, want $COMMIT" >&2
  exit 1
fi

MORE=()
if [ -n "${APLOG_XML:-}" ]; then
  MORE+=(--compare-xml "$APLOG_XML")
fi
python3 -I "$GEN/aplog2pack.py" --ardupilot "$SRC/ardupilot" --out "$ROOT" --date-read 2026-11-19 "${MORE[@]}" "$@"
