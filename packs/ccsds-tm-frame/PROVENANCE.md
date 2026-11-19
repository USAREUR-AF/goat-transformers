# Provenance: ccsds-tm-frame pack

Read on 2026-11-19. No source file is copied into this tree. The pack holds
field positions, widths and the values the standard fixes, stated in this
project's own words; the vectors hold header bytes computed by
`tools/gen/ccsds-vectors.py` from its own layout table.

## Pack `ccsds-tm-frame`, module `ccsdstm`

| | |
|---|---|
| Source | CCSDS 132.0-B-3, TM Space Data Link Protocol, Recommended Standard (Blue Book), Issue 3, October 2021 |
| Download | https://ccsds.org/Pubs/132x0b3.pdf |
| SHA-256 | `be715bb3b1f92a4e5655719969277aee3b250dd706748b53dccd9971896603ad` (893096 bytes) |
| Sections used | 1.6 (bit numbering), 4.1.1 (frame structure), 4.1.2 (primary header), 4.1.3.2 (secondary header identification field) |

## License and terms

The Blue Books are published by the CCSDS Secretariat and can be downloaded
without registration or charge from https://ccsds.org/publications/ (the
`https://public.ccsds.org/Pubs/` addresses redirect to `https://ccsds.org/Pubs/`).
The documents carry no copyright notice, no distribution statement, no
handling marking and no export-control notice (searched in the extracted text
for copyright, export-control, proprietary, distribution and restriction
notices). The terms of reuse are the CCSDS "Reproduction Permission
Statement for Publications", shown on https://ccsds.org/publications/ (read
2026-11-19):

> In general, reasonable reuse of materials published in CCSDS documents is
> permitted with attribution, and reprint permission can be provided in
> writing for those organizations that require formal permission statements.

The statement continues with the address for reprint requests. This pack
reuses facts (field positions, widths, values) with attribution in its
`source` line, this file and `NOTICE`; it reprints no text, table or figure.
Each Blue Book's foreword draws attention to possible patent rights in elements
of the document and states that CCSDS seeks agreement from holders that
licensing policies are reasonable and non-discriminatory.
