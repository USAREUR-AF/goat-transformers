# Provenance: tasmota-result

Written by hand from the source of Tasmota. No source file is copied into this tree, and no code
or comment is restated: only the member names and the nesting of the JSON the firmware publishes.

| | |
|---|---|
| Repository | https://github.com/arendst/Tasmota |
| Tag | `v16.0.0`, commit `1c2173927cdf1be61759bcc3b064b9511a18e5d7`, the latest release when read |
| Files read | `tasmota/tasmota_support/support_tasmota.ino` (the STATE object), `tasmota/tasmota_xdrv_driver/xdrv_03_energy.ino` (the ENERGY member), `tasmota/tasmota_xsns_sensor/xsns_05_ds18x20.ino`, `xsns_09_bmp.ino`, `xsns_06_dht_v6.ino` (the sensor members), `tasmota/include/i18n.h` (the JSON member name constants) |
| Date read | 2026-11-21 |

## Licence

`LICENSE.txt` at the tag is the GNU General Public License, version 3; the file headers name
Theo Arends (with co-authors for some drivers) as copyright holder. GitHub reports the repository
as `GPL-3.0`.

This pack restates a data layout (member names, nesting, value types) in this repository's words
and copies no code, so it is labelled Apache-2.0 with the source named (rule 17 of the pack
brief).

## What this repository takes

The member names of the STATE, SENSOR and RESULT objects listed in pack.md, which members are
nested in which, and the JSON type each is written as. The units are those the firmware's own
web page and console show for the same values.

## Attribution

Member names and nesting of the STATE, SENSOR and RESULT payloads, from Tasmota,
https://github.com/arendst/Tasmota tag v16.0.0 commit 1c217392. Copyright (C) Theo Arends and
contributors. GNU GPL v3. A data layout restated; no code or comments copied.

## SHA-256

```
7d03107e59a6e7645024e9c6e59f26af81412ca0776b95c054b999bc0d35b22c  tasmota/tasmota_support/support_tasmota.ino
5f59220b3d1eb59e48f97224b75d25622500a64abe3396ca57b3722ab4b4f7b3  tasmota/tasmota_xdrv_driver/xdrv_03_energy.ino
957ed28c42ee5c381ab89f4274c74aa5104ae094e296d3b99ca56e48bffc9df6  tasmota/tasmota_xsns_sensor/xsns_05_ds18x20.ino
2a56fdaed4e471d450e1d0b05f6811385a4b5120dfdcce40f433c373985adda4  tasmota/tasmota_xsns_sensor/xsns_09_bmp.ino
e138d3cb749e1b9bd3c8711332824eba47a6583cc5b0958d0cad720b6f7971f3  tasmota/tasmota_xsns_sensor/xsns_06_dht_v6.ino
7050acdcf7307339445fe7b18226f5ca7d7ba05457143886a57b34a4d447b9b9  tasmota/include/i18n.h
b98fbb37db5b23bc5cfdcd16793206a5a7120a7b01f75374e5e0888376e4691c  LICENSE.txt
```
