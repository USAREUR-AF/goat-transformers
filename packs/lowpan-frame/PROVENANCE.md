# Provenance: lowpan-frame pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 4944, Transmission of IPv6 Packets over IEEE 802.15.4 Networks, September 2007 | https://www.rfc-editor.org/rfc/rfc4944.txt | `2a1d639aa85e37d860f4c1e535865cdcc3dfc9f48518a2fcc922b3b18ce78c63` |
| IETF RFC 6282, Compression Format for IPv6 Datagrams over IEEE 802.15.4-Based Networks, September 2011 | https://www.rfc-editor.org/rfc/rfc6282.txt | `a3b46845b7223dff27bb78c1c094caa1a6ffdc1f87ec17b8ff905c4aedc4a7f2` |
| IETF RFC 7400, 6LoWPAN-GHC: Generic Header Compression for IPv6 over LoWPANs, November 2014 | https://www.rfc-editor.org/rfc/rfc7400.txt | `d7e583fb7f5aa839e4c8fc32343b09fec43df95e4659868c52232bc3b63b9be9` |

## Licence

RFC 6282 and RFC 7400 are IETF documents: "Copyright (c) 2011 IETF Trust and the persons identified as the
document authors. All rights reserved." (RFC 6282; RFC 7400 has the same notice for 2014). RFC 4944
carries "Copyright (C) The IETF Trust (2007)." Each is subject to BCP 78 and the IETF Trust's Legal
Provisions Relating to IETF Documents (https://trustee.ietf.org/license-info). The pack keeps the default
Apache-2.0 label.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure, table or
code of the sources is copied. The vectors are frames built by `tools/gen/mesh-vectors.py` from values
chosen there; their expected bytes are derived there, without an engine.
