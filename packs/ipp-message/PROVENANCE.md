# Provenance: ipp-message pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| IETF RFC 8010, Internet Printing Protocol/1.1: Encoding and Transport, January 2017, section 3 | https://www.rfc-editor.org/rfc/rfc8010.txt | `565ee2ff5da8185ebf867936e0c28004adcb28789477c1c54ba3db55692fba5e` |
| IETF RFC 8011, Internet Printing Protocol/1.1: Model and Semantics, January 2017, section 5.1.16 (resolution units) | https://www.rfc-editor.org/rfc/rfc8011.txt | `409d1b407c1810a6da9e406fa2f3dd9ddb0d733dd0760e83dadb3543f55f8291` |

## Licence

Each source is an IETF document: "Copyright (c) 2017 IETF Trust and the persons identified as the document
authors. All rights reserved." It is subject to BCP 78 and the IETF Trust's Legal Provisions Relating to
IETF Documents (https://trustee.ietf.org/license-info). The pack keeps the default Apache-2.0 label.

This pack restates the layouts (field order, sizes, tag values) in its own words; no text, figure, table or
ABNF of the sources is copied. The vectors are messages built by `tools/gen/printing-vectors.py` from values
chosen there; their expected bytes are derived there, without an engine.

## Attribution

Layouts from IETF RFC 8010 and RFC 8011 (M. Sweet, I. McDonald, 2017), restated.
