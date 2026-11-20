## What a message is

One observation as a GeoJSON Feature: the O&M Simple Features properties sit in
`properties`, and `properties.featureType` names the observation type and selects the kind
(generic, measure, category, count, truth, measure time series).

## Evidence for the shared keys

- `lon`, `lat`, `hae` (`geometry` of type Point): the schema takes the Feature model of
  geojson.org and RFC 7946. RFC 7946 section 4 gives coordinates as WGS 84 longitude and
  latitude in decimal degrees, and a third number as height in metres relative to the WGS 84
  ellipsoid.
- `time_ms` (`properties.phenomenonTime`): the schema gives it as a date-time; the profile
  writes an interval with separate start and end members, so this member is always one
  instant: the time the observed value applies to. `resultTime` (when the result became
  available) is kept as its raw key.
- `uid` is not bound: the schema does not declare the Feature's `id` member (RFC 7946 makes
  it optional), so the generator has no leaf to map, and the geojson wire does not carry an
  unmapped top-level member. An observation's `id` is dropped on decode.

## Licence basis

`opengeospatial/omsf-profile` states no license: no LICENSE file, no notice in the schema or
the README (checked at the pinned commit). Under the operator's licensing model a missing
licence does not exclude a format; the pack is labelled `LicenseRef-unstated` (see
`LICENSES/LicenseRef-unstated.txt` and `PROVENANCE.md`), which the `open` profile excludes
until the licence is resolved.
