# Pack: dlms-hdlc-frame

A DLMS/COSEM HDLC frame. Wire `bits`, `layout
sequential`, `bit_order msb`. One kind, `hdlc`, chosen by the opening flag. HDLC framing only: the COSEM
APDU stays octets. Written by `tools/gen/meter2-pack.py`.

## What is mapped

- **Flags**: 0x7E at both ends.
- **Frame format**: the type (0xA), the segmentation bit and the 11-bit length (a `length 11 bytes plus
  2` block: the length counts the frame format field to the frame check).
- **Addresses**: the destination and the source, each of 1, 2 or 4 octets, read octet by octet (the
  upper 7 bits and the low bit that marks the last).
- **Control field**, then the 16-bit check that follows it, then the information field and the frame
  check as octets.

## Shared keys

None.

## Not mapped

- **The header and frame checks computed**: kept as sent.
- **The header check told from the frame check**: a frame with an information field carries the header
  check after the control field and the frame check at the end; a frame without one carries only the
  frame check there. The pack reads the 16 bits after the control field as `header_check` either way
  and leaves the information with the final check as octets; the end of the information is not stated
  apart from its last two octets.
- **The address value**: the parts are kept; the source combines them into one number.
- **The control field decoded** (sequence numbers, poll/final, frame kind), the LLC header and the APDU.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one frame, flag to flag.

## Vectors

`tools/gen/meter2-vectors.py`, without an engine: an SNRM without information; an I frame to a
four-octet server address; a segment to a two-octet address; no opening flag (`no-kind`); a cut frame
(`malformed-wire`).
