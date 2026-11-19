# Provenance: drip pack

Read on 2026-11-19. No source file is copied into this tree. The pack, its
module and pack.md state the layouts in this repository's words. The vectors of
`tools/gen/drip-vectors.py` are built from those layouts; no example message
of the RFCs is used.

## Pack `drip`, module `drip`

| Document | Where | SHA-256 of the text file |
|---|---|---|
| RFC 9575, DRIP Entity Tag (DET) Authentication Formats and Protocols for Broadcast Remote Identification (RID), June 2024, Standards Track | https://www.rfc-editor.org/rfc/rfc9575.txt | `0069e2f2037b7015f28f05607e339d922255e6a1f1b7b9230e1769c2bcce9788` |
| RFC 9434, Drone Remote Identification Protocol (DRIP) Architecture, July 2023 (context) | https://www.rfc-editor.org/rfc/rfc9434.txt | `90ccae0d7794f08744ffd8e2526aeda11f143dfe4021c5a9bed75fd94c77915f` |
| RFC 9374, DRIP Entity Tag (DET) for Unmanned Aircraft System Remote ID, March 2023 (context) | https://www.rfc-editor.org/rfc/rfc9374.txt | `3c4b8cde5e7158e8debdc3369c4895de516642d8070f5dfd68850f485c6871ff` |

Errata: https://www.rfc-editor.org/errata/rfc9575 listed none on 2026-11-19.

The copyright notice of RFC 9575:

> Copyright (c) 2024 IETF Trust and the persons identified as the document
> authors. All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal Provisions
> Relating to IETF Documents (https://trustee.ietf.org/license-info) in effect on
> the date of publication of this document.

The layout of the F3411 Location message inside a Wrapper is that of pack
`remote-id`; its source and license are in `packs/remote-id/PROVENANCE.md`.
