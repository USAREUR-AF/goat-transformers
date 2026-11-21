# Provenance: ais-binary-regional pack

SPDX licence: LicenseRef-unstated

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| St. Lawrence Seaway AIS Data Messaging Formats and Specifications, Harmonized with U.S. Coast Guard PAWSS AIS Messages, Revision 4.1, April 9, 2010; sections 1 to 9 and Appendix A | https://greatlakes-seaway.com/wp-content/uploads/2020/05/Seaway-AIS-message-specifications-R41.pdf | `79da3b8f29acf7543ff440903769a702c98bd7dc4dba438720c75150262b917d` |
| gpsd, AIVDM/AIVDO protocol decoding (www/AIVDM.adoc), the type 8 DAC/FID table and the regional extensions section, which name the document above as the description of DAC 316/366 (read for the pointer only) | https://gitlab.com/gpsd/gpsd/-/blob/c59fc6de479d06620c8b2ba395b728e10a71527b/www/AIVDM.adoc | `a55511139751f5b9385166143443c0353f64fc77155b4ef4026f4ab03e3dffbd` |

## Licence

The Seaway publishes the document on its own website, and gpsd describes it as freely available. Its
title page says it was developed for the Saint Lawrence Seaway Development Corporation (a U.S. federal
agency) and the Saint Lawrence Seaway Management Corporation by the U.S. Department of Transportation's
John A. Volpe Transportation Systems Center. It carries no copyright notice, no licence and no terms
of use (searched in the extracted text). A work prepared by U.S. federal staff is not under copyright in
the United States, but the document does not say so, and part of it may be the Canadian corporation's.

This project's standing decision is that a document that states no licence, without limiting the
purpose of use, is restated from its text. The pack restates the layouts (field order, widths, codes)
in this project's own words; no text, table or example of the document is copied. Because no licence
is stated the pack is labelled `LicenseRef-unstated` (REUSE.toml in this directory;
model/aisregion.def.license for the module), which keeps it out of the `open` profile; the operator can
overturn this, for example by recording the document as a U.S. Government work.

The vectors are payloads built by `tools/gen/ais-regional-vectors.py` from values chosen there and
armored there; their expected text is derived there, without an engine.

## Attribution

From St. Lawrence Seaway AIS Data Messaging Formats and Specifications, Revision 4.1 (2010), prepared by
the U.S. DOT Volpe Center for the Saint Lawrence Seaway Development Corporation and the Saint Lawrence
Seaway Management Corporation. No copyright notice or licence stated; labelled LicenseRef-unstated.
Layouts restated, no text copied.
