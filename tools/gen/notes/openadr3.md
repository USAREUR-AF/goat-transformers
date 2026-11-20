## Evidence for the shared keys

- `uid` (`id`): the object metadata common to every addressable object carries an `id`
  that the server (the VTN) provisions when it creates the object, a URL-safe text of 1 to
  128 characters. `uid` is the stable identifier of the entity.

Not bound, and why: `createdDateTime` and `modificationDateTime` are bookkeeping times of
the object, not the time a report is valid; interval start times are inside lists. No
OpenADR object carries a position, so no conversion vector to geojson or cot-xml is
written.

## Source

The OpenADR Alliance makes the specification available at no charge after an account
registration; its repository is not public. The pack is generated from a public mirror
that republishes the OpenAPI document unchanged (the `-UPSTREAM` file of the mirror).
