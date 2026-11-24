# Pack: hl7v2-segment

One HL7 version 2 segment line: the MSH, PID or OBX segment, its fields split at `|`. Wire `text`,
`delimiter "|"`. Kinds by field 0: `msh`, `pid`, `obx`. Field numbers and names are those of HL7 v2.5 as
hl7apy lists them. Written by `tools/gen/health-pack.py`.

## Message convention

One message is one segment line, without its CR terminator; a whole HL7 message is several lines, one
per segment. In MSH the field separator `|` is itself MSH-1, so the text after `MSH|` is MSH-2 (the
encoding characters), and MSH-n is the n-1th field of the line. Every field is marked
`optional`, so a line is written back without trailing separators.

## What is mapped

- **MSH**: MSH-2 to MSH-21 (sending and receiving application and facility, date and time of message,
  message type, control ID, processing ID, version, and the rest).
- **PID**: PID-1 to PID-39 (identifiers, name, date of birth, sex, address and the rest).
- **OBX**: OBX-1 to OBX-19 (set ID, value type, observation identifier, sub-ID, value, units, reference
  range, abnormal flags, result status, observation time and the rest).
- Each field is its text, with the component (`^`), repetition (`~`), subcomponent (`&`) and escape (`\`)
  characters left in it. A field beyond the last mapped one is kept as residue.

## Shared keys

None. A patient record has no `core` meaning, and HL7 v2 data is personal health information: the pack
maps it as text and nothing more.

## Not mapped

- **Components** (`^`), repetitions (`~`) and escapes: a field is not split further (the text wire splits
  at one delimiter); `PATIENT_NAME` is `DOE^JOHN`, not two keys.
- **The other segments** (EVN, PV1, ORC, OBR, NTE, AL1 and the rest): `no-kind`.
- **Characters outside printable ASCII** (non-ASCII names in another character set): the text wire refuses
  them (`malformed-wire`).
- **Data types**: text.
- **Message structure** (which segments follow which).

## Vectors

`tools/gen/health-vectors.py`, without an engine: an MSH; a PID; a numeric OBX; an OBX whose value holds a
repetition separator; an EVN line (`no-kind`).
