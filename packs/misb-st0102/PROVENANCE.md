# Provenance: misb-st0102 pack

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module hold the key, item tags, value types, stated lengths and code values,
stated in this project's own words; no text, table, figure or example of the
document is reproduced.

## Pack `misb-st0102`, module `misb0102`

| | |
|---|---|
| Source | MISB ST 0102.12, "Security Metadata Universal and Local Sets for Motion Imagery Data", Motion Imagery Standards Board |
| Version | ST 0102.12, dated 22 June 2017. The registry entry lists it as edition 1.12, valid from 6 Sep 2017, superseding ST 0102.11. PDF metadata: created 2019-01-10, 18 pages |
| Obtained from | the NSG Registry public document store, document view `doc/view?i=4422`, through an Internet Archive capture of the registry's file store of 2026-10-03; the registry's document page was read in an Internet Archive capture of 2025-09-05 |
| File | `ST0102.12.pdf`, 514842 bytes |
| SHA-256 | `20d40b5237cdcd2f486547add8eee238e37d5a6b11b7e0aca306be0785eca267` |

### Terms

The copyright page of the NSG Registry states:

> Materials in the public portions of this registry are either in the public
> domain, have been released for public use, or make fair use of copyright
> protected material.

The PDF itself carries no distribution statement, no copyright notice and no
license text. Its text, page headers and page footers were searched for a
distribution, handling, export or proprietary marking, and none was found.
Each page carries only the document number and title, the date and the name of
the Motion Imagery Standards Board. The document's subject is security
metadata: the classification levels, caveats and handling words it contains
are values it defines for its items, not markings applied to the document.

### Parts used

| Part of ST 0102.12 | Used for |
|---|---|
| 6.1.1 to 6.1.17 | meaning and text form of each item |
| 6.6, Table 1 | the Universal Set form (pack.md, "Not mapped") |
| 6.7 | the 16-byte Universal Label key of the Local Set and its conformance to SMPTE ST 336 |
| Table 2 | tags, value types, stated lengths and code lists of the Local Set items |
| 6.8 | the conversion between the integer codes and the Universal Set text |
| Revision history, Appendix A | deleted and deprecated items (pack.md, "Not mapped") |

MISB ST 0601.19 (the source of the `misb-st0601` pack, see its PROVENANCE.md)
was consulted for item 48, which nests this set. SMPTE ST 336, which defines
the meaning of byte 6 of the key (tag and length form), and the other
documents ST 0102 refers to (CAPCO registers, GENC, ISO 3166, FIPS 10-4,
STANAG 1059, RFC 2781, MISB ST 0107 and ST 0807) were not read.
