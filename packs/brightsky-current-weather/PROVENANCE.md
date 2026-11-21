# Provenance of the brightsky-current-weather pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/wxfc-run.sh`) reads one file, the OpenAPI
document of Bright Sky, and takes `components.schemas.CurrentWeatherResponse` and the schemas it refers to.
The file is not kept in this repository. Read on 2026-11-21.

## Source

| | |
|---|---|
| Document | Bright Sky, OpenAPI 3.1.0 document, `info.version` 2.2.12 |
| Address | https://api.brightsky.dev/openapi.json, served 2026-11-21; the document has no versioned address (the repository's `docs/brightsky.yml` points to it), so this copy is pinned |
| SHA-256 | `2488b99f28691318939a29eadf55500a7fde7bd646032d193bf16a7885185b63` (71,220 bytes of JSON as served) |
| Repository | https://github.com/jdemaeyer/brightsky, commit `0f5d0df885b053d6c85a82dc72db4fed04b87a7e`, archive SHA-256 `6d41ae8ab9f64d2cfc2445b976ed9cd0e445c33939cd80ccc24c875cac3a00c3` (`LICENSE`) |
| Responses read | `/weather`, `/current_weather`, `/synop`, `/sources` and `/alerts` for one place, 2026-11-21, to check the shape; not kept, and no value of them is in a vector |

## Licence

The document's `info.license` is the MIT License (identifier MIT), and the repository's
`LICENSE` at that commit is the MIT License:

> Copyright (c) 2020 Jakob de Maeyer
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

This pack restates the member names and types of the document (no description or example is
copied); it carries the project's licence, Apache-2.0 (the default annotation). The data Bright
Sky serves are Deutscher Wetterdienst open data; this pack holds none of them. Credit: Jakob de
Maeyer (Bright Sky) and DWD.

No document read carries a handling marking, a distribution statement or an export-control
notice.
