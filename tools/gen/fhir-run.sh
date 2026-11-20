#!/bin/bash
# Regenerate the HL7 FHIR R4 (4.0.1) resource packs: fhir-r4-<resource>, one per resource type.
# Usage: tools/gen/fhir-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds fhir.schema.json of FHIR R4 4.0.1, taken from the definitions bundle:
#   https://hl7.org/fhir/R4/definitions.json.zip
#     sha256 ecd74b1d57d86869992b4171e490d1a3fcebb8877110756b73f7be0f7159f534
#     version.info: FhirVersion=4.0.1-9346c8cc45, date=20191101092923
#   which holds fhir.schema.json.zip (sha256 75e5560da3cf503895a44c8ca7af17a83b4cca6c2cb5ba1883d2aec0d1cb5ac6),
#   which holds fhir.schema.json (sha256 2230406893b4cf002a4ee1e5e2bbeca22ac5d2d4931b3e9ef7b9594bbc376a01).
# FHIR is licensed CC0 (https://hl7.org/fhir/R4/license.html). The script checks the SHA-256.
#
# Writes, per resource type <R> (the members of the schema's resourceType discriminator):
#   model/fhirr4<r>.def, packs/fhir-r4-<r>/ (pack.def, pack.md, vectors/gen-*) and
#   tools/gen/names/fhir-r4-<r>.json; for Location also
#   packs/geojson/vectors/gen-geojson-to-fhir-r4-location.json. PROVENANCE.md is written
#   by this script (the same text for every pack).
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
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
F="$SRC/fhir.schema.json"
SUM="$(sha256sum "$F" | cut -d' ' -f1)"
[ "$SUM" = 2230406893b4cf002a4ee1e5e2bbeca22ac5d2d4931b3e9ef7b9594bbc376a01 ] || { echo "$F has sha256 $SUM" >&2; exit 1; }
STATUS=0

DEPTH="FHIR datatypes and backbone elements nest without bound (Reference.identifier.assigner is a Reference); three levels hold a resource's elements, the members of its datatypes and of its backbone elements, and an array inside two arrays is not mapped"
OMIT="every element may carry extension and modifierExtension (arrays of Extension, whose value[x] is any datatype), every primitive a _<name> sibling holding its id and extensions, and contained holds whole resources of any type; walked, they would multiply each pack many times over, so they are not mapped and the json wire drops their arrays"
EV_ID="the logical id of the resource on its server, which once assigned never changes: the stable identifier of the entity"
EV_LU="the instant the resource last changed, an instant with seconds and a time zone (FHIR instant), read with iso8601_ms; the raw key keeps the text"
EV_LAT="Location.position states its coordinates in the WGS 84 datum, latitude in decimal degrees as KML gives it"
EV_LON="Location.position states its coordinates in the WGS 84 datum, longitude in decimal degrees as KML gives it"

for R in $(python3 -I -c 'import json,sys; print(" ".join(sorted(json.load(open(sys.argv[1]))["discriminator"]["mapping"])))' "$F"); do
  r="$(python3 -I -c 'import re,sys; print(re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", sys.argv[1]).lower())' "$R")"
  m="fhirr4$(echo "$R" | tr 'A-Z' 'a-z')"
  EXTRA=()
  if [ "$R" = Location ]; then
    EXTRA=(--map "Location:position.latitude=lat" --evidence "Location:position.latitude=$EV_LAT"
           --map "Location:position.longitude=lon" --evidence "Location:position.longitude=$EV_LON"
           --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input")
  fi
  if ! python3 -I "$GEN/jsonschema2pack.py" \
      --schema "$F" --message "$R=$F#/definitions/$R" --kind-when "$R:resourceType=$R" \
      --map "$R:id=uid" --evidence "$R:id=$EV_ID" \
      --map "$R:meta.lastUpdated=time_ms" --date-time "$R:meta.lastUpdated" --evidence "$R:meta.lastUpdated=$EV_LU" \
      "${EXTRA[@]}" \
      --max-depth 3 --max-nest 2 --limit-reason "$DEPTH" \
      --omit extension --omit modifierExtension --omit contained --omit-prefix _ --omit-reason "$OMIT" \
      --format "fhir-r4-$r" --module "$m" \
      --title "HL7 FHIR R4 (4.0.1) $R resource, JSON (fhir.schema.json)" \
      --license "CC0-1.0, HL7 FHIR R4 (https://hl7.org/fhir/R4/license.html)" \
      --source "https://hl7.org/fhir/R4/definitions.json.zip (FHIR 4.0.1-9346c8cc45), fhir.schema.json sha256 2230406893b4cf002a4ee1e5e2bbeca22ac5d2d4931b3e9ef7b9594bbc376a01" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/fhir-r4-$r.json" \
      --notes-file "$GEN/notes/fhir-r4.md" ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
  if [ -z "$CHECK" ]; then
    sed "s/@PACK@/fhir-r4-$r/; s/@MODULE@/$m/; s/@RES@/$R/" "$GEN/fhir/provenance.md" > "$W/packs/fhir-r4-$r/PROVENANCE.md"
  elif ! sed "s/@PACK@/fhir-r4-$r/; s/@MODULE@/$m/; s/@RES@/$R/" "$GEN/fhir/provenance.md" | cmp -s - "$W/packs/fhir-r4-$r/PROVENANCE.md"; then
    echo "packs/fhir-r4-$r/PROVENANCE.md differs" >&2
    STATUS=1
  fi
done
exit "$STATUS"
