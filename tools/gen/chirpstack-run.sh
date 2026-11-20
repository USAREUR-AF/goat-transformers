#!/bin/bash
# Regenerate the chirpstack-* packs: the messages of the ChirpStack v4 API that travel
# between gateway, network server and application. They come from the protobuf files of
# chirpstack/chirpstack: the gateway messages (package gw), the integration events and
# the downlink command (package integration), and the stream records (package stream).
#
# Usage: tools/gen/chirpstack-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary copy of
# its model/, packs/ and tools/gen/names/, the copy is compared with <checkout>, every file
# that differs is listed and the exit status is 1 when there is one.
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words
# (tools/gen/notes/chirpstack.md). The schema files are not kept in the repository.
#
#   <sources>/chirpstack   a checkout of github.com/chirpstack/chirpstack at tag v4.20.0,
#     commit 8b5688584c60fca78ae756d90a54f681faa5bee6. Read: api/proto/common/common.proto,
#     api/proto/gw/gw.proto, api/proto/integration/integration.proto and the four files of
#     api/proto/stream/. MIT License (LICENSE, "Copyright (c) 2022 Orne Brocaar").
#   <sources>/protobuf-wkt/google/protobuf/struct.proto   src/google/protobuf/struct.proto of
#     github.com/protocolbuffers/protobuf at tag v36.2, commit
#     2c74169b34066ceb8ddb6b882fcb3fb32d737a55 (BSD 3-Clause, LICENSE "Copyright 2008 Google
#     Inc."), which gw.proto and integration.proto import. timestamp.proto and
#     duration.proto are the generator's built-in copies.
#
# Not generated: the gRPC management API of api/proto/api/ (requests and responses of the
# services that create, list and update tenants, applications and devices), and the
# messages ChirpStack keeps to itself (api/proto/internal/).
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
2c92517e786d83bd05fe6b510b8df7d252097a854e7e9f009ed18a57cd874e70  chirpstack/api/proto/common/common.proto
227fda5fd77fb115cb00610fb1ea1fa87c3112d972fc6534342dc7083a6dc12b  chirpstack/api/proto/gw/gw.proto
54415137adbd75a4c175b074744a3afcdb9791124451ab4b70651e8e0f3783e6  chirpstack/api/proto/integration/integration.proto
127ad5467743c3a58e98299b801f14e8f2e5d8f17fad7f90393b5e2ec60cdedb  chirpstack/api/proto/stream/api_request.proto
0c8f011dbfe309df6d88eafa9014437391419cd43132befa0c26d5e5e207843e  chirpstack/api/proto/stream/backend_interfaces.proto
6f4b57de6c78cd5925abc293a556913274100c69600308037ba60875177ef7b0  chirpstack/api/proto/stream/frame.proto
cb0c40baf2377625e361488f96a1233e6d91bde4bbe4a01827b0ecc9cfe1559c  chirpstack/api/proto/stream/meta.proto
85d5dd93079588f3fa33b5affe431223de4036f66ffb76253efe930bc2d39696  protobuf-wkt/google/protobuf/struct.proto
SUMS
TAG=v4.20.0
COMMIT=8b5688584c60fca78ae756d90a54f681faa5bee6
PB=2c74169b34066ceb8ddb6b882fcb3fb32d737a55
P="$SRC/chirpstack/api/proto"
PROTO=("$P/common/common.proto" "$P/gw/gw.proto" "$P/integration/integration.proto"
       "$P/stream/api_request.proto" "$P/stream/backend_interfaces.proto" "$P/stream/frame.proto"
       "$P/stream/meta.proto" "$SRC/protobuf-wkt/google/protobuf/struct.proto")
# <package>.<message>:<pack name without the chirpstack- prefix>[:<extra generator option>]
# gw.Command is one layout (--one-layout): two of its oneof members are messages with no
# field, which cannot each be a kind.
PACKS=(
  gw.Event:gw-event
  gw.Command:gw-command:--one-layout
  gw.UplinkFrame:gw-uplink-frame
  gw.UplinkFrameSet:gw-uplink-frame-set
  gw.DownlinkFrame:gw-downlink-frame
  gw.DownlinkTxAck:gw-downlink-tx-ack
  gw.GatewayStats:gw-gateway-stats
  gw.GatewayConfiguration:gw-gateway-configuration
  gw.GatewayCommandExecRequest:gw-gateway-command-exec-request
  gw.GatewayCommandExecResponse:gw-gateway-command-exec-response
  gw.RawPacketForwarderEvent:gw-raw-packet-forwarder-event
  gw.RawPacketForwarderCommand:gw-raw-packet-forwarder-command
  gw.ConnState:gw-conn-state
  gw.MeshEvent:gw-mesh-event
  gw.MeshCommand:gw-mesh-command
  gw.GetGatewayIdResponse:gw-get-gateway-id-response
  gw.GetLocationResponse:gw-get-location-response
  integration.UplinkEvent:integration-uplink-event
  integration.JoinEvent:integration-join-event
  integration.AckEvent:integration-ack-event
  integration.TxAckEvent:integration-tx-ack-event
  integration.LogEvent:integration-log-event
  integration.StatusEvent:integration-status-event
  integration.LocationEvent:integration-location-event
  integration.DownlinkCommand:integration-downlink-command
  stream.ApiRequestLog:stream-api-request-log
  stream.BackendInterfacesRequest:stream-backend-interfaces-request
  stream.UplinkFrameLog:stream-uplink-frame-log
  stream.DownlinkFrameLog:stream-downlink-frame-log
  stream.UplinkMeta:stream-uplink-meta
  stream.DownlinkMeta:stream-downlink-meta
)
for p in "${PACKS[@]}"; do
  msg="${p%%:*}"
  rest="${p#*:}"
  name="${rest%%:*}"
  extra=()
  [ "$rest" != "$name" ] && extra=("${rest#*:}")
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "${PROTO[@]}" \
    --envelope "$msg" --format "chirpstack-$name" --module "chirpstack${name//-/}" \
    --source "ChirpStack v4 API, protobuf: github.com/chirpstack/chirpstack tag $TAG, commit $COMMIT, api/proto (common, gw, integration, stream); envelope $msg; field numbers, names and types only" \
    --source "LICENSE at that commit: The MIT License (MIT), Copyright (c) 2022 Orne Brocaar" \
    --source "google/protobuf/struct.proto: github.com/protocolbuffers/protobuf tag v36.2, commit $PB, BSD 3-Clause License, Copyright 2008 Google Inc." \
    --names-file "$NAMES/chirpstack-$name.json" \
    --notes-file "$GEN/notes/chirpstack.md" ${extra[@]+"${extra[@]}"} > /dev/null
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "chirpstack-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "chirpstack-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
