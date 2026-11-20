# Pack: twamp-reflector-auth

A TWAMP-Test packet of a Session-Reflector in authenticated or encrypted mode (RFC 5357 section 4.2.1). Wire `bits`, `layout sequential`, most significant bit first,
big-endian; the MBZ runs are `pad` lines (read over, written as zero). No kind. Input and output
are hex. Written by `tools/gen/ippm-pack.py` with the other OWAMP, TWAMP and STAMP packs.

A packet is one UDP payload. The direction and the mode (unauthenticated, authenticated) are not
on the wire: they are set up by the control protocol (OWAMP-Control, TWAMP-Control) or by
configuration (STAMP), so each layout is its own pack.

## What is mapped

In order: the fields of the unauthenticated packet, each block separated by the MBZ runs of the authenticated layout, then the 16-octet HMAC and the padding.

## Shared keys

None. **The timestamps are not `time_ms`.** Each is the NTP format of 64 bits (RFC 5905): seconds
since 1900 and a fraction in units of 2^-32 s (in STAMP, with Z = 1, the PTP format: seconds since
1970 and nanoseconds). A fraction of 2^-32 s is a whole number of milliseconds only when it is 0, so
the time is not exact in `time_ms`; the integer and fractional parts stay raw (`ippm.ts_sec`,
`ippm.ts_frac` and the receive and sender timestamps likewise). The pack carries the error estimate
as its four parts (S, Z, scale, multiplier).

## Not mapped

- The HMAC is carried, not computed or checked.
- In encrypted mode the fields before the HMAC are ciphertext.

## Vectors

`tools/gen/ietf-more-vectors.py` builds each packet from its own restatement of the RFCs and
derives `expect` without an engine; see the `source` of each vector.
