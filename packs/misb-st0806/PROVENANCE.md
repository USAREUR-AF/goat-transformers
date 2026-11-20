# Provenance: misb-st0806 pack

Read on 2026-11-20. No source file is copied into this tree. The pack and the
module hold item tags, value types, sizes and the meaning of each item, stated
in this project's own words; no text, table, figure, example or sample code of
the document is reproduced.

## Pack `misb-st0806`, module `misb0806`

| | |
|---|---|
| Source | MISB ST 0806.4, "Remote Video Terminal Metadata Set", Motion Imagery Standards Board |
| Version | ST 0806.4, dated 27 February 2014. PDF metadata: created 2014-06-30, 13 pages |
| Obtained from | the NSG Registry public document store (its file store, path `doc/Document/ST0806.4.pdf`), through an Internet Archive capture of 2026-10-03 (capture 20261003212940). The registry's document view page for this file (`doc/view?i=…`) was not found, so no page number is given here |
| File | `ST0806.4.pdf`, 716099 bytes |
| SHA-256 | `58de4265d377d88b922df111aab49e52209fe4a4d54870aba53b310ad6e01037` |

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

| Part of ST 0806.4 | Used for |
|---|---|
| 5 | standalone and embedded use of the set (pack.md, "Not mapped") |
| 6, requirements 01 to 04 | the time stamp first, the checksum last, the checksum required in a standalone set |
| 7.1, requirement 06 | the 16-byte Universal Label key |
| 7.3, 7.3.1 to 7.3.3, Tables 8-2 to 8-4 | the structure of the three subordinate sets that are residue (pack.md) |
| 7.4, requirement 25 | single top-level items, repeatable subordinate sets |
| Table 8-1 | the list of top-level items, their formats, lengths, units and meaning |
| 9 (Appendix) | the CRC: ISO/IEC 13818-1 CRC-32, its polynomial and initial value |

The sample code of the appendix was read for the CRC's parameters only and is
not reproduced. Other documents that ST 0806 refers to (MISB ST 0107, 0603,
0807, TRM 1006, SMPTE RP 210, SMPTE ST 336, ISO/IEC 13818-1, MIL-STD-2525B)
were not read. MISB ST 0601.19, read for the `misb-st0601` pack, was consulted
for how it describes the ST 0603 time stamp (pack.md, "Shared keys").
