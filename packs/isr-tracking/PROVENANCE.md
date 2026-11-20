# Provenance: isr-tracking

`distribution public`.

| Source | Where published | Version | SHA-256 of the copy read |
|---|---|---|---|
| NATO AEDP-12, NATO Intelligence, Surveillance and Reconnaissance Tracking Standard (STANAG 4676) | NSG Standards Registry, nsgreg.nga.mil | Edition B Version 2, March 2022 | `c55573231a5882f031862b06589d5a7abaeda9cf7c0b7a55d81843eeb7dc138b` |
| NATO AEDP-12, the same (read to compare; the class tables agree with Version 2 for this pack's use) | NSG Standards Registry, nsgreg.nga.mil | Edition B Version 1 | `234ae941a5ff6bbda9083074e27b4ac585a590722c52562e3b28c8dc8813efb2` |
| NATO AEDP-12.1, implementation guidance (read for the shape of XML instances; no layout taken) | NSG Standards Registry, nsgreg.nga.mil | Edition A Version 1 | `7a4267fced81c760c8a8b487a70b9bb8507b9f765cb32bc4a0a97996b0c4341d` |

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

Taken: the class attribute tables of sections 2.5 and 2.6 (class, attribute name, type,
multiplicity), listed into `tools/isr-tracking/model.tsv` by `tools/isr-tracking/uml2tsv.py`;
the rule of section 2.1.1.7 (attributes are elements, `type` is an XML attribute); the root
element of Annex B.1; the `xsi:type` rule for abstract classes; the two concrete classes of
Shape. The XML schema the standard makes normative is not held (Annex B.5 places it on an
access-controlled NATO site); every assumption this pack makes in its place is in `pack.md`.
The guide's example writes the confidence type as an element; the pack follows the standard's
rule that `type` is an XML attribute.
