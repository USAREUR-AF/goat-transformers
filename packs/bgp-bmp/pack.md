# Pack: bgp-bmp

A BGP Monitoring Protocol message (RFC 7854), with the Adj-RIB-Out of RFC 8671 and the Loc-RIB
of RFC 9069. Wire `bits`, `layout sequential` (engine-spec 0.8, 0.20, 0.21), most significant bit
first, big-endian. One kind, `message`: version 3 is its `when`, the message length a `length 32
whole` line, then the message type and a `switch` on it. Input and output are hex. The pack is
written by `tools/gen/bmp-pack.py` from one statement of each repeated block.

## What is mapped

| Message type | Read as |
|---|---|
| 0 Route Monitoring | the per-peer header, then the BGP UPDATE (below); its AS numbers are 2 octets when the A flag is 1, else 4 |
| 1 Statistics Report | the per-peer header, a count of 32 bits, then each statistic: type, length, and by type a 32-bit counter (0-6, 11-13), a 64-bit gauge (7, 8, 14, 15) or an AFI, a SAFI and a gauge (9, 10, 16, 17); any other type as octets |
| 2 Peer Down | the per-peer header, the reason, then by reason a BGP NOTIFICATION (1, 3), an FSM event code (2), information TLVs (6, RFC 9069) or nothing (4, 5) |
| 3 Peer Up | the per-peer header, the local address (IPv4 or IPv6 by the V flag), the local and remote port, the sent and the received OPEN, information TLVs |
| 4 Initiation, 5 Termination | information TLVs; the termination reason (type 1) as its 2-octet code |
| 6 Route Mirroring | the per-peer header, then TLVs: a BGP message (type 0) or an information code (type 1) |
| any other | the body as octets |

**The per-peer header**: peer type (3 is the Loc-RIB instance of RFC 9069), the flags V (for the
Loc-RIB type, the F flag in the same bit), L, A and O (RFC 8671) and the four reserved bits, the
peer distinguisher, the peer address (IPv6 when V is 1, else IPv4 in the last 4 octets), peer AS,
BGP identifier, and the timestamp in seconds and microseconds.

**A BGP message** (RFC 4271 section 4): the 16-octet marker (written as all ones), the length (a
`length 16 bytes plus 18` block), the type. An UPDATE: the withdrawn IPv4 prefixes, the path
attributes, the announced IPv4 prefixes; a prefix is its length and the fewest octets that hold
it. The attributes ORIGIN, AS_PATH (segments and their AS numbers), NEXT_HOP, MULTI_EXIT_DISC and
LOCAL_PREF are read; every other attribute is kept as octets. An OPEN: version, AS, hold time,
BGP identifier, the optional parameters as octets. A NOTIFICATION: code, subcode, data as octets.
Each place lays out the types RFC 7854 puts there; another type keeps its body as octets, so a
message round-trips.

## Shared keys

None. **The timestamp is not `time_ms`.** It is seconds plus microseconds; `time_ms` holds whole
milliseconds, so the time is not exact in it unless the microseconds are a multiple of 1000. The
two fields stay raw (`bmp.timestamp_sec`, `bmp.timestamp_usec`). A derive line could give
`time_ms` truncated to the millisecond (the microseconds as nanoseconds through `uiscale:1000`,
then `ms_of`); that is left to a decision.

## Not mapped

- **Routes of other address families.** MP_REACH_NLRI and MP_UNREACH_NLRI (IPv6 and every
  family but IPv4 unicast) are attributes kept as octets.
- **ADD-PATH** (RFC 7911): BMP version 3 does not say when NLRI carry a path identifier; such an
  UPDATE is read as plain NLRI and misread.
- **Strings** (information TLVs, the VRF name, sysDescr) are their octets: the `bits` wire has no
  transform for text of a length given by a field. Needed: a text or hex transform whose length
  comes from a `length` block.
- **Route Mirroring** BGP messages are read with 4-octet AS numbers; the A flag has no meaning
  there (RFC 7854 section 4.2).
- Stat types, information TLV types and message types defined after RFC 9069 are kept as octets.

## Vectors

`tools/gen/routing-vectors.py` builds each message from its own restatement of the RFCs and
derives `expect` without an engine: route monitoring (IPv4 peer with six attributes; IPv6 peer
with the legacy AS_PATH; Adj-RIB-Out end of RIB; Loc-RIB), a statistics report with every layout
and an unknown type, three Peer Down reasons, a Peer Up with both OPENs, Initiation, Termination,
Route Mirroring, version 2 (`no-kind`) and a truncated message (`malformed-wire`).
