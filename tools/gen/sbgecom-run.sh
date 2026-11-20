#!/bin/bash
# Regenerate the sbgECom pack: packs/sbgecom/ and model/sbgecom.def, with
# tools/gen/sbgecom2pack.py.
#
# Usage: tools/gen/sbgecom-run.sh <checkout> <sources> [--fetch] [--check]
#
# <checkout> is a goat-transformers checkout; it is written. <sources> is a
# directory for the sbgECom tree, not kept in the repository. With --fetch the
# script downloads
#   https://codeload.github.com/SBG-Systems/sbgECom/tar.gz/d60e590a0e3d6372732401e549a2a6f7f791c43b
#   sha256 of the archive as fetched on 2026-11-20 (tag 6.0.4661-stable):
#   db1e762d9b93ba7d75c1d407cd2389a916d5184f0dbe774f5eb2f2adf64753fb
# and unpacks it to <sources>/sbgECom-<commit>/. GitHub may rebuild an archive
# with other bytes; the generator checks every file it reads against
# tools/gen/sources/sbgecom-PROVENANCE.md, which is what pins the input.
# License: MIT (LICENSE.md at the root; quoted in packs/sbgecom/PROVENANCE.md).
# With --check the generator writes nothing and reports any file that differs
# from what it would write.
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
COMMIT=d60e590a0e3d6372732401e549a2a6f7f791c43b
SHA=db1e762d9b93ba7d75c1d407cd2389a916d5184f0dbe774f5eb2f2adf64753fb
shift 2
if [ "${1:-}" = "--fetch" ]; then
  shift
  curl -sS -f -L -o "$SRC/sbgECom-$COMMIT.tar.gz" "https://codeload.github.com/SBG-Systems/sbgECom/tar.gz/$COMMIT"
  echo "$SHA  $SRC/sbgECom-$COMMIT.tar.gz" | sha256sum -c - || echo "archive bytes differ; the per-file SHA-256 check decides"
  mkdir -p "$SRC/sbgECom-$COMMIT"
  tar -xzf "$SRC/sbgECom-$COMMIT.tar.gz" -C "$SRC/sbgECom-$COMMIT" --strip-components=1
fi
python3 -I "$GEN/sbgecom2pack.py" --src "$SRC/sbgECom-$COMMIT" --out "$ROOT" "$@"
