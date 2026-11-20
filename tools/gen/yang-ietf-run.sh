#!/bin/bash
# Regenerate the yang-ietf-* packs: one per top-level container of an IETF YANG module, as
# the JSON of RFC 7951 that a NETCONF, RESTCONF or gNMI (JSON_IETF) server returns.
#
# Usage: tools/gen/yang-ietf-run.sh [--check] <yang checkout> <goat-transformers checkout>
#
# <yang checkout> is github.com/YangModels/yang at the commit below; a sparse checkout of
# standard/ietf/RFC/ and standard/iana/ is enough:
#   git clone --filter=blob:none --no-checkout https://github.com/YangModels/yang yang
#   git -C yang sparse-checkout set --no-cone /standard/ietf/RFC/ /standard/iana/
#   git -C yang checkout <commit>
# The modules under standard/ietf/RFC are the versions published in RFCs. Each states its
# licence in its description (the Simplified or the Revised BSD License of the IETF Trust
# Legal Provisions); each pack's PROVENANCE.md lists every file read with its SHA-256 and
# quotes the statements.
#
# Writes model/yangietf*.def, packs/yang-ietf-*/ (pack.def, pack.md, PROVENANCE.md,
# vectors/gen-*) and tools/gen/names/yang-ietf-*.json. With --check nothing is written; the
# exit status is 1 when any file differs.
#
# Not packs: the deprecated top-level containers (interfaces-state, routing-state,
# modules-state, hardware-state), whose data RFC 8343, 8349, 8525 and 8348 moved into the
# operational tree; ietf-network-instance (RFC 8529), whose content is a mounted schema
# (RFC 8528) that a pack cannot follow; the service and network models (VPN, TE), which are
# requests to a controller rather than device state.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] <yang checkout> <goat-transformers checkout>" >&2; exit 2; fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
COMMIT=e13b05c4ddcbfab9170e60dddbbe9eaf6a831964
got="$(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo none)"
if [ "$got" != "$COMMIT" ]; then echo "$SRC is at $got, not $COMMIT" >&2; exit 1; fi
STATUS=0

# y <format> <module> <top> [<augmenting module>...] [-- <option>...]
y() {
  local fmt="$1" mod="$2" top="$3"; shift 3
  local aug=() opts=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do aug+=(--augment-module "$1"); shift; done
  [ "$#" -gt 0 ] && shift
  opts=("$@")
  if ! python3 -I "$W/tools/gen/yang2pack.py" --source-root "$SRC" \
      --search standard/ietf/RFC --search standard/iana \
      --module "$mod" --top "$top" "${aug[@]}" \
      --format "$fmt" --model-module "$(echo "$fmt" | tr -d -)" \
      --title "IETF YANG module $mod, container $top, in the JSON encoding of RFC 7951" \
      --license "IETF Trust Legal Provisions 4.c, Simplified or Revised BSD License as each module states" \
      --source "https://github.com/YangModels/yang at commit $COMMIT, standard/ietf/RFC (the RFC versions of the modules): $mod and the modules it imports; node names, types and value ranges only" \
      --source "RFC 7951, JSON Encoding of Data Modeled with YANG; RFC 7950, YANG 1.1" \
      --repository "https://github.com/YangModels/yang, commit \`$COMMIT\` (the head of main when read)" \
      --download "https://raw.githubusercontent.com/YangModels/yang/$COMMIT/<file>" \
      --run-script tools/gen/yang-ietf-run.sh --read-on 2026-11-20 \
      --model-dir "$W/model" --names-file "$W/tools/gen/names/$fmt.json" \
      --notes-file "$W/tools/gen/notes/yang-ietf.md" --out "$W" \
      "${opts[@]}" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

EV_TIME="ietf-system (RFC 7317) describes clock.current-datetime as the current date and time of the system; it is the device's own reading at the moment the state in the reply holds for, a date-and-time of RFC 3339"
PTP_NOTE="The module ietf-ptp states no licence of its own. RFC 8575, which contains it, says that code components taken from it carry the Simplified BSD License text described in Section 4.e of the IETF Trust Legal Provisions."

y yang-ietf-interfaces ietf-interfaces interfaces ietf-ip
y yang-ietf-system ietf-system system ietf-system-tacacs-plus
y yang-ietf-system-state ietf-system system-state -- \
  --map "ietf-system:system-state.clock.current-datetime=time_ms" \
  --evidence "ietf-system:system-state.clock.current-datetime=$EV_TIME"
y yang-ietf-routing ietf-routing routing ietf-ipv4-unicast-routing ietf-ipv6-unicast-routing ietf-ospf ietf-isis -- \
  --max-depth 24 --limit-reason "objects nested more than 24 levels deep (inside OSPF and IS-IS link-state databases) are not mapped"
y yang-ietf-hardware ietf-hardware hardware
y yang-ietf-alarms ietf-alarms alarms ietf-alarms-x733
y yang-ietf-ntp ietf-ntp ntp
y yang-ietf-yang-library ietf-yang-library yang-library
y yang-ietf-ptp ietf-ptp ptp -- --file-licence "ietf-ptp=BSD-2-Clause" --licence-note "$PTP_NOTE"
y yang-ietf-networks ietf-network networks ietf-network-topology
y yang-ietf-acls ietf-access-control-list acls
y yang-ietf-key-chains ietf-key-chain key-chains
y yang-ietf-netconf-state ietf-netconf-monitoring netconf-state ietf-netconf-time
y yang-ietf-restconf-state ietf-restconf-monitoring restconf-state
y yang-ietf-subscriptions ietf-subscribed-notifications subscriptions ietf-yang-push
y yang-ietf-streams ietf-subscribed-notifications streams
y yang-ietf-syslog ietf-syslog syslog
y yang-ietf-tcp ietf-tcp tcp
y yang-ietf-vrrp ietf-vrrp vrrp
exit "$STATUS"
