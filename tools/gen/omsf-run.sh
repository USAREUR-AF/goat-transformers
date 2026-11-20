#!/bin/bash
# Regenerate the OGC Observations and Measurements Simple Features GeoJSON pack: omsf-json.
# Usage: tools/gen/omsf-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds one git checkout, at the commit below (the script checks):
#   omsf-profile  https://github.com/opengeospatial/omsf-profile
#                 commit 524c39dee7a4421b0b4b9d2b16714500ce8ac7f4
#                 The repository states no license (SPDX label LicenseRef-unstated).
# The file read is omsf-json/feature.json; its SHA-256 is in pack.md. PROVENANCE.md is
# not generated.
#
# Writes model/omsf.def, packs/omsf-json/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-omsf-json.json and tools/gen/names/omsf-json.json.
# With --check nothing is written; the exit status is 1 when any file differs.
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
got="$(git -C "$SRC/omsf-profile" rev-parse HEAD)"
[ "$got" = 524c39dee7a4421b0b4b9d2b16714500ce8ac7f4 ] || { echo "omsf-profile is at $got" >&2; exit 1; }
cd "$W"
F="$SRC/omsf-profile/omsf-json/feature.json"

# One kind per observation type, chosen by properties.featureType.
MSG=()
for t in GenericObservation MeasureObservation CategoryObservation CountObservation TruthObservation \
         MeasureTimeseriesObservation; do
  MSG+=(--message "$t=$F" --kind-when "$t:properties.featureType=$t")
done
EV_POS="RFC 7946 section 4, which the schema's Feature model follows: Point coordinates are WGS 84 longitude and latitude in decimal degrees and, as a third number, height in metres relative to the WGS 84 ellipsoid"
python3 -I "$GEN/jsonschema2pack.py" \
  --schema "$F" --opaque http://geojson.org/schema/ \
  "${MSG[@]}" \
  --map "*:geometry.lon=lon" --map "*:geometry.lat=lat" --map "*:geometry.alt=hae" \
  --map "*:properties.phenomenonTime=time_ms" \
  --evidence "*:properties.phenomenonTime=the instant at which the observed property applies, an RFC 3339 date-time (an interval is given by separate start and end members instead)" \
  --wire geojson --top-level-members id --format omsf-json --module omsf \
  --title "OGC Observations and Measurements Simple Features profile, GeoJSON encoding (omsf-json/feature.json)" \
  --license "LicenseRef-unstated: opengeospatial/omsf-profile states no license" \
  --source "https://github.com/opengeospatial/omsf-profile at commit 524c39dee7a4421b0b4b9d2b16714500ce8ac7f4, omsf-json/feature.json" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/omsf-json.json" --notes-file "$GEN/notes/omsf-json.md" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input" \
  ${CHECK:+"$CHECK"}
