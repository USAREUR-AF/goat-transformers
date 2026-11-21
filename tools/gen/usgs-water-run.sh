#!/bin/bash
# Regenerate the USGS Water Data API packs (usgs-water-*), GeoJSON Features of the OGC API -
# Features service at https://api.waterdata.usgs.gov/ogcapi/v0.
# Usage: tools/gen/usgs-water-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds two files, as served on 2026-11-21 (the script checks their SHA-256):
#   usgs-openapi.json  https://api.waterdata.usgs.gov/ogcapi/v0/openapi?f=json  (API version 0.90.0)
#                      sha256 fcd0db01e664df290e7bf85c8372b67cd14cc10aa37414a01397dd8ee7066910
#   ml-schema.json     https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/schema?f=json
#                      sha256 173ef4bb9aa5aa00e73b7bad53840ef1c5e172039a311007c9d313c16bb5a0a6
# The OpenAPI document states its licence as "US Government work in the public domain" (CC0 1.0 URL).
#
# Writes model/usgswater*.def, packs/usgs-water-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-usgs-water-{continuous,monitoring-location}.json and
# tools/gen/names/usgs-water-*.json. PROVENANCE.md is not generated.
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
echo "fcd0db01e664df290e7bf85c8372b67cd14cc10aa37414a01397dd8ee7066910  $SRC/usgs-openapi.json" | sha256sum -c --quiet
echo "173ef4bb9aa5aa00e73b7bad53840ef1c5e172039a311007c9d313c16bb5a0a6  $SRC/ml-schema.json" | sha256sum -c --quiet
O="$SRC/usgs-openapi.json"
cd "$W"
LIC="US Government work in the public domain (U.S. Geological Survey); the OpenAPI document names CC0 1.0"
SOURCE="USGS Water Data API (OGC API - Features), https://api.waterdata.usgs.gov/ogcapi/v0, API version 0.90.0, read 2026-11-21"

# One pack per collection: <format> <module> <kind> <schema> <maps time_ms> <title>
gen() {
  local fmt="$1" mod="$2" kind="$3" schema="$4" time="$5" title="$6"
  local extra=()
  if [ "$time" = yes ]; then
    extra=(--date-time "$kind:properties.time" --map "$kind:properties.time=time_ms")
  fi
  python3 -I "$GEN/jsonschema2pack.py" ${CHECK:+"$CHECK"} \
    --schema "$O" --opaque https://schemas.opengis.net/ \
    --message "$kind=$O#/components/schemas/$schema" \
    --map "$kind:geometry.lon=lon" --map "$kind:geometry.lat=lat" "${extra[@]}" \
    --wire geojson --top-level-members id --format "$fmt" --module "$mod" \
    --title "$title" --license "$LIC" --source "$SOURCE" \
    --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/usgs-water.md" \
    ${CROSS:+--cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"}
}
CROSS=yes gen usgs-water-continuous         usgswatercont       Continuous         ContinuousFeature         yes "USGS Water Data API: continuous (instantaneous) values"
gen usgs-water-latest-continuous  usgswaterlatcont    LatestContinuous   LatestContinuousFeature   yes "USGS Water Data API: latest continuous value"
gen usgs-water-daily              usgswaterdaily      Daily              DailyFeature              no  "USGS Water Data API: daily values"
gen usgs-water-latest-daily       usgswaterlatdaily   LatestDaily        LatestDailyFeature        no  "USGS Water Data API: latest daily value"
gen usgs-water-field-measurements usgswaterfield      FieldMeasurement   FieldMeasurementsFeature  yes "USGS Water Data API: field measurements"
gen usgs-water-peaks              usgswaterpeaks      Peak               PeaksFeature              no  "USGS Water Data API: annual peak streamflow and gage height"
gen usgs-water-time-series        usgswaterseries     TimeSeries         TimeSeriesMetadataFeature no  "USGS Water Data API: time-series metadata"
# The monitoring-locations schema lists the Feature's members flat, as a collection schema of OGC
# API - Features Part 5 does (the geometry, id and the properties side by side). The wrapper below
# places them where a GeoJSON Feature holds them: the schema's members as `properties`.
cat > "$SRC/ml-feature.json" <<'JSON'
{"type": "object",
 "properties": {"id": {"type": "string"},
                "properties": {"$ref": "https://api.waterdata.usgs.gov/ogcapi/v1/collections/monitoring-locations/schema"}}}
JSON
python3 -I "$GEN/jsonschema2pack.py" ${CHECK:+"$CHECK"} \
  --schema "$SRC/ml-feature.json" "$SRC/ml-schema.json" \
  --message "MonitoringLocation=$SRC/ml-feature.json" \
  --map MonitoringLocation:geometry.lon=lon --map MonitoringLocation:geometry.lat=lat \
  --wire geojson --top-level-members id --format usgs-water-monitoring-location --module usgswaterloc \
  --title "USGS Water Data API: monitoring location" --license "$LIC" --source "$SOURCE" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/usgs-water-monitoring-location.json" --notes-file "$GEN/notes/usgs-water.md" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
