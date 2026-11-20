# Provenance of the ogc-routes-waypoint pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/ogc-routes-run.sh`) reads the schema files that `pack.md`
lists with their SHA-256, and nothing else. The files are not kept in this repository. Read on
2026-11-20.

## Source

| | |
|---|---|
| Document | OGC API - Routes, Route Exchange Model (REM) |
| Publisher | Open Geospatial Consortium (OGC) |
| Repository | https://github.com/opengeospatial/ogcapi-routes, default branch (only tag `v1.0.0-draft.1` is older), commit `c9b74b570326b83ec608f977aa381ccfe9d4cfa8` |
| Files read | `rem/standard/code/rem-json-schema.json` (each file and its SHA-256 in `pack.md`) |
| Status | draft |
| License file | `rem/LICENSE` at that commit, SHA-256 `b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1` |
| Evidence | the REM clause of the same commit (`rem/standard/clause_7_rem.adoc`); stated in the project's words in `pack.md` |

## Licence

The licence of the `rem/` directory (its own `LICENSE`; the repository root carries the OGC Software License) is the Apache License, Version 2.0 ("Apache License / Version 2.0, January 2004 / http://www.apache.org/licenses/"). It allows use, modification and redistribution, with the licence and notices kept. The pack carries the project's Apache-2.0 label (REUSE.toml, the default annotation).

None of the schema files read is headed "All Rights Reserved". Copyright (C) Open Geospatial Consortium.
