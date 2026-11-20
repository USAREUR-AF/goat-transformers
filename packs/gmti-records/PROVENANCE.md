# Provenance: gmti-records

Same sources, versions, SHA-256 and release basis as `packs/gmti/PROVENANCE.md`
(AEDP-4607 Edition A Version 1 and AEDP-4607.1 Edition A Version 1, NSG
Standards Registry). `distribution public`. NATO is acknowledged as the source
of the layouts, which are restated in this project's own words.

Taken: the segment layouts of AEDP-4607, and from AEDP-4607.1 Annex C the field sets of the
situation, targeting and targeting-with-HRR exploitation classes, from which each kind's mask is
computed. The guide's stated targeting mask (`ff c7 1f fa 7f 80 00 00`) disagrees with its own
field table; `dwell-targeting` follows the table (`ff 07 1f fb 9f 80 00 00`) and
`dwell-targeting-as-masked` reads the stated mask. The stated HRR mask (`ff ff f0`) disagrees
with the HRR field table too; the HRR kinds follow the table.
