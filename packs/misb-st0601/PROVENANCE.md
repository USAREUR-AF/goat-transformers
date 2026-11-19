# Provenance: misb-st0601 pack

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module hold item tags, value types, sizes, ranges and scale factors, stated in
this project's own words; no text, table, figure or example of the document
is reproduced.

## Pack `misb-st0601`, module `misb0601`

| | |
|---|---|
| Source | MISB ST 0601.19, "UAS Datalink Local Set", Motion Imagery Standards Board |
| Version | ST 0601.19, dated 02 March 2023; its revision history lists later edits of 05/10/2024 and 06/11/2025. PDF metadata: created 2025-07-02, 226 pages |
| Obtained from | the NSG Registry public document store, document view `doc/view?i=5471`, through an Internet Archive capture of 2026-10-03 |
| File | `ST0601.19.pdf`, 4700978 bytes |
| SHA-256 | `e53c1e7bfdda888d5946610f89a8146a3f339394e1b127807302676c0cfb92b1` |

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

| Part of ST 0601.19 | Used for |
|---|---|
| 6.2 | the 16-byte Universal Label key |
| 6.3, 6.4, 6.6 and item 1 (8.1) | packet structure, BER-OID tags, BER lengths, item 2 first, checksum last, the checksum sum |
| 6.5, 7.5 | zero-length items and special values (pack.md, "Not mapped") |
| 7.1, Table 1 | the list of items, their formats and lengths |
| 7.2.1 | which items give the sensor location |
| Section 8, items 2 to 25, 56, 59, 65, 75, 78 to 80, 90, 91 | units, integer type, required length, range and mapping of each mapped item |

Other documents that ST 0601 refers to (MISB ST 0102, 0603, 0806, 0903, 1201,
1607 and others, SMPTE ST 336) were not read. Items defined by them are
residue (pack.md).
