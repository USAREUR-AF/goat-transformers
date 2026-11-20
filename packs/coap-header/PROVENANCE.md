# Provenance: coap-header pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-4-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `coap-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 7252, The Constrained Application Protocol (CoAP), June 2014 | https://www.rfc-editor.org/rfc/rfc7252.txt | `abfe8cce3370b5b32487421b35725eb6eaf962ea454cad008b5a5cd052e27c5f` | the message header and token, section 3 |

The pack follows the text of the RFC; errata are listed at
https://www.rfc-editor.org/errata/rfc7252.

## Licence

The copyright notice of RFC 7252:

> Copyright (c) 2014 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (http://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The notice goes on to say that code components extracted from the document must carry the Simplified BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
