# Provenance: rtz-route pack

SPDX licence: LicenseRef-unstated

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| CIRM, Route Exchange Format (RTZ) XML schema, revision 1.2 (the schema of IEC PAS 61174-1:2021) | https://cirm.org/storage/documents/October2022/bWjrTyyfNGseK9ch3TKf.xsd, linked as "RTZ_Schema_version_1_2.xsd" from https://cirm.org/rtz-xml-schemas | `ba5695107e2b559ea0594eb80f7407b7e4f1c10da8cf09b447b4b920f681ceff` |

## Licence

CIRM (Comité International Radio-Maritime) publishes the schema on its RTZ page, which says the schema
that RTZ route files must meet "is available below", with no registration. The schema file carries no
copyright notice and no licence; its header names its source as an IEC PAS. The page states no terms
for the files.

This project's standing decision is that a document that reserves its rights, or states none, without
limiting the purpose of use, is restated from its text. The pack restates the structure (element and
attribute names, nesting, types) in this project's own words; no annotation text of the schema is
copied, and the schema is not redistributed. Because no licence is stated the pack is labelled
`LicenseRef-unstated` (REUSE.toml in this directory; model/rtz.def.license for the module), which keeps
it out of the `open` profile; the choice is recorded for the operator, who can overturn it. IEC PAS
61174-1 itself: not read.

The vectors are built by `tools/gen/maritime-vectors.py` from values chosen there; their expected
output is derived there, without an engine.

## Attribution

From the Route Exchange Format (RTZ) XML schema, revision 1.2, published by CIRM at
https://cirm.org/rtz-xml-schemas (the schema of IEC PAS 61174-1:2021). No copyright notice or licence
stated; labelled LicenseRef-unstated. Structure restated, schema not redistributed.
