# Provenance of the otp-itinerary pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/transit-run.sh`) generates this pack from this
project's restatement of the source's objects. The source is not kept in this repository.
Read on 2026-11-20.

## Source

| | |
|---|---|
| Document | OpenTripPlanner 2.10, GTFS GraphQL API schema |
| Repository | https://github.com/opentripplanner/OpenTripPlanner, tag `v2.10.0`, commit `521cd5d8acaae628878f43bf5946f4942c118548` |
| File read | `application/src/main/resources/org/opentripplanner/apis/gtfs/schema.graphqls`, SHA-256 `ee5c42d5fd6346b6062d057030f8cb2062517b31e93add66ca5a92cae247aac4` |
| Restatement | `tools/gen/transit/otp-2.10-objects.json`, SHA-256 `258d7833e0722ff635eba962b1e8bf77bacf866db7693b25e78c65bfbbe42ab1` |

## Licence

OpenTripPlanner is free software under the GNU Lesser General Public License, version 3 or
(at the recipient's option) any later version (`LICENSE`). This pack restates the member
names and types of the API's objects (no code, schema text or description is copied), as
for the other packs restated from GPL-family code sources (`ardupilot-log-*`, `meshtastic`,
`cot-protobuf`, `msp`); it carries the project's licence, Apache-2.0 (REUSE.toml, the
default annotation). Credit: the OpenTripPlanner project.
