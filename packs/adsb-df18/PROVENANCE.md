# Provenance: adsb-df18 pack

Read on 2026-11-19. No source file is copied into this tree. The pack holds
field positions and widths restated from the decoder below; the vectors hold
four published messages and constructed ones, with bytes computed by
`tools/gen/adsb-vectors.py`.

## pyModeS

| | |
|---|---|
| Source | pyModeS, https://github.com/junzis/pyModeS |
| Version | commit `4bf083284c0d9878ca0c88f16b9b5f6514ca194a`; `pyproject.toml` version 3.7.0 |
| Download | `https://codeload.github.com/junzis/pyModeS/tar.gz/4bf083284c0d9878ca0c88f16b9b5f6514ca194a`, SHA-256 `6f7ddcce89bf792acd3b732c477d4b22061b87465ccd550c3da5dc77e02060a9` |
| License | `LICENSE` is the GNU General Public License, Version 3, 29 June 2007 |

Files read for layouts: `src/pyModeS/decoder/adsb.py` (the frame, and one
dispatch for downlink formats 17 and 18), `decoder/bds/bds05.py`, `bds06.py`,
`bds08.py`, `bds09.py`, `bds30.py`, `bds61.py`, `bds62.py`, `bds65.py`,
`_callsign.py`, `_idcode.py`, `_bits.py` (the parity polynomial) and
`position/_cpr.py` (the surface position check of vector 35).

Files read for messages and decoded values: `tests/test_adsb.py`,
`test_bds06.py`, `test_bds08.py`, `test_cpr.py`.

No pyModeS code is copied or adapted into the pack, the model or the
generator. The positions in pyModeS docstrings and shifts are restated as
`<word>:<bit>:<len>` locators (pyModeS payload bit *b*, numbered from 0, is
ME bit *b* + 1 and message offset 32 + *b*). The generator's check of vector
35 states the surface CPR resolution in its own code.

As a further check, after the vectors were written, every one with a `model`
was decoded by pyModeS itself (run outside the tree) and its pinned values
(address, type code, CPR fields, category, movement, emergency state,
capability class, operational mode, version, selected altitude, ACAS
indicator, threat address, range and bearing) were compared: all agree. The
expected bytes were not taken from pyModeS; they are those of `tools/gen/adsb-vectors.py`.

Not read: "The 1090 Megahertz Riddle" (CC BY-NC-SA 4.0), RTCA DO-260B and
ICAO Annex 10 (priced).

### "Not available" values (version 0.2)

The `absent` options of version 0.2 restate what pyModeS's decoders at the commit above read as not available: `decoder/bds/bds06.py` (movement 0 and above 124), `bds09.py` (velocity, vertical rate and airspeed magnitude 0; GNSS-baro difference 0 and 127), `bds62.py` (selected altitude and barometric setting 0) and `bds30.py` (threat range and bearing 0). Read on 2026-11-19; no code copied.

### The callsign (version 0.3)

The `chars:icao6` binding of the identification characters rests on pyModeS
`src/pyModeS/_callsign.py` at the commit above, which builds the 64-entry
alphabet of the field (1-26 letters, 32 space, 48-57 digits, every other code
invalid). Read on 2026-11-19; no code copied.

