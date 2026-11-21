# Provenance: csp-v2-packet pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| libcsp v2.1 (commit 48f7fb0b57f610bf65bab1aa2d1357c3b9722782), src/csp_id.c: the CSP 1.x and 2.x header packing | https://github.com/libcsp/libcsp/blob/48f7fb0b57f610bf65bab1aa2d1357c3b9722782/src/csp_id.c | `ad02699c7c39abb69b2fcb119c51b2852ebb35ace94ca34c64ac28241b3233b8` |
| libcsp v1.6 (commit 87006959696c78f70535ab382b0bcd4cb5a6558d), include/csp/csp_types.h: the 1.x field sizes and flags (XTEA among them) | https://github.com/libcsp/libcsp/blob/87006959696c78f70535ab382b0bcd4cb5a6558d/include/csp/csp_types.h | `d469f59d2dfcaccf3548b0510367fccb20cc586be72fcd70637e724184b51e67` |
| libcsp v2.1, LICENSE | https://github.com/libcsp/libcsp/blob/48f7fb0b57f610bf65bab1aa2d1357c3b9722782/LICENSE | `cfad8cf0fedea5bf80e2daa294c70a78fc7a0692d19e1c05fcefc41ee5f879d3` |

## Licence

CSP has no specification document apart from its reference implementation. libcsp is under the MIT
License ("Copyright (c) 2009-2021 CSP Contributors (see AUTHORS file)"). The pack restates the header
layout (field order, widths, flag bits) that the code packs, in this project's words; no code or
comment is copied. Under rule 17 of this project a layout restated from permissively licensed code is
Apache-2.0: the pack keeps the default label, and the source is named here and in `NOTICE`.

The vectors are packets built by `tools/gen/space-more-vectors.py` from values chosen there; their
expected bytes are derived there, without an engine.
