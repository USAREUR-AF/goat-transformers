# Provenance: hart-ip-message pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| Wireshark | https://github.com/wireshark/wireshark | `de1eec95b2007952f7399173d2f0904275a31c6f` |

| File read | SHA-256 |
|---|---|
| `epan/dissectors/packet-hartip.c` | `9f0f47483e289f5407c8757850c8deb5f28fa98f1058e552f72ac26d53af94ac` |

## Licence

Each Wireshark file gives the SPDX licence identifier `GPL-2.0-or-later` in its header (Wireshark's
COPYING is the GNU GPL version 2).

This pack restates the layouts (field order, sizes, codes) in its own words; no code, comment or table
of the source is copied. Under this project's rule for code sources, layouts restated from GPL code are
facts and the pack keeps the default Apache-2.0 label. The FieldComm Group HART-IP specification, a paid document, was not used. The vectors are built by
`tools/gen/indauto2-vectors.py` from values chosen there; their expected bytes are derived there, without
an engine.

## Attribution

Layouts from Wireshark epan/dissectors/packet-hartip.c, https://github.com/wireshark/wireshark (Copyright
2012 Bill Schiller, Gerald Combs, GPL-2.0-or-later), restated. The FieldComm Group specification was not used.
