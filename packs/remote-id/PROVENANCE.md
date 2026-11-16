# Provenance: remote-id pack

Read on 2026-11-15. No source file is copied into this tree. The packs hold
field positions, scale factors and code meanings; the vectors hold message
bytes and decoded values.

## Pack `remote-id`, module `rid`

| | |
|---|---|
| Source | `opendroneid-core-c`, the reference implementation of ASTM F3411 / ASD-STAN prEN 4709-002 message contents |
| Upstream | https://github.com/opendroneid/opendroneid-core-c |
| Version | commit `849c03adbe0cdd68997a462fafab397edcfe53f3`; `CMakeLists.txt` `set(VERSION 0.2)`; `#define ODID_PROTOCOL_VERSION 2` (ASTM F3411-22a) |
| Download | `https://raw.githubusercontent.com/opendroneid/opendroneid-core-c/849c03adbe0cdd68997a462fafab397edcfe53f3/<path>`; the SHA-256 values below are those of the files at that commit |
| License file | `LICENSE`, 201 lines, sha256 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |
| NOTICE file | none in the tree |

The `LICENSE` file is the text of the Apache License. Its heading:

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

Its appendix is the unfilled template (`Copyright [yyyy] [name of copyright
owner]`). The copyright statement is in each file header:

> Copyright (C) 2019 Intel Corporation
>
> SPDX-License-Identifier: Apache-2.0

(`libopendroneid/wifi.c`, not used here, adds `Copyright (C) 2020 Simon
Wunderlich, Marek Sobe` and `Copyright (C) 2020 Doodle Labs`.)

Section 4 of the license, on redistribution of the Work or Derivative Works:

> (a) You must give any other recipients of the Work or Derivative Works a
> copy of this License; and (b) You must cause any modified files to carry
> prominent notices stating that You changed the files; and (c) You must
> retain, in the Source form of any Derivative Works that You distribute, all
> copyright, patent, trademark, and attribution notices from the Source form
> of the Work

Files read, with sha256:

| File | sha256 | Used for |
|---|---|---|
| `libopendroneid/opendroneid.h` | `a60b9b38c4fa82d7c85437dc11f57f0dea4ebf8bb4b90b3ff3c21c585ccd55f4` | packed structs (`ODID_*_encoded`): every field position and width; enumerations; unknown values |
| `libopendroneid/opendroneid.c` | `60b0964f5f2a0dc13833eb6a304f7bd3f64bb9c227fae168c7caba53c82927c2` | `SPEED_DIV`, `VSPEED_DIV`, `LATLON_MULT`, `ALT_DIV`, `ALT_ADDER`; `encode*` / `decode*` functions |
| `test/test_inout.c` | `08d184c0999b9d1ff9e2d0a89a9b1f4abbf52394fa16afad6f8c1647d40eecee` | input values of vectors 01-07 and 10 |
| `test/unit_odid_wifi_beacon.cpp` | `2c339cded6d2d138d3d1b2236eed0ffe3d156289dfe6c35fcdff678d931216cb` | the fixed 25-byte Basic ID message of vectors 08, 09 and 13 |

ASTM F3411-22a itself is a priced standard and was not read. Every layout
statement in the pack is the reference implementation's.
