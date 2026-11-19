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
