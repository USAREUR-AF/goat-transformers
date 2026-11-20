# Provenance of the vss-vehicle pack

`tools/gen/vss2pack.py` reads the files below (the `type`, `datatype`, `instances` and
`instantiate` keys of their nodes, no text), expands the instances into 14 signals, builds a
JSON Schema of the tree as a document and passes it to `tools/gen/jsonschema2pack.py`. The
files are not kept in this repository. Read on 2026-11-20.

| | |
|---|---|
| Document | COVESA Vehicle Signal Specification (VSS) v6.1, the signal tree |
| Publisher | COVESA (Connected Vehicle Systems Alliance) |
| Repository | https://github.com/COVESA/vehicle_signal_specification at tag `v6.1`, commit `2817646d1808fc7c470c0432fc7f4ed685e5c9e3` |
| Download | `https://raw.githubusercontent.com/COVESA/vehicle_signal_specification/2817646d1808fc7c470c0432fc7f4ed685e5c9e3/spec/VehicleSignalSpecification.vspec` and the files it includes |

| File | SHA-256 |
|---|---|
| `spec/Vehicle/Vehicle.vspec` | `89060c70a427f4141ebb1795f1b0fd63724be9ac097e74a697a26ac0dc125f39` |
| `spec/VehicleSignalSpecification.vspec` | `fe1019b5736c0711c5a0715f87feb8cde938650632064d628f817df5ee0f4afa` |
| `spec/include/Extra.vspec` | `5f2d8a9e7e60a27e4f11b8a60377c3ede8bdf22c3d031f0c1097f1b48947e2b5` |
| `LICENSE` | `c665f47ab8605c845a2e6036ccbb89bcfde4999a5caf791464323b931b6dc131` |

## License

`LICENSE` is the Mozilla Public License, Version 2.0. Its title, and the notice each vspec
file carries in its header (in full, the file's own words):

> Mozilla Public License Version 2.0
>
> Copyright (c) 2016 Contributors to COVESA
>
> This program and the accompanying materials are made available under the
> terms of the Mozilla Public License 2.0 which is available at
> https://www.mozilla.org/en-US/MPL/2.0/
>
> SPDX-License-Identifier: MPL-2.0

The pack is not a copy or a modification of the vspec files: it restates the tree's
structure (node names, data types, the expansion of instances) with keys of this
project's naming and takes no description, comment or allowed-value text. It is not
endorsed by COVESA.
