## Evidence for the shared keys

- `lon`, `lat` (`geometry`, a Point): every collection of the USGS Water Data API lists
  `http://www.opengis.net/def/crs/OGC/1.3/CRS84` first among its coordinate reference systems
  and states it as its storage CRS (the collection document, read 2026-11-21), and OGC API -
  Features Part 1 makes CRS84 (longitude and latitude on WGS 84, in that order) the default for
  `items`. A monitoring location's `original_horizontal_datum` names the datum it was surveyed
  in; the geometry the API returns is in CRS84.
- `time_ms` (`properties.time`, only where it is a date and a time): the API documents `time` as
  the date an observation represents, queried and written in RFC 3339; instantaneous values and
  field measurements carry a date-time with an offset (`+00:00`), which `iso8601_ms` reads. The
  raw key keeps the text as written. Daily values, latest daily values and peaks carry a date
  alone, which is not an instant: there `time` stays a raw key.

## Heights not bound

A monitoring location's `altitude` is the height of the land surface or reference point above the
vertical datum its `vertical_datum` member names (for example NAVD88 or NGVD29, both tied to mean
sea level, not to the WGS 84 ellipsoid), with its accuracy in `altitude_accuracy`. `hae` is the
height above the WGS 84 ellipsoid, so `altitude` stays the raw key `usgswaterloc.properties_altitude`.
Gage heights and depths among the values are heights above a local gage datum.

## What the geojson wire leaves out

- `value` is a string in every collection (the API sends it as text to keep its precision): a
  raw key, not converted.
- Booleans and nulls: a `null` member is absent; booleans are residue.
- A geometry other than a Point does not occur in these collections; a Feature without a geometry
  (`null`) decodes with `lat` and `lon` absent.
