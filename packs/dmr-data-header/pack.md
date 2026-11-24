# Pack: dmr-data-header

The 12-octet DMR data header after BPTC (196,96) decoding: octet 0 (the source's GI and A, two bits,
data packet format), octet 1, the 24-bit destination and source IDs, octets 8 and 9 by format, and the
16-bit CRC. Wire `bits`, `layout sequential`, `bit_order msb`. Written by `tools/gen/hamdig-pack.py`.

## What is mapped

By the data packet format, the fields MMDVMHost reads:

- 2 unconfirmed: F (`full_message`), blocks to follow, octet 9.
- 3 confirmed: F, blocks, S (`resync`), Ns (`send_sequence`), the low nibble of octet 9.
- 1 response: blocks.
- 13 defined short, 14 raw or status/precoded short: S and F in octet 8 (the block
  count is octet 0 bits 5-4 plus octet 1's low nibble, as the source adds them).
- 0 UDT: blocks to follow minus one.
- 15 proprietary and others: octets 8 and 9 as hex.

## Shared keys

None.

## Not mapped

- **The octet 1 and octet 9 fields** the source does not name: kept as nibbles or octets. The keys `group`,
  `response_requested`, `full_message`, `resync` and `send_sequence` are named beyond what the source
  states: it calls them GI, A, F, S and Ns and does not expand them.
- **The CRC computed** (CCITT with the data-header mask): as sent.
- **BPTC decoding**, the data blocks, the voice and CSBK bursts: below or beside this pack.
- **Proprietary headers**: octets 2 to 7 are read as the two IDs; the source does not read them.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the 12 octets.

## Vectors

`tools/gen/hamdig-vectors.py`, without an engine: unconfirmed data to a talkgroup; confirmed individual data;
a UDT header; a proprietary header; a cut header (`malformed-wire`).
