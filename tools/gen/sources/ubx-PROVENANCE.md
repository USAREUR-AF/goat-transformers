# Provenance of the UBX inputs

| Fact | Value |
|---|---|
| repository | https://github.com/semuconsulting/pyubx2 |
| tag | `v1.4.1` |
| commit | `e5335f7285b24808fb62ccaf6666a6b954f27118` (the commit of the tag, read 2026-11-19) |
| archive | `https://codeload.github.com/semuconsulting/pyubx2/tar.gz/e5335f7285b24808fb62ccaf6666a6b954f27118` |
| license | BSD 3-Clause, copyright (c) 2020 semuadmin (Steve Smith): the file `LICENSE` at the root of the commit, verbatim below |

The definition files say in their header that their content was taken from
the public u-blox interface specifications (copyright u-blox AG). This
repository reads only the definition files of pyubx2, never a u-blox
document, and takes no description text from them.

## Files

| Path | SHA-256 |
|---|---|
| `LICENSE` | `8de4cd2e5c6347b9c064ce30546266a144a10bab48301f24eb2c0a3087fa6c52` |
| `src/pyubx2/ubxtypes_core.py` | `f85c7424477df925382e0f50d21a80c68b6311833f122d55e7d6713112a2a113` |
| `src/pyubx2/ubxtypes_get.py` | `7131280ff13987563d3cfee54c9bb239b6431c948ab2945eaf07e498ed2ee0c8` |
| `src/pyubx2/ubxtypes_set.py` | `0b95383f4a8c9f5a5af3c33c4fd40466ecb7a5575f085dffe8fe6f89cfb42fc2` |
| `src/pyubx2/ubxtypes_poll.py` | `11706860ff5c3448bdf06a5e3f8ecab69595593e610b8508467ce6c7b6cb6bf3` |
| `src/pyubx2/ubxvariants.py` | `ee003423a80a09800ca6b43ccda6ccd80c662795cdafb5c9aeef312128076372` |
| `examples/gpxtracker.py` | `1f45d5ad80cfb96f2d97e27e9dc96fde4e560ca7f33ba8495ed250b8029d5d84` |
| `examples/ubx_spatialite.py` | `4c59428f34fe959fbd0e299476ef74d50f8ddefbbd552c9c1c81ef6041ae9e7d` |
| `examples/gnssapp.py` | `0507cc25809a3fa14071832ec98e30d7ccaa38637b8884cfcd5cd81bde46f88b` |

## LICENSE

```
BSD 3-Clause License ("BSD License 2.0", "Revised BSD License", "New BSD License", or "Modified BSD License")

Copyright (c) 2020, semuadin (Steve Smith)
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

## The units: ublox_msgs

| Fact | Value |
|---|---|
| repository | https://github.com/KumarRobotics/ublox (the package `ublox_msgs`) |
| commit | `3a3e1c253722b68e350a60aee6ef399d8c2304cb` (branch ros2; the commit `tools/gen/ros2-run.sh` uses for the ros2-ublox-msgs pack) |
| files | `https://raw.githubusercontent.com/KumarRobotics/ublox/3a3e1c253722b68e350a60aee6ef399d8c2304cb/<path>` |
| license | BSD, as the package states it: `ublox_msgs/package.xml` holds `<license>BSD</license>`, and the comment at the top of `ublox_msgs/src/ublox_msgs.cpp` holds the text below; the repository has no LICENSE file and the .msg files carry no licence header |

The generator reads the units of the fields it binds from these .msg files
and binds a field only where the file states the unit; it takes no other
text from them.

| Path | SHA-256 |
|---|---|
| `ublox/ublox_msgs/msg/NavPVT.msg` | `a180b2a602d60a57c727f2679ea01a583d8250afb7763c9435b6b5f1a2319d76` |
| `ublox/ublox_msgs/msg/NavVELNED.msg` | `29976a85fe517a6ea6759218b1653a84170d87d800b85ef1bdd4ca74ff18703e` |
| `ublox/ublox_msgs/msg/HnrPVT.msg` | `3f6e4160ca254c259b565e0e5a108e096024c0a8f3fb96c22f52a52cfe8232b8` |
| `ublox/ublox_msgs/package.xml` | `cd16477756a4ed1e88268e560dcd10248b2b5a485500bd73dd8864035aed02cc` |
| `ublox/ublox_msgs/src/ublox_msgs.cpp` | `d26c35fd06eb6f2337f190f7aae531adb19358039e69c3d630be6eba428b5f90` |

### ublox_msgs/src/ublox_msgs.cpp, the licence comment

```
Copyright (c) 2012, Johannes Meyer, TU Darmstadt
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the Flight Systems and Automatic Control group,
      TU Darmstadt, nor the names of its contributors may be used to
      endorse or promote products derived from this software without
      specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
