# Provenance of the neows-stats pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/space-run.sh`) generates this pack from this
project's restatement `tools/gen/space/neows-1-objects.json` (SHA-256 `4a5eb5e93830abe1ac3c4941c8a1efef695b7a82c117d76e71785964f5bb0577`), object `Stat`. The source is not kept in
this repository. Read on 2026-11-21.

## Sources

| Document | Address | Used for |
|---|---|---|
| neows-ruby, the Ruby client of NeoWs by its maintainers | https://github.com/SpaceRocks/neows-ruby, commit `b81655f31357b1d1700628085c041630111d0f06`, archive SHA-256 `4042ef4d52ff34a201ff5c9084b949c005265966c435d9d6c7e67128c1a971f6` | member names (`lib/neows/models/*.rb`) and JSON types (`spec/fixtures/*.json`) |
| api.nasa.gov, Asteroids - NeoWs | https://api.nasa.gov/ (catalogue `assets/json/apis.json`) | the endpoints and the maintainers |
| A feed response, 2026-11-19 to 2026-11-20 | https://api.nasa.gov/neo/rest/v1/feed | that the 2026 service sends the same types and the members the client does not model; not kept, and no value of it is in a vector |

## Licence

neows-ruby is under the MIT License (`LICENSE.md` at that commit):

> Copyright (c) 2015 Jason English
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.

This pack restates the member names of the client's models and the JSON types its fixtures
show (no code, comment or fixture value is copied), as for the other packs restated from
code sources under permissive licences; it carries the project's licence, Apache-2.0 (the
default annotation). The NeoWs service itself is run for NASA at api.nasa.gov; its page
lists the endpoints and their parameters and names the maintainers (the SpaceRocks team),
but documents no member of a response, which is why the client is the source. Credit: the
SpaceRocks team and NASA.

No document read carries a handling marking, a distribution statement or an export-control
notice.
