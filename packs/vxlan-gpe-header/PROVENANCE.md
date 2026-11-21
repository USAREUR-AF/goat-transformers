# Provenance: vxlan-gpe-header pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF Internet-Draft draft-ietf-nvo3-vxlan-gpe-13, Generic Protocol Extension for VXLAN (VXLAN-GPE), November 2023 | https://www.ietf.org/archive/id/draft-ietf-nvo3-vxlan-gpe-13.txt | `02928ea03d3f99b33ef6107ccef28a30ce580ace676d94de494804fd80a49d65` |
| IETF RFC 7348, VXLAN, August 2014 (for the shared keys) | https://www.rfc-editor.org/rfc/rfc7348.txt | `731475429b30bf4b29a102a0c9217cb0d3522c34fd546ba7b134fec931e83574` |

## Licence

Each source is an IETF document: "Copyright (c) 2023 IETF Trust and the persons identified as the
document authors. All rights reserved." (the draft; RFC 7348 has the same notice for 2014). It is subject to BCP 78 and the IETF Trust's Legal Provisions
Relating to IETF Documents (https://trustee.ietf.org/license-info). The pack keeps the default Apache-2.0
label.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure, table or
code of the sources is copied. The vectors are packets built by `tools/gen/tunnels-vectors.py` from
values chosen there; their expected bytes are derived there, without an engine.
