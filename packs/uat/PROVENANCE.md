SPDX licence: Apache-2.0

This repository's restatement is Apache-2.0. The source it restates is under the BSD 2-Clause
licence (below); its notice is in `NOTICE`.

# Provenance: uat pack

Written by hand from the decoder of dump978. No source file is copied into this tree.

| | |
|---|---|
| Repository | https://github.com/flightaware/dump978 |
| Commit | `f40aa9a0d2d0a0067c0c628b44ba316f7049b8ce` (committed 2026-07-01T15:39:07-05:00), the head of the default branch when read |
| Files read | `uat_message.cc` (the constructor of `AdsbMessage` and `DecodeSV`, `DecodeMS`, `DecodeAUXSV`, `DecodeTS`), `uat_message.h` (`RawMessage::Bit`, `RawMessage::Bits` and the enumerations), `uat_protocol.h` (the payload sizes) |
| Date read | 2026-11-20 |
| Not used | RTCA DO-282 (the UAT MOPS): a paid document, not held. dump978 cites its section and table numbers; this pack does not, beyond what pack.md says came from dump978 |

## Licence

`LICENSE` at that commit, with the copyright lines "Copyright 2015, Oliver Jowett" and
"Copyright (c) 2019, FlightAware LLC. All rights reserved.", grants redistribution and use in
source and binary forms, with or without modification, provided that source redistributions
retain the copyright notice, the list of conditions and the disclaimer, and binary
redistributions reproduce them in the documentation; the software is provided as is, without
warranty. Those are the terms of the BSD 2-Clause licence, and GitHub reports the repository as
`BSD-2-Clause`. The three files read each state that they are under the 2-clause BSD licence and
refer to `LICENSE`.

## What this repository takes

The byte and bit positions dump978 reads each field from, the width of each field, the
payload-type composition table, the meaning of each code where dump978 names it (the address
qualifier, the air/ground state, the track/heading type), and the arithmetic dump978 applies
(the angular weight of latitude and longitude, the altitude, selected altitude and pressure
setting formulas). They are restated in `pack.def`, `model/uat.def` and `pack.md` in this
repository's own words. The vectors are built by `tools/gen/uat-vectors.py`, which places the
bits at dump978's byte and bit numbers; no engine is run to make them.

## SHA-256

```
2feafa5b5bb404af849a331ef02f7705c844fa921e04b4defda92782278b551e  uat_message.cc
90c93d8b7bd59dbf936138d07f4b71ddac59f936f25deb51ad3fc0d2ed01b191  uat_message.h
2c834a3918362bf0982da94bbe6bb4cdd5cda08e4223c64df7dc0e27f87844fc  uat_protocol.h
4c61901da63ff338dc8e8f444fb9427ca38b905755835dbf8d5464ab3a197c95  LICENSE
```
