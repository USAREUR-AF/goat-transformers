#!/bin/bash
# Regenerate the aviationweather.gov Data API packs (awc-*), one per product and form.
#
# Usage: tools/gen/awc-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/awc/openapi-2026-11-20.yaml is the API's OpenAPI 3.1.0 document (info.version
# v4.0) as served at https://aviationweather.gov/data/schema/openapi.yaml on 2026-11-20
# (Last-Modified 2026-11-19 19:45:47 GMT). The document has no versioned address, so the
# dated copy is pinned by its SHA-256 below; a copy that differs stops the run. It is not
# kept in this repository. The Aviation Weather Center is part of the National Weather
# Service; the site's Disclaimer link is the NWS disclaimer, which states that the
# information is in the public domain (packs/awc-metar/PROVENANCE.md quotes it).
#
# Writes model/awc*.def, packs/awc-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-awc-*.json and tools/gen/names/awc-*.json.
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
F="$SRC/awc/openapi-2026-11-20.yaml"
SHA=51fe8bfd7fead5085aae9bba62aeaa0c287a836712b77f3c05f3915570465ec2
got="$(sha256sum "$F" | cut -d' ' -f1)"
[ "$got" = "$SHA" ] || { echo "$F: sha256 $got, expected $SHA" >&2; exit 1; }
STATUS=0
TITLE="AviationWeather.gov Data API OpenAPI 3.1.0 document (info.version v4.0), copy of https://aviationweather.gov/data/schema/openapi.yaml served 2026-11-20"
LICENSE="US Government work (NOAA/NWS Aviation Weather Center): the NWS states that its web information is in the public domain (https://www.weather.gov/disclaimer)"
cd "$W"

# awc <format> <module> <JSON pointer of the message> <wire> [options...]
awc() {
  local fmt="$1" mod="$2" ptr="$3" wire="$4"
  shift 4
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$F" --message "report=$F#$ptr" --wire "$wire" \
      --format "$fmt" --module "$mod" --title "$TITLE; $ptr" --license "$LICENSE" \
      --source "https://aviationweather.gov/data/schema/openapi.yaml (OpenAPI 3.1.0), $ptr" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/awc.md" \
      "$@" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
C=/components/schemas
FI=properties/features/items
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
EV_SITE="the ICAO identifier of the reporting site"
EV_NAME="the site's full name"
EV_LATJ="the site's latitude in degrees; no datum is named, and the GeoJSON form of the same report is WGS 84 by RFC 7946 (notes)"
EV_LONJ="the site's longitude in degrees; no datum is named, and the GeoJSON form of the same report is WGS 84 by RFC 7946 (notes)"
EV_OBS="the time of the observation as a UNIX timestamp, seconds since 1970-01-01 UTC; iscale:1000 makes milliseconds"
EV_VALIDTO="the end of the forecast's period of validity as a UNIX timestamp, seconds since 1970-01-01 UTC; iscale:1000 makes milliseconds"
EV_SITEG="the station's ICAO identifier"
EV_SNAME="the station's site name"

# METAR: observations
awc awc-metar awcmetar $C/METARproperties json \
  --map report:icaoId=uid --evidence "report:icaoId=$EV_SITE" --map report:name=callsign --evidence "report:name=$EV_NAME" \
  --map report:lat=lat --evidence "report:lat=$EV_LATJ" --map report:lon=lon --evidence "report:lon=$EV_LONJ" \
  --map report:obsTime=time_ms --scale report:obsTime=iscale:1000 --evidence "report:obsTime=$EV_OBS"
awc awc-metar-geojson awcmetargeo $C/METARGeoJSON/$FI geojson --top-level-members id \
  --map report:geometry.lon=lon \
  --map report:geometry.lat=lat \
  --map report:properties.icaoId=uid --evidence "report:properties.icaoId=$EV_SITE" \
  --map report:properties.name=callsign --evidence "report:properties.name=$EV_NAME" \
  --map report:properties.obsTime=time_ms --scale report:properties.obsTime=iscale:1000 \
  --evidence "report:properties.obsTime=$EV_OBS" --cross "$XG"
# TAF: forecasts
awc awc-taf awctaf $C/TAFproperties json \
  --map report:icaoId=uid --evidence "report:icaoId=$EV_SITE" --map report:name=callsign --evidence "report:name=$EV_NAME" \
  --map report:lat=lat --evidence "report:lat=$EV_LATJ" --map report:lon=lon --evidence "report:lon=$EV_LONJ" \
  --map report:validTimeTo=stale_ms --scale report:validTimeTo=iscale:1000 --evidence "report:validTimeTo=$EV_VALIDTO"
awc awc-taf-geojson awctafgeo $C/TAFGeoJSON/$FI geojson --top-level-members id \
  --map report:geometry.lon=lon \
  --map report:geometry.lat=lat \
  --map report:properties.icaoId=uid --evidence "report:properties.icaoId=$EV_SITE" --cross "$XG"
# PIREP: pilot reports (the position is the report's, not a site's; no uid)
awc awc-pirep awcpirep $C/PIREPJSON/items json \
  --map report:lat=lat --evidence "report:lat=the report's latitude; no datum is named, and the GeoJSON form of the same report is WGS 84 by RFC 7946 (notes)" \
  --map report:lon=lon --evidence "report:lon=the report's longitude; no datum is named, and the GeoJSON form of the same report is WGS 84 by RFC 7946 (notes)" \
  --map report:obsTime=time_ms --scale report:obsTime=iscale:1000 --evidence "report:obsTime=$EV_OBS"
awc awc-pirep-geojson awcpirepgeo $C/PIREPGeoJSON/$FI geojson --top-level-members id \
  --map report:geometry.lon=lon \
  --map report:geometry.lat=lat \
  --map report:properties.obsTime=time_ms --scale report:properties.obsTime=iscale:1000 \
  --evidence "report:properties.obsTime=$EV_OBS" --cross "$XG"
# Station information
awc awc-station awcstation $C/StationInfoJSON/items json \
  --map report:icaoId=uid --evidence "report:icaoId=$EV_SITEG" --map report:site=callsign --evidence "report:site=$EV_SNAME" \
  --map report:lat=lat --evidence "report:lat=$EV_LATJ" --map report:lon=lon --evidence "report:lon=$EV_LONJ"
awc awc-station-geojson awcstationgeo $C/StationInfoGeoJSON/$FI geojson --top-level-members id \
  --map report:geometry.lon=lon \
  --map report:geometry.lat=lat \
  --map report:properties.icaoId=uid --evidence "report:properties.icaoId=$EV_SITEG" \
  --map report:properties.site=callsign --evidence "report:properties.site=$EV_SNAME" --cross "$XG"
# Advisories: area products, no shared key (their times have no stated meaning or unit)
awc awc-airsigmet awcairsigmet $C/AirSigmetJSON/items json
awc awc-isigmet awcisigmet $C/ISigmetJSON/items json
awc awc-sigmet awcsigmet $C/SigmetJSON/items json
awc awc-airmet awcairmet $C/AirmetJSON/items json
awc awc-gairmet awcgairmet $C/GairmetJSON/items json
awc awc-cwa awccwa $C/CwaJSON/items json
awc awc-tcf awctcf $C/TcfGeoJSON/$FI json
# The GeoJSON forms of the advisories: one Feature of the collection, on the json wire (the
# geometry is a polygon, which the geojson wire does not carry); no shared key, as above
awc awc-airsigmet-geojson awcairsigmetgeo $C/AirSigmetGeoJSON/$FI json
awc awc-isigmet-geojson awcisigmetgeo $C/ISigmetGeoJSON/$FI json
awc awc-sigmet-geojson awcsigmetgeo $C/SigmetGeoJSON/$FI json
awc awc-gairmet-geojson awcgairmetgeo $C/GairmetGeoJSON/$FI json
awc awc-cwa-geojson awccwageo $C/CwaGeoJSON/$FI json
# Navigational data: the schema gives no descriptions, so nothing is bound
awc awc-airport awcairport '/paths/~1api~1data~1airport/get/responses/200/content/application~1json/schema/items' json
awc awc-navaid awcnavaid '/paths/~1api~1data~1navaid/get/responses/200/content/application~1json/schema/items' json
awc awc-fix awcfix '/paths/~1api~1data~1fix/get/responses/200/content/application~1json/schema/items' json

exit "$STATUS"
