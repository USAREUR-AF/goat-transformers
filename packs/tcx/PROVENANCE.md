# Provenance of the tcx pack

The pack and the module `tcx` are written by hand from the Garmin Training Center Database XML
schema, version 2; the vectors by `tools/gen/lwm2m-tcx-vectors.py` from documents written for
them. No source file is kept in this repository. Read on 2026-11-20.

## Source

| Fact | Value |
|---|---|
| schema | Garmin Training Center Database, version 2 |
| address | https://www8.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd |
| SHA-256 of the file as served | `ec392e16a33756df03d3e16fc12fd39f55601ec9e4e22cebb83243a8deb5a0dd` |
| namespace | `http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2` |

## Licence: `LicenseRef-unstated`

The schema file states no licence and no copyright: its only documentation says what the
schema defines. It is served without a licence file beside it. No licence is granted or
implied by this repository for the schema (LICENSES/LicenseRef-unstated.txt); the pack restates
element names, their nesting and their types in this repository's words. The commercial use of
the pack is unknown until Garmin states terms, so it is outside the `open` profile.
