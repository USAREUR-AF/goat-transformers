# Provenance: gdl90 pack

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module hold byte positions, widths and the scale and sentinel values, restated
from the code below; the vectors hold payloads computed by
`tools/gen/gdl90-vectors.py`.

## Stratux (the only source used)

| | |
|---|---|
| Source | Stratux, https://github.com/cyoung/stratux |
| Version | commit `36b504555408fb90dd5cf1171d4f91f99571e50c` (branch `master`) |
| Download | `https://codeload.github.com/cyoung/stratux/tar.gz/36b504555408fb90dd5cf1171d4f91f99571e50c`, SHA-256 `fcb94bca857a41928ed67ef32c3de0740d26e628e0a1e39d32c8b1a509488fb6` |
| License | `LICENSE`: BSD 3-Clause, "Copyright (c) 2015-2016 Christopher Young" |

The license's conditions, quoted:

> Redistribution and use in source and binary forms, with or without
> modification, are permitted provided that the following conditions are met:
> Redistributions of source code must retain the above copyright notice, this
> list of conditions and the following disclaimer. Redistributions in binary
> form must reproduce the above copyright notice, this list of conditions and
> the following disclaimer in the documentation and/or other materials
> provided with the distribution. Neither the name of the copyright holder nor
> the names of its contributors may be used to endorse or promote products
> derived from this software without specific prior written permission.

No Stratux code is copied or adapted into the pack, the module or the vector
program; the program restates the layouts and the CRC and framing steps in
its own code.

Files and functions read:

| File | Functions | Used for |
|---|---|---|
| `main/gen_gdl90.go` | constants `MSGTYPE_*`, `LON_LAT_RESOLUTION`, `TRACK_RESOLUTION`, `UPLINK_FRAME_DATA_BYTES`; `crcInit`, `crcCompute`, `prepareMessage`, `makeLatLng`, `makeOwnshipReport`, `makeOwnshipGeometricAltitudeReport`, `makeFFIDMessage`, `makeHeartbeat`, `relayMessage` | heartbeat, uplink, ownship, geometric altitude and ForeFlight ID layouts; position scale; framing and CRC (documented, not mapped) |
| `main/traffic.go` | `makeTrafficReportMsg` | traffic report layout, altitude code, the low-nibble flags |
| `main/gps.go` | `makeFFAHRSMessage`; the `GPSHeightAboveEllipsoid` and `GPSAltitudeMSL` fields | ForeFlight AHRS layout; the altitude reference notes in `pack.md` |

## Not used

| Document | Why |
|---|---|
| GDL 90 public ICD 560-1058-00 Rev A, June 5, 2007, Garmin, as hosted at https://www.faa.gov/sites/faa.gov/files/air_traffic/technology/adsb/archival/GDL90_Public_ICD_RevA.PDF (SHA-256 `81904b5cc7f0a3b66317e5bd285c4e96976577bd089d238a5271269ba131c738`) | not used: "© 2004-2007 Garmin Ltd. or its subsidiaries. All rights reserved."; no license, and a condition on display makers that use its information. Nothing in this pack is taken from it |
| ForeFlight GDL 90 Extended Specification, https://www.foreflight.com/connect/spec/ | not used: no terms stated on the page |

Stratux's comments name the ICD's page numbers; those references were not
followed.
