# Provenance: tpkt-x224 pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 1006, ISO Transport Service on top of the TCP, Version: 3, May 1987, section 6 (the packet format) | https://www.rfc-editor.org/rfc/rfc1006.txt | `855adb9556880a3c71fb24c79f174026e763ff02b1ec19d7248a5a2005883f53` |
| IETF RFC 905, ISO Transport Protocol Specification ISO DP 8073, April 1984, section 13 (the TPDU structure and the CR, CC, DR, DT and ER TPDUs) | https://www.rfc-editor.org/rfc/rfc905.txt | `b15fd8a58189016a039c3409eb8f4cd1d9e02d10d9bc2a6fda6a5b5179e084bd` |

## Licence

Both are RFCs from before the IETF Trust; neither carries a copyright line. RFC 1006 states that its
distribution is unlimited. RFC 905 says it is distributed for information only, and that it was prepared
by retyping two ISO TC97/SC16 working documents (N1576 with the corrections of N1695) that were then
being balloted as the draft international standard. RFCs are covered by BCP 78 and the IETF Trust's Legal
Provisions Relating to IETF Documents (https://trustee.ietf.org/license-info). The pack keeps the default
Apache-2.0 label for the restated layouts; the published ISO/IEC 8073 and ITU-T X.224 texts were not used.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure or table of
the sources is copied. The vectors are packets built by `tools/gen/rdp-neg-vectors.py` from values chosen
there; their expected bytes are derived there, without an engine.

## Attribution

Layouts from IETF RFC 1006 (M. Rose, D. Cass, 1987) and IETF RFC 905 (ISO DP 8073, 1984), restated.
