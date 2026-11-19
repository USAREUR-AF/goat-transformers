#!/bin/bash
# Regenerate the NeTEx packs: one per frame type, each reading that frame inside a
# CompositeFrame of a PublicationDelivery.
#
# Usage: tools/gen/netex-run.sh [--check] [--fetch] <checkout> <sources>
#
# <checkout> is a goat-transformers checkout. It is read (model/core.def, model/track.def)
# and written: model/<module>.def, packs/<format>/{pack.def,pack.md,vectors/gen-*.json} and
# tools/gen/names/<format>.json of the four packs below. PROVENANCE.md is not generated.
#
# With --check nothing is written: each run compares what it would write with the files
# of <checkout> and with its names file (xsd2pack.py --check), all runs are made, and the
# exit status is 1 when any file differs.
#
# <sources> holds the NeTEx repository's xsd/ directory: <sources>/xsd/NeTEx_publication.xsd
# and the files it includes. With --fetch, when that file is missing, the repository at the
# commit below is downloaded from
#   https://codeload.github.com/NeTEx-CEN/NeTEx/tar.gz/<commit>
# (github.com/NeTEx-CEN/NeTEx redirects to github.com/TransmodelEcosystem/NeTEx) and its
# xsd/ directory is extracted. Every file read is checked against the SHA-256 that
# tools/gen/sources/netex-xsd.txt pins; a mismatch stops the run. The files are not kept in
# this repository. The repository's LICENSE is the GNU General Public License version 3
# (packs/netex-service-frame/PROVENANCE.md quotes it).
#
# The xml files of namespaces other than NeTEx's (GML 3.2, SIRI, xml:) are not read
# (--decline-namespace); what refers to them is listed as not mapped in pack.md.
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
COMMIT=11d40b5e94684fa2ddea0222702b220d7d93760b
MANIFEST="$GEN/sources/netex-xsd.txt"

if [ ! -f "$SRC/xsd/NeTEx_publication.xsd" ]; then
  if [ "$FETCH" != 1 ]; then
    echo "missing $SRC/xsd/NeTEx_publication.xsd (run with --fetch to download it)" >&2
    exit 1
  fi
  curl -fsSL -o "$SRC/netex-$COMMIT.tar.gz" "https://codeload.github.com/NeTEx-CEN/NeTEx/tar.gz/$COMMIT"
  tar -xzf "$SRC/netex-$COMMIT.tar.gz" -C "$SRC" --strip-components=1 --wildcards '*/xsd/*'
fi

XSDS=()
while read -r sha rel; do
  case "$sha" in ''|'#'*) continue ;; esac
  got="$(sha256sum "$SRC/$rel" | cut -d' ' -f1)"
  if [ "$got" != "$sha" ]; then
    echo "$rel: sha256 $got, expected $sha" >&2
    exit 1
  fi
  XSDS+=("$SRC/$rel")
done < "$MANIFEST"

TITLE="NeTEx (CEN/TS 16614) XML schema, github.com/NeTEx-CEN/NeTEx commit $COMMIT: NeTEx_publication.xsd and the files it includes, ${#XSDS[@]} files"
STATEMENT="The NeTEx-CEN/NeTEx repository at commit $COMMIT carries a LICENSE file with the GNU General \
Public License version 3; its README states (C) 2009-2026 NeTEx, CEN, Crown Copyright. Element and \
attribute names, types and value ranges only."
STATUS=0

# netex <format> <module> <frame element>
netex() {
  if ! python3 -I "$GEN/xsd2pack.py" \
      --xsd "${XSDS[@]}" \
      --format "$1" --module "$2" --out "$CHECKOUT" --model-dir "$CHECKOUT/model" \
      --title "$TITLE; the $3 of a CompositeFrame" \
      --public-statement "$STATEMENT" \
      --decline-namespace http://www.opengis.net/gml/3.2 \
      --decline-namespace http://www.siri.org.uk/siri \
      --decline-namespace http://www.w3.org/XML/1998/namespace \
      --substitution-groups --substitute "CommonFrame=$3" \
      --skip PublicationRequest --skip "dataObjects/$3" \
      --message PublicationDelivery --max-depth 10 --max-nest 3 \
      --version 0.1.0 \
      --notes-file "$GEN/notes/netex.md" \
      --names-file "$GEN/names/$1.json" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

netex netex-service-frame netexservice ServiceFrame
netex netex-site-frame netexsite SiteFrame
netex netex-timetable-frame netextimetable TimetableFrame
netex netex-service-calendar-frame netexcalendar ServiceCalendarFrame
exit "$STATUS"
