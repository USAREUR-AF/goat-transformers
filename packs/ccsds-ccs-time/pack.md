# Pack: ccsds-ccs-time

The CCSDS Calendar Segmented Time Code (CCSDS 301.0-B-4, Time Code Formats,
sections 3.1 and 3.4) with an explicit P-field: year, month and day of month or
day of year, hour, minute, second and 0 to 6 subsecond octets, every segment in
binary coded decimal. Public. Hand-written from the Blue Book; I/O is hex text.
Needs engine version 0.7 (a counted `bits` group).

Uses the modules `core` and `ccsdstime` (`model/ccsdstime.def`).

## Message convention

A message of this pack is one time code: the P-field octet and the T-field.
Octets after the T-field are read over and not written (vector 04).

## Addressing

`word_bytes 1`, `bit_order msb`; bit 0 is the first transmitted bit.

| Bits | Field | Model key | Note |
|---|---|---|---|
| 0 | P-field extension | common `when 0:0:1 0` | |
| 1-3 | time code identification | common `when 0:1:3 5` | `101` |
| 4 | calendar variation | the kind | |
| 5-7 | resolution | `ccsdstime.ccs_resolution` | the number of subsecond octets; also the count of the list |
| 8-23 | year | `ccsdstime.ccs_year` | 4 BCD digits |
| 24-31 / 32-39 (month-day) | month, day of month | `ccsdstime.ccs_month`, `ccsdstime.ccs_day_of_month` | 2 BCD digits each |
| 24-39 (day-of-year) | day of year | `ccsdstime.ccs_day_of_year` | 3 BCD digits, the top 4 bits 0 |
| 40-47 | hour | `ccsdstime.ccs_hour` | |
| 48-55 | minute | `ccsdstime.ccs_minute` | |
| 56-63 | second | `ccsdstime.ccs_second` | 60 in a leap second |
| 64 on, 8 each | subsecond octets | list `ccsdstime.ccs_subseconds`, item key `ccsdstime.ccs_subsecond_digits` | `group … item 8 count 0:5:3` |

`word_bytes 1`, `bit_order msb`. Each segment is carried as the integer of its
bits: a BCD value reads as its hexadecimal digits, so year 2026 is `0x2026`
(8230). The resolution is both a field and the count of the subsecond list
(ruling 2 of 0.7). Resolution 7, which section 3.4.2 marks as not used, reads
7 octets; the pack does not check the digits.

## Kinds

| Kind | `when` | Requires |
|---|---|---|
| `month-day` | bit 4 = 0 | `ccsdstime.ccs_month` |
| `day-of-year` | bit 4 = 1 | `ccsdstime.ccs_day_of_year` |

## Shared keys

None. Section 3.4.1 makes both variations UTC-based, so the code is the scale
of `time_ms`, but two features are missing to state it:

1. A transform that reads binary coded decimal: each 4 bits one decimal digit.
   `uint` gives the hexadecimal value (0x2026), and no transform or derive
   turns that into 2026.
2. A derive that turns calendar parts (year, month, day or day of year, hour,
   minute, second, fraction) into milliseconds since 1970. The 0.16 derives
   combine seconds and nanoseconds (`ms_of`), not a calendar date, and the
   `iso8601_ms` transform reads text, not separate fields.

Candidates for the language: a `bcd` transform on `bits`, and an `ms_of_date`
derive (year, month, day, hour, minute, second, milliseconds; and a
day-of-year form). A leap second (second 60) would also need a stated rule, as
in `ccsds-cds-time`.

## Not mapped

| Part | Why |
|---|---|
| `time_ms` | see Shared keys |
| An implicit P-field | the code's form is agreed outside the message |

## Vectors

`vectors/*.json`, written by `tools/gen/ccsds-3-vectors.py` from its own layout
table: a month-day code to microseconds, a day-of-year code to the second, a
leap second (23:59:60.50), a day-of-year code at its largest digits with
resolution 6, a code cut inside its subsecond octets (`malformed-wire`) and a
CDS code ID (`no-kind`).
