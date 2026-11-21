# Pack: ikev2-eap

One IKEv2 payload: the EAP payload (type 48, section 3.16): the EAP message header, with its generic header, as `ikev2-message` holds it in a payload's
`ikev2.body` after its header. Wire `bits`, `layout sequential`, most significant bit first. No kind:
the payload's type is in the payload before it, so the caller chooses this pack. Input and output are
hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The generic header (next payload type, critical bit, seven reserved bits, and the payload length: a
`length` block, written on encode, counting the 4-octet header). Then the body. The EAP code and identifier, then for a request or response (codes 1 and 2) the EAP length (a `length` block counting the 4-octet header), the method type and the type data as octets; for a success or failure (codes 3 and 4), which have no type, the EAP length as written.

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- The type data of each EAP method is octets.
- A success or failure is a separate case: a `length` block writes every line on encode (ruling 7 of 0.8), so a block holding the type would write a type octet that a success does not have.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: an identity request; an identity response with type data; a success.
