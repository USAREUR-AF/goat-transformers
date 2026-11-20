# Provenance: mf-json pack

SPDX licence: Apache-2.0

Read on 2026-11-20. No source file is copied into this tree. The pack and the module
`mfjson` hold member names and value forms that the standard's text states; descriptions
are in our own words. Every message in the vectors is written for this repository.

## Pack `mf-json`, module `mfjson`

| | |
|---|---|
| Source | OGC Moving Features Encoding Extension - JSON (MF-JSON), Version 1.0, OGC 19-045r3 (OGC Implementation Standard, published 2020-06-02), Open Geospatial Consortium |
| Download | https://docs.ogc.org/is/19-045r3/19-045r3.html |
| SHA-256 | `19-045r3.html`, 4182244 bytes, `80200e8c642d0084b3884bca0d25a972fec331147de2016fe9a8f4be2f46e871` |
| Sections used | 7.1 MF-JSON Trajectory; 7.2.1 TemporalGeometry and 7.2.1.1 TemporalPrimitiveGeometry; 7.2.4 MovingFeature; 7.2.6 LifeSpan; 7.2.7 BoundingBox; 7.2.10 MotionCurve |

## Schema files not used

Per the operator decision of 2026-11-20, the MF-JSON JSON Schema files were not used: the
lead reported a reservation of all rights on them. The copies in the repository
`opengeospatial/mf-json` (commit `bf0f7cbb1efcffff97482a7fd7e9f7153c261ca5`,
`json-schema/MF-JSON_Prism.schema.json` and `MF-JSON_Trajectory.schema.json`) state no
license of their own either. Nothing in this pack was taken or derived from them; the pack
and the vectors were written from the standard's text alone, which is cited above.

## License

The document's cover states:

> Copyright © 2020 Open Geospatial Consortium
> To obtain additional rights of use, visit http://www.opengeospatial.org/legal/

It states that it is an OGC Member approved international standard, available on a
royalty free, non-discriminatory basis. Its License Agreement (the OGC Document License
Agreement, https://www.ogc.org/about/policies/document-license-agreement/) begins:

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

The rest of the agreement disclaims warranties and patent rights, provides for
termination, reserves the OGC name and marks, and names the governing law.

Basis of use (operator decision of 2026-11-20 for the OGC formats): the OGC document
license permits implementing and modifying with the notice kept. This pack implements the
standard from its text: it holds member names and value forms the standard states, with
descriptions in our own words, and copies no text, table or example message. **This pack
is a modification that has not been approved or adopted by the OGC.**
