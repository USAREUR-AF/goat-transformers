# Pack: misb-st0102

The Security Metadata Local Set of MISB ST 0102.12: the set of items that
states the security classification, caveats and releasability of motion
imagery data. Public. Written from the document only (PROVENANCE.md). I/O is
hex text (`spec/engine-spec.md`, Version 0.13, the `tlv` wire). Needs engine
version 0.13.

Uses the module `misb0102` (`model/misb0102.def`). The words for
classification levels below are values the document defines for its items;
they are not markings of this pack or of the document.

## Message convention

A message of this pack is one stand-alone Security Metadata Local Set:

1. the 16-byte Universal Label key of the Local Set, section 6.7 of the
   document, `06 0E 2B 34 02 03 01 01 0E 01 03 03 02 00 00 00` (`key`);
2. the length of the rest of the set, BER short or long form (`length ber`);
3. the items, each a one-byte tag, a BER length and the value (`tag 1`).

The document defines no checksum item for this set, so the pack has no
`checksum` line. The document requires the set to follow the KLV encoding
rules of SMPTE ST 336 and does not itself state the tag size. The pack takes a
one-byte tag and a BER length from byte 6 of the key (`0x03`), the value that
SMPTE ST 336 assigns to that form of local set; ST 336 was not read
(PROVENANCE.md), so a reviewer who has it should confirm this. Every tag the
document defines is below 128, where a one-byte tag and a BER-OID tag are the
same byte.

Encode writes the items in `field`-line order, which is tag order, then any
residue. When the entity has no `misb0102.version`, no item 22 is written: a
set without it is read as version 3 (6.1.15), so writing 12 would change what the
set says. The document requires item 22 in every set from version 4 on; an entity
that should be such a set must hold the version.

The same items also travel without the key and length inside item 48 of the
MISB ST 0601 UAS Datalink Local Set. That form is not a message of this pack
(see "Not mapped").

## Mapping

No item has a `core` or `track` key of the same meaning: the shared model has
no key for a security classification, a caveat, a releasability list or a
country coding method. Every item is a raw key of `misb0102`. Sizes `:<n>` are
the document's stated length of the item (Table 2).

| Tag | Item | Key | Transform | Note |
|---|---|---|---|---|
| 1 | Security Classification | `security_classification` | `uint`, 1 byte, `via classification` | the one-byte code read as its Universal Set text (below) |
| 2 | Classifying Country and Releasing Instructions Country Coding Method | `country_coding_method` | `uint`, 1 byte | code list below |
| 3 | Classifying Country | `classifying_country` | `utf8` | two slashes then a country code |
| 4 | SCI/SHI information | `sci_shi_info` | `utf8` | ISO/IEC 646 text |
| 5 | Caveats | `caveats` | `utf8` | ISO/IEC 646 text |
| 6 | Releasing Instructions | `releasing_instructions` | `utf8` | country codes separated by spaces |
| 7 | Classified By | `classified_by` | `utf8` | free text |
| 8 | Derived From | `derived_from` | `utf8` | free text |
| 9 | Classification Reason | `classification_reason` | `utf8` | free text |
| 10 | Declassification Date | `declassification_date` | `utf8` | eight characters, year, month, day; kept as text, not converted to a time |
| 11 | Classification and Marking System | `marking_system` | `utf8` | free text |
| 12 | Object Country Coding Method | `object_country_coding_method` | `uint`, 1 byte | code list below |
| 13 | Object Country Codes | `object_country_codes` | `hex` | UTF-16 in the document; kept as the item's bytes |
| 14 | Classification Comments | `classification_comments` | `utf8` | free text |
| 22 | Version | `version` | `uint`, 2 bytes | unsigned 16-bit; not written when absent |
| 23 | Classifying Country and Releasing Instructions Country Coding Method Version Date | `country_coding_method_date` | `utf8` | ten characters, year-month-day with hyphens |
| 24 | Object Country Coding Method Version Date | `object_country_coding_method_date` | `utf8` | as tag 23 |

### Text items

The document gives the text items as ISO/IEC 646 (7-bit) text. That is a
subset of UTF-8, so `utf8` decodes every conforming value unchanged. Encode
writes the key's text as UTF-8 and does not check that it is 7-bit; a key
holding a character above U+007F gives a set that does not conform.

### Tag 1, the classification table

Section 6.8.1 states that the Local Set carries the classification as an
unsigned integer and the Universal Set as an uppercase string, and that each
converts to the other. The pack's table `classification` makes that
conversion, so the key holds the Universal Set text whichever form a later
pack reads:

| Code | Key value |
|---|---|
| 1 | `UNCLASSIFIED//` |
| 2 | `RESTRICTED//` |
| 3 | `CONFIDENTIAL//` |
| 4 | `SECRET//` |
| 5 | `TOP SECRET//` |

A code outside 1 to 5 is not a value the document allows. Decode of such a set
is `transform-decode` (the table has no entry, and the types differ), and so
is encode of a key value not in the table. The whole set is refused, not only
the item: a reader of security metadata should not pass on a set whose
classification it cannot read.

### Tags 2 and 12, coding methods

The two coding-method items are kept as their integer codes, not through a
table, for two reasons. First, the document's lists have codes it marks as
omitted (8 and 9 in tag 2; 8 to 12 in tag 12), and a table would turn any of
them into a refusal of the whole set. Second, the two lists number the same
methods differently, so one table cannot serve both. The codes, in this
pack's words:

| Code | Tag 2 method | Tag 12 method |
|---|---|---|
| 1 | ISO 3166 two-letter | ISO 3166 two-letter |
| 2 | ISO 3166 three-letter | ISO 3166 three-letter |
| 3 | FIPS 10-4 two-letter | ISO 3166 numeric |
| 4 | FIPS 10-4 four-letter | FIPS 10-4 two-letter |
| 5 | ISO 3166 numeric | FIPS 10-4 four-letter |
| 6 | STANAG 1059 two-letter | STANAG 1059 two-letter |
| 7 | STANAG 1059 three-letter | STANAG 1059 three-letter |
| 8, 9 | omitted | omitted |
| 10 | FIPS 10-4 mixed | omitted |
| 11 | ISO 3166 mixed | omitted |
| 12 | STANAG 1059 mixed | omitted |
| 13 | GENC two-letter | GENC two-letter |
| 14 | GENC three-letter | GENC three-letter |
| 15 | GENC numeric | GENC numeric |
| 16 | GENC mixed | not listed |
| 64 | not listed | GENC administrative subdivision |

## Not mapped, and why

- **The Universal Set.** Section 6.6 defines a second form with its own
  16-byte key, where each item is keyed by a 16-byte Universal Label instead
  of a one-byte tag. The `tlv` wire states tags as BER-OID or fixed 1, 2 or 4
  bytes; it has no 16-byte tag, so the Universal Set cannot be stated in this
  pack language. Its values would map to the same `misb0102` keys (with tag 1,
  2 and 12 as text, section 6.8). Candidate addition: a 16-byte tag on `tlv`,
  or a `tag` form that names Universal Label keys.
- **The set nested in MISB ST 0601.** ST 0601 item 48 holds these items with
  no key and no length of their own. A pack with a `key` line refuses input
  that does not begin with the key, and the `misb-st0601` pack keeps item 48
  as one residue item. Reading the nested form needs either a second pack
  without `key`, or lines in `misb-st0601` on paths `48.<tag>`; neither is in
  this pack.
- **Tag 13 as text.** The document gives Object Country Codes as UTF-16 (RFC
  2781). The wire has no UTF-16 transform, so the value is kept as hex bytes;
  a consumer decodes the text itself. Candidate addition: a `utf16` transform
  on `tlv`.
- **Text checks.** The document's rules on the content of text items (two
  slashes before the classifying country, separators in tags 4, 6 and 13, the
  date patterns of tags 10, 23 and 24) are not checked on decode or encode.
- **Stated lengths.** Tags 1, 2, 10, 12, 22, 23 and 24 have a stated length.
  Decode reads an integer at the length it has (up to 8 bytes) and a text item
  at any length; a value of another length is not refused.
- **Zero-length items.** An empty value is absent for the integer items and
  the empty string for the text and hex items (ruling 1 of 0.13); the document
  gives no meaning to an empty item.
- **Values longer than 8 bytes as integers.** No item of this set is an
  integer longer than 2 bytes, so the 8-byte limit of the integer transforms
  does not bind here. An integer item sent longer than 8 bytes would be
  `transform-decode`.
- **Version 3 by default.** The document says a set without tag 22 is to be
  read as version 3. Decode leaves `misb0102.version` absent rather than
  inventing 3, and encode writes no version, so the set round-trips as it was.
- **Deprecated items.** Earlier versions of the document had items for
  linking a set to a stream or a metadata item (UMID, stream identifiers,
  item designator; revision history of ST 0102.12). ST 0102.12 deleted them,
  and Table 2 defines no tag from 15 to 21. Earlier editions were not read, so
  their tags are not stated here. Any item of such a tag is residue and is
  carried back unchanged in a round trip.
- **Repetition rate.** The rule that the set is repeated at least every 30
  seconds and whenever a value changes is a rule for a stream, not for one
  message.
- **Shared keys.** None. In particular `misb0102.security_classification` is
  not a `core` key: no other loaded format has a field of the same meaning, so
  a conversion between this pack and a track format carries nothing.

## Candidate additions to the pack language

- A 16-byte (Universal Label) tag form on `tlv`, for the Universal Set.
- A `utf16` transform on `tlv`, for tag 13.
- A way for a pack to read a set without its key, or for one pack to decode
  a nested set with another pack's lines (ST 0601 item 48).
