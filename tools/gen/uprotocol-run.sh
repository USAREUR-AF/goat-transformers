#!/bin/bash
# Regenerate the uprotocol-* packs: one pack per message of the Eclipse uProtocol core API
# (up-spec, up-core-api/uprotocol), tag v1.6.0-alpha.7, in its protobuf form.
#
# Usage: tools/gen/uprotocol-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words
# (tools/gen/notes/uprotocol.md).
#
# <sources>/up-core-api/uprotocol/**/*.proto: the 13 files under up-core-api/uprotocol at
# github.com/eclipse-uprotocol/up-spec tag v1.6.0-alpha.7 (commit
# 347d68438afd9e4813193b243dc98fb42963ad99), each
# https://raw.githubusercontent.com/eclipse-uprotocol/up-spec/<commit>/<path>. Each file
# carries an SPDX Apache-2.0 header; LICENSE is Apache-2.0. They are not kept in the repository;
# each pack's PROVENANCE.md has their SHA-256. Every run is given all 13 files;
# google/protobuf/any.proto and timestamp.proto are the generator's built-in copies.
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
TAG=v1.6.0-alpha.7
COMMIT=347d68438afd9e4813193b243dc98fb42963ad99
U="$SRC/up-core-api/uprotocol"
PROTO=("$U/uoptions.proto" "$U"/v1/*.proto "$U"/core/*/*/*.proto)
# <message>:<pack name suffix>
PACKS=(
  uprotocol.core.udiscovery.v3.GetServiceTopicsRequest:udiscovery-v3-get-service-topics-request
  uprotocol.core.udiscovery.v3.GetServiceTopicsResponse:udiscovery-v3-get-service-topics-response
  uprotocol.core.udiscovery.v3.ServiceTopicInfo:udiscovery-v3-service-topic-info
  uprotocol.core.udiscovery.v3.FindServicesRequest:udiscovery-v3-find-services-request
  uprotocol.core.udiscovery.v3.FindServicesResponse:udiscovery-v3-find-services-response
  uprotocol.core.udiscovery.v3.SetServiceTopicsRequest:udiscovery-v3-set-service-topics-request
  uprotocol.core.usubscription.v3.SubscribeAttributes:usubscription-v3-subscribe-attributes
  uprotocol.core.usubscription.v3.SubscriberInfo:usubscription-v3-subscriber-info
  uprotocol.core.usubscription.v3.SubscriptionStatus:usubscription-v3-subscription-status
  uprotocol.core.usubscription.v3.EventDeliveryConfig:usubscription-v3-event-delivery-config
  uprotocol.core.usubscription.v3.SubscriptionRequest:usubscription-v3-subscription-request
  uprotocol.core.usubscription.v3.SubscriptionResponse:usubscription-v3-subscription-response
  uprotocol.core.usubscription.v3.UnsubscribeRequest:usubscription-v3-unsubscribe-request
  uprotocol.core.usubscription.v3.FetchSubscribersRequest:usubscription-v3-fetch-subscribers-request
  uprotocol.core.usubscription.v3.FetchSubscribersResponse:usubscription-v3-fetch-subscribers-response
  uprotocol.core.usubscription.v3.Subscription:usubscription-v3-subscription
  uprotocol.core.usubscription.v3.FetchSubscriptionsRequest:usubscription-v3-fetch-subscriptions-request
  uprotocol.core.usubscription.v3.FetchSubscriptionsResponse:usubscription-v3-fetch-subscriptions-response
  uprotocol.core.usubscription.v3.NotificationsRequest:usubscription-v3-notifications-request
  uprotocol.core.usubscription.v3.Update:usubscription-v3-update
  uprotocol.core.usubscription.v3.PassiveMode:usubscription-v3-passive-mode
  uprotocol.core.usubscription.v3.ResetRequest:usubscription-v3-reset-request
  uprotocol.core.utwin.v2.MessageResponse:utwin-v2-message-response
  uprotocol.core.utwin.v2.GetLastMessagesRequest:utwin-v2-get-last-messages-request
  uprotocol.core.utwin.v2.GetLastMessagesResponse:utwin-v2-get-last-messages-response
  uprotocol.v1.File:v1-file
  uprotocol.v1.FileBatch:v1-file-batch
  uprotocol.v1.Checksum:v1-checksum
  uprotocol.v1.UAttributes:v1-uattributes
  uprotocol.v1.UMessage:v1-umessage
  uprotocol.v1.UUri:v1-uuri
  uprotocol.v1.UUriBatch:v1-uuri-batch
  uprotocol.v1.UStatus:v1-ustatus
)
for spec in "${PACKS[@]}"; do
  msg="${spec%%:*}"; name="${spec#*:}"
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "${PROTO[@]}" \
    --envelope "$msg" --format "uprotocol-$name" --module "uprotocol${name//-/}" \
    --source "Eclipse uProtocol core API $TAG protobuf definitions: github.com/eclipse-uprotocol/up-spec commit $COMMIT, up-core-api/uprotocol (13 .proto files); envelope $msg; field numbers, names and types only" \
    --source "File headers and LICENSE at that commit: Apache License, Version 2.0 (SPDX-License-Identifier: Apache-2.0), Contributors to the Eclipse Foundation" \
    --names-file "$NAMES/uprotocol-$name.json" \
    --notes-file "$GEN/notes/uprotocol.md" > /dev/null
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "uprotocol-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "uprotocol-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
