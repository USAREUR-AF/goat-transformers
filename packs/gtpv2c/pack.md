# Pack: gtpv2c

A GTPv2-C message (3GPP TS 29.274, ETSI TS 129 274 V19.6.0): the header and the IEs. Wire `bits`,
`layout sequential`, most significant bit first, big-endian. One kind, `message`: version 2 is its
`when`. Input and output are hex; one message is one UDP payload (port 2123). Written by
`tools/gen/gtp-pack.py`.

**Licence.** The specification states no licence; its ETSI and 3GPP editions reserve all rights.
The layout is restated in this project's words, and the pack is labelled `LicenseRef-unstated`
(PROVENANCE.md quotes both notices and the ETSI SR 000 314 pointer to declared essential IPRs).

## What is mapped

The header: the flags P, T and MP and two spare bits, the message type, the length (a `length 16
bytes` block: the length counts what follows the first 4 octets), the TEID when T is 1, the sequence
number, and the message priority when MP is 1 (else a spare octet).

Each IE is an item of `gtpv2.ies`: its type, its length (a `length 16 bytes plus -1` block, which
holds the spare-and-instance octet too), the spare bits, the instance, and the value by type:

| Type | IE | Read as |
|---|---|---|
| 1 | IMSI | the digits, two per octet (TBCD: the earlier digit in the low nibble; a filler of 15) |
| 2 | Cause | cause value, the flags PCE, BCE, CS, and the offending IE as octets |
| 3 | Recovery | restart counter |
| 73 | EBI | the EPS bearer ID |
| 87 | F-TEID | the flags V4 and V6, interface type, TEID or GRE key, the IPv4 and IPv6 addresses by the flags |
| 93, 109, 195 | Bearer Context, PDN Connection, SCEF PDN Connection | the IEs inside, one level deep (`gtpv2.grouped_ies`) |
| any other | | the value as octets |

## Shared keys

None.

## Not mapped

- The IEs not in the table (APN, ULI, Serving Network, RAT Type, AMBR, Bearer QoS, PAA and the rest)
  are octets.
- Grouped IEs are laid out one level deep; a grouped IE inside one is octets.
- A piggybacked message (P = 1) after this one is not read; the pack reads one message.

## Vectors

`tools/gen/gtp-vectors.py`, without an engine: an echo request with Recovery; a Create Session
Request with IMSI, F-TEID and a Bearer Context; a Create Session Response with message priority,
Cause, a dual-stack F-TEID and a Bearer Context; a Delete Session Request with an APN kept as octets;
version 1 (`no-kind`); a truncated message (`malformed-wire`).
