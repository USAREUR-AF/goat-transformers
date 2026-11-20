#!/bin/bash
# Regenerate the dis7 pack: one `bits` pack for the Distributed Interactive
# Simulation protocol, version 7 (IEEE 1278.1-2012), one kind per PDU type, and
# its module model/dis7.def.
#
# Usage: tools/gen/dis-run.sh <checkout> <sources> [--fetch] [--check]
#
# <checkout> is a goat-transformers checkout; it is written: model/dis7.def and
# packs/dis7/ (pack.def, pack.md, PROVENANCE.md, vectors/). The generator checks
# the SHA-256 of every input against tools/gen/sources/dis-PROVENANCE.md and stops
# when one differs. With --check it writes nothing and reports any file that
# differs from what it would write.
#
# <sources> is a directory for the two source trees, not kept in the repository.
# With --fetch the script downloads
#   https://codeload.github.com/open-dis/xmlpg/tar.gz/35ed3733009a89a34604abad87d1aefc1fdfbbc2
#   sha256 a58d9e9f3487e22b51855684a4c10c54ebad16b4729f37dc7fe2359078f52af7
#   (branch master; DIS2012.xml holds the PDU and record layouts)
#   https://codeload.github.com/open-dis/open-dis-python/tar.gz/48cb4fa59b44ad50d9f519190e53609ef7a3ef19
#   sha256 53a2921c48d680185c4f4fd77639ca7691f7a5bae4c8a7fa7f4acd25edc5d936
#   (branch master; opendis/dis7.py states the PDU type of each PDU class)
# and unpacks them to <sources>/xmlpg-<commit>/ and <sources>/open-dis-python-<commit>/.
# Licenses: BSD 2-Clause both (xmlpg LICENSE.md, Copyright (c) 2015, mcgredonps;
# open-dis-python LICENSE, Copyright (c) 2023, Open DIS), verbatim in
# tools/gen/sources/dis-PROVENANCE.md. The generator reads both as data and runs
# neither.
#
# The xmlpg README says DIS2012.xml is no longer maintained and that corrections
# go to the generated libraries. Each kind was compared with open-dis-python by a
# scratch check outside the repository: a PDU with one field set at a time was
# read by open-dis-python, and the field must come back alone and unchanged. The
# PDU classes below failed that check, or could not be read by open-dis-python
# at this commit, and get no kind.
set -euo pipefail
ROOT="$(cd "$1" && pwd)"
mkdir -p "$2"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
XMLPG=35ed3733009a89a34604abad87d1aefc1fdfbbc2
XMLPG_SHA=a58d9e9f3487e22b51855684a4c10c54ebad16b4729f37dc7fe2359078f52af7
OPENDIS=48cb4fa59b44ad50d9f519190e53609ef7a3ef19
OPENDIS_SHA=53a2921c48d680185c4f4fd77639ca7691f7a5bae4c8a7fa7f4acd25edc5d936
shift 2
if [ "${1:-}" = "--fetch" ]; then
  shift
  curl -sS -f -L -o "$SRC/xmlpg-$XMLPG.tar.gz" "https://codeload.github.com/open-dis/xmlpg/tar.gz/$XMLPG"
  echo "$XMLPG_SHA  $SRC/xmlpg-$XMLPG.tar.gz" | sha256sum -c -
  tar -xzf "$SRC/xmlpg-$XMLPG.tar.gz" -C "$SRC"
  curl -sS -f -L -o "$SRC/open-dis-python-$OPENDIS.tar.gz" "https://codeload.github.com/open-dis/open-dis-python/tar.gz/$OPENDIS"
  echo "$OPENDIS_SHA  $SRC/open-dis-python-$OPENDIS.tar.gz" | sha256sum -c -
  tar -xzf "$SRC/open-dis-python-$OPENDIS.tar.gz" -C "$SRC"
fi
DIFFERS="the XML layout and open-dis-python's reading of the same bytes differ"
UNREAD="open-dis-python at this commit cannot read the PDU, so the XML layout is unchecked"
EXCLUDE=(
  --exclude "CreateEntityPdu=$DIFFERS"
  --exclude "RemoveEntityPdu=$DIFFERS"
  --exclude "StartResumePdu=$DIFFERS"
  --exclude "StopFreezePdu=$DIFFERS"
  --exclude "AcknowledgePdu=$DIFFERS"
  --exclude "StartResumeReliablePdu=$DIFFERS"
  --exclude "ArealObjectStatePdu=$DIFFERS"
  --exclude "ResupplyOfferPdu=$UNREAD"
  --exclude "IntercomControlPdu=$UNREAD"
  --exclude "LinearObjectStatePdu=$UNREAD"
  --exclude "ResupplyReceivedPdu=open-dis-python at this commit cannot read its counted items, so their XML layout is unchecked"
  --exclude "MinefieldResponseNackPdu=open-dis-python at this commit cannot read its counted items, so their XML layout is unchecked"
  --exclude "RecordQueryReliablePdu=open-dis-python at this commit cannot read its counted items, so their XML layout is unchecked"
  --exclude "IntercomSignalPdu=open-dis-python reads the data length as a count of bits (data length / 8 bytes); the XML counts bytes, and a bits group counts items, not bits"
  --exclude "EntityDamageStatusPdu=open-dis-python reads each item as a standard variable record whose own length field gives its size; the XML fixes every item at 40 bytes"
)
python3 -I "$GEN/dis2pack.py" --xmlpg "$SRC/xmlpg-$XMLPG" --opendis "$SRC/open-dis-python-$OPENDIS" \
  --out "$ROOT" --core-def "$ROOT/model/core.def" "${EXCLUDE[@]}" "$@"
