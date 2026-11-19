# Provenance of the wzdx-device pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/jsonschema2pack-run.sh`, block
"WZDx 4.2") reads four JSON Schema files of `schemas/4.2/` and nothing else; their SHA-256
are listed in `pack.md`. The files are not kept in this repository. Read on 2026-11-19.

## Source

| | |
|---|---|
| Document | Work Zone Data Exchange (WZDx) Specification 4.2, Device Feed schema |
| Publisher | U.S. Department of Transportation, ITS Joint Program Office (usdot-jpo-ode) |
| Repository | https://github.com/usdot-jpo-ode/wzdx, tag `v4.2`, commit `42b98fcdd837e897ae3e208780c45ce61f7fc12a` |
| Files read | `schemas/4.2/DeviceFeed.json` (the message is `#/definitions/FieldDeviceFeature`), `Direction.json`, `BoundingBox.json`, `FeedInfo.json` (JSON Schema draft-07) |
| Evidence | `spec-content/objects/FieldDeviceFeature.md`, SHA-256 `ec283473133443330d3c211556969c8de439ee49cad4a9b40e029c3784111f8c` (geometry is a GeoJSON Point per RFC 7946) |
| License file | `LICENSE`, SHA-256 `a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499` |

License: the repository's `LICENSE` is "Creative Commons Legal Code / CC0 1.0 Universal",
the public-domain dedication; the GitHub repository metadata names CC0-1.0.

The schemas refer to `https://geojson.org/schema/Point.json`; it is not read: the geojson
wire is the Feature structure (`--opaque`).
