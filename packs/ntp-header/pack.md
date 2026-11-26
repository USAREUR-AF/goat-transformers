# Pack: ntp-header

The basic header of an NTP packet, the first 48 octets, from the first octet to
the end of the transmit timestamp, as IETF RFC 5905 section 7.3 lays it out.
Public. Written by hand from the RFC; the layout is stated in this repository's
words. I/O is hex text. Needs engine version 0.15 (`uiscale`).

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
| 40-47 | transmit timestamp | `inet.ntp_xmt_ts_sec`, `inet.ntp_xmt_ts_frac`; octets 40-43 also `time_ms` | `uint`, `uint`; `uiscale:1000:-2208988800000` (Shared keys) |

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

`time_ms`, from the whole seconds of the transmit timestamp (octets 40-43), with
`uiscale:1000:-2208988800000` (engine-spec 0.15): the seconds times 1000, less
the 2 208 988 800 000 ms between 1900-01-01 and 1970-01-01. The integer scale is
exact (no double), so the result is the transmit time in milliseconds since
1970 UTC, truncated to the whole second. Evidence: RFC 5905 section 7.3 gives
the transmit timestamp as the time at which the packet left its sender, and
section 6 counts NTP seconds from 1900-01-01 00:00 UTC. The line for `time_ms`
comes before the raw `inet.ntp_xmt_ts_sec`, which stays.

Sub-second part. The fraction (octets 44-47) stays the raw key
`inet.ntp_xmt_ts_frac` and is not added: decode gives `time_ms` a multiple of
1000. On a same-format round trip both raw keys are written back, so no bit is
lost. From another format, encode writes `round((time_ms + 2208988800000) /
1000)`, rounding half away from zero, so a time with 500 ms or more goes to the
next second, and the fraction field is written 0 unless the entity carries
`inet.ntp_xmt_ts_frac`.

Era. The seconds are modulo 2^32 and the era is not on the wire. The binding
reads era 0, 1900-01-01 to 2036-02-07 06:28:15 UTC; a timestamp of era 1
decodes to a time in era 0, and a `time_ms` after the end of era 0 does not fit
32 bits and is `transform-encode`, as is a time before 1900.

Zero. RFC 5905 section 6 gives an all-zero timestamp the meaning of a time not
known. The `time_ms` line has `absent 0`: transmit seconds 0 decode with no
`time_ms` (vectors 04 and 09), and an entity without `time_ms` writes 0, as it
did before. Limit: the sentinel is on the seconds alone, so a true
1900-01-01T00:00:00 with a fraction of a second has no `time_ms`; the raw keys
keep both halves.

The other three timestamps stay raw: they are not the time of this packet
(reference: when the clock was last set; origin and receive: times of the
request).

## Not mapped, and why

- Extension fields, the key identifier and the digest: optional, of varying
  length.
- The era number: not on the wire.

## Vectors

`tools/gen/ietf-headers-vectors.py`, from values chosen there: a client request,
a stratum 1 reply, a stratum 2 reply with edge values (leap indicator 3, poll
-128, precision 127, the largest root delay, the last second of era 0), a kiss
code reply, a reply with key identifier and digest, a kiss code with a control
octet (`transform-decode`), 47 octets (`malformed-wire`), and the server reply
to GeoJSON carrying `time_ms`. From GeoJSON (in `packs/geojson/vectors`,
`ntp-header-*.json`): 500 ms past a second rounds up, 499 ms rounds down, the
last second of era 0, the NTP epoch, and `transform-encode` one second after
era 0 and one second before 1900.

## Kind on encode from another format

`secondary` requires `time_ms`, the transmit timestamp.
An entity that fits no kind is `no-kind`.
