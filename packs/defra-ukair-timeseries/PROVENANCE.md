# Provenance of the defra-ukair-timeseries pack

The pack and the module `defraukair` (shared by `defra-ukair-timeseries` and `defra-ukair-data`)
are written by hand from the UK-AIR SOS pages, the service's responses and the 52°North
Timeseries API server that the service runs; the vectors by `tools/gen/airq-vectors.py` from
responses written for them. No source file is kept in this repository. Read on 2026-11-21.

| Document | Address | Version | SHA-256 |
|---|---|---|---|
| UK-AIR Sensor Observation Service page | https://uk-air.defra.gov.uk/data/about_sos | as served 2026-11-21 | `fa3d883754c17509f10239efc00f06353a8e5226f5708d9c54ec9708d62adc26` |
| UK-AIR terms and conditions | https://uk-air.defra.gov.uk/about-these-pages | as served 2026-11-21 | `8dab9a0733ec2376ffc25004b16836d18d6dfdf91342e755381fb18a805defe9` |
| Example SOS queries (Defra) | linked from the SOS page | v1.3 | `36eafe2e1d7ae485bff57e9106a3f6bd139e1a0dafdcca1dafe4834258600ac1` |
| REST API responses | https://uk-air.defra.gov.uk/sos-ukair/api/v1/timeseries/{id} and `/getData` | API v1 | (live responses; shape only) |
| 52North/sensorweb-server-helgoland | https://github.com/52North/sensorweb-server-helgoland | commit `2298d1c75a0805493cd55214e63e1bdc3b85029d` | `TimeOutputConverter.java` `8d54f3458f008b9c455bf0b6a4f5e818dccbd3e48dca282f0348fc27bb89ae0d` |

## Licence: OGL-UK-3.0

The UK-AIR terms state that information on uk-air.defra.gov.uk is published by Defra and the
Devolved Governments under the Open Government Licence, except where otherwise noted, and every
page states:

> All content is available under the Open Government Licence v3.0, except where otherwise stated.

The terms ask for this attribution statement:

> © Crown 2026 copyright Defra via uk-air.defra.gov.uk, licenced under the Open Government Licence (OGL).

The API's own `extras/license` answer is a placeholder address, not a licence; the site's
statement is the one relied on. The server code (helgoland, GPL-2.0) was read only to confirm the
member names and the time form; no code or comment is copied, and the pack restates the members
in this repository's words.
