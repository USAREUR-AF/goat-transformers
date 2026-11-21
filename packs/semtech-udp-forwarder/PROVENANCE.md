# Provenance: semtech-udp-forwarder pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| Lora-net/packet_forwarder (Semtech) | https://github.com/Lora-net/packet_forwarder | `d0226eae6e7b6bbaec6117d0d2372bf17819c438` |

| File read | SHA-256 |
|---|---|
| `PROTOCOL.TXT` (Basic communication protocol between Lora gateway and server, revision v1.4) | `33c2159be7d3771a6ef9a799a5696f6423481d21248af2950301f4781f2ae696` |
| `LICENSE` | `b761e3c85ea589609fa1cf0b879875b4d69b56cef021c15b4288588c87dfc39d` |

## Licence

`PROTOCOL.TXT` carries "(C)2013 Semtech-Cycleo". The repository's `LICENSE` is "Copyright (C) 2013, SEMTECH
S.A. All rights reserved." followed by the three-clause BSD terms (redistribution in source and binary form
with the notice kept, no endorsement by the Semtech name). GitHub reports the licence as NOASSERTION; the
text is the BSD-3-Clause text with Semtech named. Under this project's rule the restated layout carries the
default Apache-2.0 label.

This pack restates the layout (byte positions and identifiers) in its own words; no text or table is
copied. The vectors are built by `tools/gen/lpwan2-vectors.py` from values chosen there; their expected
bytes are derived there, without an engine.

## Attribution

Layout from Lora-net/packet_forwarder PROTOCOL.TXT, https://github.com/Lora-net/packet_forwarder
(Copyright (C) 2013 Semtech S.A., BSD-3-Clause terms), restated.
