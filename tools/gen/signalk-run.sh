#!/bin/bash
# Regenerate the Signal K packs: signalk-delta (a delta message), signalk-full (the full
# data model document) and signalk-vessel (one vessel object of the full model, as a
# server returns it for one vessel).
#
# Usage: tools/gen/signalk-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/specification is a git checkout of https://github.com/SignalK/specification at
# tag v1.8.6, commit 739ea90561750a76a7bdb30d5683a628205e1b41 (the script checks). The
# repository's LICENSE is Creative Commons Attribution-ShareAlike 2.0 (SPDX CC-BY-SA-2.0);
# the packs are labelled with it. The SHA-256 of every schema file read is in each pack's
# pack.md and PROVENANCE.md.
#
# Writes model/signalk*.def, packs/signalk-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-signalk-vessel.json and
# tools/gen/names/signalk-*.json. PROVENANCE.md is not generated. With --check nothing is
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
COMMIT=739ea90561750a76a7bdb30d5683a628205e1b41
got="$(git -C "$SRC/specification" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "specification is at $got, not $COMMIT" >&2; exit 1; }
K="$SRC/specification/schemas"
STATUS=0
LICENSE="CC-BY-SA-2.0, Signal K (SignalK/specification)"
SOURCE="https://github.com/SignalK/specification at tag v1.8.6, commit $COMMIT"
cd "$W"

# signalk <format> <module> <title> [options...]
signalk() {
  local fmt="$1" mod="$2" title="$3"
  shift 3
  if ! python3 -I "$GEN/jsonschema2pack.py" \
      --format "$fmt" --module "$mod" --title "Signal K 1.8.6 JSON Schema: $title" \
      --license "$LICENSE" --source "$SOURCE" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
# vessel.json and signalk.json refer to definitions.json and to the group schemas.
GRP=$(cd "$SRC" && ls specification/schemas/groups/*.json | LC_ALL=C sort | sed "s|^|$SRC/|")

signalk signalk-delta signalkdelta "delta message (delta.json)" \
  --schema "$K/delta.json" "$K/definitions.json" --message Delta="$K/delta.json"

signalk signalk-full signalkfull "full data model document (signalk.json)" \
  --schema "$K/signalk.json" "$K/definitions.json" "$K/vessel.json" "$K/aircraft.json" "$K/aton.json" $GRP \
  --message Full="$K/signalk.json"

V="Vessel"
signalk signalk-vessel signalkvessel "one vessel object of the full model (vessel.json)" \
  --schema "$K/vessel.json" "$K/definitions.json" $GRP --message $V="$K/vessel.json" \
  --map $V:uuid=uid --map $V:name=callsign \
  --map $V:navigation.position.value.latitude=lat --map $V:navigation.position.value.longitude=lon \
  --map $V:navigation.position.timestamp=time_ms --map $V:navigation.speedOverGround.value=speed_ms \
  --evidence "$V:uuid=the identifier the server gives the vessel, a Signal K URN; stable for the vessel" \
  --evidence "$V:name=the vessel's common name, a human-readable name" \
  --evidence "$V:navigation.position.value.latitude=latitude in degrees (units deg), WGS 84 datum stated by navigation.position" \
  --evidence "$V:navigation.position.value.longitude=longitude in degrees (units deg), WGS 84 datum stated by navigation.position" \
  --evidence "$V:navigation.position.timestamp=the time of the position value, an RFC 3339 UTC date-time" \
  --evidence "$V:navigation.speedOverGround.value=speed over ground in metres per second (units m/s)" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"

exit "$STATUS"
