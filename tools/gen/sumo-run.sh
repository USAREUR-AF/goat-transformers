#!/bin/bash
# Regenerate the SUMO packs: one per XML file type of Eclipse SUMO (simulation
# outputs, then network and demand inputs), each from that file type's schema.
#
# Usage: tools/gen/sumo-run.sh [--check] [--fetch] <checkout> <sources>
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def,
# model/track.def) and written: model/<module>.def,
# packs/<format>/{pack.def,pack.md,vectors/gen-*.json} and
# tools/gen/names/<format>.json of every pack below. PROVENANCE.md is not generated.
#
# With --check nothing is written: each run compares what it would write with the
# files of <checkout> and with its names file (xsd2pack.py --check), all runs are
# made, and the exit status is 1 when any file differs.
#
# <sources> receives the repository's data/xsd/ files. With --fetch, a missing file
# is downloaded from
#   https://raw.githubusercontent.com/eclipse-sumo/sumo/<commit>/<path>
# Every file read is checked against the SHA-256 that tools/gen/sources/sumo-xsd.txt
# pins; a mismatch stops the run. The files are not kept in this repository. The
# repository's LICENSE is the Eclipse Public License 2.0 (packs/sumo-fcd/PROVENANCE.md
# quotes it).
#
# Not built: summary_file.xsd and person_summary_file.xsd (both use a simple type,
# nonNegativeFloat, that no file of the set defines, so xsd2pack refuses them); the
# *Configuration.xsd files and viewsettings_file.xsd (tool settings, not data).
# In sumo-state the element rngState (the saved states of the random number generators)
# is not walked: it is simulator-internal, and two of its attribute names (device.<name>)
# read as e-mail addresses to tools/boundary-gate in the key descriptions.
set -euo pipefail
CHECK=""
FETCH=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --check) CHECK="--check"; shift ;;
    --fetch) FETCH=1; shift ;;
    *) break ;;
  esac
done
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] [--fetch] <checkout> <sources>" >&2
  exit 2
fi
CHECKOUT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
COMMIT=daf91b5578901d599ac9af53f49d26eeb9aefc3b
MANIFEST="$GEN/sources/sumo-xsd.txt"

while read -r sha rel; do
  case "$sha" in ''|'#'*) continue ;; esac
  if [ ! -f "$SRC/$rel" ]; then
    if [ "$FETCH" != 1 ]; then
      echo "missing $SRC/$rel (run with --fetch to download it)" >&2
      exit 1
    fi
    mkdir -p "$(dirname "$SRC/$rel")"
    curl -fsSL -o "$SRC/$rel" "https://raw.githubusercontent.com/eclipse-sumo/sumo/$COMMIT/$rel"
  fi
  got="$(sha256sum "$SRC/$rel" | cut -d' ' -f1)"
  if [ "$got" != "$sha" ]; then
    echo "$rel: sha256 $got, expected $sha" >&2
    exit 1
  fi
done < "$MANIFEST"

X="$SRC/data/xsd"
T="$X/types"
CONFIG=("$T/activitygenConfigurationType.xsd" "$T/dfrouterConfigurationType.xsd"
  "$T/duarouterConfigurationType.xsd" "$T/jtrrouterConfigurationType.xsd"
  "$T/marouterConfigurationType.xsd" "$T/netconvertConfigurationType.xsd"
  "$T/neteditConfigurationType.xsd" "$T/netgenerateConfigurationType.xsd"
  "$T/od2tripsConfigurationType.xsd" "$T/polyconvertConfigurationType.xsd"
  "$T/sumoConfigurationType.xsd")
STATEMENT="The eclipse-sumo/sumo repository at tag v1_28_0 (commit $COMMIT) carries a LICENSE \
file with the Eclipse Public License 2.0, and its README states that SUMO is licensed under \
that license. The schema files under data/xsd carry no header of their own. Element and \
attribute names, types and value ranges only."
STATUS=0

# sumo <format> <module> <what> <catalog xsd> [<other xsd>...] -- <root>... [-- <option>...]
sumo() {
  local fmt="$1" mod="$2" what="$3"; shift 3
  local xsds=() roots=() opts=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do xsds+=("$1"); shift; done
  shift
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do roots+=(--message "$1"); shift; done
  [ "$#" -gt 0 ] && shift
  opts=("$@")
  if ! python3 -I "$GEN/xsd2pack.py" \
      --xsd "${xsds[@]}" \
      --format "$fmt" --module "$mod" --out "$CHECKOUT" --model-dir "$CHECKOUT/model" \
      --title "Eclipse SUMO $what, schema $(basename "${xsds[0]}"), github.com/eclipse-sumo/sumo tag v1_28_0 commit $COMMIT" \
      --source "Eclipse SUMO documentation, https://sumo.dlr.de/docs/ (meaning of the files and their attributes)" \
      --public-statement "$STATEMENT" \
      --substitution-groups \
      "${roots[@]}" "${opts[@]}" \
      --version 0.1.0 \
      --notes-file "$GEN/notes/sumo.md" \
      --names-file "$GEN/names/$fmt.json" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

# simulation outputs
sumo sumo-fcd sumofcd "floating car data output" "$X/fcd_file.xsd" "$T/base.xsd" -- fcd-export
sumo sumo-tripinfo sumotripinfo "trip information output" "$X/tripinfo_file.xsd" "$T/base.xsd" -- tripinfos
sumo sumo-emission sumoemission "emission output" "$X/emission_file.xsd" "$T/base.xsd" -- emission-export
sumo sumo-battery sumobattery "battery output" "$X/battery_file.xsd" "$T/base.xsd" -- battery-export
sumo sumo-collision sumocollision "collision output" "$X/collision_file.xsd" "$T/base.xsd" -- collisions
sumo sumo-det-e1 sumodete1 "induction loop (E1) detector output" "$X/det_e1_file.xsd" -- detector
sumo sumo-det-e1meso sumodete1meso "induction loop (E1) detector output of the mesoscopic model" "$X/det_e1meso_file.xsd" "$T/base.xsd" -- detector
sumo sumo-det-e2 sumodete2 "lane area (E2) detector output" "$X/det_e2_file.xsd" -- detector
sumo sumo-det-e3 sumodete3 "multi-entry-exit (E3) detector output" "$X/det_e3_file.xsd" -- e3Detector
sumo sumo-instant-e1 sumoinstante1 "instantaneous induction loop output" "$X/instant_e1_file.xsd" "$T/base.xsd" -- instantE1
sumo sumo-meandata sumomeandata "edge and lane traffic measures output" "$X/meandata_file.xsd" "$T/meandata.xsd" "$T/base.xsd" -- meandata
sumo sumo-netstate sumonetstate "raw network state dump" "$X/netstate_file.xsd" "$T/base.xsd" -- netstate
sumo sumo-queue sumoqueue "lane queue output" "$X/queue_file.xsd" "$T/base.xsd" -- queue-export
sumo sumo-statistic sumostatistic "simulation statistics output" "$X/statistic_file.xsd" "$T/base.xsd" -- statistics
sumo sumo-stopinfo sumostopinfo "stop information output" "$X/stopinfo_file.xsd" "$T/base.xsd" -- stops
sumo sumo-tlsstates sumotlsstates "traffic light states output" "$X/tlsstates_file.xsd" "$T/base.xsd" -- tlsStates
sumo sumo-tlsswitches sumotlsswitches "traffic light switch output" "$X/tlsswitches_file.xsd" "$T/base.xsd" -- tlsSwitches
sumo sumo-vtypeprobe sumovtypeprobe "vehicle type probe output" "$X/vtypeprobe_file.xsd" "$T/base.xsd" -- vehicle-type-probes
sumo sumo-calibratorstats sumocalibratorstats "calibrator statistics output" "$X/calibratorstats_file.xsd" "$T/base.xsd" -- calibratorstats
sumo sumo-full sumofull "full network and vehicle dump" "$X/full_file.xsd" "$T/base.xsd" -- full-export
sumo sumo-amitran-trajectories sumoamitrantrajectories "Amitran trajectory output" "$X/amitran/trajectories.xsd" -- trajectories

# network and demand inputs
sumo sumo-net sumonet "network" "$X/net_file.xsd" "$T/taz.xsd" "$T/base.xsd" -- net
sumo sumo-routes sumoroutes "route and demand definitions" "$X/routes_file.xsd" "$T/route.xsd" "$T/base.xsd" -- routes route-alternatives
sumo sumo-additional sumoadditional "additional infrastructure definitions" "$X/additional_file.xsd" "$T/metadata.xsd" "${CONFIG[@]}" "$T/route.xsd" "$T/taz.xsd" "$T/base.xsd" -- additional -- --skip metadata
sumo sumo-edges sumoedges "plain edge definitions" "$X/edges_file.xsd" "$T/base.xsd" -- edges
sumo sumo-nodes sumonodes "plain node definitions" "$X/nodes_file.xsd" "$T/base.xsd" -- nodes
sumo sumo-connections sumoconnections "plain connection definitions" "$X/connections_file.xsd" "$T/base.xsd" -- connections
sumo sumo-types sumotypes "edge type definitions" "$X/types_file.xsd" "$T/base.xsd" -- types
sumo sumo-tllogic sumotllogic "traffic light program definitions" "$X/tllogic_file.xsd" "$T/base.xsd" -- tlLogics
sumo sumo-taz sumotaz "traffic assignment zone definitions" "$X/taz_file.xsd" "$T/taz.xsd" "$T/base.xsd" -- tazs
sumo sumo-ptlines sumoptlines "public transport line definitions" "$X/ptlines_file.xsd" "$T/route.xsd" "$T/base.xsd" -- ptLines
sumo sumo-turns sumoturns "turn count and turn ratio definitions" "$X/turns_file.xsd" "$T/base.xsd" -- turns
sumo sumo-detectors sumodetectors "detector definitions for the flow router" "$X/detectors_file.xsd" "$T/base.xsd" -- detectors
sumo sumo-edgediff sumoedgediff "network difference of edges" "$X/edgediff_file.xsd" "$T/base.xsd" -- edges
sumo sumo-datamode sumodatamode "edge data definitions" "$X/datamode_file.xsd" "$T/base.xsd" -- data
sumo sumo-genericparameter sumogenericparameter "generic parameter file" "$X/genericparameter_file.xsd" -- genericParameter
sumo sumo-state sumostate "saved simulation state" "$X/state_file.xsd" "$X/additional_file.xsd" "$T/metadata.xsd" "${CONFIG[@]}" "$T/route.xsd" "$T/taz.xsd" "$T/base.xsd" -- snapshot -- --skip rngState
sumo sumo-amitran-linkdata sumoamitranlinkdata "Amitran link data" "$X/amitran/linkdata.xsd" -- linkData
sumo sumo-amitran-network sumoamitrannetwork "Amitran network" "$X/amitran/network.xsd" -- network
sumo sumo-amitran-od sumoamitranod "Amitran origin-destination demand" "$X/amitran/od.xsd" -- demand
sumo sumo-amitran-routes sumoamitranroutes "Amitran routes" "$X/amitran/routes.xsd" -- routes
exit "$STATUS"
