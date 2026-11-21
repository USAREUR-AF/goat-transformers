# Pack: ikev2-ke

One IKEv2 payload: the Key Exchange payload (type 34, section 3.4), with its generic header, as `ikev2-message` holds it in a payload's
`ikev2.body` after its header. Wire `bits`, `layout sequential`, most significant bit first. No kind:
the payload's type is in the payload before it, so the caller chooses this pack. Input and output are
hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The generic header (next payload type, critical bit, seven reserved bits, and the payload length: a
`length` block, written on encode, counting the 4-octet header). Then the body. The Diffie-Hellman group number, 16 reserved bits, and the key exchange data as octets.

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- The key exchange data is a public value whose size the group gives; it is octets.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: group 19 with 64 octets of data; a payload cut before its end (`malformed-wire`).
