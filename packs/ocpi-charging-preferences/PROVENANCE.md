# Provenance of the ocpi-charging-preferences pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/ocpi-run.sh`) generates this pack from
`tools/gen/ocpi/ocpi-2.2.1-objects.json` (SHA-256 `fdee3d66ef5e584adf6f66429f7a5dbebd2d2e2fd8b5182fc720c361c9c8fa15`), this project's own restatement
of the OCPI 2.2.1 objects. The OCPI document is not kept in this repository. Read on
2026-11-20.

## Source

| | |
|---|---|
| Document | OCPI 2.2.1, Open Charge Point Interface |
| Publisher | EVRoaming Foundation |
| Repository | https://github.com/ocpi/ocpi, tag `2.2.1`, commit `480973547169dee2fe6d12b1a0fe604623efcbb5` |
| Chapters read | `mod_locations`, `mod_sessions`, `mod_cdrs`, `mod_tariffs`, `mod_tokens`, `mod_commands`, `types`, `transport_and_format` (`.asciidoc`; each SHA-256 in the run script) |
| Licence notice | `copyright.asciidoc`, SHA-256 `4433fa91d995e2a0cdd9310b7e2418169425212175d0f680ad6f2354ae092514` |

## Licence

The document's notice (`copyright.asciidoc`), as it reads at that tag:

> Copyright © 2014 – {year} EVRoaming Foundation. All rights reserved.
>
> This document is made available under the _Creative Commons Attribution-NoDerivatives 4.0
> International Public License_ (https://creativecommons.org/licenses/by-nd/4.0/legalcode).

CC BY-ND 4.0 allows sharing the document unchanged, with attribution, and does not allow
sharing an adaptation of it. This pack does not share the document or an adaptation of it:
no description text, table, example or other expression of the document is copied. The pack
is this project's implementation of the protocol the document specifies, built from the
member names, JSON types and required members of the objects, which the project restated
in its own file. Under the operator's licensing decision (the same basis as for I3S), the
pack carries the project's licence, Apache-2.0 (REUSE.toml, the default annotation).

Attribution: OCPI is developed and managed by the EVRoaming Foundation
(https://www.evroaming.org).
