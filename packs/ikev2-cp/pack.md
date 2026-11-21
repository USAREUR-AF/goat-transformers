# Pack: ikev2-cp

One IKEv2 payload: the Configuration payload (type 47, section 3.15), with its generic header, as `ikev2-message` holds it in a payload's
`ikev2.body` after its header. Wire `bits`, `layout sequential`, most significant bit first. No kind:
the payload's type is in the payload before it, so the caller chooses this pack. Input and output are
hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The generic header (next payload type, critical bit, seven reserved bits, and the payload length: a
`length` block, written on encode, counting the 4-octet header). Then the body. The CFG type, 24 reserved bits, and the attributes to the end of the payload: a reserved bit, the attribute type, and the value as octets in the extent of a 16-bit length.

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- Attribute values (addresses, netmasks, subnets) are octets: their layout depends on the attribute type and on the length (a request may send an empty value).

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: a request with two empty attributes; a reply with an address and a DNS server.
