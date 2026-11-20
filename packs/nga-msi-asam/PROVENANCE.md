# Provenance of the nga-msi-asam pack

SPDX licence: LicenseRef-NGA-MSI

`tools/gen/nga-msi-run.sh` fetches the archived responses below and checks their SHA-256; `tools/gen/nga-msi2pack.py` reads them. No response is kept in this repository and no record of them is copied: the vectors are records written for this repository. Read on 2026-11-20.

| | |
|---|---|
| Publisher | National Geospatial-Intelligence Agency (NGA), Maritime Safety Information, https://msi.nga.mil |
| Endpoint | `https://msi.nga.mil/api/publications/asam` |
| Live API on 2026-11-20 | HTTP 503; no OpenAPI document reachable or archived |

| Archived response (Internet Archive) | SHA-256 of the body |
|---|---|
| `https://web.archive.org/web/20230927174507id_/https://msi.nga.mil/api/publications/asam?filter=none&sort=date&output=html` | `6e9e6c4242411d3ed4f40c6a50c63da5225d0321234a912e07be3491f63c1868` |

The SHA-256 is that of the response body after removing its gzip content encoding.

## Licence

NGA's page Commercial Use Warning (`https://msi.nga.mil/api/pageContent/getByTitle?pageTitle=Commercial%20Use%20Warning`, archived 2026-08-11) states that NGA claims no copyright or other intellectual property right in the nautical products posted on the site for public use. It prohibits using NGA's name, seal or initials to imply NGA approval, and requires a product that includes NGA's name or implies an association with NGA to carry a disclaimer, quoted in `LICENSES/LicenseRef-NGA-MSI.txt`.

The pack carries the licence `LicenseRef-NGA-MSI`, defined there. This pack is not approved, authorized or endorsed by NGA (see the disclaimer).

