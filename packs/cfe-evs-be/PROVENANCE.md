# Provenance: cfe-evs-be pack

SPDX licence: Apache-2.0

Read on 2026-11-20. No source file is copied into this tree. The pack, the modules
`cfeevs` and `cfemsg`, `pack.md` and `tools/gen/cfe/layout.json` are written by
`tools/gen/cfe2pack.py` (run by `tools/gen/cfe-run.sh`) from the C headers below; the
vectors by `tools/gen/cfe-vectors.py` from `layout.json`. Member names, sizes, message IDs
and function codes come from the headers; descriptions are in our own words.

## Pack `cfe-evs-be`, modules `cfeevs` and `cfemsg`

| | |
|---|---|
| Source | NASA core Flight Executive (cFE), EVS (Event Services) module: default configuration headers (`modules/evs/config/default_cfe_evs_*.h`), interface headers (`modules/evs/fsw/inc`), command dispatch (`modules/evs/fsw/src/cfe_evs_dispatch.c`), message headers (`modules/msg/option_inc`) |
| Repository | https://github.com/nasa/cFE at tag `v7.0.2-rc1` (the newest release tag; published as a release, not a pre-release), commit `73f6fe102eae7949fc5f550e6818fec60319ddea` (2026-10-20) |
| Files | listed in `pack.md`, "Sources", with size and SHA-256 |
| License file | `LICENSE` at that commit, 11357 octets, sha256 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`: the Apache License, Version 2.0 |

## License

`LICENSE` is the text of the Apache License, Version 2.0. Every header read begins:

> NASA Docket No. GSC-19,200-1, and identified as "cFS Draco"
>
> Copyright (c) 2023 United States Government as represented by the
> Administrator of the National Aeronautics and Space Administration.
> All Rights Reserved.
>
> Licensed under the Apache License, Version 2.0 (the "License"); you may
> not use this file except in compliance with the License. You may obtain
> a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
>
> Unless required by applicable law or agreed to in writing, software
> distributed under the License is distributed on an "AS IS" BASIS,
> WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
> See the License for the specific language governing permissions and
> limitations under the License.

This pack restates the layout of the packets those headers define; it carries the
attribution above (and in `NOTICE`) as the license asks.
