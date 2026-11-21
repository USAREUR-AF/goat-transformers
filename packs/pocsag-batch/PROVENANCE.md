# Provenance: pocsag-batch pack

SPDX licence: LicenseRef-unstated

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| Recommendation ITU-R M.584-2 (11/1997), Codes and formats for radio paging, Annex 1 | https://www.itu.int/dms_pubrec/itu-r/rec/m/R-REC-M.584-2-199711-I!!PDF-E.pdf | `3f9fb2fd0324ec9ecb37a4645ee24fc75d7d61424dbd6a8826df415bad955301` |

## Licence

The ITU provides free online access to all current ITU-R Recommendations to the general public (its
R-REC publications page). This 1997 PDF carries no copyright notice or licence in its text. The
Recommendation is the ITU's; its Annex 1 describes the code that is commonly called POCSAG.

This project's standing decision is that a document that reserves its rights, or states none, without
limiting the purpose of use, is restated from its text. Because no licence is stated the pack is labelled
`LicenseRef-unstated` (REUSE.toml in this directory; model/pocsag.def.license for the module), which keeps it
out of the `open` profile; the choice is recorded for the operator, who can overturn it.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure or table
of the source is copied. The vectors are frames built by `tools/gen/radio-vectors.py` from values
chosen there; their expected bytes are derived there, without an engine.
