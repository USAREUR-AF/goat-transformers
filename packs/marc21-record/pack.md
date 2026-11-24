# Pack: marc21-record

One MARC 21 bibliographic record in the ISO 2709 exchange structure. Wire `bits`, `layout sequential`,
`bit_order msb`. Written by `tools/gen/biblio-pack.py`.

## What is mapped

- **Leader** (24 characters): record length, record status, type of record, bibliographic level, type
  of control, character coding scheme, indicator count, subfield code count, base address of data,
  encoding level, descriptive cataloging form, multipart resource record level, and the entry map (4,
  5, 0, 0), each as its characters.
- **Directory**: a `rest` list whose items are the 12-character entries (the tag's first character as
  a code, its other two characters, the field length, the starting position), then one last item that
  begins with the field terminator 0x1E and holds every variable field after it as octets (each field
  ended by 0x1E, the last also by the record terminator 0x1D). The list ends there because that item
  takes the rest of the record.

## Shared keys

None.

## Not mapped

- **Lengths and positions computed**: the record length, base address, field lengths and starting
  positions are the digits as sent.
- **Variable fields by tag**: control fields (00X) and data fields (indicators, subfield code 0x1F and
  data) are octets; reading them needs the directory's lengths applied to the data, and a list that
  ends at a delimiter.
- **The tag as one text**: its first character is kept as a code (the item's first octet chooses
  between an entry and the terminator).
- **MARC-8 text** and the other MARC 21 formats (authority, holdings): the leader positions are those of
  the bibliographic format.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the record's octets.

## Vectors

`tools/gen/biblio-vectors.py`, without an engine (lengths and positions computed there): a book record with
001, 008 and 245; a map record; a cut leader (`malformed-wire`).
