#!/bin/bash
# Regenerate the space JSON packs: CelesTrak GP data (FORMAT=JSON), NASA CCMC DONKI and
# NASA NeoWs.
# Usage: tools/gen/space-run.sh [--check] <sources> <goat-transformers checkout>
#
# None of the three publishes a JSON Schema this project can read as it is. This project
# restated the objects it maps in its own files under tools/gen/space/ (member names, JSON
# types and references only; no description text is copied); this script generates the packs
# from them. The sources the restatements were made from, checked by SHA-256 when present:
#   <sources>/donki-openapi.json  the DONKI-API 2.0 OpenAPI 3.0.1 document,
#     https://ccmc.gsfc.nasa.gov/DONKI/api/openapi/ (read 2026-11-21); a work of NASA, a
#     United States Government agency
#   <sources>/neows-ruby-b81655f31357b1d1700628085c041630111d0f06.tar.gz  the neows-ruby
#     client of the NeoWs maintainers, https://github.com/SpaceRocks/neows-ruby at that
#     commit; MIT
# CelesTrak's GP data documentation (https://celestrak.org/NORAD/documentation/gp-data-formats.php)
# is a web page whose text changes on every request (an access counter), so it is not
# checked; the keywords it names are those of CCSDS 502.0-B-3 (tables 4-1 to 4-3).
#
# Writes model/ckgp.def, model/donki*.def, model/neows*.def, packs/celestrak-gp-json/,
# packs/donki-*/, packs/neows-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-celestrak-gp-json.json and the names files.
# PROVENANCE.md is not generated. With --check nothing is written; every run is made and the
# exit status is 1 when any file differs.
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
STATUS=0
while read -r sha f; do
  [ -e "$SRC/$f" ] || { echo "$f: not in $SRC; not checked" >&2; continue; }
  got="$(sha256sum "$SRC/$f" | cut -d' ' -f1)"
  [ "$got" = "$sha" ] || { echo "$f: sha256 $got, expected $sha" >&2; exit 1; }
done <<'SUMS'
16d2253db190cd4e8673ffc40f3d7fae2facde48cef09ef4ce93157c5705430d donki-openapi.json
4042ef4d52ff34a201ff5c9084b949c005265966c435d9d6c7e67128c1a971f6 neows-ruby-b81655f31357b1d1700628085c041630111d0f06.tar.gz
SUMS
GP="$GEN/space/celestrak-gp-objects.json"
DK="$GEN/space/donki-api-2.0-objects.json"
NW="$GEN/space/neows-1-objects.json"
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
cd "$W"

# [NOTES=<notes file name>] gen <file> <object> <format> <module> <title> <license> <source> [options...]
gen() {
  local file="$1" obj="$2" fmt="$3" mod="$4" title="$5" lic="$6" src="$7"
  shift 7
  if ! python3 -I "$GEN/jsonschema2pack.py" --schema "$file" --message "$obj=$file#/\$defs/$obj" \
      --format "$fmt" --module "$mod" --title "$title" --license "$lic" --source "$src" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/${NOTES:-$fmt}.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

CL="LicenseRef-unstated (CelesTrak states no licence for its GP data documentation; the keywords are those of CCSDS 502.0-B-3, reused with attribution under the CCSDS reproduction permission statement)"
CS="CelesTrak, A New Way to Obtain GP Data (gp-data-formats.php, updated 2026-06-23, read 2026-11-21) and CCSDS 502.0-B-3 Orbit Data Messages (April 2023, tables 4-1 to 4-3), restated in tools/gen/space/celestrak-gp-objects.json"
gen "$GP" GP celestrak-gp-json ckgp \
  "CelesTrak GP data, FORMAT=JSON: one element set (OMM keywords)" "$CL" "$CS" \
  --map GP:OBJECT_ID=uid \
  --evidence "GP:OBJECT_ID=CCSDS 502.0-B-3 (table 4-2) gives OBJECT_ID as the identifier of the object, recommending the international designator (YYYY-NNNP{PP}) that stays with the object for its life; CelesTrak's documentation says the JSON form uses the OMM keywords with their OMM definitions and leaves the member out when the object has no designator. uid is a stable identifier of the entity, with no unit." \
  --cross "$XG"

DL="Apache-2.0 (this project's restatement of the DONKI-API objects; the OpenAPI document is a work of NASA, a United States Government agency, which has no copyright protection in the United States under 17 U.S.C. 105)"
DS="CCMC DONKI-API 2.0, OpenAPI 3.0.1 document https://ccmc.gsfc.nasa.gov/DONKI/api/openapi/ (read 2026-11-21, SHA-256 16d2253db190cd4e8673ffc40f3d7fae2facde48cef09ef4ce93157c5705430d), restated in tools/gen/space/donki-api-2.0-objects.json"
NOTES=donki gen "$DK" CMEJSON donki-cme donkicme "NASA CCMC DONKI, one coronal mass ejection (GET /get/CME)" "$DL" "$DS"
NOTES=donki gen "$DK" CMEAnalysisObject donki-cme-analysis donkicmea "NASA CCMC DONKI, one CME analysis (GET /get/CMEAnalysis)" "$DL" "$DS"
NOTES=donki gen "$DK" FLRObject donki-flr donkiflr "NASA CCMC DONKI, one solar flare (GET /get/FLR)" "$DL" "$DS"
NOTES=donki gen "$DK" GSTObject donki-gst donkigst "NASA CCMC DONKI, one geomagnetic storm (GET /get/GST)" "$DL" "$DS"
NOTES=donki gen "$DK" IPSObject donki-ips donkiips "NASA CCMC DONKI, one interplanetary shock (GET /get/IPS)" "$DL" "$DS"
NOTES=donki gen "$DK" SEPObject donki-sep donkisep "NASA CCMC DONKI, one solar energetic particle event (GET /get/SEP)" "$DL" "$DS"
NOTES=donki gen "$DK" MPCObject donki-mpc donkimpc "NASA CCMC DONKI, one magnetopause crossing (GET /get/MPC)" "$DL" "$DS"
NOTES=donki gen "$DK" RBEObject donki-rbe donkirbe "NASA CCMC DONKI, one radiation belt enhancement (GET /get/RBE)" "$DL" "$DS"
NOTES=donki gen "$DK" HSSObject donki-hss donkihss "NASA CCMC DONKI, one high speed stream (GET /get/HSS)" "$DL" "$DS"
NOTES=donki gen "$DK" NotificationObject donki-notification donkinotif "NASA CCMC DONKI, one notification (GET /get/notifications)" "$DL" "$DS"
NOTES=donki gen "$DK" WSAEnlilObject donki-wsa-enlil donkienlil "NASA CCMC DONKI, one WSA-ENLIL simulation (GET /get/WSAEnlilSimulations)" "$DL" "$DS"

NL="Apache-2.0 (this project's restatement of the NeoWs objects as the MIT-licensed neows-ruby client models them)"
NS="neows-ruby (github.com/SpaceRocks/neows-ruby, commit b81655f31357b1d1700628085c041630111d0f06), lib/neows/models and spec/fixtures, restated in tools/gen/space/neows-1-objects.json"
NOTES=neows gen "$NW" NearEarthObject neows-neo neowsneo "NASA NeoWs v1, one near-Earth object (GET /neo/{id}; an item of browse and feed)" "$NL" "$NS"
NOTES=neows gen "$NW" Browse neows-browse neowsbrowse "NASA NeoWs v1, one page of the browse result (GET /neo/browse)" "$NL" "$NS"
NOTES=neows gen "$NW" Feed neows-feed neowsfeed "NASA NeoWs v1, the feed result (GET /feed)" "$NL" "$NS"
NOTES=neows gen "$NW" Stat neows-stats neowsstats "NASA NeoWs v1, the statistics result (GET /stats)" "$NL" "$NS"

exit "$STATUS"
