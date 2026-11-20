#!/bin/bash
# Regenerate the aisstream.io pack (aisstream): the JSON message the aisstream.io websocket
# sends, one kind per AIS message type.
#
# Usage: tools/gen/aisstream-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/ais-message-models is a git checkout of
# https://github.com/aisstream/ais-message-models at commit
# 8650fc5bf8c308264bc0c18e9ddc83c3ec5d10b8 (the head of its default branch; its tag
# v0.1.0 is an earlier commit) (the script checks). The script reads type-definition.yaml,
# an OpenAPI 3.0 document. Its README says the project is under the MIT License and names
# a LICENSE file that the repository does not have; its package.json says ISC. The pack is
# labelled LicenseRef-unstated.
#
# The envelope (AisStreamMessage) has one member under `Message` per message type. So that
# each kind maps only its own member, the script writes, into a temporary directory, a
# wrapper schema with one envelope per type that refers to the type's schema in
# type-definition.yaml (copied next to it, unchanged; its SHA-256 is checked). The wrapper
# is this project's text; its SHA-256 is in pack.md.
#
# Writes model/aisstream.def, packs/aisstream/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-aisstream.json and tools/gen/names/aisstream.json.
# PROVENANCE.md is not generated. With --check nothing is written and the exit status is 1
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
COMMIT=8650fc5bf8c308264bc0c18e9ddc83c3ec5d10b8
SHA=0c7492a6fbea64bf858401dbf2ac5bc8ea7482b5e88b8c8d19a366d609ed69ac
got="$(git -C "$SRC/ais-message-models" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "ais-message-models is at $got, not $COMMIT" >&2; exit 1; }
F="$SRC/ais-message-models/type-definition.yaml"
got="$(sha256sum "$F" | cut -d' ' -f1)"
[ "$got" = "$SHA" ] || { echo "$F: sha256 $got, expected $SHA" >&2; exit 1; }
T="$(mktemp -d)"
trap 'rm -rf -- "$T"' EXIT
cp "$F" "$T/type-definition.yaml"

# The message types, PositionReport first: encode from another format takes the first
# kind, and PositionReport is the type whose position is bound. DataLinkManagementMessageData
# is listed by the document but has no schema there, so it is not a kind.
TYPES="PositionReport StandardClassBPositionReport ExtendedClassBPositionReport BaseStationReport
ShipStaticData StaticDataReport AidsToNavigationReport StandardSearchAndRescueAircraftReport
LongRangeAisBroadcastMessage AddressedSafetyMessage SafetyBroadcastMessage
AddressedBinaryMessage BinaryBroadcastMessage SingleSlotBinaryMessage MultiSlotBinaryMessage
BinaryAcknowledge CoordinatedUTCInquiry Interrogation AssignedModeCommand
GroupAssignmentCommand DataLinkManagementMessage ChannelManagement GnssBroadcastBinaryMessage
UnknownMessage"
python3 -I - "$T/aisstream-envelopes.json" $TYPES <<'PY'
import json, sys
out, types = sys.argv[1], sys.argv[2:]
defs = {}
for t in types:
    defs[t] = {
        "type": "object",
        "required": ["MessageType", "MetaData", "Message"],
        "properties": {
            "MessageType": {"type": "string"},
            "MetaData": {"type": "object"},
            "Message": {"type": "object", "required": [t],
                        "properties": {t: {"$ref": "type-definition.yaml#/components/schemas/" + t}}},
        },
    }
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    json.dump({"$comment": "goat-transformers wrapper: one AisStreamMessage envelope per message type",
               "definitions": defs}, fh, indent=1, sort_keys=True)
    fh.write("\n")
PY
cd "$W"

ARGS=()
for t in $TYPES; do
  ARGS+=(--message "$t=$T/aisstream-envelopes.json#/definitions/$t" --kind-when "$t:MessageType=$t")
done
P=PositionReport
python3 -I "$GEN/jsonschema2pack.py" --schema "$T/aisstream-envelopes.json" "$T/type-definition.yaml" \
  "${ARGS[@]}" \
  --map $P:Message.$P.Latitude=lat --map $P:Message.$P.Longitude=lon \
  --evidence "$P:Message.$P.Latitude=latitude in decimal degrees (aisstream.io documentation, PositionReport); an AIS position is WGS 84" \
  --evidence "$P:Message.$P.Longitude=longitude in decimal degrees (aisstream.io documentation, PositionReport); an AIS position is WGS 84" \
  --format aisstream --module aisstream \
  --title "aisstream.io websocket message models (ais-message-models type-definition.yaml, OpenAPI 3.0)" \
  --license "LicenseRef-unstated: README names the MIT License, no LICENSE file; package.json says ISC" \
  --source "https://github.com/aisstream/ais-message-models at commit $COMMIT" \
  --source "https://aisstream.io/documentation (units of PositionReport, read 2026-11-20)" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/aisstream.json" \
  --notes-file "$GEN/notes/aisstream.md" \
  --cross "$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input" \
  ${CHECK:+"$CHECK"}
