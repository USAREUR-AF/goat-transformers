# Pack: dcep

A WebRTC Data Channel Establishment Protocol message (RFC 8832), sent on an SCTP stream with payload
protocol identifier 50. Wire `bits`, `layout sequential`, most significant bit first. Two kinds by
the message type: `open` (0x03) and `ack` (0x02). Input and output are hex. Written by
`tools/gen/media-pack.py`.

## What is mapped

**`open`**: channel type, priority, reliability parameter, then the label and the protocol. Their two
lengths both come before both strings, so they are `count` lines (engine-spec 0.21) that count the
octets of the two lists: on encode each length is written from its list.

**`ack`**: nothing after the type.

## Shared keys

None.

## Not mapped

- The label and protocol are lists of UTF-8 octets, not text: the `bits` wire has no text transform
  whose length a field gives.

## Vectors

`tools/gen/media-vectors.py`, without an engine: an open of a reliable channel, an open of a
partially reliable unordered channel, an ack, an unknown type (`no-kind`), a cut label
(`malformed-wire`).
