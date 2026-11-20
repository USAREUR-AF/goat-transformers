## What is not carried

The EDR GeoJSON feature collection: features, the parameter metadata (`parameters`), links,
`timeStamp`, `numberMatched`, `numberReturned`. No shared key is bound: on the json wire a
feature's coordinates are arrays whose shape depends on the geometry type, and its `id` is a
string or an integer. Read one feature with `ogcapi-edr-feature`.
