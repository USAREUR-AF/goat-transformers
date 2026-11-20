# Pack: pcep

A PCEP message (RFC 5440): the common header, then every object. Wire `bits`, `layout
sequential`, most significant bit first, big-endian. One kind, `message`: version 1 is its `when`,
then the flags, the message type and the message length (a `length 16 whole` line). Input and
output are hex. Written by `tools/gen/pcep-pack.py`. A TCP stream of messages is one message per
pack message.

## What is mapped

Each object is an item of `pcep.objects`: its common header (class, type, the P and I flags, the
length as a `length 16 bytes plus 4` block, since it counts the 4-octet header) and its body by
class:

| Class | Object | Body |
|---|---|---|
| 1 | OPEN | version, flags, keepalive, deadtimer, session ID, TLVs |
| 2 | RP | flags with O, B, R and the priority, request ID, TLVs |
| 3 | NO-PATH | nature of issue, C flag, flags, TLVs |
| 4 | END-POINTS | by object type: IPv4 (1) or IPv6 (2) source and destination; other types as octets |
| 5 | BANDWIDTH | the bandwidth, an IEEE single (`f32`) |
| 6 | METRIC | flags with C and B, metric type, value (`f32`) |
| 7, 8, 10 | ERO, RRO, IRO | subobjects (RFC 3209 section 4.3.3): the L bit, type, length; IPv4 prefix (1), IPv6 prefix (2), AS number (32); other types as octets |
| 9 | LSPA | the three attribute filters, setup and holding priority, flags with L, TLVs |
| 11 | SVEC | flags with S, N and L, the request IDs |
| 12 | NOTIFICATION | flags, type, value, TLVs |
| 13 | PCEP-ERROR | flags, error type, error value, TLVs |
| 14 | LOAD-BALANCING | flags, the most TE LSPs, the least bandwidth (`f32`) |
| 15 | CLOSE | flags, reason, TLVs |
| any other | | the body as octets |

TLVs (RFC 5440 section 7.1): type, length, the value as octets, then padding to a multiple of 4
octets (`align 32`). The message types (Open, Keepalive, PCReq, PCRep, PCNtf, PCErr, Close) differ
only in which objects they hold, so the message type is a field, not a kind.

## Shared keys

None: PCEP carries path computation requests and replies, not a reported entity.

## Not mapped

- **TLV values** are octets: RFC 5440 defines no TLV of its own; the TLVs of later documents
  (stateful PCE, segment routing) are not laid out.
- **Objects of later documents** (LSP, SRP and others of RFC 8231 and after) are octets.
- **RRO subobjects** have no L bit; the pack reads that bit as `sub_l`, which an RRO keeps 0.

## Vectors

`tools/gen/ietf-more-vectors.py` builds each message from its own restatement of the RFCs and
derives `expect` without an engine: Open with two TLVs, Keepalive, PCRep with an ERO and a METRIC
bound, PCReq with IPv6 END-POINTS, an IRO and an SVEC, PCRep with NO-PATH, PCErr, PCNtf,
LOAD-BALANCING, Close, version 2 (`no-kind`) and a truncated message (`malformed-wire`). A PCReq
vector with IPv4 END-POINTS, BANDWIDTH, LSPA and an object of unknown class was dropped (its input
set the RP B bit where its model stated the O bit); those bodies have no vector yet.
