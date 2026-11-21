# Provenance of the astm-f3411-v22a-error-response pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/utm-run.sh`) generates this pack. Read
on 2026-11-20.

## Source of record

| | |
|---|---|
| Document | ASTM F3411-22a network Remote ID interface, as InterUSS restates it in Python |
| Repository | https://github.com/interuss/uas_standards, tag `v4.4.0`, commit `15c05ba878efe76b7d47225fc7d673a9effb70f7` |
| File | `src/uas_standards/astm/f3411/v22a/api.py`, SHA-256 `138541ba2f797c78985bfa2136cdfa6cd511a6f071d9ecd8871636084e5805ed` |
| License file | `LICENSE.md`, SHA-256 `094bedda295c0702807d1027a00e1134f4cb71d523dc49f6d4b3caf589053068`: the Apache License, Version 2.0 |

The pack restates the object names, member names, JSON types and required members that
api.py states; no code and no description text is copied (the evidence of every binding in
`pack.md` is in the project's words). As other restatements of code sources, it carries the
project's licence, Apache-2.0 (the default annotation; no per-pack REUSE.toml).

## Cross-check only

| | |
|---|---|
| File | https://github.com/uastech/standards, commit `dd4016b09fc8cb98f30c2a17b5a088fb2995ab54`, `remoteid/canonical.yaml`, SHA-256 `0d37e6911befa23e187f3a0a7b986509f38b0a01db7619f6c2631abd0da0df38` (submodule `interfaces/astm/f3411/v22a` of interuss/uas_standards v4.4.0) |
| Licence | none stated: the repository has no licence file and the OpenAPI `info` names none |

The generator reads this OpenAPI file because api.py is Python, not a schema. Before the
packs were generated, `tools/gen/utm-crosscheck.py` compared every object schema of the file
with the class of the same name in api.py (members and their JSON kinds) and found them in
agreement.
The ASTM F3411 and F3548 standards (paid documents) were not used.
