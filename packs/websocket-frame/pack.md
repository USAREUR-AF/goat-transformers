# Pack: websocket-frame

One WebSocket frame (RFC 6455 section 5.2). Wire `bits`, `layout sequential`. No kind. One message is one
frame, to the end of the input. Written by `tools/gen/webframes-pack.py`.

## What is mapped

FIN, RSV1-3, opcode, MASK, the 7-bit payload length and, by its value, the 16-bit (126) or 64-bit (127)
extended length; the masking key when MASK is set (hex); for a close frame (opcode 8) the status code and
reason, or neither when the length is 0 (RFC 6455 section 5.5.1: a close frame MAY contain a body); for any other opcode the payload as octets, as on the wire.

## Shared keys

None.

## Not mapped

- **Unmasking**: a masked payload is the data XORed with the key, repeated; the octets are kept masked.
  A masked close frame's status code is read from masked octets. Needed: an XOR-with-key transform.
- **The payload length as an extent**: the length is carried, not computed; the payload runs to the end
  of the input.
- **A close frame without a body**: RFC 6455 section 5.5.1 allows it; the pack reads the 16-bit status code of
  every close frame, so such a frame is `malformed-wire`.
- Message reassembly from fragments; extensions that use the RSV bits.

## Vectors

`tools/gen/webframes-vectors.py`, without an engine: an unmasked text frame; a masked binary frame; a fragment
with a 16-bit length; a close frame; a ping; a cut length (`malformed-wire`); close frames without a body, unmasked and masked;
a close frame with the status code alone.
