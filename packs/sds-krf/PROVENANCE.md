# Provenance of the sds-krf pack

`tools/gen/sds-run.sh` runs `tools/gen/jsonschema2pack.py` on the standard's
`main.fb.schema.json` and nothing else. The file is not kept in this repository.
Read on 2026-11-19.

| | |
|---|---|
| Document | Space Data Standards, standard `KRF`, JSON Schema (draft 2019-09) |
| Publisher | Edgesource Corporation (spacedatastandards.org) |
| Repository | https://github.com/DigitalArsenal/spacedatastandards.org at commit `0a61c131bc8a849360a0bba57855cc6dd8dde70a` |
| Download | `https://raw.githubusercontent.com/DigitalArsenal/spacedatastandards.org/0a61c131bc8a849360a0bba57855cc6dd8dde70a/lib/fbjson/KRF/main.fb.schema.json` |

| File | SHA-256 | Read by the generator |
|---|---|---|
| `lib/fbjson/KRF/main.fb.schema.json` | `e4d27aa263399595c36087e2cc2dd51d0ea89b1e1d64a2eec0c0d9f2fe597308` | yes |
| `LICENSE` | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` | no |
| `NOTICE` | `2de8b5a632486b70ee1cdbaa05803b67b1dec872ec5ebf1651b543f9c9c779e0` | no |

## License

Apache-2.0. The repository's `README.md`, section License: "Copyright 2026 Edgesource Corporation. This project is licensed under the Apache License, Version 2.0." Its `NOTICE` begins: "Space Data Standards. Copyright 2026 Edgesource Corporation. Licensed under the Apache License 2.0." and states that every file of the repository is covered by the License except the third-party components it lists; `lib/fbjson/` is not among them. `LICENSE` is the text of the Apache License, Version 2.0, January 2004.

Attribution: the pack is derived from the Space Data Standards schema `KRF`; it restates the schema's structure with keys of this project's naming and is not endorsed by the publisher.
