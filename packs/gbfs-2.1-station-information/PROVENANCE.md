# Provenance of the gbfs-2.1-station-information pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/gbfs-run.sh`) reads one file and nothing
else. The file is not kept in this repository. Read on 2026-11-19.

| | |
|---|---|
| Document | General Bikeshare Feed Specification (GBFS) 2.1, JSON Schema of `station_information.json` |
| Publisher | MobilityData |
| Repository | https://github.com/MobilityData/gbfs-json-schema at commit `bae2d215bd21e546bc482df01f5bed1c8a9b74ab` |
| File | `v2.1/station_information.json`, SHA-256 `3983bd67fd94babfcff5a68ec6511f60a64f81806df0f4874a9361bc93aee5fe` |
| Download | `https://raw.githubusercontent.com/MobilityData/gbfs-json-schema/bae2d215bd21e546bc482df01f5bed1c8a9b74ab/v2.1/station_information.json` |

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
