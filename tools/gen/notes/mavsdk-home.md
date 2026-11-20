## Shared keys: latitude and longitude

The payload is MAVSDK's home position type. The schema gives its second and
third fields as latitude and longitude in degrees, with their ranges, and names
no datum. MAVSDK fills them from the MAVLink home position message, whose
definition states WGS 84 latitude and longitude. The binding to core `lat` and
`lon` rests on that inference, which this repository makes; the MAVSDK schema
does not state the datum itself.

| Field | Shared key | Evidence |
|---|---|---|
| 1.2 latitude in degrees | `lat` | degrees stated; WGS 84 inferred from the MAVLink source of the value |
| 1.3 longitude in degrees | `lon` | as for 1.2 |

Left raw: the altitude above mean sea level (core `hae` is above the WGS 84
ellipsoid), the altitude above take-off, the local north-east-down offsets of the
home point and of the approach vector, the surface quaternion, and the timestamp,
which may be since the Unix epoch or since boot.
