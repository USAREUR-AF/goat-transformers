# Provenance: mqtt5 pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| OASIS, MQTT Version 5.0, OASIS Standard, 7 March 2019 | https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html | `16f24e2b021d86b3bbb2b39c8b5ee134b3d39f69320ba61d3c07a38af74e696c` |

## Licence

The specification states: "Copyright © OASIS Open 2019. All Rights Reserved."

The OASIS notice permits derivative works that comment on, explain or assist in implementing the document, provided the copyright notice and the notice section are included. The pack is labelled `LicenseRef-OASIS-Notice` (packs/mqtt5/REUSE.toml; the notice is in LICENSES/LicenseRef-OASIS-Notice.txt) and its module likewise (model/mqtt.def.license).

This pack restates the layouts (field order, sizes, values) in its own words; no text, table, figure
or example of the sources is copied. The vectors are messages built by
`tools/gen/messaging-vectors.py` from values chosen there; their expected bytes are derived there,
without an engine.
