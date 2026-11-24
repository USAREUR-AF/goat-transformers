# Provenance: mbus-frame pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| libmbus (Raditex AB, rSCADA, and contributors) | https://github.com/rscada/libmbus | `94352715928182d9e1761959f887c6a66e70de93` |

| File read | SHA-256 |
|---|---|
| `mbus/mbus-protocol.h` | `18d6cc6897b05620ed2836aaa091179cde9a79a2a887a27041e0d3f4ede07ade` |
| `mbus/mbus-protocol.c` | `dddfb43c266a29e2ecd6af773f9b7b0d8c3c68cf5b4a333101c72d122e06012c` |
| `COPYING` | `75f1f9854bae0c61ff3281324798315f89e52b5ef846c2b088008449b93ead3e` |

## Licence

`COPYING` states "Copyright (C) 2010-2012, Raditex AB and contributors. All rights reserved." and that the
library is published as open source and is free for anyone to use as long as due credit is given to
rSCADA and Raditex Control in derivative work. GitHub reports the repository's licence as BSD-3-Clause;
the file at this commit is the short permission quoted, not the BSD text. The credit it asks for is
given below and in `tools/notice/entries/mbus-frame.txt`.

This pack restates the layouts (field order, sizes, bit positions, codes) in its own words; no code,
comment or table of the source is copied. Under this project's rule for code sources the pack keeps the
default Apache-2.0 label. EN 13757-2 and -3 and their terms: not read. The vectors are built by `tools/gen/meter2-vectors.py` from values chosen
there; their expected bytes are derived there, without an engine.

## Attribution

Layouts from libmbus, https://github.com/rscada/libmbus, a component of rSCADA (http://www.rSCADA.se),
Copyright (C) 2010-2012 Raditex AB and contributors, restated. Credit to rSCADA and Raditex Control.
