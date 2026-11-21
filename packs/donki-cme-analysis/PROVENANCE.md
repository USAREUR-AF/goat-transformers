# Provenance of the donki-cme-analysis pack

SPDX licence: Apache-2.0

`tools/gen/jsonschema2pack.py` (run script `tools/gen/space-run.sh`) generates this pack from this
project's restatement `tools/gen/space/donki-api-2.0-objects.json` (SHA-256 `83e2bcbe458ef5bd48114a3587718b0bb0cbd5defd10ee70d953073201d63eff`), schema `CMEAnalysisObject`. The source is not kept in
this repository. Read on 2026-11-21.

## Source

| | |
|---|---|
| Document | CCMC DONKI-API, OpenAPI 3.0.1 document, `info.version` 2.0 |
| Publisher | Community Coordinated Modeling Center, NASA Goddard Space Flight Center, United States |
| Address | https://ccmc.gsfc.nasa.gov/DONKI/api/openapi/, served 2026-11-21; the document has no versioned address, so this copy is pinned |
| SHA-256 | `16d2253db190cd4e8673ffc40f3d7fae2facde48cef09ef4ce93157c5705430d` (55,295 bytes of JSON as served) |
| Schema | `components.schemas.CMEAnalysisObject`, the items of `GET /get/CMEAnalysis` |
| Responses read | `GET /get/CMEAnalysis` for 2026-10-01 to 2026-11-20 (through ccmc.gsfc.nasa.gov or api.nasa.gov) where the endpoint answered, to check the time notation; not kept, and no value of them is in a vector |

## Licence

The OpenAPI document is published by the Community Coordinated Modeling Center of NASA's
Goddard Space Flight Center, an office of NASA, a United States Government agency. It
carries no licence or copyright notice. A work of the United States Government has no
copyright protection in the United States (17 U.S.C. 105). NASA's Images and Media Usage
Guidelines (https://www.nasa.gov/nasa-brand-center/images-and-media/, read 2026-11-21)
state:

> NASA content – images, audio, video, and media files used in the rendition of
> 3-dimensional models, such as texture maps and polygon data in any format – generally
> are not subject to copyright in the United States.

and that NASA should be acknowledged as the source. The DONKI disclaimer
(https://ccmc.gsfc.nasa.gov/tools/DONKI/#disclaimer, read 2026-11-21) provides the data
"as is" and states that using it implies no endorsement by NASA. This pack restates the
member names and types of the API's objects; it carries the project's licence, Apache-2.0
(the default annotation), as the NWS packs restated from the weather.gov OpenAPI document
do. Credit: NASA CCMC, the DONKI team and the Moon to Mars Space Weather Analysis Office.
The pack is not NASA material and implies no endorsement by NASA.

No document read carries a handling marking, a distribution statement or an export-control
notice.
