## Evidence for the shared keys

- `lon`, `lat` (`geometry` of type Point): the REM requires a valid GeoJSON feature
  collection (IETF RFC 7946) and states that the only coordinate reference system accepted is
  WGS 84; the start, end, waypoints and segments are required to be Point features.
  Longitude and latitude in decimal degrees.

## What is not carried

The start, end or an intermediate waypoint of a route (the property `featureType` says which).

- **The third coordinate.** The REM text gives heights above mean sea level, not above the
  ellipsoid, so it is not `hae` and is not bound.
- **`id`** is a number or a string; no transform reads either.
- **`properties.timestamp`.** The text allows an estimated time of arrival or departure as a
  `timestamp` property; the schema does not list it, and an estimate is not the time a
  report holds for, so it is not bound (it is residue, carried back as it was).
