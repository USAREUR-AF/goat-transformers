# goat-adapters-zenoh

Status: Built, and released for Linux arm64 (Jetson Thor and Orin) by
`.github/workflows/release-pipe.yml`. `cargo test` here passes its 2 tests.

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

## Links

Zenoh 1.9.0 is built with its `tcp`, `udp` and `tls` links (features
`transport_tcp`, `transport_udp`, `transport_tls`). A router that accepts
only `tls/` endpoints is reached with a configuration file that names the CA
(`transport/link/tls/root_ca_certificate`) and the `tls/` endpoint, passed as
`?config=<file>` on the `zenoh:` URI. `tests/tls-smoke.sh <binary> <packs>`
sends messages from one copy of the binary to another over
`tls/127.0.0.1` with a CA and certificate it makes, and fails when the binary
has no TLS link; `release-pipe.yml` runs it on every build.

## Metrics

`--metrics <addr>` (`:9464` for every address) serves the pipeline's counters
for Prometheus on `GET /metrics`: messages in and out by format, and errors by
stage (`decode`, `encode`, `deliver`, `source`), format and error name. It is
in `goat-adapters-std`, so `goat-xf-pipe` has it too; the series are listed in
`adapters/std/src/metrics.rs`.

## Release

A tag `xf-pipe-v<version>` equal to this crate's version (`xf-pipe-v0.1.0`)
builds `goat-xf-pipe-zenoh` on an arm64 runner for `aarch64-unknown-linux-gnu`,
checks that it needs no glibc newer than 2.35 (Jetson Orin, JetPack 6), packs it
with `packs/` and `model/` of the tag, the licence files and
[`dist/README.txt`](dist/README.txt) as
`goat-xf-pipe-zenoh_<version>_linux_arm64.tar.gz`, and attaches it to a GitHub
Release with `SHA256SUMS` and a build provenance attestation. A pull request
that touches `adapters/` runs the same build, package and smoke test, without
releasing.

## Where it is built

The `adapters` job of the conformance workflow builds the workspace only, so
it downloads no crate; `release-pipe.yml` builds this crate on arm64. Build and
test it where the 297 crates can be fetched:

```bash
cd adapters/zenoh
cargo test       # 2 tests; one opens two sessions in one process
```
