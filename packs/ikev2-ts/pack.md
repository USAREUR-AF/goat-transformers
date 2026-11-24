# Pack: ikev2-ts

One IKEv2 payload: the Traffic Selector payloads (types 44 TSi and 45 TSr, section 3.13), with its generic header, as `ikev2-message` holds it in a payload's
`ikev2.body` after its header. Wire `bits`, `layout sequential`, most significant bit first. No kind:
the payload's type is in the payload before it, so the caller chooses this pack. Input and output are
hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The generic header (next payload type, critical bit, seven reserved bits, and the payload length: a
`length` block, written on encode, counting the 4-octet header). Then the body. The number of traffic selectors (a `count` line: written from the list), 24 reserved bits, and the selectors. Each: TS type, IP protocol ID, selector length (a `length` block counting the 4-octet header), then by the type: for IPv4 (type 7) and IPv6 (type 8) ranges, the start and end port and the start and end address (IPv4 as the 32-bit integers of `inet`, IPv6 as hex); for any other type, the content after the length as octets (RFC 7296 defines the ports for types 7 and 8 only).

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- Selector types other than 7 and 8 are octets after the length.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: an IPv4 range and an IPv6 range; a selector of another type.
