# Provenance: igs-ssr pack

SPDX licence: LicenseRef-unstated

The IGS SSR format document states no licence, copyright or terms of use. The pack
and the module `igsssr` restate its message layouts (field order, bit widths and
resolutions) in this repository's words; no text or table is copied.

Read on 2026-11-20.

| | |
|---|---|
| Source | IGS State Space Representation (SSR) Format, Version 1.00, International GNSS Service, 2020-10-05 |
| Address | https://files.igs.org/pub/data/format/igs_ssr_v1.pdf |
| SHA-256 | `igs_ssr_v1.pdf` `2077dde0c87ff45069fd93ba44ee71a50657bddfc003f74f72316af5088f5f6e` |
| Sections used | 7 (data field table: ranges and resolutions), 8 (message tables of IGM01 to IGM07 and IM201), the table of IGS message numbers |

pyrtcm v1.2.1 (BSD-3-Clause), whose IGS definitions the `rtcm3` pack's generator
reads, was compared with the document; the pack follows the document where they
differ (see pack.md).
