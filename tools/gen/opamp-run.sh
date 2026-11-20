#!/bin/bash
# Regenerate the opamp-* packs: the two messages of the Open Agent Management Protocol
# (OpAMP) that travel on the wire, AgentToServer (opamp-agent-to-server) and ServerToAgent
# (opamp-server-to-agent), from the opamp-spec protobuf files.
#
# Usage: tools/gen/opamp-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary copy of
# its model/, packs/ and tools/gen/names/, the copy is compared with <checkout>, every file
# that differs is listed and the exit status is 1 when there is one.
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words
# (tools/gen/notes/opamp.md). The schema files are not kept in the repository.
#
#   <sources>/opamp.proto, <sources>/anyvalue.proto   proto/opamp/v1/opamp.proto and
#     proto/opamp/v1/anyvalue.proto of github.com/open-telemetry/opamp-spec at tag v0.20.0,
#     commit b08624151d000c1ca043b300e1f5e3bc93107987, each
#     https://raw.githubusercontent.com/open-telemetry/opamp-spec/<commit>/proto/opamp/v1/<name>
#     Apache License 2.0 (LICENSE; each file's header names the OpenTelemetry Authors and the
#     Apache License, Version 2.0).
#
# The transport framing (the WebSocket header byte, or the HTTP body) is not part of a pack.
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
b972f1486c480752f4981309f94628aed12b0231c4d0a18a3554647d1884c488  opamp.proto
f0326211aed50272a221e75ada27f31db55266ea65dcd7b7b3d8a0a58934e128  anyvalue.proto
SUMS
TAG=v0.20.0
COMMIT=b08624151d000c1ca043b300e1f5e3bc93107987
for p in AgentToServer:agent-to-server ServerToAgent:server-to-agent; do
  msg="${p%%:*}"
  name="${p#*:}"
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "$SRC/opamp.proto" "$SRC/anyvalue.proto" \
    --envelope "opamp.proto.v1.$msg" --format "opamp-$name" --module "opamp${name//-/}" \
    --source "OpAMP specification, protobuf: github.com/open-telemetry/opamp-spec tag $TAG, commit $COMMIT, proto/opamp/v1/opamp.proto and anyvalue.proto; envelope opamp.proto.v1.$msg; field numbers, names and types only" \
    --source "LICENSE at that commit: Apache License, Version 2.0" \
    --names-file "$NAMES/opamp-$name.json" \
    --notes-file "$GEN/notes/opamp.md" > /dev/null
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "opamp-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "opamp-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
