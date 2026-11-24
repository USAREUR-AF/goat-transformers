# Pack: mbus-frame

A wired M-Bus frame (EN 13757-2 link layer, EN 13757-3 application layer). Wire `bits`, `layout
sequential`, `bit_order msb`; multi-octet values are little-endian (`swap`). Kinds by the start
character: `ack` (0xE5), `short` (0x10), `long` (0x68, the control and long frames). Written by
`tools/gen/meter2-pack.py`.

## What is mapped

- **Short frame**: the control field (reserved bit, PRM, FCB or ACD, FCV or DFC, function), the
  address, the checksum, the stop character.
- **Control and long frames**: the length (a `length 8 bytes plus -2` block: it counts C to the last
  data octet, and the block also holds the repeated length and the second start character), the
  repeated length as sent, the control field, the address, the CI field, the data, the checksum, the
  stop character.
- **CI 0x72 and 0x76, variable data**: the header (identification as its octets in hex, manufacturer,
  version, medium, access number, status, signature) and the records: DIF (extension bit, storage LSB,
  function, data coding), the DIFEs (unit, tariff, storage), VIF and VIFEs, a plain-text VIF's text, and
  the value by the data coding (integers of 1 to 8 octets, a 32-bit real, BCD as hex, a variable-length
  value as octets). DIF 0x2F is an idle filler (an item with no more octets); DIF 0x0F and 0x1F take the
  manufacturer data to the end.
- **CI 0x73 and 0x77, fixed data**: identification, access number, status, the two type octets and the
  two counters (as hex).
- Any other CI: the data as octets.

## Shared keys

None.

## Not mapped

- **The checksum computed**: kept as sent; a changed frame is not re-checksummed.
- **The repeated length checked**: kept as sent.
- **Values decoded**: integers are unsigned here (the source decodes them as signed), BCD stays as its octets
  in hex (low octet first), the VIF's unit and multiplier are not applied, the manufacturer code is not
  turned into its three letters, and the identification number is its octets in hex, low octet first.
- **LVAR above 0xBF** (BCD, binary and other variable codings): read as a character count, so wrong.
- **DIF data coding 8** (selection for readout): no value, as in the source.
- **More than one frame of records** (DIF 0x1F): the frames are separate messages.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one frame, start to stop character.

## Vectors

`tools/gen/meter2-vectors.py`, without an engine: an ACK; a REQ_UD2 short frame; a control frame
(application reset); a variable data response with five records and two fillers; a plain-text VIF with a
variable-length value and manufacturer data; a fixed data response; another start character
(`no-kind`); a cut long frame (`malformed-wire`).
