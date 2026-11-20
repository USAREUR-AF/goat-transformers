# Provenance: esp-header pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/link-headers-vectors.py` are built from that layout and
from values chosen there; no example of a document is used.

## Pack `esp-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 4303, IP Encapsulating Security Payload (ESP), December 2005 | https://www.rfc-editor.org/rfc/rfc4303.txt | `d22f9d4120e5645525b63ac7bbf8ef78c334fe003a2c48bf1e25ac25f6e7dc58` | the SPI and the sequence number, section 2 |

## Licence

The copyright notice of RFC 4303:

> Copyright (C) The Internet Society (2005).

Its Full Copyright Statement makes the document subject to the rights, licenses and restrictions of BCP 78. The IETF Trust's Legal Provisions (https://trustee.ietf.org/license-info) cover it.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of a document is copied.
