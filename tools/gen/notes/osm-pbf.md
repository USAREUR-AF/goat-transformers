## What the message is

An OpenStreetMap PBF file is a sequence of blocks. Each block is a 4-byte big-endian length, a
`BlobHeader` of that length, and a `Blob` whose size the header gives. The `Blob` holds the
serialized block, usually compressed (zlib, and in newer files lzma, lz4 or zstd). The first block
is an `OSMHeader` and holds a `HeaderBlock`; every other block is an `OSMData` and holds a
`PrimitiveBlock`.

Three packs share module `osmpbf`:

- `osm-pbf-blob-header`: one `BlobHeader`.
- `osm-pbf-header`: one `HeaderBlock`, the uncompressed content of the first blob.
- `osm-pbf-primitive`: one `PrimitiveBlock`, the uncompressed content of a data blob.

The packs do not split a file into blocks, read the length prefix or decompress a blob: the
engine has no framing and no decompression. A caller does those steps and hands each message to
its pack. `Blob` itself has no pack: apart from `raw_size` every field is `bytes`, which no
transform reads.

## Everything raw

No field is bound to a shared key, and the packs convert to no other format.

- A node's position is an integer in units of `granularity` nanodegrees, offset by `lat_offset` and
  `lon_offset` of the block; in `DenseNodes` each id, latitude and longitude is also the difference
  from the previous node. Neither the scale nor the running sum is a transform, so the values are
  carried as the integers on the wire, in the lists of the block.
- `HeaderBBox` (`left`, `right`, `top`, `bottom`) is in nanodegrees: raw integers.
- Tags are indices into the block's `StringTable`, whose entries are `bytes`; the string table has
  no line, so a tag's text is not carried.
- `Info.timestamp` is in units of `date_granularity` milliseconds: raw.
- `BlobHeader.indexdata` is `bytes`: not carried.
- `PrimitiveBlock.stringtable` is `required` in the schema and holds only `bytes`: a block that
  is decoded and encoded again has no string table, which a PBF reader rejects. The round trip is
  for inspecting a block, not for writing a file.

## Hand-written vectors

`osm-pbf-blob-header/01-indexdata-dropped`, `osm-pbf-header/01-header-roundtrip` and
`osm-pbf-primitive/01-dense-nodes-stringtable-dropped` (two dense nodes; the string table is not
written back), written field by field by `tools/gen/protobuf-2-vectors.py` (standard library only; no engine, no generator).
