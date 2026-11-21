# Pack: ogcapi-coverages-coverage

A coverage in the JSON encoding of the OGC Coverage Implementation Schema (CIS) 1.1.1, the
document OGC API - Coverages returns for a coverage. Wire `json` (engine-spec 0.5, groups
0.7). Written by hand from the standard's text (OGC 09-146r8). No kinds: one message.

## Why by hand, and from the text only

The JSON Schema files of CIS (and their copy in `opengeospatial/ogcapi-coverages`,
`standard/openapi/schemas/cis/`) are headed "All Rights Reserved". This pack does not copy or
derive from them. It is built from the standard document, which is published under OGC's
licence and is free to implement. Its member names and types come from:

- the structure tables of clauses 6 to 8 (`AbstractCoverage`, `EnvelopeByAxis`,
  `AxisExtent`, `GeneralGrid`, `Axis`, `GridLimits`, `IndexAxis`, `RegularAxis`,
  `IrregularAxis`, `RangeType`);
- the JSON example of clause 13 (class `json-coverage`), which shows how those structures
  are written in JSON: every object carries a `type` member with a type token, the grid's
  axes are the array `axis`, the axis labels the array `axisLabels`, the range values sit in
  `dataBlock.values`, and the range type record's components are the array `field`, each
  with `type`, `definition` and `uom.code`.

## Open questions a person should settle

1. **Case of the three components.** The AbstractCoverage table names them `domainSet`, `rangeSet` and
   `rangeType`; the JSON example of clause 13 writes `DomainSet`, `RangeSet` and `RangeType`.
   Requirement 36 makes the JSON Schema normative, and this project has not read it. The pack
   follows the table (lower case). A document written the other way decodes with no domain set,
   range set or range type.
2. **The range type record.** The RangeType table gives `RangeType` a member `dataRecord`; the JSON example
   writes the record's own `type` and `field` directly in the range type object. The pack
   follows the example.
3. **Names the JSON example does not show** follow the tables: `id`, `envelope`,
   `srsDimension`, `axisExtent`, `uomLabel`, `resolution`, `gridLimits`, `indexAxis`. The name
   of a range component (`name`) follows the soft-typing text of clause 6.5 and SWE Common.

## What is mapped

Every member below is a raw key of module `ogccovcis`; no shared key is bound (a coverage is
a gridded data set, not a reported entity: its envelope is a box in any CRS, not a position).

| Place | Transform | From the text |
|---|---|---|
| `type`, `id` | string | the coverage type token; the coverage identifier (AbstractCoverage table: a string) |
| `envelope.type`, `.srsName`, `.srsDimension` | string, string, int | EnvelopeByAxis table: CRS URL, positive integer dimension |
| `envelope.axisLabels[]` | list of strings | the axis labels, in CRS axis order |
| `envelope.axisExtent[]`: `type`, `axisLabel`, `uomLabel`, `lowerBound`, `upperBound` | string | the AxisExtent table types every member, bounds included, as a string |
| `domainSet.type`, `domainSet.generalGrid.type`, `.srsName` | string | GeneralGrid table |
| `domainSet.generalGrid.axisLabels[]` | list of strings | as in the clause 13 example |
| `domainSet.generalGrid.axis[]`: `type`, `axisLabel`, `uomLabel`, `resolution` | string | Axis, RegularAxis and IrregularAxis tables; `resolution` is a string (the text gives durations as the reason) |
| `domainSet.generalGrid.gridLimits.type`, `.srsName` | string | GridLimits table: the Index CRS of the array |
| `domainSet.generalGrid.gridLimits.indexAxis[]`: `type`, `axisLabel`, `lowerBound`, `upperBound` | string, string, int, int | GridLimits and IndexAxis tables (index axis bounds are integers) |
| `rangeSet.type`, `rangeSet.dataBlock.type` | string | the clause 13 example |
| `rangeType.type`, `rangeType.field[]`: `type`, `name`, `definition`, `uom.type`, `uom.code` | string | clause 6.5 and the clause 13 example |

## Not mapped, and why

| Place | Reason |
|---|---|
| `rangeSet.dataBlock.values` | the range values. Their JSON type follows the range type (numbers, encoded dates, text, or arrays for composite values), so no single transform reads them; an array is not residue on the json wire. A pack-language addition that reads a list whose item type is chosen by another member would carry them |
| `lowerBound`, `upperBound` of `domainSet.generalGrid.axis[]` | an integer for an index axis, a string for a regular axis (IndexAxis and RegularAxis tables); one list holds both, and a transform reads one JSON type |
| `directPositions` of an irregular axis; displacement and transformation axes; `partitionSet` | coordinate tuples and nested structures of classes `grid-irregular`, `grid-transformation`, `discrete-*` and `coverage-partitioning`; not addressable, or of several JSON types |
| `coverageFunction`, `interpolationRestriction` | GML-defined structures the text does not spell out for JSON |
| `metadata` | open extension content; its scalar members are residue (carried back as they were) |
| any other top-level scalar | residue |

The pack is not hollow: it reads the structure of a coverage (CRS, axes, resolution, array
limits, range components and units). It does not read the data values.

## Message convention

One JSON object per message. Canonical output: mapped members in line order (envelope,
domain set, range set, range type), nested objects where their first line addresses them,
then residue scalars in input order.

## Vectors

Written by `tools/gen/ogcapi-coverages-vectors.py` from its own copy of the member list and
the json wire rules of `spec/engine-spec.md`; no engine is run, and no value comes from the
standard's example.

- `01-regular-grid-roundtrip`: a 2-D regular grid with envelope, grid limits and two range
  components, members in an order of their own; the regular-axis bounds and the range values
  are not carried; a top-level scalar is residue.
- `02-index-grid-roundtrip`: a 3-D index grid, no envelope and no grid limits.
- `03-srs-dimension-string-error`: `srsDimension` as a string is `transform-decode`.
- `04-index-bound-fraction-error`: an index axis bound with a fraction is `transform-decode`.

No conversion vector: the pack binds no shared key, so it converts to nothing.
