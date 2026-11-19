# Pack: ipv4-header

The fixed part of the IPv4 header, the first 20 octets of an IP datagram, as
IETF RFC 791 section 3.1 lays it out. Public. Written by hand from the RFC; the
layout is stated in this repository's words. I/O is hex text (`spec/engine-spec.md`,
bits wire). Needs engine version 0.5 (kinds, `bit_order`, fields past their word).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is an IP datagram from its first octet. The pack reads octets 0-19.
Options (present when the header length is more than 5 words) and the data are
read over on decode and are not written on encode, so a round trip of a datagram
with options or data gives back the 20-octet fixed header alone (vector 03). The
header checksum is carried as a value; the pack does not compute or check it.

## Addressing

`word_bytes 1`, `bit_order msb`: a locator is `0:<bit>:<len>`, bit 0 is the most
significant bit of octet 0, as in the RFC's figure, and a multi-octet field is a
big-endian integer.

| Bits | Field | Key | Note |
|---|---|---|---|
| 0-3 | version | `inet.ipv4_version` | also the `when` of kind `ipv4` (4) |
| 4-7 | header length | `inet.ipv4_ihl` | 32-bit words |
| 8-15 | type of service | `inet.ipv4_tos` | the octet as one integer |
| 16-31 | total length | `inet.ipv4_total_length` | octets |
| 32-47 | identification | `inet.ipv4_identification` | |
| 48, 49, 50 | flags | `inet.ipv4_flag_reserved`, `inet.ipv4_dont_fragment`, `inet.ipv4_more_fragments` | |
| 51-63 | fragment offset | `inet.ipv4_fragment_offset` | units of 8 octets |
| 64-71 | time to live | `inet.ipv4_ttl` | |
| 72-79 | protocol | `inet.ip_protocol` | shared with `ipv6-header` |
| 80-95 | header checksum | `inet.ipv4_header_checksum` | |
| 96-127 | source address | `inet.ipv4_src_addr` | 32-bit integer |
| 128-159 | destination address | `inet.ipv4_dst_addr` | 32-bit integer |

## Kinds

One kind, `ipv4`, with `when 0:0:4 4`: a packet whose version nibble is not 4
is `no-kind` (vector 04). It requires both addresses, so an entity from another
format without them is `no-kind` on encode (vector 06).

## Shared keys, with evidence

No field is bound to `core` or `track`: an IP header has no position, time or
identity of a tracked entity.

| Key | Also in | Evidence |
|---|---|---|
| `inet.ip_protocol` | `ipv6-header` (next header) | RFC 8200 section 3 says the IPv6 next header field takes its values from the same registry as the IPv4 protocol field (IANA protocol numbers). The same number means the same protocol in both. |

## Not mapped, and why

- Options: their number and length vary with the header length, and the `bits`
  wire maps fixed positions. They are read over.
- The data after the header.
- The address as dotted text: no `bits` transform writes it; the key holds the
  32-bit integer (192.0.2.1 is 3221225985).
- The type of service octet is one integer; its later reading as a DSCP and ECN
  (RFC 2474, RFC 3168) is outside RFC 791.

## Vectors

`tools/gen/ietf-headers-vectors.py` builds every input from values it chooses and
packs it by its own restatement of the layout; no message is taken from a
document. Round trips of a datagram header and of edge values, a header with an
option and data, a version-6 packet (`no-kind`) and 19 octets (`malformed-wire`).
A conversion to `ipv6-header` gives `no-kind` (its kind requires both
addresses); no vector pins it, because the device profile refuses that plan
at compile time.
