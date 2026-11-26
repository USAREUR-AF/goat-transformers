## Evidence for the shared keys

The keys match the meanings the `remote-id` pack (ASTM F3411 broadcast messages) gives them.

- `uid` (`id`): the identifier of the flight, which the interface makes unique per flight.
- `lat`, `lon` (`current_state.position.lat`, `.lng`): degrees north and east with reference to
  the WGS 84 ellipsoid, as the `Latitude` and `Longitude` schemas state.
- `hae` (`current_state.position.alt`): geodetic altitude, the distance above the WGS 84
  ellipsoid in metres (the schema rules out altitude above launch, above ground and EGM96).
- `time_ms` (`current_state.timestamp.value`): the time at which this state was valid, the `value` of a `Time` object, an RFC 3339 date-time with the time zone Z; `iso8601_ms` reads it.
- `course` (`current_state.track`): direction of flight as a true-north ground track angle in
  degrees, clockwise.
- `speed_ms` (`current_state.speed`): ground speed in metres per second.
- `track.vel_up_ms` (`current_state.vertical_speed`): speed upward in metres per second.
- `track.simulated` (`simulated`): the flight is simulated (a boolean; `bool` gives 1 or 0).

## Not bound

`pressure_altitude` (barometric) and `height` (above takeoff or ground) are not `hae`; the
accuracy codes are enumerations, not metres. `recent_positions` and `operating_area` are lists
and stay raw.

## Unknown values

The interface gives a value that means invalid, no value or unknown for several members:
latitude and longitude 0, altitude -1000 m, track 361 degrees, speed 255 m/s, vertical speed
63 m/s. Altitude -1000, track 361 and speed 255 are `absent` on the `hae`, `course` and
`speed_ms` lines: such a flight carries no height, course or speed into another format, the raw
keys keep the values, and an absent key writes the unknown value (vector
`unknown-alt-track-speed-roundtrip`). Not stated: latitude and longitude 0, which mean unknown
only together (a condition over two members the language does not have), and the vertical
speed, which is `track.vel_up_ms`, not one of the keys of this change.

## Licence and source

The source of record is InterUSS's Apache-2.0 api.py module for this interface in
interuss/uas_standards; the OpenAPI file, which states no licence, is read for convenience and
agrees with api.py (tools/gen/utm-crosscheck.py). The ASTM standards (paid documents) were not
used. PROVENANCE.md has the details.
