# davis-wll-udp

One UDP packet of the WeatherLink Live's real-time broadcast (port 22222, every 2.5 s while enabled): `did`, `ts` and `conditions`, the rapid ISS records (wind and rain); a console with more than three ISS transmitters sends several packets. Davis WeatherLink Live is a hub for Davis weather-station transmitters. Licence
`LicenseRef-unstated` (PROVENANCE.md).

## Mapping

The records of `conditions` are a group; the members of all four record types (1 ISS, 2
leaf/soil, 3 barometer, 4 inside temperature and humidity) are lines of the one item, and a record
holds only its type's members, so the others are absent. `null` members are absent and not
written back. Units are those the document states: degrees Fahrenheit, mph, inches of mercury,
counts of the rain collector (`rain_size` gives a count's size), W/m2.

| Member | Key | Evidence |
|---|---|---|
| `did` | `uid` | the device ID of the WeatherLink Live |
| `ts` | `time_ms` | a Unix timestamp in seconds: the document gives it as the time at which the HTTP request was made; for the UDP packet it gives the same member with no further words, read the same way; `iscale:1000` |

## Not mapped

- No position: the API carries no latitude or longitude.
- Temperatures, speeds and pressures stay raw in their US units: no shared key holds them.
- Members of a record that are not in the document are dropped (items carry no residue).
