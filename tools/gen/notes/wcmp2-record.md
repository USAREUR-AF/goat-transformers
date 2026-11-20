## Shared-model keys: none

A WCMP2 record describes a dataset, not an observation. Its `geometry` is the dataset's extent,
usually a Polygon or a bounding box, and the geojson wire refuses a Polygon where a field reads
`geometry.lon` (the reference engine gives `transform-decode`), so no line reads the geometry:
it is not carried, and encode writes `"geometry":null`. `created` and `updated` are times of the
record, not of the data, and the data's time extent is the nested `time` object: no `time_ms`.

## What the geojson wire leaves out of a WCMP2 record

- **The geometry** (above).
- **Top-level members other than the mapped ones:** `conformsTo`, `time`, `links`,
  `linkTemplates`, `additionalExtents`. The reference engine drops top-level residue; ruling 4
  of 0.1.1 orders it, so a ruling is needed before a pack relies on it.
- **Arrays and objects inside `properties`** (`keywords`, `themes`, `contacts`, `wmo:topicHierarchy`
  where an array): residue, which the geojson wire carries back as it was.
- **`id`**, typed as a string or an integer: a line reads one type, so it is residue.
