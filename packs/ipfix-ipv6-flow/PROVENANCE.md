# Provenance: ipfix-ipv6-flow pack

Read on 2026-11-20. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 7011, Specification of the IPFIX Protocol, September 2013 | https://www.rfc-editor.org/rfc/rfc7011.txt | `59b7ddb1c0350ae711ba41d771d93f4d440ee04755403446f580bb777b928f73` |
| IANA registry IPFIX Information Elements, as CSV; the registry states it was updated 2026-09-11 | https://www.iana.org/assignments/ipfix/ipfix-information-elements.csv | `c8691dd71f6d5fa20839519775c0d2d40079c64a166852ae3a9fb2ecbe9eddcd` |
| IANA, Licensing Terms (the joint statement of IANA and IETF on the Protocol Registries, last revised 2021-11-10) | https://www.iana.org/help/licensing-terms | `16887b36c23739ae51b44d02cfd4e909302ece8325f815a763287afcbd589ae3` |

## Licence

RFC 7011, RFC 7012 and RFC 3954 are IETF documents. Each carries the IETF Trust copyright and refers to BCP 78 and the IETF Trust's Legal Provisions Relating to IETF Documents (https://trustee.ietf.org/license-info). This pack restates the layouts (field order, sizes, values) in its own words; no text, figure or example message of the RFCs is copied.

The IANA registry is under the joint statement of IANA and the IETF Trust on the Protocol Registries (https://www.iana.org/help/licensing-terms). It says that the two intend the registries to be freely used by anyone for any purpose, and that any rights they have in them are subject to the Creative Commons CC0 1.0 dedication. The model module `ipfix` takes element numbers, names, abstract types, semantics and units from it; no description text.

The vectors are messages built by `tools/gen/flows-vectors.py` from values chosen there; their expected bytes are derived there, without an engine.
