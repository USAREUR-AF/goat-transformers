# Provenance: wms-capabilities pack

SPDX licence: Apache-2.0

Built from the standard's text only (OGC 06-042, Annex E included); the schema file was read to confirm element order and is not copied.

Read on 2026-11-19. No source file is copied into this tree. The pack and the
module `wms` hold element and attribute names and value types from the
standard and its schema; descriptions are in our own words. The vectors are
documents written for this repository by `tools/gen/ogc-geo-vectors.py`.

## Pack `wms-capabilities`, module `wms`

| | |
|---|---|
| Source | OpenGIS Web Map Server Implementation Specification, OGC 06-042, Version 1.3.0, dated 2006-03-15, Open Geospatial Consortium (also ISO 19128:2005) |
| Download | https://docs.ogc.org/is/06-042/06-042.pdf (also reachable from https://www.ogc.org/standards/wms) |
| SHA-256 | `06-042.pdf` `decb8bf74b67ea2b601612abffaedc10b77b176f6493c3a1eb8c22d5b88b2116` |
| Schema | https://schemas.opengis.net/wms/1.3.0/capabilities_1_3_0.xsd (`version="1.3.0.2"`), sha256 `bb2db70912176e3c50aa6476d9c13e45d1cb56e6e83c8b285dca793e3c74bdf7`; read for element order only, the same order Annex E of the document prints |
| Sections used | 7.2.4 GetCapabilities response (7.2.4.2 to 7.2.4.7: service metadata, LayerLimit, MaxWidth and MaxHeight, Layer properties and attributes, EX_GeographicBoundingBox, scale denominators); Annex E.1 capabilities schema |

## License

The document's cover states:

> Copyright © 2006 Open Geospatial Consortium, Inc. All Rights Reserved.
> To obtain additional rights of use, visit http://www.opengeospatial.org/legal/.

Its License Agreement (the OGC Document License Agreement,
https://www.ogc.org/about/policies/document-license-agreement/) begins:

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

The schema's header states "WMS is an OGC Standard. Copyright (c) 2004,2010
Open Geospatial Consortium." and points to the OGC legal page. The pack is
built from the document's text; the schema file is not copied, and its
element order is the order the document's Annex E prints.

**Notice of modification.** This pack states, in its own words, part of the
capabilities document of OGC 06-042. It includes modifications that have not
been approved or adopted by the Open Geospatial Consortium. It is not an OGC
product and claims no compliance with an OGC standard.
