# Provenance: c37118-config-4ph-int-rect pack

SPDX licence: Apache-2.0

A restatement, in this repository's words, of the frame layout pypmu implements;
pypmu is BSD-3-Clause, and its notice is kept in NOTICE and quoted below. No
pypmu code is copied or run, and none of its sample frames is used. IEEE Std
C37.118.2-2011, which pypmu implements, is a paid standard and was not read.

Read on 2026-11-20.

| | |
|---|---|
| Source | iicsys/pypmu, https://github.com/iicsys/pypmu, commit `66e6c495a91efb8a6018061ff7955a6654b1404d` (2020-06-15) |
| `synchrophasor/frame.py` | `ebf1b5ba8f6ba4d0b1f88c037bb5d8b0210c258525a87f1b732225408e02ff24` (frame classes: common header, data, configuration 1/2, command, header) |
| `examples/pyPMU.py` | `7f58161424f79a5e97c0f0a1420fac1512c8b19058f355f7de0edd36c4ae14e8` (the configuration of the 4-phasor packs) |
| `examples/randomPMU.py` | `07ad7644782e5de8d771e6d29132295025e9b3c2616b2ae7ace301c45dbb7a7c` (the configuration of the 3-phasor packs) |
| `LICENSE.txt` | `cb7478c49518bb596fae291a7e84d691430911e8009616a28f71aa7b299623c4` |

pypmu's README states that it implements IEEE C37.118.2-2011.

## Licence of the source

```
Copyright (c) 2016, Tomo Popovic, Stevan Sandi & Bozo Krstajic
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of pyPMU nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

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
