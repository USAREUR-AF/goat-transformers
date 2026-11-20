# Pack: stamp-reflector

A STAMP Session-Reflector test packet in unauthenticated mode (RFC 8762 section 4.3.1), with the SSID of RFC 8972. Wire `bits`, `layout sequential`, most significant bit first,
big-endian; the MBZ runs are `pad` lines (read over, written as zero). No kind. Input and output
are hex. Written by `tools/gen/ippm-pack.py` with the other OWAMP, TWAMP and STAMP packs.

A packet is one UDP payload. The direction and the mode (unauthenticated, authenticated) are not
on the wire: they are set up by the control protocol (OWAMP-Control, TWAMP-Control) or by
configuration (STAMP), so each layout is its own pack.

## What is mapped

In order: the sequence number, timestamp, error estimate, SSID, the receive timestamp, the session-sender's sequence number, timestamp and error estimate, 2 MBZ octets, the TTL, 3 MBZ octets, then the TLVs.

**STAMP TLVs** (RFC 8972 section 4): the flags U, M and I and five reserved bits, the type, the
length of the value, and the value by type: timestamp information (3: synchronization sources and
timestamping methods in and out), class of service (4: DSCP1, DSCP2, ECN, RP), direct measurement
(5: the three counters), access report (6: identifier and return code), follow-up telemetry (7:
sequence number, timestamp, mode). Extra padding (1), location (2, with its sub-TLVs), HMAC (8)
and every other type are kept as octets.

## Shared keys

None. **The timestamps are not `time_ms`.** Each is the NTP format of 64 bits (RFC 5905): seconds
since 1900 and a fraction in units of 2^-32 s (in STAMP, with Z = 1, the PTP format: seconds since
1970 and nanoseconds). A fraction of 2^-32 s is a whole number of milliseconds only when it is 0, so
the time is not exact in `time_ms`; the integer and fractional parts stay raw (`ippm.ts_sec`,
`ippm.ts_frac` and the receive and sender timestamps likewise). The pack carries the error estimate
as its four parts (S, Z, scale, multiplier).

## Not mapped

- Nothing of the base packet.
- TLV values of the types kept as octets. A Location TLV's sub-TLVs are not laid out.

## Vectors

`tools/gen/ietf-more-vectors.py` builds each packet from its own restatement of the RFCs and
derives `expect` without an engine; see the `source` of each vector.
