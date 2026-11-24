#!/bin/bash
# Regenerate the CSL-JSON item pack: csl-json-item.
# Usage: tools/gen/csl-run.sh [--check] <schema checkout> <goat-transformers checkout>
#
# <schema checkout> is https://github.com/citation-style-language/schema at commit
# e3ce254a72c4470a5ed3b9d23b428017d25674e9 (the script checks); only schemas/input/csl-data.json is read
# (MIT License, Copyright (c) 2007-2018 Citation Style Language and contributors).
#
# Writes model/csl.def, packs/csl-json-item/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/csl-json-item.json. PROVENANCE.md is not generated.
# With --check nothing is written; the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <schema checkout> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
want=e3ce254a72c4470a5ed3b9d23b428017d25674e9
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$want" ] || { echo "schema is at $got, not $want" >&2; exit 1; }
F="$SRC/schemas/input/csl-data.json"
cd "$W"
python3 -I tools/gen/jsonschema2pack.py --schema "$F" --message "Item=$F#/items" \
  --format csl-json-item --module csl --title "CSL-JSON item (Citation Style Language data)" \
  --source "Citation Style Language schema, https://github.com/citation-style-language/schema at commit $want, schemas/input/csl-data.json" \
  --license "MIT License, Copyright (c) 2007-2018 Citation Style Language and contributors" \
  --out . --model-dir model --names-file tools/gen/names/csl-json-item.json ${CHECK:+"$CHECK"}
