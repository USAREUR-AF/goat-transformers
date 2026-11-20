## What is not carried

The response of the items resource: the features, links, `timeStamp`, `numberMatched` and
`numberReturned`. No shared key is bound: a feature inside the collection has no Point
locator on the json wire (`geometry.coordinates` is an array of numbers or of arrays,
depending on the geometry type), its `id` is a string or an integer, and its `properties`
are open. Read single features with `ogcapi-feature`. `timeStamp` is the time the response
was generated, not the time a feature is valid, so it is not bound to `time_ms`.
