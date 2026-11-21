# Provenance: ptp-message pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| linuxptp v4.4 (commit 0188667308e62b6ac61151193320ec052e2fd023), msg.h: the message header and bodies | https://github.com/richardcochran/linuxptp/blob/0188667308e62b6ac61151193320ec052e2fd023/msg.h | `4fcb3192f77ca15ab848857f21854bf3ac3d3d849ce47b97b071180cbb387c55` |
| linuxptp v4.4, ddt.h: the timestamp, port identity, clock quality and TLV types | https://github.com/richardcochran/linuxptp/blob/0188667308e62b6ac61151193320ec052e2fd023/ddt.h | `1f14a317068a737b6e659231a81ccda96c0fc2ab62f5dd10b14bb0795b3f3665` |
| linuxptp v4.4, tlv.h: the TLV type codes | https://github.com/richardcochran/linuxptp/blob/0188667308e62b6ac61151193320ec052e2fd023/tlv.h | `35e12a52067d2eb8f42ca197a8c4d7c64eba4bd7343f27b02ba9083bd4f83da3` |
| linuxptp v4.4, COPYING | https://github.com/richardcochran/linuxptp/blob/0188667308e62b6ac61151193320ec052e2fd023/COPYING | `8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643` |

## Licence

IEEE 1588 (the PTP standard) is sold by the IEEE and was not read. linuxptp, an implementation of it for
Linux, is under the GNU General Public License, version 2 or later ("Copyright (C) 2011 Richard Cochran"
in msg.h). The pack restates the message layouts the headers declare (field order and widths, type
codes, flag bits) in this project's own words; no code or comment is copied. Under rule 17 of this
project a layout restated from GPL code, with no code copied, is Apache-2.0: the pack keeps the default
label, and the source is named here (Attribution below).

The vectors are built by `tools/gen/gnss-time-vectors.py` from values chosen there; their expected output is
derived there, without an engine.

## Attribution

PTP message layouts restated from linuxptp msg.h, ddt.h and tlv.h, https://github.com/richardcochran/linuxptp
tag v4.4 commit 01886673. Copyright (C) 2011 Richard Cochran and the linuxptp contributors. GNU General
Public License, version 2 or later. No code or comments copied.
