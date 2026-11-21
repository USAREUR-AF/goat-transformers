# Pack: dmr-data-header

The 12-octet DMR data header after BPTC (196,96) decoding: octet 0 (group, response requested, two bits,
data packet format), octet 1, the 24-bit destination and source IDs, octets 8 and 9 by format, and the
16-bit CRC. Wire `bits`, `layout sequential`, `bit_order msb`. Written by `tools/gen/hamdig-pack.py`.

## What is mapped

By the data packet format, the fields MMDVMHost reads:

- 2 unconfirmed: full message, blocks to follow, octet 9.
- 3 confirmed: full message, blocks, resync, send sequence, the low nibble of octet 9.
- 1 response: blocks.
- 13 defined short, 14 raw or status/precoded short: resync and full message in octet 8 (the block
  count is octet 0 bits 5-4 plus octet 1's low nibble, as the source adds them).
- 0 UDT: blocks to follow minus one.
- 15 proprietary and others: octets 8 and 9 as hex.

## Shared keys

None.

## Not mapped

- **SAP, header compression and the other octet 1 and octet 9 fields** the source does not name: kept as
  nibbles or octets.
- **The CRC computed** (CCITT with the data-header mask): as sent.
- **BPTC decoding**, the data blocks, the voice and CSBK bursts: below or beside this pack.
- **Proprietary headers**: octets 2 to 7 are read as the two IDs, which is not their meaning there.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the 12 octets.

## Vectors

`tools/gen/hamdig-vectors.py`, without an engine: unconfirmed data to a talkgroup; confirmed individual data;
a UDT header; a proprietary header; a cut header (`malformed-wire`).
