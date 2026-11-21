# Provenance: enip-encapsulation pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| Wireshark | https://github.com/wireshark/wireshark | `de1eec95b2007952f7399173d2f0904275a31c6f` |

| File read | SHA-256 |
|---|---|
| `epan/dissectors/packet-enip.c` | `9e5fe28abb2f6cbce77763a3f77c655a2c2f7a86e96bd897b3540d5b7e60caf5` |

## Licence

Each Wireshark file gives the SPDX licence identifier `GPL-2.0-or-later` in its header (Wireshark's
COPYING is the GNU GPL version 2).

This pack restates the layouts (field order, sizes, codes) in its own words; no code, comment or table
of the source is copied. Under this project's rule for code sources, layouts restated from GPL code are
facts and the pack keeps the default Apache-2.0 label. The ODVA EtherNet/IP and CIP specifications, paid documents, were not used. The vectors are built by
`tools/gen/indauto2-vectors.py` from values chosen there; their expected bytes are derived there, without
an engine.

## Attribution

Layouts from Wireshark epan/dissectors/packet-enip.c, https://github.com/wireshark/wireshark (Copyright
Gerald Combs and the authors named in the file, GPL-2.0-or-later), restated. The ODVA specification was not used.
