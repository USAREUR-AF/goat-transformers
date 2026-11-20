# Pack: icmpv6-header

The ICMPv6 message header, as IETF RFC 4443 lays it out, with the router
solicitation and router advertisement of RFC 4861: type, code, checksum and
the fixed fields of the type, 8 octets (16 for a router advertisement).
Public. Written by hand from the RFCs; the layout is stated in this
repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the IPv6 payload of an ICMPv6 packet (next header 58). The pack
reads the header and the type's fixed fields; the invoking packet of an error
message, the data of an echo message and Neighbor Discovery options are read
over and not written.

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0 | type | `inet.icmpv6_type`; also the `when` of the kinds | `uint` |
| 1 | code | `inet.icmpv6_code` | `uint` |
| 2-3 | checksum | `inet.icmpv6_checksum` | `uint` |
| 4-7 | by kind | below | |

| Kind | `when` | Octets 4 on | Keys |
|---|---|---|---|
| `destination-unreachable` | type 1 | 4-7 unused | `inet.icmpv6_unused` |
| `packet-too-big` | type 2 | 4-7 MTU | `inet.icmpv6_mtu` |
| `time-exceeded` | type 3 | 4-7 unused | `inet.icmpv6_unused` |
| `parameter-problem` | type 4 | 4-7 pointer | `inet.icmpv6_pointer` |
| `echo-request` | type 128 | 4-5 identifier, 6-7 sequence | `inet.icmpv6_identifier`, `inet.icmpv6_sequence` |
| `echo-reply` | type 129 | 4-5 identifier, 6-7 sequence | as above |
| `router-solicitation` | type 133 | 4-7 reserved | `inet.icmpv6_reserved` |
| `router-advertisement` | type 134 | 4 cur hop limit, 5 bit 0 M, bit 1 O, bits 2-7 reserved, 6-7 router lifetime, 8-11 reachable time, 12-15 retrans timer | the `inet.icmpv6_ra_*` keys |
| `other` | none | 4-7 as one integer | `inet.icmpv6_rest` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. As in the
`icmp-header` pack, the type is a common field and the `when` of each kind on
the same bits; on encode the kind's `when` value is written last. The router
lifetime stays in seconds and the reachable time and retransmit timer in
milliseconds, the units of the wire. The checksum is carried, not computed or
checked (it covers an IPv6 pseudo header the message does not hold). The six
reserved bits of a router advertisement are a field: later RFCs give some of
them meaning, and the pack carries them as read.

Each kind but `other` requires its own fields, so encode from another format
writes the first kind whose keys the entity holds, and kind `other` when it
holds only `inet.icmpv6_rest`.

## Shared keys

None. The ICMPv6 keys are not those of `icmp-header`: the type numbers and the
kinds differ, and a shared echo identifier would let an IPv4 echo reply be
written as an ICMPv6 echo request.

## Not mapped, and why

- The invoking packet of an error message (as much of it as fits in the IPv6
  minimum MTU): its first 40 octets are an IPv6 header. Mapping it would
  repeat the `ipv6-header` keys under other names inside one message; it is a
  layer, which the pack language reads one at a time. The same holds for the
  quoted IPv4 header and leading octets in the `icmp-header` pack.
- Echo data: any length.
- Neighbor Discovery options after a router solicitation or advertisement: a
  list of type, length (in units of 8 octets) and value, whose end is the end
  of the message. A `bits` group needs a count.
- Neighbor solicitation, neighbor advertisement and redirect (types 135-137):
  their 128-bit target addresses would need the eight 16-bit groups of the
  `ipv6-header` pack and are left for a later version; they decode as kind
  `other`.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: an echo
request, an echo reply with data, a port unreachable with an invoking packet,
a packet too big, a time exceeded, a parameter problem, a router solicitation
with an option, type 200 (kind `other`), a router advertisement with a prefix
option, a router advertisement at its largest values, and a router
advertisement cut to 15 octets (`malformed-wire`).
