## Evidence for the shared keys

- `lat`, `lon` (`navigation.position.value.latitude`, `.longitude`): `groups/navigation.json`
  describes the vessel position as two- or three-dimensional in the WGS 84 datum, and the
  `position` definition in `definitions.json` gives latitude and longitude with the unit
  `deg`. That is `lat`/`lon` (WGS 84, degrees).
- `time_ms` (`navigation.position.timestamp`): every value of the model carries a
  timestamp, an RFC 3339 date-time in UTC; this one is the time of the position.
  `iso8601_ms` reads it to epoch milliseconds.
- `speed_ms` (`navigation.speedOverGround.value`): speed over ground, unit `m/s`.
- `uid` (`uuid`): the Signal K URN the server assigns to the vessel.
- `callsign` (`name`): the vessel's common name, a human-readable name.

Not bound, and why:

- `navigation.position.value.altitude` is in metres with no stated height reference;
  `hae` is above the WGS 84 ellipsoid.
- `navigation.courseOverGroundTrue` is in radians; `course` is in degrees, and the
  factor 180/pi is not exact (engine-spec 0.15 exact factors).
- `mmsi` is an identifier too, but optional; `uuid` is the one the server assigns.

## What the model cannot hold

Signal K keeps a value per source under `values`, an object whose member names are
source references; such objects are not mapped. The full model (`signalk-full`) keys every
vessel by its URN, so its vessels are not mapped there; this pack is the object of one
vessel.
