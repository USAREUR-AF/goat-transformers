# Provenance: netflow5 pack

Read on 2026-11-20. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| Cisco Systems, NetFlow Export Datagram Format, NetFlow Collection Engine 3.6 user guide, page updated 2007-09-14; the copy the Internet Archive took on 2026-11-10 (the publisher's server refuses a scripted download) | https://www.cisco.com/c/en/us/td/docs/net_mgmt/netflow_collection_engine/3-6/user/guide/format.html, read as https://web.archive.org/web/20261110233649id_/https://www.cisco.com/c/en/us/td/docs/net_mgmt/netflow_collection_engine/3-6/user/guide/format.html | `1d8744162bed54563bbe51b8a54f1af364ef0e5ff5fe70160df8f74f7f2a0b09` (the page as served, decompressed) |
| IETF RFC 3954, Cisco Systems NetFlow Services Export Version 9, October 2004 (Informational) | https://www.rfc-editor.org/rfc/rfc3954.txt | `dfb55ec88ce0a5f53139d3e1b06f039e5237a25c21122bcc3d4d40903505ee3f` |
| IETF RFC 7012, Information Model for IPFIX, September 2013 (section 4: identifiers 1 to 127 are the NetFlow version 9 field types) | https://www.rfc-editor.org/rfc/rfc7012.txt | `85b4f7d66a1de7d29897e12f67d8d67cfdeb8f2eafc6107a46899ddf08fa137f` |
| IANA registry IPFIX Information Elements, as CSV; the registry states it was updated 2026-09-11 | https://www.iana.org/assignments/ipfix/ipfix-information-elements.csv | `c8691dd71f6d5fa20839519775c0d2d40079c64a166852ae3a9fb2ecbe9eddcd` |
| IANA, Licensing Terms (the joint statement of IANA and IETF on the Protocol Registries, last revised 2021-11-10) | https://www.iana.org/help/licensing-terms | `16887b36c23739ae51b44d02cfd4e909302ece8325f815a763287afcbd589ae3` |

## Licence

The Cisco page states no licence and no terms of use; the page carries no copyright line in its body (Cisco's site terms apply to the site as a whole). This pack restates the field layout (offsets, sizes, names, meaning) in its own words; no text or table of the page is copied. Because no licence is stated, the pack is labelled `LicenseRef-unstated` in REUSE.toml, which keeps it out of the `open` profile until a person resolves it (LICENSING.md).

RFC 7011, RFC 7012 and RFC 3954 are IETF documents. Each carries the IETF Trust copyright and refers to BCP 78 and the IETF Trust's Legal Provisions Relating to IETF Documents (https://trustee.ietf.org/license-info). This pack restates the layouts (field order, sizes, values) in its own words; no text, figure or example message of the RFCs is copied.

The IANA registry is under the joint statement of IANA and the IETF Trust on the Protocol Registries (https://www.iana.org/help/licensing-terms). It says that the two intend the registries to be freely used by anyone for any purpose, and that any rights they have in them are subject to the Creative Commons CC0 1.0 dedication. The model module `ipfix` takes element numbers, names, abstract types, semantics and units from it; no description text.

The vectors are messages built by `tools/gen/flows-vectors.py` from values chosen there; their expected bytes are derived there, without an engine.
