# Provenance of the ecs-event pack

`tools/gen/ecs2pack.py` reads `generated/ecs/ecs_flat.yml` (the type, array and object-type keys of its 2614
fields, no text), builds a JSON Schema of the document's structure and passes it to
`tools/gen/jsonschema2pack.py`. The pack's notes cite `schemas/*.yml` for the bindings in
this project's words. The files are not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | Elastic Common Schema (ECS) v9.5.0, the event document |
| Publisher | Elasticsearch B.V. |
| Repository | https://github.com/elastic/ecs at tag `v9.5.0`, commit `401807e0547301525acd28c4fb667203fec66d59` |
| Download | `https://raw.githubusercontent.com/elastic/ecs/401807e0547301525acd28c4fb667203fec66d59/generated/ecs/ecs_flat.yml` |

| File | SHA-256 | Read by the generator |
|---|---|---|
| `generated/ecs/ecs_flat.yml` | `70557ba53e2bda966688f8255193d36f2dcfa5bce2fb4a1a460bcccfd328ed5c` | yes |
| `schemas/base.yml` | `3b01d0a4a6dca93de145dd47c33c3a2b781c3d377d72c6d360c19acae8be229d` | no (cited in the notes) |
| `schemas/event.yml` | `3b32568e9c539639cdcc37dbdaca49c3e6423ca3036e6c07734ab85c256afdf1` | no (cited in the notes) |
| `schemas/geo.yml` | `d88b8a2f4ef309029bb4b13069d23647a2981cd30022886c0631647c1813c428` | no (cited in the notes) |
| `schemas/host.yml` | `97e65e5c055e4b35788f26fdfc1c973e46df9e0b6cb02a9c12477aa166d2bae8` | no (cited in the notes) |
| `LICENSE.txt` | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` | no |
| `NOTICE.txt` | `a6cf45157894095039048a17bee2cb3f7c3c58ab64269e7729a22226bd98fea9` | no |

## License

`LICENSE.txt` is the Apache License, Version 2.0; it opens:

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

`NOTICE.txt`, which the license asks to be carried with derivative works, in full:

> Elastic Common Schema
> Copyright 2018-2021 Elasticsearch B.V.
>
> Licensed under the Apache License, Version 2.0 (the "License");
> you may not use this file except in compliance with the License.
> You may obtain a copy of the License at
>
>     http://www.apache.org/licenses/LICENSE-2.0
>
> Unless required by applicable law or agreed to in writing, software
> distributed under the License is distributed on an "AS IS" BASIS,
> WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
> See the License for the specific language governing permissions and
> limitations under the License.

The pack restates the document's structure (field names, types, nesting) with keys of
this project's naming. It takes no description or example text of the schema. It is not
endorsed by Elasticsearch B.V.
