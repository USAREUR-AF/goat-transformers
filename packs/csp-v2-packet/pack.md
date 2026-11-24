# Pack: csp-v2-packet

A CubeSat Space Protocol 2.x packet: the 48-bit header and the data. CSP has no specification apart from
libcsp, its reference implementation (MIT); the layout is restated from libcsp's `csp_id.c`
(PROVENANCE.md). Wire `bits`, `layout sequential`, most significant bit first (libcsp sends the
header big-endian). No kind: the version is a setting of the network, not a field, so the caller
chooses `csp-v1-packet` or `csp-v2-packet`. Input and output are hex. Written by
`tools/gen/space-more-pack.py`.

## What is mapped

Priority (2 bits), destination (14), source (14), destination port (6), source port (6), and the six flag bits: reserved (0x20), fragmentation, HMAC, 0x04 (not defined in libcsp 2.1), RDP, CRC32. Then the data as octets.

## Shared keys

None of `core` or `track`. Both CSP packs use the `csp` module's keys for the same fields (priority,
source and destination address, ports, flags), so a packet converts between versions; an address
above 31 does not fit a 1.x header (no vector pins the result), and the 1.x reserved flags 0x80 and 0x40 have
no place in 2.x.

## Not mapped

- **The CRC32, HMAC and RDP data** the flags announce are in the data octets: the CRC32 and HMAC
  are trailers after a list that runs to the end. Needed: a trailer after a `rest` list.
- **Interface framing** is below this message; the little-endian 1.x header that libcsp's ZMQ fix-up option writes is not read.

## Vectors

`tools/gen/space-more-vectors.py`, without an engine: a broadcast with the fragmentation flag; to `csp-v1-packet`; a cut header (`malformed-wire`).
