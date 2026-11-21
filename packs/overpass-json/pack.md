# Pack: overpass-json

A response of the Overpass API in its JSON output (`[out:json]`), the format the OpenStreetMap API
JSON format is based on: the header, the time of the data, and the elements (nodes, ways and
relations) with their metadata and, with `out geom`, their geometry. Wire `json`. No kind.

**Licence.** The layout is restated from the OpenStreetMap Wiki page OSM JSON (CC BY-SA 2.0) and
the Overpass API output formats page. Under rule 17 of this project a pack adapted from a CC BY-SA
document carries that licence: the pack and its module are labelled `CC-BY-SA-2.0`
(packs/overpass-json/REUSE.toml, model/overpass.def.license). The OpenStreetMap data a response
carries is under the ODbL; that is the data's licence, not the pack's.

## What is mapped

The header: `version` (a number in Overpass output), `generator`, the `osm3s` object
(`timestamp_osm_base`, `timestamp_areas_base`, `copyright`), the OSM API fields `copyright`,
`attribution` and `license`, and `remark` (an error or warning of the query).

Each element is an item of `overpass.elements`: type, id, latitude and longitude (nodes), the
metadata (timestamp, version, changeset, user, uid; `visible` in OSM API history), the bounding box
(`out geom`), the node ids of a way, the geometry of a way (a list of points), and the members of a
relation (type, ref, role, and with `out geom` a member node's position or a member way's geometry).

## Shared keys

| Field | Key | Evidence |
|---|---|---|
| `osm3s.timestamp_osm_base` | `time_ms` | The Overpass output formats page: the date of the data; every edit uploaded before it is included; written as YYYY-MM-DDThh:mm:ssZ. The response describes the map as of that moment, so it is the time the report holds for. Read with `iso8601_ms` (exact: whole seconds in UTC); the text is kept in `overpass.timestamp_osm_base` too. |

On encode the `time_ms` line comes first, so a round trip writes the time in the form
`iso8601_ms` writes (`…:02.000Z`), not the input's `…:02Z` (ruling 16 of engine-spec 0.5).

Positions are not `lat` and `lon`: every node is an item of the element list, and a shared key is
bound only outside lists.

## Not mapped

- **Tags.** An element's `tags` object has the tag keys as member names: member names that are data,
  which the json wire cannot address. A list item has no residue, so the tags are not written back.
  Needed: a group over an object's members (the key as a field), the same need as for YANG, WoT and
  GeoParquet.
- **The OSM API flavour's `version`** is a string where Overpass writes a number; such a response is
  `transform-decode`. The pack is for Overpass output.
- `out center` (a `center` object) is not in the two sources and is not mapped.
- The Overpass page says an element's version and changeset are strings; the wiki's example and
  the OSM API write numbers, and the pack reads numbers.

## Vectors

`tools/gen/geo-open-vectors.py`, without an engine: a response to geojson (the time of the data
carries) and an OSM API response whose string `version` is `transform-decode`. Round trips are to be
written by an independent vector-deriver from the specification and this pack; on encode
`timestamp_osm_base` is written in the canonical form of `iso8601_ms` (`…:02.000Z`).
