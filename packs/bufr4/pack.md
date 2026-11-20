# bufr4

One BUFR edition 4 message (WMO FM 94 BUFR, Manual on Codes WMO-No. 306 Volume I.2). Wire
`bits`, `layout sequential`, `bit_order msb`; I/O is hex text. Written by hand from the ecCodes
BUFR section definitions (Apache-2.0), with the WMO BUFR edition 4 tables (wmo-im/BUFR4, MIT) for
the codes the module names; vectors by `tools/gen/wmo-vectors.py`. Licence: Apache-2.0.

## Layout

| Part | Lines |
|---|---|
| section 0 | common lines: `when` "BUFR", `length 24 whole`, `when` edition 4 |
| section 1 | `length 24 bytes plus 3`: master table, centre, sub-centre, update sequence number, the flag of section 2 and the other flag bits, data category and sub-categories, table versions, the typical time as year, month, day, hour, minute, second; local octets after them |
| section 2 | present when the flag of section 1 is 1 (`switch bufr4.optional_section`): reserved octet, the local data as octets |
| section 3 | number of subsets, observed and compressed flags, the descriptors as F (2 bits), X (6), Y (8) |
| section 4 | reserved octet, the data as octets |
| section 5 | `const 32` "7777": written on encode, not checked on decode (a `when` must stand at the start of a kind) |

## The data section: assessment

Section 4 holds the values the descriptors of section 3 describe, packed without separators: an
element descriptor (F = 0) takes the width, scale and reference value its Table B entry gives; a
sequence descriptor (F = 3) expands into the descriptors of its Table D entry, recursively; a
replication descriptor (F = 1) repeats the next descriptors a number of times stated in the
descriptor or in the data; operators (F = 2) change widths, scales and references for the
descriptors after them; compressed data stores each element for all subsets together, with a
minimum and an increment width. The layout of section 4 is therefore computed at run time from
the descriptors and the tables (in wmo-im/BUFR4, Table B has 1,897 entries and Table D 1,054 sequences).

The pack language states layouts in the pack: no line reads a width or a scale from a table
chosen by a value of the message, and no group's body is chosen by a table lookup. So section 4
stays octets. Reading it needs one of:

- a table-driven layout feature (a descriptor list expanded through tables held as data), or
- a pack per fixed descriptor sequence: a message whose section 3 holds exactly one known Table D
  sequence (for example a SYNOP or TEMP template) has a fixed section 4 layout, which a generator
  could expand from wmo-im/BUFR4 Tables B and D into fields, as long as no delayed replication
  occurs (delayed replication counts come from the data, which `count` groups can read where the
  count precedes the items). That is a candidate follow-up, per template.

## Shared-model keys: none, and why

The typical time is six fields with no date-composition `derive` (as in grib2). Positions are in
section 4, which is not read.

## Not mapped

- Section 4's values (above).
- BUFR editions 2 and 3: section 1 differs; `no-kind`.
- A file of several messages: one vector is one message.

## Vectors

| File | Shows |
|---|---|
| `01-message-roundtrip.json` | a message without section 2, two descriptors, data kept as octets |
| `02-optional-section-roundtrip.json` | section 2 present, local octets in section 1, compressed data of two subsets |
| `03-edition-3-is-no-kind.json` | edition 3: `no-kind` |
