# Provenance: ais-binary pack

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module `aisbin` hold bit positions, widths, field names and code meanings,
stated in this project's own words. The vectors of
`tools/gen/ais-binary-vectors.py` are built from those layouts and from values
chosen there; no sample message is used.

## Pack `ais-binary`, module `aisbin`

The source is the same document, at the same commit, as pack `ais`
(`packs/ais/PROVENANCE.md`):

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

followed by the two conditions of the BSD 2-Clause license, quoted in full in
`packs/ais/PROVENANCE.md`. The document states its basis, in the section
"Improving This Document":

> To avoid copyright difficulties, I rely only on freely redistributable
> public documents and paraphrased reports from people who have seen the
> relevant proprietary standards.

Sections read: "Type 6: Binary Addressed Message" and "Type 8: Binary
Broadcast Message", each with the subtype sections that follow it, and the
code tables those subtypes refer to.

## What was not used

The documents behind the subtypes were not read and nothing in the pack is
taken from them: IMO SN/Circ.236 and SN.1/Circ.289 (IMO copyright), the
inland AIS standard of the Central Commission for the Navigation of the Rhine
(the source's INLAND reference) and IALA Recommendation A-126 (the AtoN
monitoring messages). ITU-R M.1371, the standard behind every AIS message,
was not read, for the reason `packs/ais/PROVENANCE.md` gives.
