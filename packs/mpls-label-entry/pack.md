# Pack: mpls-label-entry

One MPLS label stack entry, as IETF RFC 3032 section 2.1 lays it out, with the
name RFC 5462 gives its 3-bit field: 4 octets, the top of the stack. Public.
Written by hand from the RFCs; the layout is stated in this repository's words.
I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is the label stack and what follows it. The pack reads octets 0-3,
the top entry; further entries and the payload are read over and not written
(vector 04).

| Bits | Field | Key | Transform |
|---|---|---|---|
| 0-19 | label | `inet.mpls_label` | `uint` |
| 20-22 | traffic class (EXP in RFC 3032) | `inet.mpls_tc` | `uint` |
| 23 | bottom of stack | `inet.mpls_bottom_of_stack` | `uint` |
| 24-31 | time to live | `inet.mpls_ttl` | `uint` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. Labels 0-15 are
reserved by RFC 3032; the pack carries them as numbers (vector 03).

## Shared keys

None.

## Not mapped, and why

- The rest of the stack. Its end is the entry whose bottom-of-stack bit is 1.
  A `bits` group can end on a count or on a bit before each item (`while`,
  `more`), not on a bit inside an item. Candidate for the language: a group
  that ends on the item whose given field holds a given value.
- The payload after the stack.

## Vectors

`tools/gen/ietf-headers-2-vectors.py`, from values chosen there: a bottom
entry, every field at its largest value, the reserved label 0, a stack of two
entries (the top one comes back), and 3 octets (`malformed-wire`).
