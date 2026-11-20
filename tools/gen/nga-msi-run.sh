#!/bin/bash
# Regenerate the NGA Maritime Safety Information packs: nga-msi-asam,
# nga-msi-broadcast-warn, nga-msi-ngalol, nga-msi-wpi.
# Usage: tools/gen/nga-msi-run.sh [--check] <sources dir> <goat-transformers checkout>
#
# Source: archived responses of the NGA MSI API (https://msi.nga.mil/api), taken from
# the Internet Archive because the live API answered 503 and no OpenAPI document of it
# is archived (read on 2026-11-20). Licence LicenseRef-NGA-MSI
# (LICENSES/LicenseRef-NGA-MSI.txt): NGA claims no copyright; NGA's disclaimer is
# required where NGA is named.
#
# Each file below is fetched once into <sources dir> as the archived body (the `id_`
# form of the capture, which serves the original bytes), decompressed when it is gzip,
# and checked: tools/gen/nga-msi2pack.py holds the SHA-256 of each decompressed body
# and stops when one differs. The archived bodies themselves have these SHA-256:
#
#   asam.json  29a157803c67b5b0bc7bc7add71d59e95995b67753fcdb597e6df650de40e459
#   bw.json    dca29b3047eb61fa7a3baeff34e40887a72eb12af8cd97f9e207edb359247bce
#   lol.json   fe7f2ce16b5be9e0ff52e7a85ddb65f9ab8b6bec8d7b6058d567cccf51754a88
#   lol2.json  61d332b8cae5805466e3439414b433d3b1f0aed9467b319c18d1b1c6278a7e64
#   lol3.json  2e5b2dd22c889008bc24edf94c1e61646dddf76d38fefac6b29c33606cb88b33
#   lol4.json  a3a9085d42caed91a090d6196f015b104cca4f57959265904e66d4a22670e902
#   wpi.json   676d0d7ac80c33a302a96d87293b1389ad37c6c97c30f3b850092b5d61cd9736
#   wpi2.json  9781e3a9b83b8b553de70a980464c28fdb825457957c08beb26db17a77d126ac
#   wpi3.json  88f9f4f10fe75b98fece1cd244e4a3dd0ce40179969ee0cc0f6d47d484edf3f3
#
# Writes model/nga{asam,bwarn,lol,wpi}.def and packs/nga-msi-*/ (pack.def, pack.md,
# PROVENANCE.md, vectors/gen-*). With --check nothing is written and the exit status is
# 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <sources dir> <goat-transformers checkout>" >&2
  exit 2
fi
mkdir -p "$1"
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
A=https://web.archive.org/web
M=https://msi.nga.mil/api/publications
fetch() {  # <file> <timestamp> <url>
  [ -s "$SRC/$1" ] && return 0
  curl -fsSL -m 300 -o "$SRC/$1.raw" "$A/$2id_/$3"
  if [ "$(head -c2 "$SRC/$1.raw" | od -An -tx1 | tr -d ' \n')" = "1f8b" ]; then
    gunzip -c "$SRC/$1.raw" > "$SRC/$1"
  else
    cp "$SRC/$1.raw" "$SRC/$1"
  fi
}
fetch asam.json 20230927174507 "$M/asam?filter=none&sort=date&output=html"
fetch bw.json   20261022102238 "$M/broadcast-warn?output=json&navArea=P&msgYear=2023&msgNumber=1779&status=all"
fetch lol.json  20260914160540 "$M/ngalol/lights-buoys?volume=110&featureNumber=11636&includeRemovals=false&output=json"
fetch lol2.json 20260914160555 "$M/ngalol/lights-buoys?volume=110&featureNumber=11668&includeRemovals=false&output=json"
fetch lol3.json 20260914160623 "$M/ngalol/lights-buoys?volume=110&featureNumber=11672&includeRemovals=false&output=json"
fetch lol4.json 20260910224550 "$M/ngalol/lights-buoys?volume=114&featureNumber=1220&includeRemovals=false&output=html"
fetch wpi.json  20250222063435 "$M/world-port-index?indexNumber=12370&output=json"
fetch wpi2.json 20260124043107 "$M/world-port-index?countryName=Costa%20Rica&output=html"
fetch wpi3.json 20260124043522 "$M/world-port-index?countryName=Venezuela&output=html"
exec python3 -I "$W/tools/gen/nga-msi2pack.py" ${CHECK:+"$CHECK"} "$SRC" "$W"
