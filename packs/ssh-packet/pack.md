# Pack: ssh-packet

The SSH binary packet (RFC 4253 section 6), as it is before encryption or after decryption: the packet
length, the padding length, the payload and padding, and the MAC. Wire `bits`, `layout sequential`,
big-endian. No kind. One message is one packet. Written by `tools/gen/remote-pack.py`.

## What is mapped

The packet length (a `length 32 bytes` block, written on encode), the padding length, the payload with
the padding after it as one octet list, and the MAC after the packet as octets (empty before keys are
exchanged). The payload is an SSH message: see `ssh-message`.

## Shared keys

None.

## Not mapped

- **Payload apart from padding**: the padding is the last `padding_length` octets of the block, after a
  payload with no length of its own, so the two are one list. Needed: a trailer after a `rest` list whose
  size a field gives.
- **Encrypted packets**: with a cipher the packet length is encrypted too (or, with ChaCha20-Poly1305 and
  the encrypt-then-MAC modes, kept apart); the pack reads plaintext packets. The MAC's size comes from
  the negotiated algorithm; it is the octets after the packet.
- The identification string (`SSH-2.0-...`) that precedes the first packet is a text line.

## Vectors

`tools/gen/remote-vectors.py`, without an engine: an unencrypted packet; the same with a MAC; a cut packet
(`malformed-wire`).
