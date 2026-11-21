# Provenance of the astm-f3411-v19-isa pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/utm-run.sh`) generates this pack. Read
on 2026-11-20.

## Source of record

| | |
|---|---|
| Document | ASTM F3411-19 network Remote ID interface, as InterUSS restates it in Python |
| Repository | https://github.com/interuss/uas_standards, tag `v4.4.0`, commit `15c05ba878efe76b7d47225fc7d673a9effb70f7` |
| File | `src/uas_standards/astm/f3411/v19/api.py`, SHA-256 `baa31e8758fd49e15c8c1f871fdbc5231abb126ba2780bb213923808d8357774` |
| License file | `LICENSE.md`, SHA-256 `094bedda295c0702807d1027a00e1134f4cb71d523dc49f6d4b3caf589053068`: the Apache License, Version 2.0 |

The pack restates the object names, member names, JSON types and required members that
api.py states; no code and no description text is copied (the evidence of every binding in
`pack.md` is in the project's words). As other restatements of code sources, it carries the
project's licence, Apache-2.0 (the default annotation; no per-pack REUSE.toml).

## Cross-check only

| | |
|---|---|
| File | https://github.com/uastech/standards, commit `228b301be1f4466df9b014f20b515665861a8e67`, `remoteid/canonical.yaml`, SHA-256 `74f4107b93f77a805a59956e36778d68f6ab5a313a76289ff2b15c15cc8d5a2a` (submodule `interfaces/astm/f3411/v19` of interuss/uas_standards v4.4.0) |
| Licence | none stated: the repository has no licence file and the OpenAPI `info` names none |

The generator reads this OpenAPI file because api.py is Python, not a schema. Before the
packs were generated, `tools/gen/utm-crosscheck.py` compared every object schema of the file
with the class of the same name in api.py (members and their JSON kinds) and found them in
agreement.
The ASTM F3411 and F3548 standards (paid documents) were not used.
