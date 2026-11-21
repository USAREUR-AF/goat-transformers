# Provenance: sirf-binary pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| gpsd (the GPSD project) | https://gitlab.com/gpsd/gpsd | `edd38e78a875062f53add5c1ade745761240fffb` |

| File read | SHA-256 |
|---|---|
| `drivers/driver_sirf.c` | `f23065b04598555488037fbe83565c40f0d60beffa7fdcd9b9ebad2f85e90b4b` |
| `COPYING` | `fdf339997bbca9eaf507476b82fbcac608fc39a3d89b86b51e16db4c9f933716` |

## Licence

`COPYING` states that the compilation copyright is held by the GPSD project and that the licence is
BSD-2-Clause (its SPDX short identifier), followed by the two-clause terms. Under this project's rule for
code sources the restated layout carries the default Apache-2.0 label. The SiRF binary protocol reference
manual was not used.

This pack restates the layout (offsets, sizes, scale factors) in its own words; no code or comment is
copied. The vectors are built by `tools/gen/gnssbin-vectors.py` from values chosen there; their expected
bytes are derived there, without an engine.

## Attribution

Layout from gpsd drivers/driver_sirf.c, https://gitlab.com/gpsd/gpsd (BSD-2-Clause, compilation copyright
the GPSD project), restated.
