#!/bin/bash
# Regenerate the GOFS packs: one pack gofs-<file> per feed file of the General On-demand
# Feed Specification that has a JSON Schema.
#
# Usage: tools/gen/gofs-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds a git checkout of https://github.com/MobilityData/gofs at commit
# ab9151ed0237de98e4f68f7c574da8b8dc34083d (Apache-2.0; the script checks the commit). It reads
# schema/*.json. The repository calls these schemas partial and a work in progress.
#
# Shared keys (tools/gen/notes/gofs.md): `last_updated`, an integer of POSIX seconds, is
# time_ms through iscale:1000 (engine-spec 0.15), as in the GBFS packs before 3.0.
#
# Writes model/gofs*.def, packs/gofs-*/ (pack.def, pack.md, vectors/gen-*, PROVENANCE.md),
# packs/geojson/vectors/gen-geojson-to-gofs-system-information.json and
# tools/gen/names/gofs-*.json.
#
# With --check nothing is written: every run compares what it would write with the
# checkout, all runs are made, and the exit status is 1 when any file differs.
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
SRC="$(cd "$1" && pwd)/gofs"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=ab9151ed0237de98e4f68f7c574da8b8dc34083d
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "gofs is at $got, not $COMMIT" >&2; exit 1; }
cd "$W"
STATUS=0
EV="schema/<file>: the time the feed's data was last updated, an integer of POSIX seconds (seconds since 1970-01-01 UTC)"

gofs_pack() {
  local base="$1"
  local file="$SRC/schema/$base.json"
  local fmt="gofs-${base//_/-}"
  local module="gofs$(echo "$base" | tr -d '_')"
  local args=(--schema "$file" --message "$base=$file" --format "$fmt" --module "$module"
    --title "General On-demand Feed Specification (GOFS) $base.json JSON Schema"
    --license "Apache-2.0, MobilityData/gofs"
    --source "https://github.com/MobilityData/gofs at commit $COMMIT, schema/$base.json"
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json"
    --notes-file "$GEN/notes/gofs.md"
    --map "$base:last_updated=time_ms" --scale "$base:last_updated=iscale:1000"
    --evidence "$base:last_updated=${EV/<file>/$base.json}")
  if [ "$fmt" = gofs-system-information ]; then
    args+=(--cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input")
  fi
  if ! python3 -I "$GEN/jsonschema2pack.py" "${args[@]}" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1
    [ -n "$CHECK" ] || { echo "gofs-run: $fmt failed" >&2; exit 1; }
  fi
  [ -n "$CHECK" ] || echo "$fmt"
}

for f in $(cd "$SRC/schema" && ls *.json | LC_ALL=C sort); do
  gofs_pack "${f%.json}"
done
python3 -I "$GEN/jsonmore-provenance.py" gofs ${CHECK:+"$CHECK"} "$SRC" "$W" || STATUS=1
exit "$STATUS"
