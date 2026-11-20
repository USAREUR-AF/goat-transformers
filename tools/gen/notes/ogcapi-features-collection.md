## What is not carried

A collection description: Part 1 `collection.yaml` with the two members Part 2 adds
(`storageCrs`, `storageCrsCoordinateEpoch`). No shared key is bound: the collection is
metadata about a set of features, not a reported entity. The spatial extent's `bbox` is an
array of arrays of numbers and the temporal extent's `interval` an array of arrays of
strings: an array of arrays is not addressable on the json wire.
