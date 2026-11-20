# Provenance of the ogc-geopose-stream-element pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/ogc-geopose-run.sh`) reads the schema files that `pack.md`
lists with their SHA-256, and nothing else. The files are not kept in this repository. Read on
2026-11-20.

## Source

| | |
|---|---|
| Document | OGC GeoPose 1.0 Data Exchange Standard, JSON encodings |
| Publisher | Open Geospatial Consortium (OGC) |
| Repository | https://github.com/opengeospatial/GeoPose, default branch, commit `cc8a239c8f59bb4579e250a97a3512f8459e5113` |
| Files read | `standard/standard/schemata` (each file and its SHA-256 in `pack.md`) |
| Status | the schemata of the approved standard, at the repository head |
| License file | `LICENSE` at that commit, SHA-256 `b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1` |
| Evidence | the conformance clause, the conceptual model and the annex on time of the same commit (`standard/standard/clause_2_conformance.adoc`, `models/conceptual_model.adoc`, `annex-g-time.adoc`); stated in the project's words in `pack.md` |

## Licence

The licence is the Apache License, Version 2.0 ("Apache License / Version 2.0, January 2004 / http://www.apache.org/licenses/"). It allows use, modification and redistribution, with the licence and notices kept. The pack carries the project's Apache-2.0 label (REUSE.toml, the default annotation).

None of the schema files read is headed "All Rights Reserved". Copyright (C) Open Geospatial Consortium.
