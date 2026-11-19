# Provenance: etsi-cam pack

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module `etsicam` hold the component names, constraints, extension markers and
named numbers of the ASN.1 types they describe; `pack.md` quotes the
definitions of the five types its shared-key bindings rest on.

Only the ASN.1 modules below were used. The documents they are published with
(the PDF of ETSI EN 302 637-2 and of TS 102 894-2) carry "All rights
reserved"; no text of them was used or copied.

## Pack `etsi-cam`, module `etsicam`

### CAM-PDU-Descriptions (ETSI EN 302 637-2 v1.4.1)

| | |
|---|---|
| Source | ETSI ASN.1 module `CAM-PDU-Descriptions`, published with ETSI EN 302 637-2 v1.4.1 (2019-04), Cooperative Awareness Basic Service |
| Upstream | https://forge.etsi.org/rep/ITS/asn1/cam_en302637_2 |
| Version | commit `fed28cfe5c930dd9d3109ff1162c28008697754a`; module identifier `... en (302637) cam (2) version (2)` |
| `CAM-PDU-Descriptions.asn` | sha256 `78e42dbd0dc95d9f2fa7bf1b00d7484dfb8b1b89b064a2f34c60372a775f0449` |
| `LICENSE` | sha256 `8f102e377f1ad7ed9fa90d9dd6cb9ab75e071949dcdb8cb413a10dc98d80b9d4` |
| `README.md` | sha256 `df56477e86371ba50454503c704d16c33835302ca1df8cf36a97caa776680bb4`; states that the content of the repository is released under the BSD-3-Clause license |

### ITS-Container (ETSI TS 102 894-2 v1.3.1)

| | |
|---|---|
| Source | ETSI ASN.1 module `ITS-Container`, published with ETSI TS 102 894-2 v1.3.1, Common Data Dictionary; the version that `CAM-PDU-Descriptions` v1.4.1 imports (`... ts (102894) cdd (2) version (2)`) and that its README names |
| Upstream | https://forge.etsi.org/rep/ITS/asn1/cdd_ts102894_2 |
| Version | commit `2d2450e79aab4c7032ef615b72ddefaf2e5ba8a9` |
| `ITS-Container.asn` | sha256 `afc658e2ad6382539a7710dd2607051a5416b5ed9cb3e681a6d52328cde8d0f9` |
| `LICENSE` | sha256 `8f102e377f1ad7ed9fa90d9dd6cb9ab75e071949dcdb8cb413a10dc98d80b9d4`, the same text as above |

### License

Both repositories carry the same `LICENSE` file. Its copyright line and
conditions:

> Copyright 2019 ETSI
>
> Redistribution and use in source and binary forms, with or without
> modification, are permitted provided that the following conditions are met:
> 1. Redistributions of source code must retain the above copyright notice,
>    this list of conditions and the following disclaimer.
> 2. Redistributions in binary form must reproduce the above copyright notice,
>    this list of conditions and the following disclaimer in the documentation
>    and/or other materials provided with the distribution.
> 3. Neither the name of the copyright holder nor the names of its contributors
>    may be used to endorse or promote products derived from this software without
>    specific prior written permission.

The disclaimer that follows in the file (provided "AS IS", no warranty, no
liability) is reproduced in `NOTICE` with the copyright line and the
conditions. ETSI is not named as endorsing this pack.

## Why not SAE J2735

The North American counterpart of the CAM, the Basic Safety Message of SAE
J2735, and its ASN.1 are sold by SAE ("download purchase only"). Its license
could not be read without buying it, so it is not used.
