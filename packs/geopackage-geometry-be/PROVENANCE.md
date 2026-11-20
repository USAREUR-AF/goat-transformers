# Provenance: geopackage-geometry-be pack

SPDX licence: Apache-2.0

Built from the standard's text only (OGC 12-128r19, OGC 06-103r4); no OGC schema file is used.

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module `gpkg` (shared with `geopackage-geometry-le`) hold the byte layout,
flag values and type codes the sources state; descriptions are in our own
words. The vectors are messages built for this repository by
`tools/gen/ogc-geo-vectors.py`.

## GeoPackage

| | |
|---|---|
| Source | OGC GeoPackage Encoding Standard, OGC 12-128r19, Version 1.4.0, published 2024-02-06, Open Geospatial Consortium (OGC Standard, Encoding) |
| Download | https://docs.ogc.org/is/12-128r19/12-128r19.html (the same text: http://www.geopackage.org/spec140/) |
| SHA-256 | `12-128r19.html` `a1de5c6d82e94673086c32f39b7bce35a555b404ab2abb796475bea9520b7137`; `spec140/index.html` `a0cb07273e2bd901f4caf496033db317d7e3c55418de1dbd6afe6d116356c2b6` |
| Sections used | 1.1.2 Spatial Reference Systems (Requirement 11, the record for srs_id 4326); 2.1.3 Geometry Encoding (the binary header, Table 5 flags byte, axis order, Requirement 152 empty geometries) |

## Well-known Binary

| | |
|---|---|
| Source | OpenGIS Implementation Standard for Geographic information - Simple feature access - Part 1: Common architecture, OGC 06-103r4, Version 1.2.1, dated 2011-05-28 |
| Download | https://docs.ogc.org/is/06-103r4/06-103r4.pdf |
| SHA-256 | `06-103r4.pdf` `4e64b5a22815a680e24c8d07af5d86df3abebc0b9bb7f40939a0c539dd3d56a9` |
| Sections used | 8.2 Well-known Binary Representation for Geometry (byte order values, geometry type 1, the Point structure) |

## License

GeoPackage's front matter states:

> Copyright © 2024 Open Geospatial Consortium.
> To obtain additional rights of use, visit http://www.opengeospatial.org/legal/

OGC 06-103r4 states "Copyright © 2010 Open Geospatial Consortium, Inc." with
the same pointer to the OGC legal page. Both carry the OGC License Agreement
(the OGC Document License Agreement,
https://www.ogc.org/about/policies/document-license-agreement/), which begins:

> Permission is hereby granted by the Open Geospatial Consortium, ("Licensor"),
> free of charge and subject to the terms set forth below, to any person
> obtaining a copy of this Intellectual Property and any associated
> documentation, to deal in the Intellectual Property without restriction
> (except as set forth below), including without limitation the rights to
> implement, use, copy, modify, merge, publish, distribute, and/or sublicense
> copies of the Intellectual Property, and to permit persons to whom the
> Intellectual Property is furnished to do so, provided that all copyright
> notices on the intellectual property are retained intact and that each
> person to whom the Intellectual Property is furnished agrees to the terms of
> this Agreement.
>
> If you modify the Intellectual Property, all copies of the modified
> Intellectual Property must include, in addition to the above copyright
> notice, a notice that the Intellectual Property includes modifications that
> have not been approved or adopted by LICENSOR.

**Notice of modification.** This pack states, in its own words, the layout
of OGC 12-128r19 clause 2.1.3 and OGC 06-103r4 clause 8.2. It includes
modifications that have not been approved or adopted by the Open Geospatial
Consortium. It is not an OGC product and claims no compliance with an OGC
standard.
