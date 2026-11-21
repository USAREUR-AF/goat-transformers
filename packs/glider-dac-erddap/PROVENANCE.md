# Provenance of the glider-dac-erddap pack

SPDX licence: LicenseRef-unstated

`tools/gen/jsonschema2pack.py` (run script `tools/gen/ocean-run.sh`) generates this pack from
`tools/gen/ocean/glider-dac-erddap-objects.json` (SHA-256
`75a7b72764c7d9729526e234562887e69a0bf1e081bbe1554193b4a1820cd3a5`), this project's restatement of
the variables it reads. Read on 2026-11-21.

## Source

| | |
|---|---|
| Document | IOOS National Glider Data Assembly Center NetCDF file format, template version 3 |
| Repository | https://github.com/ioos/ioosngdac, commit `f8d8204e219e27729b94b046a94d48e818dbc7b4`, `nc/template/IOOS_Glider_NetCDF_v3.0-noqartod.cdl` (variables, units, the WGS84 reference and EPSG 4326 of `lat` and `lon`) |
| Observed | the variable list and a .jsonlKVP response of the DAC's ERDDAP server, https://gliders.ioos.us/erddap/ (dataset `amelia-20180501T0000`, read 2026-11-21) |

## Licence

The ioos/ioosngdac repository states no licence (no licence file; GitHub names none). The
template's global `license` attribute concerns the data files made from it ("This data may be
redistributed and used without restriction"), not the template. Under the project's rule for a
source that states no licence, the pack is labelled `LicenseRef-unstated`
(`packs/glider-dac-erddap/REUSE.toml`, `model/gliderdac.def.license`).
