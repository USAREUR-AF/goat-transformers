#!/bin/bash
# Regenerate the NWS weather API packs (api.weather.gov), one per response schema.
#
# Usage: tools/gen/nws-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/nws/openapi-2026-11-19.json is the API's OpenAPI 3.1 document as served at
# https://api.weather.gov/openapi.json on 2026-11-19 (info.version 3.12.2). The document
# changes without notice and has no versioned address, so the dated copy is pinned by its
# SHA-256 below; a later download that differs stops the run. It is not kept in this
# repository. The NWS states that the information on its web servers is in the public
# domain (packs/nws-alert/PROVENANCE.md quotes it).
#
# Responses whose geometry is a Point (point, observation, station, relative location) are
# GeoJSON Features on the geojson wire. The others are read on the json wire, a Feature
# being a JSON object there: their geometry is a Polygon or absent, and their members are
# nested. Collections are json objects with a `features` group. The JSON-LD forms
# (*JsonLd), the CAP and Atom forms of alerts and the plain JSON objects (offices, text
# products) are not generated.
#
# Writes model/nws*.def, packs/nws-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-nws-*.json and tools/gen/names/nws-*.json.
# PROVENANCE.md is not generated. With --check nothing is written (jsonschema2pack --check
# per run); every run is made and the exit status is 1 when any file differs.
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
F="$SRC/nws/openapi-2026-11-19.json"
SHA=ae478b69cdac6449e3b834dca636300f830dde552ac6abc180b1d5e82e2f1d35
got="$(sha256sum "$F" | cut -d' ' -f1)"
[ "$got" = "$SHA" ] || { echo "$F: sha256 $got, expected $SHA" >&2; exit 1; }
STATUS=0
TITLE="NWS weather.gov API OpenAPI 3.1 document (info.version 3.12.2), copy of https://api.weather.gov/openapi.json served 2026-11-19"
LICENSE="US Government work: the NWS states that the information on its web servers is in the public domain (https://www.weather.gov/disclaimer)"
cd "$W"

# nws <format> <module> <schema> <wire> [options...]
nws() {
  local fmt="$1" mod="$2" schema="$3" wire="$4"
  shift 4
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$F" \
      --message "$schema=$F#/components/schemas/$schema" --wire "$wire" \
      --format "$fmt" --module "$mod" --title "$TITLE; schema $schema" --license "$LICENSE" \
      --source "https://api.weather.gov/openapi.json (OpenAPI 3.1), components.schemas.$schema" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"

# GeoJSON Features with a Point geometry: the geojson wire
nws nws-point nwspoint PointGeoJson geojson --top-level-members id \
  --map PointGeoJson:id=uid --map PointGeoJson:geometry.lon=lon --map PointGeoJson:geometry.lat=lat --cross "$XG"
nws nws-observation nwsobs ObservationGeoJson geojson --top-level-members id \
  --map ObservationGeoJson:id=uid --map ObservationGeoJson:geometry.lon=lon --map ObservationGeoJson:geometry.lat=lat \
  --map ObservationGeoJson:properties.timestamp=time_ms --cross "$XG"
nws nws-station nwsstation ObservationStationGeoJson geojson --top-level-members id \
  --map ObservationStationGeoJson:id=uid --map ObservationStationGeoJson:geometry.lon=lon \
  --map ObservationStationGeoJson:geometry.lat=lat --map ObservationStationGeoJson:properties.name=callsign --cross "$XG"
nws nws-relative-location nwsrel RelativeLocationGeoJson geojson --top-level-members id \
  --map RelativeLocationGeoJson:geometry.lon=lon --map RelativeLocationGeoJson:geometry.lat=lat --cross "$XG"

# Features with a Polygon geometry or none: the json wire
nws nws-alert nwsalert AlertGeoJson json --map AlertGeoJson:id=uid \
  --map AlertGeoJson:properties.sent=time_ms --map AlertGeoJson:properties.expires=stale_ms
nws nws-zone nwszone ZoneGeoJson json --map ZoneGeoJson:id=uid
nws nws-gridpoint nwsgrid GridpointGeoJson json --map GridpointGeoJson:id=uid
nws nws-forecast nwsfc Gridpoint12hForecastGeoJson json --map Gridpoint12hForecastGeoJson:properties.generatedAt=time_ms
nws nws-forecast-hourly nwsfch GridpointHourlyForecastGeoJson json \
  --map GridpointHourlyForecastGeoJson:properties.generatedAt=time_ms
nws nws-zone-forecast nwszfc ZoneForecastGeoJson json --map ZoneForecastGeoJson:properties.updated=time_ms
nws nws-cwa nwscwa CenterWeatherAdvisoryGeoJson json --map CenterWeatherAdvisoryGeoJson:id=uid
nws nws-sigmet nwssigmet SigmetGeoJson json --map SigmetGeoJson:id=uid

# Collections: a json object with a `features` group
nws nws-alert-collection nwsalertc AlertCollectionGeoJson json
nws nws-observation-collection nwsobsc ObservationCollectionGeoJson json
nws nws-station-collection nwsstationc ObservationStationCollectionGeoJson json
nws nws-zone-collection nwszonec ZoneCollectionGeoJson json
nws nws-cwa-collection nwscwac CenterWeatherAdvisoryCollectionGeoJson json
nws nws-sigmet-collection nwssigmetc SigmetCollectionGeoJson json

exit "$STATUS"
