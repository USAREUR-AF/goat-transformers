#!/bin/bash
# Regenerate the rtcm3 pack: one `bits` pack (layout sequential) for RTCM 3
# (RTCM 10403.x) message bodies, one kind per message number, from the message
# definitions of pyrtcm (github.com/semuconsulting/pyrtcm), and its module
# model/rtcm3.def.
#
# Usage: tools/gen/rtcm-run.sh <checkout> <sources> [--fetch] [--check]
#
# <checkout> is a goat-transformers checkout; it is written: model/rtcm3.def and
# packs/rtcm3/ (pack.def, pack.md, PROVENANCE.md, vectors/). The generator reads
# the definition files as Python syntax trees and never runs them; it checks
# the SHA-256 of every input against tools/gen/sources/rtcm3-PROVENANCE.md and
# stops when one differs. With --check it writes nothing and reports any file
# that differs from what it would write.
#
# <sources> is a directory for the pyrtcm tree. It is not kept in the
# repository. With --fetch the script downloads tag v1.2.1,
#   https://codeload.github.com/semuconsulting/pyrtcm/tar.gz/0e190e70498a6795ce5f45c0a8671f0041698ce7
#   sha256 022c304f66f92f09fc27c5790d7df7fc836b1881cad3209e8f92f51b74e69505
# and unpacks it to <sources>/pyrtcm-<commit>/. License: BSD 3-Clause, Copyright
# (c) 2020 semuadmin (Steve Smith) (LICENSE at the root of the commit, verbatim
# in tools/gen/sources/rtcm3-PROVENANCE.md).
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
COMMIT=0e190e70498a6795ce5f45c0a8671f0041698ce7
TAR_SHA=022c304f66f92f09fc27c5790d7df7fc836b1881cad3209e8f92f51b74e69505
shift 2
if [ "${1:-}" = "--fetch" ]; then
  shift
  curl -sS -f -L -o "$SRC/pyrtcm-$COMMIT.tar.gz" "https://codeload.github.com/semuconsulting/pyrtcm/tar.gz/$COMMIT"
  echo "$TAR_SHA  $SRC/pyrtcm-$COMMIT.tar.gz" | sha256sum -c -
  tar -xzf "$SRC/pyrtcm-$COMMIT.tar.gz" -C "$SRC"
fi
python3 -I "$GEN/rtcm2pack.py" --src "$SRC/pyrtcm-$COMMIT" --out "$ROOT" --core-def "$ROOT/model/core.def" "$@"
