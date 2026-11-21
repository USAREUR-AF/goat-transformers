# Provenance: doip-message pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| Wireshark | https://github.com/wireshark/wireshark | `de1eec95b2007952f7399173d2f0904275a31c6f` |

| File read | SHA-256 |
|---|---|
| `epan/dissectors/packet-doip.c` | `ad42912b3b1d9c38dbc35a0d7f065c79b3aedff5e07254a11af7ac798c0f529e` |

## Licence

The file gives the SPDX licence identifier `GPL-2.0-or-later` in its header (Wireshark's COPYING is the GNU
GPL version 2). Under this project's rule for code sources the restated layouts carry the default
Apache-2.0 label.

This pack restates the layouts (field order, sizes, codes) in its own words; no code, comment or table
of the source is copied. ISO 13400-2, a paid document, was not used. The vectors are built by `tools/gen/vehnet-vectors.py` from values chosen
there; their expected bytes are derived there, without an engine.

## Attribution

Layouts from Wireshark epan/dissectors/packet-doip.c, https://github.com/wireshark/wireshark (Copyright
1998 Gerald Combs and contributors, GPL-2.0-or-later), restated.
