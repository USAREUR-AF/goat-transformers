# Pack: geneve-header

The Geneve header, as IETF RFC 8926 section 3.4 lays it out: the 8-octet base
header, and the options as raw 4-octet words counted by the option length.
Public. Written by hand from the RFC; the layout is stated in this
repository's words. I/O is hex text. Needs engine version 0.7 (a counted
`bits` group).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the UDP payload of a Geneve packet. The pack reads the base header
and the option words; the payload is read over and not written (vector 01).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bits 0-1 | version | `inet.geneve_version` | `uint` |
| 0, bits 2-7 | option length, 4-octet words | `inet.geneve_opt_len` | `uint`; also the count of the words |
| 1, bit 0 | O, control packet | `inet.geneve_control` | `uint` |
| 1, bit 1 | C, critical options present | `inet.geneve_critical` | `uint` |
| 1, bits 2-7 | reserved | `inet.geneve_reserved1` | `uint` |
| 2-3 | protocol type | `inet.geneve_protocol_type` | `uint` |
| 4-6 | VNI | `inet.geneve_vni` | `uint` |
| 7 | reserved | `inet.geneve_reserved2` | `uint` |
| 8 on, 4 each | options | list `inet.geneve_option_words`, item key `inet.geneve_option_word` | `item 32 count 0:2:6`, `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The option length is
both a field and the count of the words (ruling 2 of 0.7). Carrying the options
as words keeps them bit for bit on a round trip (vector 02) without decoding
them.

## Shared keys

None. The VNI has the meaning of the VXLAN VNI (a 24-bit virtual network
identifier) but the two RFCs do not define one as the other; the keys stay
apart.

## Not mapped, and why

- The options as options: each is a class (16 bits), a type (8), 3 reserved
  bits and a 5-bit length in 4-octet words, then its data. The number of
  options is not on the wire, only their total length; a `bits` group needs a
  count of items. The `tlv` wire (0.13) reads a whole message, not a part
  inside a `bits` message.
- The payload.

## Vectors

`tools/gen/ietf-headers-4-vectors.py`, from values chosen there: a base header
carrying Ethernet, one critical option as two words, the largest values with
63 words (260 octets), a header cut inside its options and 7 octets (both
`malformed-wire`).
