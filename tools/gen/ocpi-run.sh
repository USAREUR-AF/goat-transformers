#!/bin/bash
# Regenerate the OCPI 2.2.1 packs (Open Charge Point Interface, EVRoaming Foundation).
# Usage: tools/gen/ocpi-run.sh [--check] <sources> <goat-transformers checkout>
#
# The OCPI 2.2.1 document is published at https://github.com/ocpi/ocpi, tag 2.2.1, commit
# 480973547169dee2fe6d12b1a0fe604623efcbb5, under the Creative Commons
# Attribution-NoDerivatives 4.0 licence; it has no machine-readable schema. This project
# restated the member names, JSON types and required members of the objects it maps in its
# own file tools/gen/ocpi/ocpi-2.2.1-objects.json (no text of the document is copied), and
# this script generates the packs from that file. The packs are this project's
# implementation of the protocol, labelled Apache-2.0; PROVENANCE.md quotes the document's
# licence. <sources>/ocpi is a checkout of the document at that commit: the script checks
# the commit and the SHA-256 of the object chapters the restatement was made from, so a
# reviewer can compare them.
#
# Writes model/ocpi*.def, packs/ocpi-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/ocpi-*.json. PROVENANCE.md is not generated. With --check nothing is
# written; every run is made and the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <sources> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
STATUS=0
got="$(git -C "$SRC/ocpi" rev-parse HEAD)"
[ "$got" = 480973547169dee2fe6d12b1a0fe604623efcbb5 ] || { echo "ocpi is at $got" >&2; exit 1; }
while read -r sha f; do
  got="$(sha256sum "$SRC/ocpi/$f" | cut -d' ' -f1)"
  [ "$got" = "$sha" ] || { echo "$f: sha256 $got, expected $sha" >&2; exit 1; }
done <<'SUMS'
6f17ffc2930b7f19675e11bd3d3c8804156dca530dd8ba45d6ae6d40d579f668 mod_locations.asciidoc
18422ecdfe57f86b41e106c09337870711b435f50593a8a11330276151afa51f mod_sessions.asciidoc
e351bcddb622119f49a68cebd93bf1bde465255fc1c09c8d6b61759e68ecce47 mod_cdrs.asciidoc
8124d1bec84b54c9bfbe26b86c4d3e6f41b67d50d377acbe016d89af2e2bbd50 mod_tariffs.asciidoc
cb8f232ce9868eacb0538aabe117b62f59cf40fed3c34457f58bceb004bfd78b mod_tokens.asciidoc
8307b2ff42aaf376eeb33bb31b443a1b5071b40156df0f63655fad4baac166a4 mod_commands.asciidoc
a3004b958dce5ef442f37517650f833cfa220d8b2c19c169be197a7da8b4272e transport_and_format.asciidoc
c0a06b43e848da5ce318a1dde5aec811e90733edccd73cfc09f14305d6567322 types.asciidoc
SUMS
O="$GEN/ocpi/ocpi-2.2.1-objects.json"
LICENSE="Apache-2.0 (this project's restatement and implementation of OCPI 2.2.1; the OCPI document is CC BY-ND 4.0, EVRoaming Foundation)"
SOURCE="OCPI 2.2.1, https://github.com/ocpi/ocpi tag 2.2.1, commit 480973547169dee2fe6d12b1a0fe604623efcbb5 (CC BY-ND 4.0, EVRoaming Foundation), restated in tools/gen/ocpi/ocpi-2.2.1-objects.json"
cd "$W"

# ocpi <format> <module> <object> <what> [options...]
ocpi() {
  local fmt="$1" mod="$2" obj="$3" what="$4"
  shift 4
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$O" --message "$obj=$O#/\$defs/$obj" \
      --format "$fmt" --module "$mod" --title "OCPI 2.2.1, $what ($obj object)" --license "$LICENSE" \
      --source "$SOURCE" --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" \
      --notes-file "$GEN/notes/$fmt.md" "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}
# Locations module
ocpi ocpi-location ocpiloc Location "Locations module, a location with its EVSEs and connectors" \
  --map Location:name=callsign
ocpi ocpi-evse ocpievse EVSE "Locations module, one EVSE"
ocpi ocpi-connector ocpiconn Connector "Locations module, one connector"
# Sessions, CDRs, Tariffs, Tokens
ocpi ocpi-session ocpisess Session "Sessions module, a charging session"
ocpi ocpi-charging-preferences ocpipref ChargingPreferences "Sessions module, charging preferences"
ocpi ocpi-cdr ocpicdr CDR "CDRs module, a charge detail record"
ocpi ocpi-tariff ocpitariff Tariff "Tariffs module, a tariff"
ocpi ocpi-token ocpitoken Token "Tokens module, a token"
ocpi ocpi-authorization-info ocpiauth AuthorizationInfo "Tokens module, the result of a real-time authorization"
# Commands module
ocpi ocpi-start-session ocpicmdstart StartSession "Commands module, START_SESSION request"
ocpi ocpi-stop-session ocpicmdstop StopSession "Commands module, STOP_SESSION request"
ocpi ocpi-reserve-now ocpicmdres ReserveNow "Commands module, RESERVE_NOW request"
ocpi ocpi-cancel-reservation ocpicmdcancel CancelReservation "Commands module, CANCEL_RESERVATION request"
ocpi ocpi-unlock-connector ocpicmdunlock UnlockConnector "Commands module, UNLOCK_CONNECTOR request"
ocpi ocpi-command-response ocpicmdresp CommandResponse "Commands module, the receiver's response to a command"
ocpi ocpi-command-result ocpicmdresult CommandResult "Commands module, the result of a command sent to the response URL"
# The response envelope of every OCPI response
ocpi ocpi-response ocpiresp Response "transport and format, the response envelope"

exit "$STATUS"
