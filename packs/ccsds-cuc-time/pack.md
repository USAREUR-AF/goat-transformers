# Pack: ccsds-cuc-time

The CCSDS Unsegmented Time Code (CCSDS 301.0-B-4, Time Code Formats, sections
3.1 and 3.2) with an explicit one-octet P-field: a count of basic time units
(1 to 4 octets) and a binary fraction of the unit (0 to 3 octets). Public.
Hand-written from the Blue Book; I/O is hex text. Needs engine version 0.17
(gate blocks).

Uses the modules `core` and `ccsdstime` (`model/ccsdstime.def`).

## Message convention

A message of this pack is one time code: the P-field octet and the T-field it
describes. Octets after the T-field are read over and not written (vector 02).
A code sent without its P-field (implicit P-field, its form agreed by other
means) is not this pack's message.

## Addressing

`word_bytes 1`, `bit_order msb`; bit 0 is the first transmitted bit.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0 | P-field extension | common `when 0:0:1 0` | a second P-field octet is not mapped |
| 1-3 | time code identification | the kind | `001` level 1, `010` level 2 |
| 4-5 | coarse octets minus one | `ccsdstime.cuc_coarse_octets` | |
| 6-7 | fine octets | `ccsdstime.cuc_fine_octets` | |
| 8, `8(c+1)` bits | basic time units | `ccsdstime.cuc_coarse` | gate `if 0:4:2 c` |
| next `8f` bits | binary fraction | `ccsdstime.cuc_fine` | nested gate `if 0:6:2 f`, `f` from 1 to 3 |

The places of the two T-field parts follow from bits 4-7: four gate blocks on
the coarse length, each with three nested blocks on the fine length
(engine-spec 0.17). Both lengths are plain fields, so encode writes them first
and the blocks they select follow them. The fraction is the integer of its
octets; its value in units is that integer over 2^(8f).

## Kinds

| Kind | `when` | Epoch |
|---|---|---|
| `level-1` | bits 1-3 = 001 | 1958 January 1, TAI |
| `level-2` | bits 1-3 = 010 | defined by the agency |

Both require `ccsdstime.cuc_coarse`.

## Shared keys

None. `time_ms` is not bound, for either kind:

- Level 1 counts TAI seconds from 1958 January 1 TAI, and section 3.2.1 says
  the code is not UTC-based and leap-second corrections do not apply.
  `time_ms` counts UTC milliseconds from 1970 with no leap seconds. Going from
  one to the other needs TAI - UTC at the instant: an integer count of leap
  seconds that changes at each one announced (37 s since 2017), and before
  1972 a fractional, drifting offset. The pack language has no table of leap
  seconds, so the conversion cannot be stated exactly. Candidate for the
  language: a `tai_to_utc` derive with a leap-second table the caller or a
  module supplies.
- The basic time unit and the octet counts come from mission metadata when the
  P-field is not explicit, and a level 2 epoch is the agency's: neither is
  stated in the message.

## Not mapped

| Part | Why |
|---|---|
| The second P-field octet (extension bit 1) | it adds 0-3 coarse and 0-7 fine octets, up to 7 and 10 in all; the fine part would pass 64 bits, and the gate blocks for every combination of the four length fields would number 512 |
| An implicit P-field | the code's form is agreed outside the message |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-3-vectors.py` from its own layout
table: level 1 with 4 and 2 octets, level 2 with 1 and 0 octets (with octets
after the code), the largest one-octet-P-field code, level 2 with 2 and 1
octets, an extended P-field and a CDS code ID (both `no-kind`), and a code cut
inside its fraction (`malformed-wire`).
