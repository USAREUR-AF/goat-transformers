# Provenance: wmbus-frame pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| wmbusmeters (Fredrik Öhrström and contributors) | https://github.com/wmbusmeters/wmbusmeters | `86c46f145077f66e988c25ee04c06f89230c12e3` |

| File read | SHA-256 |
|---|---|
| `src/wmbus.cc` | `a38f1dec24a00d570ccc42e07b47e22be25106c7d956c0166ab42c55a2e26623` |
| `LICENSE` | `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903` |

## Licence

`src/wmbus.cc` states "Copyright (C) 2017-2024 Fredrik Öhrström (gpl-3.0-or-later)"; `LICENSE` is the GNU GPL
version 3.

This pack restates the layouts (field order, sizes, bit positions, codes) in its own words; no code,
comment or table of the source is copied. Under this project's rule for code sources the pack keeps the
default Apache-2.0 label. EN 13757-4, a paid document, was not used. The vectors are built by `tools/gen/meter2-vectors.py` from values chosen
there; their expected bytes are derived there, without an engine.

## Attribution

Layouts from wmbusmeters, https://github.com/wmbusmeters/wmbusmeters (Copyright (C) 2017-2024 Fredrik
Öhrström, GPL-3.0-or-later), restated.
