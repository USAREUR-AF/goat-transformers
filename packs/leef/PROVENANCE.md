# Provenance of the leef pack

The pack and the module `leef` are written by hand from IBM's documentation of the LEEF event
components; the vectors by `tools/gen/logs-vectors.py` from records written for them. No part of
the documentation is kept in this repository. Read on 2026-11-20.

| Fact | Value |
|---|---|
| document | IBM QRadar DSM documentation, "LEEF event components" |
| address | https://www.ibm.com/docs/en/dsm?topic=overview-leef-event-components |
| read | 2026-11-20, as rendered by a browser; the site refuses automated downloads, so no SHA-256 of the page is recorded |
| what was read | the LEEF 1.0 and 2.0 header fields, the pipe separator, the tab as the default attribute delimiter, and how LEEF 2.0 names another delimiter |

## Licence: `LicenseRef-unstated`

The page states no licence for the format and no terms for implementing it; IBM's general
terms of use for its web site govern the site, not the format. No licence is granted or implied
by this repository for the documentation (LICENSES/LicenseRef-unstated.txt). The pack restates
the header's field order in this repository's words.
