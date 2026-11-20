## The form

The aviationweather.gov Data API answers each product request with a JSON array of
reports (format `json`) or a GeoJSON FeatureCollection (format `geojson`). One message of
the JSON packs is one element of that array, a JSON object; one message of the GeoJSON
packs (`*-geojson`) is one Feature of the collection, with a Point geometry. Polygon
products (SIGMETs, AIRMETs, G-AIRMETs, CWAs, the TCF) are read in their JSON form, where
their vertices are a list, and the TCF, which has only a GeoJSON form, as a json object.
The raw text, XML and IWXXM forms are not packs.

## Evidence for the shared keys

The JSON forms describe `lat` and `lon` as the site's latitude and longitude (in degrees,
for METAR and TAF) and name no datum. The same API serves the same reports as GeoJSON,
whose coordinates RFC 7946 defines as WGS 84 longitude and latitude in decimal degrees,
and the two forms carry the same positions; the packs take the JSON degrees as WGS 84 on
that ground. A consumer that needs the datum stated in the source reads the GeoJSON pack.

`elev` is the site's elevation in metres with no stated reference (in practice above mean
sea level): a raw key, not `hae`. The observation times given as text (`receiptTime`,
`reportTime`, a TAF's `issueTime`) are written with a space between date and time, which
`iso8601_ms` does not read: raw keys.

For the GeoJSON packs, `lon` and `lat` are the Point coordinates of the Feature: the
responses are `application/geo+json`, and RFC 7946 section 4 gives GeoJSON coordinates as
WGS 84 longitude and latitude in decimal degrees.
