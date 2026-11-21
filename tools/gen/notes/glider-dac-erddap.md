## Evidence for the shared keys

- `lat`, `lon` (`latitude`, `longitude`): the NGDAC NetCDF template gives the glider's `lat`
  and `lon` in degrees north and east with reference WGS84 and coordinate reference frame
  EPSG 4326; the DAC's ERDDAP server serves them as `latitude` and `longitude`.
- `time_ms` (`time`): the time of the measurement, written by ERDDAP as an ISO 8601 date-time
  in UTC.

## Not bound

`depth` is positive down from the sea surface, not a height above the ellipsoid.
`precise_lat`, `precise_lon` and `lat_uv`, `lon_uv` are other positions (the GPS fixes, and
the position of the depth-averaged current), raw keys. `u` and `v` are depth-averaged water
velocity, not the glider's. The quality-control and QARTOD flag variables are residue.
