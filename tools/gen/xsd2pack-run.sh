#!/bin/bash
# Regenerate the four XSD packs.
#
# Usage: tools/gen/xsd2pack-run.sh [--check] <root> <goat-transformers checkout>
#
# <root> holds sources/ and receives model/ and packs/: the four packs, and under
# packs/cot-xml/vectors the vectors gen-cot-xml-to-uci.json, gen-cot-xml-to-uci-2.5.json
# and gen-cot-xml-to-a-gra.json.
# The checkout supplies model/core.def, model/track.def and the cot-xml pack with its
# round-trip vector; the names files beside this script (names/) are read and extended.
# Copy model/{uci,uci25,agra,isaxml}.def, packs/{uci,uci-2.5,a-gra,isa-xml}/ and the three cot-xml
# vectors from <root> into the checkout afterwards; PROVENANCE.md files are not generated.
#
# With --check nothing is written: each of the four runs compares what it would write
# with the files under <root> and with its names file, all four runs are made, and the
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

# One run of the generator. The four runs do not read one another's output.
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

# UCI 2.5 (schema 002.5.0, OAC-STD-002 Rev E): the OMS 2.5 message set. The OMS Standard
# OMSC-STD-001 RevM names UCI Schema OAC-STD-002 Rev E as the compatible OMS Message Schema.
# sources/uci-2.5/ holds the two files of directory 03_OAC-STD-002_RevE_UCI_Schema_v2_5 of
# https://github.com/open-arsenal/uci at tag v2.5, commit 093610b7753944059360d3236770ab446d039556.
# Same arguments as uci, its own module and names file.
xsd2pack \
  --xsd "$ROOT/sources/uci-2.5/UCI_MessageDefinitions_v2_5_0.xsd" "$ROOT/sources/uci-2.5/UCI_SecurityMarkings_v2_5_0.xsd" \
  --format uci-2.5 --module uci25 --out "$ROOT" --model-dir "$GT/model" \
  --title "Universal Command and Control Interface (UCI) schema 002.5.0 message definitions (UCI Schema Rev E, the OMS 2.5 message set)" \
  --source "OMS Standard OMSC-STD-001 RevM (OMS 2.5, 22 January 2026) names UCI Schema OAC-STD-002 Rev E as the compatible OMS Message Schema" \
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
  --names-file "$GEN/names/uci-2.5.json"

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
