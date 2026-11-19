# Provenance of the stac-item pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/jsonschema2pack-run.sh`, block
"STAC Item 1.1.0") reads the JSON Schema files of `item-spec/json-schema/` and nothing else;
their SHA-256 are listed in `pack.md`. The files are not kept in this repository. Read on
2026-11-19.

## Source

| | |
|---|---|
| Document | SpatioTemporal Asset Catalog (STAC) specification 1.1.0, Item JSON Schema |
| Publisher | the STAC project (radiantearth/stac-spec) |
| Repository | https://github.com/radiantearth/stac-spec, tag `v1.1.0`, commit `ec002bb93dbfa47976822def8f11b2861775b662` |
| Files read | `item-spec/json-schema/*.json` (9 files, JSON Schema draft-07) |
| Evidence | `item-spec/item-spec.md`, SHA-256 `4cb08832ae498be4dc4e838e15d06af5fa389744c7ebc6d499d925a7923f80bd` (geometry per RFC 7946 on WGS 84; `datetime` in UTC per RFC 3339) |
| License file | `LICENSE`, SHA-256 `b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1` |

License: the repository's `LICENSE` is the Apache License, Version 2.0 ("Apache License /
Version 2.0, January 2004 / http://www.apache.org/licenses/"). The GitHub repository
metadata names the same license (Apache-2.0).

The schemas refer to `https://geojson.org/schema/Feature.json` and `Geometry.json`; those
are not read: the geojson wire is the Feature structure (`--opaque`).
