# covjson-coverage

A CoverageJSON Coverage document: a domain, the parameters, and the ranges of values over the domain. Wire `json`. Written by hand from the text of OGC 21-069r2 (CoverageJSON 1.0).

Two kinds, both under `type` = `Coverage`:

| Kind | Holds when | `requires` |
|---|---|---|
| `inline-domain` | `domain.type` is `Domain`: the domain is written in the coverage | `covjson.domain_object` |
| `domain-url` | otherwise: `domain` is a URL (a string) | `covjson.domain_url` |

Both map `id`, the coverage's `domainType` (`covjson.coverage_domain_type`) and `parameterGroups`
(list `covjson.parameter_groups`: `type`, `id`, and the parameter names in `members`).

## The domain

The domain lines are the same in the three packs (with the prefix `domain.` inside a coverage).

| Members | Lines | Keys |
|---|---|---|
| `axes.x`, `axes.y`, `axes.z`: `values` | `group` of `.` items, `float` | lists `covjson.axis_{x,y,z}_values`, item key `covjson.axis_{x,y,z}_value` |
| `axes.t`: `values` | `group` of `.` items, `string` | list `covjson.axis_t_values`, item key `covjson.axis_t_value` |
| `start`, `stop`, `num` of each of the four axes | `float`, `float`, `int` | `covjson.axis_<a>_start`, `_stop`, `_num` |
| `bounds` of each of the four axes | `group` of `.` items (`string` on `t`) | `covjson.axis_<a>_bounds`, item `covjson.axis_<a>_bound` |
| `axes.composite`: `dataType`, `coordinates` | `string`; `group` of `.` strings | `covjson.axis_composite_data_type`, `covjson.axis_composite_coordinates` |
| `referencing`, each item: `coordinates`, `system.type`, `system.id`, `system.calendar`, `system.timeScale` | `group` with a nested `group` | `covjson.referencing`, `covjson.ref_coordinates`, `covjson.ref_system_*` |

## Shared-model keys: none, and why

The standard says that in the common domain types the coordinate identifier `x` is geodetic
longitude and `y` geodetic latitude when the reference system is geographic, and the usual
system is the OGC CRS84 longitude-latitude identifier. So a Point domain under that system
holds the position of its coverage, and `x`, `y` could be bound to `lon` and `lat`. The pack
language cannot state it:

- An axis value always sits in the array `values`, even for a Point domain with one value.
  On the `json` wire an array element is reached only as an item of a list (Version 0.7), and
  a shared key such as `lat` is a key of the entity, not of an item; there is no locator for
  "element 0", and no `derive` function takes an item out of a list.
- The meaning of `x` and `y` depends on the `referencing` list (which system, and in which
  order the coordinates are named). A binding that holds only when an item of that list has
  `system.type` GeographicCRS and a CRS84 or EPSG:4326-family `id` needs a `when` that reads a
  list item, or a condition on a decoded item value. Neither exists (Version 0.7 names an item
  decoded by kind as not in the language).

The axis values therefore stay raw keys of `covjson`, and no conversion vector to `geojson` or
`cot-xml` is written: without `lat` and `lon` such a conversion carries no position.

## Not mapped

- Axis values that are not numbers on `x`, `y`, `z` (an identifier reference system may use
  strings): the line reads a number, so a string there is `transform-decode`. Numeric values
  on `t` (a numeric time axis) are likewise `transform-decode`: the 1.0 text writes time as
  strings.
- The values of a composite axis (`tuple` values are arrays of arrays; `polygon` values are
  GeoJSON polygon arrays): an item is an object or a scalar, not an array. `dataType` and
  `coordinates` are mapped; the values are not carried.
- Axes with other names than `x`, `y`, `z`, `t` and `composite`: axis names are data. Their
  scalar members (`start`, `stop`, `num`, `dataType`) come back as residue; their arrays do not.
- Inside a `referencing` item, the i18n members (`description`, `label`), `targetConcept`
  and `identifiers` of a reference system: their member names are language tags or
  identifiers, and an item carries no residue, so they are dropped on a round trip.
- `parameters` and `ranges`: each member is named by the producer (the parameter's short
  name), so no locator reaches them. Their scalar members come back as residue (a range given
  as a URL included); their arrays do not: the range `values`, `shape` and `axisNames`, and
  the `categories` and `categoryEncoding` of a parameter, are not carried. The values of a
  coverage are therefore not held by this pack.
- Inside a `parameterGroups` item: `label`, `description` and `observedProperty` (i18n
  objects); an item carries no residue.

## Vectors

Derived by `tools/gen/covjson-vectors.py` from the rules of `spec/engine-spec.md`; no engine run.

| File | Shows |
|---|---|
| `01-point-coverage-roundtrip.json` | a Point coverage with its domain inline, a parameter, a parameter group and a range: the range values are not carried |
| `02-domain-url-roundtrip.json` | the domain and the range given as URLs, `domainType` at the coverage |
| `03-not-a-coverage.json` | a Domain document: `no-kind` |
| `04-num-that-is-not-an-integer.json` | `num` of 2.5: `transform-decode` |

## Candidate additions to the pack language

- A `json` locator for one element of an array (or a `derive` that takes item 0 of a list), so
  that a Point domain's `x` and `y` can be bound to `lon` and `lat`.
- A condition on a list item (`when` inside a group, or a binding that holds only when an item
  of `referencing` names a geographic CRS), so that the binding holds only under CRS84.
- A group over an object whose member names are data (the name as an item key), for
  `parameters` and `ranges`; and `json` residue that keeps arrays, as `geojson` residue does,
  so that range values survive a round trip.
