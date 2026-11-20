# Pack: rtp-header

The fixed header of an RTP data packet, the first 12 octets, as IETF RFC 3550
section 5.1 lays it out. Public. Written by hand from the RFC; the layout is
stated in this repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the UDP payload of an RTP packet. The pack reads octets 0-11; the
CSRC list, a header extension, the payload and padding are read over and not
written (vector 03).

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

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The pack does not
check the version (vector 02).

## Shared keys

None. The RTP timestamp counts in the clock of the payload format, from a
random offset (RFC 3550 section 5.1), so it is not a time `time_ms` could hold.

## Not mapped, and why

- The CSRC list (CSRC count times 4 octets). Fixed parts only in this pack;
  a counted `bits` group (`group … item 32 count 0:4:4`) can state it, and is
  a candidate for a later version. The count is kept as `inet.rtp_csrc_count`.
- The header extension and the payload: their layout belongs to the profile.
- Padding: its length is in the last octet of the packet.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: a round trip
with a dynamic payload type, a round trip with every field at its largest
value, a header with two CSRC identifiers and a payload (the fixed part comes
back), and 11 octets (`malformed-wire`).
