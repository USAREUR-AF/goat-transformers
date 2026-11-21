# Provenance: overpass-json pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| OpenStreetMap Wiki, OSM JSON, revision 2907469 of 2025-10-12 (wikitext through the MediaWiki API) | https://wiki.openstreetmap.org/wiki/OSM_JSON | `fbb2d064b23cd36325432cfaf7ceb5da65ad44cdb5dbf2c18eaf6f67bc2ac73f` |
| Overpass API, Output Formats (the JSON section and the meaning of osm_base) | https://dev.overpass-api.de/output_formats.html | `279c3ec733ab55c8d735dc646e1d80be93a162e658af5ec1c21d10c88334b28c` |

## Licence

The OpenStreetMap Wiki's content is under the Creative Commons Attribution-ShareAlike 2.0 licence
(CC BY-SA 2.0), as the wiki's footer and its copyright page state. The Overpass output formats page
states no licence; it is used for the meaning of fields the wiki page points to it for.

Under rule 17 of this project a pack adapted from a CC BY-SA document carries that licence: the pack
and the module `overpass` are labelled `CC-BY-SA-2.0` (REUSE.toml in this directory;
model/overpass.def.license). The layout (member names, types, nesting) is restated in this
project's words; no text or example of either page is copied. The vectors are responses built by
`tools/gen/geo-open-vectors.py` from values chosen there; their expected text is derived there,
without an engine.
