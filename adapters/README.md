# adapters

Optional transport adapters: state where messages arrive and where they leave,
and the engine converts them in between. The engine does not depend on anything
here. The page for users is [docs/adapters.md](../docs/adapters.md).

| Directory | Holds | Dependencies |
|---|---|---|
| `core/` | the `Source`, `Sink` and `Framer` traits, the framers, the pipeline | the engine |
| `std/` | stdin, stdout, files, directories, TCP, UDP, serial; the `goat-xf-pipe` tool | `core` |
| `mqtt/` | MQTT 3.1.1 at QoS 0; the `goat-xf-pipe-mqtt` tool | `std` |
| `zenoh/` | Zenoh; the `goat-xf-pipe-zenoh` tool. Outside the workspace | `std`, `zenoh` |

```bash
cargo test                                   # core, std, mqtt
cargo build --release -p goat-adapters-std   # target/release/goat-xf-pipe
target/release/goat-xf-pipe --help
```

`core`, `std` and `mqtt` use only the standard library. A transport that needs
a third-party crate is its own crate outside this workspace, so that building
the workspace downloads nothing. The `adapters` job of `.github/workflows/conformance.yml` builds and tests this workspace.
