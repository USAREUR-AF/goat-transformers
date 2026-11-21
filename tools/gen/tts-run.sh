#!/bin/bash
# Regenerate the tts-* packs: the application-facing messages of The Things Stack v3
# (LoRaWAN network server), from the protobuf files of TheThingsNetwork/lorawan-stack:
# ApplicationUp (every event the Application Server hands to an application, one kind per
# member of its oneof), ApplicationDownlink and ApplicationDownlinks (what the application
# pushes to, or replaces in, a device's downlink queue).
#
# Usage: tools/gen/tts-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary copy of
# its model/, packs/ and tools/gen/names/, the copy is compared with <checkout>, every file
# that differs is listed and the exit status is 1 when there is one.
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words
# (tools/gen/notes/tts.md). The schema files are not kept in the repository.
#
#   <sources>/lorawan-stack   a checkout of github.com/TheThingsNetwork/lorawan-stack at tag
#     v3.37.0, commit 0bfcfcd2ef1a38a22ab373894959ac67c79c9a45. Read: messages.proto and the
#     six files it imports from api/ttn/lorawan/v3/ (metadata, lorawan, identifiers, enums,
#     keys, error). Apache License 2.0 (LICENSE; each file's header names The Things Network
#     Foundation, The Things Industries B.V. and the Apache License, Version 2.0).
#     The option files those import, under api/third_party/ (validate/validate.proto,
#     thethings/json/annotations.proto, thethings/flags/annotations.proto,
#     protoc-gen-openapiv2/options/annotations.proto and openapiv2.proto), are given so that
#     every import resolves; they declare field and message options only, which the
#     generator skips, and nothing of them reaches a pack.
#   <sources>/protobuf-wkt/google/protobuf/{struct,wrappers}.proto   src/google/protobuf/ of
#     github.com/protocolbuffers/protobuf at tag v36.2, commit
#     2c74169b34066ceb8ddb6b882fcb3fb32d737a55 (BSD 3-Clause, LICENSE "Copyright 2008 Google
#     Inc."). timestamp.proto, duration.proto and any.proto are the generator's built-in
#     copies.
#
# Shared keys (tools/gen/notes/tts.md): `lat` and `lon` in kind location_solved of
# tts-application-up. Not generated: the gRPC services and the messages of the network
# server, join server, gateway server and identity server.
set -euo pipefail
CHECK=0
if [ "${1:-}" = "--check" ]; then
  CHECK=1
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <checkout> <sources>" >&2
  exit 2
fi
CHECKOUT="$(cd "$1" && pwd)"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ROOT="$CHECKOUT"
NAMES="$GEN/names"
if [ "$CHECK" = 1 ]; then
  ROOT="$TMP/checkout"
  NAMES="$ROOT/tools/gen/names"
  mkdir -p "$ROOT/tools/gen"
  cp -R "$CHECKOUT/model" "$CHECKOUT/packs" "$ROOT/"
  cp -R "$GEN/names" "$NAMES"
fi
(cd "$SRC" && sha256sum --quiet -c -) <<'SUMS'
84730bf32c21714322886899e8cd9fbd4b92a523a5eeaf1f2697b6354e824fdd  lorawan-stack/api/ttn/lorawan/v3/messages.proto
9efeae14a1647acfba4e34ed79fbc3050931030158e2c5d33a1cdc6a92a6f876  lorawan-stack/api/ttn/lorawan/v3/metadata.proto
17b7dbcb5c1ce522a0b9f78aa401c4c1c3078e8fc3d37c155fcda9a2af0c6ccb  lorawan-stack/api/ttn/lorawan/v3/lorawan.proto
1c8b33dcdebaf84f72c3ba5faa13b49ba05bf1208ae05b03a45ea3f048800e16  lorawan-stack/api/ttn/lorawan/v3/identifiers.proto
805882f558104277243338763fb638d33c916ed9e9909dfb00373fdf65226ed2  lorawan-stack/api/ttn/lorawan/v3/enums.proto
82b767f5e7559c82efed4afea99c571e4f0f4fe32d043dc80ac7ca9672640fc5  lorawan-stack/api/ttn/lorawan/v3/keys.proto
813918b1df276ed6ac3989a1c64fd94439771fc5a1ecf4f0ddcb8c737da253f9  lorawan-stack/api/ttn/lorawan/v3/error.proto
aea20025596f3b855acb8da3f683e75035b914e814f290c14aef9cceed4c05c2  lorawan-stack/api/third_party/validate/validate.proto
dfb7023b377f49dd8a21effb03f3f07af6856358ee84c22362d44b64516debeb  lorawan-stack/api/third_party/thethings/json/annotations.proto
627b57f024753ab33b573300d1c058c72fdcc71b0aa3662d16dc4ce0d07f43db  lorawan-stack/api/third_party/thethings/flags/annotations.proto
154344c409a71de28b7c5677d14e96b48a316625cbf40a46531931fec2a72ea3  lorawan-stack/api/third_party/protoc-gen-openapiv2/options/annotations.proto
022d2c1bcec0c962658fe3213226682d87b852f0aec69ce92275cc8c0ea5f8d6  lorawan-stack/api/third_party/protoc-gen-openapiv2/options/openapiv2.proto
85d5dd93079588f3fa33b5affe431223de4036f66ffb76253efe930bc2d39696  protobuf-wkt/google/protobuf/struct.proto
6878dc7534cf9805eee56345cdc38b5e9ca39dece246710c663c7007a67fef49  protobuf-wkt/google/protobuf/wrappers.proto
SUMS
TAG=v3.37.0
COMMIT=0bfcfcd2ef1a38a22ab373894959ac67c79c9a45
PB=2c74169b34066ceb8ddb6b882fcb3fb32d737a55
V="$SRC/lorawan-stack/api/ttn/lorawan/v3"
T="$SRC/lorawan-stack/api/third_party"
PROTO=("$V/messages.proto" "$V/metadata.proto" "$V/lorawan.proto" "$V/identifiers.proto"
       "$V/enums.proto" "$V/keys.proto" "$V/error.proto"
       "$T/validate/validate.proto" "$T/thethings/json/annotations.proto"
       "$T/thethings/flags/annotations.proto" "$T/protoc-gen-openapiv2/options/annotations.proto"
       "$T/protoc-gen-openapiv2/options/openapiv2.proto"
       "$SRC/protobuf-wkt/google/protobuf/struct.proto" "$SRC/protobuf-wkt/google/protobuf/wrappers.proto")
for p in ApplicationUp:application-up ApplicationDownlink:application-downlink \
         ApplicationDownlinks:application-downlinks; do
  msg="${p%%:*}"
  name="${p#*:}"
  extra=()
  if [ "$name" = application-up ]; then
    extra=(--map 11.2.1=lat --map 11.2.2=lon --default-kind location_solved --default-requires lat lon
           --cross-text "$ROOT/packs/geojson/pack.def")
  fi
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "${PROTO[@]}" \
    --envelope "ttn.lorawan.v3.$msg" --format "tts-$name" --module "tts${name//-/}" \
    --source "The Things Stack v3 API, protobuf: github.com/TheThingsNetwork/lorawan-stack tag $TAG, commit $COMMIT, api/ttn/lorawan/v3 (messages and its imports); envelope ttn.lorawan.v3.$msg; field numbers, names and types only" \
    --source "LICENSE at that commit: Apache License, Version 2.0" \
    --source "google/protobuf/struct.proto and wrappers.proto: github.com/protocolbuffers/protobuf tag v36.2, commit $PB, BSD 3-Clause License, Copyright 2008 Google Inc." \
    --names-file "$NAMES/tts-$name.json" \
    --notes-file "$GEN/notes/tts.md" ${extra[@]+"${extra[@]}"} > /dev/null
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "tts-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "tts-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
