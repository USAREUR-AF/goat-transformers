# ea-flood-readings

The Environment Agency's real-time flood-monitoring API (England): a readings response
(`/data/readings`, `/id/stations/{id}/readings`, `/id/measures/{id}/readings`), its `items` the
readings in order. Wire `json`, no kinds. Written by hand from the API reference; vectors by
`tools/gen/hydro-vectors.py`. Licence: `OGL-UK-3.0`.

Each reading is a list item of `eaflood.readings`: `@id`, `dateTime` (as written), `measure`
(the URI that names the station, the quantity and the unit), `value` (absent where the reading is
not a number, as the reference says the API omits it).

## Shared-model keys: none, and why

The reading time and value are list items, and a shared key of the entity cannot be filled from
one item; a response holds many readings. The position is the station's, which another request
gives (`ea-flood-station`).

## Not mapped

- `meta` (publisher, licence, documentation, version): scalar residue, carried back; its arrays
  (`hasFormat`) are not carried on the json wire.
- Members inside a list item that the pack does not name: an item carries no residue.
- The JSON-LD meaning of the members (`@context`): the context URI is kept as text, not resolved.
- The CSV, RDF and Turtle forms of the API: other wires.

## Vectors

| File | Shows |
|---|---|
| `01-readings-roundtrip.json` | two readings, one without a value |
