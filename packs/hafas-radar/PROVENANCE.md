# Provenance of the hafas-radar pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/transit-run.sh`) generates this pack from this
project's restatement of the source's objects. The source is not kept in this repository.
Read on 2026-11-20.

## Source

| | |
|---|---|
| Document | hafas-client 6, documentation of `radar()` |
| Repository | https://github.com/public-transport/hafas-client, tag `6.3.6`, commit `3f5049d47401bec509b8caab69a1fc68086fe972` |
| Files read | `docs/radar.md` (SHA-256 `e1ffd42b9d34d3c56b53cd238317e626bb35eb59fdfbc1f26776941ec2a1a66c`), `docs/hafas-mgate-api.md` (for the coordinate frame) |
| Restatement | `tools/gen/transit/hafas-client-6-objects.json`, SHA-256 `930a8b5865297d6851f29eddaf4293b5a13e8ac449e5a7d00e32068fd9221c17` |

## Licence

hafas-client's `license.md` (SHA-256 `a96a7231593f2377159e5801d1fd46e2dc6b5a608460ad88e03ee896f3ab442e`) is the ISC licence:

> Copyright (c) 2025, Jannis R
>
> Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear in all copies.

This pack restates the member names and types of the documented results in the project's
own words and carries the project's licence, Apache-2.0 (REUSE.toml, the default
annotation). The results follow the Friendly Public Transport Format (CC BY-SA 4.0), which
was not used as a source.
