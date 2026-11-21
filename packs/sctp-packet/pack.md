# Pack: sctp-packet

An SCTP packet (RFC 9260): the common header and its chunks. Wire `bits`, `layout sequential`,
most significant bit first, big-endian. No kind. Input and output are hex. Written by
`tools/gen/telecom-pack.py`.

## What is mapped

The common header (section 3.1) on the same `inet` keys as `sctp-common-header` (source and
destination port, verification tag, checksum), so the two convert. Each chunk is an item of
`sctp.chunks`: its type, its flags as one octet, its length (a `length 16 bytes plus 4` block: the
length counts the 4-octet header, not the padding), the body by type, then padding to 4 octets:

| Type | Chunk | Body |
|---|---|---|
| 0 | DATA | TSN, stream identifier, stream sequence number, payload protocol identifier, the user data as octets |
| 1, 2 | INIT, INIT ACK | initiate tag, receiver window, outbound and inbound streams, initial TSN, parameters |
| 3 | SACK | cumulative TSN ack, receiver window, the gap blocks and duplicate TSNs (two `count` lines before their lists) |
| 4, 5 | HEARTBEAT, HEARTBEAT ACK | parameters (heartbeat information as octets) |
| 6, 9 | ABORT, ERROR | error causes |
| 7 | SHUTDOWN | cumulative TSN ack |
| 10 | COOKIE ECHO | the cookie as octets |
| 8, 11, 14 | SHUTDOWN ACK, COOKIE ACK, SHUTDOWN COMPLETE | nothing |
| any other | | the value as octets |

Parameters and error causes are type-length-value items padded to 4 octets: IPv4 address (5),
IPv6 address (6, `hex`), cookie preservative (9), supported address types (12) are laid out, state
cookie (7), unrecognized parameter (8), host name and others as octets; the causes invalid stream
identifier (1), stale cookie (3) and no user data (9) are laid out, the others as octets.

## Shared keys

The ports are `inet.src_port` and `inet.dst_port`, shared with the UDP, TCP and SCTP header packs.
No `core` or `track` key.

## Not mapped

- The checksum is carried, not computed or checked (CRC32c).
- The flag bits are one octet, not named bits (DATA's I, U, B, E; ABORT's and SHUTDOWN COMPLETE's T).
- Chunks of extensions (FORWARD TSN, AUTH, ASCONF, RE-CONFIG, PAD and others) are octets.

## Vectors

`tools/gen/telecom-vectors.py`, without an engine: INIT, INIT ACK, DATA bundled with SACK,
HEARTBEAT and its ACK, ABORT with three causes, a packet of COOKIE ECHO, COOKIE ACK, ERROR,
SHUTDOWN, SHUTDOWN ACK and SHUTDOWN COMPLETE, an unknown chunk, a truncated packet
(`malformed-wire`), a conversion to `sctp-common-header`, and under
`packs/sctp-common-header/vectors` one from it.
