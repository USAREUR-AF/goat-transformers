# Pack: amqp10-frame

The framing of AMQP 1.0 (OASIS standard, Part 2 sections 2.2 and 2.3): the protocol header, an
empty frame, or a frame with its header and the descriptor of its performative; the rest of the
frame body is kept as octets. Wire `bits`, `layout sequential`, most significant bit first. Input
and output are hex. Licensed under the OASIS notice (PROVENANCE.md). Written by
`tools/gen/messaging-pack.py`.

## What is mapped

| Kind | Chosen by | Read as |
|---|---|---|
| `protocol_header` | the four octets `AMQP` | protocol ID (0 AMQP, 2 TLS, 3 SASL), major, minor, revision |
| `empty_frame` | a frame size of 8 | data offset, type, channel; no body (a heartbeat) |
| `frame` | any other frame | the size (a `length 32 whole` line), data offset, type (0 AMQP, 1 SASL), channel; with a data offset of 2, the described-type marker, the encoding of the descriptor (smallulong or ulong) and the descriptor code: the performative (16 open to 24 close; 64 to 68 the SASL frames); then the rest of the body as octets |

On encode with no recorded kind (an entity built by a library, or converted from another pack),
`protocol_header` is chosen only when `amqp.protocol_id` is present. Otherwise `empty_frame`, which
has no key of its own to require and must stand before `frame` for decode, is chosen: an entity
with a frame body is written as an 8-octet empty frame and the body is dropped. The language has
no `requires` on an absent key, which would let `empty_frame` stand aside when a body is present.
A same-format round trip keeps its kind and is not affected.

A frame whose data offset is not 2 has an extended header of 4 × (offset − 2) octets; the pack
keeps the extended header and the body together as octets.

## Assessment: the performatives are beyond the pack language

The body of a performative is a described list whose fields are encoded by the AMQP type system
(Part 1 section 1.6): each field starts with a constructor octet that chooses its type and width
(null, a uint in 0, 1 or 4 octets, a string of an 8- or 32-bit length, a symbol, a list, a map, an
array, another described type), trailing fields may be omitted, and fields such as an attach's
source and target are themselves described composites. Stating one performative on the `bits`
wire would take a `switch` on every field's constructor, with nested blocks for lists, maps and
arrays and no way to recurse into an arbitrary described value; an encoder could not write back the
choice of width an encoder made. The pack language would need a self-describing type wire (an
`amqp` wire, akin to the CBOR or ASN.1 wires), not more lines. The frame and the performative code
are stated; the fields are kept as octets so a frame round-trips.

## Shared keys

None.

## Vectors

`tools/gen/messaging-vectors.py`, without an engine: the protocol header, an empty frame, an open
frame, a flow frame whose descriptor is a ulong, a SASL frame, a frame with an extended header, and
a truncated frame (`malformed-wire`).
