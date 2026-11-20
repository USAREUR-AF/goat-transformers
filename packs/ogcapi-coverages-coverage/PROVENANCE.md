# Provenance of the ogcapi-coverages-coverage pack

SPDX licence: Apache-2.0

Written by hand from the text of the standard; the vectors by
`tools/gen/ogcapi-coverages-vectors.py`. The document is not kept in this repository.
Read on 2026-11-20.

## Source

| | |
|---|---|
| Document | OGC Coverage Implementation Schema (CIS) with Corrigendum, version 1.1.1, OGC 09-146r8 (approved 2019-06-27, published 2019-10-28) |
| Publisher | Open Geospatial Consortium (OGC) |
| Address | https://docs.ogc.org/is/09-146r8/09-146r8.html |
| SHA-256 | `031d61c079c865a9b8b3957b9453f9660749729b85f067edd5e77092f3b48b4d` (the HTML document as served on 2026-11-20) |
| Parts read | clause 6 (coverage structure, envelope, range type), clause 7 (general grid, index and regular axes), clause 8 (irregular axes), clause 13 (class `json-coverage`) |
| Not read | the CIS JSON Schema files (`schemas.opengis.net/cis/1.1/json/`, and their copy in `opengeospatial/ogcapi-coverages`, `standard/openapi/schemas/cis/`): they are headed "All Rights Reserved" |

## Licence

The document is an OGC standard, approved for public release and available on a royalty-free
basis; its front matter carries "Copyright (C) 2019 Open Geospatial Consortium" and OGC's
licence agreement, which grants the rights to implement, use, copy and modify. A standard's
text is free to implement. Following the project's rule for a schema file headed "All Rights
Reserved", nothing in this pack is copied or derived from the schema files: the member names
and types are restated from the document's structure tables and from the JSON example of
clause 13, in the project's own words, and no example message or table is copied. The pack
is therefore the project's own work under Apache-2.0 (REUSE.toml). It describes OGC's
standard; OGC has not approved or adopted it.
