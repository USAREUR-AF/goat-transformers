#!/bin/bash
# Regenerate the STIX 2.1 packs: one pack stix-<type> per STIX Domain Object (sdos/),
# Relationship Object (sros/) and Cyber-observable Object (observables/).
#
# Usage: tools/gen/stix-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds a git checkout of https://github.com/oasis-open/cti-stix2-json-schemas at
# commit c4f8d589acf2bdb3783655c89e0ffb6e150006ae (branch stix2.1; BSD-3-Clause, Copyright
# OASIS Open; the script checks the commit). Each pack reads its object's schema and the
# common/ schemas it references, directly or not (found by following `$ref`).
#
# Shared keys (tools/gen/notes/stix.md): `id` is uid in every pack. SDOs and SROs: `modified`,
# an RFC 3339 UTC timestamp stated by a pattern, is time_ms (--date-time). Location: latitude
# and longitude are lat and lon. Observables have no time of their own.
#
# Writes model/stix*.def, packs/stix-*/ (pack.def, pack.md, vectors/gen-*, PROVENANCE.md
# through tools/gen/jsonmore-provenance.py), packs/geojson/vectors/gen-geojson-to-stix-location.json
# and tools/gen/names/stix-*.json.
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
SRC="$(cd "$1" && pwd)/cti-stix2-json-schemas"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=c4f8d589acf2bdb3783655c89e0ffb6e150006ae
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "cti-stix2-json-schemas is at $got, not $COMMIT" >&2; exit 1; }
cd "$W"
STATUS=0

# The schema files one object reads: the file and every file its $ref reach, sorted.
closure() {
  python3 -I - "$1" <<'EOF'
import json, os, sys
todo, seen = [os.path.abspath(sys.argv[1])], set()
while todo:
    f = todo.pop()
    if f in seen:
        continue
    seen.add(f)
    def refs(x):
        if isinstance(x, dict):
            r = x.get("$ref")
            if isinstance(r, str) and not r.startswith("#"):
                yield r.split("#")[0]
            for v in x.values():
                yield from refs(v)
        elif isinstance(x, list):
            for v in x:
                yield from refs(v)
    with open(f, encoding="utf-8") as fh:
        doc = json.load(fh)
    for r in refs(doc):
        todo.append(os.path.normpath(os.path.join(os.path.dirname(f), r)))
print("\n".join(sorted(seen)))
EOF
}

EV_ID="core.json: the identifier of the object, its type name, two dashes and a UUID; the same over every version of the object"
EV_TIME="core.json: the time this version of the object was made, to the millisecond; timestamp.json: RFC 3339 with the Z designator, so UTC"
EV_LAT="location.json: latitude in decimal degrees; the STIX 2.1 Location section makes WGS 84 the datum when a precision is given"
EV_LON="location.json: longitude in decimal degrees; the STIX 2.1 Location section makes WGS 84 the datum when a precision is given"

# One pack: <directory> <type>
stix_pack() {
  local dir="$1" type="$2"
  local file="$SRC/schemas/$dir/$type.json"
  local fmt="stix-$type"
  local module="stix$(echo "$type" | tr -d '-')"
  local args=(--schema $(closure "$file") --message "$type=$file" --when "type=$type"
    --format "$fmt" --module "$module"
    --title "STIX 2.1 $type object JSON Schema (OASIS CTI TC Open Repository cti-stix2-json-schemas)"
    --license "BSD-3-Clause, Copyright OASIS Open (oasis-open/cti-stix2-json-schemas)"
    --source "https://github.com/oasis-open/cti-stix2-json-schemas at commit $COMMIT, schemas/$dir/$type.json"
    --source "STIX Version 2.1, OASIS Standard: https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html"
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json"
    --notes-file "$GEN/notes/stix.md"
    --map "$type:id=uid" --evidence "$type:id=$EV_ID")
  if [ "$dir" != observables ]; then
    args+=(--date-time "$type:modified" --map "$type:modified=time_ms" --evidence "$type:modified=$EV_TIME")
  fi
  if [ "$type" = location ]; then
    args+=(--map "location:latitude=lat" --map "location:longitude=lon"
      --evidence "location:latitude=$EV_LAT" --evidence "location:longitude=$EV_LON"
      --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input")
  fi
  if ! python3 -I "$GEN/jsonschema2pack.py" "${args[@]}" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1
    [ -n "$CHECK" ] || { echo "stix-run: $fmt failed" >&2; exit 1; }
  fi
  [ -n "$CHECK" ] || echo "$fmt"
}

for dir in sdos sros observables; do
  for f in $(cd "$SRC/schemas/$dir" && ls *.json | LC_ALL=C sort); do
    stix_pack "$dir" "${f%.json}"
  done
done
python3 -I "$GEN/jsonmore-provenance.py" stix ${CHECK:+"$CHECK"} "$SRC" "$W" || STATUS=1

exit "$STATUS"
