# Provenance of the nga-msi-wpi pack

SPDX licence: LicenseRef-NGA-MSI

`tools/gen/nga-msi-run.sh` fetches the archived responses below and checks their SHA-256; `tools/gen/nga-msi2pack.py` reads them. No response is kept in this repository and no record of them is copied: the vectors are records written for this repository. Read on 2026-11-20.

| | |
|---|---|
| Publisher | National Geospatial-Intelligence Agency (NGA), Maritime Safety Information, https://msi.nga.mil |
| Endpoint | `https://msi.nga.mil/api/publications/world-port-index` |
| Live API on 2026-11-20 | HTTP 503; no OpenAPI document reachable or archived |

| Archived response (Internet Archive) | SHA-256 of the body |
|---|---|
| `https://web.archive.org/web/20250222063435id_/https://msi.nga.mil/api/publications/world-port-index?indexNumber=12370&output=json` | `676d0d7ac80c33a302a96d87293b1389ad37c6c97c30f3b850092b5d61cd9736` |
| `https://web.archive.org/web/20260124043107id_/https://msi.nga.mil/api/publications/world-port-index?countryName=Costa%20Rica&output=html` | `6f42f6db08175cf8ce046ff3ef8c46144d495288dc203a8901206cf6f076928f` |
| `https://web.archive.org/web/20260124043522id_/https://msi.nga.mil/api/publications/world-port-index?countryName=Venezuela&output=html` | `1b820bc8faace47fcede3d125e57b618eff5d80c3ab3b91b11496058945bd749` |

The SHA-256 is that of the response body after removing its gzip content encoding.

## Licence

NGA's page Commercial Use Warning (`https://msi.nga.mil/api/pageContent/getByTitle?pageTitle=Commercial%20Use%20Warning`, archived 2026-08-11) states that NGA claims no copyright or other intellectual property right in the nautical products posted on the site for public use. It prohibits using NGA's name, seal or initials to imply NGA approval, and requires a product that includes NGA's name or implies an association with NGA to carry a disclaimer, quoted in `LICENSES/LicenseRef-NGA-MSI.txt`.

The pack carries the licence `LicenseRef-NGA-MSI`, defined there. This pack is not approved, authorized or endorsed by NGA (see the disclaimer).

