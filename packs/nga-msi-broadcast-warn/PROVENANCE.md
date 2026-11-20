# Provenance of the nga-msi-broadcast-warn pack

SPDX licence: LicenseRef-NGA-MSI

`tools/gen/nga-msi-run.sh` fetches the archived responses below and checks their SHA-256; `tools/gen/nga-msi2pack.py` reads them. No response is kept in this repository and no record of them is copied: the vectors are records written for this repository. Read on 2026-11-20.

| | |
|---|---|
| Publisher | National Geospatial-Intelligence Agency (NGA), Maritime Safety Information, https://msi.nga.mil |
| Endpoint | `https://msi.nga.mil/api/publications/broadcast-warn` |
| Live API on 2026-11-20 | HTTP 503; no OpenAPI document reachable or archived |

| Archived response (Internet Archive) | SHA-256 of the body |
|---|---|
| `https://web.archive.org/web/20261022102238id_/https://msi.nga.mil/api/publications/broadcast-warn?output=json&navArea=P&msgYear=2023&msgNumber=1779&status=all` | `2e6dfbd0c5b80ec9239f0417a2c28ee120aad00beacee8a2806d0ec6f34ce249` |

The SHA-256 is that of the response body after removing its gzip content encoding.

## Licence

NGA's page Commercial Use Warning (`https://msi.nga.mil/api/pageContent/getByTitle?pageTitle=Commercial%20Use%20Warning`, archived 2026-08-11) states that NGA claims no copyright or other intellectual property right in the nautical products posted on the site for public use. It prohibits using NGA's name, seal or initials to imply NGA approval, and requires a product that includes NGA's name or implies an association with NGA to carry a disclaimer, quoted in `LICENSES/LicenseRef-NGA-MSI.txt`.

The pack carries the licence `LicenseRef-NGA-MSI`, defined there. This pack is not approved, authorized or endorsed by NGA (see the disclaimer).

