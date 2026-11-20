#!/bin/bash
# Regenerate the Elastic Common Schema pack: ecs-event, the ECS event document.
#
# Usage: tools/gen/ecs-run.sh [--check] <elastic/ecs checkout> <goat-transformers checkout>
#
# Source: https://github.com/elastic/ecs at tag v9.5.0, commit
# 401807e0547301525acd28c4fb667203fec66d59 (Apache-2.0; NOTICE.txt: Copyright 2018-2021
# Elasticsearch B.V.). tools/gen/ecs2pack.py checks the commit, reads the types of
# generated/ecs/ecs_flat.yml and writes through tools/gen/jsonschema2pack.py.
#   LICENSE.txt                 cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30
#   NOTICE.txt                  a6cf45157894095039048a17bee2cb3f7c3c58ab64269e7729a22226bd98fea9
#   generated/ecs/ecs_flat.yml  70557ba53e2bda966688f8255193d36f2dcfa5bce2fb4a1a460bcccfd328ed5c
#
# Writes model/ecsevent.def, packs/ecs-event/ (pack.def, pack.md, PROVENANCE.md,
# vectors/gen-*), packs/geojson/vectors/gen-geojson-to-ecs-event.json and
# tools/gen/names/ecs-event.json.
#
# With --check nothing is written; the exit status is 1 when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <elastic/ecs checkout> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
echo "70557ba53e2bda966688f8255193d36f2dcfa5bce2fb4a1a460bcccfd328ed5c  $SRC/generated/ecs/ecs_flat.yml" \
  | sha256sum --quiet --strict -c - || { echo "ecs_flat.yml differs from the pinned SHA-256" >&2; exit 1; }
exec python3 -I "$W/tools/gen/ecs2pack.py" ${CHECK:+"$CHECK"} "$SRC" "$W"
