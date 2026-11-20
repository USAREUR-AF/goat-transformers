#!/bin/sh
# Compile the Erlang engine (OTP stdlib only, plain erlc).
#
#   ./build.sh                                  every wire, into ebin/
#   ./build.sh --wires xml,json,geojson         only those wires (Version 0.24)
#   ./build.sh --wires xml --out <dir>          into <dir> instead of ebin/
#
# The wires are xml, geojson, json, bits, protobuf, text, tlv and cbor. A wire not
# named is left out: its modules are not compiled, and the code of gt_engine
# and gt_pack that only it needs is compiled out with -Dno_wire_<wire>
# (src/gt_wires.hrl). A pack on such a wire is unknown-wire at load.
set -eu
cd "$(dirname "$0")"
all="xml geojson json bits protobuf text tlv cbor"
wires=$all
out=ebin
while [ $# -gt 0 ]; do
    case $1 in
        --wires) [ $# -ge 2 ] || { echo "build.sh: --wires needs a list" >&2; exit 2; }
                 wires=$(echo "$2" | tr ',' ' '); shift 2 ;;
        --out) [ $# -ge 2 ] || { echo "build.sh: --out needs a directory" >&2; exit 2; }
               out=$2; shift 2 ;;
        *) echo "build.sh: unknown argument $1" >&2; exit 2 ;;
    esac
done
has() { case " $wires " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
for w in $wires; do
    case " $all " in *" $w "*) ;; *) echo "build.sh: $w is not a wire (one of: $all)" >&2; exit 2 ;; esac
done
[ -n "$(echo $wires)" ] || { echo "build.sh: --wires names no wire" >&2; exit 2; }

defs=""
for w in $all; do has "$w" || defs="$defs -Dno_wire_$w"; done

# the engine's core, then the modules of each wire in the set
mods="gt_engine gt_pack gt_model gt_num gt_derive gt_iso gt_licence gt_cli"
has xml && mods="$mods gt_xml"
# gt_json reads JSON text for json and geojson, and the conformance
# runner gt_test and the benchmark gt_bench read JSON with it
if has json || has geojson; then mods="$mods gt_json gt_test gt_bench"; fi
has bits && mods="$mods gt_bits gt_seq"
has protobuf && mods="$mods gt_protobuf"
has text && mods="$mods gt_text"
has tlv && mods="$mods gt_tlv"
has cbor && mods="$mods gt_cbor"
if has bits || has protobuf || has tlv || has cbor; then mods="$mods gt_hex"; fi

srcs=""
for m in $mods; do srcs="$srcs src/$m.erl"; done
# every wire: every module, as before 0.24
[ -n "$defs" ] || srcs=$(echo src/*.erl)
mkdir -p "$out"
rm -f "$out"/*.beam
# shellcheck disable=SC2086
erlc -Wall $defs -o "$out" $srcs
echo "built: $(ls "$out"/*.beam | wc -l) modules, wires: $(echo $wires)"
