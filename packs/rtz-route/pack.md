# Pack: rtz-route

An RTZ route exchange file, schema revision 1.2 (CIRM; the format of IEC PAS 61174-1:2021, used by
ECDIS for route plans). Wire `xml`, root `route`; the default namespace `http://www.cirm.org/RTZ/1/2` and
`version="1.2"` select the one kind, `route`. One message is one file. Written by
`tools/gen/maritime-pack.py`. Labelled `LicenseRef-unstated` (PROVENANCE.md).

## What is mapped

- **Route information**: every attribute of `routeInfo` (name, author, status, validity period,
  vessel name, MMSI, IMO number, voyage, displacement, cargo, metacentric height, optimization method,
  roll, wave and wind limits, speeds, change history).
- **The default waypoint**: its turn radius and its leg attributes.
- **The waypoints** (a list): identifier, revision, name, turn radius, latitude and longitude, and
  the attributes of the leg from the previous waypoint (cross-track limits, safety contour and depth,
  geometry, speed limits, draughts, under-keel clearances, masthead height, notes).
- **The first schedule**: its identifier and name, and its manual and calculated schedule elements
  (two lists: waypoint, ETD and ETA with their windows, stay, speeds, weather, losses, engine settings,
  fuel).

Dates and times and XML durations are kept as written (strings). Units are those the schema's
annotations give (nautical miles for cross-track limits and radii, metres for depths and draughts,
knots for speeds, degrees for directions); where the schema states none the key says so.

## Shared keys

None. Waypoint positions are in a list, and core `lat` and `lon` hold one position; the route
information's MMSI and IMO number are the planned vessel's, not a sender's.

## Not mapped

- **Schedules after the first**: a group reads the elements under the first matching `schedule`.
- **Extensions** (`extensions/extension` with vendor content, at every level): their content is any
  XML; extensions inside list items are not kept.
- RTZ 1.0 and 1.1 (other namespaces) are `no-kind`; the schema of IEC 61174 (RTZ 1.0) differs.

## Vectors

`tools/gen/maritime-vectors.py`, without an engine: a route with a default waypoint, three waypoints
and a manual schedule; a minimal route; a calculated schedule element; an RTZ 1.1 document
(`no-kind`).
