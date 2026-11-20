#!/bin/bash
# Regenerate the MassRobotics AMR Interoperability Standard pack (massrobotics-amr): the
# identity report and the status report, one kind each.
#
# Usage: tools/gen/massrobotics-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/AMR_Interop_Standard is a git checkout of
# https://github.com/MassRobotics-AMR/AMR_Interop_Standard at commit
# f9357a423ecabc3f7112e6d10025a5231943ec50 (the head of its default branch; its one tag,
# 1.0, is an earlier commit) (the script checks). The script reads AMR_Interop_Standard.json.
# The repository has no LICENSE file and the schema states no licence; the PDF of the
# standard states the copyright of MassRobotics. The pack is labelled LicenseRef-unstated.
#
# Writes model/massrobotics.def, packs/massrobotics-amr/ (pack.def, pack.md, vectors/gen-*)
# and tools/gen/names/massrobotics-amr.json. PROVENANCE.md is not generated. With --check
# nothing is written and the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <sources> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=f9357a423ecabc3f7112e6d10025a5231943ec50
got="$(git -C "$SRC/AMR_Interop_Standard" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "AMR_Interop_Standard is at $got, not $COMMIT" >&2; exit 1; }
F="$SRC/AMR_Interop_Standard/AMR_Interop_Standard.json"
cd "$W"

python3 -I "$GEN/jsonschema2pack.py" --schema "$F" \
  --message Identity="$F#/identityReport" --message Status="$F#/statusReport" \
  --kind-when Identity:manufacturerName=present --kind-when Status:operationalState=present \
  --map '*:uuid=uid' --map '*:timestamp=time_ms' \
  --evidence "Identity:uuid=the RFC 4122 UUID that identifies the robot in every later message" \
  --evidence "Status:uuid=the robot's UUID, as its identity report gave it" \
  --evidence "Identity:timestamp=the time of the report, a date-time in UTC (section 4.1.2 of the standard)" \
  --evidence "Status:timestamp=the time of the report, a date-time in UTC (section 5.1.2 of the standard)" \
  --format massrobotics-amr --module massrobotics \
  --title "MassRobotics AMR Interoperability Standard 1.0 JSON Schema (AMR_Interop_Standard.json)" \
  --license "LicenseRef-unstated: no licence stated; copyright MassRobotics" \
  --source "https://github.com/MassRobotics-AMR/AMR_Interop_Standard at commit $COMMIT" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/massrobotics-amr.json" \
  --notes-file "$GEN/notes/massrobotics-amr.md" \
  ${CHECK:+"$CHECK"}
