#!/bin/bash
# Regenerate the NASA GCN packs: one pack per mission notice schema of the unified GCN
# Kafka JSON schema, and one for the GCN Circular.
#
# Usage: tools/gen/gcn-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources>/gcn-schema is a git checkout of https://github.com/nasa-gcn/gcn-schema at tag
# v7.3.0, commit 388eb34d1327b75e355ecb9c54756cc63c973696 (the script checks). Each run
# reads one mission schema with the core schemas (gcn/notices/core/**), the IVOA ObsCore
# schema, and the neutrino Alert schema where the mission schema refers to it. The
# repository has no LICENSE file and its package.json states no licence. The packs are
# labelled LicenseRef-unstated.
#
# Writes model/gcn*.def, packs/gcn-*/ (pack.def, pack.md, vectors/gen-*) and
# tools/gen/names/gcn-*.json. PROVENANCE.md is not generated. With --check nothing is
# written (jsonschema2pack --check per run); every run is made and the exit status is 1
# when any file differs.
set -euo pipefail
CHECK=""
if [ "${1:-}" = "--check" ]; then
  CHECK="--check"
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <sources> <goat-transformers checkout>" >&2
  exit 2
fi
SRC="$(cd "$1" && pwd)"
W="$(cd "$2" && pwd)"
GEN="$W/tools/gen"
COMMIT=388eb34d1327b75e355ecb9c54756cc63c973696
got="$(git -C "$SRC/gcn-schema" rev-parse HEAD)"
[ "$got" = "$COMMIT" ] || { echo "gcn-schema is at $got, not $COMMIT" >&2; exit 1; }
G="$SRC/gcn-schema/gcn"
CORE=$(cd "$SRC" && find gcn-schema/gcn/notices/core -name '*.schema.json' | LC_ALL=C sort | sed "s|^|$SRC/|")
STATUS=0
LICENSE="LicenseRef-unstated: no licence stated (nasa-gcn/gcn-schema)"
SOURCE="https://github.com/nasa-gcn/gcn-schema at tag v7.3.0, commit $COMMIT"
cd "$W"

# gcn <format> <module> <schema path under gcn/> <message name> [other schema it refers to]
gcn() {
  local fmt="$1" mod="$2" file="$3" msg="$4" more=""
  [ -z "${5:-}" ] || more="$G/$5"
  if ! python3 -I "$GEN/jsonschema2pack.py" \
      --schema "$G/$file" $more $CORE "$G/notices/ivoa/ObsCore.schema.json" \
      --message "$msg=$G/$file" \
      --format "$fmt" --module "$mod" --title "NASA GCN schema v7.3.0: $file" \
      --license "$LICENSE" --source "$SOURCE" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/gcn.md" \
      ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

gcn gcn-circular gcncircular circulars.schema.json Circular
gcn gcn-boom-alert gcnboom notices/boom/alert.schema.json Alert
gcn gcn-burstcube-alert gcnburstcube notices/burstcube/alert.schema.json Alert
gcn gcn-burstcube-test gcnburstcubetest notices/burstcube/test.schema.json Test
gcn gcn-chime-frb gcnchime notices/chime/frb.schema.json Frb
gcn gcn-dsa110-frb gcndsa110 notices/dsa110/frb.schema.json Frb
gcn gcn-einstein-probe-wxt-alert gcnepwxt notices/einstein_probe/wxt/alert.schema.json Alert
gcn gcn-fermi-gbm-trigger gcnfermigbm notices/fermi/gbm/trigger.schema.json Trigger
gcn gcn-fermi-lat-flare gcnfermilat notices/fermi/lat/flare.schema.json Flare
gcn gcn-glowbug-alert gcnglowbug notices/glowbug/Alert.schema.json Alert
gcn gcn-heasarc-archive-alert gcnheasarc notices/heasarc/archive_alert.schema.json ArchiveAlert
gcn gcn-icecube-lvk-nu-search gcnicecubelvk notices/icecube/lvk_nu_search.schema.json LvkNuSearch
gcn gcn-icecube-single-neutrino gcnicecubesingle notices/icecube/single_neutrino_alerts.schema.json SingleNeutrino \
  notices/neutrino/Alert.schema.json
gcn gcn-km3net-alert gcnkm3net notices/km3net/alert.schema.json Alert notices/neutrino/Alert.schema.json
gcn gcn-maxi-gsc-known gcnmaxiknown notices/maxi/gsc.known.schema.json GscKnown
gcn gcn-maxi-gsc-unknown gcnmaxiunknown notices/maxi/gsc.unknown.schema.json GscUnknown
gcn gcn-neutrino-alert gcnneutrino notices/neutrino/Alert.schema.json Alert
gcn gcn-snews2-coincidence gcnsnews2 notices/snews2/coincidence.schema.json Coincidence
gcn gcn-superk-sn-alert gcnsuperk notices/superk/sn_alert.schema.json SnAlert
gcn gcn-svom-trigger gcnsvom notices/svom/trigger.schema.json Trigger
gcn gcn-swift-bat-guano gcnswiftguano notices/swift/bat/Guano.schema.json Guano

exit "$STATUS"
