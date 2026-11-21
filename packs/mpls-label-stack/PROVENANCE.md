# Provenance: mpls-label-stack pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 3032, MPLS Label Stack Encoding, January 2001 | https://www.rfc-editor.org/rfc/rfc3032.txt | `c611103bf720c643a40e128159aabb1607eab97977d0f3483d468a620cd86180` |
| IETF RFC 5462, EXP Field Renamed to Traffic Class Field, February 2009 | https://www.rfc-editor.org/rfc/rfc5462.txt | `4e6154ec58f83fa5a7c1a14584ad87804fecc69092ea8e87b57027bf9246cc58` |
| IETF RFC 7510, Encapsulating MPLS in UDP, April 2015 | https://www.rfc-editor.org/rfc/rfc7510.txt | `c22acef088d16e298e47bf58366be413c06f71db84f009e40cf102d1cb25fa25` |

## Licence

RFC 5462 and RFC 7510 are IETF documents: "Copyright (c) 2015 IETF Trust and the persons identified as the
document authors. All rights reserved." (RFC 7510; RFC 5462 has the same notice for 2009). RFC 3032 (2001) carries the Internet Society's copyright
notice of its time, which permits derivative works that implement it. It is subject to BCP 78 and the IETF Trust's Legal Provisions
Relating to IETF Documents (https://trustee.ietf.org/license-info). The pack keeps the default Apache-2.0
label.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure, table or
code of the sources is copied. The vectors are packets built by `tools/gen/tunnels-vectors.py` from
values chosen there; their expected bytes are derived there, without an engine.
