# Pack: pfcp

A PFCP message (3GPP TS 29.244, ETSI TS 129 244 V19.6.0): the header and the IEs, node and session
messages alike. Wire `bits`, `layout sequential`, most significant bit first, big-endian. One kind,
`message`: version 1 is its `when`. Input and output are hex; one message is one UDP payload (port
8805). Written by `tools/gen/gtp-pack.py`.

**Licence.** The specification states no licence; its ETSI and 3GPP editions reserve all rights.
The layout is restated in this project's words, and the pack is labelled `LicenseRef-unstated`
(PROVENANCE.md quotes both notices and the ETSI SR 000 314 pointer to declared essential IPRs).

## What is mapped

The header: two spare bits, the flags FO, MP and S, the message type, the length (a `length 16
bytes` block: the length counts what follows the first 4 octets), the SEID when S is 1 (session
messages), the sequence number, and the message priority when MP is 1 (else a spare octet).

Each IE is an item of `pfcp.ies`: the vendor bit and the 15-bit type, the length (a `length 16
bytes` block), and for a vendor IE the enterprise ID and the value as octets; for a 3GPP IE the value
by type:

| Type | IE | Read as |
|---|---|---|
| 19 | Cause | cause value |
| 20, 42 | Source Interface, Destination Interface | interface value |
| 29 | Precedence | precedence |
| 56 | PDR ID | rule ID |
| 57 | F-SEID | the flags V4 and V6, SEID, the IPv4 and IPv6 addresses by the flags |
| 60 | Node ID | type, then an IPv4 address, an IPv6 address, or the FQDN as octets |
| 96 | Recovery Time Stamp | the time, NTP seconds |
| 1-18, 51, 54, 58, 59 | Create/Update/Remove PDR, FAR, URR, QER, PDI and the other grouped IEs of those numbers | the IEs inside, one level deep (`pfcp.grouped_ies`) |
| any other | | the value as octets |

An extendable IE may carry octets after its defined fields; they are kept (`pfcp.extra`).

## Shared keys

None. The Recovery Time Stamp is when the node started, not the time of the message.

## Not mapped

- The IEs not in the table (F-TEID, Network Instance, SDF Filter, Apply Action, FAR ID, MBR, Volume
  Threshold and the rest) are octets.
- Grouped IEs are laid out one level deep: a PDI inside a Create PDR is octets.
- The grouped IEs numbered above 59 are octets.

## Vectors

`tools/gen/gtp-vectors.py`, without an engine: a heartbeat request; an association setup request;
a session establishment request with an FQDN Node ID, an F-SEID, a Create PDR and a Create FAR; a
session establishment response with message priority, an IPv6 Node ID, Cause and an F-SEID; a vendor
IE; version 2 (`no-kind`); a truncated message (`malformed-wire`).
