# Pack: ppp-frame

The header of a PPP frame, as IETF RFC 1661 section 2 and RFC 1662 section 3
lay it out: the address and control octets of HDLC-like framing when present,
and the protocol field, 1 or 2 octets. Public. Written by hand from the RFCs;
the layout is stated in this repository's words. I/O is hex text. Needs engine
version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is one PPP frame between its flag sequences, with octet transparency
already undone. The pack reads the address, control and protocol fields; the
information field, padding and FCS are read over and not written (vector 01).

| Kind | `when` | Protocol field |
|---|---|---|
| `hdlc-protocol-16` | octet 0 = 0xFF, octet 1 = 0x03, octet 2 even | octets 2-3 |
| `hdlc-protocol-8` | octet 0 = 0xFF, octet 1 = 0x03, octet 2 odd | octet 2 |
| `protocol-16` | octet 0 even | octets 0-1 |
| `protocol-8` | octet 0 odd | octet 0 |

The protocol is `inet.ppp_protocol` (`uint`) in each kind. The kinds follow
from two rules of the RFCs: a protocol value's first octet is even and its
last octet odd (RFC 1661), so a compressed 1-octet protocol is odd; and with
address and control field compression the frame starts with the protocol,
whose first octet is never 0xFF (RFC 1662). A 2-octet protocol whose last
octet is even does not follow RFC 1661; the pack carries it.

## Shared keys

None.

## Not mapped, and why

- The information field and padding: the protocol's own packet.
- The FCS (16 or 32 bits): a CRC at the end of the frame, its length agreed by
  LCP; it needs a checksum rule and the frame end.
- Flag sequences and octet transparency: the framing before the frame.

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there: an IPv4 frame
with address and control and its information and FCS, an LCP frame, a
compressed protocol after address and control, a frame with both compressions
of each protocol length, and a frame cut inside its protocol (`malformed-wire`).
