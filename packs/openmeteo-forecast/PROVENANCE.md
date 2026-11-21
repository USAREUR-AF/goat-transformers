# Provenance of the openmeteo-forecast pack

SPDX licence: CC-BY-4.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/wxfc-run.sh`) generates this pack from this
project's restatement `tools/gen/wxfc/openmeteo-forecast-1.0-response.json` (SHA-256 `e65415128f675c64c87ddba011bc348acb2d55ad6385d2d0c37f3b04979dbdc1`) of the response of `GET /v1/forecast`. The
source is not kept in this repository. Read on 2026-11-21.

## Source

| | |
|---|---|
| Document | Open-Meteo Weather Forecast API, OpenAPI 3.1.0 document, `info.version` 1.0 |
| Repository | https://github.com/open-meteo/open-meteo, commit `7cc41ffa9a79c2e4c7ad4e18f13b51ab8df610aa`, archive SHA-256 `0c382215ffbc21c713af58498713870371ef674814cc27fbb5e2c81c59f214f7` |
| File read | `openapi/forecast.yml`, the schema of the 200 response of `GET /v1/forecast` |
| Response read | one forecast for one location, 2026-11-21, to check the shape; not kept, and no value of it is in a vector |

The restatement keeps member names, types and formats. Six time members typed as string or
integer (the request's `timeformat` chooses) are strings: `hourly.time`, `daily.time`,
`daily.sunrise`, `daily.sunset`, `current.time`, `minutely_15.time`.

## Licence

The document's `info.license` is "Attribution 4.0 International (CC BY 4.0)"
(https://creativecommons.org/licenses/by/4.0/). The repository that holds it is under the GNU
Affero General Public License, version 3 (`LICENSE`). This pack restates member names and types
only (no code, description or example is copied); it is labelled with the licence the document
states for itself, CC-BY-4.0 (`REUSE.toml` of this directory and `model/omfc.def.license`).
Credit: Open-Meteo (open-meteo.com).

No document read carries a handling marking, a distribution statement or an export-control
notice.
