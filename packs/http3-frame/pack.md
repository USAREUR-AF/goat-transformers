# Pack: http3-frame

One HTTP/3 frame (RFC 9114 section 7): the type and length as QUIC variable-length integers, then the
payload by type. Wire `bits`, `layout sequential`. No kind. One message is one frame, to the end of the
input. Written by `tools/gen/webframes-pack.py`.

## How a variable-length integer is read

A QUIC variable-length integer (RFC 9000 section 16) gives its size in its first two bits (1, 2, 4 or 8
octets). The pack reads those two bits as a field (`<name>_size`) and a `switch` on it reads the value
in 6, 14, 30 or 62 bits. The size is kept, so a round trip writes the same size, including a value
written in more octets than it needs; a conversion from a format without the size writes the one-octet
size (0) unless it is given.

## What is mapped

Type and length; DATA (octets), HEADERS (the QPACK field section as octets), CANCEL_PUSH, GOAWAY and
MAX_PUSH_ID (one integer), SETTINGS (identifier and value integers to the end), PUSH_PROMISE (push ID,
field section); other types as octets.

## Shared keys

None.

## Not mapped

- **The frame length as an extent**: the length is a variable-length integer, which is read as a value;
  a `length` block takes a fixed-width length. So the payload runs to the end of the input, and the length
  is carried, not computed: the caller passes one frame. Needed: a variable-length integer transform
  usable as a length.
- **Choosing the size on encode**: a value is written in the size its key gives, not the smallest that
  holds it.
- QPACK decoding; the stream-type prefixes of unidirectional streams.

## Vectors

`tools/gen/webframes-vectors.py`, without an engine: SETTINGS with integers of three sizes; DATA; HEADERS;
GOAWAY with a two-octet ID; a type in an eight-octet integer; a cut integer (`malformed-wire`).
