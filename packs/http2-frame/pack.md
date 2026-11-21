# Pack: http2-frame

One HTTP/2 frame (RFC 9113 section 4.1): the 9-octet header and the payload by frame type. Wire `bits`,
`layout sequential`, most significant bit first. No kind: a `switch` on the frame type chooses the
payload. One message is one frame; octets after it are not read. Written by `tools/gen/webframes-pack.py`.

## What is mapped

- **Header**: the payload length (a `length 24 bytes plus -6` block: it counts the payload, which follows
  the type, flags and stream identifier; written on encode), the type, the eight flag bits (PRIORITY,
  PADDED, END_HEADERS, END_STREAM or ACK by name; the unused ones by value), the reserved bit and the
  stream identifier.
- **Payloads**: DATA (pad length when PADDED, data), HEADERS (pad length when PADDED, priority when
  PRIORITY, field block), PRIORITY, RST_STREAM, SETTINGS (identifier and value pairs to the end),
  PUSH_PROMISE (pad length, promised stream, field block), PING (8 octets as hex), GOAWAY (last stream,
  error code, debug data), WINDOW_UPDATE, CONTINUATION (field block); other types as octets.

## Shared keys

None.

## Not mapped

- **Padding**: when PADDED is set the padding sits at the end of the payload, after a list of octets that
  runs to the end, so the data (or field block) and the padding are one list; the pad length says how
  many of its last octets are padding. Needed: a trailer after a `rest` list whose size a field gives.
- **HPACK**: the field block fragments are octets; decompression needs the connection's dynamic table.
- The connection preface (the 24-octet `PRI * HTTP/2.0` string) is not a frame.

## Vectors

`tools/gen/webframes-vectors.py`, without an engine: SETTINGS; a SETTINGS acknowledgement; HEADERS with priority;
padded DATA; PING; GOAWAY; WINDOW_UPDATE; RST_STREAM; PUSH_PROMISE; an unknown type; a cut payload
(`malformed-wire`).
