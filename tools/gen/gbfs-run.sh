#!/bin/bash
# Regenerate the GBFS packs: one pack per feed file per GBFS version, gbfs-<version>-<file>.
#
# Usage: tools/gen/gbfs-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds a git checkout of https://github.com/MobilityData/gbfs-json-schema at
# commit bae2d215bd21e546bc482df01f5bed1c8a9b74ab (Apache-2.0; the script checks the commit).
# Versions v1.0, v1.1, v2.0, v2.1, v2.2, v2.3 and v3.0 are read whole. Of the release
# candidate v3.1-RC3 only vehicle_availability.json is read: no released version has that file.
#
# Shared keys: `last_updated` is bound to time_ms where it is an RFC 3339 date-time (v3.0
# and v3.1-RC3); before v3.0 it is POSIX seconds, which the json wire cannot scale to
# milliseconds, so it stays a raw key. Positions are inside the `data` arrays (stations,
# bikes, vehicles): list items, so they stay raw keys (tools/gen/notes/gbfs.md).
#
# Writes model/gbfs*.def, packs/gbfs-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-gbfs-3.0-vehicle-status.json and
# tools/gen/names/gbfs-*.json. PROVENANCE.md files are not generated.
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
SRC="$(cd "$1" && pwd)/gbfs-json-schema"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=bae2d215bd21e546bc482df01f5bed1c8a9b74ab
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "gbfs-json-schema is at $got, not $COMMIT" >&2; exit 1; }
cd "$W"
STATUS=0

# One pack: <schema directory> <file base name> <version as in the format name>
gbfs_pack() {
  local dir="$1" base="$2" ver="$3"
  local file="$base.json"
  local fmt="gbfs-$ver-${base//_/-}"
  local module="gbfs$(echo "$ver" | tr -d '.-' | tr 'A-Z' 'a-z')$(echo "$base" | tr -d '_')"
  local args=(--schema "$SRC/$dir/$file" --message "$base=$SRC/$dir/$file"
    --format "$fmt" --module "$module"
    --title "General Bikeshare Feed Specification (GBFS) $ver $file JSON Schema"
    --license "Apache-2.0, MobilityData/gbfs-json-schema"
    --source "https://github.com/MobilityData/gbfs-json-schema at commit $COMMIT, $dir/$file"
    --source "GBFS specification: https://github.com/MobilityData/gbfs (CC BY 3.0)"
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json"
    --notes-file "$GEN/notes/gbfs.md")
  case "$ver" in
    3.*) args+=(--map "$base:last_updated=time_ms") ;;
  esac
  if [ "$fmt" = "gbfs-3.0-vehicle-status" ]; then
    args+=(--cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input")
  fi
  if ! python3 -I "$GEN/jsonschema2pack.py" "${args[@]}" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1
    [ -n "$CHECK" ] || { echo "gbfs-run: $fmt failed" >&2; exit 1; }
  fi
  [ -n "$CHECK" ] || echo "$fmt"
}

for v in v1.0 v1.1 v2.0 v2.1 v2.2 v2.3 v3.0; do
  for f in $(cd "$SRC/$v" && ls *.json | LC_ALL=C sort); do
    gbfs_pack "$v" "${f%.json}" "${v#v}"
  done
done
gbfs_pack v3.1-RC3 vehicle_availability 3.1-rc3

exit "$STATUS"
