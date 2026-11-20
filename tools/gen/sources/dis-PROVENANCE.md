# Provenance of the DIS inputs

| Fact | Value |
|---|---|
| layouts | https://github.com/open-dis/xmlpg, master, commit `35ed3733009a89a34604abad87d1aefc1fdfbbc2` |
| xmlpg archive | `https://codeload.github.com/open-dis/xmlpg/tar.gz/35ed3733009a89a34604abad87d1aefc1fdfbbc2` |
| PDU types | https://github.com/open-dis/open-dis-python, master, commit `48cb4fa59b44ad50d9f519190e53609ef7a3ef19` |
| open-dis-python archive | `https://codeload.github.com/open-dis/open-dis-python/tar.gz/48cb4fa59b44ad50d9f519190e53609ef7a3ef19` |

The xmlpg README calls `DIS2012.xml` the original specification file of Open
DIS, no longer maintained, with corrections made in the generated libraries.
The generator takes the layouts from it, the PDU type numbers from the class
annotations of open-dis-python, and reads both as data (an XML tree and a
Python syntax tree); it runs neither. No IEEE document was read.

## Files

| Path | SHA-256 |
|---|---|
| `xmlpg/LICENSE.md` | `ce6a50db9a0a6dff4109706103353fe2b7b739e0703603a01ca0fda3272d786f` |
| `xmlpg/DIS2012.xml` | `6f934f5a10c06482fc9eeb169c1ede041106dfb8af8fb538adb3b38d75e687dc` |
| `opendis/LICENSE` | `cfb9a9cb6113eacc5ae909473d48d7b04a94929498103b3208bca9665b7270b0` |
| `opendis/opendis/dis7.py` | `a85b926a1f399ce6cabbb163af98518b82e1097e13ac30026f5dc1e7211cd515` |
| `opendis/opendis/PduFactory.py` | `dab22a4c8d55042f9624fdb4894704f2d69fd9ae7676437982409a1e037e9cb8` |

## xmlpg LICENSE.md

```
Copyright (c) 2015, mcgredonps
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## open-dis-python LICENSE

```
BSD 2-Clause License

Copyright (c) 2023, Open DIS
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
