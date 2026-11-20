## Shared keys: velocity

The payload is the vehicle's velocity in the local north-east-down frame, each
component stated in metres per second.

| Field | Shared key | Evidence |
|---|---|---|
| 1.1 velocity toward north, m/s | `track.vel_north_ms` | north component and m/s stated |
| 1.2 velocity toward east, m/s | `track.vel_east_ms` | east component and m/s stated |

The down component stays raw: `track.vel_up_ms` is positive upward, and the
protobuf wire has no transform that changes the sign. The message holds no
position, so it converts to no other format on its own.
