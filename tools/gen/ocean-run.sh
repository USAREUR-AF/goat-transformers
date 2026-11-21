#!/bin/bash
# Regenerate the ocean data JSON packs: ERDDAP tabledap rows (generic), IOOS glider DAC ERDDAP
# rows, and Argo float, platform and sensor metadata.
#
# Usage: tools/gen/ocean-run.sh [--check] <sources> <goat-transformers checkout>
#
# ERDDAP and the glider DAC publish no JSON Schema for their responses: this project restated the
# members it reads in its own files tools/gen/ocean/erddap-tabledap-objects.json (from ERDDAP's
# documentation; ERDDAP is CC0-1.0) and tools/gen/ocean/glider-dac-erddap-objects.json (from the
# NGDAC NetCDF template, ioos/ioosngdac commit f8d8204e219e27729b94b046a94d48e818dbc7b4,
# nc/template/IOOS_Glider_NetCDF_v3.0-noqartod.cdl, and the variable names the DAC ERDDAP server
# serves). The Argo metadata schemas are read from <sources>/argo-meta/, the files of
# euroargodev/sensor_metadata_json commit 9352eeb0f8351145eed1086b08972508b5ac775e, schemas/
# (EUPL-1.2), checked by SHA-256 below. Licence basis: each PROVENANCE.md.
#
# Writes model/<module>.def, packs/{erddap,glider-dac,argo}-*/ (pack.def, pack.md, vectors/gen-*),
# packs/geojson/vectors/gen-geojson-to-erddap-*.json and the names files. PROVENANCE.md is not
# generated. With --check nothing is written; every run is made and the exit status is 1 when
# any file differs.
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
  got="$(sha256sum "$SRC/$f" | cut -d' ' -f1)"
  [ "$got" = "$sha" ] || { echo "$f: sha256 $got, expected $sha" >&2; exit 1; }
done <<'SUMS'
95c9ac07e361422fdf734d1b736b873ea0316e3054733607fbe087c22d950d9f argo-meta/argo.float.schema.json
24da7fe5cab2ba6d1a6476414886a4bc6503d5c77eb2a51ad612719f045cf5fd argo-meta/argo.platform.schema.json
0bae29c37cb602d5fa4ee538d15a37e4ab181f3ffc401e7a6bc791c120835e80 argo-meta/argo.sensor.schema.json
1bff0ae58f8c82f9a7597369bbbd976319bbc598a8a981c0a97f351c67d41db7 argo-meta/argo.MRV.schema.json
54bc012aede66e0df62fcf32a9cdcc7a4b7ca1b74a7ec27d57792446ee601285 argo-meta/argo.RBR.schema.json
bad2fbb8d41a0b4b8cbf8f509bf0b4215dbc74799d4aab98cd35a3818fe79b60 argo-meta/argo.SBE.schema.json
36df4027e9164079a78277714052366830cdcc7c1d50d8c9c68ac8f4d9e7384d argo-meta/argo.TRIOS.schema.json
e8c41564cd60e865e4deb33f9c3ebee1e57c6022fd0890c596eb4f20e39fc9db argo-meta/argo.vendors.schema.json
SUMS
XG="$W/packs/geojson/pack.def=$W/packs/geojson/vectors/01-geojson-to-cot.json:input"
cd "$W"

# gen <format> <module> <title> <license> <source> [options...]
gen() {
  local fmt="$1" mod="$2" title="$3" lic="$4" src="$5"
  shift 5
  if ! python3 -I "$GEN/jsonschema2pack.py" --format "$fmt" --module "$mod" --title "$title" \
      --license "$lic" --source "$src" \
      --out "$W" --model-dir "$W/model" --names-file "$GEN/names/$fmt.json" --notes-file "$GEN/notes/$fmt.md" \
      "$@" ${CHECK:+"$CHECK"}; then
    STATUS=1
    [ -n "$CHECK" ] || exit 1
  fi
}

E="$GEN/ocean/erddap-tabledap-objects.json"
EL="Apache-2.0 (this project's restatement of ERDDAP's documented output formats; ERDDAP is CC0-1.0)"
ES="ERDDAP tabledap output formats (.geoJson, .jsonlKVP), https://erddap.github.io/docs, restated in tools/gen/ocean/erddap-tabledap-objects.json"
gen erddap-tabledap-geojson erddapgeo "ERDDAP tabledap .geoJson response, one Feature" "$EL" "$ES" \
  --schema "$E" --message "Feature=$E#/\$defs/GeoJsonFeature" --wire geojson --top-level-members id \
  --map Feature:geometry.lon=lon --map Feature:geometry.lat=lat \
  --map Feature:properties.time=time_ms \
  --evidence "Feature:properties.time=the row's time, which ERDDAP writes as an ISO 8601 date-time in UTC (its time variable, propertyUnits UTC)" \
  --cross "$XG"
gen erddap-tabledap-jsonlkvp erddapkvp "ERDDAP tabledap .jsonlKVP response, one line (one row)" "$EL" "$ES" \
  --schema "$E" --message "Row=$E#/\$defs/JsonlKvpRow" \
  --map Row:time=time_ms \
  --evidence "Row:time=the row's time, which ERDDAP writes as an ISO 8601 date-time in UTC (its time variable)"

G="$GEN/ocean/glider-dac-erddap-objects.json"
gen glider-dac-erddap gliderdac "IOOS National Glider DAC ERDDAP tabledap .jsonlKVP row" \
  "LicenseRef-unstated (the NGDAC template repository states no licence; PROVENANCE.md)" \
  "IOOS NGDAC NetCDF template v3 (ioos/ioosngdac commit f8d8204e219e27729b94b046a94d48e818dbc7b4) and the gliders.ioos.us ERDDAP variable names, restated in tools/gen/ocean/glider-dac-erddap-objects.json" \
  --schema "$G" --message "Row=$G#/\$defs/GliderRow" \
  --map Row:latitude=lat --map Row:longitude=lon --map Row:time=time_ms \
  --evidence "Row:latitude=the template's lat: degrees north, reference WGS84, coordinate reference frame EPSG 4326 (ERDDAP names it latitude)" \
  --evidence "Row:longitude=the template's lon: degrees east, reference WGS84, coordinate reference frame EPSG 4326 (ERDDAP names it longitude)" \
  --evidence "Row:time=the measurement time, which ERDDAP writes as an ISO 8601 date-time in UTC"

A="$SRC/argo-meta"
AF=("$A/argo.float.schema.json" "$A/argo.platform.schema.json" "$A/argo.sensor.schema.json" "$A/argo.MRV.schema.json"
  "$A/argo.RBR.schema.json" "$A/argo.SBE.schema.json" "$A/argo.TRIOS.schema.json" "$A/argo.vendors.schema.json")
# the files' relative $id values (./argo.platform.schema.json) name the files of this directory
AA=(--alias "argo.platform.schema.json=$A/argo.platform.schema.json" --alias "argo.sensor.schema.json=$A/argo.sensor.schema.json"
  --alias "argo.float.schema.json=$A/argo.float.schema.json" --alias "argo.vendors.schema.json=$A/argo.vendors.schema.json"
  --alias "argo.SBE.schema.json=$A/argo.SBE.schema.json" --alias "argo.RBR.schema.json=$A/argo.RBR.schema.json"
  --alias "argo.TRIOS.schema.json=$A/argo.TRIOS.schema.json" --alias "argo.MRV.schema.json=$A/argo.MRV.schema.json")
AL="Apache-2.0 (restated from the Euro-Argo sensor metadata JSON schemas, EUPL-1.2; PROVENANCE.md)"
AS="euroargodev/sensor_metadata_json commit 9352eeb0f8351145eed1086b08972508b5ac775e, schemas/"
gen argo-float-metadata argofloat "Argo float metadata JSON (argo.float.schema.json)" "$AL" "$AS" \
  --schema "${AF[@]}" "${AA[@]}" --message "Float=$A/argo.float.schema.json"
gen argo-platform-metadata argoplatform "Argo platform metadata JSON (argo.platform.schema.json)" "$AL" "$AS" \
  --schema "${AF[@]}" "${AA[@]}" --message "Platform=$A/argo.platform.schema.json"
gen argo-sensor-metadata argosensor "Argo sensor metadata JSON (argo.sensor.schema.json)" "$AL" "$AS" \
  --schema "${AF[@]}" "${AA[@]}" --message "Sensor=$A/argo.sensor.schema.json"

exit "$STATUS"
