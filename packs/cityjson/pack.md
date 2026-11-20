# cityjson

CityJSON 2.0 is a JSON encoding of a subset of the OGC CityGML 3.0 data model
for 3D city and landscape models, published by its editors under CC0 1.0 and
adopted as an OGC Community Standard. This pack reads the parts of a CityJSON
object and of a CityJSONFeature that the `json` wire can address. It reads no
geometry.

## Message convention

One message is one JSON object, of one of two kinds:

| Kind | `when` | A message is |
|---|---|---|
| `city-model` | `type` is `CityJSON` and `version` is the string `2.0` | one CityJSON object (section 1), a `.city.json` file |
| `feature` | `type` is `CityJSONFeature` | one CityJSONFeature (section 7.2), one line of a `.city.jsonl` stream |

Encode chooses `city-model` for an entity with the list `cityjson.scale`,
and `feature` for an entity with `uid`.

## Mapping and evidence

| Wire | Model key | Evidence |
|---|---|---|
| CityJSONFeature `id` | `uid` | section 7.2: the member is required and is the identifier of the feature, the City Object that is the parent of the others in the feature. That is the meaning of `uid` (a stable identifier of the entity), and both are text. |
| `version` | (the kind's `when`) | section 1: the minor version only, as a string |
| `transform.scale`, `transform.translate` | lists `cityjson.scale`, `cityjson.translate` of `cityjson.component` | section 4: three numbers each |
| `metadata.title`, `identifier`, `referenceDate`, `referenceSystem` | `cityjson.title`, `cityjson.identifier`, `cityjson.reference_date`, `cityjson.reference_system` | sections 5.2, 5.4, 5.5, 5.6 |
| `metadata.geographicalExtent` | list `cityjson.extent` of `cityjson.component` | section 5.1: six numbers in the reference system, not compressed by the transform |
| `metadata.pointOfContact` members | `cityjson.contact_name`, `contact_email`, `contact_role`, `contact_website`, `contact_type`, `contact_phone`, `contact_organization` | section 5.3 |

No position is bound. The extent and the vertices are in the CRS that
`referenceSystem` names, which section 5.5 asks to be a three-dimensional
one, usually a national projected system, not WGS 84 longitude and latitude.

## Not mapped

- **Vertices and geometries.** `vertices` is an array of arrays of three
  integers, and every geometry's `boundaries` are nested arrays of indexes
  into it (section 3). The json wire addresses object members by name; a
  group reads an array whose items are objects or scalars, and an item that
  is itself an array is `transform-decode` (ruling 6 of 0.7). There is no
  locator for "element i of an array", nor for a value found by an index
  read elsewhere. Same gap as CZML (docs/coverage-roadmap.md). On a round trip
  `vertices` and every geometry are dropped (arrays outside a group are not
  residue, Version 0.5), so the encoder's output lacks the required
  `vertices` member and is not a valid CityJSON object.
- **City Objects.** `CityObjects` is a map whose member names are object IDs
  chosen by the producer. A group needs an array; a field needs a fixed
  name. Their scalar members (`type`, the members of `attributes`) are
  carried as residue under paths such as `CityObjects.b1.type`, so a round
  trip keeps them; `children`, `parents` and `geometry` are arrays and are
  dropped. An ID that holds a `.` cannot be told apart from a nested member
  in a residue path.
- `appearance`, `geometry-templates`, `extensions` and extension members at
  the root: their scalar members are residue, their arrays are dropped.
- `metadata.pointOfContact.address`: any members; scalars are residue.
- Versions other than 2.0 (`no-kind`, vector 04).
- **CityGML 3.0** (the XML encoding, OGC 21-006r2) is not built: every
  element is in one of several namespaces written with prefixes
  (`core:`, `bldg:`, `gml:`, `xlink:`), for example
  `<core:CityModel xmlns:core="http://www.opengis.net/citygml/3.0" xmlns:gml="http://www.opengis.net/gml/3.2"><core:cityObjectMember><bldg:Building gml:id="b1">`,
  and positions are `gml:posList` text, a list of numbers to split. The pack
  language has neither namespace-aware names nor a split transform.

## Candidate pack-language additions

1. Array indexing on `json`: a locator step for element i of an array
   (`transform.scale.0`), and a group whose item is an array (`vertices` as a
   list of x, y, z).
2. Indirection: a value found by an index read in the same message (a
   boundary's vertex index into `vertices`). With 1 and 2, and the transform,
   a pack could state the real coordinates of a vertex.
3. A group over the members of an object whose names are data (`CityObjects`),
   the member name being an item key.

## Vectors

`tools/gen/ogc-geo-vectors.py` writes each object and its canonical form from
the json rules of `spec/engine-spec.md`; no engine is run.

| File | Case |
|---|---|
| `01-city-model-roundtrip` | transform, metadata and extent lists, point of contact; City Object scalars as residue; vertices and geometry dropped |
| `02-feature-roundtrip` | the feature's id as `uid`; vertices dropped |
| `03-feature-to-geojson` | `uid` to the GeoJSON id; geometry null |
| `04-other-version-is-no-kind` | version 1.1 |
| `packs/geojson/vectors/to-cityjson-05-from-geojson-feature` | GeoJSON id to a CityJSONFeature |
