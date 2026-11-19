#!/bin/bash
# Regenerate the protobuf packs foxglove-location-fix, osm-pbf-blob-header, osm-pbf-header,
# osm-pbf-primitive, mvt, valhalla and tesla-fleet-telemetry.
#
# Usage: tools/gen/protobuf-2-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does; a later run reads what an
# earlier run writes, so the runs are not each given `proto2pack.py --check`).
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def, model/track.def,
# the geojson pack) and written: model/{foxglove,osmpbf,mvt,valhalla,teslafleet}.def,
# packs/<the seven>/ and tools/gen/names/<the seven>.json. The vector into geojson is
# hand-written (tools/gen/protobuf-2-vectors.py): --cross-text would have to leave out the
# velocity, the only shared keys, because geojson writes the course and speed they derive.
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words (tools/gen/notes/).
#
# <sources> holds the schema files. They are not kept in the repository; each pack's
# PROVENANCE.md has the license and the SHA-256 of every file. Each file is
# https://raw.githubusercontent.com/<repository>/<commit>/<path>:
#
#   <sources>/foxglove/foxglove/{LocationFix,Color,KeyValuePair,Vector3}.proto
#     foxglove/foxglove-sdk 8cebcc575cea4a2dfb3622948936a8a2f2552820, schemas/proto/foxglove/<name>.proto
#   <sources>/osm/osmpbf/{fileformat,osmformat}.proto
#     openstreetmap/OSM-binary 9f01ad3ece9737503a059d58749e02c9008d5699, osmpbf/<name>.proto
#   <sources>/mvt/2.1/vector_tile.proto
#     mapbox/vector-tile-spec 21ff2cbd83c241d0ecdce0c782ecc08a565e713b, 2.1/vector_tile.proto
#   <sources>/valhalla/proto/<name>.proto   (12 files: api and the files it imports)
#     valhalla/valhalla b1cfbaf007d407c726c5a15d290e115326cc966a, proto/descriptors/<name>.proto
#   <sources>/tesla/protos/vehicle_data.proto
#     teslamotors/fleet-telemetry bb7c8a931e46da3b3eb6d20a67541c8f755f1ee6, protos/vehicle_data.proto
#
# The order of the OSM runs matters: osm-pbf-blob-header writes model/osmpbf.def afresh, the
# two after it extend it (--module-base).
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
P2P=(python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0)

FOX=8cebcc575cea4a2dfb3622948936a8a2f2552820
F="$SRC/foxglove/foxglove"
"${P2P[@]}" \
  --proto "$F/LocationFix.proto" "$F/Color.proto" "$F/KeyValuePair.proto" "$F/Vector3.proto" \
  --envelope LocationFix --format foxglove-location-fix --module foxglove \
  --source "Foxglove schema LocationFix, protobuf: github.com/foxglove/foxglove-sdk commit $FOX, schemas/proto/foxglove (LocationFix, Color, KeyValuePair, Vector3); field numbers, names and types only" \
  --source "LICENSE at that commit: MIT License, Copyright (c) Foxglove Technologies Inc" \
  --map 1=lat --map 2=lon --map 11.1=track.vel_east_ms --map 11.2=track.vel_north_ms --map 11.3=track.vel_up_ms \
  --names-file "$NAMES/foxglove-location-fix.json" \
  --notes-file "$GEN/notes/foxglove-location-fix.md"

OSM=9f01ad3ece9737503a059d58749e02c9008d5699
OSM_SRC="OpenStreetMap PBF format definitions: github.com/openstreetmap/OSM-binary commit $OSM, osmpbf/fileformat.proto and osmpbf/osmformat.proto; field numbers, names and types only"
OSM_LIC="osmpbf/LICENSE and the header of both files at that commit: MIT License (Copyright (c) OpenStreetMap developers; Copyright (c) 2010 Scott A. Crosby); the repository's LICENSE is the GNU LGPL, Version 3"
"${P2P[@]}" \
  --proto "$SRC/osm/osmpbf/fileformat.proto" \
  --envelope BlobHeader --format osm-pbf-blob-header --module osmpbf \
  --source "$OSM_SRC" --source "$OSM_LIC" \
  --names-file "$NAMES/osm-pbf-blob-header.json" \
  --notes-file "$GEN/notes/osm-pbf.md"
for pair in HeaderBlock:osm-pbf-header PrimitiveBlock:osm-pbf-primitive; do
  "${P2P[@]}" \
    --proto "$SRC/osm/osmpbf/osmformat.proto" \
    --envelope "${pair%%:*}" --format "${pair#*:}" --module osmpbf \
    --module-base "$ROOT/model/osmpbf.def" \
    --source "$OSM_SRC" --source "$OSM_LIC" \
    --names-file "$NAMES/${pair#*:}.json" \
    --notes-file "$GEN/notes/osm-pbf.md"
done

MVT=21ff2cbd83c241d0ecdce0c782ecc08a565e713b
"${P2P[@]}" \
  --proto "$SRC/mvt/2.1/vector_tile.proto" \
  --envelope Tile --format mvt --module mvt \
  --source "Mapbox Vector Tile specification 2.1, vector_tile.proto: github.com/mapbox/vector-tile-spec commit $MVT, file 2.1/vector_tile.proto; field numbers, names and types only" \
  --source "LICENSE at that commit: Creative Commons Attribution 3.0 Unported; README.md: the text of the specification is licensed under Creative Commons Attribution 3.0 United States" \
  --names-file "$NAMES/mvt.json" \
  --notes-file "$GEN/notes/mvt.md"

VAL=b1cfbaf007d407c726c5a15d290e115326cc966a
V="$SRC/valhalla/proto"
"${P2P[@]}" \
  --proto "$V/api.proto" "$V/common.proto" "$V/directions.proto" "$V/expansion.proto" "$V/incidents.proto" \
          "$V/info.proto" "$V/isochrone.proto" "$V/matrix.proto" "$V/options.proto" "$V/sign.proto" \
          "$V/status.proto" "$V/trip.proto" \
  --envelope Api --format valhalla --module valhalla \
  --source "Valhalla protobuf definitions: github.com/valhalla/valhalla commit $VAL, proto/descriptors (api.proto and the 11 files it imports); field numbers, names and types only" \
  --source "COPYING at that commit: The MIT License (MIT), Copyright (c) 2018 Valhalla contributors, Copyright (c) 2015-2017 Mapillary AB, Mapzen" \
  --names-file "$NAMES/valhalla.json" \
  --notes-file "$GEN/notes/valhalla.md"

TESLA=bb7c8a931e46da3b3eb6d20a67541c8f755f1ee6
"${P2P[@]}" \
  --proto "$SRC/tesla/protos/vehicle_data.proto" \
  --envelope Payload --format tesla-fleet-telemetry --module teslafleet \
  --source "Tesla Fleet Telemetry vehicle_data.proto: github.com/teslamotors/fleet-telemetry commit $TESLA, file protos/vehicle_data.proto; field numbers, names and types only" \
  --source "LICENSE at that commit: Apache License, Version 2.0" \
  --names-file "$NAMES/tesla-fleet-telemetry.json" \
  --notes-file "$GEN/notes/tesla-fleet-telemetry.md"

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "protobuf-2-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "protobuf-2-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
