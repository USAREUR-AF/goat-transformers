# Pack: udp-header

The UDP header, the 8 octets of IETF RFC 768. Public. Written by hand from the
RFC; the layout is stated in this repository's words. I/O is hex text. Needs
engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is a UDP datagram from its first octet; the data after octet 7 is read
over and not written (vector 02). The checksum is carried as a value; the pack
does not compute or check it.

| Bits | Field | Key |
|---|---|---|
| 0-15 | source port | `inet.src_port` |
| 16-31 | destination port | `inet.dst_port` |
| 32-47 | length (octets, header and data) | `inet.udp_length` |
| 48-63 | checksum | `inet.udp_checksum` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian.

## Shared keys, with evidence

No field is bound to `core` or `track`.

| Key | Also in | Evidence |
|---|---|---|
| `inet.src_port`, `inet.dst_port` | `tcp-header` | RFC 768 gives the source port as the port of the sending process and the destination port as the port at the destination; RFC 9293 section 3.1 gives the TCP source and destination port numbers the same 16-bit meaning. Both draw on the one IANA service name and port number registry. |

A UDP datagram converted to `tcp-header` carries its ports, and the TCP fields it
has no value for are zero bits (vector 03).

## Not mapped, and why

- The data.
- The pseudo header of the checksum: it is made of IP header fields, not sent in
  the UDP header.

## Vectors

`tools/gen/ietf-headers-vectors.py`, from values chosen there: a round trip with a
checksum computed over an IPv4 pseudo header, edge values (source port 0,
checksum 0) with data, a conversion to `tcp-header`, and 7 octets
(`malformed-wire`).
