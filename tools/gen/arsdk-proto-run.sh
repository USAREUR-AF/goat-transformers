#!/bin/bash
# Regenerate the arsdk-proto-* packs: one pack per protobuf feature of Parrot's ARSDK
# (the `Event` message of each schema file under protobuf/arsdk of arsdk-xml).
#
# Usage: tools/gen/arsdk-proto-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words (tools/gen/notes/).
#
#   <sources>/arsdk/*.proto and <sources>/arsdk/internal/lora.proto: the 41 files of
#     protobuf/arsdk of github.com/Parrot-Developers/arsdk-xml commit
#     2299c689be5951fa2104793e0154b0b5b1896c03 (the commit of the arsdk-* packs), each
#     https://raw.githubusercontent.com/Parrot-Developers/arsdk-xml/<commit>/protobuf/arsdk/<path>.
#     They carry no licence line and the repository has no licence file: the packs are
#     labelled LicenseRef-unstated.
#   <sources>/google/protobuf/empty.proto and wrappers.proto: github.com/protocolbuffers/protobuf
#     tag v29.3 (commit b407e8416e3893036aee5af9a12bd9b6a0e2b2e6), src/google/protobuf/<name>.proto,
#     BSD-3-Clause (Copyright 2008 Google Inc.).
# The schema files import parrot/protobuf/extensions.proto, which declares their custom
# options (documentation strings, supported firmware) and is not published. It holds nothing a
# message is made of, so the run gives the generator an empty stand-in written here.
# None of these files is kept in this repository; each pack's PROVENANCE.md has their SHA-256.
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
COMMIT=2299c689be5951fa2104793e0154b0b5b1896c03
mkdir -p "$TMP/stub/parrot/protobuf"
printf 'syntax = "proto3";\npackage parrot.protobuf;\n' > "$TMP/stub/parrot/protobuf/extensions.proto"
PROTO=("$SRC"/arsdk/*.proto "$SRC/arsdk/internal/lora.proto"
       "$SRC/google/protobuf/empty.proto" "$SRC/google/protobuf/wrappers.proto"
       "$TMP/stub/parrot/protobuf/extensions.proto")
# <schema file under protobuf/arsdk>:<package>:<pack name suffix>
PACKS=(
  antiflicker.proto:arsdk.antiflicker:antiflicker
  backuplink.proto:arsdk.backuplink:backuplink
  calibration.proto:arsdk.calibration:calibration
  camera2.proto:arsdk.camera:camera2
  connectivity.proto:arsdk.connectivity:connectivity
  controller_backuplink.proto:arsdk.controllerbackuplink:controller-backuplink
  controller_network.proto:arsdk.controllernetwork:controller-network
  controller_privacy.proto:arsdk.controllerprivacy:controller-privacy
  developer.proto:arsdk.developer:developer
  device_manager.proto:arsdk.devicemanager:device-manager
  dri.proto:arsdk.dri:dri
  esim.proto:arsdk.esim:esim
  external_autopilot.proto:arsdk.externalautopilot:external-autopilot
  flight_data.proto:arsdk.flightdata:flight-data
  geofence.proto:arsdk.geofence:geofence
  killswitch.proto:arsdk.killswitch:killswitch
  led.proto:arsdk.led:led
  logsync.proto:arsdk.logsync:logsync
  loiter.proto:arsdk.loiter:loiter
  microhard.proto:arsdk.microhard:microhard
  mobile_device.proto:arsdk.mobiledevice:mobile-device
  navigation.proto:arsdk.navigation:navigation
  netdebuglog.proto:arsdk.netdebuglog:netdebuglog
  network.proto:arsdk.network:network
  night_vision.proto:arsdk.nightvision:night-vision
  piloting.proto:arsdk.piloting:piloting
  pointnfly.proto:arsdk.pointnfly:pointnfly
  privacy.proto:arsdk.privacy:privacy
  remote_antenna.proto:arsdk.remoteantenna:remote-antenna
  sleepmode.proto:arsdk.sleepmode:sleepmode
  sms.proto:arsdk.sms:sms
  storage.proto:arsdk.storage:storage
  system.proto:arsdk.system:system
  thermal_control.proto:arsdk.thermalcontrol:thermal-control
  tracking.proto:arsdk.tracking:tracking
  unguarded_flight.proto:arsdk.unguardedflight:unguarded-flight
  usb_power.proto:arsdk.usbpower:usb-power
  vehicle.proto:arsdk.vehicle:vehicle
  internal/lora.proto:arsdk.internal.lora:internal-lora
)
for spec in "${PACKS[@]}"; do
  file="${spec%%:*}"; rest="${spec#*:}"; pkg="${rest%%:*}"; name="arsdk-proto-${rest#*:}"
  notes="$TMP/notes-$name.md"
  cat "$GEN/notes/arsdk-proto.md" > "$notes"
  EXTRA=()
  case "$file" in
    backuplink.proto|camera2.proto|connectivity.proto|thermal_control.proto)
      cat "$GEN/notes/arsdk-proto-one-layout.md" >> "$notes"
      EXTRA=(--one-layout) ;;
  esac
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "${PROTO[@]}" \
    --envelope "$pkg.Event" --format "$name" --module "${name//-/}" \
    --source "Parrot ARSDK protobuf features: github.com/Parrot-Developers/arsdk-xml commit $COMMIT, protobuf/arsdk (41 .proto files); envelope $pkg.Event of protobuf/arsdk/$file; field numbers, names and types only" \
    --source "google/protobuf/empty.proto and wrappers.proto: github.com/protocolbuffers/protobuf v29.3, BSD-3-Clause" \
    --source "Licence of the arsdk protobuf files: none stated (LicenseRef-unstated); see PROVENANCE.md" \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    --names-file "$NAMES/$name.json" \
    --notes-file "$notes" > /dev/null
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "arsdk-proto-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "arsdk-proto-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
