## Shared keys: latitude and longitude

The raw GNSS type states its latitude and longitude as degrees in WGS 84.

| Field | Shared key | Evidence |
|---|---|---|
| 1.2 latitude in degrees | `lat` | degrees and WGS 84 stated |
| 1.3 longitude in degrees | `lon` | degrees and WGS 84 stated |

Left raw:

- The altitude above mean sea level (core `hae` is above the ellipsoid), and the
  ellipsoid altitude, whose description names both the WGS 84 ellipsoid and the
  EGM96 geoid model and so does not settle the height reference.
- The ground speed and the course over ground: the course does not state true or
  magnetic north, and the speed is kept with it, as the MAVLink packs keep the
  same fields raw.
- The timestamp, which may be since the Unix epoch or since boot.
