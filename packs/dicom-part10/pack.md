# Pack: dicom-part10

A DICOM Part 10 file whose data set is encoded explicit VR little endian: the 128-octet preamble, the
`DICM` prefix and the data elements in order. Wire `bits`, `layout sequential`, `bit_order lsb`. The
preamble is a common line; the kind `part10` is chosen by `DICM`. Written by `tools/gen/health-pack.py`.

## What is mapped

- **Preamble**: 128 octets as hex.
- **Data elements** (a `rest` list): group and element, the two-letter VR, and the value in a length
  block: a 16-bit length for AE, AS, AT, CS, DA, DS, DT, FL, FD, IS, LO, LT, PN, SH, SL, SS, ST, TM, UI,
  UL and US; two reserved octets and a 32-bit length for the others (OB, OD, OF, OL, OV, OW, SQ, SV, UC,
  UN, UR, UT, UV). The value is octets.

## Shared keys

None. DICOM files hold personal health information; the pack keeps values as octets.

## Not mapped

- **Undefined lengths** (0xFFFFFFFF, used for sequences and encapsulated pixel data): the length block
  would read four gigaoctets; such a file is `malformed-wire`. Sequence items and their delimiters
  (FFFE,E000 / E00D / E0DD, which have no VR) are not read.
- **Other transfer syntaxes**: implicit VR little endian and explicit VR big endian data sets after the
  file meta group are read as explicit little endian, which is wrong for them.
- **Values by VR** (text, numbers, dates, UIDs): octets, as a character field that fills its length block
  is not in the pack language.
- **The tag dictionary** (names for group and element): numbers.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the whole file.

## Vectors

`tools/gen/health-vectors.py`, without an engine: a file with the meta group length, transfer syntax, patient
name, rows and OW pixel data; a file with CS, FD and UC elements (both length forms); a wrong prefix
(`no-kind`); a cut element (`malformed-wire`).
