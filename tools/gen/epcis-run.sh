#!/bin/bash
# Regenerate the GS1 EPCIS 2.0 event pack: gs1-epcis-event.
# Usage: tools/gen/epcis-run.sh [--check] <EPCIS checkout> <goat-transformers checkout>
#
# <EPCIS checkout> is https://github.com/gs1/EPCIS at commit
# 6f71468231838e424bb5dfa836e006e8dc69615c (the script checks); only JSON-Schema/schemas/*.json
# is read. The repository states no licence (its LICENSE file is GS1's disclaimer), so the pack is
# labelled LicenseRef-unstated (packs/gs1-epcis-event/REUSE.toml, model/epcis.def.license).
#
# Writes model/epcis.def, packs/gs1-epcis-event/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/gs1-epcis-event.json. PROVENANCE.md and REUSE.toml are not generated.
# With --check nothing is written; the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <EPCIS checkout> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
want=6f71468231838e424bb5dfa836e006e8dc69615c
got="$(git -C "$SRC" rev-parse HEAD)"
[ "$got" = "$want" ] || { echo "EPCIS is at $got, not $want" >&2; exit 1; }
E="$SRC/JSON-Schema/schemas"
cd "$W"
args=()
for k in ObjectEvent AggregationEvent AssociationEvent TransactionEvent TransformationEvent; do
  args+=(--message "$k=$E/$k-JSON-Schema.json#/definitions/$k" --kind-when "$k:type=$k")
done
python3 -I tools/gen/jsonschema2pack.py --schema $(ls "$E"/*.json | LC_ALL=C sort) "${args[@]}" \
  --format gs1-epcis-event --module epcis --title "GS1 EPCIS 2.0 event (JSON/JSON-LD)" \
  --source "GS1 EPCIS 2.0 JSON Schema, https://github.com/gs1/EPCIS at commit $want, JSON-Schema/schemas/*.json" \
  --license "no licence stated (the repository's LICENSE file is GS1's disclaimer); LicenseRef-unstated" \
  --out . --model-dir model --names-file tools/gen/names/gs1-epcis-event.json ${CHECK:+"$CHECK"}
