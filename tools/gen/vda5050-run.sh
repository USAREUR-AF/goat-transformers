#!/bin/bash
# Regenerate the VDA 5050 packs: one per message (MQTT topic) of VDA 5050 version 3.0.0,
# the interface between fleet control and mobile robots, from its JSON schemas.
#
# Usage: tools/gen/vda5050-run.sh [--check] [--fetch] <checkout> <sources>
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def,
# model/track.def) and written: model/<module>.def,
# packs/<format>/{pack.def,pack.md,vectors/gen-*.json} and tools/gen/names/<format>.json
# of the eight packs below. PROVENANCE.md is not generated.
#
# <sources> receives the schema files. With --fetch, a missing file is downloaded from
#   https://raw.githubusercontent.com/VDA5050/VDA5050/<commit>/json_schemas/<name>
# Every file is checked against the SHA-256 below before it is read; a mismatch stops the
# run. The files are not kept in this repository.
#
# The commit is the head of the default branch when read (2026-11-20). It is not the tag
# 3.0.0: at that tag three of the eight schema files (factsheet, order, visualization)
# are not valid JSON (a comma before a closing brace); the branch has the fixes made since
# and still describes version 3.0.0. The repository's LICENSE.txt is the MIT License
# (packs/vda5050-state/PROVENANCE.md quotes it).
set -euo pipefail
CHECK=""
FETCH=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --check) CHECK="--check"; shift ;;
    --fetch) FETCH=1; shift ;;
    *) break ;;
  esac
done
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] [--fetch] <checkout> <sources>" >&2
  exit 2
fi
CHECKOUT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
COMMIT=f480c4020c91577841400b27390e8eb38120e434

# name sha256
FILES="
connection.schema 50710e678b56ddeffe2af7f3c87687abd20f425d62235e05809895074abbd555
factsheet.schema fb3290b804b6879c26d58d94f1185453f67e5050acc9182334fbb23c7e922556
instantActions.schema 230bfcab4617fb9e8b93c1b9c18c99da43b1c80619e3a1ecc8daa926cd792450
order.schema 3d8b37a6660d72dd8c581f8df583cb722a04a0b03f9fc9e7c4c59897fe29d902
responses.schema 780232b5867256fac4d995233435439b053a025c8e1f053d860bd17520fd3496
state.schema 9cb308fb2b59c591f518dabd32f030430e26963e5ad38e08d199eb1650dfc061
visualization.schema 785223c024b1b9a7efd2596bb8455e76f5b0a08bbdcd8a140990a53ecce32608
zoneSet.schema 4050df2a0821f9313e89a85c33ad702ec54b693b205196aaab557a318276efae
"
while read -r name sha; do
  [ -n "$name" ] || continue
  if [ ! -f "$SRC/$name" ]; then
    if [ "$FETCH" != 1 ]; then
      echo "missing $SRC/$name (run with --fetch to download it)" >&2
      exit 1
    fi
    curl -fsSL -o "$SRC/$name" "https://raw.githubusercontent.com/VDA5050/VDA5050/$COMMIT/json_schemas/$name"
  fi
  got="$(sha256sum "$SRC/$name" | cut -d' ' -f1)"
  if [ "$got" != "$sha" ]; then
    echo "$name: sha256 $got, expected $sha" >&2
    exit 1
  fi
done <<< "$FILES"

EV_TIME="the header member timestamp: the schema gives the form YYYY-MM-DDTHH:mm:ss.fffZ, and the VDA 5050 document's header table states it is ISO 8601 in UTC, so epoch milliseconds UTC with no loss"
EV_UID="the header member serialNumber: the VDA 5050 document states it is the mobile robot's unique serial number (letters, digits and the characters _ . : -), and the MQTT topic of every message names the robot by it"
STATUS=0

# vda <format> <module> <schema file> <title of the message>
vda() {
  local f="$SRC/$3" k="${3%.schema}"
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$f" --message "$k=$f" \
      --map "$k:timestamp=time_ms" --evidence "$k:timestamp=$EV_TIME" \
      --map "$k:serialNumber=uid" --evidence "$k:serialNumber=$EV_UID" \
      --format "$1" --module "$2" \
      --title "VDA 5050 version 3.0.0, $4 (JSON schema json_schemas/$3)" \
      --license "MIT, Copyright 2024 Verband der Automobilindustrie (LICENSE.txt of github.com/VDA5050/VDA5050)" \
      --source "https://github.com/VDA5050/VDA5050 at commit $COMMIT, json_schemas/$3" \
      --source "VDA 5050 version 3.0.0, VDA5050_EN.md of the same commit (meaning of the header members)" \
      --version 0.1.0 \
      --out "$CHECKOUT" --model-dir "$CHECKOUT/model" \
      --names-file "$GEN/names/$1.json" --notes-file "$GEN/notes/vda5050.md" \
      ${CHECK:+"$CHECK"} > /dev/null; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

vda vda5050-connection vda5050connection connection.schema "connection message (broker or mobile robot to fleet control)"
vda vda5050-factsheet vda5050factsheet factsheet.schema "factsheet message (mobile robot to fleet control)"
vda vda5050-instant-actions vda5050instantactions instantActions.schema "instant actions message (fleet control to mobile robot)"
vda vda5050-order vda5050order order.schema "order message (fleet control to mobile robot)"
vda vda5050-responses vda5050responses responses.schema "responses message (fleet control to mobile robot)"
vda vda5050-state vda5050state state.schema "state message (mobile robot to fleet control)"
vda vda5050-visualization vda5050visualization visualization.schema "visualization message (mobile robot to visualization systems)"
vda vda5050-zone-set vda5050zoneset zoneSet.schema "zone set message (fleet control to mobile robot)"
exit "$STATUS"
