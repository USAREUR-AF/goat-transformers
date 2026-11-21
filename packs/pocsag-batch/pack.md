# Pack: pocsag-batch

A POCSAG batch (Rec. ITU-R M.584-2, Annex 1, radio-paging code No. 1): the synchronization codeword
0x7CD215D8, then the codewords to the end of the message (16 in a batch: 8 frames of 2). Wire `bits`,
`layout sequential`, most significant bit first (each codeword is sent most significant bit first).
One kind, `batch`, whose `when` is the synchronization codeword. Input and output are hex, the
codewords as 32-bit words without the preamble. Written by `tools/gen/radio-pack.py`. Labelled
`LicenseRef-unstated` (PROVENANCE.md).

## What is mapped

Each codeword: the flag bit; for an address codeword (flag 0) the 18 address bits and the 2 function
bits; for a message codeword (flag 1) the 20 message bits as hex; then the 10 BCH check bits and the
even parity bit, as on the wire. The idle codeword (0x7A89C197) is an address codeword and reads as
one.

## Shared keys

None.

## Not mapped

- **The pager identity**: an address codeword holds the identity's 18 high bits; the 3 low bits are
  the number of the frame it is sent in (its place in the batch divided by 2), which is not a field.
- **The message text**: numeric (4-bit digits) and alphanumeric (7-bit characters) messages are sent
  least significant bit first and run across codewords, around the check bits; the message bits are
  hex per codeword. Needed: a list's bits joined across items, with a character set read low bit
  first.
- **The check bits** are carried, not computed or verified (BCH(31,21) and even parity).
- **Several batches** are several messages: each batch begins with its synchronization codeword; the
  preamble is not part of the message.

## Vectors

`tools/gen/radio-vectors.py`, without an engine, with check bits computed from the Recommendation's
generator polynomial (the encoder reproduces the idle codeword): a numeric page; an idle batch; an
address with function 3 and two message codewords; no synchronization codeword (`no-kind`); a cut
codeword (`malformed-wire`).
