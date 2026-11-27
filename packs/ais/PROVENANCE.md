# Provenance: ais pack

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module `ais` hold bit positions, widths, scale factors and code meanings,
stated in this project's own words.

## Pack `ais`, module `ais`

| | |
|---|---|
| Source | "AIVDM/AIVDO protocol decoding", Eric S. Raymond, the GPSD project |
| Version | v1.58, 24 June 2023 (the document's own revision line) |
| Upstream | https://gitlab.com/gpsd/gpsd, file `www/AIVDM.adoc` |
| Commit | `c59fc6de479d06620c8b2ba395b728e10a71527b` |
| Download | `https://gitlab.com/gpsd/gpsd/-/raw/c59fc6de479d06620c8b2ba395b728e10a71527b/www/AIVDM.adoc` |
| SHA-256 of `www/AIVDM.adoc` | `a55511139751f5b9385166143443c0353f64fc77155b4ef4026f4ab03e3dffbd` |
| License file | `COPYING` at the same commit, sha256 `fdf339997bbca9eaf507476b82fbcac608fc39a3d89b86b51e16db4c9f933716` |

The document carries no license text of its own; it is part of the gpsd
source tree, whose `COPYING` file states:

> Compilation copyright is held by the GPSD project.  All rights reserved.

> LICENSE
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

The document states its own basis, in the section "Improving This Document":

> To avoid copyright difficulties, I rely only on freely redistributable
> public documents and paraphrased reports from people who have seen the
> relevant proprietary standards.

It carries no distribution statement, handling marking, export-control notice
or proprietary notice.

Sections read: "AIVDM/AIVDO Payload Armoring", "AIS Payload Data Types",
"AIS Payload Interpretation" (the message type list and the sections for types
1 to 27, without the subtypes of types 6 and 8), and "AIS Payload Byte
Alignment, Padding, and Bit Stuffing".

## Golden vectors: pyais

`packs/ais/vectors/golden-*.json` are written by `tools/gen/golden-pyais.py`
from pyais, a reference AIS encoder and decoder, not from this pack and not by
any engine (shared-model hardening, item 2). pyais encodes each message and
decodes it again; the vector's input is pyais's payload and its model values
are what pyais decodes.

| | |
|---|---|
| Package | pyais 3.3.1, https://github.com/M0r13n/pyais, wheel `pyais-3.3.1-py3-none-any.whl`, SHA-256 `0ad45f232639cfec7eadb20228a0402e5a0c81e46d3a32a8229eeb384199a093` |
| Dependency | attrs 26.1.0, wheel `attrs-26.1.0-py3-none-any.whl`, SHA-256 `c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309` |
| Pins | `tools/gen/golden-pyais.txt`, installed with `pip --require-hashes` (CI: conformance, "AIS golden vectors are what pyais writes") |
| Licence | MIT (the wheel's `LICENSE`); only its output is used, no code is copied |

## What was not used

ITU-R M.1371, "Technical characteristics for an automatic identification
system using time division multiple access in the VHF maritime mobile band",
is the standard the gpsd document describes. It was not read and nothing in
the pack is taken from it. The ITU publishes its Recommendations for download
under terms that allow personal, non-commercial use and do not allow
derivative works; a pack is a derivative statement of the layout and is
distributed under Apache-2.0, so those terms do not allow it. It is cited in
`pack.md` only as the standard behind the source.

IEC 61162 and NMEA 0183, which define the `AIVDM` sentence around the
payload, are priced standards and were not read. The pack does not describe
the sentence.
