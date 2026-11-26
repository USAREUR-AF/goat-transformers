## Shared keys: the evidence

| Keys | Field | What the schema states |
|---|---|---|
| `lat`, `lon` | `latitude` (5), `longitude` (6), double | degrees; `datum_id` (9) is the datum, an enum whose only value is `WGS84` (61), with the remark that only WGS-84 is used |
| `track.sigma_north_m`, `track.sigma_east_m`, `track.sigma_up_m` | `latitude_std_dev` (10), `longitude_std_dev` (11), `height_std_dev` (12), float | standard deviations in metres: of latitude (north), of longitude (east), of height (up) |

Encode writes `datum_id` = 61 on every message (a `const` line), so a position from another
format leaves with the datum it is in.

## Left raw

- `height_msl` (7): height above mean sea level, not above the ellipsoid. The ellipsoid height is
  `height_msl + undulation` (8), and no derive function adds two keys; `hae` is not set.
- `base_station_id` (13) is `bytes`: not carried.
- The solution status and type, the satellite counts and masks, the ages: raw keys.

## Validity flag not applied

`sol_status` and `sol_type`, which state whether the solution is computed and what it is. The pack keeps the flag as a raw key and binds the position whatever it says: a message whose
flag says there is no fix converts with the coordinates it carries (often 0, 0), as if they were a
position. The pack language has no gate for a JSON or protobuf member yet (asked of gt-lang); until
it has, a consumer must read the flag. Bit-level packs of the same messages (PX4) read the shared
keys only when the flag says so.
