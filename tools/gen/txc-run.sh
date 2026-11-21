#!/bin/bash
# Regenerate the TransXChange 2.4 packs: the whole document, and the document read for one of
# its sections (stop points, services, vehicle journeys).
#
# Usage: tools/gen/txc-run.sh [--check] [--fetch] <checkout> <sources>
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def, model/track.def)
# and written: model/<module>.def, packs/<format>/{pack.def,pack.md,vectors/gen-*.json} and
# tools/gen/names/<format>.json of the packs below. PROVENANCE.md is not generated.
#
# With --check nothing is written: each run compares what it would write with the files
# of <checkout> and with its names file (xsd2pack.py --check), all runs are made, and the
# exit status is 1 when any file differs.
#
# <sources> holds the schema files of TransXChange 2.4 under the paths
# tools/gen/sources/txc-xsd.txt lists (TransXChange_general.xsd, txc/, napt/, nptg/). With
# --fetch, a missing file is downloaded from the Department for Transport's address
#   http://www.transxchange.org.uk/schema/2.4/<path>
# (the address the DfT publication "TransXChange: downloads and schema" on gov.uk gives for
# the 2.4 schema). Every file read is checked against the SHA-256 the manifest pins; a
# mismatch stops the run. The files are not kept in this repository. They state Crown
# Copyright; GOV.UK publishes the schema under the Open Government Licence v3.0
# (packs/txc/PROVENANCE.md).
#
# The files of the govtalk.gov.uk address and personal-details namespaces (apd/) and the xml:
# namespace are not read (--decline-namespace): their elements carry a namespace of their
# own, which an instance writes with a prefix; what refers to them is listed as not mapped.
# The NaPTAN and NPTG files are chameleon includes that take the TransXChange namespace, so
# an instance writes them without a prefix, under the document's default namespace.
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
BASE=http://www.transxchange.org.uk/schema/2.4
MANIFEST="$GEN/sources/txc-xsd.txt"

XSDS=()
while read -r sha rel; do
  case "$sha" in ''|'#'*) continue ;; esac
  if [ ! -f "$SRC/$rel" ]; then
    if [ "$FETCH" != 1 ]; then
      echo "missing $SRC/$rel (run with --fetch to download it)" >&2
      exit 1
    fi
    mkdir -p "$(dirname "$SRC/$rel")"
    curl -fsSL -o "$SRC/$rel" "$BASE/$rel"
  fi
  got="$(sha256sum "$SRC/$rel" | cut -d' ' -f1)"
  if [ "$got" != "$sha" ]; then
    echo "$rel: sha256 $got, expected $sha" >&2
    exit 1
  fi
  XSDS+=("$SRC/$rel")
done < "$MANIFEST"

TITLE="TransXChange 2.4 XML schema (Department for Transport), $BASE: TransXChange_general.xsd and the files it includes, ${#XSDS[@]} files"
STATEMENT="The TransXChange 2.4 schema files state Crown Copyright and are published by the Department \
for Transport at $BASE through GOV.UK, whose content is available under the Open Government Licence \
v3.0. Element and attribute names, types and value ranges only."
STATUS=0

# txc <format> <module> <what> [options...]
txc() {
  local fmt="$1" mod="$2" what="$3"
  shift 3
  if ! python3 -I "$GEN/xsd2pack.py" \
      --xsd "${XSDS[@]}" \
      --format "$fmt" --module "$mod" --out "$CHECKOUT" --model-dir "$CHECKOUT/model" \
      --title "$TITLE; $what" \
      --public-statement "$STATEMENT" \
      --decline-namespace http://www.govtalk.gov.uk/core \
      --decline-namespace http://www.govtalk.gov.uk/people/AddressAndPersonalDetails \
      --decline-namespace http://www.govtalk.gov.uk/people/bs7666 \
      --decline-namespace http://www.govtalk.gov.uk/people/PersonDescriptives \
      --decline-namespace http://www.w3.org/XML/1998/namespace \
      --message TransXChange --max-depth 10 --max-nest 3 \
      --version 0.1.0 \
      --notes-file "$GEN/notes/txc.md" \
      --names-file "$GEN/names/$fmt.json" "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

txc txc txc "the whole TransXChange document"
exit "$STATUS"
