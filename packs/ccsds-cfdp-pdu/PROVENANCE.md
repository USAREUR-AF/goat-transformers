# Provenance: ccsds-cfdp-pdu pack

Read on 2026-11-20. No source file is copied into this tree. The pack holds
field positions, widths and the values the standard fixes, stated in this
project's own words; the vectors hold header bytes computed by
`tools/gen/ccsds-2-vectors.py` from its own layout table.

## Pack `ccsds-cfdp-pdu`, module `ccsdscfdp`

| | |
|---|---|
| Source | CCSDS 727.0-B-5, CCSDS File Delivery Protocol (CFDP), Recommended Standard (Blue Book), Issue 5, July 2020, Editorial Change 1 |
| Download | https://ccsds.org/Pubs/727x0b5e1.pdf |
| SHA-256 | `8b84c694be2312cd7364b39a8fd053a75c1bd48cb477965841750ec46c13108c` (1159291 bytes) |
| Sections used | 5.1 (fixed PDU header), 5.2.1 (directive codes), 1.3.1 (bit numbering) |

## License and terms

The Blue Books are published by the CCSDS Secretariat and can be downloaded
without registration or charge from https://ccsds.org/publications/. This
document carries no copyright notice, no distribution statement, no handling
marking and no export-control notice (searched in the extracted text for
copyright, export-control, proprietary, distribution and restriction notices).
The terms of reuse are the CCSDS "Reproduction Permission Statement for
Publications", shown on https://ccsds.org/publications/ (read 2026-11-19, the
same statement as for the other CCSDS packs):

> In general, reasonable reuse of materials published in CCSDS documents is
> permitted with attribution, and reprint permission can be provided in
> writing for those organizations that require formal permission statements.

This pack reuses facts (field positions, widths, values) with attribution in
its `source` line, this file and `NOTICE`; it reprints no text, table or
figure. The foreword draws attention to possible patent rights in elements of
the document and states that CCSDS seeks agreement from holders that licensing
policies are reasonable and non-discriminatory.
