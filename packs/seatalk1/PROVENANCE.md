# Provenance: seatalk1 pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | Commit |
|---|---|---|
| SignalK/signalk-parser-nmea0183 (Signal K and contributors) | https://github.com/SignalK/signalk-parser-nmea0183 | `5ab479bcfc1bec0d36f98616e5f9be96f52e3f23` |

| File read | SHA-256 |
|---|---|
| `src/hooks/seatalk/0x00.ts` | `4efe9ca7c1ad66a63d6c2c07160971c960af189369762db2aa00c0da1c99b655` |
| `src/hooks/seatalk/0x10.ts` | `1190343289aa0ce76f7c71a4ea50b5d21235f652e8d3982646dde4419f376655` |
| `src/hooks/seatalk/0x11.ts` | `8e9eed22ee4c25cd78a4694d5f2fc73ec9c52e91ec1a3957ac05dd3859df5e30` |
| `src/hooks/seatalk/0x20.ts` | `eff7ab9597ea2e1996847501afe71f1a4d862b89ff85991fbf69f6e835bb5f91` |
| `src/hooks/seatalk/0x21.ts` | `f6699ea486e5cec6e930d77b502c87a5f26352f9815be07442b2696c04f50926` |
| `src/hooks/seatalk/0x22.ts` | `e03f548a85f8dab5192ccc1033bd3fd940d3e724513225e24e9e587b97ebca96` |
| `src/hooks/seatalk/0x25.ts` | `37fffa8ebe3934c81a06601ed5a1b8dbd5221995bf120813d717ec169dc679c2` |
| `src/hooks/seatalk/0x26.ts` | `ec31fae1c33d39ba4e78f57c3926442e205bbef81eee511846b020656abad0eb` |
| `src/hooks/seatalk/0x27.ts` | `461b989f1970ac675c42da8e3aad8f8cdb5d6690cc989c17eb24213f3e8cc337` |
| `src/hooks/seatalk/0x50.ts` | `c2720205c96e838b653b2eebdedabde2ba896264125b5574de4622b36145072a` |
| `src/hooks/seatalk/0x51.ts` | `22e1cf1e9e974d89c0312419653f206494af26d9c7d78a2b6139a70f8e5cacfc` |
| `src/hooks/seatalk/0x52.ts` | `50a946a44ef91cf81388ee105b6227b5cc37abe032dc22269d835abca73bd7f4` |
| `src/hooks/seatalk/0x53.ts` | `7ae961a33873d0a9decc88702db081de84626d4be28fbec25e9289e14fa04ec0` |
| `src/hooks/seatalk/0x54.ts` | `557cab51ea1aca8335871978458549c2c1f71a42d413463eb4c1db7ffd5bd4e4` |
| `src/hooks/seatalk/0x56.ts` | `a4b4637a035d5814dac147860fdaadb6c4a255e4dcff4264dfd686599ff50c3b` |
| `src/hooks/seatalk/0x57.ts` | `063e44de64869a5e9ca74dddaf74cc47c4f3ecdf393406fa9edb201040939615` |
| `src/hooks/seatalk/0x82.ts` | `58c79a4092dcb6417aaa8f255bfa50ded5d5ce336be176ca08dfa4cc5c1e89fa` |
| `src/hooks/seatalk/0x84.ts` | `6c8ee9ea82fe8eeb9375beaeb8b9b141dd6d49f44657d04acf31dcce7c6a26f0` |
| `src/hooks/seatalk/0x85.ts` | `dabef2fb075a7efcd092ae8328b7375ddf0f7f8b58b1be064a6d82a066a75fd5` |
| `src/hooks/seatalk/0x99.ts` | `e02cbd5d95f630e661bec0dd97ae66a3656c20e80fa95e06875ea4ae1e2bfd84` |
| `src/hooks/seatalk/0x9C.ts` | `cd06bcf1c95b2ad57f1833d079fa0c2c44b3d73c8b2c1dd6e59f93baa3b55b83` |
| `src/hooks/seatalk/compass-heading.ts` | `7df04c0f2ac663b52b80428e3981712d31b54b28d131a49a50321fc5647c0652` |
| `src/hooks/seatalk/index.ts` | `907245b10b2cfeff90a95ffaffac6b1d4e69c8f5f4b118cbd24a7f7270d9f8f3` |
| `LICENSE` | `b0f5b13f9838f5a5683e1a4ce76738879901e15cd8ee88415188b60ade4590be` |

## Licence

`LICENSE` and each hook file carry the Apache License 2.0 ("Copyright 2016/2017 Signal K and Fabian Tollenaar",
"Copyright 2016 Signal K and contributors"). The pack keeps the default Apache-2.0 label.

The hook files' comments cite Thomas Knauf's SeaTalk Technical Reference and the marnav project; those
were not read for this pack, and no comment text is copied. Raymarine's own SeaTalk documentation:
not read.

This pack restates the layouts (octet order, nibbles, bits, scale factors) in its own words. The vectors
are built by `tools/gen/seatalk-vectors.py` from values chosen there; their expected bytes are derived
there, without an engine.

## Attribution

Layouts from SignalK/signalk-parser-nmea0183, https://github.com/SignalK/signalk-parser-nmea0183 (Apache
License 2.0, Copyright Signal K and contributors), restated.
