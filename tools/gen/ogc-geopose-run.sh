#!/bin/bash
# Regenerate the OGC GeoPose 1.0 Data Exchange packs (JSON encodings).
# Usage: tools/gen/ogc-geopose-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/GeoPose is a checkout of https://github.com/opengeospatial/GeoPose at commit
# cc8a239c8f59bb4579e250a97a3512f8459e5113 (the script checks it), standard/standard/schemata.
# License: the LICENSE of the repository and of standard/standard, the Apache License 2.0
# (SHA-256 b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1). The SHA-256 of
# every schema file read is in each pack.md.
#
# Basic GeoPose: position (lat, lon, h in the EPSG 4979 outer frame) to lat, lon, hae.
# Advanced GeoPose and the stream element: validTime (integer UNIX milliseconds) to time_ms.
#
# Writes model/ogcgp*.def, packs/ogc-geopose-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/ogc-geopose-*.json. PROVENANCE.md is not generated. With --check nothing is
# written; every run is made and the exit status is 1 when any file differs.
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
check() {
  local got
  got="$(git -C "$SRC/$1" rev-parse HEAD)"
  [ "$got" = "$2" ] || { echo "$1 is at $got, not $2" >&2; exit 1; }
}
# gen <format> <module> <title> [options...]
gen() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$LICENSE" --source "$SOURCE" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
check GeoPose cc8a239c8f59bb4579e250a97a3512f8459e5113
LICENSE="Apache-2.0, Open Geospatial Consortium (opengeospatial/GeoPose)"
SOURCE="https://github.com/opengeospatial/GeoPose at commit cc8a239c8f59bb4579e250a97a3512f8459e5113, standard/standard/schemata"
G="$SRC/GeoPose/standard/standard/schemata"
cd "$W"

POS=(--map "Pose:position.lat=lat" --map "Pose:position.lon=lon" --map "Pose:position.h=hae")
gen ogc-geopose-basic-ypr ogcgpypr "OGC GeoPose 1.0, Basic-YPR (GeoPose.Basic.YPR.Schema.json)" \
  --schema "$G/GeoPose.Basic.YPR.Schema.json" --message Pose="$G/GeoPose.Basic.YPR.Schema.json" "${POS[@]}"
gen ogc-geopose-basic-quaternion ogcgpq "OGC GeoPose 1.0, Basic-Quaternion (GeoPose.Basic.Quaternion.Schema.json)" \
  --schema "$G/GeoPose.Basic.Quaternion.Schema.json" --message Pose="$G/GeoPose.Basic.Quaternion.Schema.json" "${POS[@]}"
gen ogc-geopose-advanced ogcgpadv "OGC GeoPose 1.0, Advanced (GeoPose.Advanced.Schema.json)" \
  --schema "$G/GeoPose.Advanced.Schema.json" --message Pose="$G/GeoPose.Advanced.Schema.json" \
  --map Pose:validTime=time_ms
gen ogc-geopose-stream-element ogcgpse "OGC GeoPose 1.0, stream element (GeoPose.Composite.Sequence.StreamElement.Schema.json)" \
  --schema "$G/GeoPose.Composite.Sequence.StreamElement.Schema.json" \
  --message Element="$G/GeoPose.Composite.Sequence.StreamElement.Schema.json" \
  --map Element:streamElement.validTime=time_ms

exit "$STATUS"
