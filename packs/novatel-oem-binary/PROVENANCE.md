# Provenance: novatel-oem-binary pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| swri-robotics/novatel_gps_driver (Southwest Research Institute) | https://github.com/swri-robotics/novatel_gps_driver | `63e19e2e3088e80ecceaa18d86022afffb3ccaf3` |

| File read | SHA-256 |
|---|---|
| `novatel_gps_driver/include/novatel_gps_driver/binary_header.h` | `75c60fdbfeff3cac48e399c01f9c17260de711423c12c20071bbaf1f6e527307` |
| `novatel_gps_driver/src/parsers/bestpos.cpp` | `9c74a8438ce0a9faf0b2ca6a5b9a31af15caf57cc682e8f8d05190becf75965e` |
| `novatel_gps_driver/include/novatel_gps_driver/parsers/bestpos.h` | `0ad41d7ee5884d2892735dde36f15c822698bab5e200f0f5ad835d1727e59a82` |
| `novatel_gps_driver/src/parsers/header.cpp` (time status values; read 2026-11-24) | `4d4e11d2ce574dc89db4f2a45a855d93d8288c33c8284d14ee0f45cd74bca321` |
| `novatel_gps_driver/include/novatel_gps_driver/parsers/header.h` (header length; read 2026-11-24) | `79c568fdc0bc9a2e29462c1d037e6cdec492f9d5541b86c40f1e42ad1cb320f4` |
| `novatel_gps_driver/src/novatel_message_extractor.cpp` (header length and CRC; read 2026-11-24) | `137b3b42eef4317f1f55f51460be10d286f29cdf4bb70ca9432d38eee7861c7e` |
| `novatel_gps_driver/include/novatel_gps_driver/novatel_message_extractor.h` (read 2026-11-24) | `8af67c88d0af2754acf7e6bfe6723a871b4ef6ee7c74535b664c0f6c0c430cc8` |
| `novatel_gps_driver/src/novatel_gps.cpp` (how BESTPOS feeds a fix) | `c368be67a72c95af0e3c74c32e81fd6bee28f731bec376ffb9829811638816e9` |

## Licence

Each file carries "Copyright (c) 2017, Southwest Research Institute (SwRI). All rights reserved." and the
three-clause BSD terms; the repository is BSD-3-Clause. Under this project's rule for code sources the
restated layout carries the default Apache-2.0 label. The NovAtel OEM7 documentation was not used.

This pack restates the layout (offsets, sizes, types) in its own words; no code or comment is copied.
The vectors are built by `tools/gen/gnssbin-vectors.py` from values chosen there; their expected bytes are
derived there, without an engine.

## Attribution

Layout from swri-robotics/novatel_gps_driver, https://github.com/swri-robotics/novatel_gps_driver
(BSD-3-Clause, Copyright (c) 2017 Southwest Research Institute), restated.
