# Pack: bfd-control

The mandatory section of a BFD control packet, as IETF RFC 5880 section 4.1
lays it out: 24 octets. Public. Written by hand from the RFC; the layout is
stated in this repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the UDP payload of a BFD control packet. The pack reads octets
0-23; an authentication section is read over and not written (vector 04).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bits 0-2 | version | `inet.bfd_version` | `uint` |
| 0, bits 3-7 | diagnostic | `inet.bfd_diag` | `uint` |
| 1, bits 0-1 | state | `inet.bfd_state` | `uint` |
| 1, bit 2 | poll | `inet.bfd_poll` | `uint` |
| 1, bit 3 | final | `inet.bfd_final` | `uint` |
| 1, bit 4 | control plane independent | `inet.bfd_cpi` | `uint` |
| 1, bit 5 | authentication present | `inet.bfd_auth_present` | `uint` |
| 1, bit 6 | demand | `inet.bfd_demand` | `uint` |
| 1, bit 7 | multipoint | `inet.bfd_multipoint` | `uint` |
| 2 | detect multiplier | `inet.bfd_detect_mult` | `uint` |
| 3 | length | `inet.bfd_length` | `uint`, octets |
| 4-7 | my discriminator | `inet.bfd_my_disc` | `uint` |
| 8-11 | your discriminator | `inet.bfd_your_disc` | `uint` |
| 12-15 | desired min TX interval | `inet.bfd_desired_min_tx` | `uint`, microseconds |
| 16-19 | required min RX interval | `inet.bfd_required_min_rx` | `uint`, microseconds |
| 20-23 | required min echo RX interval | `inet.bfd_required_min_echo_rx` | `uint`, microseconds |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The intervals stay
integer microseconds, the unit of the wire. The pack does not check the
version, the multipoint bit or the length (vector 03).

## Shared keys

None.

## Not mapped, and why

- The authentication section (present when A is 1): its layout depends on the
  authentication type, and its length is in its second octet. Fixed parts only
  in this pack. The length octet of the mandatory section, which counts it, is
  kept.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: an Up session,
a Down session with poll set, every field at its largest value, a packet with a
simple password section (the mandatory section comes back), and 23 octets
(`malformed-wire`).
