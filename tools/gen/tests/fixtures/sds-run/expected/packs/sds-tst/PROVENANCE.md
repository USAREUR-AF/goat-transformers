# Provenance of the sds-tst pack

`tools/gen/sds-run.sh` runs `tools/gen/jsonschema2pack.py` on the standard's
`main.fb.schema.json` and nothing else. The file is not kept in this repository.
Read on 2026-11-19.

| | |
|---|---|
| Document | Space Data Standards, standard `TST`, JSON Schema (draft 2019-09) |
| Publisher | Edgesource Corporation (spacedatastandards.org) |
| Repository | https://github.com/DigitalArsenal/spacedatastandards.org at commit `90783885e58c692ee7dae29188c41632cc9f5f04` |
| Download | `https://raw.githubusercontent.com/DigitalArsenal/spacedatastandards.org/90783885e58c692ee7dae29188c41632cc9f5f04/lib/fbjson/TST/main.fb.schema.json` |

| File | SHA-256 | Read by the generator |
|---|---|---|
| `lib/fbjson/TST/main.fb.schema.json` | `912c947fc10c5ac42177913bfdce04deb037d01ba13c45756576da2b934fa32f` | yes |
| `LICENSE` | `c32f106be593d41b6dee7e7d888006fbfff09d1ddb8cb2b5aa25a91513a05def` | no |
| `NOTICE` | `8d71b868af0a0e12b101b21979de9843019133bb366fc17ccecfb3ef6e1cae6f` | no |

## License

Apache-2.0. The repository's `README.md`, section License: "Copyright 2026 Edgesource Corporation. This project is licensed under the Apache License, Version 2.0." Its `NOTICE` begins: "Space Data Standards. Copyright 2026 Edgesource Corporation. Licensed under the Apache License 2.0." and states that every file of the repository is covered by the License except the third-party components it lists; `lib/fbjson/` is not among them. `LICENSE` is the text of the Apache License, Version 2.0, January 2004.

Attribution: the pack is derived from the Space Data Standards schema `TST`; it restates the schema's structure with keys of this project's naming and is not endorsed by the publisher.
