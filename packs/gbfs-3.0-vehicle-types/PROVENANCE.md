# Provenance of the gbfs-3.0-vehicle-types pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/gbfs-run.sh`) reads one file and nothing
else. The file is not kept in this repository. Read on 2026-11-19.

| | |
|---|---|
| Document | General Bikeshare Feed Specification (GBFS) 3.0, JSON Schema of `vehicle_types.json` |
| Publisher | MobilityData |
| Repository | https://github.com/MobilityData/gbfs-json-schema at commit `bae2d215bd21e546bc482df01f5bed1c8a9b74ab` |
| File | `v3.0/vehicle_types.json`, SHA-256 `8135804aeaa0b4116d3fbd2feefb8bd1a7472104091273baeed91a5887f831b5` |
| Download | `https://raw.githubusercontent.com/MobilityData/gbfs-json-schema/bae2d215bd21e546bc482df01f5bed1c8a9b74ab/v3.0/vehicle_types.json` |

## License

The schema repository's `LICENSE` (SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`) is the Apache License, Version 2.0; it
opens:

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

The specification the schemas describe, https://github.com/MobilityData/gbfs (read at commit
`439ba1e6ddd476c003a9d787bd7ab3869a989ca6`, `gbfs.md`), is licensed under its `LICENSE` (SHA-256 `e6bc9e9c474700b708f568bac9e5a8a9bcb2b1dad53442f5ba449fcb848b8e76`):

> Creative Commons Legal Code
>
> Attribution 3.0 Unported

The pack restates the schema's structure (member names, types, nesting) with keys of this
project's naming; it takes no text of the specification. It is not endorsed by MobilityData.
