# Provenance: kiss-frame pack

SPDX licence: LicenseRef-unstated

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| M. Chepponis (K3MC) and P. Karn (KA9Q), The KISS TNC: A simple Host-to-TNC communications protocol, ARRL 6th Computer Networking Conference, 1987; HTML by KA9Q, January 1997 | http://www.ka9q.net/papers/kiss.html | `a6a1627dbf1e64539a287d7cdb59dc3de618d15653e2df7fac2279ef1decd8ab` |

## Licence

The page, published by one of its authors, carries no copyright notice and states no licence or terms.

This project's standing decision is that a document that reserves its rights, or states none, without
limiting the purpose of use, is restated from its text. Because no licence is stated the pack is labelled
`LicenseRef-unstated` (REUSE.toml in this directory; model/kiss.def.license for the module), which keeps it
out of the `open` profile; the choice is recorded for the operator, who can overturn it.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure or table
of the source is copied. The vectors are frames built by `tools/gen/radio-vectors.py` from values
chosen there; their expected bytes are derived there, without an engine.
