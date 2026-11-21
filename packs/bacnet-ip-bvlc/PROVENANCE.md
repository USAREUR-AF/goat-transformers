# Provenance: bacnet-ip-bvlc pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| bacnet-stack (Steve Karg and contributors) | https://github.com/bacnet-stack/bacnet-stack | `229ba806601d4459a2b7889ec1280cb0ed4efcb4` |

| File read | SHA-256 |
|---|---|
| `src/bacnet/datalink/bvlc.c` | `40a18f53a7378b01f24c7821865698447a9a8988569bd0b6738987a8ae903abd` |
| `src/bacnet/datalink/bvlc.h` | `b7feb5515299de628dcd79012dcdcfce0e63d92ee7934c8e3b75062339f9cc6a` |
| `src/bacnet/npdu.c` | `46dd3dca6663ee92a4f394e87f3628530a28c833f96c76696e1f3a031eb6b9ab` |

## Licence

Each file read gives the SPDX licence identifier `GPL-2.0-or-later WITH GCC-exception-2.0` in its header;
the repository's `license/` directory holds the GPL-2.0 text and the GCC exception (and the other licences
some of its files use).

This pack restates the layouts (field order, sizes, codes) in its own words; no code, comment or table
of the source is copied. Under this project's rule for code sources, layouts restated from GPL code are
facts and the pack keeps the default Apache-2.0 label. ANSI/ASHRAE Standard 135, a paid document, was not used. The vectors are built by
`tools/gen/indauto2-vectors.py` from values chosen there; their expected bytes are derived there, without
an engine.

## Attribution

Layouts from bacnet-stack, https://github.com/bacnet-stack/bacnet-stack (Copyright Steve Karg and
contributors, GPL-2.0-or-later WITH GCC-exception-2.0), restated. ANSI/ASHRAE Standard 135 was not used.
