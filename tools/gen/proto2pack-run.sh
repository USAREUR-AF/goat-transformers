#!/bin/bash
# Regenerate the six protobuf packs: sapient, isa, isa-message, isa-ipl1, sapient-v1,
# cot-protobuf.
#
# Usage: tools/gen/proto2pack-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the six runs write into a
# temporary copy of its model/, packs/ and tools/gen/names/, the copy is compared
# with <checkout>, every file that differs is listed and the exit status is 1
# when there is one. The runs cannot each be given `proto2pack.py --check`
# instead, because a later run reads what an earlier run writes: `isa` writes
# model/isa.def afresh and `isa-message` extends it, so the file a correct
# checkout holds is not the file the `isa` run alone writes.
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def,
# model/track.def, the cot-xml and geojson packs, the hand-written vectors of
# sapient, isa and cot-protobuf) and written: model/sapient.def, model/isa.def,
# model/isa1.def, model/sapient1.def, model/takproto.def, packs/<the six>/, the
# gen-*-to-<format>.json vectors under packs/cot-xml, packs/geojson and packs/isa, and
# tools/gen/names/.
#
# A `repeated` field becomes a `group` block and a list (engine-spec 0.7). Three
# limits keep a pack in bounds, and the run lowers them by itself and says so in
# pack.md: pack.def holds at most 100,000 `field` lines (the path length inside an
# item is lowered first, then how many groups stand inside one another), a module
# at most 60,000 keys and lists, and the generated vectors of a pack at most 12 MB
# (one item per group where two would pass that).
#
# <sources> holds the schema files. They are not kept in the repository; each
# pack's PROVENANCE.md has the licence and the SHA-256 of every file.
#
#   <sources>/sapient/bsi_flex_335_v2_0/*.proto   (16 files)   pack sapient
#   <sources>/sapient/proto_options.proto
#   <sources>/sapient-v1/bsi_flex_335_v1_0/*.proto   (15 files)   pack sapient-v1
#   <sources>/sapient-v1/proto_options.proto
#     Both from github.com/dstl/SAPIENT-Proto-Files at commit
#     244a741c13bcee628f84944aef91e4a66854bd7d. Each file is
#     https://raw.githubusercontent.com/dstl/SAPIENT-Proto-Files/244a741c13bcee628f84944aef91e4a66854bd7d/<path>
#     with <path> bsi_flex_335_v2_0/<name>.proto, bsi_flex_335_v1_0/<name>.proto
#     or proto_options.proto (the same file in both directories here).
#
#   <sources>/isa/ipl-3.7-6.0.13.proto   packs isa and isa-message
#     sha256 a959dde49e752d326b8e050a07d798d131e59853e45c74add51b02b339235927
#   <sources>/isa/ipl-1.6-6.0.13.proto   pack isa-ipl1
#     sha256 aff034e73a12435c2176f5af6d68ffa4be7116f09fe68e4dda1c1dfec3f645a5
#     Both from the ISA 6.0.13 schema set (ISA IPL Format 6.0, Git Hash c02e800),
#     directory sources/schemas/. There is no download address for them: copy
#     the two files from a copy of that schema set and check the SHA-256.
#
#   <sources>/tak/*.proto   (10 files)   pack cot-protobuf
#     From github.com/deptofdefense/AndroidTacticalAssaultKit-CIV at commit
#     889eee292c43d3d2eafdd1f2fbf378ad5cd89ecc, directory takproto/: contact, cotevent,
#     detail, group, precisionlocation, status, takcontrol, takmessage, takv, track. Each is
#     https://raw.githubusercontent.com/deptofdefense/AndroidTacticalAssaultKit-CIV/889eee292c43d3d2eafdd1f2fbf378ad5cd89ecc/takproto/<name>.proto
#     The run takes names, field numbers and types from them and no comment
#     (--no-comments). takproto/README.md beside them describes the protocol and its
#     framing; the run does not read it.
#
# The order of the runs matters. `isa` writes model/isa.def afresh and removes
# every gen-*.json under packs/isa/vectors; `isa-message` runs after it, extends
# that module (--module-base: key and list lines are kept), takes the names of
# `isa` (--names-from: paths under the prefix, names of items as they are) and
# writes gen-isa-to-isa-message.json back.
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
# ROOT is where the runs read and write: the checkout, or with --check a copy of
# the three directories they touch. NAMES is the directory of the names files.
ROOT="$CHECKOUT"
NAMES="$GEN/names"
if [ "$CHECK" = 1 ]; then
  ROOT="$TMP/checkout"
  NAMES="$ROOT/tools/gen/names"
  mkdir -p "$ROOT/tools/gen"
  cp -R "$CHECKOUT/model" "$CHECKOUT/packs" "$ROOT/"
  cp -R "$GEN/names" "$NAMES"
fi
SHA=244a741c13bcee628f84944aef91e4a66854bd7d
ISA37="Integrated Sensor Architecture IPL 3.7 protobuf declaration file ipl-3.7-6.0.13.proto (ISA IPL Format 6.0, Iteration 149, Git Hash c02e800), sha256 a959dde49e752d326b8e050a07d798d131e59853e45c74add51b02b339235927"
ISA16="Integrated Sensor Architecture IPL 1.6 protobuf declaration file ipl-1.6-6.0.13.proto (ISA IPL Format 6.0, Iteration 90, Git Hash c02e800), sha256 aff034e73a12435c2176f5af6d68ffa4be7116f09fe68e4dda1c1dfec3f645a5"
DISTA="File header: Distribution Statement A. Approved for Public Release. Distribution is Unlimited."
LICENCE="LICENCE.txt at that commit: Crown owned Copyright 2023; licensed under the Apache License, Version 2.0, except where noted otherwise"

# The isa pack must keep every binding of the pack.def it replaces and decode the
# hand-written vectors as that pack does: the file as it is before this run.
# The sapient pack takes no --supersedes: the hand-written pack it replaced bound
# `uid` to DetectionReport.object_id (7.2), and this pack does not (notes/sapient.md).
SUP_ISA=()
if [ -f "$ROOT/packs/isa/pack.def" ]; then
  cp "$ROOT/packs/isa/pack.def" "$TMP/isa-pack.def"
  SUP_ISA=(--supersedes "$TMP/isa-pack.def")
fi

# The treatment of a detection report, the same in v2.0 (sapient) and v1.0
# (sapient-v1): the two schemas give these fields the same numbers.
DETECTION=(
  --map 7.6.1=lon --map 7.6.2=lat --map 7.6.3=hae
  --map 7.6.6=track.sigma_up_m --map 7.7=track.confidence
  --map 7.19.1=track.vel_east_ms --map 7.19.2=track.vel_north_ms --map 7.19.3=track.vel_up_ms
  --bind detection_report:7.11.1=track.class:pstring:sapient-class
  --table sapient-class:UNKNOWN=unknown
  --table sapient-class:AIRCRAFT_FIXEDWING=fixed-wing-aircraft
  --table sapient-class:AIRCRAFT_ROTARYWING=rotary-wing-aircraft
  --table sapient-class:UAV=uas
  --table sapient-class:BALLOON=balloon
  --table sapient-class:BIRD=bird
  --table sapient-class:VEHICLE=vehicle
  --table sapient-class:CLUTTER=clutter
  --table sapient-class:UNKNOWN=other
  --const detection_report:7.6.7=1 --const detection_report:7.6.8=1
  --default-kind detection_report --default-requires lat lon
)

# The message timestamp (1) is time_ms split into seconds and nanoseconds, and the
# detection report's x and y error (7.6.4, 7.6.5) are the east and north sigma in
# degrees at the report's latitude (engine-spec 0.16), as the open-billie translator
# writes them; each is set only when the entity does not already hold it.
# DetectionReport.state (7.4) is track.status_text, the flags as tokens (model/track.def),
# and the classification's confidence (7.11.2) is track.confidence, written only
# beside a class (engine-spec 0.18 `with`), as the translator writes both.
# A decoded detection's object id (7.2, a ULID the node allocates for the object) is
# also its uid, by a derivation: it fills uid only when the entity has none, so a
# message whose source states a uid keeps it, and a CoT uid is never written back
# into object_id, where the schema requires a ULID.
# Location.x, y and z (7.6.1 to 7.6.3) are longitude, latitude and height only when
# Location.coordinate_system (7.6.7) is 1, latitude and longitude in degrees. The
# detection_report kind therefore holds only those messages (`when 7.6.7 1`, which
# also writes 1 on encode), and the kind detection_report_other_system, last, takes a
# detection in radians, UTM metres or no stated system with the same lines but no
# lat, lon, hae or track.sigma_up_m: its numbers stay in the raw location keys.
# It requires the fields the schema makes mandatory in DetectionReport (report_id,
# object_id), so an entity no kind fits is no-kind, not an empty DetectionReport.
python3 -I "$GEN/proto2pack.py" \
  --proto "$SRC"/sapient/bsi_flex_335_v2_0/*.proto "$SRC/sapient/proto_options.proto" \
  --envelope SapientMessage --format sapient --module sapient --out "$ROOT" \
  --mandatory-option is_mandatory \
  --source "BSI Flex 335 v2.0 protobuf definitions: github.com/dstl/SAPIENT-Proto-Files commit $SHA, directory bsi_flex_335_v2_0 (16 .proto files) and proto_options.proto" \
  --source "$LICENCE" \
  "${DETECTION[@]}" \
  --pack-version 0.3.0 --module-version 0.2.0 \
  --derive "sapient.timestamp_seconds sec_of time_ms" \
  --derive "sapient.timestamp_nanos nsec_of time_ms" \
  --derive "sapient.location_x_error deg_lon_of track.sigma_east_m lat" \
  --derive "sapient.location_y_error deg_lat_of track.sigma_north_m lat" \
  --derive "uid copy sapient.detection_report_object_id" \
  --split-kind "detection_report:7.6.7=1:detection_report_other_system:lat,lon,hae,track.sigma_up_m" \
  --map 7.4=track.status_text \
  --bind detection_report:7.11.2=track.confidence:pfloat \
  --with detection_report:7.11.2=track.class \
  --names-file "$NAMES/sapient.json" \
  --cross "$ROOT/packs/cot-xml/pack.def=$ROOT/packs/cot-xml/vectors/02-cot-roundtrip.json:input" \
  --cross "$ROOT/packs/geojson/pack.def=$ROOT/packs/sapient/vectors/01-sapient-to-geojson.json:expect" \
  --notes-file "$GEN/notes/sapient.md"

python3 -I "$GEN/proto2pack.py" \
  --proto "$SRC/isa/ipl-3.7-6.0.13.proto" \
  --envelope Event --format isa --module isa --out "$ROOT" \
  --source "$ISA37" --source "$DISTA" \
  --map 25.1=lat --map 25.2=lon --map 25.3=hae --map 29.1.1=course --map 29.3.1=speed_ms \
  --names-file "$NAMES/isa.json" \
  --cross "$ROOT/packs/geojson/pack.def=$ROOT/packs/isa/vectors/01-isa-to-geojson.json:expect" \
  --notes-file "$GEN/notes/isa.md" ${SUP_ISA[@]+"${SUP_ISA[@]}"}

# isa-message: the seven-kind pack for `Message`. Its `event` kind is the isa pack's
# envelope at field 3, so it takes that pack's names under prefix 3 and extends
# module isa, which the isa run above has just written.
python3 -I "$GEN/proto2pack.py" \
  --proto "$SRC/isa/ipl-3.7-6.0.13.proto" \
  --envelope Message --kinds-from-fields --format isa-message --module isa --out "$ROOT" \
  --max-depth 14 \
  --module-base "$ROOT/model/isa.def" --module-version 0.2.0 \
  --names-from "$NAMES/isa.json=3" --names-file "$NAMES/isa-message.json" \
  --source "$ISA37" --source "$DISTA" \
  --map 3.25.1=lat --map 3.25.2=lon --map 3.25.3=hae --map 3.29.1.1=course --map 3.29.3.1=speed_ms \
  --default-kind event --default-requires lat lon \
  --cross-text "$ROOT/packs/geojson/pack.def" --cross-text "$ROOT/packs/isa/pack.def" \
  --notes-file "$GEN/notes/isa-message.md"

python3 -I "$GEN/proto2pack.py" \
  --proto "$SRC/isa/ipl-1.6-6.0.13.proto" \
  --envelope Message --kinds-from-fields --format isa-ipl1 --module isa1 --out "$ROOT" \
  --source "$ISA16" --source "$DISTA" \
  --names-file "$NAMES/isa-ipl1.json" \
  --cross-text "$ROOT/packs/geojson/pack.def" --cross-kind event \
  --notes-file "$GEN/notes/isa-ipl1.md"

# --cross-omit: model/track.def derives `le` from track.sigma_up_m (7.6.6) and `course`
# and `speed_ms` from track.vel_east_ms and track.vel_north_ms (7.19.1, 7.19.2); geojson
# writes all three, so the message converted to geojson leaves those paths out.
python3 -I "$GEN/proto2pack.py" \
  --proto "$SRC"/sapient-v1/bsi_flex_335_v1_0/*.proto "$SRC/sapient-v1/proto_options.proto" \
  --envelope SapientMessage --format sapient-v1 --module sapient1 --out "$ROOT" \
  --mandatory-option is_mandatory \
  --source "BSI Flex 335 v1.0 protobuf definitions: github.com/dstl/SAPIENT-Proto-Files commit $SHA, directory bsi_flex_335_v1_0 (15 .proto files) and proto_options.proto" \
  --source "$LICENCE" \
  "${DETECTION[@]}" \
  --names-file "$NAMES/sapient-v1.json" \
  --cross-text "$ROOT/packs/geojson/pack.def" \
  --cross-omit 7.6.6 --cross-omit 7.19.1 --cross-omit 7.19.2 \
  --notes-file "$GEN/notes/sapient-v1.md"

# cot-protobuf: TAK protocol version 1, the bare TakMessage (no framing). CotEvent.uid carries
# track.scoped_id and then uid, as packs/cot-xml binds @uid. takControl may
# stand beside cotEvent, so its fields are common lines (--common-member) and the kind
# `cot_event` is first. The bindings are those of packs/cot-xml, field for field; sendTime
# and startTime both hold time_ms, as @time and @start do there. --cross writes
# gen-cot-xml-to-cot-protobuf.json; --cross-text on cot-xml then writes the vector into
# cot-xml and checks the way back without writing it again.
TAKSHA=889eee292c43d3d2eafdd1f2fbf378ad5cd89ecc
python3 -I "$GEN/proto2pack.py" \
  --proto "$SRC"/tak/*.proto \
  --envelope TakMessage --kinds-from-fields --common-member takControl --no-comments \
  --format cot-protobuf --module takproto --out "$ROOT" \
  --pack-version 0.1.0 \
  --source "TAK protocol version 1 protobuf definitions: github.com/deptofdefense/AndroidTacticalAssaultKit-CIV commit $TAKSHA, directory takproto (10 .proto files); field numbers, names and types only" \
  --source "LICENSE.md at that commit: GNU General Public License, Version 3; INTENT.md at that commit on work of U.S. Federal government employees; the .proto files carry no header (packs/cot-protobuf/PROVENANCE.md)" \
  --map 2.1=type --map 2.5=track.scoped_id --map 2.5=uid --map 2.6=time_ms --map 2.7=time_ms --map 2.8=stale_ms --map 2.9=how \
  --map 2.10=lat --map 2.11=lon --map 2.12=hae --map 2.13=ce --map 2.14=le \
  --map 2.15.2.2=callsign --map 2.15.7.1=speed_ms --map 2.15.7.2=course \
  --default-kind cot_event --default-requires lat lon \
  --names-file "$NAMES/cot-protobuf.json" \
  --cross "$ROOT/packs/cot-xml/pack.def=$ROOT/packs/cot-xml/vectors/02-cot-roundtrip.json:input" \
  --cross-text "$ROOT/packs/geojson/pack.def" --cross-text "$ROOT/packs/cot-xml/pack.def" \
  --notes-file "$GEN/notes/cot-protobuf.md"

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "proto2pack-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "proto2pack-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
