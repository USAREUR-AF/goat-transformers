#!/bin/bash
# Regenerate the arsdk-* packs: one pack per Parrot ARSDK feature, one kind per command,
# from the message definitions of arsdk-xml and the wire encoding of libARCommands.
#
# Usage: tools/gen/arsdk-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the generator compares what it would
# write with the files there, lists every difference and exits 1 when there is one.
#
# <sources> holds (none is kept in the repository; each pack's PROVENANCE.md has the
# SHA-256 of the files it reads):
#
#   <sources>/arsdk-xml/xml/*.xml   the 45 files of xml/ at
#     github.com/Parrot-Developers/arsdk-xml commit 2299c689be5951fa2104793e0154b0b5b1896c03,
#     each https://raw.githubusercontent.com/Parrot-Developers/arsdk-xml/<commit>/xml/<name>.xml
#     BSD-3-Clause by each file's header (Copyright (C) Parrot SA / Parrot Drones SAS).
#   <sources>/libARCommands/Tools/libARCommandsgen.py
#     github.com/Parrot-Developers/libARCommands commit d25b24e3d37c4fdf092d83196f575baf17420652
#     (LICENSE.md: BSD-3-Clause, Copyright (C) 2014 Parrot SA): the command header and the
#     argument sizes. Read by the author of the generator; the generator records its SHA-256.
#   <sources>/libARSAL/Includes/libARSAL/ARSAL_Endianness.h
#     github.com/Parrot-Developers/libARSAL commit 22e1f6b12aa6e46b26a75b768fd224c29ee00326
#     (LICENSE.md: BSD-3-Clause, Copyright (C) 2014 Parrot SA): the little-endian device byte
#     order. Read by the author; the generator records its SHA-256.
set -euo pipefail
CHECK=()
if [ "${1:-}" = "--check" ]; then
  CHECK=(--check)
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <checkout> <sources>" >&2
  exit 2
fi
CHECKOUT="$(cd "$1" && pwd)"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
python3 -I "$GEN/arsdk2pack.py" ${CHECK[@]+"${CHECK[@]}"} \
  --xml-dir "$SRC/arsdk-xml/xml" --out "$CHECKOUT" --model-dir "$CHECKOUT/model" \
  --xml-commit 2299c689be5951fa2104793e0154b0b5b1896c03 \
  --libarcommands-gen "$SRC/libARCommands/Tools/libARCommandsgen.py" \
  --libarsal-endianness "$SRC/libARSAL/Includes/libARSAL/ARSAL_Endianness.h"
