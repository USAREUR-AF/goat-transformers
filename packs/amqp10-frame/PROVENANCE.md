# Provenance: amqp10-frame pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| OASIS, AMQP Version 1.0, Part 2: Transport, OASIS Standard, 29 October 2012 | https://docs.oasis-open.org/amqp/core/v1.0/os/amqp-core-transport-v1.0-os.xml | `9cd32460d1730975ff0a9dbb66573ff456cbd53ffd8d4f6899c497f02867f637` |
| OASIS, AMQP Version 1.0, Part 1: Types | https://docs.oasis-open.org/amqp/core/v1.0/os/amqp-core-types-v1.0-os.xml | `2ccf30b2c55924aaa5291cc34430a91b75c85d11d34bc008c36fc7ca7574d28c` |
| OASIS, AMQP Version 1.0, the complete specification (for the notice) | https://docs.oasis-open.org/amqp/core/v1.0/os/amqp-core-complete-v1.0-os.pdf | `4416561abae7664efa45a70a81cd59488c71cb4b03321e9e73dffdcba4a7cba4` |

## Licence

The specification carries the OASIS copyright notice of 2012.

The OASIS notice permits derivative works that comment on, explain or assist in implementing the document, provided the copyright notice and the notice section are included. The pack is labelled `LicenseRef-OASIS-Notice` (packs/amqp10-frame/REUSE.toml; the notice is in LICENSES/LicenseRef-OASIS-Notice.txt) and its module likewise (model/amqp.def.license).

This pack restates the layouts (field order, sizes, values) in its own words; no text, table, figure
or example of the sources is copied. The vectors are messages built by
`tools/gen/messaging-vectors.py` from values chosen there; their expected bytes are derived there,
without an engine.
