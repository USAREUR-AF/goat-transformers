## Evidence for the shared keys

- `uid` (`id`): the local identifier of the observation, which the schema requires.
- `time_ms` (`phenomenonTime`): the schema describes it as the time at which the result is a
  valid estimate of the observed property, the meaning of `time_ms` (the time the report is
  valid). `iso8601_ms` reads it. When it is absent the standard takes `resultTime` in its
  place; the pack does not, so `time_ms` is then absent and `resultTime` is a raw key.

## What is not carried

- **`result`** states no type: it is valid against the result schema of the datastream, which
  the pack cannot see. It is not mapped, nor are `parameters` (an open object).
- **The Link objects** (`procedure@link`, `result@link`) and every other object member: the
  locator of a member of such an object joins the `@link` name and the member name with a
  `.`, which the boundary gate reads as an e-mail address and refuses. The run limits the
  pack to the top level (`--max-depth 1`); the message's own scalars, `id`,
  `datastream@id`, `samplingFeature@id`, `phenomenonTime` and `resultTime`, are mapped.
