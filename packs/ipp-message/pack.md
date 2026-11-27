# Pack: ipp-message

An IPP/1.1 request or response in the binary encoding of RFC 8010 section 3, as carried in the body of an
HTTP POST with the media type application/ipp. Wire `bits`, `layout sequential`, `bit_order msb`, every
integer big-endian and signed (`twos`). No kinds: the encoding has no marker. One message is the IPP body
from the version octets to the end of the document data. Written by `tools/gen/printing-pack.py`.

## What is mapped

- **Header**: major and minor version, the operation-id or status-code (one key: the encoding puts both in
  the same two octets, and only the HTTP direction says which), the request-id.
- **Items** (`ipp.items`, a `rest` list), one per delimiter tag or attribute, in message order. Each item
  begins with its tag octet:
  - 0x00 to 0x0f except 0x03: a begin-attribute-group tag, nothing more;
  - 0x03, the end-of-attributes tag: the document data that follows, as octets (`ipp.data`); since it runs
    to the end of the message, the list ends with it;
  - 0x10 to 0xff, a value tag: the name length block with the name as octets, then the value length block
    with the value read by its tag: integer and enum (0x21, 0x23) a 32-bit signed integer, boolean (0x22)
    one octet, resolution (0x32) cross-feed, feed and units, rangeOfInteger (0x33) lower and upper,
    textWithLanguage and nameWithLanguage (0x35, 0x36) the language and the text, each with its own
    16-bit length. Every other value (the character-string tags, octetString, dateTime, the collection
    tags, the out-of-band tags, the 0x7f extension) is octets (`ipp.value`).
- An additional value is an item whose name is empty, as on the wire.

## Shared keys

None. No IPP field has the meaning and unit of a `core` or `track` key.

## Not mapped

- The version number's two octets are read as unsigned (`uint`). RFC 8010 section 3 types them
  SIGNED-BYTE, so an octet from 0x80 to 0xFF decodes as 128 to 255 where the RFC gives -128 to
  -1. No defined IPP version uses those values; changing the keys' reading would change what
  their stored numbers mean, so it is stated here instead.
- **The end-of-attributes tag as a list terminator.** The attribute list ends at tag 0x03; the pack has no
  list that ends at a value of its first octet. It reads the items as a `rest` list instead and puts the
  document data inside the end-tag item, which reads the same messages and writes them back unchanged. A
  message with no end tag decodes (it is malformed by RFC 8010) rather than failing.
- **Names and string values as text.** A character field that fills its length block is not in the pack
  language (`until:` needs a terminator; a `chars` field has a fixed size), so names and string values are
  lists of octets. Needed: a `chars` field whose size is the rest of its extent.
- **Attributes grouped by name and value**, collections nested: each tag is one flat item, as on the wire.
- **dateTime** (RFC 2579 DateAndTime): octets; the layout is in another document, not read.
- **An integer, boolean, resolution or range value whose length is not the fixed one**: a shorter value
  re-encodes at the full size with zeros (ruling 7 of 0.8, vector 06), a longer one fails.
- **Operation and status code names**, attribute names and their syntaxes (RFC 8011 and the IANA
  registry): the pack keeps the numbers and the octets.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one IPP message body.

## Vectors

`tools/gen/printing-vectors.py`, without an engine: a Get-Printer-Attributes request with an additional
value; a response with enum, boolean, negative integer, resolution, range and an out-of-band value; a
Print-Job with a nameWithLanguage and document data; empty groups; a collection as flat items; an integer
with an empty value (four zero octets added); a cut attribute and a short header (`malformed-wire`).
