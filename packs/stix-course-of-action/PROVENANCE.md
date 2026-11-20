# Provenance of the stix-course-of-action pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/stix-run.sh`) reads the files below and nothing
else. They are not kept in this repository. Read on 2026-11-19.

| | |
|---|---|
| Document | STIX 2.1 `course-of-action` object, JSON Schema |
| Publisher | OASIS Cyber Threat Intelligence (CTI) Technical Committee, TC Open Repository |
| Repository | https://github.com/oasis-open/cti-stix2-json-schemas at commit `c4f8d589acf2bdb3783655c89e0ffb6e150006ae` |
| Download | `https://raw.githubusercontent.com/oasis-open/cti-stix2-json-schemas/c4f8d589acf2bdb3783655c89e0ffb6e150006ae/schemas/sdos/course-of-action.json` |

| File | SHA-256 |
|---|---|
| `schemas/common/binary.json` | `18d0faef9f42579d5c7f337659ae6f72334029209035c05f21583ae2be17bf25` |
| `schemas/common/core.json` | `e8562aa1dd674249c33a640d1d972183256e491b9af81eaa78d102da1c473ffb` |
| `schemas/common/dictionary.json` | `4984a232a664bd54d2fb99a49c052a38da2ce90e43995a007a9e5fa8d208c116` |
| `schemas/common/extension.json` | `e4537cf608b709597ede2ad39027defa979df9ad79666b15643d625ac260f15d` |
| `schemas/common/external-reference.json` | `ade5360f0e7b0863ad933d34a54802e7ac9e85d1e0db53cf449e43465ba81127` |
| `schemas/common/granular-marking.json` | `24c51ff9d99f1902b156e6e04e360e23ea01cded49d07a83fca709cef26884c0` |
| `schemas/common/hashes-type.json` | `6493e13b08fbf0ced26e956166e03ab37011ae1bb2c26d80a449ea7c81155c50` |
| `schemas/common/hex.json` | `d079f4141f68615424756bd74d16b4a47b9a7388dd836845849595db6e59f253` |
| `schemas/common/identifier.json` | `662be3c490c8f3b2aa82100d1dc41ec1acf93c04d099c857cc2f88217d688524` |
| `schemas/common/properties.json` | `ccb1920b6d2c9a80856d36e870163b3b298cf9c3ca42742f3f63dfbc87295754` |
| `schemas/common/timestamp.json` | `e816ad77e8f46b66aaaacac6b7f5f14dcd9d320c01d992455a7958481337d4d9` |
| `schemas/common/url-regex.json` | `88a22341762c7b039a1ce349d808a1ed4e0b560af11dbc911532eeb580026115` |
| `schemas/sdos/course-of-action.json` | `56fd137d6d9e4bcfe56d7c98acc05a79957db924381ee40680d2e621274079c5` |

## License

The repository's `LICENSE` is the BSD 3-Clause License with the copyright of OASIS Open. Its README states that the repository is an OASIS TC Open Repository whose contributions are under that license, and that its governance is separate from the OASIS TC Process. The license asks that its notice be kept with redistributions; in full: (SHA-256 of `LICENSE`: `6a23b2cdf8fc03e855944a1edcce357100c4fa5d14cb0274bab1aaf85f4c44a5`)

> Copyright (c) [2016], OASIS Open
> All rights reserved.
>
> Redistribution and use in source and binary forms, with or without
> modification, are permitted provided that the following conditions are met:
>
> * Redistributions of source code must retain the above copyright notice, this
>   list of conditions and the following disclaimer.
>
> * Redistributions in binary form must reproduce the above copyright notice,
>   this list of conditions and the following disclaimer in the documentation
>   and/or other materials provided with the distribution.
>
> * Neither the name of the copyright holder nor the names of its
>   contributors may be used to endorse or promote products derived from
>   this software without specific prior written permission.
>
> THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
> AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
> IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
> DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
> FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
> DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
> SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
> CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
> OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
> OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

The schemas are not normative; they follow the STIX Version 2.1 OASIS Standard (https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html). The pack takes no text of the standard; its notes name the section they rely on in this project's words.

The pack restates the schema's structure (member names, types, nesting) with keys of this
project's naming. It is not endorsed by the publisher.
