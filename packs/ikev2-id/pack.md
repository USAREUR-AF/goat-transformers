# Pack: ikev2-id

One IKEv2 payload: the Identification payloads (types 35 IDi and 36 IDr, section 3.5), with its generic header, as `ikev2-message` holds it in a payload's
`ikev2.body` after its header. Wire `bits`, `layout sequential`, most significant bit first. No kind:
the payload's type is in the payload before it, so the caller chooses this pack. Input and output are
hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The generic header (next payload type, critical bit, seven reserved bits, and the payload length: a
`length` block, written on encode, counting the 4-octet header). Then the body. The ID type, 24 reserved bits, then by the type: an IPv4 address (type 1, the 32-bit integer as in `inet`), an IPv6 address (type 5, hex), or the identification data as octets (FQDN, RFC 822 address, DER distinguished name or general name, key ID).

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- FQDN and RFC 822 identities are octets, not text: the `bits` wire has no text transform whose length the end of an extent gives.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: an IPv4 identity; an FQDN identity; an IPv6 identity.
