# Pack: ax25-frame

An AX.25 frame (TAPR AX.25 v2.2, July 1998, sections 3 and 4): the address field, the control field
(modulo 8), the PID and the information field. The message is the frame between the flags, after
bit-stuffing is undone, without the frame-check sequence: the form a KISS data frame carries. Wire
`bits`, `layout sequential`, most significant bit first within each octet (the octet values as a
host holds them; the radio sends each octet least significant bit first). No kind. Input and output
are hex. Written by `tools/gen/radio-pack.py`. Labelled `LicenseRef-unstated` (PROVENANCE.md).

## What is mapped

- **Addresses**: destination, source, and up to eight repeaters. Each is six callsign characters
  (each a 7-bit ASCII character shifted one bit left; one field per character, so `dest_call_1` to
  `dest_call_6`, a space where the callsign is shorter) and the SSID octet: the C bit (destination
  and source) or H bit (repeaters), two reserved bits, the SSID, and the extension bit.
- **The repeater chain** ends at the address whose extension bit is 1. A list cannot end on a bit
  inside its item, so each repeater is a `switch` on the previous address's extension bit, nested
  eight deep. Version 2.2 allows two repeaters; the pack reads up to eight. A ninth is `no-kind`.
- **Control**: the whole octet. The frame type (I, S, U) is in its low bits, read after the bits
  that hold N(R), P/F and N(S), so the layout after it is a `switch` on the octet's value: I frames
  (every even value) and UI (0x03, 0x13) have a PID and an information field; XID, TEST and FRMR
  (0xAF, 0xBF, 0xE3, 0xF3, 0x87, 0x97) have an information field; S frames and the other U frames
  have neither.
- **PID** and the **information field** (octets).

## Shared keys

None.

## Not mapped

- **N(R), N(S), P/F and the S and U frame types** are not separate keys: they are bits of the
  control octet, and the pack must read the whole octet to choose the layout. Needed: sub-fields of an
  earlier field, or a switch on bits not yet consumed.
- **The callsign as one text**: the characters are not contiguous (each is followed by a bit), so
  each is a key. Needed: a character set with a gap bit, or a join of keys without a separator.
- **Modulo 128** control fields (two octets) depend on the connection's state, not on the frame.
- **XID parameters** and the **FRMR** fields are octets; the layer 3 behind a PID is octets.
- Flags, bit stuffing and the FCS are below this message.

## Vectors

`tools/gen/radio-vectors.py`, without an engine: a UI frame; a UI frame through two repeaters; an I
frame; an RR response; a SABM; a TEST frame; eight repeaters; nine repeaters (`no-kind`); a cut
address (`malformed-wire`).
