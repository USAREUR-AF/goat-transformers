## What the message is

The pack's message is one `valhalla.Api`, the protobuf form of a request to the Valhalla routing
engine and its response (Valhalla returns it when a request asks for protobuf output). It holds
the request options (1), and, by the action, a trip (2), directions (3), status (4), a matrix (5),
an isochrone (6), an expansion (7), and statistics (20).

## Everything raw

Every field the walk reaches is a raw key of module `valhalla`, and the pack converts to no other
format.

- `LatLng.lat` and `lng`: double degrees, but the schema states neither the unit nor the datum.
  Positions also stand inside repeated locations, legs and maneuvers, which are lists.
- Encoded shapes are strings in Valhalla's polyline encoding, carried as text and not decoded.
- The walk stops at path depth 6 (the default); `pack.md` counts the fields below it.
