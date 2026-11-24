# Pack: wmbus-frame

A wireless M-Bus link-layer frame, with the CRC blocks removed, as wmbusmeters
parses it. Wire `bits`, `layout sequential`, `bit_order msb`; multi-octet values little-endian.
No kinds. Written by `tools/gen/meter2-pack.py`.

## What is mapped

- **Link layer**: the length (`length 8 bytes`, the octets after it), the C field, the manufacturer, the
  identification number (its octets as hex), the version, the device type, the CI field.
- **CI 0x7A, short transport header**: access number, status, configuration, then the application data.
- **CI 0x72, long transport header**: identification, manufacturer, version, device type, then as the
  short header.
- **CI 0x8C, extended link layer I**: CC, ACC, then the next CI field with the transport headers above.
- Any other CI (0x78 no header, the other ELL and AFL forms, network layer): the rest as octets.

## Shared keys

None.

## Not mapped

- **The link-layer CRCs**: removed before the frame reaches the pack; a frame with them in place is not read correctly.
- **The application data**: octets, because it may be encrypted (the configuration's security mode);
  unencrypted records have the layout `mbus-frame` reads.
- **Configuration extensions** of security modes 7 and 10 (they are at the start of the application data).
- **ELL II to V and AFL** headers.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one frame from its length octet, CRCs removed.

## Vectors

`tools/gen/meter2-vectors.py`, without an engine: a short transport header with one record; a long
transport header with an encrypted block; an ELL I followed by a short header; CI 0x78 as octets; a cut
frame (`malformed-wire`).
