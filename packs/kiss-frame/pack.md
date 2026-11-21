# Pack: kiss-frame

A KISS TNC frame (Chepponis and Karn, 1987, section 4): the type octet and what follows it. The
message is the content between two FEND (0xC0) octets after the escapes are undone (FESC TFEND to
0xC0, FESC TFESC to 0xDB). Wire `bits`, `layout sequential`. No kind. Input and output are hex.
Written by `tools/gen/radio-pack.py`. Labelled `LicenseRef-unstated` (PROVENANCE.md).

## What is mapped

The port (high nibble of the type octet) and the command (low nibble), then by the command: a data
frame (0), its octets (an AX.25 frame without flags and FCS: see `ax25-frame`); TXDELAY, P, SlotTime,
TXtail and FullDuplex (1 to 5), the parameter octet; Return (15, sent as 0xFF), nothing; SetHardware
(6) and any other command, its octets.

## Shared keys

None.

## Not mapped

- **FEND framing and FESC escaping** are byte stuffing: an escape changes the length of what follows,
  which no transform of the `bits` wire expresses. The caller removes the FENDs and undoes the escapes.
  Needed: a byte-stuffing (escape) transform or framing.
- **The AX.25 frame inside a data frame** is octets: a pack cannot hand a field to another pack. Run
  `ax25-frame` on the data.

## Vectors

`tools/gen/radio-vectors.py`, without an engine: data frames on ports 0 and 1; TXDELAY; persistence;
full duplex on port 2; Return; SetHardware; a TXDELAY without its parameter (`malformed-wire`).
