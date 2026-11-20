
## Shared keys: the evidence

| Keys | Field | What the schema states |
|---|---|---|
| `lat`, `lon` | `vehicle_localization.geodetic_position.latitude`, `.longitude` (double) | the host vehicle's most accurate geodetic position known on board: latitude and longitude in decimal degrees on WGS 84, within -90 to 90 and -180 to 180 |

`geodetic_position.altitude` is above sea level by the EGM96 geoid, not above the WGS 84
ellipsoid, so it is not `hae`: a raw key. The host vehicle's position in the world frame
(`vehicle_localization.position`) and every velocity are in OSI's Cartesian frames: raw keys.
