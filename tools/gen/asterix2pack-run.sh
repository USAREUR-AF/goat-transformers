#!/bin/bash
# Regenerate every ASTERIX pack (asterix-cat*, asterix-cat062-full, asterix-cat021-ed023,
# asterix-cat021-ed026), their modules, names files and canonical-track-v2 gen-to-* vectors.
# Usage: tools/gen/asterix2pack-run.sh <root> <goat-transformers checkout>
#
# Source: https://github.com/zoranbosnjak/asterix-specs, BSD 3-Clause (c) 2019 KZPS
#   published JSON, branch gh-pages, commit 64e9ffba964b92a1af3157bc6bdf7852a63bf700
#   built from branch master, commit        5cf64b635424891b9f7e5d8fc51f6531e5790f89
#   files: https://raw.githubusercontent.com/zoranbosnjak/asterix-specs/<commit>/<path>
#   The URL, path and SHA-256 of every file are in tools/gen/sources/asterix-PROVENANCE.md,
#   which the run rewrites as <root>/sources/PROVENANCE.md; the check below compares them.
#
# <root> receives sources/asterix-specs/, model/, packs/ and tools/gen/names/ (the names
# files are copied in first, so every existing key keeps its name). Copy model/cat*.def,
# packs/asterix-cat*/, packs/canonical-track-v2/vectors/gen-to-asterix-*.json,
# tools/gen/names/asterix-*.json and sources/PROVENANCE.md (as
# tools/gen/sources/asterix-PROVENANCE.md) into the checkout afterwards.
set -euo pipefail
ROOT="$1"
GT="$2"
GEN="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ROOT/tools/gen/names"
cp "$GEN"/names/asterix-*.json "$ROOT/tools/gen/names/"
python3 -I "$GEN/asterix2pack.py" --out "$ROOT" --commit 64e9ffba964b92a1af3157bc6bdf7852a63bf700 --lib "$GT"
diff "$GEN/sources/asterix-PROVENANCE.md" "$ROOT/sources/PROVENANCE.md"
