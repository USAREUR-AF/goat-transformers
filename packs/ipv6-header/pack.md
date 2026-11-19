# Pack: ipv6-header

The IPv6 header, the first 40 octets of an IPv6 packet, as IETF RFC 8200
section 3 lays it out. Public. Written by hand from the RFC; the layout is
stated in this repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is an IPv6 packet from its first octet. The pack reads octets 0-39.
Extension headers and the payload are read over on decode and are not written
on encode (vector 03).

## Addressing

`word_bytes 1`, `bit_order msb`: a locator is `0:<bit>:<len>`, bit 0 is the most
significant bit of octet 0, and a multi-octet field is a big-endian integer.

| Bits | Field | Key | Note |
|---|---|---|---|
| 0-3 | version | `inet.ipv6_version` | also the `when` of kind `ipv6` (6) |
| 4-11 | traffic class | `inet.ipv6_traffic_class` | |
| 12-31 | flow label | `inet.ipv6_flow_label` | |
| 32-47 | payload length | `inet.ipv6_payload_length` | octets after the header |
| 48-55 | next header | `inet.ip_protocol` | shared with `ipv4-header` |
| 56-63 | hop limit | `inet.ipv6_hop_limit` | |
| 64-191 | source address | `inet.ipv6_src_g0` … `inet.ipv6_src_g7` | eight 16-bit groups |
| 192-319 | destination address | `inet.ipv6_dst_g0` … `inet.ipv6_dst_g7` | eight 16-bit groups |

An address is 128 bits and a `bits` field at most 64, so each address is held as
its eight 16-bit groups, first group first: the groups the text form writes
(`2001:db8::1` is 0x2001, 0x0db8, 0, 0, 0, 0, 0, 1).

## Kinds

One kind, `ipv6`, with `when 0:0:4 6`: a packet whose version nibble is not 6 is
`no-kind` (vector 04). It requires the first group of each address.

## Shared keys, with evidence

No field is bound to `core` or `track`.

| Key | Also in | Evidence |
|---|---|---|
| `inet.ip_protocol` | `ipv4-header` (protocol) | RFC 8200 section 3: the next header field uses the same values as the IPv4 protocol field, from the IANA protocol numbers registry. |

## Not mapped, and why

- Extension headers (hop-by-hop options, routing, fragment, destination options):
  each is a chain link whose presence depends on the next header value before it.
- The payload.
- The traffic class read as DSCP and ECN: one integer here.

## Vectors

`tools/gen/ietf-headers-vectors.py`, from values chosen there: round trips of a
header and of edge values with a link-local source (a first group with its top
bit set), a header with its payload, a version-4 packet (`no-kind`) and 39
octets (`malformed-wire`).
