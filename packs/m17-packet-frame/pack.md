# Pack: m17-packet-frame

The contents of one M17 Packet Frame as Type 1 bits: a 25-octet chunk of the packet data, the
end-of-frame bit, the 5-bit counter (frame number, or valid octets in the last frame) and 2 reserved bits.
Wire `bits`, `layout sequential`, `bit_order msb`. Written by `tools/gen/hamdig-pack.py`.

## Shared keys

None.

## Not mapped

- **Packet reassembly** and the packet data's own protocol identifier, payload and CRC (they span frames).
- **Coding**: below this pack.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the 26 octets.

## Vectors

`tools/gen/hamdig-vectors.py`, without an engine: a first frame; the last frame with 6 valid octets; a cut
frame (`malformed-wire`).
