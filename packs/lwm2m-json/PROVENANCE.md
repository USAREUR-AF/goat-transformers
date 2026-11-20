# Provenance of the lwm2m-json pack

The pack and the module `lwm2m` are written by hand from the LwM2M JSON section of the OMA
LwM2M 1.0.2 technical specification; the resource tables of pack.md come from the OMA LwM2M
object registry; the vectors are derived by `tools/gen/lwm2m-tcx-vectors.py` from payloads
written for them. No source file is kept in this repository. Read on 2026-11-20.

## Sources

| Document | Version | Where | SHA-256 |
|---|---|---|---|
| OMA Lightweight M2M Technical Specification, section 6.4.4 JSON | Approved Version 1.0.2, 2018-02-09, OMA-TS-LightweightM2M-V1_0_2-20180209-A | https://www.openmobilealliance.org/release/LightweightM2M/V1_0_2-20180209-A/OMA-TS-LightweightM2M-V1_0_2-20180209-A.pdf | `79061ccd170d288b3051b54605b43e5b905b34e0e61a6f8905161cca389bab82` |
| OMA LwM2M registry, objects 3, 6, 3303, 3336 (and 3301, 3304, 3315, checked to share 3303's resources) | commit `a763bb5414099844fadf0797b2c8223d169d0c7e` | https://github.com/OpenMobileAlliance/lwm2m-registry | 3.xml `dacf39a733f0c002e1695637d59833ca207cd785c2e1686b2e30620c51c6535b`, 6.xml `885b70b70411e4b96d34d95f630618c2ff85d88e9e86768b5cd5adc50a5facb0`, 3303.xml `2d667c1003550d68799303e7ea76d0606efe35b1e179ed80aa589e1f57cd5184`, 3336.xml `a90678061209efe52753d9e0d112c716685d5598b98a11f496ed427d84dcb083` |

## Licence of the content format: `LicenseRef-OMA-Internal`

Page 2 of the technical specification states:

> You may use this document or any part of the document for internal or educational purposes
> only, provided you do not modify, edit or take out of context the information in this
> document in any manner. Information contained in this document may be used, at your sole
> risk, for any purposes. You may not use this document in any other manner without the prior
> written permission of the Open Mobile Alliance.

The pack restates the members of the format in this repository's words and copies no text,
table or example of the document. Under `LicenseRef-OMA-Internal` (LICENSES/, licences.toml)
the pack is treated as not usable commercially, so it is outside the `open` profile.

## Licence of the registry: BSD-3-Clause

Each object file of the registry carries this notice, which applies to the resource tables of
pack.md:

> Copyright 2020 Open Mobile Alliance.
>
> Redistribution and use in source and binary forms, with or without modification, are
> permitted provided that the following conditions are met:
> 1. Redistributions of source code must retain the above copyright notice, this list of
> conditions and the following disclaimer.
> 2. Redistributions in binary form must reproduce the above copyright notice, this list of
> conditions and the following disclaimer in the documentation and/or other materials
> provided with the distribution.
> 3. Neither the name of the copyright holder nor the names of its contributors may be used to
> endorse or promote products derived from this software without specific prior written
> permission.
>
> THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
> IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
> FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. (The full disclaimer is in each file.)
