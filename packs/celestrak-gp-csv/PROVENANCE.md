# Provenance of the celestrak-gp-csv pack

SPDX licence: LicenseRef-unstated

Hand-written (`pack.def`, `pack.md`, `model/ckgpcsv.def`); the vectors are written by
`tools/gen/space-text-vectors.py`. Read on 2026-11-21.

## Sources

| Document | Address | Used for |
|---|---|---|
| CelesTrak, A New Way to Obtain GP Data, by T.S. Kelso (updated 2026-06-23) | https://celestrak.org/NORAD/documentation/gp-data-formats.php | the GP query, the JSON and CSV forms and which OMM keywords they leave out |
| CCSDS 502.0-B-3, Orbit Data Messages, April 2023 | https://ccsds.org/Pubs/502x0b3e1.pdf, SHA-256 `97d1687b4a461ffdf965b9b65923820cc6aa9d1d1c4d4df77a598a53d4a49d81` | the OMM keywords, their meanings and units (tables 4-1 to 4-3) |
| GP responses, `GROUP=stations&FORMAT=csv` and `GROUP=geo&FORMAT=csv`, 2026-11-21 | https://celestrak.org/NORAD/elements/gp.php | the order of the header's columns and the notation of numbers; not kept, and no row of them is in a vector |

## Licence

CelesTrak's pages carry no licence, copyright notice or terms of reuse for their text; the
usage policy (https://celestrak.org/usage-policy.php, read 2026-11-21) governs how often data
may be downloaded and says nothing about reuse. Under this project's rule for a source that
states no licence, the pack is labelled `LicenseRef-unstated` (`REUSE.toml` of this
directory and `model/ckgpcsv.def.license`; the `ckgp` keys it uses are labelled with `celestrak-gp-json`) until a person resolves it. Nothing of CelesTrak's text is reprinted.

The keyword names, meanings and units come from CCSDS 502.0-B-3. The terms of reuse of CCSDS
publications are the "Reproduction Permission Statement for Publications" on
https://ccsds.org/publications/ (read 2026-11-19 for `ccsds-ndm-xml`):

> In general, reasonable reuse of materials published in CCSDS documents is
> permitted with attribution, and reprint permission can be provided in
> writing for those organizations that require formal permission statements.

This pack reuses names and units with attribution here, in its `source` lines and in
`NOTICE`; it reprints no text or table of the Blue Book.

No document read carries a handling marking, a distribution statement or an export-control
notice.
