SPDX licence: Apache-2.0

This repository's restatement of facts (field positions, widths, codes) is Apache-2.0. The source
it read is GPL-2.0-or-later with the Classpath Exception; no code or text of it is copied, as for
the facts taken from pyModeS (GPL) for the `adsb` pack. The source's notice is in `NOTICE`.

# Provenance: knx-ip

Written by hand from calimero-core. No source file is copied into this tree.

| | |
|---|---|
| Repository | https://github.com/calimero-project/calimero-core |
| Commit | `68c99bffb5d065220410311fbdf8f372fd84555e` (committed 2026-11-17T19:29:18+01:00), the head of the default branch when read (the last tag is `v3.0-M2`) |
| Files read | `src/io/calimero/cemi/CEMILData.java` (the L_Data frame), `knxnetip/servicetype/KNXnetIPHeader.java`, `ServiceRequest.java`, `ServiceAck.java` (the KNXnet/IP header, the connection header, the acknowledge), `DataUnitBuilder.java` and `process/ProcessCommunicatorImpl.java` (the APCI and the six-bit data), `dptxlator/DPTXlatorBoolean.java`, `DPTXlator8BitUnsigned.java`, `DPTXlator2ByteFloat.java`, `DPTXlator4ByteFloat.java` (where each DPT's value sits and how it reads) |
| Date read | 2026-11-20 |
| Not used | the KNX Standard of the KNX Association, a paid document not held |

## Licence

`LICENSE.txt` at that commit states that the software is distributed under the GNU General Public
License, version 2, with the Classpath Exception, followed by the GPL text; each file's header
licenses it under version 2 or, at the user's option, any later version, and adds the exception
that allows linking independent modules. GitHub reports the licence as `NOASSERTION`.

## SHA-256

```
9be8328edb34c02af6897efcfe072620bb88ac4569798541eba3f5d7f14b1051  cemi/CEMILData.java
3a0eca6f012e4fca77499b2c8c4cb77db5a0c04fb9f8423dd1a790eea72f69d6  knxnetip/servicetype/KNXnetIPHeader.java
d87c29afd4d9e713070add6e4ebb9b2d5e26baec9982be5a122a7952d4adb075  DataUnitBuilder.java
3834542e5967137b5de4e6e64b8332cf39ee10c20b5b7bf4920bfc4959e4a2a8  process/ProcessCommunicatorImpl.java
af83d275324a96f2f0db43159f038b966f051b9c3df9211b2d0dcf4ddc58a861  dptxlator/DPTXlatorBoolean.java
f4a4d019c9f7ce56a4f4d0d780d1cc11fa510497d2d55cd14f79cac2462321f8  dptxlator/DPTXlator8BitUnsigned.java
b87cc7c18eeb37a023d074f846289fd203a9eb04f6a7b884b23a2ac09849423f  dptxlator/DPTXlator2ByteFloat.java
79e891f2a8ba17502a9f1cb79bfe741b778e2875d6b870beb62f78e39305e976  dptxlator/DPTXlator4ByteFloat.java
40716785e4d8b6c6053aeb014ece4b4cf5ba6507715063460445774c20706c9e  LICENSE.txt
```
