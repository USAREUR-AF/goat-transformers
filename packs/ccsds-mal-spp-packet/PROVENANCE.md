# Provenance: ccsds-mal-spp-packet pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| CCSDS 524.1-B-1, Mission Operations, MAL Space Packet Transport Binding and Binary Encoding, Recommended Standard (Blue Book), Issue 1, August 2015; sections 3.1 and 3.4 (with the space packet primary header of CCSDS 133.0-B-2, as ccsds-space-packet states it) | https://ccsds.org/Pubs/524x1b1.pdf | `6daa871c4f1298fbd0789dd6073841f5c71e7860e44a0b613c17b156939332a4` |

## Licence

The Blue Books are published by the CCSDS Secretariat and downloaded without registration or charge.
This document carries no copyright notice, distribution statement, handling marking or export-control
notice (searched in the extracted text for copyright, export, proprietary and distribution notices). The terms of reuse are the CCSDS "Reproduction Permission Statement for
Publications" on https://ccsds.org/publications/, the same statement as for the other CCSDS packs:

> In general, reasonable reuse of materials published in CCSDS documents is permitted with
> attribution, and reprint permission can be provided in writing for those organizations that
> require formal permission statements.

The pack reuses facts (field positions, widths and codes) with attribution in its `source` line,
this file and `NOTICE`; it reprints no text, table or figure, and keeps the default Apache-2.0 label.
The foreword draws attention to possible patent rights and states that CCSDS seeks reasonable and
non-discriminatory licensing from holders.

The vectors are built by `tools/gen/sdls-ep-vectors.py` from values chosen there; their expected bytes
are derived there, without an engine.
