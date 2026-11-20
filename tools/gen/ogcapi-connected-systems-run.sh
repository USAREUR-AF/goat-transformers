#!/bin/bash
# Regenerate the OGC API - Connected Systems 1.0.0 packs (Part 1: Feature Resources, GeoJSON
# encoding; Part 2: Dynamic Data, JSON encoding).
# Usage: tools/gen/ogcapi-connected-systems-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/cs-1.0.0 is a checkout of https://github.com/opengeospatial/ogcapi-connected-systems
# at tag v1.0.0, commit 8e03b236a049849f2ccc24b4fd9fdce5ff69bed2 (the script checks it).
# License: the repository's LICENSE, the OGC Software License (SHA-256
# b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1), quoted in each
# pack's PROVENANCE.md. The SHA-256 of every schema file read is in each pack.md.
#
# The GeoJSON features (system, deployment, procedure, sampling feature) are on the geojson
# wire; their Feature structure (https://geojson.org/schema/Feature.json) is the wire's own
# (--opaque). The SensorML JSON encodings of Part 1 and the SWE Common encodings of Part 2
# (observations as SWE Common text, binary or protobuf) are not generated.
#
# Writes model/ogccs*.def, packs/ogcapi-cs-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-ogcapi-cs-*.json and tools/gen/names/ogcapi-cs-*.json.
# PROVENANCE.md is not generated. With --check nothing is written; every run is made and
# the exit status is 1 when any file differs.
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
got="$(git -C "$SRC/cs-1.0.0" rev-parse HEAD)"
[ "$got" = 8e03b236a049849f2ccc24b4fd9fdce5ff69bed2 ] || { echo "cs-1.0.0 is at $got" >&2; exit 1; }
LICENSE="OGC Software License (Open Geospatial Consortium, opengeospatial/ogcapi-connected-systems LICENSE); this pack is a modification that OGC has not approved or adopted"
SC="https://github.com/opengeospatial/ogcapi-connected-systems at tag v1.0.0, commit 8e03b236a049849f2ccc24b4fd9fdce5ff69bed2"
C="$SRC/cs-1.0.0"
P1="$C/api/part1/openapi/schemas"
P2="$C/api/part2/openapi/schemas"
cd "$W"

gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$SC" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
# files <dir>: every .json file of the directory under $C, sorted
files() { (cd "$C/$1" && LC_ALL=C ls -- *.json) | sed "s|^|$C/$1/|"; }
# shellcheck disable=SC2207
COMMON1=("$P1/common/commonDefs.json" "$P1/common/links.json" "$P1/common/uris.json"
  "$C/common/link.json" "$C/common/timeInstant.json" "$C/common/timePeriod.json")
# shellcheck disable=SC2207
COMMON2=("$P2/common/commonDefs.json" "$P1/common/links.json" "$P1/common/commonDefs.json"
  "$C/common/link.json" "$C/common/timeInstant.json" "$C/common/timeInstantOrNow.json" "$C/common/timePeriod.json")
# shellcheck disable=SC2207
SWE=("$P2/common/sweCommonDefs.json" $(files swecommon/schemas/json))
# shellcheck disable=SC2207
SML=("$P2/common/sensormlDefs.json" $(files sensorml/schemas/json))
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"

# Part 1, GeoJSON features: <format> <module> <file> <Kind> [options...]
feature() {
  local fmt="$1" mod="$2" file="$3" kind="$4"
  shift 4
  gen "$fmt" "$mod" "OGC API - Connected Systems - Part 1 1.0.0, $kind as GeoJSON (api/part1/openapi/schemas/geojson/$file)" \
    --schema "$P1/geojson/$file" "$P1/geojson/feature.json" "${COMMON1[@]}" --opaque https://geojson.org/schema/ \
    --message "$kind=$P1/geojson/$file" --wire geojson --top-level-members id \
    --map "$kind:properties.uid=uid" --map "$kind:properties.name=callsign" --cross "$XG" "$@"
}
# point <Kind>: the geometry, where the standard gives the feature a location
point() { echo --map "$1:geometry.lon=lon" --map "$1:geometry.lat=lat" --map "$1:geometry.alt=hae"; }
# shellcheck disable=SC2046
feature ogcapi-cs-system ogccssys system.json System $(point System)
# shellcheck disable=SC2046
feature ogcapi-cs-deployment ogccsdep deployment.json Deployment $(point Deployment)
# A procedure has no location (the GeoJSON encoding maps no attribute to `geometry`)
feature ogcapi-cs-procedure ogccsproc procedure.json Procedure
# shellcheck disable=SC2046
feature ogcapi-cs-sampling-feature ogccssf samplingFeature.json SamplingFeature $(point SamplingFeature)

# Part 2, JSON encodings: <format> <module> <file> <Kind> [options...]
dyn() {
  local fmt="$1" mod="$2" file="$3" kind="$4"
  shift 4
  gen "$fmt" "$mod" "OGC API - Connected Systems - Part 2 1.0.0, $kind (api/part2/openapi/schemas/json/$file)" \
    --schema "$P2/json/$file" "${COMMON2[@]}" "$@" --opaque https://geojson.org/schema/ --message "$kind=$P2/json/$file"
}
# The `<name>@link` members are Link objects. Their members would have json locators of the
# form name, `@`, `link`, `.`, member, which the boundary gate reads as an e-mail address and
# refuses; so in the five messages that have them, no object member is mapped (--max-depth 1).
FLAT=(--max-depth 1 --limit-reason "the members of an object inside the message are not mapped: the Link objects (members named with the suffix @link) would need json locators that the boundary gate refuses as e-mail addresses")
dyn ogcapi-cs-observation ogccsobs observation.json Observation "${FLAT[@]}" \
  --map Observation:id=uid --map Observation:phenomenonTime=time_ms
# shellcheck disable=SC2207
OBS_SCHEMA=($(cd "$P2/json" && LC_ALL=C ls observationSchema*.json dataStreamSchemaDef.json | sed "s|^|$P2/json/|"))
# The SensorML and SWE Common component trees of an event are thousands of members deep in
# the schema; they are not mapped below the third level.
DEEP=(--max-depth 3 --limit-reason "the SensorML and SWE Common component trees inside the event are not mapped below the third level, which keeps the pack to the members of the API itself")
dyn ogcapi-cs-datastream ogccsds dataStream.json DataStream "$P2/json/baseStream.json" "${OBS_SCHEMA[@]}" "${SWE[@]}" "${FLAT[@]}"
# shellcheck disable=SC2207
CMD_SCHEMA=($(cd "$P2/json" && LC_ALL=C ls commandSchema*.json | sed "s|^|$P2/json/|"))
dyn ogcapi-cs-controlstream ogccscs controlStream.json ControlStream "$P2/json/baseStream.json" "${CMD_SCHEMA[@]}" "${SWE[@]}" "${FLAT[@]}"
dyn ogcapi-cs-command ogccscmd command.json Command "$P2/json/commandStatusCode.json" "${FLAT[@]}"
dyn ogcapi-cs-command-status ogccscst commandStatus.json CommandStatus "$P2/json/commandStatusCode.json" "$P2/json/commandResult.json" "${FLAT[@]}"
dyn ogcapi-cs-system-event ogccsev systemEvent.json SystemEvent "${SML[@]}" "${SWE[@]}" "${DEEP[@]}"

exit "$STATUS"
