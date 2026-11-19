# Provenance of the wzdx-work-zone-feed-4.0 pack

`tools/gen/jsonschema2pack.py` (run script `tools/gen/wzdx-run.sh`) reads the JSON Schema
files of `schemas/4.0/`; their SHA-256 are listed in `pack.md`. The files are not kept in
this repository. Read on 2026-11-19.

## Source
| | |
|---|---|
| Document | Work Zone Data Exchange (WZDx) Specification 4.0 |
| Publisher | U.S. Department of Transportation, ITS Joint Program Office (usdot-jpo-ode) |
| Repository | https://github.com/usdot-jpo-ode/wzdx, tag `v4.2`, commit `42b98fcdd837e897ae3e208780c45ce61f7fc12a` (the tag holds the schemas of every 4.x version) |
| Files read | `BoundingBox.json`, `FeedInfo.json`, `RoadEventFeature.json`, `RoadRestrictionFeed.json`, `SwzDeviceFeed.json`, `WZDxFeed.json` (JSON Schema draft-07); the message is `WZDxFeed.json` |
| License file | `LICENSE`, SHA-256 `a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499` |

License: the repository's `LICENSE` is "Creative Commons Legal Code / CC0 1.0 Universal",
the public-domain dedication; the GitHub repository metadata names CC0-1.0.

The schemas refer to `https://geojson.org/schema/` geometries; they are not read
(`--opaque`).
