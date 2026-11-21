## What is not carried

One moving feature as the API returns it. No shared key is bound: the trajectory positions
(`temporalGeometry.coordinates`) are arrays of arrays, which the json wire does not address,
and a track of many points has no single position for `lat` and `lon`; `id` is a string or an
integer, which no transform reads. The instants (`temporalGeometry.datetimes`) are mapped as
a list. The static `geometry` (outside this schema set), the bounding box (a tuple) and the
open `properties` are not mapped.

The schemas of the API response refer to the MF-JSON Prism schema by its schemas.opengis.net
address; the run reads that file (pinned by SHA-256 in the run script). It states no licence,
so the pack is labelled `LicenseRef-unstated` (REUSE.toml); the response schemas themselves
are under the OGC Software License.
