# Provenance of the ltm pack

SPDX licence: Apache-2.0

Written by hand from INAV's LTM telemetry code; the vectors by
`tools/gen/rc-telemetry-vectors.py`. The file is not kept in this repository. Read on
2026-11-20.

## Source

| | |
|---|---|
| Document | LTM (Lightweight Telemetry) as INAV sends it |
| Repository | https://github.com/iNavFlight/inav, default branch, commit `21adf64440bb0d9f0bdc56569098fbaa0e39d24d` |
| License file | `LICENSE`, SHA-256 `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903` (GNU General Public License, version 3) |
| Files read | `src/main/telemetry/ltm.c` (SHA-256 `d5bc43754709f522e7a03ab52762c3123b9c7661e80c0171eb817fe593a315e1`), `src/main/telemetry/ltm.h` (`10b1b8d3f124e266c442ae3af9ec287a1dc7b7dbec1da20776dc693d9358c6f8`) |

LTM was first defined for the Ghettostation antenna tracker; no separate public
specification was found, so INAV's implementation is the source.

## Licence

INAV is licensed under the GNU General Public License: `LICENSE` is the text of the GNU
General Public License, version 3, 29 June 2007, and the source files state that they may be
redistributed and modified under version 3 of the License or (at the option of the
recipient) any later version. This pack restates the frame and message layouts it reads
(names, offsets, sizes, types and units) in the project's own words; no code or comment text
is copied. As for `ardupilot-log-*`, `meshtastic` and `cot-protobuf` (also GPL-3.0
sources), the restated layouts carry the project's licence, Apache-2.0 (REUSE.toml, the
default annotation). The GPL source is credited: the INAV project contributors.
