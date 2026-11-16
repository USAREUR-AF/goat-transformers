# Pack: conformance-json

A synthetic probe format for the `json` wire (`spec/engine-spec.md`, Version
0.5). It belongs to no standard. Its vectors pin canonical member order, residue
at nested depth, string escaping, `null` as absent, the `bool` transform, and
kind selection by a string, by a number, by a boolean and by `present`, the
JSON type a `when` value is written with, and two `field` lines on one locator.
