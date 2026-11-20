# Pack: sctp-common-header

The SCTP common header, as IETF RFC 9260 section 3.1 lays it out: the first 12
octets of an SCTP packet. Public. Written by hand from the RFC; the layout is
stated in this repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the IP payload of an SCTP packet. The pack reads octets 0-11; the
chunks are read over and not written (vector 04).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0-1 | source port | `inet.src_port` | `uint` |
| 2-3 | destination port | `inet.dst_port` | `uint` |
| 4-7 | verification tag | `inet.sctp_verification_tag` | `uint` |
| 8-11 | checksum (CRC32c) | `inet.sctp_checksum` | `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The checksum is
carried as the integer of its four octets in wire order, not computed or
checked.

## Shared keys

`inet.src_port` and `inet.dst_port`, the keys of the UDP and TCP packs. Evidence:
RFC 9260 section 3.1 gives the source port as the port number of the SCTP
sender and the destination port as that of the receiver, 16-bit unsigned
integers, used with the IP addresses to find the association; the UDP and TCP
packs bind the same keys to the ports of their senders and receivers (their
pack.md). The key descriptions in `model/inet.def` now name SCTP. Vector 06
carries both ports to `udp-header`.

## Not mapped, and why

- The chunks: a sequence of type-length-value parts after the header, each
  padded to 4 octets. Fixed parts only in this pack.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: a common
header, a zero verification tag, every field at its largest value, a header
followed by a DATA chunk, 11 octets (`malformed-wire`), and the header to
`udp-header`.
