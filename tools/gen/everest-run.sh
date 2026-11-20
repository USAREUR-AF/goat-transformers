#!/bin/bash
# Regenerate the EVerest packs: everest-<file>-<type>, one per object type an interface
# publishes as a var.
#
# Usage: tools/gen/everest-run.sh [--check] <everest-core checkout> <goat-transformers checkout>
#
# Source: https://github.com/EVerest/everest-core at tag 2026.02.2, commit
# 45dba2c049223d05beb7611c75d59f6639c46ee0 (Apache-2.0). A sparse checkout of types/ and
# interfaces/ and LICENSE is enough. tools/gen/everest2pack.py checks the commit, reads
# every types/*.yaml and interfaces/*.yaml (their SHA-256 are in each PROVENANCE.md) and
# writes through tools/gen/jsonschema2pack.py.
#
# Writes model/everest*.def, packs/everest-*/ (pack.def, pack.md, PROVENANCE.md, vectors/gen-*)
# and tools/gen/names/everest-*.json.
#
# With --check nothing is written; the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then CHECK="--check"; shift; fi
if [ "$#" -ne 2 ]; then echo "usage: $0 [--check] <everest-core checkout> <goat-transformers checkout>" >&2; exit 2; fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
exec python3 -I "$W/tools/gen/everest2pack.py" ${CHECK:+"$CHECK"} "$SRC" "$W"
