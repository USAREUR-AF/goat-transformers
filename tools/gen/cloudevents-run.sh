#!/bin/bash
# Regenerate the CloudEvents pack: cloudevents, one event in the JSON event format.
#
# Usage: tools/gen/cloudevents-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds a git checkout of https://github.com/cloudevents/spec at tag v1.0.2,
# commit fc1f6f31f5f011a72183f1bcea20c987cb683ade (Apache-2.0; the script checks the commit).
# It reads cloudevents/formats/cloudevents.json, the JSON Schema of the JSON event format.
#
# Shared keys (tools/gen/notes/cloudevents.md): `time` is time_ms; nothing else.
#
# Writes model/cloudevents.def, packs/cloudevents/ (pack.def, pack.md, vectors/gen-*,
# PROVENANCE.md), packs/geojson/vectors/gen-geojson-to-cloudevents.json and
# tools/gen/names/cloudevents.json.
#
# With --check nothing is written: the run compares what it would write with the
# checkout, and the exit status is 1 when any file differs.
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
SRC="$(cd "$1" && pwd)/spec"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=fc1f6f31f5f011a72183f1bcea20c987cb683ade
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "cloudevents/spec is at $got, not $COMMIT" >&2; exit 1; }
cd "$W"
STATUS=0
F="$SRC/cloudevents/formats/cloudevents.json"
python3 -I "$GEN/jsonschema2pack.py" --schema "$F" --message "CloudEvent=$F" \
  --format cloudevents --module cloudevents \
  --title "CloudEvents 1.0.2 JSON event format JSON Schema (cloudevents/spec)" \
  --license "Apache-2.0, cloudevents/spec" \
  --source "https://github.com/cloudevents/spec at tag v1.0.2, commit $COMMIT, cloudevents/formats/cloudevents.json" \
  --source "CloudEvents 1.0.2 specification: cloudevents/spec.md and cloudevents/formats/json-format.md at the same commit" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/cloudevents.json" \
  --notes-file "$GEN/notes/cloudevents.md" \
  --map "CloudEvent:time=time_ms" \
  --evidence "CloudEvent:time=spec.md, attribute time: when the occurrence happened (or, when that is unknown, a time the producer chooses the same way for every event of one source); RFC 3339" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input" \
  ${CHECK:+"$CHECK"} > /dev/null || STATUS=1
python3 -I "$GEN/jsonmore-provenance.py" cloudevents ${CHECK:+"$CHECK"} "$SRC" "$W" || STATUS=1
[ -n "$CHECK" ] || echo cloudevents
exit "$STATUS"
