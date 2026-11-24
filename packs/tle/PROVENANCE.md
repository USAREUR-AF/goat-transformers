# Provenance of the tle pack

SPDX licence: LicenseRef-unstated

Hand-written (`pack.def`, `pack.md`, `model/tle.def`); the vectors are written by
`tools/gen/space-text-vectors.py`. Read on 2026-11-21.

## Sources

| Document | Address | Used for |
|---|---|---|
| CelesTrak, NORAD Two-Line Element Set Format, by T.S. Kelso (last updated 2022-07-01) | https://celestrak.org/NORAD/documentation/tle-fmt.php | the columns of lines 0, 1 and 2, the assumed decimal points and the checksum rule |
| CelesTrak, FAQ: Two-Line Element Set Format (Satellite Times, volume 4 number 3) | https://celestrak.org/columns/v04n03/, read 2026-11-24 | the reading of the two-digit epoch year |
| A GP response, `GROUP=stations&FORMAT=tle`, 2026-11-21 | https://celestrak.org/NORAD/elements/gp.php | the CR LF line ends and the space padding of numeric columns; not kept, and no line of it is in a vector |
| CelesTrak, A New Way to Obtain GP Data (updated 2026-06-23) | https://celestrak.org/NORAD/documentation/gp-data-formats.php | that objects numbered 100000 and up have no TLE |

## Licence

CelesTrak's pages carry no licence, copyright notice or terms of reuse for their text; the
usage policy (https://celestrak.org/usage-policy.php, read 2026-11-21) governs how often data
may be downloaded and says nothing about reuse. The format page describes the element set
format of NORAD and NASA (it names ADCOM/DO Form 12 as the further reference). Under this
project's rule for a source that states no licence, the pack is labelled
`LicenseRef-unstated` (`REUSE.toml` of this directory and `model/tle.def.license`) until a
person resolves it. The column positions and meanings are restated in this project's words;
no text or example of the page is reprinted.

No document read carries a handling marking, a distribution statement or an export-control
notice.
