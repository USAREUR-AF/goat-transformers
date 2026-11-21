# geopackage-geometry-be

A GeoPackage (OGC 12-128r19) is a SQLite database. Its feature tables store
each geometry as a blob in the GeoPackageBinary format: an 8-byte header, an
envelope, then the geometry in Well-known Binary (WKB, OGC 06-103r4). This
pack reads that blob when its header is big-endian (flag B 0, most significant byte first). The pack
`geopackage-geometry-le` reads the little-endian header; the two share the
module `gpkg` and convert into each other without loss for the values both
map.

## Message convention

One message is the bytes of one geometry column value, as hex text. The
pack does not read a GeoPackage file: the tables of the database are not
messages (below).

## Layout

| Bytes | Content | Pack line |
|---|---|---|
| 0, 1 | the ASCII letters G and P | common `when` (71, 80) |
| 2 | version, 0 for GeoPackage version 1 | common `when` 0 |
| 3 | flags: reserved, reserved, X, Y, E (3 bits), B | `when` on B; `gpkg.extended` (X), `gpkg.empty` (Y), `gpkg.envelope` (E) |
| 4 to 7 | srs_id, signed 32-bit, in the order of B | `gpkg.srs_id` |
| 8 on | E = 1: min x, max x, min y, max y; 2: then min z, max z; 3: then min m, max m; 4: then z then m bounds; doubles in the order of B | gate blocks on E (Version 0.17) |
| after the envelope (byte 8, 40, 56 or 72) | WKB: byte order, 32-bit type, then for a Point x and y as doubles | gate blocks on X and Y both 0, on E, and on the first 5 WKB bytes |

The `bits` wire has one bit order per pack (`bit_order msb`), so a pack can
read only one value of B. A blob is big-endian (flag B 0, most significant byte first)
exactly when the common `when` on B holds; the other byte order is
`no-kind` here.

The WKB Point is read only when its own byte order byte equals this pack's
(0) and its type is 1 (two-dimensional Point). The pack reads these 5
bytes as one 40-bit value (1). The standard asks writers to use the same
order in the header and the WKB, and does not require it.

## Mapping and evidence

| Wire | Model key | Evidence |
|---|---|---|
| WKB Point x, when srs_id is 4326 | `lon` | OGC 12-128r19 clause 2.1.3: WKB in a GeoPackage always has the axis order x, y, where x is easting or longitude and y northing or latitude, overriding the axis order of the SRS definition. Clause 1.1.2.1.2 (Requirement 11): the row of `gpkg_spatial_ref_sys` with srs_id 4326 is WGS 84 as EPSG defines code 4326, a geographic system in degrees. So x of a srs_id 4326 Point is WGS 84 longitude in degrees. |
| WKB Point y, when srs_id is 4326 | `lat` | the same sentences: y is latitude, WGS 84, degrees |
| WKB Point x, y, any srs_id | `gpkg.x`, `gpkg.y` | raw, in the units of the srs_id; kept so that a projected point round-trips |
| flags X, Y, E | `gpkg.extended`, `gpkg.empty`, `gpkg.envelope` | Table 5 of clause 2.1.3 |
| srs_id | `gpkg.srs_id` | clause 2.1.3 |
| envelope | `gpkg.min_x` … `gpkg.max_m` | clause 2.1.3, the envelope contents code |

Only srs_id 4326 binds `lat` and `lon`. Another srs_id may also be WGS 84
in a given file, but the number alone does not say so: the meaning of every
other srs_id is in that file's `gpkg_spatial_ref_sys` table, which a blob
does not carry, and clause 1.1.2.1.2 tells clients not to assume the meaning
of any srs_id other than the three Requirement 11 fixes (4326, 0, -1). No height is bound: EPSG 4326 is two-dimensional, and a z
coordinate's reference is not stated by the blob.

## Encode

From an entity with `lat` and `lon` and no `gpkg` keys (a conversion from
GeoJSON or CoT), the gates write X 0, Y 0, E 0, srs_id 4326 and a WKB Point
in this pack's byte order: a 29-byte blob a GeoPackage feature table can
hold. From a decoded blob, the values written outside the gate blocks (flags,
srs_id) decide which blocks hold, so the envelope and the point return at
their offsets.

## Not mapped

- **The tables of a GeoPackage.** `gpkg_contents`, `gpkg_spatial_ref_sys`,
  `gpkg_geometry_columns`, `gpkg_tile_matrix_set`, `gpkg_tile_matrix`,
  `gpkg_metadata` and `gpkg_metadata_reference`, and the user feature and
  tile tables, are SQLite tables. The standard defines them as SQL tables
  only and gives them no message form (no JSON or XML encoding of a row), so
  there is no wire for a row and no pack is written for them.
- **WKB other than a two-dimensional Point.** PointZ, PointM, PointZM (type
  1001, 2001, 3001), LineString, Polygon, the multi types, collections and
  the non-linear types of Annex F.1 are recognised as "not a Point": the
  header decodes, `lat`, `lon`, `gpkg.x` and `gpkg.y` are absent, and an
  encode writes the header only. Their coordinates are counted lists whose
  place depends on earlier counts; a `layout sequential` pack could read
  them, but the pack language cannot combine a sequential layout with the
  gates on E that choose where the WKB starts.
- **A WKB Point whose byte order differs from the header's.** It decodes as
  "not a Point" here.
- **Extended GeoPackageBinary** (X 1, Annex F.2): the extension's type name
  and payload are not read.
- **Empty geometries** (Y 1): the header decodes with `gpkg.empty` 1; the
  WKB, which the standard fills with NaN coordinates for an empty Point, is
  not read and not written.
- **The reserved bits** of the flags byte are not read and are written 0.
- **Envelope codes 5 to 7** are invalid in the standard; such a blob decodes
  its header with no envelope or point.

## Candidate pack-language additions

1. A byte order chosen by a bit of the message: one pack for both values of
   flag B (a `bit_order` per kind, or byte-order-aware transforms such as
   `f64le` / `f64be`, `twos32le`).
2. A sequential layout whose start is chosen by gates, or a sequential block
   at a computed offset: the WKB of every geometry type after an envelope of
   0, 32, 48 or 64 bytes.

## Vectors

`tools/gen/ogc-geo-vectors.py` derives every vector with Python's `struct`
from the layout above; no engine is run. `--check` verifies the files.

| File | Case |
|---|---|
| `01-point-roundtrip` | no envelope, srs_id 4326, a WKB Point; lat and lon bound |
| `02-point-envelope-roundtrip` | envelope code 1; the WKB at byte 40 |
| `03-projected-point-roundtrip` | srs_id 3857: x and y kept raw, lat and lon absent |
| `04-point-to-geojson` | to GeoJSON |
| `packs/geojson/vectors/to-geopackage-geometry-be-05-point-from-geojson` | from GeoJSON: the gates write the header |
| `06-xyzm-envelope-to-le` | envelope code 4 (64 bytes); converted to the other byte order |
| `07-other-byte-order-is-no-kind` | flag B of the other pack |
| `08-bad-magic-is-no-kind` | magic not G P |
| `09-truncated-header-is-malformed` | 7 bytes: srs_id runs past the input |
| `10-empty-point-header-only` | Y 1: the header, without the NaN Point |
| `11-polygon-header-only` | a WKB Polygon: the header decodes; the encode writes the header only |
