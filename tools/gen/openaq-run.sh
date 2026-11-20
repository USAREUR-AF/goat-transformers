#!/bin/bash
# Regenerate the OpenAQ API v3 packs, one per response schema (locations, latest,
# measurements, sensors, ...).
#
# Usage: tools/gen/openaq-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/openaq/openapi-2026-11-20.json is the API's OpenAPI 3.1 document as served at
# https://api.openaq.org/openapi.json on 2026-11-20 (info.version 3.0.0). The document has
# no versioned address, so the dated copy is pinned by its SHA-256 below; a later download
# that differs stops the run. It is not kept in this repository. The document states no
# licence; the OpenAQ terms of use (https://docs.openaq.org/about/terms) govern the API.
# The packs are labelled LicenseRef-OpenAQ (LICENSES/LicenseRef-OpenAQ.txt quotes them).
#
# Every response is a json object with `meta` and a `results` group; the items are read
# member by member.
#
# Writes model/openaq*.def, packs/openaq-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/openaq-*.json. PROVENANCE.md is not generated. With --check nothing is
# written (jsonschema2pack --check per run); every run is made and the exit status is 1
# when any file differs.
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
F="$SRC/openaq/openapi-2026-11-20.json"
SHA=05873df4fed8e82789aeb14369368950570bb83ffd5f1f9ac1b700328a942b7e
got="$(sha256sum "$F" | cut -d' ' -f1)"
[ "$got" = "$SHA" ] || { echo "$F: sha256 $got, expected $SHA" >&2; exit 1; }
STATUS=0
TITLE="OpenAQ API v3 OpenAPI 3.1 document (info.version 3.0.0), copy of https://api.openaq.org/openapi.json served 2026-11-20"
LICENSE="LicenseRef-OpenAQ: OpenAQ terms of use, https://docs.openaq.org/about/terms"
cd "$W"

# openaq <format> <module> <schema>
openaq() {
  local fmt="$1" mod="$2" schema="$3"
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$F" \
      --message "$schema=$F#/components/schemas/$schema" \
      --format "$fmt" --module "$mod" --title "$TITLE; schema $schema" --license "$LICENSE" \
      --source "https://api.openaq.org/openapi.json (OpenAPI 3.1), components.schemas.$schema" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/openaq.md" \
      ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

openaq openaq-locations openaqloc LocationsResponse
openaq openaq-latest openaqlatest LatestResponse
openaq openaq-measurements openaqmeas MeasurementsResponse
openaq openaq-hourly openaqhourly HourlyDataResponse
openaq openaq-daily openaqdaily DailyDataResponse
openaq openaq-annual openaqannual AnnualDataResponse
openaq openaq-sensors openaqsensors SensorsResponse
openaq openaq-location-flags openaqflags LocationFlagsResponse
openaq openaq-parameters openaqparams ParametersResponse
openaq openaq-countries openaqcountries CountriesResponse
openaq openaq-providers openaqproviders ProvidersResponse
openaq openaq-owners openaqowners OwnersResponse
openaq openaq-manufacturers openaqmfr ManufacturersResponse
openaq openaq-instruments openaqinstr InstrumentsResponse
openaq openaq-licenses openaqlicenses LicensesResponse

exit "$STATUS"
