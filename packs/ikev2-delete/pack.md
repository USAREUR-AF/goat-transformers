# Pack: ikev2-delete

One IKEv2 payload: the Delete payload (type 42, section 3.11), with its generic header, as `ikev2-message` holds it in a payload's
`ikev2.body` after its header. Wire `bits`, `layout sequential`, most significant bit first. No kind:
the payload's type is in the payload before it, so the caller chooses this pack. Input and output are
hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The generic header (next payload type, critical bit, seven reserved bits, and the payload length: a
`length` block, written on encode, counting the 4-octet header). Then the body. The protocol ID and the SPI size, then by the size: for 4 or 8 octets, the number of SPIs (a `count` line: written from the list) and the SPIs, each as hex; for any other size (0 for an IKE SA), the number of SPIs as written and the SPIs as octets.

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- SPIs of sizes other than 4 and 8 are octets: an item's size cannot come from a field outside the list.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: two ESP SPIs; the deletion of the IKE SA; one 8-octet SPI.
