# Provenance: tcp-header pack

Read on 2026-11-19. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `tcp-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 9293, Transmission Control Protocol (TCP), August 2022, STD 7 | https://www.rfc-editor.org/rfc/rfc9293.txt | `6d9ac8be4b0286f8c3d337addf442b2eb6a9b14e1366594ea7fbc273f93dc2d9` | section 3.1, the header format |
| RFC 768, User Datagram Protocol, August 1980, STD 6 | https://www.rfc-editor.org/rfc/rfc768.txt | `7dc8880e1ecef9c3f9da0db4b876a16e96bfa4f0953cc9d977d414f8f680c2f0` | the meaning of the port fields, shared keys `inet.src_port` and `inet.dst_port` |

The pack follows the text of the RFC; its errata are listed at
https://www.rfc-editor.org/errata/rfc9293.

## Licence

The copyright notice of RFC 9293:

> Copyright (c) 2022 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (https://trustee.ietf.org/license-info) in effect on
> the date of publication of this document.

The notice goes on to say that code components extracted from the document must
carry the Revised BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
