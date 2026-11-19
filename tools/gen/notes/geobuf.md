## What the message is

The pack's message is one geobuf `Data`: a compact protobuf encoding of a GeoJSON feature
collection, feature or geometry. Coordinates are signed integers, each the coordinate times
10 to the power of `precision` and, in a line or ring, the difference from the coordinate before;
properties are indices into the key list and values of the message.

## Everything raw

Recovering a longitude and latitude needs the running sum along `coords` and the division by the
precision, neither of which the pack language states, and a feature's position is a list of
integers, not one point. So no field is a shared key and the pack converts to no other format; the
lists carry the integers as they are on the wire. The geometry and feature collections nest
messages of their own type: the walk stops where a message type would stand inside itself.
