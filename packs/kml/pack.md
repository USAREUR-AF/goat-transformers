# kml

OGC KML 2.2 (OGC 07-147r2) and KML 2.3 (OGC 12-007r2), the XML language for
geographic annotation, read for two cases: a Placemark with a Point, and a
Placemark with a KML 2.3 Track or MultiTrack. Wire `xml`, root `kml`, five
kinds. Hand-written; vectors 01 to 06 derived by
`tools/gen/aviation-xml-vectors.py`, vectors 07 to 13 by
`tools/gen/ogc-mf-kml-vectors.py` (standard library only, no engine).

This pack includes modifications that have not been approved or adopted by the
Open Geospatial Consortium: it is an implementation written for this
repository, not a part of the standard.

## Message convention

One message is one KML document.

| Kind | Holds when | The Placemark read |
|---|---|---|
| `placemark` | `Placemark/Point/coordinates` exists | the root's feature, a Placemark |
| `document-placemark` | `Document/Placemark/Point/coordinates` exists | the first Placemark of the root's Document, and the Document's name |
| `track` | `Placemark/Track/when` exists | the root's feature, a Placemark whose geometry is a Track (KML 2.3) |
| `document-track` | `Document/Placemark/Track/when` exists | the first Placemark of the root's Document, with a Track |
| `multitrack` | `Placemark/MultiTrack/Track/when` exists | the root's feature, a Placemark whose geometry is a MultiTrack (KML 2.3) |

A common `when` checks that the root declares the KML default namespace
`http://www.opengis.net/kml/2.2`; the encoder writes it. KML 2.3 keeps this
namespace (12-007r2, 5.2: a document valid under 2.2 keeps its meaning) and
tells the versions apart by the root's `version` attribute, which no line maps:
it is residue and is written back (vector 07). Field lines follow the
element order of `AbstractFeatureGroup` (name, description, TimeStamp,
styleUrl) and then the Placemark's Point (extrude, altitudeMode, coordinates),
so an encoded Placemark keeps the schema's order.

### Tracks (KML 2.3)

12-007r2, 10.15: a Track holds parallel arrays: element i of `when`, `coord`
and `angles` together are one sample. The pack reads each array as a list in
document order (`kml.track_whens`, `kml.track_coords`, `kml.track_angles`),
so index i of each list is sample i. The standard lets the three kinds of
element appear in any order; the encoder writes every `when`, then every
`coord`, then every `angles`, after `extrude` and `altitudeMode` (vector 09).
An empty `coord` marks a missing sample (10.15.2): it is an item with no value
and is written `<coord/>` (vector 08). A MultiTrack (10.16) is the list
`kml.tracks`, one item per Track, each holding its own three lists and
`altitudeMode`.

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
- **Track samples.** `coord` is longitude, latitude and altitude separated by
  single spaces (10.15.3), carried as text for the same reason as
  `coordinates`; `when` is `kml:dateTimeType` like `TimeStamp/when`, carried
  as text (`kml.track_when`). A list of samples has no shared key in any case:
  `lat`, `lon` and `time_ms` are scalars of one report.
- `Placemark/@id` is an XML identifier within the document, not a stable entity
  identifier, so it is `kml.placemark_id`, not `uid`.

## Raw keys (module `kml`)

`kml.coordinates`, `kml.altitude_mode`, `kml.extrude`, `kml.placemark_id`,
`kml.description`, `kml.when`, `kml.style_url`, `kml.document_name`,
`kml.interpolate`; the lists `kml.tracks`, `kml.track_whens` (items
`kml.track_when`), `kml.track_coords` (items `kml.coord`), `kml.track_angles`
(items `kml.angles`); all values strings, carried as written.

## Not mapped

- Every geometry other than Point, Track and MultiTrack (LineString,
  LinearRing, Polygon, MultiGeometry, Model), and a Placemark without one of
  these (`no-kind`). A Track's `Model`, `ExtendedData` (its per-sample data
  arrays) and `seaFloorAltitudeMode`, and a MultiTrack in a Document.
- **`gx:Track` and `gx:MultiTrack`.** KML 2.2 documents write tracks with the
  Google extension namespace (`xmlns:gx="http://www.google.com/kml/ext/2.2"`,
  `<gx:Track>`, `<gx:coord>`). The prefixed names match no kind (vector 13):
  the pack does not bind a literal prefix, because a document may choose any
  prefix for the namespace.
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
   prefixes", Designed): for `atom:` and `xal:` content, prefixed documents
   and the `gx:` extension elements of KML 2.2 (`gx:Track`, `gx:coord`).

## Vectors

| File | Case |
|---|---|
| `01-placemark-roundtrip` | every mapped element, root residue |
| `02-document-placemark-roundtrip` | Placemark in a Document; coordinate text kept exactly |
| `03-placemark-to-geojson` | name carries; geometry null |
| `04-kml-2-1-namespace-is-no-kind` | other namespace |
| `05-placemark-without-point-is-no-kind` | no Point |
| `06-prefixed-root-is-no-kind` | the namespace limitation |
| `07-track-roundtrip` | a Track with when, coord and angles; root `version` residue |
| `08-track-missing-coord` | an empty coord is kept as an item with no value, written `<coord/>` |
| `09-track-interleaved-is-regrouped` | when and coord interleaved on input, grouped on output |
| `10-document-track-roundtrip` | a Track Placemark in a Document |
| `11-multitrack-roundtrip` | two Tracks as items, each with its lists |
| `12-track-to-geojson` | name carries; geometry null |
| `13-gx-track-is-no-kind` | the KML 2.2 extension `gx:Track` needs namespaces |
| `packs/geojson/vectors/92-to-kml-without-coordinates-is-no-kind` | GeoJSON to KML cannot write a position |
