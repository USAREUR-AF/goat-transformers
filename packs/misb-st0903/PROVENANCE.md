# Provenance: misb-st0903 pack

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module hold item tags, value types, sizes and the meaning of each item, stated
in this project's own words; no text, table, figure or example of the
document is reproduced.

## Pack `misb-st0903`, module `misb0903`

| | |
|---|---|
| Source | MISB ST 0903.6, "Video Moving Target Indicator Metadata", Motion Imagery Standards Board |
| Version | ST 0903.6, dated 21 October 2021; its revision history lists later edits of 01/21/2022 and 05/08/2024. PDF metadata: created 2024-05-09, 72 pages |
| Obtained from | the NSG Registry public document store, document view `doc/view?i=5310`, through an Internet Archive capture of 2026-10-04 of the file in the registry's document store |
| File | `ST0903.6.pdf`, 1635839 bytes |
| SHA-256 | `aa09465cd6d2da3b04bdff33bfee090cfbe061a62c1f6ce2a40f8611d9f9ed07` |

### Terms

The copyright page of the NSG Registry states:

> Materials in the public portions of this registry are either in the public
> domain, have been released for public use, or make fair use of copyright
> protected material.

The PDF itself carries no distribution statement, no copyright notice and no
license text. Its text, page headers and page footers were searched for a
distribution, handling, export or proprietary marking, and none was found.
Each page carries only the document number and title, the date and the name of
the Motion Imagery Standards Board.

### Parts used

| Part of ST 0903.6 | Used for |
|---|---|
| 8.2, 8.3 | standalone and embedded forms (pack.md, "Not mapped") |
| 9.1, 9.1.1 | the "V" length notation; IMAPB and its special values (pack.md, "Not mapped") |
| 9.1.3, 9.2, 9.2.1, 9.2.2 | series structure, tag and length encodings, no repeated items, the timestamp base |
| 10.1, Table 9 | the 16-byte key, the list of top-level items, their formats and lengths |
| 10.1.1 to 10.1.13 | the meaning, units and requirements of items 1 to 13 |
| 10.1.14 to 10.1.16, 10.2, Table 10, 10.10, 10.11 | the structure of the series and packs that are not mapped (pack.md) |

The checksum algorithm is defined in ST 0903.6 by reference to MISB ST 0601;
it was read in MISB ST 0601.19 (NSG Registry `doc/view?i=5471`), the source of
the `misb-st0601` pack. Other documents that ST 0903 refers to (MISB ST 0107,
0603, 0807, 1201, 1204, SMPTE ST 336, STANAG 4676) were not read; the items
that depend on them are residue or kept raw (pack.md).

Section 9.2 gives byte 6 of the key as 0x2B; the key printed in section 10.1
has 0x0B, the value for BER-OID tags and BER lengths. The pack uses the key of
section 10.1 (pack.md, "Message convention").
