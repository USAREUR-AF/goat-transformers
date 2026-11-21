# Pack: ikev2-notify

One IKEv2 payload: the Notify payload (type 41, section 3.10), with its generic header, as `ikev2-message` holds it in a payload's
`ikev2.body` after its header. Wire `bits`, `layout sequential`, most significant bit first. No kind:
the payload's type is in the payload before it, so the caller chooses this pack. Input and output are
hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The generic header (next payload type, critical bit, seven reserved bits, and the payload length: a
`length` block, written on encode, counting the 4-octet header). Then the body. The protocol ID, the SPI size (a `count` line: written from the SPI list), the notify message type, the SPI as octets, and the notification data as octets.

## Shared keys

None of `core` or `track`. The generic payload header (`ikev2.next_payload`, `ikev2.critical`,
`ikev2.payload_reserved`) is the same in every IKEv2 pack and in the items of `ikev2-message`.

## Not mapped

- The notification data by type (cookies, NAT detection hashes, ...) is octets.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: NAT_DETECTION_SOURCE_IP with no SPI; a notification about a 4-octet ESP SPI. One vector (an SPI cut by the payload length, expected `malformed-wire`) was dropped: a count is checked against the bits left (ruling 14 of 0.8) and items that start past the extent read as absent (ruling 7), so it decodes; see the script.
