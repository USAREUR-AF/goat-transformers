# Provenance of the nws-cwa pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/nws-run.sh`) reads one file, the
OpenAPI document of the NWS weather API, and takes the schema `components.schemas.CenterWeatherAdvisoryGeoJson` and
the schemas it refers to. The file is not kept in this repository. Read on 2026-11-19.

## Source

| | |
|---|---|
| Document | weather.gov API, OpenAPI 3.1.2 document, `info.version` 3.12.2 |
| Publisher | National Weather Service (NOAA), United States |
| Address | https://api.weather.gov/openapi.json, served 2026-11-19 17:36 UTC; the document has no versioned address, so this copy is pinned |
| SHA-256 | `ae478b69cdac6449e3b834dca636300f830dde552ac6abc180b1d5e82e2f1d35` (122,897 bytes of JSON as served) |
| Schema | `components.schemas.CenterWeatherAdvisoryGeoJson` |

## License

The document is a work of the United States Government, which has no copyright protection
in the United States (17 U.S.C. 105). The National Weather Service states, on
https://www.weather.gov/disclaimer (read 2026-11-19, SHA-256 of the page as served
`c08c1597ebd52b31e3ba749f76d2217c290dcd16dc894cb4c109655566ecbbd1`):

> The information on National Weather Service (NWS) Web pages are in the public domain,
> unless specifically noted otherwise, and may be used without charge for any lawful
> purpose so long as you do not: 1) claim it is your own (e.g., by claiming copyright for
> NWS information -- see below), 2) use it in a manner that implies an endorsement or
> affiliation with NOAA/NWS, or 3) modify its content and then present it as official
> government material.

and

> The information on National Weather Service Web servers and Web sites is in the public
> domain, unless specifically annotated otherwise, and may be used freely by the public.

The OpenAPI document carries no other notice. This pack is not official NWS material and
implies no endorsement by NOAA or the NWS.
