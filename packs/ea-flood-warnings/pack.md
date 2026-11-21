# ea-flood-warnings

The Environment Agency's real-time flood-monitoring API (England): the flood alerts and warnings
in force (`/id/floods`), its `items` a list. Wire `json`, no kinds. Written by hand from the API
reference; vectors by `tools/gen/hydro-vectors.py`. Licence: `OGL-UK-3.0`.

Each warning is a list item of `eaflood.floods`: `@id`, `description`, `eaAreaName`,
`eaRegionName`, `floodAreaID`, `message`, `severity`, `severityLevel`, the three times (as
written: the API writes them without a zone), and the flood area's `county`, `notation`,
`polygon` (a URI) and `riverOrSea`.

## Shared-model keys: none, and why

Warnings are list items; their times carry no zone, so they are not instants; the flood area's
boundary is a separate document behind `polygon`.

## Not mapped

- `meta` (publisher, licence, documentation, version): scalar residue, carried back; its arrays
  (`hasFormat`) are not carried on the json wire.
- Members inside a list item that the pack does not name: an item carries no residue.
- The JSON-LD meaning of the members (`@context`): the context URI is kept as text, not resolved.
- The CSV, RDF and Turtle forms of the API: other wires.
- `isTidal`, a boolean inside an item, and the flood area's `@id`: dropped (no `bool` line is
  given for it here, to keep every line a string or number the API documents as one).

## Vectors

| File | Shows |
|---|---|
| `01-warnings-roundtrip.json` | one flood alert; the area's `@id` and `isTidal` dropped |
