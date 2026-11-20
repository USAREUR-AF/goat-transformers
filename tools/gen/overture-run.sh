#!/bin/bash
# Regenerate the Overture Maps packs: one pack overture-<type> per feature type of the
# Overture Maps schema, on the geojson wire (every Overture feature is a GeoJSON Feature).
#
# Usage: tools/gen/overture-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds a git checkout of https://github.com/OvertureMaps/schema at tag v2.0.0,
# commit cb69ac3a3d31daa05f72a505af4f3234f191e77b (schema under CC BY 4.0, the repository's
# LICENSE; the script checks the commit). Each pack reads schema/defs.yaml, its theme's
# defs.yaml (where there is one) and its feature file; the GeoJSON schemas the files refer
# to (geojson.org) are the wire's own structure and are not followed.
#
# Shared keys (tools/gen/notes/overture.md): `id` is uid where the feature file declares it
# (all but building_part); the Point of the
# four feature types whose geometry must be a Point (address, connector, division, place)
# is lon/lat. No time is bound.
#
# Writes model/overture*.def, packs/overture-*/ (pack.def, pack.md, vectors/gen-*,
# PROVENANCE.md through tools/gen/jsonmore-provenance.py),
# packs/geojson/vectors/gen-geojson-to-overture-place.json and tools/gen/names/overture-*.json.
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
SRC="$(cd "$1" && pwd)/schema"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=cb69ac3a3d31daa05f72a505af4f3234f191e77b
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "OvertureMaps/schema is at $got, not $COMMIT" >&2; exit 1; }
cd "$W"
STATUS=0
EV_ID="schema/defs.yaml: the feature's identifier (a GERS ID where the feature is part of GERS); every Overture feature has one"

# One pack: <theme directory> <feature file base name>
ov_pack() {
  local theme="$1" base="$2"
  local file="$SRC/schema/$theme/$base.yaml"
  local fmt="overture-${base//_/-}"
  local module="overture$(echo "$base" | tr -d '_')"
  local schemas=("$SRC/schema/defs.yaml")
  [ -f "$SRC/schema/$theme/defs.yaml" ] && schemas+=("$SRC/schema/$theme/defs.yaml")
  schemas+=("$file")
  local args=(--schema "${schemas[@]}" --opaque https://geojson.org/schema/
    --message "$base=$file" --when "properties.theme=$theme" --when "properties.type=$base"
    --wire geojson --top-level-members id --format "$fmt" --module "$module"
    --title "Overture Maps schema $base feature (theme $theme) JSON Schema"
    --license "CC-BY-4.0, Overture Maps Foundation (OvertureMaps/schema)"
    --source "https://github.com/OvertureMaps/schema at tag v2.0.0, commit $COMMIT, schema/$theme/$base.yaml"
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json"
    --notes-file "$GEN/notes/overture.md")
  # building_part.yaml declares no `id` member (notes): uid only where the file declares it
  if grep -q '^  id:' "$file"; then
    args+=(--map "$base:id=uid" --evidence "$base:id=$EV_ID")
  fi
  case "$base" in
    address|connector|division|place)
      args+=(--map "$base:geometry.lon=lon" --map "$base:geometry.lat=lat") ;;
  esac
  if [ "$base" = place ]; then
    args+=(--cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input")
  fi
  if ! python3 -I "$GEN/jsonschema2pack.py" "${args[@]}" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1
    [ -n "$CHECK" ] || { echo "overture-run: $fmt failed" >&2; exit 1; }
  fi
  [ -n "$CHECK" ] || echo "$fmt"
}

for f in $(cd "$SRC/schema" && ls */*.yaml | grep -v '/defs.yaml$' | LC_ALL=C sort); do
  ov_pack "${f%%/*}" "$(basename "$f" .yaml)"
done
python3 -I "$GEN/jsonmore-provenance.py" overture ${CHECK:+"$CHECK"} "$SRC" "$W" || STATUS=1
exit "$STATUS"
