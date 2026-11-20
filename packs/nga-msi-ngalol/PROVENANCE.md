# Provenance of the nga-msi-ngalol pack

SPDX licence: LicenseRef-NGA-MSI

`tools/gen/nga-msi-run.sh` fetches the archived responses below and checks their SHA-256; `tools/gen/nga-msi2pack.py` reads them. No response is kept in this repository and no record of them is copied: the vectors are records written for this repository. Read on 2026-11-20.

| | |
|---|---|
| Publisher | National Geospatial-Intelligence Agency (NGA), Maritime Safety Information, https://msi.nga.mil |
| Endpoint | `https://msi.nga.mil/api/publications/ngalol/lights-buoys` |
| Live API on 2026-11-20 | HTTP 503; no OpenAPI document reachable or archived |

| Archived response (Internet Archive) | SHA-256 of the body |
|---|---|
| `https://web.archive.org/web/20260914160540id_/https://msi.nga.mil/api/publications/ngalol/lights-buoys?volume=110&featureNumber=11636&includeRemovals=false&output=json` | `afff43b1ef950559a7b0b8645ec32fb932e2be6297da9982b9611d63afe0d1d9` |
| `https://web.archive.org/web/20260914160555id_/https://msi.nga.mil/api/publications/ngalol/lights-buoys?volume=110&featureNumber=11668&includeRemovals=false&output=json` | `a486fbd7ded63555c9999faa08b3e5765d12d9f9beb1ea74236e2ec72ecc3120` |
| `https://web.archive.org/web/20260914160623id_/https://msi.nga.mil/api/publications/ngalol/lights-buoys?volume=110&featureNumber=11672&includeRemovals=false&output=json` | `87553ba4d22ba5728606c528e4182e0549467f8370e9a8281ba992704f238387` |
| `https://web.archive.org/web/20260910224550id_/https://msi.nga.mil/api/publications/ngalol/lights-buoys?volume=114&featureNumber=1220&includeRemovals=false&output=html` | `546d0420aba6f89a589e421ccda7ecdf05da4c610a28bdc0339eec01433b0608` |

The SHA-256 is that of the response body after removing its gzip content encoding.

## Licence

NGA's page Commercial Use Warning (`https://msi.nga.mil/api/pageContent/getByTitle?pageTitle=Commercial%20Use%20Warning`, archived 2026-08-11) states that NGA claims no copyright or other intellectual property right in the nautical products posted on the site for public use. It prohibits using NGA's name, seal or initials to imply NGA approval, and requires a product that includes NGA's name or implies an association with NGA to carry a disclaimer, quoted in `LICENSES/LicenseRef-NGA-MSI.txt`.

The pack carries the licence `LicenseRef-NGA-MSI`, defined there. This pack is not approved, authorized or endorsed by NGA (see the disclaimer).

