SPDX licence: CC-BY-SA-2.0

This pack restates parts of the Signal K specification, which is licensed under Creative Commons
Attribution-ShareAlike 2.0. The pack, its module `signalk` and its vectors carry the same licence
(REUSE.toml; `LICENSES/CC-BY-SA-2.0.txt`), and the attribution is in `NOTICE`.

# Provenance

Written by hand from the JSON Schema files of the Signal K specification. No source file is copied
into this tree.

| | |
|---|---|
| Repository | https://github.com/SignalK/specification |
| Commit | `c6130b2a5e1a1700b25760dc86b2076d37277700` (committed 2026-11-10T16:50:49+01:00), the head of the default branch when read: tag `v1.8.6` and seven commits after it |
| Files read | `schemas/vessel.json`, `schemas/groups/navigation.json`, `schemas/definitions.json`, `schemas/delta.json` |
| Date read | 2026-11-20 |

## Licence

`LICENSE` at that commit is the full legal code of "Creative Commons Attribution-ShareAlike 2.0".
Its grant (section 3) lets anyone reproduce the work, make derivative works and distribute them,
commercially or not; section 4 requires that a derivative work be distributed only under the
same licence (or a later version or a later licence with the same elements), that the licence be
included or referred to by its address, and that credit be given to the original author and the
title of the work. The repository names no individual author; the work is credited as "the
Signal K specification, by the Signal K project (signalk.org)". GitHub reports the licence as
`NOASSERTION` because the file is not one of its recognised texts; the text is CC BY-SA 2.0.

## What this pack takes

Member names and nesting of the vessel object and its navigation group, of the delta message and
of the source object; the unit each schema states for a member (degrees for latitude and
longitude, radians for courses and headings, metres per second for speeds, RFC 3339 UTC text for
timestamps); the datum the position schema names (WGS 84). No description text of the schemas is
copied; pack.md states what is used in this repository's own words. The vectors are made by
`tools/gen/signalk-vectors.py`.

## SHA-256

```
7e273c2a5067ef5ff2a83738908b6c23072fdc9ab1b622a0b6a6d9555f151fb7  schemas/vessel.json
9578ef05f1655a7530bc2a9658f4c0745c8835c54de13c507ad52678c6cb6b15  schemas/groups/navigation.json
a919dfbe769208c37ff3de33bacc818e1b9a84f71208d182df77c62841098587  schemas/definitions.json
67e08b784d1de268fd2161e050043c1a11bb6f3ebd7d5c0254934626f0d0919a  schemas/delta.json
324f0cb5c623ce5e8c23b017e4906f1ba465b8412c49824b4c67c4ba1031d20c  LICENSE
```
