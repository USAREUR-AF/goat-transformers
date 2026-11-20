# Provenance of the msp-v2 pack

SPDX licence: Apache-2.0

Written by hand from INAV's MSP message definitions and serial code; the vectors by
`tools/gen/rc-telemetry-vectors.py`. The files are not kept in this repository. Read on
2026-11-20.

## Source

| | |
|---|---|
| Document | INAV MSP message definitions (`msp_messages.json`, version 2.1.2) and MSP serial framing |
| Repository | https://github.com/iNavFlight/inav, default branch, commit `21adf64440bb0d9f0bdc56569098fbaa0e39d24d` |
| License file | `LICENSE`, SHA-256 `8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903` (GNU General Public License, version 3) |
| Files read | `docs/development/msp/msp_messages.json` (SHA-256 `07bf2f771aea96c3c362dcd6493bad78607f3f52f4205317fb3d95985c483c77`), `docs/development/msp/README.md` (`7d868df6a5202d7d1f8f8dd202755045e4993fd8e97322e1bb12e92d4549cee3`), `src/main/msp/msp_serial.c` (`e477c00add0bf86d6f2eed4fd7f9d304b1e621daa54eb2b133a7e70434a6fec8`), `src/main/msp/msp_serial.h` (`250b547dd7ddfce1a0d2242b37f45942344e313a52b531f3094e93799884c031`) |

## Licence

INAV is licensed under the GNU General Public License: `LICENSE` is the text of the GNU
General Public License, version 3, 29 June 2007, and the source files state that they may be
redistributed and modified under version 3 of the License or (at the option of the
recipient) any later version. This pack restates the frame and message layouts it reads
(names, offsets, sizes, types and units) in the project's own words; no code or comment text
is copied. As for `ardupilot-log-*`, `meshtastic` and `cot-protobuf` (also GPL-3.0
sources), the restated layouts carry the project's licence, Apache-2.0 (REUSE.toml, the
default annotation). The GPL source is credited: the INAV project contributors.
