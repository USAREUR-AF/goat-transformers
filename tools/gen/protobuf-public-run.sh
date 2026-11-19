#!/bin/bash
# Regenerate the protobuf packs of public message sets: sparkplug-b, gtfs-realtime-entity,
# gtfs-realtime, meshtastic.
#
# Usage: tools/gen/protobuf-public-run.sh <checkout> <sources>
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def, model/track.def,
# the geojson pack) and written: model/sparkplug.def, model/gtfsrt.def, model/meshtastic.def,
# packs/<the four>/, packs/geojson/vectors/gen-geojson-to-gtfs-realtime-entity.json and
# tools/gen/names/<the four>.json.
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments). The meaning lines of the modules and the notes in pack.md are written
# in this repository's own words (tools/gen/notes/).
#
# <sources> holds the schema files. They are not kept in the repository; each pack's
# PROVENANCE.md has the license and the SHA-256 of every file.
#
#   <sources>/sparkplug-b/sparkplug_b.proto   pack sparkplug-b
#     sha256 4432c5c483b7fb9732d0594c98a2e97dca5e517e39c5374a8b918d837f0b4a19
#     From github.com/eclipse-tahu/tahu at commit 5736e404889d4b95910613040a99ba79589ffb13:
#     https://raw.githubusercontent.com/eclipse-tahu/tahu/5736e404889d4b95910613040a99ba79589ffb13/sparkplug_b/sparkplug_b.proto
#
#   <sources>/gtfs-realtime/gtfs-realtime.proto   packs gtfs-realtime-entity and gtfs-realtime
#     sha256 8feff2c5499e0ff08777e203e49ef702e07be0a8376b8bb2126add311a709299
#     From github.com/google/transit at commit 2ce6aa79e3fa7bdbaf19d2a12765cee5b9fdd699:
#     https://raw.githubusercontent.com/google/transit/2ce6aa79e3fa7bdbaf19d2a12765cee5b9fdd699/gtfs-realtime/proto/gtfs-realtime.proto
#
#   <sources>/meshtastic/meshtastic/<name>.proto   (11 files)   pack meshtastic
#     From github.com/meshtastic/protobufs at commit 62b09edf40711fd7bd17804b2fa62ba327fcea60,
#     directory meshtastic/: mqtt and the files it imports, directly or not: mesh, atak,
#     channel, config, device_ui, field_metadata, module_config, portnums, telemetry, xmodem.
#     Each is
#     https://raw.githubusercontent.com/meshtastic/protobufs/62b09edf40711fd7bd17804b2fa62ba327fcea60/meshtastic/<name>.proto
#     The other files of that directory are not on the tree of ServiceEnvelope and are not read.
#
# The order of the runs matters. gtfs-realtime-entity writes model/gtfsrt.def afresh;
# gtfs-realtime runs after it and extends that module (--module-base).
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"

TAHU=5736e404889d4b95910613040a99ba79589ffb13
python3 -I "$GEN/proto2pack.py" \
  --proto "$SRC/sparkplug-b/sparkplug_b.proto" \
  --envelope Payload --no-comments \
  --format sparkplug-b --module sparkplug --out "$ROOT" \
  --pack-version 0.1.0 \
  --source "Sparkplug B payload protobuf definition sparkplug_b.proto: github.com/eclipse-tahu/tahu commit $TAHU, file sparkplug_b/sparkplug_b.proto; field numbers, names and types only" \
  --source "File header at that commit: Copyright (c) 2015, 2018 Cirrus Link Solutions and others; Eclipse Public License 2.0 (SPDX-License-Identifier: EPL-2.0)" \
  --names-file "$GEN/names/sparkplug-b.json" \
  --notes-file "$GEN/notes/sparkplug-b.md"

# gtfs-realtime-entity: one FeedEntity, a kind per member. The five bindings are the
# statements of the schema comments (notes/gtfs-realtime-entity.md); --cross-text writes
# the vehicle kind into geojson and back.
TRANSIT=2ce6aa79e3fa7bdbaf19d2a12765cee5b9fdd699
GTFS_SRC="GTFS Realtime protobuf definition gtfs-realtime.proto: github.com/google/transit commit $TRANSIT, file gtfs-realtime/proto/gtfs-realtime.proto; field numbers, names and types only"
GTFS_LIC="File header at that commit: Copyright 2015 The GTFS Specifications Authors; licensed under the Apache License, Version 2.0"
python3 -I "$GEN/proto2pack.py" \
  --proto "$SRC/gtfs-realtime/gtfs-realtime.proto" \
  --envelope FeedEntity --kinds-from-fields --no-comments \
  --format gtfs-realtime-entity --module gtfsrt --out "$ROOT" \
  --pack-version 0.1.0 \
  --source "$GTFS_SRC" --source "$GTFS_LIC" \
  --map 4.2.1=lat --map 4.2.2=lon --map 4.2.5=speed_ms --map 4.8.1=uid --map 4.8.2=callsign \
  --default-kind vehicle --default-requires lat lon \
  --names-file "$GEN/names/gtfs-realtime-entity.json" \
  --cross-text "$ROOT/packs/geojson/pack.def" \
  --notes-file "$GEN/notes/gtfs-realtime-entity.md"

# gtfs-realtime: the whole FeedMessage, every field raw; extends module gtfsrt.
python3 -I "$GEN/proto2pack.py" \
  --proto "$SRC/gtfs-realtime/gtfs-realtime.proto" \
  --envelope FeedMessage --no-comments \
  --format gtfs-realtime --module gtfsrt --out "$ROOT" \
  --pack-version 0.1.0 \
  --module-base "$ROOT/model/gtfsrt.def" \
  --names-from "$GEN/names/gtfs-realtime-entity.json=2" \
  --source "$GTFS_SRC" --source "$GTFS_LIC" \
  --names-file "$GEN/names/gtfs-realtime.json" \
  --notes-file "$GEN/notes/gtfs-realtime.md"

MESH=62b09edf40711fd7bd17804b2fa62ba327fcea60
M="$SRC/meshtastic/meshtastic"
python3 -I "$GEN/proto2pack.py" \
  --proto "$M/mqtt.proto" "$M/mesh.proto" "$M/atak.proto" "$M/channel.proto" "$M/config.proto" \
          "$M/device_ui.proto" "$M/field_metadata.proto" "$M/module_config.proto" \
          "$M/portnums.proto" "$M/telemetry.proto" "$M/xmodem.proto" \
  --envelope ServiceEnvelope --no-comments \
  --format meshtastic --module meshtastic --out "$ROOT" \
  --pack-version 0.1.0 \
  --source "Meshtastic protobuf definitions: github.com/meshtastic/protobufs commit $MESH, directory meshtastic (mqtt.proto and the 10 files it imports); field numbers, names and types only" \
  --source "LICENSE at that commit: GNU General Public License, Version 3; the .proto files carry no license header (packs/meshtastic/PROVENANCE.md)" \
  --names-file "$GEN/names/meshtastic.json" \
  --notes-file "$GEN/notes/meshtastic.md"
