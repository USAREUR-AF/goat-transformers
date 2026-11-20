## What is not carried

- `data` is an object, a list or a string according to the endpoint; it states no single JSON type and is not mapped. Read the object itself with the pack of its module.

## How this pack was made

OCPI 2.2.1 has no machine-readable schema. This project restated the member names, JSON
types and required members of the objects from the document's object tables in its own file
`tools/gen/ocpi/ocpi-2.2.1-objects.json` (no description text, example or table of the
document is copied), and generated the pack from it. Enumerations are read as strings; a
`DateTime` is kept as its text (a raw key).

## Not bound to shared keys

- **Positions.** `GeoLocation` gives `latitude` and `longitude` as JSON strings holding
  decimal degrees on WGS 84, with five to seven decimals. No transform of the json wire reads
  a number held in a string (`float` reads a JSON number), and no derive function parses
  decimal text into a float, so `lat` and `lon` are not bound; the strings are raw keys. A
  derive `parse_float` (the float sibling of `parse_int`), with a fixed-decimals form for
  encode, would carry them.
- **Times.** `last_updated` is the time the object was last changed in the sender's system,
  not the time a report is valid; session and CDR times are the start and end of charging.
  None is bound to `time_ms`.
- **Identifiers.** `id`, `uid` and `evse_id` are unique only within a CPO's or eMSP's
  platform (with `country_code` and `party_id`); `uid` is not bound.
