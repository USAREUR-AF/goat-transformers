# Provenance: ais-binary-apps pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| gpsd, AIVDM/AIVDO protocol decoding (www/AIVDM.adoc), sections IMO236 Tidal Window, IMO289 Dangerous Cargo Indication, IMO289 Route Information (addressed and broadcast), Tidal Window (IMO289), VTS-Generated/Synthetic targets, IMO289 Environmental; at commit c59fc6de479d06620c8b2ba395b728e10a71527b | https://gitlab.com/gpsd/gpsd/-/blob/c59fc6de479d06620c8b2ba395b728e10a71527b/www/AIVDM.adoc | `a55511139751f5b9385166143443c0353f64fc77155b4ef4026f4ab03e3dffbd` |
| gpsd COPYING, same commit | https://gitlab.com/gpsd/gpsd/-/blob/c59fc6de479d06620c8b2ba395b728e10a71527b/COPYING | `fdf339997bbca9eaf507476b82fbcac608fc39a3d89b86b51e16db4c9f933716` |

## Licence

gpsd is under the BSD 2-Clause License (COPYING: "Compilation copyright is held by the GPSD project.
All rights reserved." with the BSD-2-Clause terms). The document states it was written from freely
redistributable sources (it restates IMO SN.1/Circ.236 and 289 as published by others). Under rule 17
of this project a layout restated from a BSD-licensed document, with no text copied, is Apache-2.0: the
pack keeps the default label, and the source is named here (Attribution below).

The vectors are payloads built by `tools/gen/ais-apps-vectors.py` from values chosen there, armored
there; their expected text is derived there, without an engine.

## Attribution

From gpsd, AIVDM/AIVDO protocol decoding (www/AIVDM.adoc), https://gitlab.com/gpsd/gpsd commit
c59fc6de. Compilation copyright held by the GPSD project. BSD 2-Clause License. Layouts restated, no
text copied.
