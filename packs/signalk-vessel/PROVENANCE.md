SPDX licence: CC-BY-SA-2.0

# Provenance of the signalk-vessel pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/signalk-run.sh`) reads the files below. They are not kept in this repository. Read on 2026-11-20.

## Source

| | |
|---|---|
| Publisher | Signal K project |
| Address | https://github.com/SignalK/specification |
| Version | tag v1.8.6, commit 739ea90561750a76a7bdb30d5683a628205e1b41 |
| Files | under `schemas/` of the repository |

| File | Bytes | SHA-256 |
|---|---|---|
| `vessel.json` | 9103 | `7e273c2a5067ef5ff2a83738908b6c23072fdc9ab1b622a0b6a6d9555f151fb7` |
| `definitions.json` | 28716 | `a919dfbe769208c37ff3de33bacc818e1b9a84f71208d182df77c62841098587` |
| `groups/communication.json` | 1578 | `444395585d3defe84fc4edd01c54ffdee0d77a073114f775d27d35ebe1857271` |
| `groups/design.json` | 18329 | `4321d80cf569f80d307321fb2dd3516844f281dfacac68ff5e63dfc1fc234880` |
| `groups/electrical.json` | 22055 | `a07479ea899f72e1ea783264b4181ec333d22a7644b383ae744603fc75f9dad2` |
| `groups/environment.json` | 14576 | `34397f4583165a568d6998343fd827cb6bdd3f2df95a92e649341a3cb05775be` |
| `groups/navigation.json` | 28413 | `9578ef05f1655a7530bc2a9658f4c0745c8835c54de13c507ad52678c6cb6b15` |
| `groups/notifications.json` | 1873 | `1396819d172681fde72f7e608383cf51e0d67e26dcee5b885af8f416efd59b34` |
| `groups/performance.json` | 8795 | `ec12029d32e629575b4a0028dca447b8043bf05409d6f094f0f66ae4134ac98c` |
| `groups/propulsion.json` | 8111 | `caebdc9d08a91241e98790784fb6c0cb20fda9afa2d9acfb152bd22404b4b4d3` |
| `groups/resources.json` | 11907 | `f0af8e080ff3a38e0c71793116a62bc07a47a061bfab540a33a6b1016266a83d` |
| `groups/sails.json` | 3943 | `eacc87a592adee2587d8cec11818571441fae5db950c0950a3fd697d62982350` |
| `groups/sensors.json` | 1832 | `599574cd688e7fd543b78db5ea6dffa009c538d52d8b091e8c3141fd5d1ad8f7` |
| `groups/sources.json` | 5309 | `8942f48113de2de101f20ec38a7d7e3e55b52b3cc075714e2336699dadd336c5` |
| `groups/steering.json` | 4538 | `72e5748d465846d42a82fa96157323f540fb62ceb3fc0e1cd1f3461dfd5ebb1b` |
| `groups/tanks.json` | 3634 | `7192ecb5f7ab50b56cfc20e6181c14cfd3a971e5bea9339d6f769a4dd9dbd6cb` |

## Licence

The repository's `LICENSE` is the Creative Commons Attribution-ShareAlike 2.0
licence; it opens with its title line:

> Creative Commons Attribution-ShareAlike 2.0

and the repository's `package.json` states:

> "license": "CC-BY-SA-2.0",

A pack generated from the schemas is an adaptation of them, so it carries the same
licence: `CC-BY-SA-2.0`. Attribution: Signal K, https://signalk.org, schemas of the Signal K
specification. Share-alike: an adaptation of this pack must carry the same licence (or a
later version with the same elements). The pack is in the `open+copyleft` profile.
