#!/bin/bash
# Regenerate the three XSD packs.
#
# Usage: tools/gen/xsd2pack-run.sh [--check] <root> <goat-transformers checkout>
#
# <root> holds sources/ and receives model/ and packs/: the three packs, and under
# packs/cot-xml/vectors the vectors gen-cot-xml-to-uci.json and gen-cot-xml-to-a-gra.json.
# The checkout supplies model/core.def, model/track.def and the cot-xml pack with its
# round-trip vector; the names files beside this script (names/) are read and extended.
# Copy model/{uci,agra,isaxml}.def, packs/{uci,a-gra,isa-xml}/ and the two cot-xml
# vectors from <root> into the checkout afterwards; PROVENANCE.md files are not generated.
#
# With --check nothing is written: each of the three runs compares what it would write
# with the files under <root> and with its names file, all three runs are made, and the
# exit status is 1 when any file differs. Without it the script stops at the first run
# that fails.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <root> <goat-transformers checkout>" >&2
  exit 2
fi
ROOT="$1"
GT="$2"
GEN="$(cd "$(dirname "$0")" && pwd)"
STATUS=0

# One run of the generator. The three runs do not read one another's output.
xsd2pack() {
  if ! python3 -I "$GEN/xsd2pack.py" "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

xsd2pack \
  --xsd "$ROOT/sources/uci/UCI_MessageDefinitions_v2_6_0.xsd" "$ROOT/sources/uci/UCI_SecurityMarkings_v2_6_0.xsd" \
  --format uci --module uci --out "$ROOT" --model-dir "$GT/model" \
  --title "Universal Command and Control Interface (UCI) schema 002.6.0 message definitions" \
  --message-type-suffix MT \
  --name-drop MessageData \
  --sample "Classification/#text=U" \
  --sample "MessageHeader/Mode/#text=SIMULATION" \
  --map "Entity:MessageData/EntityID/UUID/#text=uid" \
  --map "Entity:MessageData/Kinematics/KinematicsTimeStamp/#text=time_ms" \
  --map "Entity:MessageData/Kinematics/Velocity/NorthSpeed/#text=track.vel_north_ms" \
  --map "Entity:MessageData/Kinematics/Velocity/EastSpeed/#text=track.vel_east_ms" \
  --default-kind Entity --default-requires uid \
  --cross "$GT/packs/cot-xml/pack.def=$GT/packs/cot-xml/vectors/02-cot-roundtrip.json:input" \
  --names-file "$GEN/names/uci.json"

xsd2pack \
  --xsd "$ROOT/sources/a-gra/A-GRA_MessageDefinitions_v6_0_a.xsd" "$ROOT/sources/a-gra/A-GRA_SecurityMarkings_v6_0_a.xsd" \
  --alias "A-GRA_SecurityMarkings_v6_0.xsd=A-GRA_SecurityMarkings_v6_0_a.xsd" \
  --format a-gra --module agra --out "$ROOT" --model-dir "$GT/model" \
  --title "Autonomy Government Reference Architecture (A-GRA) schema 006.0.ASK (6.0a) message definitions" \
  --message-type-suffix MT \
  --name-drop MessageData \
  --sample "Classification/#text=U" \
  --sample "MessageHeader/Mode/#text=SIMULATION" \
  --map "Entity:MessageData/EntityID/UUID/#text=uid" \
  --map "Entity:MessageData/Kinematics/KinematicsTimeStamp/#text=time_ms" \
  --map "Entity:MessageData/Kinematics/Velocity/NorthSpeed/#text=track.vel_north_ms" \
  --map "Entity:MessageData/Kinematics/Velocity/EastSpeed/#text=track.vel_east_ms" \
  --default-kind Entity --default-requires uid \
  --cross "$GT/packs/cot-xml/pack.def=$GT/packs/cot-xml/vectors/02-cot-roundtrip.json:input" \
  --names-file "$GEN/names/a-gra.json"

xsd2pack \
  --xsd "$ROOT/sources/isa-xml/ipl-4.7-6.0.13.xsd" \
  --format isa-xml --module isaxml --out "$ROOT" --model-dir "$GT/model" \
  --title "Integrated Sensor Architecture IPL 4.7 XML schema ipl-4.7-6.0.13.xsd (ISA IPL Format 6.0)" \
  --message-choice Message --message Envelope \
  --names-file "$GEN/names/isa-xml.json"

exit "$STATUS"
