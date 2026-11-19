# Pack: adsb-df18

ADS-B on Mode S Extended Squitter downlink format 18: the 112-bit message that
equipment other than a transponder sends, and that ground stations use for
TIS-B and ADS-R. Public. Every layout is from pyModeS (GPL-3.0, commit
`4bf083284c0d9878ca0c88f16b9b5f6514ca194a`), restated; no other source was
read for this pack. I/O is hex text. Needs engine version 0.9 (`absent`).

Uses the modules `core` and `adsb` (`model/adsb.def`). `pack.def` is maintained
by hand, kind for kind with the pack `adsb`. Its vectors are written by
`tools/gen/adsb-vectors.py`, which holds its own copy of the layouts.

## Same layouts as downlink format 17

pyModeS `decoder/adsb.py` registers one decoder for downlink formats 17 and 18
and states that both have the same 112-bit layout and the same ME field
format, dispatched on the type code. So this pack has the kinds of `adsb`,
with the same raw keys of the module `adsb`, and differs in three places:

| Place | `adsb` | `adsb-df18` |
|---|---|---|
| bits 1-5 | `when 0:0:5 17` | `when 0:0:5 18` |
| bits 6-8 | `adsb.ca` (capability) | `adsb.cf` (control field) |
| `operational-status-surface`, ME bits 9-24 | two keys, `surface_capability_class` (12 bits) and `length_width` (4 bits) | one key, `capability_class` (16 bits), the region pyModeS `decoder/bds/bds65.py` reads as one raw value |

## What the source does not say, and what this pack therefore does

- **The control field.** pyModeS reads bits 6-8 of a DF18 message as "CA/CF"
  and does not interpret them. `adsb.cf` holds the value as received.
- **The address.** pyModeS reads bits 9-32 as the ICAO address in every DF18
  message, whatever the control field holds. This pack does the same
  (`adsb.icao`). A receiver that knows the control field marks a non-ICAO
  address, or a TIS-B format other than the ones pyModeS decodes, must
  check `adsb.cf` itself: the pack decodes every DF18 message with the
  layouts above.
- **Parity.** As in `adsb`, `adsb.parity` is carried, not computed or
  checked.

## Shared keys

None, as in `adsb`: each value needs a decoding step the pack language does
not have (CPR position, Q-bit altitude, interleaved Mode A code, sign and
magnitude velocity); `adsb/pack.md`, "Kept raw", lists them and the addition
each needs. The keys are those of the module `adsb`, so a conversion between
`adsb-df18` and `adsb` carries them, with two limits: the target writes its own
downlink format, and the target kind is chosen by `requires`, so within a
type code group (1-4, 5-8, 9-18, 20-22) the lowest type code is written
(`adsb/pack.md`, "One kind per type code"). No vector pins such a conversion:
re-sending a TIS-B or ADS-R report as DF17 is not a use the source describes.

## Kinds

32 kinds, as listed in `adsb/pack.md` ("Kinds"), every one mapping all 112
bits. pyModeS confirms each layout:

| Kinds | pyModeS |
|---|---|
| `identification-tc1` ... `-tc4` | `decoder/bds/bds08.py`, `_callsign.py` |
| `surface-position-tc5` ... `-tc8` | `decoder/bds/bds06.py` |
| `airborne-position-baro-tc9` ... `-tc18`, `airborne-position-gnss-tc20` ... `-tc22` | `decoder/bds/bds05.py` |
| `airborne-velocity-*-st1` ... `-st4` | `decoder/bds/bds09.py` |
| `aircraft-status-emergency` | `decoder/bds/bds61.py` subtype 1, `_idcode.py` |
| `acas-ra-*` (three kinds by threat type indicator) | `decoder/bds/bds61.py` subtype 2, `decoder/bds/bds30.py` |
| `target-state` | `decoder/bds/bds62.py` (the 9-bit selected heading is held as a sign bit and 8 bits, which is the same value: raw x 360/512 = sign x 180 + low 8 bits x 180/256) |
| `operational-status-airborne`, `-surface` | `decoder/bds/bds65.py` |

## Not mapped

- Type code 0, 23-27, 30, and the reserved subtypes: `no-kind`.
- Type code 29 subtype 0: pyModeS does not state its layout (see
  `adsb/pack.md`, "Not mapped").
- ACAS threat type indicator 3 (reserved): `no-kind`.
- Any control-field-dependent format, for the reason above.

## "Not available" values (engine-spec 0.9)

Version 0.2 of the pack marks the raw values pyModeS's decoders read as not
available with the field option `absent`: decode gives no key, and an entity
without the key writes the first value listed.

| Keys | `absent` | pyModeS |
|---|---|---|
| `adsb.movement_raw` | 0, 125, 126, 127 | `decoder/bds/bds06.py`: movement 0 or above 124 |
| `adsb.ew_raw`, `adsb.ns_raw`, `adsb.vr_raw`, `adsb.airspeed_raw` | 0 | `decoder/bds/bds09.py`: a magnitude of 0 |
| `adsb.galt_diff_raw` | 0, 127 | `decoder/bds/bds09.py`: difference 0 or 127 |
| `adsb.sel_alt_raw`, `adsb.baro_setting_raw` | 0 | `decoder/bds/bds62.py`: N/A |
| `adsb.threat_range_raw`, `adsb.threat_bearing_raw` | 0 | `decoder/bds/bds30.py`: range or bearing 0 |

A message holding 127 or 125-126 in such a field is written back with the
first value, 0 (engine-spec 0.9 ruling 7); no vector of version 0.1 holds one.
The keys stay raw: the sign-and-magnitude and piecewise values still need the
transforms listed under "Kept raw".

## Vectors

40 vectors under `vectors/`, written and replayed by
`tools/gen/adsb-vectors.py`, which reads no pack and imports no engine
(`--check` compares its output with the tree).

| Vectors | Content | Source |
|---|---|---|
| 01-32 | one same-format round trip per kind; parity computed by the script with the Mode S generator polynomial | constructed |
| 33 | `90406B902015A678D4D220AA4BDA`: the DF17 identification message with the downlink format changed to 18, as pyModeS `tests/test_adsb.py` builds it (its parity is that of the DF17 message) | pyModeS |
| 34, 35 | `903A23FF426A38565950432EBF95`, `903A23FF426A4E65F7487A775D17`: a real even and odd DF18 surface position pair of ICAO 3A23FF; the script resolves the odd frame against the reference 43.63, 1.37 to 43.62646, 1.37476 within 0.001 degrees, as `tests/test_cpr.py` asserts | pyModeS |
| 36 | `903A33FF40100858D34FF3CCE976`: surface position with movement code 1 (stopped), `tests/test_bds06.py` | pyModeS |
| 37 | a DF17 message: `no-kind` | pyModeS `tests/test_bds08.py` |
| 38 | type code 0: `no-kind` | constructed |
| 39 | ACAS threat type indicator 3: `no-kind` | constructed |
| 40 | surface position with movement code 126: no movement key, written back as 0 | constructed |
