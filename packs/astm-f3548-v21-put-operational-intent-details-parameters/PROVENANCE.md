# Provenance of the astm-f3548-v21-put-operational-intent-details-parameters pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/utm-run.sh`) generates this pack. Read
on 2026-11-20.

## Source of record

| | |
|---|---|
| Document | ASTM F3548-21 UTM USS-DSS and USS-USS interface, as InterUSS restates it in Python |
| Repository | https://github.com/interuss/uas_standards, tag `v4.4.0`, commit `15c05ba878efe76b7d47225fc7d673a9effb70f7` |
| File | `src/uas_standards/astm/f3548/v21/api.py`, SHA-256 `541efac9f3440434c51a9fbb9f1ac283d9ee9c72df838edd99ccff805ca354ac` |
| License file | `LICENSE.md`, SHA-256 `094bedda295c0702807d1027a00e1134f4cb71d523dc49f6d4b3caf589053068`: the Apache License, Version 2.0 |

The pack restates the object names, member names, JSON types and required members that
api.py states; no code and no description text is copied (the evidence of every binding in
`pack.md` is in the project's words). As other restatements of code sources, it carries the
project's licence, Apache-2.0 (the default annotation; no per-pack REUSE.toml).

## Cross-check only

| | |
|---|---|
| File | https://github.com/interuss/astm-utm-protocol, commit `1d3d8fbe75414e23d7e19ce35955770bea5e413f`, `utm.yaml`, SHA-256 `63482b2a665ecd836b269028a13b19adfde7a5c32b01301c168d87ca3313dd15` (submodule `interfaces/astm/f3548/v21` of interuss/uas_standards v4.4.0) |
| Licence | none stated: the repository has no licence file and the OpenAPI `info` names none |

The generator reads this OpenAPI file because api.py is Python, not a schema. Before the
packs were generated, `tools/gen/utm-crosscheck.py` compared every object schema of the file
with the class of the same name in api.py (members and their JSON kinds) and found them in
agreement.
The ASTM F3411 and F3548 standards (paid documents) were not used.
