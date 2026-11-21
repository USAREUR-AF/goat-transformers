# Provenance of the ea-flood-readings pack

The pack and the module `eaflood` (shared by `ea-flood-station`, `ea-flood-readings` and
`ea-flood-warnings`) are written by hand from the API reference; the vectors by
`tools/gen/hydro-vectors.py` from responses written for them. No source file is kept in this
repository. Read on 2026-11-21.

| Document | Address | SHA-256 |
|---|---|---|
| Real Time flood-monitoring API reference | https://environment.data.gov.uk/flood-monitoring/doc/reference | `87b7156f3fea64b54b92473cc67f62227b9fb4bf678bd76761c4a907a5b07b92` |

## Licence: OGL-UK-3.0

The reference states that the APIs are provided as open data under the Open Government Licence
with no requirement for registration, and every response names
`http://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/` as its licence. It
asks users to acknowledge the source with this attribution statement:

> this uses Environment Agency flood and river level data from the real-time data API (Beta)

The pack restates the members in this repository's words.
