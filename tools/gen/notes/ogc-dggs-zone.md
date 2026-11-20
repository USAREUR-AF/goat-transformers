## What is not carried

Information about one zone of a discrete global grid. No shared key is bound: a zone is a
cell of the grid, not a reported entity. `centroid` and `bbox` are lists of numbers in the
zone's CRS (`crs`, default CRS84) and are mapped only as lists; the zone geometry's polygon
coordinates (arrays of arrays) and the per-field `statistics` (keyed by field name) are not
mapped.
