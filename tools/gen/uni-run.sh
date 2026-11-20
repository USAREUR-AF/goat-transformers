#!/bin/bash
# Regenerate the unicore pack: one `bits` pack for the Unicore UNI binary
# messages, one kind per message of fixed length, from the message definitions
# of pyunigps (github.com/semuconsulting/pyunigps), and its module
# model/unicore.def.
#
# Usage: tools/gen/uni-run.sh <checkout> <sources> [--fetch] [--check]
#
# <checkout> is a goat-transformers checkout; it is written: model/unicore.def and
# packs/unicore/ (pack.def, pack.md, PROVENANCE.md, vectors/). The generator reads
# the definition files as Python syntax trees and never runs them; it checks
# the SHA-256 of every input against tools/gen/sources/unicore-PROVENANCE.md and
# stops when one differs. With --check it writes nothing and reports any file
# that differs from what it would write.
#
# <sources> is a directory for the pyunigps tree. It is not kept in the
# repository. With --fetch the script downloads tag v1.0.1,
#   https://codeload.github.com/semuconsulting/pyunigps/tar.gz/30e429a1cb597152cc30c328966e8034f4e16fe4
#   sha256 addf1fb261d3f5ff6b4e25353e584ab86c180c2871b02e61d67dfb0138d13a6c
# and unpacks it to <sources>/pyunigps-<commit>/. License: BSD 3-Clause,
# Copyright (c) 2020 semuadin (Steve Smith) (LICENSE at the root of the commit,
# verbatim in tools/gen/sources/unicore-PROVENANCE.md).
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
COMMIT=30e429a1cb597152cc30c328966e8034f4e16fe4
TAR_SHA=addf1fb261d3f5ff6b4e25353e584ab86c180c2871b02e61d67dfb0138d13a6c
shift 2
if [ "${1:-}" = "--fetch" ]; then
  shift
  curl -sS -f -L -o "$SRC/pyunigps-$COMMIT.tar.gz" "https://codeload.github.com/semuconsulting/pyunigps/tar.gz/$COMMIT"
  echo "$TAR_SHA  $SRC/pyunigps-$COMMIT.tar.gz" | sha256sum -c -
  tar -xzf "$SRC/pyunigps-$COMMIT.tar.gz" -C "$SRC"
fi
python3 -I "$GEN/uni2pack.py" --src "$SRC/pyunigps-$COMMIT" --out "$ROOT" --core-def "$ROOT/model/core.def" "$@"
