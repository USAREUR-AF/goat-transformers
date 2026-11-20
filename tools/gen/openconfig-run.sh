#!/bin/bash
# Regenerate the openconfig-* packs: one per top-level container of an OpenConfig YANG
# module, as the JSON of RFC 7951 that a gNMI target returns in the JSON_IETF encoding.
#
# Usage: tools/gen/openconfig-run.sh [--check] <public checkout> <goat-transformers checkout>
#
# <public checkout> is github.com/openconfig/public at tag v5.11.0 (the commit below); a
# sparse checkout of release/models/, third_party/ietf/ and LICENSE is enough:
#   git clone --filter=blob:none --no-checkout --depth 1 --branch v5.11.0 \
#     https://github.com/openconfig/public public
#   git -C public sparse-checkout set --no-cone /release/models/ /third_party/ietf/ /LICENSE
#   git -C public checkout v5.11.0
# The repository's LICENSE is the Apache License 2.0; the IETF modules under third_party/ietf
# state their own licence. Each pack's PROVENANCE.md lists every file read with its SHA-256.
#
# Writes model/openconfig*.def, packs/openconfig-*/ (pack.def, pack.md, PROVENANCE.md,
# vectors/gen-*) and tools/gen/names/openconfig-*.json. With --check nothing is written; the
# exit status is 1 when any file differs.
#
# Not packs: openconfig-bgp, openconfig-ospf and the other protocol modules, which have no
# top-level node of their own (their data, the BGP neighbour state among it, sits under
# network-instances/network-instance/protocols and is in openconfig-network-instances); the
# test-equipment, P4Runtime and SDN-extension augments of interfaces.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] <public checkout> <goat-transformers checkout>" >&2; exit 2; fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
TAG=v5.11.0
COMMIT=160da73440205de252066233b1ee0f3085d51d2d
got="$(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo none)"
if [ "$got" != "$COMMIT" ]; then echo "$SRC is at $got, not $COMMIT (tag $TAG)" >&2; exit 1; fi
STATUS=0

# o <format> <module> <top> [<augmenting module>...] [-- <option>...]
o() {
  local fmt="$1" mod="$2" top="$3"; shift 3
  local aug=() opts=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do aug+=(--augment-module "$1"); shift; done
  [ "$#" -gt 0 ] && shift
  opts=("$@")
  if ! python3 -I "$W/tools/gen/yang2pack.py" --source-root "$SRC" \
      --search release/models --search third_party/ietf \
      --module "$mod" --top "$top" "${aug[@]}" \
      --format "$fmt" --model-module "$(echo "$fmt" | tr -d -)" \
      --title "OpenConfig $TAG module $mod, container $top, in the JSON encoding of RFC 7951" \
      --license "Apache License 2.0 (LICENSE of github.com/openconfig/public); the IETF modules it imports state the Simplified or Revised BSD License" \
      --source "https://github.com/openconfig/public at tag $TAG, commit $COMMIT, release/models and third_party/ietf: $mod and the modules it imports; node names, types and value ranges only" \
      --source "RFC 7951, JSON Encoding of Data Modeled with YANG; RFC 7950, YANG 1.1" \
      --repository "https://github.com/openconfig/public, tag \`$TAG\`, commit \`$COMMIT\`" \
      --download "https://raw.githubusercontent.com/openconfig/public/$COMMIT/<file>" \
      --licence-spdx Apache-2.0 --licence-file "$SRC/LICENSE" \
      --run-script tools/gen/openconfig-run.sh --read-on 2026-11-20 \
      --model-dir "$W/model" --names-file "$W/tools/gen/names/$fmt.json" \
      --notes-file "$W/tools/gen/notes/openconfig.md" --out "$W" \
      "${opts[@]}" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

EV_TIME="openconfig-system describes state.current-datetime as the current date and time of the system; it is the device's own reading at the moment the state in the message holds for, a date-and-time of RFC 3339"
DEEP="objects nested more than 24 levels deep (inside protocol databases and forwarding tables) are not mapped"

o openconfig-interfaces openconfig-interfaces interfaces openconfig-if-ethernet openconfig-if-ethernet-ext \
  openconfig-if-aggregate openconfig-if-ip openconfig-if-ip-ext openconfig-vlan openconfig-if-tunnel \
  openconfig-if-poe openconfig-if-8021x openconfig-if-rates openconfig-platform-port openconfig-platform-transceiver
o openconfig-components openconfig-platform components openconfig-platform-boot-loader \
  openconfig-platform-controller-card openconfig-platform-cpu openconfig-platform-ext openconfig-platform-fabric \
  openconfig-platform-fan openconfig-platform-healthz openconfig-platform-integrated-circuit \
  openconfig-platform-linecard openconfig-platform-pipeline-counters openconfig-platform-port \
  openconfig-platform-psu openconfig-platform-software openconfig-platform-storage \
  openconfig-platform-transceiver openconfig-platform-usb-port
o openconfig-system openconfig-system system openconfig-system-controlplane openconfig-system-grpc \
  openconfig-system-utilization openconfig-system-bootz openconfig-gnsi-acctz openconfig-gnsi-authz \
  openconfig-gnsi-certz openconfig-gnsi-credentialz openconfig-gnsi-pathz openconfig-openflow -- \
  --map "openconfig-system:system.state.current-datetime=time_ms" \
  --evidence "openconfig-system:system.state.current-datetime=$EV_TIME"
o openconfig-network-instances openconfig-network-instance network-instances openconfig-aft-counters \
  openconfig-aft-summary openconfig-local-routing-network-instance openconfig-rib-bgp-ext -- \
  --max-depth 24 --limit-reason "$DEEP"
o openconfig-lldp openconfig-lldp lldp
o openconfig-lacp openconfig-lacp lacp
o openconfig-acl openconfig-acl acl
o openconfig-qos openconfig-qos qos
o openconfig-routing-policy openconfig-routing-policy routing-policy openconfig-bgp-policy \
  openconfig-isis-policy openconfig-ospf-policy
o openconfig-defined-sets openconfig-defined-sets defined-sets
o openconfig-keychains openconfig-keychain keychains
o openconfig-sampling openconfig-sampling sampling openconfig-sampling-sflow
o openconfig-stp openconfig-spanning-tree stp
o openconfig-telemetry-system openconfig-telemetry telemetry-system
o openconfig-bfd openconfig-bfd bfd
o openconfig-macsec openconfig-macsec macsec
o openconfig-ptp openconfig-ptp ptp
o openconfig-probes openconfig-probes probes
o openconfig-relay-agent openconfig-relay-agent relay-agent
o openconfig-access-points openconfig-access-points access-points openconfig-ap-interfaces
o openconfig-terminal-device openconfig-terminal-device terminal-device
o openconfig-optical-amplifier openconfig-optical-amplifier optical-amplifier
o openconfig-channel-monitors openconfig-channel-monitor channel-monitors
o openconfig-wavelength-router openconfig-wavelength-router wavelength-router
exit "$STATUS"
