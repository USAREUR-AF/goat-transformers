#!/bin/bash
# Regenerate the wcmp2-record pack (WMO Core Metadata Profile 2) and the BUFR sequence packs
# (bufr4-synop-307080, bufr4-temp-309052, bufr4-ship-308009, bufr4-buoy-315009).
# Usage: tools/gen/wmo-sequences-run.sh [--check] <sources> <goat-transformers checkout>
#
# <sources> holds two git checkouts at the commits below (the script checks):
#   wcmp2  https://github.com/wmo-im/wcmp2  commit f05037aa8d8bf5911a44a511b7b99a0be009c9ab
#          (Copyright (c) 2024-2026 World Meteorological Organization; no licence stated)
#          schemas/wcmp2-bundled.json sha256 c798c04c1a10fe2eb619623c59efdd8159e9444c46a91865e089dd33514b41cb
#   BUFR4  https://github.com/wmo-im/BUFR4  commit 6a993796bf2661deb9cfe4da25435d5870566b20 (MIT):
#          Table B and Table D CSV, for the BUFR sequence packs
#
# Writes model/wcmp2.def, packs/wcmp2-record/ (pack.def, pack.md, vectors/gen-*),
# tools/gen/names/wcmp2-record.json, and the BUFR sequence packs and modules below. PROVENANCE.md and REUSE.toml are not generated.
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
got="$(git -C "$SRC/wcmp2" rev-parse HEAD)"
[ "$got" = "f05037aa8d8bf5911a44a511b7b99a0be009c9ab" ] || { echo "wcmp2 is at $got" >&2; exit 1; }
got="$(git -C "$SRC/BUFR4" rev-parse HEAD)"
[ "$got" = "6a993796bf2661deb9cfe4da25435d5870566b20" ] || { echo "BUFR4 is at $got" >&2; exit 1; }
C="$SRC/wcmp2/schemas"
cd "$W"
python3 -I "$GEN/jsonschema2pack.py" ${CHECK:+"$CHECK"} \
  --schema "$C/wcmp2-bundled.json" --message Record="$C/wcmp2-bundled.json" \
  --wire geojson --format wcmp2-record --module wcmp2 \
  --title "WMO Core Metadata Profile 2 (WCMP2) 2.3.0 JSON Schema" \
  --license "LicenseRef-unstated, Copyright (c) 2024-2026 World Meteorological Organization (WMO)" \
  --source "https://github.com/wmo-im/wcmp2 at commit f05037aa8d8bf5911a44a511b7b99a0be009c9ab" \
  --out "$W" --model-dir "$W/model" --names-file "$GEN/names/wcmp2-record.json" --notes-file "$GEN/notes/wcmp2-record.md"
# BUFR surface synoptic report, Table D 3 07 080. The raw values pin the station's identity,
# position and time in the first vector (WMO 06631, 46.99083 N 7.46417 E, 553 m, 2026-11-20 06:00).
python3 -I "$GEN/bufr-sequence2pack.py" ${CHECK:+"$CHECK"} --out "$W" \
  --tables "$SRC/BUFR4" --commit 6a993796bf2661deb9cfe4da25435d5870566b20 \
  --sequence 307080 --format bufr4-synop-307080 --module bufrsynop \
  --values '{"wmo_block_number":6,"wmo_station_number":631,"station_or_site_name":"BERN-ZOLLIKOFEN","type_of_station":1,"year_2":2026,"month_2":11,"day_2":20,"hour_2":6,"minute_2":0,"latitude":13699083,"longitude":18746417,"height_of_station_ground_above_mean_sea":9530}'
# BUFR upper-air report (TEMP), Table D 3 09 052: WMO 06610, 46.81306 N 6.94250 E, 491 m, 2026-11-20 05:00:00.
python3 -I "$GEN/bufr-sequence2pack.py" ${CHECK:+"$CHECK"} --out "$W" \
  --tables "$SRC/BUFR4" --commit 6a993796bf2661deb9cfe4da25435d5870566b20 \
  --sequence 309052 --format bufr4-temp-309052 --module bufrtemp \
  --values '{"wmo_block_number":6,"wmo_station_number":610,"ship_or_mobile_land_station_identifier":"","year_2":2026,"month_2":11,"day_2":20,"hour_2":5,"minute_2":0,"second_2":0,"latitude":13681306,"longitude":18694250,"height_of_station_ground_above_mean_sea":8910}'
# BUFR ship report, Table D 3 08 009 (coarse latitude and longitude, 0.01 degree): 54.50 N 10.25 E, 2026-11-20 06:00.
python3 -I "$GEN/bufr-sequence2pack.py" ${CHECK:+"$CHECK"} --out "$W" \
  --tables "$SRC/BUFR4" --commit 6a993796bf2661deb9cfe4da25435d5870566b20 \
  --sequence 308009 --format bufr4-ship-308009 --module bufrship \
  --values '{"ship_or_mobile_land_station_identifier":"SHIP1","year_2":2026,"month_2":11,"day_2":20,"hour_2":6,"minute_2":0,"latitude":14450,"longitude":19025}'
# BUFR drifting buoy report, Table D 3 15 009 (with the 2 08 016 operator): 10.50000 S 30.25000 W, 2026-11-20 06:00.
python3 -I "$GEN/bufr-sequence2pack.py" ${CHECK:+"$CHECK"} --out "$W" \
  --tables "$SRC/BUFR4" --commit 6a993796bf2661deb9cfe4da25435d5870566b20 \
  --sequence 315009 --format bufr4-buoy-315009 --module bufrbuoy \
  --values '{"wmo_marine_observing_platform_extended_i":6203456,"long_station_or_site_name":"TEST BUOY","platform_transmitter_id_number":"300234011234560","year_2":2026,"month_2":11,"day_2":20,"hour_2":6,"minute_2":0,"latitude":7950000,"longitude":14975000}'
