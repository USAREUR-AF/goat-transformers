#!/bin/bash
# Regenerate packs nmea2000 and nmea2000-seq and module n2k.
# Usage: tools/gen/canboat2pack-run.sh <root> <goat-transformers checkout>
#
# Source: https://github.com/canboat/canboat, Apache License 2.0
#   commit  d82b7fbc64cd1ed97ccbc6926ff44bf29e0dbe37 (CANboat 9.2.0, schema 2.8.0)
#   docs/canboat.json  https://raw.githubusercontent.com/canboat/canboat/d82b7fbc64cd1ed97ccbc6926ff44bf29e0dbe37/docs/canboat.json
#                      sha256 3f5dc2c725ebcd7bb953ace431f9a7c057481762d72a509e27e91d3008d6d2bb
#   LICENSE            https://raw.githubusercontent.com/canboat/canboat/d82b7fbc64cd1ed97ccbc6926ff44bf29e0dbe37/LICENSE
#                      sha256 ec0704d2efcacadb11d846ed2c353c57625756647a2dd735094682a3f7bf7721
#
# <root> receives sources/ (downloaded at the commit), model/n2k.def and
# packs/{nmea2000,nmea2000-seq}/ (pack.def, pack.md, vectors/). Copy those into the
# checkout afterwards; the PROVENANCE.md files of the two packs are not generated.
set -euo pipefail
ROOT="$1"
GT="$2"
GEN="$(cd "$(dirname "$0")" && pwd)"
SHA=d82b7fbc64cd1ed97ccbc6926ff44bf29e0dbe37

python3 -I "$GEN/canboat2pack.py" --out "$ROOT" --commit "$SHA" --core-def "$GT/model/core.def"
echo "3f5dc2c725ebcd7bb953ace431f9a7c057481762d72a509e27e91d3008d6d2bb  $ROOT/sources/canboat.json" | sha256sum -c -
echo "ec0704d2efcacadb11d846ed2c353c57625756647a2dd735094682a3f7bf7721  $ROOT/sources/LICENSE" | sha256sum -c -
