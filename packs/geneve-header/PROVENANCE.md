# Provenance: geneve-header pack

Read on 2026-11-20. No source file is copied into this tree. The pack, the
module `inet` and pack.md state the layout in this repository's words. The
vectors of `tools/gen/ietf-headers-4-vectors.py` are built from that layout and
from values chosen there; no example message of an RFC is used.

## Pack `geneve-header`, module `inet`

| Document | Where | SHA-256 of the text file | Used for |
|---|---|---|---|
| RFC 8926, Geneve: Generic Network Virtualization Encapsulation, November 2020 | https://www.rfc-editor.org/rfc/rfc8926.txt | `23a9fcd3c23b93a103c0228128b2dce808323a7a9d15ea9cbb395fdb9f67e37d` | the base header and the option length, section 3.4 |

The pack follows the text of the RFC; errata are listed at
https://www.rfc-editor.org/errata/rfc8926.

## Licence

The copyright notice of RFC 8926:

> Copyright (c) 2020 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (https://trustee.ietf.org/license-info) in effect on the
> date of publication of this document.

The notice goes on to say that code components extracted from the document must carry the Simplified BSD License text. No code component is extracted here.

The pack holds field positions, widths and the meaning of values, restated; no
text, figure or table of the RFC is copied.
