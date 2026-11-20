## Shared keys: latitude and longitude

The payload is MAVSDK's telemetry position type (for `ground-truth`, the
simulator's true position, which has the same first three fields). The schema gives its first
two fields as latitude and longitude in degrees, with their ranges, and names no
datum. MAVSDK fills them from the MAVLink messages that report a global
position, whose definitions state WGS 84 latitude and longitude. The binding to
core `lat` and `lon` rests on that inference, which this repository makes; the
MAVSDK schema does not state the datum itself.

| Field | Shared key | Evidence |
|---|---|---|
| 1.1 latitude in degrees | `lat` | degrees stated; WGS 84 inferred from the MAVLink source of the value |
| 1.2 longitude in degrees | `lon` | as for 1.1 |

The altitude fields stay raw: the absolute altitude is stated as above mean sea
level, and core `hae` is above the WGS 84 ellipsoid; the relative altitude is
above the take-off point.
