#!/bin/bash
# Regenerate the weather-forecast API packs: MET Norway Locationforecast 2.0, the Open-Meteo
# forecast API and Bright Sky (DWD open data).
# Usage: tools/gen/wxfc-run.sh [--check] <sources> <goat-transformers checkout>
#
# The sources, checked by SHA-256 (none is kept in this repository):
#   <sources>/metno-locationforecast-2.0-swagger.json  the Swagger 2.0 document of
#     Locationforecast 2.0, https://api.met.no/weatherapi/locationforecast/2.0/swagger, served
#     2026-11-21 (no versioned address, so this copy is pinned); info.license CC BY 4.0
#   <sources>/open-meteo-7cc41ffa9a79c2e4c7ad4e18f13b51ab8df610aa.tar.gz  open-meteo/open-meteo
#     at that commit; openapi/forecast.yml (info.license CC BY 4.0; the repository is
#     AGPL-3.0). This project restated the response of GET /v1/forecast in
#     tools/gen/wxfc/openmeteo-forecast-1.0-response.json (names and types; the time members
#     the document types as string or integer are strings, the default timeformat)
#   <sources>/brightsky-openapi.json  the OpenAPI 3.1.0 document of Bright Sky 2.2.12,
#     https://api.brightsky.dev/openapi.json, served 2026-11-21 (no versioned address);
#     info.license MIT, as the repository jdemaeyer/brightsky (commit
#     0f5d0df885b053d6c85a82dc72db4fed04b87a7e, LICENSE)
#
# Writes model/metnolf.def, model/omfc.def, model/bs*.def, packs/metno-locationforecast/,
# packs/openmeteo-forecast/, packs/brightsky-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-*.json and the names files. PROVENANCE.md is not
# generated. With --check nothing is written; every run is made and the exit status is 1 when
# any file differs.
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
STATUS=0
while read -r sha f; do
  got="$(sha256sum "$SRC/$f" | cut -d' ' -f1)"
  [ "$got" = "$sha" ] || { echo "$f: sha256 $got, expected $sha" >&2; exit 1; }
done <<'SUMS'
c0c32a5bcff572ec98789173eb9fb0ecf4526763a6d49a341f20c65f571e2550 metno-locationforecast-2.0-swagger.json
0c382215ffbc21c713af58498713870371ef674814cc27fbb5e2c81c59f214f7 open-meteo-7cc41ffa9a79c2e4c7ad4e18f13b51ab8df610aa.tar.gz
2488b99f28691318939a29eadf55500a7fde7bd646032d193bf16a7885185b63 brightsky-openapi.json
SUMS
MET="$SRC/metno-locationforecast-2.0-swagger.json"
OM="$GEN/wxfc/openmeteo-forecast-1.0-response.json"
BS="$SRC/brightsky-openapi.json"
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
cd "$W"

# [NOTES=<notes file name>] gen <message spec> <format> <module> <title> <license> <source> [options...]
gen() {
  local msg="$1" fmt="$2" mod="$3" title="$4" lic="$5" src="$6"
  shift 6
  local file="${msg#*=}"
  file="${file%%#*}"
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$file" --message "$msg" \
      --format "$fmt" --module "$mod" --title "$title" --license "$lic" --source "$src" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/${NOTES:-$fmt}.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

ML="CC-BY-4.0 (the Locationforecast 2.0 Swagger document states CC BY 4.0; MET Norway)"
MS="MET Norway, Locationforecast 2.0 Swagger 2.0 document, https://api.met.no/weatherapi/locationforecast/2.0/swagger (served 2026-11-21, SHA-256 c0c32a5bcff572ec98789173eb9fb0ecf4526763a6d49a341f20c65f571e2550), definitions.METJSONForecast"
gen "forecast=$MET#/definitions/METJSONForecast" metno-locationforecast metnolf \
  "MET Norway Locationforecast 2.0, one forecast (GeoJSON Feature, compact or complete)" "$ML" "$MS" \
  --wire geojson --geojson-groups \
  --map forecast:geometry.lon=lon --map forecast:geometry.lat=lat \
  --cross "$XG"

OL="CC-BY-4.0 (Open-Meteo's OpenAPI document states CC BY 4.0; the repository open-meteo/open-meteo is AGPL-3.0)"
OS="Open-Meteo, openapi/forecast.yml of https://github.com/open-meteo/open-meteo at commit 7cc41ffa9a79c2e4c7ad4e18f13b51ab8df610aa, the 200 response of GET /v1/forecast, restated in tools/gen/wxfc/openmeteo-forecast-1.0-response.json"
EV_OM="The document gives the request's latitude and longitude as geographical WGS 84 coordinates; the response's latitude and longitude are those of the grid cell the forecast was computed for, in the same terms (decimal degrees, WGS 84)."
gen "forecast=$OM#/\$defs/ForecastResponse" openmeteo-forecast omfc \
  "Open-Meteo Weather Forecast API, the response of GET /v1/forecast (one location)" "$OL" "$OS" \
  --map forecast:latitude=lat --map forecast:longitude=lon \
  --evidence "forecast:latitude=$EV_OM" --evidence "forecast:longitude=$EV_OM" \
  --cross "$XG"

BL="Apache-2.0 (this project's restatement of the Bright Sky API objects; Bright Sky's OpenAPI document and repository are MIT)"
BSRC="Bright Sky 2.2.12, OpenAPI 3.1.0 document https://api.brightsky.dev/openapi.json (served 2026-11-21, SHA-256 2488b99f28691318939a29eadf55500a7fde7bd646032d193bf16a7885185b63); repository jdemaeyer/brightsky (MIT)"
EV_TS="The document gives timestamp as the ISO 8601 time of the weather record, with a UTC offset (format date-time); it is the time the record's values hold for, the observation time for observations. iso8601_ms reads it and converts to UTC."
NOTES=brightsky gen "m=$BS#/components/schemas/WeatherResponse" brightsky-weather bsweather \
  "Bright Sky, the response of GET /weather (hourly records and their sources)" "$BL" "$BSRC"
NOTES=brightsky gen "m=$BS#/components/schemas/CurrentWeatherResponse" brightsky-current-weather bscurrent \
  "Bright Sky, the response of GET /current_weather (one record and its sources)" "$BL" "$BSRC" \
  --map m:weather.timestamp=time_ms --evidence "m:weather.timestamp=$EV_TS"
NOTES=brightsky gen "m=$BS#/components/schemas/SynopResponse" brightsky-synop bssynop \
  "Bright Sky, the response of GET /synop (SYNOP records and their sources)" "$BL" "$BSRC"
NOTES=brightsky gen "m=$BS#/components/schemas/SourcesResponse" brightsky-sources bssources \
  "Bright Sky, the response of GET /sources (weather stations and model sources)" "$BL" "$BSRC"
NOTES=brightsky gen "m=$BS#/components/schemas/AlertsResponse" brightsky-alerts bsalerts \
  "Bright Sky, the response of GET /alerts (DWD weather warnings and the location)" "$BL" "$BSRC"
NOTES=brightsky gen "m=$BS#/components/schemas/RadarResponse" brightsky-radar bsradar \
  "Bright Sky, the response of GET /radar (radar records and their extent)" "$BL" "$BSRC"
NOTES=brightsky gen "m=$BS#/components/schemas/WeatherRecord" brightsky-weather-record bsrecord \
  "Bright Sky, one hourly weather record (an item of GET /weather)" "$BL" "$BSRC" \
  --map m:timestamp=time_ms --evidence "m:timestamp=$EV_TS"
NOTES=brightsky gen "m=$BS#/components/schemas/Source" brightsky-source bssource \
  "Bright Sky, one source (an item of GET /sources and of each weather response)" "$BL" "$BSRC"

exit "$STATUS"
