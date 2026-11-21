# Provenance of the erddap-tabledap-geojson pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/ocean-run.sh`) generates this pack from
`tools/gen/ocean/erddap-tabledap-objects.json` (SHA-256 `0355647f32aaf81be1053c0508883299fa686810abe9888a9a0a17791d274acd`),
this project's restatement of the members it reads. Read on 2026-11-21.

## Source

| | |
|---|---|
| Document | ERDDAP tabledap output formats (.geoJson) and ERDDAP's rules for the variables longitude, latitude, altitude, depth and time |
| Publisher | the ERDDAP project (originally NOAA NMFS SWFSC Environmental Research Division) |
| Documentation | https://erddap.github.io/docs (server-admin datasets: names and units of longitude, latitude and time) |
| Software | https://github.com/ERDDAP/erddap, commit `af01c8425b9de015439b8725f6ffed7a6ac611e9`, `LICENSE`: CC0-1.0 |
| Observed | a response of the IOOS glider DAC ERDDAP server (gliders.ioos.us/erddap), which writes this form |

## Licence

ERDDAP is released under CC0-1.0. ERDDAP publishes no schema for its responses; the pack
restates the members of the documented output format in the project's own words and carries
the project's licence, Apache-2.0 (the default annotation).
