# Provenance: ntrip-sourcetable-line pack

SPDX licence: LicenseRef-unstated

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| BKG, Networked Transport of RTCM via Internet Protocol (Ntrip) Version 1.0, documentation; section 6 (Source-Table) and Appendix A | https://igs.bkg.bund.de/root_ftp/NTRIP/documentation/NtripDocumentation.pdf | `d2399f37643acec3bff35b26cfc873613048a5f65bf4ccb66032eae708d44977` |

## Licence

The Ntrip standard (RTCM 10410.0 for version 1, 10410.1 for version 2) is sold by RTCM and was not read.
The German Federal Agency for Cartography and Geodesy (BKG), which developed Ntrip, publishes this
documentation of version 1.0 on its server with no registration. Its title page says it is not the
official RTCM documentation and points to RTCM for that; it omits the server and client message
details and keeps the source-table section. It carries no copyright notice and no licence for the text
(the example client source code in its Appendix C is under the GNU GPL, and was not used).

This project's standing decision is that a document that states no licence, without limiting the
purpose of use, is restated from its text. The pack restates the record layouts (field order and
meanings) in this project's own words; no text, table or example record of the document is copied.
Because no licence is stated the pack is labelled `LicenseRef-unstated` (REUSE.toml in this directory;
model/ntrip.def.license for the module); the operator can overturn it.

The vectors are built by `tools/gen/gnss-time-vectors.py` from values chosen there; their expected output is
derived there, without an engine.

## Attribution

From Networked Transport of RTCM via Internet Protocol (Ntrip) Version 1.0, documentation published by
BKG (Bundesamt für Kartographie und Geodäsie). No copyright notice or licence stated; labelled
LicenseRef-unstated. Record layouts restated, no text copied.
