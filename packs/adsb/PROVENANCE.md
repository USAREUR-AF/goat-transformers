# Provenance: adsb pack

## Pack `adsb`, module `adsb`

### The 1090 Megahertz Riddle

| | |
|---|---|
| Source | Junzi Sun, "The 1090 Megahertz Riddle: A Guide to Decoding Mode S and ADS-B Signals", second edition, TU Delft OPEN Publishing |
| URL | https://mode-s.org/1090mhz/ ; publisher's version https://doi.org/10.34641/mg.11 |
| Pages read | `content/ads-b/1-basics.html` to `6-operation-status.html` |

The license statement on the book's index page:

> This book is published by TU Delft OPEN Publishing as an open access book,
> under CC BY-NC-SA-4.0 license:
> https://creativecommons.org/licenses/by-nc-sa/4.0/.

> © Copyright 2021 Junzi Sun.

**The license is CC BY-NC-SA 4.0 (Attribution-NonCommercial-ShareAlike), not
CC BY-SA.** No text, table or figure of the book is reproduced in this tree.
What is taken is the bit position and width of each field, the meaning of
each code, and five example messages with their decoded values.

The layouts the book documents are those of ICAO Annex 10 Volume IV, ICAO Doc
9871 (Technical Provisions for Mode S Services and Extended Squitter) and RTCA
DO-260B. Those documents were not read.

Used for: the frame structure; type codes 1-4, 5-8, 9-18, 19 (subtypes 1-4),
20-22 and 31 (versions 1 and 2).

### pyModeS

| | |
|---|---|
| Source | pyModeS, https://github.com/junzis/pyModeS |
| Version | `master` at commit `4bf083284c0d9878ca0c88f16b9b5f6514ca194a`; `pyproject.toml` version 3.7.0 |
| License | `LICENSE` is the GNU General Public License, Version 3, 29 June 2007; README: "License: GPL-3.0 (see `LICENSE`)" |
| Files read | `tests/test_adsb.py`, `test_bds05.py`, `test_bds06.py`, `test_bds08.py`, `test_bds09.py`, `test_bds61.py`, `test_bds62.py`, `test_bds65.py` |

No pyModeS code is copied or adapted. What is taken is message hex strings and
the decoded values the tests assert for them. The pack and its vectors are
maintained by hand; the values (callsign, Q-bit altitude, Mode A code, velocity, parity)
were checked with decoders written from the book's descriptions.

Used for: nine of the published-message vectors, and as the check on the type
code 28 subtype 1 and type code 29 subtype 1 layouts, which the book names but
does not lay out bit by bit. Those two layouts are DO-260B's as generally
documented; the pack's reading of them reproduces every value the tests assert
(emergency state 0 and squawk 6513; selected altitude 16992 ft, barometric
setting 1012.8 hPa, selected heading 66.8 and 246.8, autopilot, VNAV, altitude
hold, approach, TCAS and LNAV bits).

### pyModeS decoder code (type code 28 subtype 2)

The three `acas-ra-*` kinds (vectors 46-49) are laid out from pyModeS alone, at
the commit above: `src/pyModeS/decoder/bds/bds61.py` (subtype 2 carries bits
8-55 of the BDS 3,0 register) and `decoder/bds/bds30.py` (the place of each
advisory and complement flag, the threat type indicator, and the threat
identity for indicators 1 and 2; indicator 3 reserved). Positions are restated;
no code is copied. Archive
`https://codeload.github.com/junzis/pyModeS/tar.gz/4bf083284c0d9878ca0c88f16b9b5f6514ca194a`,
SHA-256 `6f7ddcce89bf792acd3b732c477d4b22061b87465ccd550c3da5dc77e02060a9`. pyModeS
publishes no message of this subtype; the vectors are constructed, and after
they were written pyModeS itself decoded each one (outside the tree) to the
same advisory flag, indicator, threat address, range and bearing. Read on
2026-11-19.

### Published messages used as vectors

| Vector | Message | Published in |
|---|---|---|
| 30 | `8D4840D6202CC371C32CE0576098` | book, chapters 1 and 2 |
| 31 | `8D406B902015A678D4D220AA4BDA` | pyModeS `test_bds08.py`, `test_adsb.py` |
| 32, 33 | `8D40621D58C382D690C8AC2863A7`, `8D40621D58C386435CC412692AD6` | book, chapter 3 |
| 34, 35 | `8D40058B58C901375147EFD09357`, `8D40058B58C904A87F402D3B8C59` | pyModeS `test_bds05.py` |
| 36 | `8D485020994409940838175B284F` | book, chapter 5; pyModeS `test_bds09.py` |
| 37 | `8DA05F219B06B6AF189400CBC33F` | book, chapter 5; pyModeS `test_bds09.py` |
| 38, 39 | `8C4841753AAB238733C8CD4020B1`, `8C4841753A8A35323FAEBDAC702D` | book, chapter 4 |
| 40 | `8C4841753A9A153237AEF0F275BE` | book, chapter 4 |
| 41 | `8DA2C1B6E112B600000000760759` | pyModeS `test_bds61.py` |
| 42, 43 | `8DA05629EA21485CBF3F8CADAEEB`, `8DA05629EA21485EBF3F8CADAEEB` | pyModeS `test_bds62.py` |
| 44 | `90406B902015A678D4D220AA4BDA` | pyModeS `test_adsb.py` |

## Other inputs

`packs/geojson/pack.def` and `model/core.def` of this repository were read
to compute the GeoJSON expectations and to check key types.

### "Not available" values (version 0.2)

The `absent` options of version 0.2 restate what pyModeS's decoders at the commit above read as not available: `decoder/bds/bds06.py` (movement 0 and above 124), `bds09.py` (velocity, vertical rate and airspeed magnitude 0; GNSS-baro difference 0 and 127), `bds62.py` (selected altitude and barometric setting 0) and `bds30.py` (threat range and bearing 0). Read on 2026-11-19; no code copied.

### The callsign (version 0.3)

The `chars:icao6` binding of the identification characters rests on pyModeS
`src/pyModeS/_callsign.py` at the commit above, which builds the 64-entry
alphabet of the field (1-26 letters, 32 space, 48-57 digits, every other code
invalid). Read on 2026-11-19; no code copied.

## Golden vectors: pyModeS

`packs/adsb/vectors/golden-*.json` are written by `tools/gen/golden-pymodes.py`
from pyModeS, a reference Mode S and ADS-B decoder, not from this pack and not
by any engine (shared-model hardening, item 2). pyModeS decodes only, so the
inputs are the real DF17 messages of its own test suite, and the model values
are what pyModeS decodes from them.

| | |
|---|---|
| Package | pyModeS 3.7.0, wheel `pymodes-3.7.0-py3-none-any.whl`, SHA-256 `78e64e9c9ac81c6ea986b1a77729c1c517b5d6200c17418ca4ae0db3c4478c3d`; pinned in `tools/gen/golden-pymodes.txt`, installed with `pip --require-hashes` |
| Messages | https://github.com/junzis/pyModeS at commit `4bf083284c0d9878ca0c88f16b9b5f6514ca194a` (tag v3.7.0): `tests/data/sample_data_adsb.csv` (SHA-256 `7534e8186adec1aa44589c27d6059d0cde102c12d7e77c2584041f33afb99d9f`) and the messages written into eight `tests/*.py` files, each refused unless its SHA-256 is the one the script records |
| Licence | GPL-3.0 (the wheel's `LICENSE`, GNU General Public License, Version 3). pyModeS is run, not copied: it is installed outside the tree to write the vectors, and only its output and its published test messages (the capture and the hex strings of its tests) enter this repository; no line of its code does |
