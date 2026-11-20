# Provenance of the awc-metar pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/awc-run.sh`) reads one file, the
OpenAPI document of the aviationweather.gov Data API, and takes the schema at `/components/schemas/METARproperties`
and the schemas it refers to. The file is not kept in this repository. Read on 2026-11-20.

## Source

| | |
|---|---|
| Document | AviationWeather.gov API, OpenAPI 3.1.0 document, `info.version` v4.0 |
| Publisher | Aviation Weather Center, National Weather Service (NOAA), United States |
| Address | https://aviationweather.gov/data/schema/openapi.yaml, served 2026-11-20 02:49 UTC (Last-Modified 2026-11-19 19:45:47 GMT); the document has no versioned address, so this copy is pinned |
| SHA-256 | `51fe8bfd7fead5085aae9bba62aeaa0c287a836712b77f3c05f3915570465ec2` (93,112 bytes of YAML as served) |
| Schema | `/components/schemas/METARproperties` |
| API page | https://aviationweather.gov/data/api/ (the document's `termsOfService`) |

## License

The document is a work of the United States Government, which has no copyright protection
in the United States (17 U.S.C. 105). It carries no licence statement; its
`termsOfService` points to the API page, which sets request limits (rate, size, the use
of cache files) and states no licence or copyright. The site's Disclaimer link is the
National Weather Service disclaimer, https://www.weather.gov/disclaimer (read 2026-11-20,
SHA-256 of the page as served `c08c1597ebd52b31e3ba749f76d2217c290dcd16dc894cb4c109655566ecbbd1`), which states:

> The information on National Weather Service (NWS) Web pages are in the public domain,
> unless specifically noted otherwise, and may be used without charge for any lawful
> purpose so long as you do not: 1) claim it is your own (e.g., by claiming copyright for
> NWS information -- see below), 2) use it in a manner that implies an endorsement or
> affiliation with NOAA/NWS, or 3) modify its content and then present it as official
> government material.

This pack is not official NWS material and implies no endorsement by NOAA or the NWS.
