#!/bin/bash
# Regenerate the Curb Data Specification packs: cds-<model>, one per CDS data model.
#
# Usage: tools/gen/cds-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds a git checkout of https://github.com/openmobilityfoundation/cds-openapi at
# commit 6f8f4a78b32586f84a67d6ac3a10bf2cfec992a3 (the OpenAPI form of CDS 1.1.0; CC BY 4.0;
# the script checks the commit). Every pack reads every file of "Shared Data Models/".
#
# Shared keys (tools/gen/notes/cds.md): the model's own id is uid; last_updated_date (zone,
# area, space, object) and event_time (event) are time_ms, integer milliseconds UTC.
#
# Writes model/cds*.def, packs/cds-*/ (pack.def, pack.md, vectors/gen-*, PROVENANCE.md through
# tools/gen/jsonmore-provenance.py) and tools/gen/names/cds-*.json.
#
# With --check nothing is written; every run is made and the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] <sources> <goat-transformers checkout>" >&2; exit 2; fi
SRC="$(cd "$1" && pwd)/cds-openapi"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=6f8f4a78b32586f84a67d6ac3a10bf2cfec992a3
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "cds-openapi is at $got, not $COMMIT" >&2; exit 1; }
cd "$W"
STATUS=0
M="$SRC/Shared Data Models"
FILES=("$M"/*.yaml)
EV_TIME="timestamp.yaml: an integer of milliseconds since 1970-01-01 UTC"

# One pack: <model base name> <id member or -> <time member or -> <what the time is>
cds_pack() {
  local base="$1" idm="$2" tm="$3" what="$4"
  local fmt="cds-${base//_/-}" module="cds$(echo "$base" | tr -d '_')"
  local args=(--schema "${FILES[@]}" --message "$base=$M/$base.yaml" --format "$fmt" --module "$module"
    --title "Curb Data Specification (CDS) 1.1.0 data model $base (OpenAPI, cds-openapi)"
    --license "CC-BY-4.0, Open Mobility Foundation (cds-openapi)"
    --source "https://github.com/openmobilityfoundation/cds-openapi at commit $COMMIT, Shared Data Models/$base.yaml"
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/cds.md")
  if [ "$idm" != - ]; then
    args+=(--map "$base:$idm=uid" --evidence "$base:$idm=curb-data-specification README: the identifier of this $base")
  fi
  if [ "$tm" != - ]; then
    args+=(--map "$base:$tm=time_ms" --evidence "$base:$tm=$what; $EV_TIME")
  fi
  if ! python3 -I "$GEN/jsonschema2pack.py" "${args[@]}" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1; [ -n "$CHECK" ] || { echo "cds-run: $fmt failed" >&2; exit 1; }
  fi
  [ -n "$CHECK" ] || echo "$fmt"
}

UPD="curbs/README.md: when the record's properties were last updated"
cds_pack curb_zone curb_zone_id last_updated_date "$UPD"
cds_pack curb_area curb_area_id last_updated_date "$UPD"
cds_pack curb_space curb_space_id last_updated_date "$UPD"
cds_pack curb_object curb_object_id last_updated_date "$UPD"
cds_pack curb_event event_id event_time "events/README.md: the time the event occurred"
cds_pack curb_status - - -
cds_pack session - - -
cds_pack aggregate - - -
python3 -I "$GEN/jsonmore-provenance.py" cds ${CHECK:+"$CHECK"} "$SRC" "$W" || STATUS=1
exit "$STATUS"
