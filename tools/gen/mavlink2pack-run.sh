#!/bin/bash
# Regenerate the MAVLink 2 packs: mavlink2 (common.xml with standard.xml and
# minimal.xml) and one pack per dialect, mavlink2-<dialect in lower case>.
#
# Usage: tools/gen/mavlink2pack-run.sh <checkout> <sources> [--fetch] [generator options]
#
# Generator options are passed to every run. With none the packs are written
# as version 0.1.0 of the generator wrote them: arrays of more than 8 elements
# and the INCOMPAT/COMPAT bytes are not mapped. `--max-array 255 --compat-flags`
# maps every payload array and both flag bytes.
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def, each
# pack's PROVENANCE.md) and written: model/mavlink.def, model/mavlink<dialect>.def,
# packs/mavlink2/ and packs/mavlink2-<dialect>/ (pack.def, pack.md, vectors/).
# PROVENANCE.md is not written; the generator reads the commit and the SHA-256 of
# every input from it and stops when a file differs.
#
# <sources> holds the XML files. They are not kept in the repository. With
# --fetch the script downloads them first. Every file is
#   https://raw.githubusercontent.com/mavlink/mavlink/12c898d88ce18d24e8caf6338596e98c5005bc97/message_definitions/v1.0/<name>
# and COPYING is
#   https://raw.githubusercontent.com/mavlink/mavlink/12c898d88ce18d24e8caf6338596e98c5005bc97/COPYING
#
#   sha256                                                            file
#   a4ac8a1144529195af6f948e5b4429bae0bd7b8650472d0ce09fbc5ca7bde7d6  common.xml
#   0c08a5be4a858910ac02111a51551e0b8fa2088675a5ca0a48dfd7792fa94018  standard.xml
#   7b1e79a1cadedb618042a3f78c09a76ef1f7440df71fa179e647001eeab7475b  minimal.xml
#   8cff0bf2ae5bec60d16118bf37e1ec6e9f55f54aecc486df0b18f89977479047  ardupilotmega.xml
#   c5e15be9309138de988ee4a744bfb431cfa1aed52dd4bc93466fee484fe4197c  ASLUAV.xml
#   9ee1641e0c7f6be25faa817a1d17715dc79dfecbce0ba15833a0559cef1c1c1c  AVSSUAS.xml
#   f5b5ba62d0b65953438981ca95fc45dceb98d63601dfc0705ad91184227ee24d  csAirLink.xml
#   b4f76d660b41b16746f67fa8e17321ea6b65448791045154105f29b3a70ce7b9  cubepilot.xml
#   edea061b77b7adc8ea0146e3504929119ea7dabf5e49c88f25c16dbc3ccbbf83  development.xml
#   e40ec11a6d76b48eb815c101c96b1849c76a8ba5302a01d39f1941ff9c501bbb  icarous.xml
#   31f20f01d436f2fbaaaf86f4a51c60cc01bc42722ae4c5ad403afeaaaa512deb  loweheiser.xml
#   fd2749db90344b90425416b0b47d7079fc5c0bed3b56f7be18a67d3a67151ed0  marsh.xml
#   1920f6542ac9099f688543d0b32f962b6079992b6af33605e88f4e60f0d05b2b  paparazzi.xml
#   10e298e93cd8404ac7e485804b71d08380c38d39a8be2c72bf4c6a40e564bebb  stemstudios.xml
#   55d7b66ec1e698e7b8562df81ee564f21bb8745f9af1243889df65e0b154e42d  storm32.xml
#   bd9adf101205744270be9b5fc7205d1c73e365a619435fffc2623958069da516  uAvionix.xml
#   81133ba4d3343a0e627dd0d9582134f956bc9dc82322d369c561249cc2910224  upstream-COPYING.txt (COPYING)
#
# Not generated, at this commit: all.xml (includes every other file, defines no
# message), test.xml and python_array_test.xml (test inputs of the upstream code
# generator). matrixpilot.xml and ualberta.xml were removed upstream before this
# commit.
#
# The dialect packs hold only the messages their own file defines; each reads
# module `mavlink` for the frame-header keys, so mavlink2 runs first.
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
COMMIT=12c898d88ce18d24e8caf6338596e98c5005bc97
DIALECTS="ardupilotmega ASLUAV AVSSUAS csAirLink cubepilot development icarous loweheiser marsh paparazzi stemstudios storm32 uAvionix"

shift 2
FETCH=0
if [ "${1:-}" = "--fetch" ]; then
  FETCH=1
  shift
fi
if [ "$FETCH" = 1 ]; then
  base="https://raw.githubusercontent.com/mavlink/mavlink/$COMMIT"
  for f in common standard minimal $DIALECTS; do
    curl -sS -f -o "$SRC/$f.xml" "$base/message_definitions/v1.0/$f.xml"
  done
  curl -sS -f -o "$SRC/upstream-COPYING.txt" "$base/COPYING"
fi

python3 -I "$GEN/mavlink2pack.py" --root "$ROOT" --src "$SRC" \
  --provenance "$ROOT/packs/mavlink2/PROVENANCE.md" --core-def "$ROOT/model/core.def" "$@"
for d in $DIALECTS; do
  python3 -I "$GEN/mavlink2pack.py" --root "$ROOT" --src "$SRC" --dialect "$d" \
    --core-def "$ROOT/model/core.def" "$@"
done
