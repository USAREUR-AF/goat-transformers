#!/bin/bash
# Regenerate the zcl-* packs from zigbee-herdsman's ZCL cluster definitions.
#
# Usage: tools/gen/zcl-run.sh [--check] <checkout> <zigbee-herdsman checkout>
#
# <zigbee-herdsman checkout>: github.com/Koenkk/zigbee-herdsman tag v11.2.2 (commit
# ca3276c0fd7c0ef0b5e253d3948871232960ec9a); the generator reads
# src/zspec/zcl/definition/cluster.ts and enums.ts. MIT License. Not kept in this repository;
# each pack's PROVENANCE.md has their SHA-256.
set -euo pipefail
CHECK=()
if [ "${1:-}" = "--check" ]; then CHECK=(--check); shift; fi
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] <checkout> <zigbee-herdsman>" >&2; exit 2; fi
ROOT="$(cd "$1" && pwd)"
ZH="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
python3 -I "$GEN/zcl2pack.py" --out "$ROOT" ${CHECK[@]+"${CHECK[@]}"} --herdsman "$ZH" \
  --cluster genBasic=zcl-basic --cluster genPowerCfg=zcl-power-configuration --cluster genOnOff=zcl-on-off \
  --cluster genLevelCtrl=zcl-level-control --cluster msTemperatureMeasurement=zcl-temperature-measurement \
  --cluster msRelativeHumidity=zcl-relative-humidity --cluster ssIasZone=zcl-ias-zone \
  --source "Zigbee Cluster Library as zigbee-herdsman defines it: github.com/Koenkk/zigbee-herdsman v11.2.2 (commit ca3276c0fd7c0ef0b5e253d3948871232960ec9a), src/zspec/zcl/definition/cluster.ts, enums.ts, and the frame header of src/zspec/zcl/zclHeader.ts; MIT License; names, ids and types restated" \
  --source "Not used: the Zigbee Cluster Library specification of the Connectivity Standards Alliance" \
  --notes-file "$GEN/notes/zcl.md"
