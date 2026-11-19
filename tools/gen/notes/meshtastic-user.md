
## Shared keys: the evidence

| Key | Field | What the schema states |
|---|---|---|
| `uid` | `id` (1, string) | an identifier of the user (the node) that is globally unique: by default `!` and the node number in hexadecimal |
| `callsign` | `long_name` (2, string) | the full name of the user, at most 24 bytes |

`short_name` (a name of about two characters for small displays) is left raw. `User` has no
position: converted to geojson it is a feature with no geometry.
