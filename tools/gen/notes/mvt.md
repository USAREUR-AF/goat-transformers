## What the message is

The pack's message is one Mapbox Vector Tile: a `Tile` as specification 2.1 defines it, the bytes
of one tile as a tile server returns them. Servers often compress tiles with gzip; the caller
decompresses before `decode`.

## Everything raw

A tile holds layers; a layer holds features, a table of keys and a table of values; a feature
holds its id, its geometry type, its tags as pairs of indices into the two tables, and its
geometry as a list of command and parameter integers in tile coordinates (0 to `extent`). Every
one of these is a raw key or list of module `mvt`, and the pack converts to no other format: a
position in a tile is relative to the tile's grid, and becomes a latitude and longitude only with
the tile's zoom, column and row, which the message does not hold.

- `Tile` holds only the repeated field `layers`, so the pack has no field outside a group and
  requires nothing.
- `Layer.version` is `required` in the schema; the pack writes it only when the item has the key.
- The extension ranges of `Tile`, `Layer` and `Value` have no line.

## Hand-written vector

One round trip, written field by field by `tools/gen/protobuf-2-vectors.py` (standard library only; no engine, no generator).
