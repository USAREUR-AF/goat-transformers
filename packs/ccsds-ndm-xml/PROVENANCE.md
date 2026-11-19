# Provenance: ccsds-ndm-xml pack

Read on 2026-11-19. No source file is copied into this tree. `pack.def`,
`pack.md`, `model/ccsdsndm.def` and `vectors/gen-*.json` are written by
`tools/gen/xsd2pack.py` (run script `tools/gen/ccsds-run.sh`) from the schema
files below; element and attribute names and types come from them. The
hand-written vectors `vectors/0*.json` hold messages written for this pack,
not examples copied from a standard.

## Schema set

| | |
|---|---|
| Document | NDM/XML schema set 4.0.0 (version 4.0, Rev 0), the variant with `elementFormDefault="unqualified"`, for CCSDS 505.0-B-3 |
| Publisher | CCSDS, through the Space Assigned Numbers Authority (SANA) registry "Navigation Data Messages XML Schema (Unqualified)", authority CCSDS.MOIMS.NAV, OID 1.3.112.4.39.2 |
| Registry page | https://sanaregistry.org/r/ndmxml_unqualified (update date 2024-08-21 when read) |
| Download | `https://sanaregistry.org/files/ndmxml_unqualified/<name>` |

| File | Bytes | SHA-256 |
|---|---|---|
| `ndmxml-4.0.0-master-4.0.xsd` | 4065 | `2abc69ce7b09a14a06223ca73e9962dffe2721997636f24145523a4db67adf36` |
| `ndmxml-4.0.0-namespace-4.0.xsd` | 4263 | `452daae18e9b98f8542c013d2e12581aaa81165d9646bd387c1f72e4dd5336a6` |
| `ndmxml-4.0.0-acm-2.0.xsd` | 13627 | `0c46c47085cf2a8cfd98974edec0380d619587c861a0ebd2b722e30668ca5b21` |
| `ndmxml-4.0.0-aem-2.0.xsd` | 6457 | `4cce5b5e2bf0d9b7f925c7c27c9e202b72295c99f87f4987be847e59a57ca5f3` |
| `ndmxml-4.0.0-apm-2.0.xsd` | 6019 | `9c88db63741cd6dc49398ab48f9972973371d8e0d4fdce2bff1fa09ee9ead93d` |
| `ndmxml-4.0.0-cdm-1.0.xsd` | 20885 | `9814cb81bcc275bb08fc87844cd663774fcf2dc7636a070963a797b1dab2f494` |
| `ndmxml-4.0.0-ocm-3.0.xsd` | 25133 | `68835f8d1674e3ed3c10cde296a1f2c7df6b575c1599395531ab963caee915fa` |
| `ndmxml-4.0.0-oem-3.0.xsd` | 6576 | `7dc5ff90492d5570f386f1d640a8ec6d0fe9955ed2248ae05fb3255c75ca8b9a` |
| `ndmxml-4.0.0-omm-3.0.xsd` | 11243 | `e54622ea48972a923c1edee607f717257262114ae5ad7bdba031d1bbd28e2a1a` |
| `ndmxml-4.0.0-opm-3.0.xsd` | 7926 | `193e2effa72727e933eaaa8283c6f47bcd8e1b44f7675b8be13ba30623499519` |
| `ndmxml-4.0.0-rdm-1.0.xsd` | 8635 | `ffb45a290c65254dad76ff4c6af554a14256a74c5684432c0799631a51e4eea8` |
| `ndmxml-4.0.0-tdm-2.0.xsd` | 19642 | `19ab390e06c8ebbb1f9585f044fc044edd5e453e6c8f0de24bdde63a1f3f7dd8` |
| `ndmxml-4.0.0-ndm-4.0.xsd` | 6049 | `14df592d0991d6230e677f2e2bf1e5b971567b514313b0d3c019f534e2e162c5` |
| `ndmxml-4.0.0-common-4.0.xsd` | 65364 | `3ae25a917a8297dc7c77f98569e939351b5247e3216d239189fd6934d8d5dcde` |

Not read: `ndmxml-2.0.0-cdm-1.1.xsl` (a style sheet from CDM XML to the
keyword-value form, listed in the same registry), and the qualified variant
(https://sanaregistry.org/r/ndmxml_qualified), which differs from these files
in `elementFormDefault` (and `attributeFormDefault`) only. A document of the
qualified variant puts every element in the namespace
`urn:ccsds:schema:ndmxml` with a prefix; the `xml` wire compares element
names as written and has no namespace processing (docs/roadmap.md, "XML
namespaces and prefixes", Designed), so such a document is `no-kind` here
(vector `04-prefixed-root-is-no-kind`).

## Blue Books read

| Document | Download | SHA-256 | Used for |
|---|---|---|---|
| CCSDS 505.0-B-3, XML Specification for Navigation Data Messages, May 2023, Editorial Change 2 | https://ccsds.org/Pubs/505x0b3e2.pdf | `21516570863fd85a3f9d4a322ae008054113e7d6840cd43918c44bc2bb238c09` | the two schema variants, the root attributes of an instance (section 4.3) |
| CCSDS 502.0-B-3, Orbit Data Messages, April 2023 | https://ccsds.org/Pubs/502x0b3e1.pdf | `97d1687b4a461ffdf965b9b65923820cc6aa9d1d1c4d4df77a598a53d4a49d81` | meaning of `OBJECT_NAME`, `OBJECT_ID`, `REF_FRAME`, `TIME_SYSTEM`, `EPOCH` in the OPM and OMM (tables 3-2, 3-3, 4-2) |
| CCSDS 504.0-B-2, Attitude Data Messages, January 2024 | https://ccsds.org/Pubs/504x0b2.pdf | `0869187cb326dbf009e6f17a1fd6e920b7b4a4f8f6446706b314e2d9a6121214` | meaning of `OBJECT_NAME` and `OBJECT_ID` in the APM (table 3-2) |

## License and terms

The schema files carry no license, copyright or distribution statement in
their headers (the generator's header check finds none; the comments state the
version, the compatible Blue Books and a change log). They are published
without registration or charge in the SANA registry, which CCSDS operates for
its standards, and CCSDS 505.0-B-3 names those registry addresses as the place
to obtain them. The Blue Books carry no copyright notice, distribution
statement, handling marking or export-control notice. The terms of reuse are
the CCSDS "Reproduction Permission Statement for Publications", shown on
https://ccsds.org/publications/ (read 2026-11-19):

> In general, reasonable reuse of materials published in CCSDS documents is
> permitted with attribution, and reprint permission can be provided in
> writing for those organizations that require formal permission statements.

The run script passes that statement to the generator with
`--public-statement`, and the generator records it in a `source` line of
the pack and the module. This pack reuses names and types with attribution in
its `source` lines, this file and `NOTICE`; it reprints no text, table or
figure.
