# Pack: demo-track-json

A synthetic flat JSON track that maps every key of the `core` and `track`
modules. It belongs to no real standard. The `core` keys are top-level members;
the `track` keys are members of a nested `track` object under their model names.
It exists so a conversion into a format that requires many keys, such as
`canonical-track-v2`, can be shown from a public source that holds them all.

The list `track.identifiers` is the array `track.identifiers`; each element is
an object with `scheme` and `value` (engine-spec Version 0.7, groups).
