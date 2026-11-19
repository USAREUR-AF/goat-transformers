# cap

OASIS Common Alerting Protocol 1.2: an XML alert message for all-hazard
emergency alerts and public warnings. Wire `xml`, root `alert`, one kind.
Hand-written; vectors derived by `tools/gen/alerts-adsbjson-vectors.py`
(standard library only, no engine).

## Message convention

One message is one `<alert>` document with the CAP 1.2 default namespace
`urn:oasis:names:tc:emergency:cap:1.2` on the root (a common `when`; the
encoder writes it). Every element of `alert`, `info`, `resource` and `area`
that the 1.2 schema defines is mapped, in the schema's order, with repeated
elements as lists (`cap.codes`, `cap.infos`, and inside an info
`cap.categories`, `cap.response_types`, `cap.event_codes`, `cap.parameters`,
`cap.resources`, `cap.areas`; inside an area `cap.polygons`, `cap.circles`,
`cap.geocodes`). A CAP 1.2 alert therefore round-trips exactly (vector 01),
except that `altitude` and `ceiling` are written in shortest decimal form.

The kind `alert` requires the six elements the standard makes required
(`identifier`, `sender`, `sent`, `status`, `msgType`, `scope`). Converting from
a format that has none of them is `no-kind`; a caller can supply them as
context (`packs/geojson/vectors/94-to-cap-with-context`).

## Shared-model keys and the evidence

| Wire | Key | Evidence (CAP 1.2, in our words) |
|---|---|---|
| `sent` | `time_ms` | 3.2.1: `sent` is the time and date the alert message was originated; 3.3.2: every date-time is `YYYY-MM-DDThh:mm:ss` with a numeric offset from UTC. `iso8601_ms` reads the offset and converts to UTC |

`sent` is mapped twice: first as text (`cap.sent`), then as `time_ms`. On
encode the earlier line whose key is present is written (ruling 16 of 0.5), so
the text as the sender wrote it comes back. This is the reverse of the order
ruling 16 recommends, on purpose: 3.2.1 and 3.3.2 forbid the `Z` designator and
require `-00:00` for UTC, and `iso8601_ms` always writes `Z`, so writing from
`time_ms` would produce an alert that is not valid CAP. Because the kind
requires `cap.sent`, the encoder never writes from `time_ms`.

Nothing else is bound:

- **Areas.** 3.2.4: `polygon` is a whitespace-separated list of WGS 84
  `latitude,longitude` pairs (first equal to last), and `circle` is a pair, a
  space and a radius in kilometres. Both are one text value per element; the
  pack language cannot read numbers out of delimited text, so they are carried
  as `cap.polygon` and `cap.circle`. An alert has no single position, so
  `lat`/`lon` would in any case need a rule (first vertex, centre) that the
  standard does not state.
- `altitude` and `ceiling` are feet above mean sea level (3.2.4): not `hae`.
- `info/expires` is in the `cap.infos` list. A list item's key cannot reach the
  entity, and a `field` on `info/expires` would pass through the group's path
  (ruling 21 of 0.7), so `stale_ms` is not bound. The other times
  (`effective`, `onset`, `expires`) are kept as text for the same reason as
  `sent`.
- `identifier` names the message, not an entity, so it is not `uid`.

## Not mapped

- The extension wildcard at the end of `alert` (elements of other namespaces).
- A document written with a namespace prefix (`<cap:alert xmlns:cap=…>`): the
  xml wire compares names as written, so it matches no kind (`no-kind`).
- CAP 1.1 and 1.0 (other namespaces) are refused (vector 04).
- Text needing XML escapes (`&`, `<`): canonical XML escaping is not stated in
  `spec/engine-spec.md`, so no vector pins it, although CAP descriptions often
  hold `&`.

## Candidate pack-language additions

1. A text-split transform (`split:<sep>:<index>`, with a whitespace separator)
   to read polygon vertices and the circle centre and radius.
2. A date-time transform that writes a numeric offset, for example
   `iso8601_offset` writing `-00:00` for UTC, so `time_ms` could be written
   into a valid `sent` without the caller supplying the text.

## Vectors

| File | Case |
|---|---|
| `01-full-alert-roundtrip` | every element, two info blocks, nested lists |
| `02-minimal-alert-roundtrip` | the six required elements |
| `03-alert-to-geojson` | `sent` with `+02:00` to `time_ms`; geometry null |
| `04-cap-1-1-namespace-is-no-kind` | other namespace |
| `05-resource-size-not-integer` | `transform-decode` inside an item |
| `06-sent-without-offset` | `transform-decode` |
| `packs/geojson/vectors/93-to-cap-without-required-elements-is-no-kind` | requires |
| `packs/geojson/vectors/94-to-cap-with-context` | required elements from context; `sent` kept as text |
