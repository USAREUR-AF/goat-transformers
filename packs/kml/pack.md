# kml

OGC KML 2.2 (OGC 07-147r2), the XML language for geographic annotation, read
for one case: a Placemark with a Point. Wire `xml`, root `kml`, two kinds.
Hand-written; vectors derived by `tools/gen/aviation-xml-vectors.py`
(standard library only, no engine).

## Message convention

One message is one KML document.

| Kind | Holds when | The Placemark read |
|---|---|---|
| `placemark` | `Placemark/Point/coordinates` exists | the root's feature, a Placemark |
| `document-placemark` | `Document/Placemark/Point/coordinates` exists | the first Placemark of the root's Document, and the Document's name |

A common `when` checks that the root declares the KML 2.2 default namespace
`http://www.opengis.net/kml/2.2`; the encoder writes it. Field lines follow the
element order of `AbstractFeatureGroup` (name, description, TimeStamp,
styleUrl) and then the Placemark's Point (extrude, altitudeMode, coordinates),
so an encoded Placemark keeps the schema's order.

## Shared-model keys and the evidence

| Wire | Key | Evidence (OGC 07-147r2, in our words) |
|---|---|---|
| `Placemark/name` | `callsign` | 9.1.3.1: `name` is a text label for the feature, the human-readable name |

No other shared key is bound:

- **Position.** 10.3 and 16.9: a Point holds one `coordinates` text, a tuple of
  longitude, latitude and an optional altitude, separated by commas, in decimal
  degrees. The pack language has no transform that reads one number out of a
  delimited text, and no derive function that joins numbers into text, so the
  tuple is carried whole as `kml.coordinates` (a string) and `lat` and `lon`
  stay absent. A conversion from KML to GeoJSON therefore has `geometry: null`,
  and a conversion to KML from a format without `kml.coordinates` fails with
  `no-kind` rather than write a Placemark without its Point.
- **Altitude is not `hae`.** 6.2: the third coordinate is measured from the
  EGM96 geoid (orthometric height), not the WGS 84 ellipsoid; and 9.17: its
  meaning depends on `altitudeMode`, whose default `clampToGround` ignores it.
  Even with a split transform it would be a raw key.
- **Time.** `TimeStamp/when` is `kml:dateTimeType`, a union of date-time, date,
  year-month and year (16.10). Only the first form is an instant; binding it to
  `time_ms` would make a document holding `2008-05` fail to decode. It is
  carried as text, `kml.when`.
- `Placemark/@id` is an XML identifier within the document, not a stable entity
  identifier, so it is `kml.placemark_id`, not `uid`.

## Raw keys (module `kml`)

`kml.coordinates`, `kml.altitude_mode`, `kml.extrude`, `kml.placemark_id`,
`kml.description`, `kml.when`, `kml.style_url`, `kml.document_name`; all
strings, carried as written.

## Not mapped

- Every geometry other than Point (LineString, LinearRing, Polygon,
  MultiGeometry, Model), and a Placemark without a Point (`no-kind`).
- Features other than Placemark (Folder, NetworkLink, overlays) and a Placemark
  inside a Folder; second and later Placemarks of a Document (ruling 7 of
  0.1.1).
- `visibility`, `open`, `atom:author`, `atom:link`, `address`,
  `xal:AddressDetails`, `phoneNumber`, `Snippet`, views (`Camera`, `LookAt`),
  `TimeSpan`, inline styles, `Region`, `ExtendedData`, and extension elements
  of other namespaces. `atom:` and `xal:` elements need prefixes (below).
- Attributes of the root that no line maps are residue and are written back
  (for example `xmlns:gx`); child elements no line maps are dropped.
- **Namespaces.** Element names are compared as written. A KML document written
  with a prefix (`<k:kml xmlns:k="…kml/2.2">`) matches no kind (`no-kind`,
  vector 06), and a KML 2.1 or 2.0 namespace is refused (vector 04).
- Text needing escapes (`&`, `<`) in names and descriptions: the canonical
  escaping of XML text is not stated in `spec/engine-spec.md`, so no vector
  pins it.

## Candidate pack-language additions

1. A split transform or derive function: read the n-th number of a text
   delimited by a given character (`lon,lat,alt`), and its inverse, joining
   numbers in canonical float text. With it the pack would bind `lat` and
   `lon` from `coordinates`.
2. Namespace-aware element names (docs/roadmap.md, "XML namespaces and
   prefixes", Designed): for `atom:` and `xal:` content and prefixed documents.

## Vectors

| File | Case |
|---|---|
| `01-placemark-roundtrip` | every mapped element, root residue |
| `02-document-placemark-roundtrip` | Placemark in a Document; coordinate text kept exactly |
| `03-placemark-to-geojson` | name carries; geometry null |
| `04-kml-2-1-namespace-is-no-kind` | other namespace |
| `05-placemark-without-point-is-no-kind` | no Point |
| `06-prefixed-root-is-no-kind` | the namespace limitation |
| `packs/geojson/vectors/92-to-kml-without-coordinates-is-no-kind` | GeoJSON to KML cannot write a position |
