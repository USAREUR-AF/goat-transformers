# Provenance of the mds pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/jsonschema2pack-run.sh`, block
"MDS 2.0") reads the schema files of mds-openapi and nothing else; their SHA-256 are listed
in `pack.md`. The files are not kept in this repository. Read on 2026-11-19.

## Schema source

| | |
|---|---|
| Document | Mobility Data Specification (MDS) 2.0, OpenAPI description and data models |
| Publisher | Open Mobility Foundation |
| Repository | https://github.com/openmobilityfoundation/mds-openapi, branch `v2.0`, commit `0c07bc3d294237dd41c6273f059efb11b8149c66` |
| Files read | every `models/**/*.yaml` (68 files: JSON Schema in YAML) |
| License file | `LICENSE`, SHA-256 `419896aea50c15d6e40c5b4baf4bd346f78223b9a354c7357ad00262afdc08ec` |

License: the repository's `LICENSE` is the Creative Commons Attribution 4.0 International
Public License; it opens:

> Creative Commons Attribution 4.0 International Public License
>
> By exercising the Licensed Rights (defined below), You accept and agree to be bound by
> the terms and conditions of this Creative Commons Attribution 4.0 International Public
> License ("Public License").

Attribution: the pack is derived from the MDS data models of the Open Mobility
Foundation, licensed CC BY 4.0; the pack restates their structure and is not endorsed by
the Foundation. Changes: the models are reduced to the members a message carries, with
keys of this project's own naming.

## Evidence document (read, not used by the generator)

| | |
|---|---|
| Document | MDS 2.0.2, `general-information.md` (the statement on WGS 84 decimal degrees) |
| Repository | https://github.com/openmobilityfoundation/mobility-data-specification, tag `2.0.2`, commit `fb4d24e19066a41c091cea8d5a5f76a864263f69` |
| SHA-256 | `b022d93d301a971d47b3138819666232ea6085ed2bf949309a30bff90206c2e0` |
| License | CC BY 4.0 (the repository's `LICENSE`) |
