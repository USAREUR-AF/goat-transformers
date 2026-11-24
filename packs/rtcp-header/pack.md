# Pack: rtcp-header

One RTCP packet, as IETF RFC 3550 sections 6.4 to 6.7 lay it out: the sender
report and receiver report with their report blocks, the header of a source
description, the goodbye packet with its list of sources, and the subtype,
SSRC and name of an application-defined packet. Public. Written by hand from
the RFC; the layout is stated in this repository's words. I/O is hex text.
Needs engine version 0.7 (counted `bits` groups).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is one RTCP packet, the first of a compound packet. What the pack
does not map after the mapped part (profile-specific extensions, SDES chunks,
the goodbye reason, application data, padding, the next packet) is read over
and not written.

Common to every kind:

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bits 0-1 | version | `inet.rtcp_version` | `uint` |
| 0, bit 2 | padding | `inet.rtcp_padding` | `uint` |
| 0, bits 3-7 | count or subtype | by kind, below | |
| 1 | packet type | the `when` of the kinds | |
| 2-3 | length | `inet.rtcp_length` | `uint`: 32-bit words, less one |

Sender report (200) and receiver report (201):

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bits 3-7 | reception report count | `inet.rtcp_report_count` | `uint`; also the count of the report blocks |
| 4-7 | SSRC of the sender | `inet.rtcp_ssrc` | `uint` |
| 8-11 | NTP timestamp, whole seconds | `inet.rtcp_ntp_ts_sec` | `uint` (sender report) |
| 12-15 | NTP timestamp, fraction | `inet.rtcp_ntp_ts_frac` | `uint` (sender report) |
| 16-19 | RTP timestamp | `inet.rtcp_rtp_timestamp` | `uint` (sender report) |
| 20-23 | sender's packet count | `inet.rtcp_packet_count` | `uint` (sender report) |
| 24-27 | sender's octet count | `inet.rtcp_octet_count` | `uint` (sender report) |
| 28 on (SR), 8 on (RR), 24 each | report blocks | list `inet.rtcp_report_blocks` | `item 192 count 0:3:5` |

A report block:

| Octets of the block | Field | Key | Transform |
|---|---|---|---|
| 0-3 | SSRC of the source reported on | `inet.rtcp_rb_ssrc` | `uint` |
| 4 | fraction lost | `inet.rtcp_rb_fraction_lost` | `uint`, units of 1/256 |
| 5-7 | cumulative number of packets lost | `inet.rtcp_rb_cumulative_lost` | `twos`: RFC 3550 6.4.1 says it goes negative when duplicates arrive |
| 8-11 | extended highest sequence number received | `inet.rtcp_rb_ext_highest_seq` | `uint` |
| 12-15 | interarrival jitter | `inet.rtcp_rb_jitter` | `uint` |
| 16-19 | last SR | `inet.rtcp_rb_lsr` | `uint` |
| 20-23 | delay since last SR | `inet.rtcp_rb_dlsr` | `uint`, units of 1/65536 s |

Source description (202), goodbye (203) and application-defined (204):

| Kind | Octets | Field | Key | Transform |
|---|---|---|---|---|
| source description, goodbye | 0, bits 3-7 | source count | `inet.rtcp_source_count` | `uint`; in a goodbye also the count of the sources |
| goodbye | 4 on, 4 each | SSRC/CSRC identifiers | list `inet.rtcp_bye_sources`, item key `inet.rtcp_bye_ssrc` | `item 32 count 0:3:5`, `uint` |
| application | 0, bits 3-7 | subtype | `inet.rtcp_app_subtype` | `uint` |
| application | 4-7 | SSRC/CSRC | `inet.rtcp_ssrc` | `uint` |
| application | 8-11 | name | `inet.rtcp_app_name` | `ascii`, 4 characters |

`word_bytes 1`, `bit_order msb`; the fields are big-endian.

A count is both a field and the count of its list (ruling 2 of 0.7). Decode
reads as many items as the count says; a packet cut inside them is
`malformed-wire` (vector 07). Encode writes the count from the number of items,
over the field; an entity without the list writes a count of 0 (ruling 14 of
0.7). The length field is carried, not computed or checked (vector 05).

## Kinds

| Kind | `when` | Requires |
|---|---|---|
| `sender-report` | packet type 200 | `inet.rtcp_packet_count` |
| `receiver-report` | packet type 201 | `inet.rtcp_packet_type=201`, `inet.rtcp_ssrc`, `inet.rtcp_report_count` |
| `source-description` | packet type 202 | `inet.rtcp_packet_type=202`, `inet.rtcp_source_count` |
| `goodbye` | packet type 203 | `inet.rtcp_packet_type=203`, `inet.rtcp_source_count` |
| `application` | packet type 204 | `inet.rtcp_packet_type=204`, `inet.rtcp_ssrc`, `inet.rtcp_app_name` |

Another packet type (the feedback messages of later RFCs, among others) is
`no-kind` (vector 12). On encode from another format a sender report is
written when the entity carries the packet count; otherwise
the kind of its packet type, and an entity without one is `no-kind`.

Version 0.2.0 moved `inet.rtcp_report_count` and `inet.rtcp_ssrc` from the
common lines into the kinds that have them: in a source description and a
goodbye, octets 4-7 begin a chunk or the list of sources, and in an
application-defined packet the 5 bits are a subtype. No key was renamed.

## Shared keys

None. The NTP timestamp of a sender report is not bound to `time_ms`: RFC 3550
section 6.4.1 allows a sender to put a relative time there, from a clock such
as system uptime, or zero, so the field is not always a wall-clock time.

## Not mapped, and why

- SDES chunks: each is an SSRC and a list of items of type, length and text,
  ended by a zero octet and padded to 32 bits. The item list ends on a value,
  not a count, and a chunk's length is not on the wire.
- The goodbye reason: an optional length octet and text after the list. The
  list is counted by a locator and so is the last thing in its scope (0.7); a
  part after it cannot be stated.
- Application data and profile-specific extensions: their layout is not fixed.
- Further packets of a compound packet: one message is one packet.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: a sender report
with no block and with two blocks (one with a negative cumulative loss), an
empty receiver report, a receiver report with one block, a receiver report and
block at their edge values, a profile extension read over, a sender report cut
inside its second block (`malformed-wire`), a source description with one
chunk (header only), a goodbye with two sources, a goodbye with a reason (read
over), an application-defined packet, packet type 205 (`no-kind`) and a sender
report of 27 octets (`malformed-wire`).
