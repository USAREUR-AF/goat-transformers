# Provenance: nmea0183 pack

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module hold field positions, number layouts, units and fixed letters, stated in
this project's words; no text, table or example sentence of the source is
copied.

## Pack `nmea0183`, module `nmea0183`

| | |
|---|---|
| Source | "NMEA Revealed", a list of NMEA 0183 sentences with their fields, by Eric S. Raymond and the gpsd project |
| Upstream | https://gitlab.com/gpsd/gpsd, file `www/NMEA.adoc`; published as a web page at https://gpsd.io/NMEA.html |
| Version | commit `c59fc6de479d06620c8b2ba395b728e10a71527b`; the document's header date is 12 July 2025 |
| Download | `https://gitlab.com/gpsd/gpsd/-/raw/c59fc6de479d06620c8b2ba395b728e10a71527b/www/NMEA.adoc` |
| File | `www/NMEA.adoc`, 3105 lines, sha256 `83192561db3198d46ef249233c689de2c9735af162c840155d11e6157574d29e` |
| License file | `COPYING` at the same commit, sha256 `fdf339997bbca9eaf507476b82fbcac608fc39a3d89b86b51e16db4c9f933716` |

Both hashes were checked against the files downloaded from the address above at
that commit.

The document carries no license line of its own; the license of the gpsd tree
is in `COPYING`, which begins:

> Compilation copyright is held by the GPSD project.  All rights reserved.
>
> GPSD project copyrights are assigned to the project lead, currently
> Eric S. Raymond.

and states the license as:

> (SPDX short identifier: BSD-2-Clause)
>
> Redistribution and use in source and binary forms, with or without
> modification, are permitted provided that the following conditions
> are met:
>
> 1. Redistributions of source code must retain the above copyright
>    notice, this list of conditions and the following disclaimer.
>
> 2. Redistributions in binary form must reproduce the above copyright
>    notice, this list of conditions and the following disclaimer in the
>    documentation and/or other materials provided with the distribution.

On its relation to the NMEA standard, the document states (section "Sources and
Applicable Standards"):

> The official NMEA 0183 standard was not consulted at any
> point, thus this document is not a derivative work of that standard

The NMEA 0183 standard and IEC 61162-1 are priced documents and were not read.
Every layout statement in the pack is the gpsd document's.

Sections read: "NMEA version timeline", "Sentence Mixes and NMEA Variations",
"NMEA Encoding Conventions", "Dates and times", "Error status indications",
"Talker IDs", "Satellite IDs", "DTM", "GGA", "GLL", "GSA", "GSV", "HDT",
"RMC", "VTG", "ZDA".

## Added sentences

The kinds GNS, HDM, HDG, THS, ROT, VHW, MWV, MWD, DBT, DPT, MTW, TTM, TLL,
OSD and DTM were written from the two sources below, read on 2026-11-19, not
from "NMEA Revealed".

| | pynmea2 (field order and names) | gpsd NMEA driver (units and meanings) |
|---|---|---|
| Upstream | https://github.com/Knio/pynmea2 | https://gitlab.com/gpsd/gpsd |
| Version | commit `d8240dca51bd3f731b3fb7af8f0f9978c9b08f1a` | commit `c59fc6de479d06620c8b2ba395b728e10a71527b` |
| Download | `https://codeload.github.com/Knio/pynmea2/tar.gz/d8240dca51bd3f731b3fb7af8f0f9978c9b08f1a`, sha256 `fbd85b707a17bd9978a602fdd4340d8eee318b6075e51e9972992b14760e4c52` | `https://gitlab.com/gpsd/gpsd/-/raw/c59fc6de479d06620c8b2ba395b728e10a71527b/drivers/driver_nmea0183.c` |
| File | `pynmea2/types/talker.py`, sha256 `dacfe523dd1ed177925066db3426f0465fe396d1431697508b3b2aec365bf668`: the `fields` tables of the fifteen classes | `drivers/driver_nmea0183.c`, sha256 `63abff66fb824f350d365b3a4c6b66effd2f7cd0c697b3e236e97a4f59a580b8`: the comments and handling of GNS, HDM, HDG, THS, ROT, MWV, MWD, DBT, DPT, MTW, DTM |
| License | `LICENSE`, sha256 `4736b5d379253afa45744afc79ddb475912b213e939bdf7cb97d9a8b6f700e5f`: the MIT License | the file's header: "This file is Copyright by the GPSD project", "SPDX-License-Identifier: BSD-2-clause"; `COPYING` as above |

The MIT grant, quoted from pynmea2's `LICENSE`:

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, [...] subject to the following conditions: The above
> copyright notice and this permission notice shall be included in all copies
> or substantial portions of the Software.

No code of either is copied. The example sentences in the gpsd driver's
comments are not used, and pynmea2's tests, examples and its file
`NMEA0183.pdf` (whose terms are not stated) were not read; every sentence in
vectors 44-64 is written for this pack by `tools/gen/nmea0183-more-vectors.py`.

