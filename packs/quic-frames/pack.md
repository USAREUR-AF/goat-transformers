# Pack: quic-frames

The frames of a decrypted QUIC packet payload (RFC 9000 section 19), to the end of the payload, each by
its variable-length frame type. Wire `bits`, `layout sequential`. No kind. Written by
`tools/gen/quic-pack.py`.

## Variable-length integers

A QUIC variable-length integer (RFC 9000 section 16) gives its size in its first two bits (1, 2, 4 or 8
octets). Each is a 2-bit `<name>_size` key and a `switch` on it reading the value in 6, 14, 30 or 62
bits; the size is kept, so a round trip writes the size it read, including a larger one than the value
needs. Where an integer counts what follows (a token, data, a reason phrase, ACK ranges, a parameter
value), each size case holds a `count` line of that width and the counted list, and the count is written
from the list.

## What is mapped

PADDING, PING and HANDSHAKE_DONE (the type alone); ACK (largest acknowledged, delay, range count, first
range, the ranges as gap and length) and ACK with ECN counts; RESET_STREAM; STOP_SENDING; CRYPTO (offset,
data); NEW_TOKEN; STREAM by its OFF, LEN and FIN bits (stream ID, offset when OFF, the data counted when
LEN or to the end of the payload otherwise); MAX_DATA and DATA_BLOCKED; MAX_STREAM_DATA and
STREAM_DATA_BLOCKED; MAX_STREAMS and STREAMS_BLOCKED; NEW_CONNECTION_ID (sequence, retire prior to,
connection ID, stateless reset token); RETIRE_CONNECTION_ID; PATH_CHALLENGE and PATH_RESPONSE;
CONNECTION_CLOSE in both forms (error code, the frame type for the transport form, reason phrase).

## Shared keys

None.

## Not mapped

- **Frames of other types** (extensions): a frame has no length of its
  own, so an unknown type cannot be skipped; such a payload is `no-kind`.
- The packet protection and header that wrap the payload (`quic-long-header`), and the short header.

## Vectors

`tools/gen/quic-vectors.py`, without an engine: PADDING, PING and CRYPTO; ACK with a range; ACK with ECN;
STREAM with OFF and LEN, then STREAM with FIN to the end; the flow-control frames with RESET_STREAM and
STOP_SENDING; the connection ID, path, NEW_TOKEN and HANDSHAKE_DONE frames; both CONNECTION_CLOSE forms; an
unknown type (`no-kind`); a cut CRYPTO frame (`malformed-wire`).
