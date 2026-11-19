# Provenance: ccsds-space-packet pack

Read on 2026-11-19. No source file is copied into this tree. The pack holds
field positions, widths and the values the standard fixes, stated in this
project's own words; the vectors hold header bytes computed by
`tools/gen/ccsds-vectors.py` from its own layout table.

## Pack `ccsds-space-packet`, module `ccsdssp`

| | |
|---|---|
| Source | CCSDS 133.0-B-2, Space Packet Protocol, Recommended Standard (Blue Book), Issue 2, June 2020, Editorial Change 2 |
| Download | https://ccsds.org/Pubs/133x0b2e2.pdf |
| SHA-256 | `a7d3acaa7d8af5f306917dff454b69de187855c45a51bb76ac4636fb5b23e34e` (663940 bytes) |
| Sections used | 1.6 (bit numbering), 4.1.2 (packet structure), 4.1.3 (primary header), 4.1.4.1 and 4.1.4.2.1 (data field, to state what is not mapped) |

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
