# Provenance: geo-track-v1

| Source | Where | Version | SHA-256 | License |
|---|---|---|---|---|
| GeoTrackV1 schema | `ops/serve/goat-map/schemas/geo/track.v1.schema.json` in `https://github.com/USAREUR-AF/goatstuff` | commit `5f56c42c407a72d6392d5c86a06257c7c58fe7fd` | `ac959ea0e6d50eb9e6ae7240364723b68cb5a64603f07b80a28870ed88d26fa4` | Apache-2.0 |

The pack states member names, types and required members of that schema. The
vectors use invented values.

The pack, its module and the `cot-xml` additions were written in goatstuff (`ops/xf/upstream-proposed/`) and moved here unchanged, except that the three sender-text keys are core keys (`time_text`, `stale_text`, `display_name`) so `cot-xml` needs no further module.
