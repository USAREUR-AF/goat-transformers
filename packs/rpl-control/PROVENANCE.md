# Provenance: rpl-control pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 6550, RPL: IPv6 Routing Protocol for Low-Power and Lossy Networks, March 2012 | https://www.rfc-editor.org/rfc/rfc6550.txt | `2c09f5945d6dbba4b69203a826121150c0cff1748d10f22c5a75060e53f5cb82` |

## Licence

RFC 6550 is an IETF document: "Copyright (c) 2012 IETF Trust and the persons identified as the document
authors. All rights reserved." It is subject to BCP 78 and the IETF Trust's Legal Provisions Relating to
IETF Documents (https://trustee.ietf.org/license-info). The pack keeps the default Apache-2.0 label.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure, table or
code of the sources is copied. The vectors are frames built by `tools/gen/mesh-vectors.py` from values
chosen there; their expected bytes are derived there, without an engine.
