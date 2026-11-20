# Provenance: ccsds-uslp-frame pack

Read on 2026-11-20. No source file is copied into this tree. The pack holds
field positions, widths and the values the standard fixes, stated in this
project's own words; the vectors hold header bytes computed by
`tools/gen/ccsds-2-vectors.py` from its own layout table.

## Pack `ccsds-uslp-frame`, module `ccsdsuslp`

| | |
|---|---|
| Source | CCSDS 732.1-B-3, Unified Space Data Link Protocol, Recommended Standard (Blue Book), Issue 3, June 2024, Editorial Change 1 |
| Download | https://ccsds.org/Pubs/732x1b3e1.pdf |
| SHA-256 | `3d931ae1b9ffb6a9282fedcc79e619356e61f67729d1e3f9bf433f8e719420ff` (1364346 bytes) |
| Sections used | 4.1.2 (primary header), annex D (truncated frame), 1.6 (bit numbering) |

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
