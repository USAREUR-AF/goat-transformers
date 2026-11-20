# Provenance: omsf-json pack

SPDX licence: LicenseRef-unstated

Read on 2026-11-20. No source file is copied into this tree. The pack, the module `omsf`,
`pack.md` and the round-trip vectors are written by `tools/gen/jsonschema2pack.py`, run by
`tools/gen/omsf-run.sh`, from the schema file below.

## Pack `omsf-json`, module `omsf`

| | |
|---|---|
| Source | Observations and Measurements Simple Features profile (OMSF), GeoJSON encoding, Open Geospatial Consortium repository |
| Repository | https://github.com/opengeospatial/omsf-profile at commit `524c39dee7a4421b0b4b9d2b16714500ce8ac7f4` (2020-03-26) |
| File | `omsf-json/feature.json`, 8752 bytes, sha256 `3679223d7028887b75b37427eb71eef243dc852aaeaa831854cb8bd2ecc0d12b` |

## License

The source states no license. Where this was checked, at the commit above:

- the repository has no LICENSE, COPYING or NOTICE file;
- GitHub's repository metadata names no license;
- `README.md`, `omsf-json/README.md` and `omsf-json/feature.json` hold no license,
  copyright or rights notice.

The pack is labelled `LicenseRef-unstated` (`LICENSES/LicenseRef-unstated.txt`): no licence
is granted or implied for the source, and its commercial use is unknown until OGC states
terms. Under the operator's licensing model of 2026-11-20 a missing licence does not
exclude a format; the label lets the `open` profile leave it out.

## Other OMS JSON sources examined

`opengeospatial/om-swg` at commit `9a11d37ff55563e894fdbfe5e6f9f2c549c91cbe` holds JSON
schemas under `oms-abstract-spec/work/shapechange/results/ogc/oms/jsonschema/` (Abstract
Observation core, Abstract Sample core, Basic Observations, Basic Samples). The repository
states no license either (its README assigns contributions to OGC). They were not used:
they are working output of a model conversion with placeholder identifiers
(`http://fixme/...`) and define abstract classes and collections, not a concrete message.
