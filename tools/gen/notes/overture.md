## The form

One message is one Overture feature in its canonical GeoJSON form: a GeoJSON Feature with
`id`, `geometry` and `properties`, as `schema/schema.yaml` and each feature file of
`OvertureMaps/schema` describe it. The common `when properties.theme <theme>` and
`when properties.type <type>` check which feature type it is on decode and write it on
encode. Overture also publishes its data as GeoParquet; that form is not a pack.

The geojson wire addresses the Point coordinates, top-level members and one level of
`properties`. So the scalar members of `properties` are `field` lines and everything below
them (names, sources, addresses lists, the rules of a segment and so on) is residue, which
the geojson wire carries back as it was.

The YAML of the schema is read with the generators' own YAML reader; for these files it
gives the same structure as a full YAML parser (it was compared with one for this run);
only the folding of some long descriptions differs, and descriptions are not used.

## Evidence for the shared keys

- `uid` (`id`): `schema/defs.yaml` gives `id` as the feature's identifier (a GERS ID where
  the feature is part of the Global Entity Reference System). Every feature file declares
  `id` except `buildings/building_part.yaml`; that pack maps no `id`, and as an undeclared
  top-level member a building part's `id` is not carried.
- `lon`, `lat` (the Point), in `overture-address`, `overture-connector`,
  `overture-division` and `overture-place` only: their feature files require the geometry
  to be a GeoJSON Point, and GeoJSON (RFC 7946) gives a position as longitude then latitude
  in WGS 84 degrees.

Not bound:

- **Lines and polygons.** Segments and division boundaries are LineStrings; buildings,
  building parts, division areas, land cover and bathymetry are Polygons or MultiPolygons;
  infrastructure, land, land use and water may be any of Point, LineString, Polygon or
  MultiPolygon. The shared model has one point (`lat`, `lon`) and no line or area, and the
  geojson wire addresses only a Point's coordinates, so these geometries are not carried:
  decode drops them and encode writes `"geometry":null`, on a same-format round trip as
  in a conversion. A feature of the four Point types whose geometry is not a Point fails
  the decode of `lon`.
- **Time.** No feature states its own update time as a member of `properties`: the
  `update_time` of the schema is a member of each item of `sources` (the time of one
  source's record), so no time is bound.
- `version`, `confidence` and the heights and levels of buildings are raw keys (none is
  a shared key's meaning).
