# Provenance: dtn-bpv7 pack

Read on 2026-11-20. No source file is copied into this tree. The pack and the
module `bpv7` hold the bundle's structure, the positions of the primary-block
fields, code numbers (CRC types, URI scheme codes, the version number) and
CBOR item types, stated in this project's own words. No text, table, figure,
ABNF, CDDL or example of the RFC is reproduced. The pack's vectors use values
chosen for this pack, not the RFC's.

## RFC 9171

| | |
|---|---|
| Source | IETF RFC 9171, "Bundle Protocol Version 7", Standards Track, January 2022 |
| Download | https://www.rfc-editor.org/rfc/rfc9171.txt |
| File | `rfc9171.txt`, 134360 bytes |
| SHA-256 | `74e542b143793c9ce41a397fca76f68782792cd0169db9f6a37b21de8dbb9ce5` |
| Errata | https://www.rfc-editor.org/info/rfc9171 (not applied) |

### Terms

The RFC's copyright notice:

> Copyright (c) 2022 IETF Trust and the persons identified as the
> document authors.  All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal
> Provisions Relating to IETF Documents
> (https://trustee.ietf.org/license-info) in effect on the date of
> publication of this document.

The Legal Provisions in force are the Corrected Trust Legal Provisions 5.0,
effective 25 March 2015 (https://trustee.ietf.org/documents/trust-legal-provisions/tlp-5/,
the PDF `Corrected-TLP-5.0-legal-provsions.pdf`, SHA-256
`b5cbd993d1dae273d7b251db4efc397b4de13451b2156b94d5a901c83c0fb48a`, read
2026-11-20). What this pack relies on:

- Section 3.b of the Provisions counts the implementation of IETF standards
  and specifications as part of the IETF Standards Process. Section 3.a.iii
  licenses derivative works within that process unless the document carries
  a legend of section 6.c. RFC 9171 carries no such legend.
- The pack takes only facts needed to implement the protocol: the order and
  CBOR types of fields, code numbers and registry values. It copies no
  portion of the document's text. So the distribution licenses of section
  3.c, which cover copies of unmodified text, are not needed. The prohibition
  in 3.d on modifying the document's text is not engaged.
- The RFC's Code Components (the CDDL of its Appendix B) are licensed under
  the Revised BSD License by section 4. None is used or copied here.

The document carries no distribution statement, handling marking, export
notice or proprietary notice.

### Parts used

| Part of RFC 9171 | Used for |
|---|---|
| 4.1 | the bundle as an indefinite-length array of blocks, primary block first, payload block last; core deterministic encoding of fields |
| 4.2.1, 4.2.2 | CRC type codes; the CRC as a 2- or 4-byte byte string, present only when the type is not 0 |
| 4.2.3 | the bundle processing control flags as one unsigned integer, bit 0 the low-order bit, and the fragment bit |
| 4.2.5.1, 4.2.5.1.1, 4.2.5.1.2, 4.2.5.2 | endpoint IDs as [scheme code, SSP]; the dtn SSP (text, or 0 for `dtn:none`); the ipn SSP ([node, service]); node IDs as endpoint IDs |
| 4.2.6, 4.2.7 | DTN time (milliseconds since 2000-01-01 UTC, 0 unknown); the creation timestamp as [time, sequence] |
| 4.2.8, 4.3.2 | canonical blocks: 5 or 6 elements, block-type-specific data as a byte string (pack.md, "Not mapped") |
| 4.3.1 | the primary block: 8 to 11 elements, their order and types |
| 4.4 | extension blocks, to state what is residue |
| 9.1, 9.2, 9.6 | block type 1 (payload), version 7, URI scheme codes 1 (dtn) and 2 (ipn) |

Other documents that RFC 9171 refers to (RFC 9172 Bundle Protocol Security,
RFC 8949 CBOR beyond what the `cbor` wire states, RFC 6260 the ipn scheme)
were not read for this pack.
