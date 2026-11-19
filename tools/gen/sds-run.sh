#!/bin/bash
# Regenerate the Space Data Standards packs: one pack sds-<name> per standard.
# Usage: tools/gen/sds-run.sh [--check] <spacedatastandards.org checkout> <goat-transformers checkout>
#
# Source: https://github.com/DigitalArsenal/spacedatastandards.org at commit
#   0a61c131bc8a849360a0bba57855cc6dd8dde70a (Apache-2.0, Edgesource Corporation).
# A sparse checkout is enough:
#   git clone --filter=blob:none --no-checkout https://github.com/DigitalArsenal/spacedatastandards.org.git
#   git -C spacedatastandards.org sparse-checkout set --no-cone LICENSE NOTICE 'lib/fbjson/*/main.fb.schema.json'
#   git -C spacedatastandards.org checkout 0a61c131bc8a849360a0bba57855cc6dd8dde70a
# tools/gen/sources/sds-sha256.txt lists LICENSE, NOTICE and the 299 schema files with
# their SHA-256; every one is checked before the generator runs.
# XTC and REC are listed and checked but not generated (SKIPPED in tools/gen/sds-run.py);
# SCC, CQR, SCN, LAM and REM have a lower --max-depth (DEPTH there).
#
# Writes model/sds<name>.def, packs/sds-<name>/ (pack.def, pack.md, PROVENANCE.md,
# vectors/gen-*), packs/geojson/vectors/gen-geojson-to-sds-{gnp,omm,sen,tms,wxf}.json and
# tools/gen/names/sds-<name>.json, through tools/gen/sds-run.py, which runs
# tools/gen/jsonschema2pack.py once per standard.
#
# With --check nothing is written: every run compares what it would write with the
# checkout, all runs are made, and the exit status is 1 when any file differs.
set -euo pipefail
COMMIT=0a61c131bc8a849360a0bba57855cc6dd8dde70a
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <spacedatastandards.org checkout> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"

got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "$SRC is at $got, not $COMMIT" >&2; exit 1; }
(cd "$SRC" && sha256sum --quiet --strict -c "$GEN/sources/sds-sha256.txt") \
  || { echo "a source file differs from tools/gen/sources/sds-sha256.txt" >&2; exit 1; }

exec python3 -I "$GEN/sds-run.py" ${CHECK:+"$CHECK"} "$SRC" "$W"
