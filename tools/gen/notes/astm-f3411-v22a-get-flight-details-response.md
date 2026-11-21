
## A member that only the OpenAPI file details

`eu_classification` is an object with `category` and `class` in the OpenAPI file, but
InterUSS's api.py, the source of record, types it as an untyped dictionary. Its two members
are mapped from the OpenAPI file (raw keys `*eu_classification_category` and
`*eu_classification_class`); they are the one place this pack goes beyond what api.py states
(tools/gen/utm-crosscheck.py reports it).
