# Provenance of the RTCM 3 inputs

| Fact | Value |
|---|---|
| repository | https://github.com/semuconsulting/pyrtcm |
| tag | `v1.2.1` |
| commit | `0e190e70498a6795ce5f45c0a8671f0041698ce7` (the commit of the tag, read 2026-11-19) |
| archive | `https://codeload.github.com/semuconsulting/pyrtcm/tar.gz/0e190e70498a6795ce5f45c0a8671f0041698ce7` |
| license | BSD 3-Clause, copyright (c) 2020 semuadmin (Steve Smith): the file `LICENSE` at the root of the commit, verbatim below |

The definition files say in their header that their content was taken from
the RTCM standard 10403.3 (copyright RTCM). This repository reads only the
definition files of pyrtcm, never an RTCM document, and takes no description
text from them.

## Files

| Path | SHA-256 |
|---|---|
| `LICENSE` | `ff91a7db50c1afa9e96318249918f351e10806d388173a615021f67f58740132` |
| `src/pyrtcm/rtcmtypes_core.py` | `45c20ef00cb2ed115a105854d6a171029e5358e5f080877c960bbdfae58ae988` |
| `src/pyrtcm/rtcmtypes_get.py` | `33af2c23f995d2c4996451c865658f19e702e024cf2749a48630cd3aa276f06a` |
| `src/pyrtcm/rtcmtypes_get_msm.py` | `6efdcd056b523e4004bd939f8c370e0b7e0c3c2532fa299ccdb7f372d8f94f4d` |
| `src/pyrtcm/rtcmtypes_get_igs.py` | `839b5a242715d97a8af2fcbfbb96031cd3a679935c64466e80a72208a3036c59` |

## LICENSE

```
BSD 3-Clause License ("BSD License 2.0", "Revised BSD License", "New BSD License", or "Modified BSD License")

Copyright (c) 2020, semuadmin (Steve Smith)
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the <organization> nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
