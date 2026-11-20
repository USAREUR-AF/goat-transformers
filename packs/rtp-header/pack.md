# Pack: rtp-header

The header of an RTP data packet, the 12 fixed octets and the CSRC list after
them, as IETF RFC 3550 section 5.1 lays it out. Public. Written by hand from the RFC; the layout is
stated in this repository's words. I/O is hex text. Needs engine version 0.7 (a counted `bits` group).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the UDP payload of an RTP packet. The pack reads octets 0-11 and
the CSRC list; a header extension, the payload and padding are read over and
not written (vector 03).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bits 0-1 | version | `inet.rtp_version` | `uint` |
| 0, bit 2 | padding | `inet.rtp_padding` | `uint` |
| 0, bit 3 | extension | `inet.rtp_extension` | `uint` |
| 0, bits 4-7 | CSRC count | `inet.rtp_csrc_count` | `uint` |
| 1, bit 0 | marker | `inet.rtp_marker` | `uint` |
| 1, bits 1-7 | payload type | `inet.rtp_payload_type` | `uint` |
| 2-3 | sequence number | `inet.rtp_sequence` | `uint` |
| 4-7 | timestamp | `inet.rtp_timestamp` | `uint` |
| 8-11 | SSRC | `inet.rtp_ssrc` | `uint` |
| 12 on, 4 each | CSRC list | list `inet.rtp_csrcs`, item key `inet.rtp_csrc` | `group … 0:96 item 32 count 0:4:4`, `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The pack does not
check the version (vector 02).

The CSRC count is both a field and the count of the list (ruling 2 of 0.7).
Decode reads as many identifiers as the count says; a header cut inside them
is `malformed-wire` (vector 04). Encode writes the count from the number of
items, over `inet.rtp_csrc_count`; an entity without the list writes a count
of 0 (ruling 14 of 0.7), whatever `inet.rtp_csrc_count` holds.

## Shared keys

None. The RTP timestamp counts in the clock of the payload format, from a
random offset (RFC 3550 section 5.1), so it is not a time `time_ms` could hold.

## Not mapped, and why

- The header extension and the payload: their layout belongs to the profile.
- Padding: its length is in the last octet of the packet.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: a round trip
with a dynamic payload type and an empty CSRC list, a round trip with every
field at its largest value and 15 CSRC identifiers, a header with two CSRC
identifiers and a payload (the header and list come back), a header cut inside
its CSRC list and 11 octets (both `malformed-wire`).
