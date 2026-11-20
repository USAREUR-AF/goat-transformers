SPDX licence: LicenseRef-unstated

# Provenance of the ocpp16-reserve-now pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/ocpp-run.sh`) reads the files below. They are not kept in this repository. Read on 2026-11-20.

## Source

| | |
|---|---|
| Publisher | Open Charge Alliance (schemas); The Mobility House (the library that carries the copies) |
| Address | https://github.com/mobilityhouse/ocpp |
| Version | tag 2.1.0, commit 91f4f89140a2198dc5a300cfea88d947ac91ae28 |
| Files | under `ocpp/v16/schemas/` (OCPP 1.6) or `ocpp/v201/schemas/` (OCPP 2.0.1) of the repository |

| File | Bytes | SHA-256 |
|---|---|---|
| `ReserveNow.json` | 704 | `aa7c353475e9673b495855dd7a71b9a64df23352f4aeb8668e948d50f68cb6c4` |

## Licence

No licence was found for the schemas. The schema files carry no licence or copyright
notice (the 2.0.1 files have a comment naming the version only). The library's `LICENSE`
is the MIT License with the copyright of The Mobility House; it covers the library, and
the schemas in it are the Open Charge Alliance's. The Alliance publishes the schemas with
the OCPP specification at no charge after an account registration
(https://openchargealliance.org/download-ocpp/, read 2026-11-20); the terms attached at
that download were not read, since the download needs an account.

Looked in: the schema files, the library's LICENSE and README, the Alliance's download
page. `LicenseRef-unstated` (LICENSES/LicenseRef-unstated.txt): commercial use is unknown until the owner states terms.
