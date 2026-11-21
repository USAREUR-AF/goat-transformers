## What is not carried

Tile set metadata (OGC Two Dimensional Tile Matrix Set and Tile Set Metadata 2.0, as the
Tiles API carries it). No shared key is bound: the document describes a tiling of a dataset,
not a reported entity, and `boundingBox` and `centerPoint` are in the tile matrix set's CRS,
which need not be WGS 84. A `crs` member may be a URI string or an object (a WKT or PROJJSON
definition, or a reference), so it is not mapped; nor is a layer's open properties schema.
