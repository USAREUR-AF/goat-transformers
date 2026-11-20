## What a message is

One SWE Common 3.0 data component description, or one DataStream description, as the JSON
object the JSON encoding defines. The member `type` names the component (`Quantity`,
`DataRecord`, ...) and selects the kind. These objects describe data (its definition, unit,
constraints and, for a simple component, an optional inline value); they are not reports
about an entity, so no member is bound to a shared key.

## Licence basis

The schemas are published by OGC in `opengeospatial/ogcapi-connected-systems` under the OGC
Software License (the repository's `LICENSE`), and byte for byte at
`schemas.opengis.net/sweCommon/3.0/json/`. That license permits use, copying and
modification provided the copyright notice is kept and a modified copy says it holds changes
OGC has not approved. This pack is such a change: it is derived from the schemas and has
not been approved or adopted by OGC. `PROVENANCE.md` keeps the notice in full.

## What the pack language leaves out

- **Values whose JSON type varies.** A Quantity `value` and a constraint's `values` may be a
  number or one of the strings `NaN`, `Infinity`, `+Infinity`, `-Infinity`; a `json` line has
  one type. Outside an array such a member is residue and round-trips as written; inside an
  array (constraint values, nil values of a group item) it is not carried.
- **Intervals and ranges.** Constraint `intervals` and the `value` of a range component are
  arrays of two numbers or arrays of arrays: a group item cannot be an array.
- **Encoded values.** A DataArray, Matrix or DataStream `values` member holds the data as an
  array of arrays or a block of text whose layout the `encoding` member states; the language
  has no line for either.
- **Deep aggregates.** See the depth limit below: components inside components are mapped
  to four levels.
