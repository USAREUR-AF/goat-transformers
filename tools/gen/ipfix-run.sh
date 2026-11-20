#!/bin/bash
# Regenerate model/ipfix.def (the IPFIX Information Elements) and the vectors of the flow
# export packs (ipfix-*, netflow9-*, netflow5).
#
# Usage: tools/gen/ipfix-run.sh [--check] [--fetch] <goat-transformers checkout> <sources>
#
# <sources> holds ipfix-information-elements.csv, the IANA registry of IPFIX Information
# Elements as IANA publishes it (https://www.iana.org/assignments/ipfix/). IANA updates the
# registry in place and keeps no versions, so the file is pinned by its SHA-256 below and by
# the date the registry states (the <updated> element of ipfix.xml, read with it); with
# --fetch a missing file is downloaded, and a file whose SHA-256 differs stops the run: a
# newer registry is read by changing the two values below and running again (new elements
# add keys; the names of existing elements do not change).
# The registry is subject to the IANA and IETF joint statement on the Protocol Registries
# (CC0 1.0, https://www.iana.org/help/licensing-terms); packs/ipfix-message/PROVENANCE.md
# quotes it.
#
# The packs themselves (pack.def, pack.md, PROVENANCE.md) are written by hand from RFC 7011,
# RFC 3954 and Cisco's NetFlow version 5 page; tools/gen/flows-vectors.py derives their
# vectors without an engine.
set -euo pipefail
CHECK=""
FETCH=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --check) CHECK="--check"; shift ;;
    --fetch) FETCH=1; shift ;;
    *) break ;;
  esac
done
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] [--fetch] <checkout> <sources>" >&2; exit 2; fi
W="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
CSV_SHA=c8691dd71f6d5fa20839519775c0d2d40079c64a166852ae3a9fb2ecbe9eddcd
REGISTRY_DATE=2026-09-11
CSV="$SRC/ipfix-information-elements.csv"
if [ ! -f "$CSV" ]; then
  if [ "$FETCH" != 1 ]; then echo "missing $CSV (run with --fetch to download it)" >&2; exit 1; fi
  curl -fsSL -o "$CSV" https://www.iana.org/assignments/ipfix/ipfix-information-elements.csv
fi
got="$(sha256sum "$CSV" | cut -d' ' -f1)"
if [ "$got" != "$CSV_SHA" ]; then echo "$CSV: sha256 $got, expected $CSV_SHA" >&2; exit 1; fi
STATUS=0
python3 -I "$W/tools/gen/ipfix2def.py" --csv "$CSV" --registry-date "$REGISTRY_DATE" --out "$W" ${CHECK:+"$CHECK"} || STATUS=1
python3 -I "$W/tools/gen/flows-vectors.py" --out "$W" ${CHECK:+"$CHECK"} || STATUS=1
exit "$STATUS"
