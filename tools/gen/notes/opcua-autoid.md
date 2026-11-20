## Shared key: time_ms

OPC UA's DateTime is a signed 64-bit count of 100 ns intervals since 1601-01-01 00:00 UTC
(OPC 10000-6, 5.2.2.5). The value 0 stands for any time at or before that epoch and the largest
Int64 for any time from the end of the year 9999; a decoder reads both as the extremes of its
platform, which are not valid times. Core `time_ms` is milliseconds since
1970-01-01 UTC. The two epochs are 11,644,473,600,000 ms apart, so the transform
`siscale:1/10000:-11644473600000` states the conversion exactly, to the millisecond (a tick count
that is not a whole millisecond rounds), and `absent 0,9223372036854775807` reads both extremes as no time.

The binding is made for the field `Timestamp` at the top of a kind, which the AutoID NodeSet
describes as the time the result, sighting or coordinate was made:

| Kind | Field | Evidence (the NodeSet's description, in this repository's words) |
|---|---|---|
| scan results (`ocr_scan_result`, `optical_scan_result`, `optical_verifier_scan_result`, `rfid_scan_result`, `rtls_location_result`) | `Timestamp`, inherited from ScanResult | the time the scan result was created |
| `access_result`, `rfid_access_result` | `Timestamp` (optional) | the time the identifier was accessed |
| `rfid_sighting` | `Timestamp` | the time of the sighting, as a UtcTime |
| `local_coordinate`, `wgs84_coordinate` | `Timestamp` | the time the coordinate applies to (named Timestamp, typed UtcTime) |

Other DateTime fields (a decoding time, a receive time, timestamps inside nested structures)
stay raw 100 ns tick counts.

## Positions stay raw

`WGS84Coordinate` gives the latitude and longitude as doubles beside separate hemisphere strings,
so the sign of the double is not stated to carry the hemisphere; `DhcpGeoConfCoordinate` splits
each into an integer and a fraction with a resolution field; `LocalCoordinate` is in a local
frame. None is bound to core `lat` or `lon`. Binding the WGS 84 pair needs the hemisphere strings
read as text (the pack has their bytes, not their text) and a derive that signs the value.
