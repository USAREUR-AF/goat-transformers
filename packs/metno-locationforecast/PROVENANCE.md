# Provenance of the metno-locationforecast pack

SPDX licence: CC-BY-4.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/wxfc-run.sh`) reads one file, the Swagger
document of Locationforecast 2.0, and takes `definitions.METJSONForecast` and the definitions it
refers to. The file is not kept in this repository. Read on 2026-11-21.

## Source

| | |
|---|---|
| Document | Locationforecast 2.0, Swagger 2.0 document, `info.version` 2.0 |
| Publisher | The Norwegian Meteorological Institute (MET Norway) |
| Address | https://api.met.no/weatherapi/locationforecast/2.0/swagger, served 2026-11-21; the document has no versioned address, so this copy is pinned |
| SHA-256 | `c0c32a5bcff572ec98789173eb9fb0ecf4526763a6d49a341f20c65f571e2550` (18,341 bytes of JSON as served) |
| Schema | `definitions.METJSONForecast` |
| Responses read | `/compact` and `/complete` for one location, 2026-11-21, to check the shape; not kept, and no value of them is in a vector |

## Licence

The document's `info.license` names "CC BY 4.0" (http://creativecommons.org/licenses/by/4.0).
MET Norway's licence page (https://api.met.no/doc/License, read 2026-11-21) states:

> Unless specified otherwise, all data and products are licensed under the Norwegian Licence
> for Open Government Data (NLOD) 2.0 and Creative Commons 4.0 BY International licences.
> Credit should be given to The Norwegian Meteorological Institute, shortened MET Norway, as
> the source of data.

This pack restates the member names and types of the document; it is labelled CC-BY-4.0
(`REUSE.toml` of this directory and `model/metnolf.def.license`), with the credit to MET
Norway given here, in the `source` lines and in the notice entry.

No document read carries a handling marking, a distribution statement or an export-control
notice.
