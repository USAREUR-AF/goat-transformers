# goat-adapters-zenoh

Status: Built. `cargo test` here passes its 2 tests; CI does not build it.

Zenoh as an input and an output of `goat-xf-pipe`: a subscriber on a key
expression, and one `put` per converted message.

```bash
cd adapters/zenoh
cargo build --release
goat-xf-pipe-zenoh --packs packs --packs-only \
  --from-format cot-xml --in 'zenoh:capture/cot/**' \
  --out zenoh:converted/geojson --to-format geojson
```

URI: `zenoh:<key expression>[?config=<file>&mode=<peer|client>&connect=<endpoint>]`

One sample is one message. A framing stated with `--in-frame` applies inside
each sample. A message's origin is the key its sample was published on.

## Why it is its own crate, outside the workspace

`zenoh` 1.9.0 with TCP and UDP transports resolves to 297 crates. The rule of
`adapters/` is that a third-party dependency lives only in the crate of the
transport that needs it, so `cargo build` in `adapters/` never resolves these.

## Why CI does not build it

The `adapters` job of the conformance workflow builds the workspace only, so
it downloads no crate. Build and test this crate where the 297 crates can be
fetched:

```bash
cd adapters/zenoh
cargo test       # 2 tests; one opens two sessions in one process
```
