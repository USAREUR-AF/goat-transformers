# Provenance: fhir-r4-enrollment-response pack

SPDX licence: CC0-1.0

Read on 2026-11-20. No source file is copied into this tree. The pack, the module
`fhirr4enrollmentresponse`, `pack.md` and the round-trip vectors are written by
`tools/gen/jsonschema2pack.py`, run by `tools/gen/fhir-run.sh`, from the `EnrollmentResponse` definition
of the FHIR R4 JSON schema. This file is written by that script from
`tools/gen/fhir/provenance.md`.

## Pack `fhir-r4-enrollment-response`, module `fhirr4enrollmentresponse`

| | |
|---|---|
| Source | HL7 FHIR Release 4 (Technical Correction #1), version 4.0.1, the JSON schema `fhir.schema.json`, definition `EnrollmentResponse` |
| Download | https://hl7.org/fhir/R4/definitions.json.zip, sha256 `ecd74b1d57d86869992b4171e490d1a3fcebb8877110756b73f7be0f7159f534`; its `version.info` states FhirVersion 4.0.1-9346c8cc45, built 2019-11-01 |
| Files | `fhir.schema.json.zip` in that bundle, sha256 `75e5560da3cf503895a44c8ca7af17a83b4cca6c2cb5ba1883d2aec0d1cb5ac6`; `fhir.schema.json` in it, 3386892 octets, sha256 `2230406893b4cf002a4ee1e5e2bbeca22ac5d2d4931b3e9ef7b9594bbc376a01` |
| License page | https://hl7.org/fhir/R4/license.html (section 2.20.2) |

## License

The FHIR R4 license page states:

> Copyright © 2011+ HL7.

> This document is licensed under Creative Commons "No Rights Reserved" (CC0 ).

It adds that FHIR may be redistributed and that derivative products may be made, that
nobody may claim HL7 endorses a derived product, and that the trademarks are HL7's. The
notice it asks non-trademark uses to carry:

> HL7, FHIR and the FHIR [FLAME DESIGN] are the registered trademarks of Health Level Seven International and their use does not constitute endorsement by HL7.

This pack is not FHIR and is not endorsed by HL7. The page also names third-party code
systems (SNOMED CT, DICOM, LOINC, ICD, CPT) whose use FHIR's license does not cover. This
pack holds element names and value types of the FHIR schema, and the codes the schema lists
for a few elements bound to FHIR's own value sets; it holds no code of those systems.
