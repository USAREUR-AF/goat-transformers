SPDX licence: LicenseRef-OpenAQ

# Provenance of the openaq-parameters pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/openaq-run.sh`) reads the files below. They are not kept in this repository. Read on 2026-11-20.

## Source

| | |
|---|---|
| Publisher | OpenAQ |
| Address | https://api.openaq.org/openapi.json, served 2026-11-20; the document has no versioned address, so this copy is pinned by its SHA-256 |
| Version | OpenAPI 3.1.0, `info.version` 3.0.0 |
| Files | under the API's address |

| File | Bytes | SHA-256 |
|---|---|---|
| `openapi-2026-11-20.json` | 91364 | `05873df4fed8e82789aeb14369368950570bb83ffd5f1f9ac1b700328a942b7e` |

## Licence

The OpenAPI document states no licence. The OpenAQ terms of use,
https://docs.openaq.org/about/terms (read 2026-11-20), govern the API; the parts that bear
on this pack are quoted in LICENSES/LicenseRef-OpenAQ.txt. In short, quoted:

> Attribution to OpenAQ as the source data is also required when using OpenAQ
> services for accessing the data.

and the terms prohibit using the hosted API to build products or services that
substantially duplicate or directly compete with OpenAQ's core offerings. The pack holds
no OpenAQ data; its vectors are values written for them.
