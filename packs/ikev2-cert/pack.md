# Pack: ikev2-cert

One IKEv2 payload: the Certificate and Certificate Request payloads (types 37 and 38, sections 3.6 and 3.7, which have the same layout), with its generic header, as `ikev2-message` holds it in a payload's
`ikev2.body` after its header. Wire `bits`, `layout sequential`, most significant bit first. No kind:
the payload's type is in the payload before it, so the caller chooses this pack. Input and output are
hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The generic header (next payload type, critical bit, seven reserved bits, and the payload length: a
`length` block, written on encode, counting the 4-octet header). Then the body. The certificate encoding and the data as octets (a certificate, a hash and URL, or the concatenated hashes of certification authorities).

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- The certificate itself (DER) is octets.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: a certificate of encoding 4; a certificate request with one 20-octet hash.
