# Benchmark

Each engine runs the same benchmark (engine-spec, Version 0.25, ruling 2):
the 16 conversion vectors of `bench/set.json`, one or more on every wire, each
converted once and checked against its `expect`, then converted 2000 times.
The run prints the time of one conversion per vector, and the time the engine
took to load the set's packs. No number fails a check (ruling 2d).

## The numbers

Microseconds per conversion, from the `conformance` workflow on `main` at
commit c22e0ba6e (run 45988169036, 27 November 2026). Each engine's job ran on
its own GitHub-hosted `ubuntu-latest` runner, so two columns are not one
machine: read a column down, and compare columns only for a large difference.

| Vector | rust | go | cpp | zig | java | erlang | python |
|---|---:|---:|---:|---:|---:|---:|---:|
| `cot-xml/01-track-to-geojson` | 12.6 | 12.1 | 6.2 | 4.5 | 96.8 | 117.5 | 154.1 |
| `geojson/01-geojson-to-cot` | 13.7 | 20.3 | 7.1 | 7.4 | 112.9 | 182.7 | 116.8 |
| `canonical-track-v2/02-to-cot-xml` | 22.7 | 36.2 | 13.3 | 15.7 | 121.7 | 252.5 | 176.5 |
| `sapient/01-sapient-to-geojson` | 9.5 | 7.7 | 5.6 | 4.2 | 35.1 | 102.5 | 132.7 |
| `cot-protobuf/01-event-to-cot-xml` | 13.7 | 18.1 | 9.3 | 7.3 | 67.1 | 190.0 | 163.6 |
| `isa/01-isa-to-geojson` | 9.9 | 12.4 | 10.0 | 8.5 | 37.5 | 247.4 | 238.7 |
| `uci/gen-001-access_assessment-roundtrip` | 168.4 | 189.8 | 92.6 | 55.0 | 272.7 | 1376.4 | 1730.1 |
| `a-gra/gen-001-access_assessment-roundtrip` | 129.5 | 142.0 | 75.6 | 45.5 | 88.8 | 1063.0 | 1443.8 |
| `nmea2000/rt-pgn59392` | 1.7 | 1.4 | 0.8 | 0.6 | 9.6 | 17.4 | 29.1 |
| `mavlink2/rt-00000-heartbeat` | 6.6 | 3.2 | 2.1 | 1.3 | 7.5 | 24.4 | 53.8 |
| `asterix-cat062/12-to-canonical-track-v2-with-context` | 23.1 | 21.5 | 12.9 | 7.0 | 37.4 | 175.6 | 201.8 |
| `remote-id/09-basic-id-upstream-test-bytes-to-geojson` | 4.7 | 3.6 | 2.5 | 1.5 | 6.4 | 25.9 | 61.9 |
| `adsb/01-identification-tc1-roundtrip` | 4.7 | 4.4 | 2.5 | 1.8 | 7.2 | 41.6 | 74.8 |
| `nmea0183/40-rmc-to-geojson` | 9.8 | 7.8 | 5.4 | 3.9 | 29.3 | 70.1 | 120.6 |
| `dhcpv6-options/01-solicit-options-round-trip` | 23.3 | 7.8 | 15.5 | 16.1 | 42.8 | 84.2 | 299.3 |
| `dtn-bpv7/01-ipn-round-trip` | 27.6 | 14.8 | 15.0 | 6.3 | 36.7 | 141.5 | 227.4 |
| load, ms (packs) | 604 (16) | 832 (16) | 821 (16) | 359 (16) | 1412 (16) | 4487 (16) | 1557 (16) |
`tools/bench-table.py` made this table from the seven `bench-<engine>.jsonl`
files the run keeps as artifacts. Every `conformance` run writes the same
table to the summary of its `bench-table` job and keeps it as the
`bench-table` artifact; that job never fails the run.

## Running it

Each engine's README states its command (ruling 2e). From the repository root:

| Engine | Command |
|---|---|
| Rust | `cargo run --release --manifest-path engines/rust/Cargo.toml --example bench -- bench/set.json` |
| Go | `go -C engines/go run ./cmd/goat-bench ../../bench/set.json` |
| Python | `python3 -I engines/python/bench.py` |
| Java | `engines/java/bench.sh` |
| C++ | `cmake -S engines/cpp -B engines/cpp/build-release -DCMAKE_BUILD_TYPE=Release && cmake --build engines/cpp/build-release --target goat-bench && engines/cpp/build-release/goat-bench bench/set.json` |
| Erlang | `engines/erlang/bench.sh` |
| Zig | `engines/zig/bench.sh` |

Write each run to `bench-<engine>.jsonl`, then:

```
python3 -I tools/bench-table.py bench-rust.jsonl bench-go.jsonl ...
```

For a comparison that means something, run every engine on one idle machine
and keep the machine and the commit with the numbers.

## What an engine keeps

An engine may keep, for the life of an instance, the parsed form of the packs
and modules it loaded and any layout it computes from them (ruling 1); keeping
changes no result, on one thread or several. Each engine's README names what it
keeps and the test that checks it gives the same output as a new instance.
