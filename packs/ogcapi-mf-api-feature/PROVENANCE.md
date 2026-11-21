# Provenance of the ogcapi-mf-api-feature pack

SPDX licence: LicenseRef-unstated

`tools/gen/jsonschema2pack.py` (run script `tools/gen/ogcapi-movingfeatures-api-run.sh`) reads
the schema files that `pack.md` lists with their SHA-256, and nothing else. The files are not
kept in this repository. Read on 2026-11-20.

## Source

| | |
|---|---|
| Document | OGC API - Moving Features - Part 1: Core, the API's response schemas |
| Publisher | Open Geospatial Consortium (OGC) |
| Repository | https://github.com/opengeospatial/ogcapi-movingfeatures, default branch, commit `889d086a468bf092e63d7bb356cf14866502bc22`, `openapi/schemas/*.yaml`; `LICENSE` SHA-256 `b3b9a76d230f057844d004c374406453d92f863caecaa42ccd9c7863e143fed1` |
| Referenced schema | https://schemas.opengis.net/movingfeatures/1.0/MF-JSON_Prism.schema.json (OGC Moving Features Encoding Extension - JSON, Prism schema), SHA-256 `125b3b380c10850e5ee952803a797ed11dce7348df9d0c908393c8e30c4e2402`, served 2026-11-20 (Last-Modified 2025-04-09) |
| Also read | https://github.com/opengeospatial/ogcapi-features tag `1.0.1`, commit `4ff19a5734578cf1f815d03ab192e8e0dc407e9f`, `core/openapi/schemas/link.yaml` (OGC Software License) |

## Licence

The response schemas are in a repository under the OGC Software License (quoted below). They
refer to the MF-JSON Prism schema on schemas.opengis.net, OGC's official schema repository;
that file carries no licence statement and no notice of its own (it is not headed "All
Rights Reserved"), and the repository's index page names OGC's legal notices without a
licence for the file. The pack is therefore labelled `LicenseRef-unstated` (REUSE.toml), as
the operator decided. It includes modifications that have not been approved or adopted by
OGC. Copyright (C) Open Geospatial Consortium.

OGC's notice for the repository's files, verbatim from its `LICENSE`:

> Permission is hereby granted by the Open Geospatial Consortium, ("Licensor"), free of charge and subject to the terms set forth below, to any person obtaining a copy of this Intellectual Property and any associated documentation, to deal in the Intellectual Property without restriction (except as set forth below), including without limitation the rights to implement, use, copy, modify, merge, publish, distribute, and/or sublicense copies of the Intellectual Property, and to permit persons to whom the Intellectual Property is furnished to do so, provided that all copyright notices on the intellectual property are retained intact and that each person to whom the Intellectual Property is furnished agrees to the terms of this Agreement.
>
> If you modify the Intellectual Property, all copies of the modified Intellectual Property must include, in addition to the above copyright notice, a notice that the Intellectual Property includes modifications that have not been approved or adopted by LICENSOR.
>
> THIS LICENSE IS A COPYRIGHT LICENSE ONLY, AND DOES NOT CONVEY ANY RIGHTS UNDER ANY PATENTS THAT MAY BE IN FORCE ANYWHERE IN THE WORLD.
>
> THE INTELLECTUAL PROPERTY IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT OF THIRD PARTY RIGHTS. THE COPYRIGHT HOLDER OR HOLDERS INCLUDED IN THIS NOTICE DO NOT WARRANT THAT THE FUNCTIONS CONTAINED IN THE INTELLECTUAL PROPERTY WILL MEET YOUR REQUIREMENTS OR THAT THE OPERATION OF THE INTELLECTUAL PROPERTY WILL BE UNINTERRUPTED OR ERROR FREE. ANY USE OF THE INTELLECTUAL PROPERTY SHALL BE MADE ENTIRELY AT THE USER’S OWN RISK. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR ANY CONTRIBUTOR OF INTELLECTUAL PROPERTY RIGHTS TO THE INTELLECTUAL PROPERTY BE LIABLE FOR ANY CLAIM, OR ANY DIRECT, SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES, OR ANY DAMAGES WHATSOEVER RESULTING FROM ANY ALLEGED INFRINGEMENT OR ANY LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR UNDER ANY OTHER LEGAL THEORY, ARISING OUT OF OR IN CONNECTION WITH THE IMPLEMENTATION, USE, COMMERCIALIZATION OR PERFORMANCE OF THIS INTELLECTUAL PROPERTY.
>
> This license is effective until terminated. You may terminate it at any time by destroying the Intellectual Property together with all copies in any form. The license will also terminate if you fail to comply with any term or condition of this Agreement. Except as provided in the following sentence, no such termination of this license shall require the termination of any third party end-user sublicense to the Intellectual Property which is in force as of the date of notice of such termination. In addition, should the Intellectual Property, or the operation of the Intellectual Property, infringe, or in LICENSOR’s sole opinion be likely to infringe, any patent, copyright, trademark or other right of a third party, you agree that LICENSOR, in its sole discretion, may terminate this license without any compensation or liability to you, your licensees or any other party. You agree upon termination of any kind to destroy or cause to be destroyed the Intellectual Property together with all copies in any form, whether held by you or by any third party.
>
> Except as contained in this notice, the name of LICENSOR or of any other holder of a copyright in all or part of the Intellectual Property shall not be used in advertising or otherwise to promote the sale, use or other dealings in this Intellectual Property without prior written authorization of LICENSOR or such copyright holder. LICENSOR is and shall at all times be the sole entity that may authorize you or any third party to use certification marks, trademarks or other special designations to indicate compliance with any LICENSOR standards or specifications. This Agreement is governed by the laws of the Commonwealth of Massachusetts. The application to this Agreement of the United Nations Convention on Contracts for the International Sale of Goods is hereby expressly excluded. In the event any provision of this Agreement shall be deemed unenforceable, void or invalid, such provision shall be modified so as to make it valid and enforceable, and as so modified the entire Agreement shall remain in full force and effect. No decision, action or inaction by LICENSOR shall be construed to be a waiver of any rights or remedies available to it.
