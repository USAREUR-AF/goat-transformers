# Provenance: nmea0183-pubx pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| gpsd NMEA Revealed (www/NMEA.adoc), sections PUBX 00, 01, 03 and 04, at commit c59fc6de479d06620c8b2ba395b728e10a71527b | https://gitlab.com/gpsd/gpsd/-/blob/c59fc6de479d06620c8b2ba395b728e10a71527b/www/NMEA.adoc | `83192561db3198d46ef249233c689de2c9735af162c840155d11e6157574d29e` |
| gpsd COPYING, same commit | https://gitlab.com/gpsd/gpsd/-/blob/c59fc6de479d06620c8b2ba395b728e10a71527b/COPYING | `fdf339997bbca9eaf507476b82fbcac608fc39a3d89b86b51e16db4c9f933716` |

## Licence

gpsd is under the BSD 2-Clause License (COPYING: "Compilation copyright is held by the GPSD project.
All rights reserved." with the BSD-2-Clause terms). The document states it was written from freely
redistributable sources. Under rule 17 of this project a layout restated from a BSD-licensed document,
with no text copied, is Apache-2.0: the pack keeps the default label, and the source is named here and
in `NOTICE`.

The vectors are built by `tools/gen/maritime-vectors.py` from values chosen there; their expected
output is derived there, without an engine.
