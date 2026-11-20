# Provenance: kml pack

SPDX licence: LicenseRef-OGC-Software (element names and value types are taken from the OGC schema files ogckml22.xsd and ogckml23.xsd as well as from the standards' text).

OGC 07-147r2 read on 2026-11-19; OGC 12-007r2 read on 2026-11-20. No source
file is copied into this tree. The pack and the
module `kml` hold element names and value types from the standard and its
schema; descriptions are in our own words. The vectors are messages written
for this repository.

## Pack `kml`, module `kml`

| | |
|---|---|
| Source | OGC KML, OGC 07-147r2, Version 2.2.0, dated 2008-04-14, Open Geospatial Consortium (OGC Standard, Encoding) |
| Download | https://docs.ogc.org/is/07-147r2/07-147r2.pdf (also reachable from https://www.ogc.org/standards/kml) |
| SHA-256 | `07-147r2.pdf` `fcad423c7700c13e4a25bcf1c305ee241d8470e94128b7185c377c47d6b82b77` |
| Schema | https://schemas.opengis.net/kml/2.2.0/ogckml22.xsd (`ogckml22.xsd 2008-01-23`), sha256 `67bb8fd82e7098245360f2aeb2afb561a8eb868ec3660dc06542475f67a4b665` |
| Sections used | 6.2 Coordinate Reference System; 9.1 AbstractFeatureGroup; 9.17 altitudeMode; 10.3 Point; 16.9 coordinatesType; 16.10 dateTimeType |

| | |
|---|---|
| Source | OGC KML 2.3, OGC 12-007r2, Version 1.0, published 2015-08-04, Open Geospatial Consortium (OGC Standard, Encoding) |
| Download | https://docs.ogc.org/is/12-007r2/12-007r2.html |
| SHA-256 | `12-007r2.html` `497c1353565b9f30f1d5660d1edbe8f8e75c415d49bdfdf8f48f864d9d58e2f3` (the HTML page as served on the date read) |
| Schema | https://schemas.opengis.net/kml/2.3/ogckml23.xsd (`version="2.3.0"`), sha256 `5222be3703c634add22c0bfa0f90df8935cb01c4a1c60b287d33dc88fc695bcd` |
| Sections used | 5.2 XML namespaces; 5.4 versioning; 6.2 Coordinate Reference System; 10.15 kml:Track; 10.16 kml:MultiTrack; schema TrackType, MultiTrackType, dateTimeType |

## License

The cover of OGC 07-147r2 states:

> Copyright © 2007, 2008 Open Geospatial Consortium, Inc. All Rights Reserved.
> To obtain additional rights of use, visit http://www.opengeospatial.org/legal/.

The cover of OGC 12-007r2 states:

> Copyright © 2015 Open Geospatial Consortium
> To obtain additional rights of use, visit http://www.opengeospatial.org/legal/ .

The License Agreement of each document (the same text as the OGC Document License Agreement,
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

The schema's header: "XML Schema Document for OGC KML version 2.2. Copyright
(c) 2008 Open Geospatial Consortium." The KML 2.3 schema's header states the
same for version 2.3 with "Copyright (c) 2015 Open Geospatial Consortium." and
points to the OGC legal page for further rights. Neither schema file is
copied: element names and types are taken from the standards' text and stated
in our own words. This pack implements the standards; it copies no text of
them and does not redistribute them. As the agreement asks of a modification:
this pack includes modifications that have not been approved or adopted by the
Open Geospatial Consortium.
