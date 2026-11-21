# Pack: dstar-radio-header

The 41-octet D-STAR radio header (after descrambling and deinterleaving): three flag octets, the RPT2,
RPT1, YOUR and MY callsigns (8 characters each), the MY suffix (4 characters) and the checksum. Wire `bits`,
`layout sequential`, `bit_order msb`. Written by `tools/gen/hamdig-pack.py`.

## What is mapped

- **Flag 1**: data, repeater, interrupted, control signal, urgent, and the 3-bit repeater control value.
- **Flags 2 and 3**: whole octets.
- **Callsigns**: `chars:ascii8`, space padding kept as sent.
- **Checksum**: as sent, as hex.

## Shared keys

None.

## Not mapped

- **The checksum computed** (CRC-CCITT over the 39 octets): as sent.
- **Coding** (convolutional coding, interleaving, scrambling of the 660-bit header): below this pack.
- **The network forms** of the header (DExtra, D-Plus, DCS, G2 packets), which wrap the same 41 octets.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the 41 octets.

## Vectors

`tools/gen/hamdig-vectors.py`, without an engine: a call through a repeater; a direct header with the
repeater-control value 7; a cut header (`malformed-wire`).
