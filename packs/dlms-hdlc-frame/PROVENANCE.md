# Provenance: dlms-hdlc-frame pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| Gurux GuruxDLMS.c (Gurux Ltd) | https://github.com/Gurux/GuruxDLMS.c | `e9d77f926f3d3b8d1aa1a8f3374c7259d1c39b71` |

| File read | SHA-256 |
|---|---|
| `development/src/dlms.c` | `4bf9706a5f4f6666dd373dbde4a51ff326bd0258267b7a26193b9522fffdd05e` |

## Licence

`dlms.c` states "Copyright (c) Gurux Ltd" and that the code is licensed under the GNU General Public License
version 2; the repository's `LICENSE` is the GPL version 2. (Gurux also offers commercial licences; this
pack relies on neither, as it restates layout facts.)

This pack restates the layouts (field order, sizes, bit positions, codes) in its own words; no code,
comment or table of the source is copied. Under this project's rule for code sources the pack keeps the
default Apache-2.0 label. IEC 62056-46 and the DLMS UA Green Book, paid documents, were not used. The vectors are built by `tools/gen/meter2-vectors.py` from values chosen
there; their expected bytes are derived there, without an engine.

## Attribution

Layout from Gurux GuruxDLMS.c, https://github.com/Gurux/GuruxDLMS.c (Copyright (c) Gurux Ltd, GPL-2.0),
restated.
