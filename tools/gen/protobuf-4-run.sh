#!/bin/bash
# Regenerate the protobuf packs of the fourth public family: 11 Meshtastic payload packs
# (meshtastic-*), 9 OTLP packs (otlp-*), 8 gNMI packs (gnmi-*), openxc-vehicle-message,
# geobuf, waymo-frame and waymo-scenario.
#
# Usage: tools/gen/protobuf-4-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary
# copy of its model/, packs/ and tools/gen/names/, the copy is compared with
# <checkout>, every file that differs is listed and the exit status is 1 when
# there is one (as tools/gen/proto2pack-run.sh does).
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words (tools/gen/notes/).
# The schema files are not kept in the repository; each pack's PROVENANCE.md has the
# license and the SHA-256 of every file. Each file is
# https://raw.githubusercontent.com/<repository>/<commit>/<path>:
#
#   <sources>/meshtastic/meshtastic/<name>.proto   meshtastic/protobufs 62b09edf40711fd7bd17804b2fa62ba327fcea60
#     meshtastic/<name>.proto: mqtt, mesh, atak, channel, config, device_ui, field_metadata,
#     module_config, portnums, telemetry, xmodem, storeforward, paxcount
#   <sources>/otlp/opentelemetry/proto/...   open-telemetry/opentelemetry-proto d31f7acf9d461fd0601077de516ac1eb7051422f
#     collector/{trace,metrics,logs}/v1/*_service.proto, common/v1/common.proto,
#     resource/v1/resource.proto, trace/v1/trace.proto, metrics/v1/metrics.proto, logs/v1/logs.proto
#   <sources>/gnmi/proto/{gnmi/gnmi,gnmi_ext/gnmi_ext}.proto   openconfig/gnmi a4e40e60426e5b30ce29fd8115809d2dbe47584f
#   <sources>/openxc/openxc.proto   openxc/openxc-message-format 34979aa21f2367a5fd92398165ac0480e81a12b7
#   <sources>/geobuf/geobuf.proto   mapbox/geobuf 30e3c72136f1785ebd2d6e88a472f7de9e15806e
#   <sources>/waymo/src/waymo_open_dataset/...   waymo-research/waymo-open-dataset 99a4cb3ff07e2fe06c2ce73da001f850f628e45a
#     dataset.proto, label.proto and protos/{map,vector,keypoint,camera_tokens,compressed_lidar,
#     scenario,box,camera_segmentation,segmentation}.proto; nothing under wdl_limited/
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

# run <format> <module> <envelope> <notes> <source> <license> [options] -- <proto files>
run() {
  local fmt="$1" mod="$2" env="$3" notes="$4" src="$5" lic="$6"
  shift 6
  local opts=()
  while [ "$1" != "--" ]; do opts+=("$1"); shift; done
  shift
  "${P2P[@]}" --proto "$@" --envelope "$env" --format "$fmt" --module "$mod" \
    --source "$src" --source "$lic" ${opts[@]+"${opts[@]}"} \
    --names-file "$NAMES/$fmt.json" --notes-file "$notes"
}

# ---- Meshtastic payloads ---------------------------------------------------------------
MESH=62b09edf40711fd7bd17804b2fa62ba327fcea60
M="$SRC/meshtastic/meshtastic"
MESH_PROTO=()
for n in mqtt mesh atak channel config device_ui field_metadata module_config portnums telemetry xmodem storeforward paxcount; do
  MESH_PROTO+=("$M/$n.proto")
done
MESH_LIC="LICENSE at that commit: GNU General Public License, Version 3; the .proto files carry no license header (PROVENANCE.md)"
for spec in position:Position user:User telemetry:Telemetry waypoint:Waypoint tak-packet:TAKPacket \
            neighbor-info:NeighborInfo route-discovery:RouteDiscovery routing:Routing \
            store-and-forward:StoreAndForward paxcount:Paxcount map-report:MapReport; do
  name="${spec%%:*}"; env="${spec#*:}"
  notes="$TMP/notes-meshtastic-$name.md"
  cat "$GEN/notes/meshtastic-payload.md" > "$notes"
  EXTRA=()
  case "$env" in
    User) cat "$GEN/notes/meshtastic-user.md" >> "$notes"
          EXTRA=(--map 1=uid --map 2=callsign --cross-text "$ROOT/packs/geojson/pack.def") ;;
    TAKPacket|Routing|StoreAndForward) EXTRA=(--one-layout) ;;
  esac
  run "meshtastic-$name" "meshtastic${name//-/}" "meshtastic.$env" "$notes" \
    "Meshtastic protobuf definitions: github.com/meshtastic/protobufs commit $MESH, directory meshtastic (13 .proto files); envelope meshtastic.$env; field numbers, names and types only" \
    "$MESH_LIC" ${EXTRA[@]+"${EXTRA[@]}"} -- "${MESH_PROTO[@]}"
done

# ---- OpenTelemetry OTLP ------------------------------------------------------------------
OTLP=d31f7acf9d461fd0601077de516ac1eb7051422f
O="$SRC/otlp/opentelemetry/proto"
OTLP_PROTO=("$O/collector/trace/v1/trace_service.proto" "$O/collector/metrics/v1/metrics_service.proto"
            "$O/collector/logs/v1/logs_service.proto" "$O/common/v1/common.proto" "$O/resource/v1/resource.proto"
            "$O/trace/v1/trace.proto" "$O/metrics/v1/metrics.proto" "$O/logs/v1/logs.proto")
for spec in traces-data:trace.v1.TracesData metrics-data:metrics.v1.MetricsData logs-data:logs.v1.LogsData \
            export-trace-request:collector.trace.v1.ExportTraceServiceRequest \
            export-trace-response:collector.trace.v1.ExportTraceServiceResponse \
            export-metrics-request:collector.metrics.v1.ExportMetricsServiceRequest \
            export-metrics-response:collector.metrics.v1.ExportMetricsServiceResponse \
            export-logs-request:collector.logs.v1.ExportLogsServiceRequest \
            export-logs-response:collector.logs.v1.ExportLogsServiceResponse; do
  name="${spec%%:*}"; env="opentelemetry.proto.${spec#*:}"
  run "otlp-$name" "otlp${name//-/}" "$env" "$GEN/notes/otlp.md" \
    "OpenTelemetry protocol (OTLP) protobuf definitions: github.com/open-telemetry/opentelemetry-proto commit $OTLP, opentelemetry/proto (8 .proto files); envelope $env; field numbers, names and types only" \
    "LICENSE and the file headers at that commit: Copyright The OpenTelemetry Authors; Apache License, Version 2.0" \
    -- "${OTLP_PROTO[@]}"
done

# ---- gNMI --------------------------------------------------------------------------------------
GNMI=a4e40e60426e5b30ce29fd8115809d2dbe47584f
for spec in capability-request:CapabilityRequest capability-response:CapabilityResponse \
            get-request:GetRequest get-response:GetResponse set-request:SetRequest set-response:SetResponse \
            subscribe-request:SubscribeRequest subscribe-response:SubscribeResponse; do
  name="${spec%%:*}"; env="gnmi.${spec#*:}"
  EXTRA=()
  case "$name" in subscribe-*) EXTRA=(--one-layout) ;; esac
  run "gnmi-$name" "gnmi${name//-/}" "$env" "$GEN/notes/gnmi.md" \
    "gNMI protobuf definitions: github.com/openconfig/gnmi commit $GNMI, proto/gnmi/gnmi.proto and proto/gnmi_ext/gnmi_ext.proto; envelope $env; field numbers, names and types only" \
    "LICENSE and the file headers at that commit: Copyright Google Inc.; Apache License, Version 2.0" \
    ${EXTRA[@]+"${EXTRA[@]}"} -- "$SRC/gnmi/proto/gnmi/gnmi.proto" "$SRC/gnmi/proto/gnmi_ext/gnmi_ext.proto"
done

# ---- OpenXC and geobuf ----------------------------------------------------------------------------
run openxc-vehicle-message openxc openxc.VehicleMessage "$GEN/notes/openxc.md" \
  "OpenXC message format openxc.proto: github.com/openxc/openxc-message-format commit 34979aa21f2367a5fd92398165ac0480e81a12b7; field numbers, names and types only" \
  "LICENSE at that commit: BSD 3-clause license, Copyright (c) 2012 Ford Motor Company" \
  -- "$SRC/openxc/openxc.proto"
run geobuf geobuf Data "$GEN/notes/geobuf.md" \
  "geobuf.proto: github.com/mapbox/geobuf commit 30e3c72136f1785ebd2d6e88a472f7de9e15806e; field numbers, names and types only" \
  "LICENSE at that commit: ISC License, Copyright (c) Mapbox" \
  -- "$SRC/geobuf/geobuf.proto"

# ---- Waymo Open Dataset ------------------------------------------------------------------------------
WAYMO=99a4cb3ff07e2fe06c2ce73da001f850f628e45a
W="$SRC/waymo/src/waymo_open_dataset"
WAYMO_PROTO=("$W/dataset.proto" "$W/label.proto")
for n in map vector keypoint camera_tokens compressed_lidar scenario box camera_segmentation segmentation; do
  WAYMO_PROTO+=("$W/protos/$n.proto")
done
for spec in frame:waymo.open_dataset.Frame scenario:waymo.open_dataset.Scenario; do
  name="${spec%%:*}"; env="${spec#*:}"
  run "waymo-$name" "waymo$name" "$env" "$GEN/notes/waymo.md" \
    "Waymo Open Dataset protobuf definitions: github.com/waymo-research/waymo-open-dataset commit $WAYMO, src/waymo_open_dataset (11 .proto files, none under wdl_limited); envelope $env; field numbers, names and types only" \
    "LICENSE at that commit: Apache License, Version 2.0, for the repository excluding src/waymo_open_dataset/wdl_limited; file headers: Copyright The Waymo Open Dataset Authors, Apache License, Version 2.0" \
    -- "${WAYMO_PROTO[@]}"
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "protobuf-4-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "protobuf-4-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
