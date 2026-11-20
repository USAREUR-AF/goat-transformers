## What is not carried

A CoverageJSON response. The data is keyed by name: `parameters` and `ranges` are objects
whose member names are the parameter names (`additionalProperties`), and the labels and
descriptions are objects keyed by language tag; no json locator addresses a member whose name
is data, so none of them is mapped. The values of a composite axis are arrays of arrays, also
not addressable. What is mapped is the document's type, its domain type, the domain's axis
values that are plain lists and the referencing list. A pack-language addition that maps the
members of an object by name into a list would carry parameters and ranges.
