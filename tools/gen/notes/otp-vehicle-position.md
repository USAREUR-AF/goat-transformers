## The message

One `VehiclePosition` object as an OpenTripPlanner GTFS GraphQL response holds it (for
example in `patterns { vehiclePositions { ... } }`), with this selection: `vehicleId`,
`label`, `lat`, `lon`, `speed`, `heading`, `lastUpdate`, `lastUpdated`, `stopRelationship
{ status stop { gtfsId name lat lon code platformCode } }`, `trip { gtfsId tripShortName
routeShortName directionId }`. A GraphQL response holds only the fields a query asks for;
a field the query does not select is absent.

## Evidence for the shared keys

- `lat`, `lon`: the schema gives the vehicle's latitude and longitude as floats.
  OpenTripPlanner takes vehicle positions from GTFS Realtime feeds, whose positions are
  WGS 84 degrees; OTP keeps them in that frame.
- `time_ms` (`lastUpdate`): the schema describes it as the time the position of the vehicle
  was recorded, an ISO 8601 date-time with an offset; `iso8601_ms` reads it and converts to
  UTC. `lastUpdated` (deprecated, the same instant in UNIX seconds) is a raw key.
- `speed_ms` (`speed`): the schema gives the speed of the vehicle in metres per second.
- `uid` (`vehicleId`): the feed-scoped identifier that the schema says uniquely identifies
  the vehicle.
- `callsign` (`label`): a human-readable label of the vehicle, such as a public number or a
  licence plate.

## Not bound

- `heading`: the schema allows a compass bearing or the direction towards the next stop, so
  it is not `course`; raw key.
