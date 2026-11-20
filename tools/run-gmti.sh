#!/bin/bash
# Regenerate the STANAG 4607 (GMTI) and STANAG 4676 (ISR tracking) packs of this repository.
#
# Usage: tools/run-gmti.sh
#
# Inputs, all in this repository (layouts and the data model restated in its own words):
#   tools/gmti/segments.tsv.txt kinds.tsv.txt tables.tsv.txt profiles.tsv.txt   AEDP-4607 Ed A V1 and AEDP-4607.1
#   tools/isr-tracking/model.tsv.txt kinds.tsv.txt                       AEDP-12 Ed B V2
# model.tsv.txt was listed from the document's class tables by tools/isr-tracking/uml2tsv.py;
# rerun that only when the document changes (it needs pdftotext and a copy of the document; neither is in this repository).
# Writes:
#   model/gmti.def, packs/gmti, packs/gmti-segment, packs/gmti-records, packs/gmti-segment-records
#   model/isrtrack.def, packs/isr-tracking
# Vectors are written by the vectors.py of each directory, which do not read the packs.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
python3 -I tools/gmti/gmti2pack.py
python3 -I tools/gmti/vectors.py
python3 -I tools/isr-tracking/isr2pack.py
python3 -I tools/isr-tracking/vectors.py
