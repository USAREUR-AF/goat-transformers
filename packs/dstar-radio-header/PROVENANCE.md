# Provenance: dstar-radio-header pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| ircDDBGateway (Jonathan Naylor G4KLX) | https://github.com/g4klx/ircDDBGateway | `f5ab9f7c93c6f28147b84a8f9667f6cc4c027eaa` |

| File read | SHA-256 |
|---|---|
| `Common/HeaderData.cpp` | `b52b69bc96b84824441cbf6188abbd03accd466b042d8995ae5c3f18653c8dbb` |
| `Common/DStarDefines.h` | `471d24e2b170d0568e05e2986809d246da9fde03d33ce2dbb4929039acac362b` |
| `COPYING.txt` | `e6d6a009505e345fe949e1310334fcb0747f28dae2856759de102ab66b722cb4` |

## Licence

The files state "Copyright (C) 2010-2014 by Jonathan Naylor G4KLX" under the GNU GPL version 2 or later;
`COPYING.txt` is the GPL-2.0 text. Under this project's rule for code sources the restated layout carries
the default Apache-2.0 label. The JARL D-STAR specification was not used.

This pack restates the layout (octet offsets, lengths, flag bits) in its own words; no code or comment is
copied. The vectors are built by `tools/gen/hamdig-vectors.py` from values chosen there; their expected
bytes are derived there, without an engine.

## Attribution

Layout from ircDDBGateway, https://github.com/g4klx/ircDDBGateway (Copyright (C) 2010-2014 Jonathan Naylor
G4KLX, GPL-2.0), restated.
