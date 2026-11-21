# Pack: ikev2-sa

One IKEv2 payload: the Security Association payload (type 33, section 3.3), with its generic header, as `ikev2-message` holds it in a payload's
`ikev2.body` after its header. Wire `bits`, `layout sequential`, most significant bit first. No kind:
the payload's type is in the payload before it, so the caller chooses this pack. Input and output are
hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The generic header (next payload type, critical bit, seven reserved bits, and the payload length: a
`length` block, written on encode, counting the 4-octet header). Then the body. The proposals to the end of the payload. Each: last-substructure value (0 last, 2 more), reserved octet, proposal length (a `length` block counting the 4-octet header), proposal number, protocol ID, the SPI size and the number of transforms (`count` lines, both before both lists: written from the lists), the SPI as octets, and the transforms. Each transform: last-substructure value (0 last, 3 more), reserved, length, transform type, reserved, transform ID, and the attributes to the end of the transform: the AF bit and attribute type, then the two-octet value (AF 1) or a 16-bit length and the value as octets (AF 0).

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- The last-substructure values are carried as written; the end of each list is its extent.
- The meaning of transform IDs (by type) and attribute values.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: one IKE proposal with three transforms and a key length attribute; two ESP proposals with a 4-octet SPI; an attribute in the long form; a payload cut inside its proposal (`malformed-wire`).
