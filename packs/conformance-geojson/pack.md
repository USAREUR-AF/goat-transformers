# Pack: conformance-geojson

A synthetic probe format for message kinds on the `geojson` wire
(`spec/engine-spec.md`, Version 0.5). It belongs to no standard. Its vectors pin
that mapped members and `when` members are written in line order, at the top
level and inside `properties`, and that a `when` value is written as a number, a
boolean or a string.
