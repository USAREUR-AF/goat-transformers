# Provenance: hsrp pack

Read on 2026-11-20. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 2281, Cisco Hot Standby Router Protocol (HSRP), March 1998 (Informational) | https://www.rfc-editor.org/rfc/rfc2281.txt | `743ee61a3f257fca58d7a20e5546cee2b00e6e5ae9d5978f27dc4be0d2df1dad` |

## Licence

The RFCs are IETF documents under the IETF Trust copyright, BCP 78 and the IETF Trust's Legal
Provisions Relating to IETF Documents (https://trustee.ietf.org/license-info). This pack restates the
layouts (field order, sizes, values) in its own words; no text, figure or example message of the RFCs
is copied.

RFC 2281 states (section 2) that US patent 5,473,599, assigned to Cisco Systems, Inc. and granted on 1995-12-05, may apply to HSRP, and that Cisco will license its claims on reasonable, nondiscriminatory terms. This pack restates the message layout only; it implements no router behaviour.

The vectors are messages built by `tools/gen/ietf-more-vectors.py` from values chosen there; their
expected bytes are derived there, without an engine.
