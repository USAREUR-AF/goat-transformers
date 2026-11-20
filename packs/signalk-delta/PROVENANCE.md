SPDX licence: CC-BY-SA-2.0

# Provenance of the signalk-delta pack

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
| `delta.json` | 3238 | `67e08b784d1de268fd2161e050043c1a11bb6f3ebd7d5c0254934626f0d0919a` |
| `definitions.json` | 28716 | `a919dfbe769208c37ff3de33bacc818e1b9a84f71208d182df77c62841098587` |

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
