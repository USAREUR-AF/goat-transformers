SPDX licence: Apache-2.0

# Provenance of the openadr3-subscription pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/openadr3-run.sh`) reads the files below. They are not kept in this repository. Read on 2026-11-20.

## Source

| | |
|---|---|
| Publisher | OpenADR Alliance (specification); grid-coordination (public mirror) |
| Address | https://github.com/grid-coordination/openadr3-specification |
| Version | commit 17b91725e0f07203574ddc946e28def31cb11e44; file `3.1.0/openadr3-UPSTREAM.yaml`, the mirror's byte-for-byte copy of upstream oadr3-org/specification commit ddd2cc5 |
| Files | under `3.1.0/` of the mirror |

| File | Bytes | SHA-256 |
|---|---|---|
| `openadr3-UPSTREAM.yaml` | 90428 | `0a85f28a91565b3e2c7488d2a7a7a9afb11ce3ef6b35afddb328484720077006` |

## Licence

The OpenAPI document declares its own licence in `info.license`:

> name: Apache 2.0
> url: 'http://www.apache.org/licenses/LICENSE-2.0.html'

The pack is labelled `Apache-2.0` on that statement. The OpenADR Alliance publishes the
specification at no charge but behind an account registration, and its own repository is
not public; the mirror's NOTICE says it republishes the artifacts unmodified, quotes the
Alliance describing its specifications as "license free but copyright of the OpenADR
Alliance", and notes that the Definition and User Guide documents carry the Alliance's
copyright without a separate grant. The pack takes nothing from those documents. No
endorsement by the OpenADR Alliance is implied.
