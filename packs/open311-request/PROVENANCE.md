# Provenance of the open311-request pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/open311-run.sh`) reads the files below and nothing
else. They are not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | Open311 GeoReport v2, definition `Request`, Swagger 2.0 YAML |
| Publisher | Open311 community |
| Repository | https://github.com/open311/open311.github.io at commit `d65f0b9a6fb527bcb1836b1f986c5375c39541e1` |
| Download | `https://raw.githubusercontent.com/open311/open311.github.io/d65f0b9a6fb527bcb1836b1f986c5375c39541e1/data/georeport_v2-1.yaml` |

| File | SHA-256 |
|---|---|
| `data/georeport_v2-1.yaml` | `038ac7f5c1dea29bb743cc9d136b4c1dbd897fc008e7362fd16eb4cab622d565` |

## License

The repository has no LICENSE file; the GeoReport v2 OpenAPI document states its own license in `info.license`, Creative Commons Attribution 3.0 (CC BY 3.0) (SHA-256 of `data/georeport_v2-1.yaml`: `038ac7f5c1dea29bb743cc9d136b4c1dbd897fc008e7362fd16eb4cab622d565`)

> name: CC BY 3.0
> url: 'http://creativecommons.org/licenses/by/3.0/'

The document is the Swagger 2.0 form of Open311 GeoReport v2 (http://wiki.open311.org/GeoReport_v2/). Attribution: the pack is derived from it (CC BY 3.0), restated with keys of this project's naming.

The pack restates the schema's structure (member names, types, nesting) with keys of this
project's naming. It is not endorsed by the publisher.
