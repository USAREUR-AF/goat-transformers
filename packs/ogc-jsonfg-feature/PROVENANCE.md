# Provenance of the ogc-jsonfg-feature pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/ogc-jsonfg-run.sh`) reads the schema files that `pack.md`
lists with their SHA-256, and nothing else. The files are not kept in this repository. Read on
2026-11-20.

## Source

| | |
|---|---|
| Document | OGC Features and Geometries JSON (JSON-FG) 1.0.0 |
| Publisher | Open Geospatial Consortium (OGC) |
| Repository | https://github.com/opengeospatial/ogc-feat-geo-json, tag `v1.0.0`, commit `2572fda3ddfd83a55e4c2a04c2e9e4c5daa6c20d` |
| Files read | `core/schemas (posted at https://schemas.opengis.net/json-fg/)` (each file and its SHA-256 in `pack.md`) |
| Status | approved OGC standard, release tag |
| License file | `LICENSE` at that commit, SHA-256 `b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1` |
| Evidence | the core requirements and terms of the same tag (`core/clause_4_terms_and_definitions.adoc`, `core/clause_8_core.adoc`); stated in the project's words in `pack.md` |

## Licence

The licence is the Apache License, Version 2.0 ("Apache License / Version 2.0, January 2004 / http://www.apache.org/licenses/"). It allows use, modification and redistribution, with the licence and notices kept. The pack carries the project's Apache-2.0 label (REUSE.toml, the default annotation).

None of the schema files read is headed "All Rights Reserved". core/schemas/README.md carries "Copyright (c) 2026 Open Geospatial Consortium"; that notice is kept here.
