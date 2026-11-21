# Provenance of the celestrak-gp-json pack

SPDX licence: LicenseRef-unstated

`tools/gen/jsonschema2pack.py` (run script `tools/gen/space-run.sh`) generates this pack from this
project's restatement `tools/gen/space/celestrak-gp-objects.json` (SHA-256 `6ed4994914ba599403e6ba84245b9b8658dd2976f4db0f55746c18df0911434f`). Read on 2026-11-21.

## Sources

| Document | Address | Used for |
|---|---|---|
| CelesTrak, A New Way to Obtain GP Data, by T.S. Kelso (updated 2026-06-23) | https://celestrak.org/NORAD/documentation/gp-data-formats.php | the GP query, the JSON and CSV forms and which OMM keywords they leave out |
| CCSDS 502.0-B-3, Orbit Data Messages, April 2023 | https://ccsds.org/Pubs/502x0b3e1.pdf, SHA-256 `97d1687b4a461ffdf965b9b65923820cc6aa9d1d1c4d4df77a598a53d4a49d81` | the OMM keywords, their meanings and units (tables 4-1 to 4-3) |
| A GP response, `GROUP=stations&FORMAT=JSON`, 2026-11-21 | https://celestrak.org/NORAD/elements/gp.php | the JSON type of each member (numbers, integers, strings); not kept, and no value of it is in a vector |

## Licence

CelesTrak's pages carry no licence, copyright notice or terms of reuse for their text; the
usage policy (https://celestrak.org/usage-policy.php, read 2026-11-21) governs how often data
may be downloaded and says nothing about reuse. Under this project's rule for a source that
states no licence, the pack is labelled `LicenseRef-unstated` (`REUSE.toml` of this
directory) until a person resolves it. Nothing of CelesTrak's text is reprinted.

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
