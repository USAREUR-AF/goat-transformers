# Pack: rtcp-header

The RTCP sender report and receiver report, as IETF RFC 3550 sections 6.4.1 and
6.4.2 lay them out: the 8-octet header and, in a sender report, the 20 octets
of sender information. Public. Written by hand from the RFC; the layout is
stated in this repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is one RTCP packet, the first of a compound packet. The pack reads
octets 0-7, and 8-27 in a sender report; report blocks and extensions are read
over and not written (vector 02).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bits 0-1 | version | `inet.rtcp_version` | `uint` |
| 0, bit 2 | padding | `inet.rtcp_padding` | `uint` |
| 0, bits 3-7 | reception report count | `inet.rtcp_report_count` | `uint` |
| 1 | packet type | the `when` of the kinds | |
| 2-3 | length | `inet.rtcp_length` | `uint`: 32-bit words, less one |
| 4-7 | SSRC of the sender | `inet.rtcp_ssrc` | `uint` |
| 8-11 | NTP timestamp, whole seconds | `inet.rtcp_ntp_ts_sec` | `uint` (sender report) |
| 12-15 | NTP timestamp, fraction | `inet.rtcp_ntp_ts_frac` | `uint` (sender report) |
| 16-19 | RTP timestamp | `inet.rtcp_rtp_timestamp` | `uint` (sender report) |
| 20-23 | sender's packet count | `inet.rtcp_packet_count` | `uint` (sender report) |
| 24-27 | sender's octet count | `inet.rtcp_octet_count` | `uint` (sender report) |

`word_bytes 1`, `bit_order msb`; the fields are big-endian.

## Kinds

| Kind | `when` | Fields after the header |
|---|---|---|
| `sender-report` | packet type 200 | the sender information; `requires inet.rtcp_packet_count` |
| `receiver-report` | packet type 201 | none |

Another packet type (source description 202, goodbye 203, application 204, and
those of later RFCs) is `no-kind` (vector 05). On encode from another format a
sender report is written only when the entity carries the packet count;
otherwise a receiver report.

## Shared keys

None. The NTP timestamp of a sender report is not bound to `time_ms`: RFC 3550
section 6.4.1 allows a sender to put a relative time there, from a clock such
as system uptime, or zero, so the field is not always a wall-clock time.

## Not mapped, and why

- Report blocks (24 octets each, as many as the count). Fixed parts only in
  this pack; a counted `bits` group with the count at `0:3:5` can state them,
  and is a candidate for a later version.
- Profile-specific extensions and padding: their layout is not fixed.
- Further packets of a compound packet: one message is one packet.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: a sender
report, a sender report with one report block (the fixed part comes back), an
empty receiver report, a receiver report header at its largest values, packet
type 202 (`no-kind`) and a sender report of 27 octets (`malformed-wire`).
