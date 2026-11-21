# Provenance of the argo-sensor-metadata pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/ocean-run.sh`) reads the Euro-Argo
metadata JSON schemas (each file and its SHA-256 in `pack.md` and the run script) and takes
`argo.sensor.schema.json` as the message. The files are not kept in this repository. Read on 2026-11-21.

## Source

| | |
|---|---|
| Document | Argo float, platform and sensor metadata JSON schemas |
| Repository | https://github.com/euroargodev/sensor_metadata_json, commit `9352eeb0f8351145eed1086b08972508b5ac775e`, `schemas/` (float, platform, sensor and the vendor schemas they refer to) |
| License file | `LICENSE`: European Union Public Licence v. 1.2 (EUPL-1.2) |

## Licence

The schemas are under the EUPL-1.2, a copyleft licence. As for the project's other
restatements of schemas and code under copyleft licences (rule 17), the pack restates member
names, types and required members, copies no schema text or description, and carries the
project's licence, Apache-2.0 (the default annotation). The source is credited: Euro-Argo
(euroargodev).
