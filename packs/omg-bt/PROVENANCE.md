# Provenance: omg-bt

Written by hand from the source of OpenMQTTGateway. No source file is copied into this tree, and
no code or comment is restated: only the member names and the JSON types of the payload.

| | |
|---|---|
| Repository | https://github.com/1technophile/OpenMQTTGateway |
| Tag | `v1.9.1`, commit `1b28de93a4853020e4ad39c4a25562c23218d818`, the latest release when read |
| Files read | `main/gatewayBT.cpp` (the BLE payload and the members the decoder adds), `main/gatewayRF.cpp` (the RCSwitch payload) |
| Date read | 2026-11-21 |
| Member names | Theengs Decoder `v2.5.0`, commit `08531d205d491457d9d8ccf4e0ecdfe90b60c513`, the version OpenMQTTGateway v1.9.1 fetches (`platformio.ini`); https://github.com/theengs/decoder. `src/decoder.cpp` (SHA-256 `a2f36948b3be8f55ed19062fcb6185c8187913f4860d6ea998bb6d411c7ca5b7`): `brand` is copied into the payload, and `tempf` is added beside every `tempc`; `src/devices/LYWSD03MMC_json.h` (SHA-256 `e675c5839d1f61bcdb13feba53e0d89e301f96ffa4de09f2c2f45a616d71c85e`) and the other device files name `tempc`, `hum`, `batt`, `volt`. Read 2026-11-26. |

## Licence

`LICENSE.txt` at the tag is the GNU General Public License, version 3; the file headers name
Florian Robert as copyright holder. GitHub reports the repository as `GPL-3.0`.

This pack restates a data layout (member names and value types) in this repository's words and
copies no code, so it is labelled Apache-2.0 with the source named (rule 17 of the pack brief).

## What this repository takes

The member names and JSON types of the BTtoMQTT and RFtoMQTT payloads listed in pack.md.

## Attribution

Member names of the BTtoMQTT and RFtoMQTT payloads, from OpenMQTTGateway,
https://github.com/1technophile/OpenMQTTGateway tag v1.9.1 commit 1b28de93. Copyright Florian
Robert. GNU GPL v3. A data layout restated; no code or comments copied.

## SHA-256

```
fda372e69df06539ff35e1e16985a85d7f7731cab32a150911182dedb40f469a  main/gatewayBT.cpp
103951b28572adccc4e799fc648bad007fe5fd2f4ee7ca3366da4d3c310fb42c  main/gatewayRF.cpp
8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903  LICENSE.txt
```
