SPDX licence: Apache-2.0

# Provenance: agopengps-pgn

Written by hand from AgOpenGPS. No source file is copied into this tree.

| | |
|---|---|
| Repository | https://github.com/AgOpenGPS-Official/AgOpenGPS |
| Tag | `6.8.6`, commit `21be26aa58d09b9b5abacc715d0abcf4a021f1db` (committed 2026-08-17T18:40:35+02:00), the latest release when read |
| Files read | `docs/pgn-protocol.md` (the PGN frame and the PGNs, the source of the layouts); `SourceCode/AgIO/Source/Forms/NMEA.Designer.cs` and `SourceCode/GPS_Out/Source/PGNs/PGN54908.cs` (PGN 214 as AgIO builds it: 51 data bytes, source 0x7C); `SourceCode/GPS/Forms/UDPComm.Designer.cs` (how AgOpenGPS reads PGN 214: latitude and longitude into a WGS 84 position, the units of roll and altitude); `SourceCode/GPS/Forms/PGN.Designer.cs` (PGN 208's byte positions) |
| Date read | 2026-11-21 |

## Licence

`LICENSE` at the tag is the Apache License, Version 2.0. GitHub reports the repository as
`Apache-2.0`.

## SHA-256

```
5260145f825bc308fd72566dd75f84e48c882ae575a4d14ea0c7df406766e254  docs/pgn-protocol.md
a1254e356e40001282a1fa621ef019a9a0932261f0f0456eff017da153ccac2b  LICENSE
```
