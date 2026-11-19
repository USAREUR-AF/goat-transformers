#!/bin/bash
# Regenerate the CCSDS parts of the tree: the generated pack ccsds-ndm-xml and the
# vectors of the five hand-written CCSDS bits packs.
#
# Usage: tools/gen/ccsds-run.sh <root> <goat-transformers checkout> [--fetch]
#
# <root> holds sources/ndmxml/ (the fourteen XSD files below) and receives the
# generator's output (model/, packs/ccsds-ndm-xml/). With --fetch, a file that is
# missing is downloaded from its address first. Every file is checked against the
# SHA-256 below before it is read; a mismatch stops the run.
#
# The checkout supplies model/core.def and model/track.def and receives:
#   model/ccsdsndm.def, packs/ccsds-ndm-xml/{pack.def,pack.md,vectors/gen-*.json}
#     (generated; the hand-written vectors 0*.json of that pack are not touched)
#   tools/gen/names/ccsds-ndm-xml.json (read and extended)
#   packs/ccsds-{space-packet,tm-frame,tc-frame,aos-frame,clcw}/vectors/*.json
#     (written by tools/gen/ccsds-vectors.py, which imports no engine)
# The pack.def, pack.md and PROVENANCE.md of the five bits packs and the
# PROVENANCE.md of ccsds-ndm-xml are hand-written and not touched.
#
# Source: CCSDS 505.0-B-3 (NDM/XML), schema set 4.0.0, the "unqualified" variant
# (elementFormDefault unqualified), Space Assigned Numbers Authority registry
# ndmxml_unqualified. Each file is
#   https://sanaregistry.org/files/ndmxml_unqualified/<name>
# The registry page is https://sanaregistry.org/r/ndmxml_unqualified (updated
# 2024-08-21 when read). The files carry no license statement; the reuse terms
# are the CCSDS reproduction permission statement quoted in
# packs/ccsds-ndm-xml/PROVENANCE.md.
set -euo pipefail
ROOT="$1"
GT="$2"
FETCH="${3:-}"
GEN="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/sources/ndmxml"
BASE="https://sanaregistry.org/files/ndmxml_unqualified"

# name sha256 - the master file first: it declares the message roots
FILES="
ndmxml-4.0.0-master-4.0.xsd 2abc69ce7b09a14a06223ca73e9962dffe2721997636f24145523a4db67adf36
ndmxml-4.0.0-namespace-4.0.xsd 452daae18e9b98f8542c013d2e12581aaa81165d9646bd387c1f72e4dd5336a6
ndmxml-4.0.0-acm-2.0.xsd 0c46c47085cf2a8cfd98974edec0380d619587c861a0ebd2b722e30668ca5b21
ndmxml-4.0.0-aem-2.0.xsd 4cce5b5e2bf0d9b7f925c7c27c9e202b72295c99f87f4987be847e59a57ca5f3
ndmxml-4.0.0-apm-2.0.xsd 9c88db63741cd6dc49398ab48f9972973371d8e0d4fdce2bff1fa09ee9ead93d
ndmxml-4.0.0-cdm-1.0.xsd 9814cb81bcc275bb08fc87844cd663774fcf2dc7636a070963a797b1dab2f494
ndmxml-4.0.0-ocm-3.0.xsd 68835f8d1674e3ed3c10cde296a1f2c7df6b575c1599395531ab963caee915fa
ndmxml-4.0.0-oem-3.0.xsd 7dc5ff90492d5570f386f1d640a8ec6d0fe9955ed2248ae05fb3255c75ca8b9a
ndmxml-4.0.0-omm-3.0.xsd e54622ea48972a923c1edee607f717257262114ae5ad7bdba031d1bbd28e2a1a
ndmxml-4.0.0-opm-3.0.xsd 193e2effa72727e933eaaa8283c6f47bcd8e1b44f7675b8be13ba30623499519
ndmxml-4.0.0-rdm-1.0.xsd ffb45a290c65254dad76ff4c6af554a14256a74c5684432c0799631a51e4eea8
ndmxml-4.0.0-tdm-2.0.xsd 19ab390e06c8ebbb1f9585f044fc044edd5e453e6c8f0de24bdde63a1f3f7dd8
ndmxml-4.0.0-ndm-4.0.xsd 14df592d0991d6230e677f2e2bf1e5b971567b514313b0d3c019f534e2e162c5
ndmxml-4.0.0-common-4.0.xsd 3ae25a917a8297dc7c77f98569e939351b5247e3216d239189fd6934d8d5dcde
"

mkdir -p "$SRC"
XSDS=()
while read -r name sha; do
  [ -n "$name" ] || continue
  if [ ! -f "$SRC/$name" ]; then
    if [ "$FETCH" = "--fetch" ]; then
      curl -fsSL -o "$SRC/$name" "$BASE/$name"
    else
      echo "missing $SRC/$name (run with --fetch to download it)" >&2
      exit 1
    fi
  fi
  got="$(sha256sum "$SRC/$name" | cut -d' ' -f1)"
  if [ "$got" != "$sha" ]; then
    echo "$name: sha256 $got, expected $sha" >&2
    exit 1
  fi
  XSDS+=("$SRC/$name")
done <<< "$FILES"

STATEMENT="CCSDS reproduction permission statement for publications (ccsds.org): in general, \
reasonable reuse of materials published in CCSDS documents is permitted with attribution. \
The schema set is published without registration at https://sanaregistry.org/r/ndmxml_unqualified."

python3 -I "$GEN/xsd2pack.py" \
  --xsd "${XSDS[@]}" \
  --format ccsds-ndm-xml --module ccsdsndm --out "$ROOT" --model-dir "$GT/model" \
  --title "CCSDS Navigation Data Messages XML (NDM/XML, CCSDS 505.0-B-3) schema set 4.0.0, elementFormDefault unqualified, https://sanaregistry.org/r/ndmxml_unqualified" \
  --source "CCSDS 505.0-B-3 XML Specification for Navigation Data Messages, Blue Book, May 2023, https://ccsds.org/Pubs/505x0b3e2.pdf" \
  --source "CCSDS 502.0-B-3 Orbit Data Messages, Blue Book, April 2023, https://ccsds.org/Pubs/502x0b3e1.pdf; CCSDS 504.0-B-2 Attitude Data Messages, Blue Book, January 2024, https://ccsds.org/Pubs/504x0b2.pdf (meaning of OBJECT_NAME and OBJECT_ID)" \
  --public-statement "$STATEMENT" \
  --message acm --message aem --message apm --message cdm --message ocm \
  --message oem --message omm --message opm --message rdm --message tdm \
  --map "opm:body/segment/metadata/OBJECT_ID/#text=uid" \
  --map "opm:body/segment/metadata/OBJECT_NAME/#text=callsign" \
  --map "omm:body/segment/metadata/OBJECT_ID/#text=uid" \
  --map "omm:body/segment/metadata/OBJECT_NAME/#text=callsign" \
  --map "apm:body/segment/metadata/OBJECT_ID/#text=uid" \
  --map "apm:body/segment/metadata/OBJECT_NAME/#text=callsign" \
  --notes-file "$GEN/notes/ccsds-ndm-xml.md" \
  --names-file "$GEN/names/ccsds-ndm-xml.json"

# copy the generated files into the checkout
mkdir -p "$GT/packs/ccsds-ndm-xml/vectors"
cp "$ROOT/model/ccsdsndm.def" "$GT/model/ccsdsndm.def"
cp "$ROOT/packs/ccsds-ndm-xml/pack.def" "$ROOT/packs/ccsds-ndm-xml/pack.md" "$GT/packs/ccsds-ndm-xml/"
rm -f "$GT"/packs/ccsds-ndm-xml/vectors/gen-*.json
cp "$ROOT"/packs/ccsds-ndm-xml/vectors/gen-*.json "$GT/packs/ccsds-ndm-xml/vectors/"

# the vectors of the hand-written bits packs
python3 -I "$GEN/ccsds-vectors.py" --out "$GT"
