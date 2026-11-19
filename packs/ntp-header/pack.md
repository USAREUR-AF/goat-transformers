# Pack: ntp-header

The basic header of an NTP packet, the first 48 octets, from the first octet to
the end of the transmit timestamp, as IETF RFC 5905 section 7.3 lays it out.
Public. Written by hand from the RFC; the layout is stated in this repository's
words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the UDP payload of an NTP packet. The pack reads octets 0-47.
Extension fields, the key identifier and the message digest are read over and
not written (vector 05).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0, bits 0-1 | leap indicator | `inet.ntp_leap` | `uint` |
| 0, bits 2-4 | version | `inet.ntp_version` | `uint` |
| 0, bits 5-7 | mode | `inet.ntp_mode` | `uint` |
| 1 | stratum | `inet.ntp_stratum` | `uint`; also the `when` of the kinds |
| 2 | poll | `inet.ntp_poll` | `twos`: a signed power of two in seconds |
| 3 | precision | `inet.ntp_precision` | `twos`: a signed power of two in seconds |
| 4-7 | root delay | `inet.ntp_root_delay` | `uscale:1/65536`: NTP short format, 16.16 unsigned seconds |
| 8-11 | root dispersion | `inet.ntp_root_dispersion` | `uscale:1/65536` |
| 12-15 | reference ID | by kind, below | |
| 16-23 | reference timestamp | `inet.ntp_ref_ts_sec`, `inet.ntp_ref_ts_frac` | `uint`, `uint` |
| 24-31 | origin timestamp | `inet.ntp_org_ts_sec`, `inet.ntp_org_ts_frac` | `uint`, `uint` |
| 32-39 | receive timestamp | `inet.ntp_rec_ts_sec`, `inet.ntp_rec_ts_frac` | `uint`, `uint` |
| 40-47 | transmit timestamp | `inet.ntp_xmt_ts_sec`, `inet.ntp_xmt_ts_frac` | `uint`, `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. 1/65536 is exact in
binary, so a short-format value comes back bit for bit.

## Kinds: the reference ID by stratum

RFC 5905 reads the reference ID by the stratum: at stratum 0 four ASCII
characters, the kiss code; at stratum 1 the name of the reference clock in ASCII,
left-justified and padded with zero octets; above, a 32-bit code (the IPv4
address of the upstream server, or the first 32 bits of a hash of its IPv6
address).

| Kind | `when` | Reference ID |
|---|---|---|
| `kiss-code` | stratum 0 | `inet.ntp_kiss_code`, `ascii` |
| `primary` | stratum 1 | `inet.ntp_ref_clock`, `ascii` |
| `secondary` | none: every other stratum | `inet.ntp_ref_id`, `uint` |

A client request with stratum 0 and a zero reference ID decodes as kind
`kiss-code` with the empty string (vector 01). A reference ID with an octet that
`ascii` does not read, at stratum 0 or 1, is `transform-decode` (vector 06).

## Shared keys

None. No field is bound to `core` or `track`.

The timestamps are not bound to `time_ms`. An NTP timestamp is 32 bits of whole
seconds since 1900-01-01 00:00 UTC (modulo 2^32: the era is not on the wire) and
32 bits of fraction. No `bits` transform reads 32.32 fixed-point seconds since
1900 into integer milliseconds since 1970: `uscale` yields a float, and
`time_ms` is an integer. The two halves are raw integer keys, so a round trip
keeps every bit. A transform for it would allow the binding, given an era rule.

## Not mapped, and why

- Extension fields, the key identifier and the digest: optional, of varying
  length.
- The era number: not on the wire.

## Vectors

`tools/gen/ietf-headers-vectors.py`, from values chosen there: a client request,
a stratum 1 reply, a stratum 2 reply with edge values (leap indicator 3, poll
-128, precision 127, the largest root delay, the last second of era 0), a kiss
code reply, a reply with key identifier and digest, a kiss code with a control
octet (`transform-decode`) and 47 octets (`malformed-wire`).
