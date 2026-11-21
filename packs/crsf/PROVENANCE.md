# Provenance of the crsf pack

SPDX licence: CC-BY-SA-4.0

Written by hand from the TBS CRSF specification; the vectors by
`tools/gen/rc-telemetry-vectors.py`. The specification is not kept in this repository. Read
on 2026-11-20.

## Source

| | |
|---|---|
| Document | CRSF Protocol (CRSFv3), Team BlackSheep |
| Repository | https://github.com/tbs-fpv/tbs-crsf-spec, default branch, commit `a73f7dc5386e5b8744aa4a23b3af5354ee0d4c92` |
| File read | `crsf.md`, SHA-256 `58293cefb558425729b749f5d9700ba51a83cb578e9867dd1f94224303b6f918` (sections Frame Construction, CRC, Broadcast Frame Types) |
| License file | `LICENSE.md`, SHA-256 `57a4addf31dc9afbb2433a35966905774d9b26b2da44ad0caf9b8d8a4d1a35d7` |

ExpressLRS (GPL-3.0) implements the same protocol; it was not used as a source.

## Licence

The repository's `LICENSE.md` reads:

> [CRSF V3 Protocol Specification](https://github.com/tbs-fpv/tbs-crsf-spec) © 2020 by [TBS Avionics Co LTD](https://team-blacksheep.com) is licensed under [Creative Commons Attribution-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-sa/4.0/?ref=chooser-v1)

CC BY-SA 4.0 allows adaptation and commercial use, with attribution and the same licence on
an adaptation. This pack restates the frame layouts of the specification in the project's
own words (no text or table is copied) and is labelled `CC-BY-SA-4.0` (REUSE.toml).
Attribution: CRSF V3 Protocol Specification, © 2020 TBS Avionics Co LTD.
