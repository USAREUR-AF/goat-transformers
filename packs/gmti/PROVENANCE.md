# Provenance: gmti

`distribution public`.

| Source | Where published | Version | SHA-256 of the copy read |
|---|---|---|---|
| NATO AEDP-4607, NATO Ground Moving Target Indicator Format (GMTIF), the layouts of STANAG 4607 | NSG Standards Registry, nsgreg.nga.mil | Edition A Version 1, February 2024 | `74f5b8f354832150d01d518610fd0cb006d3a026a96a5673d8d480fb82a541ae` |
| NATO AEDP-4607.1, GMTIF implementation guide | NSG Standards Registry, nsgreg.nga.mil | Edition A Version 1 | `a5a8372e489442ffc0b3ce98c2fc0253092d0896dc841ab491c41fbf546a39d4` |

The MAJIIC 2 STANAG 4607 GMTI Implementation Guide (document version 3.0, 29
October 2015) was read for how packets are composed. No layout is taken from it
and it is not quoted.

## Release basis

The documents are published on the public NSG Standards Registry
(nsgreg.nga.mil), where they were downloaded on 2026-10-08 with open access.
Each carries "(c) NATO/OTAN" and asks that NATO be acknowledged when it is
reproduced; NATO charges no fee for its standardization documents, and they
are handled under C-M(2002)60, NATO's policy for non-classified information.
They carry no classification marking. NATO is acknowledged here and in
`pack.md`.

This pack restates the layouts in this project's own names and words. No text,
table or figure of any document is copied, and no document is held in this
repository.

What was taken: the packet header and the layouts of ten segment types
(chapters 3 and 4 of AEDP-4607), the data conventions of its Annex C (binary
angles, sign-magnitude fixed point, byte order), the existence-mask mappings,
and the target classification enumeration (mapped onto the shared
`track.class` vocabulary). All are restated in `tools/gmti/segments.tsv`,
`kinds.tsv` and `tables.tsv` in this repository's own names and words. From
AEDP-4607.1: that the range-doppler segment was folded into the HRR segment,
that the controlled extension segments 128 to 132 have no published layout,
and the exploitation-class existence masks (the situation class mask is used
in a vector).
