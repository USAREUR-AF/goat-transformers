# Provenance of the ecs-event pack

`tools/gen/ecs2pack.py` reads `generated/ecs/ecs_flat.yml` (the type, array and object-type keys of its 11
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
| `generated/ecs/ecs_flat.yml` | `ac110224587965d19956867758b39442022341d3bec545cda27629f0e6bc25de` | yes |
| `schemas/base.yml` | `349cb9c52a6c0ec6c1f05180f98fb78a1996f572daadf9e6790fd17dde0a8b58` | no (cited in the notes) |
| `schemas/event.yml` | `91cab2f3b1f0d486de386b9886bac761db96587d107bb5fc4aa13204f8fcbc5a` | no (cited in the notes) |
| `schemas/geo.yml` | `6ab9a5ef81e56d41d7b55aaa2f22e8af17cc8e1ff480d40521e6432d2371324d` | no (cited in the notes) |
| `schemas/host.yml` | `c21aa279b0ff7e0f8c6b8ad6063fc12ff2f1550ecb3ccab3f03fe827e487fd0a` | no (cited in the notes) |
| `LICENSE.txt` | `c665f47ab8605c845a2e6036ccbb89bcfde4999a5caf791464323b931b6dc131` | no |
| `NOTICE.txt` | `8d71b868af0a0e12b101b21979de9843019133bb366fc17ccecfb3ef6e1cae6f` | no |

## License

`LICENSE.txt` is the Apache License, Version 2.0; it opens:

> Apache License
> Version 2.0, January 2004
> http://www.apache.org/licenses/

`NOTICE.txt`, which the license asks to be carried with derivative works, in full:

> Test notice written for the generator tests.

The pack restates the document's structure (field names, types, nesting) with keys of
this project's naming. It takes no description or example text of the schema. It is not
endorsed by Elasticsearch B.V.
