# Provenance of the lwm2m-json pack

The pack and the module `lwm2m` are written by hand from the LwM2M JSON section of the OMA
LwM2M 1.0.2 technical specification; the resource tables of pack.md come from the OMA LwM2M
object registry; the vectors are derived by `tools/gen/lwm2m-tcx-vectors.py` from payloads
written for them. No source file is kept in this repository. Read on 2026-11-20.

## Sources

| Document | Version | Where | SHA-256 |
|---|---|---|---|
| OMA Lightweight M2M Technical Specification, section 6.4.4 JSON | Approved Version 1.0.2, 2018-02-09, OMA-TS-LightweightM2M-V1_0_2-20180209-A | https://www.openmobilealliance.org/release/LightweightM2M/V1_0_2-20180209-A/OMA-TS-LightweightM2M-V1_0_2-20180209-A.pdf | `79061ccd170d288b3051b54605b43e5b905b34e0e61a6f8905161cca389bab82` |
| OMA LwM2M registry, objects 3, 6, 3303, 3336 (and 3301, 3304, 3315, checked to share 3303's resources) | commit `a763bb5414099844fadf0797b2c8223d169d0c7e` | https://github.com/OpenMobileAlliance/lwm2m-registry | 3.xml `576ab98d1c39a2a672b42947432d89db4f4b9e72d153196de11b6a4a017cf52a`, 6.xml `a8b24da5e63ec5e423066fa5c9856338621c8532de3824ce8982f897622f30c6`, 3303.xml `627ba7642817e8cb63301774611530616925b5443da0f4d4ea133836c918c051`, 3336.xml `ae7855852fbeafccdd23bb67014a14d75d999ac4970d6454e94232bd25dfd542` |

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
