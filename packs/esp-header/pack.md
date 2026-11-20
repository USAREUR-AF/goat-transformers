# Pack: esp-header

The IPsec ESP header, as IETF RFC 4303 section 2 lays it out: the SPI and the
sequence number. Public. Written by hand from the RFC; the layout is stated in
this repository's words. I/O is hex text. Needs engine version 0.2.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the payload of the IP packet (protocol 50). The pack reads octets
0-7; the payload, padding, trailer and ICV are read over and not written
(vector 01).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0-3 | security parameters index | `inet.ipsec_spi` | `uint` |
| 4-7 | sequence number | `inet.ipsec_seq` | `uint` |

## Shared keys

`inet.ipsec_spi` and `inet.ipsec_seq` are also the keys of `ah-header`: RFC 4303
section 2.1 and RFC 4302 section 2.4 both give the SPI as the value a receiver
uses to find the security association of the packet, and sections 2.2 and 2.5
both give the sequence number as the counter for anti-replay. Vector 04 carries
them to `ah-header`.

## Not mapped, and why

- The payload, padding, pad length, next header and ICV: encrypted, or placed
  by the algorithm the SA uses.
- The high 32 bits of an extended sequence number: not on the wire.

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there: a first packet
with its payload, the largest values, 7 octets (`malformed-wire`), and the
header to `ah-header`.
