# Pack: owamp-test

An OWAMP-Test packet in unauthenticated mode (RFC 4656 section 4.1.2), which is also the TWAMP-Test packet a Session-Sender sends (RFC 5357 section 4.1.2). Wire `bits`, `layout sequential`, most significant bit first,
big-endian; the MBZ runs are `pad` lines (read over, written as zero). No kind. Input and output
are hex. Written by `tools/gen/ippm-pack.py` with the other OWAMP, TWAMP and STAMP packs.

A packet is one UDP payload. The direction and the mode (unauthenticated, authenticated) are not
on the wire: they are set up by the control protocol (OWAMP-Control, TWAMP-Control) or by
configuration (STAMP), so each layout is its own pack.

## What is mapped

In order: the sequence number, the timestamp, the error estimate, then the packet padding to the end, octet by octet.

## Shared keys

None. **The timestamps are not `time_ms`.** Each is the NTP format of 64 bits (RFC 5905): seconds
since 1900 and a fraction in units of 2^-32 s (in STAMP, with Z = 1, the PTP format: seconds since
1970 and nanoseconds). A fraction of 2^-32 s is a whole number of milliseconds only when it is 0, so
the time is not exact in `time_ms`; the integer and fractional parts stay raw (`ippm.ts_sec`,
`ippm.ts_frac` and the receive and sender timestamps likewise). The pack carries the error estimate
as its four parts (S, Z, scale, multiplier).

## Not mapped

- Nothing of the base packet.
- Conversion to `stamp-sender`: the sequence number, timestamp and error estimate carry; the SSID is 0 and the padding has no place there.

## Vectors

`tools/gen/ietf-more-vectors.py` builds each packet from its own restatement of the RFCs and
derives `expect` without an engine; see the `source` of each vector.
