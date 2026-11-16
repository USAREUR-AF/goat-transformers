# goat-transformers (Rust)

The reference engine of [goat-transformers](https://github.com/USAREUR-AF/goat-transformers):
it converts messages between formats that are described by data files (packs).
Standard library only.

```toml
[dependencies]
goat-transformers = { git = "https://github.com/USAREUR-AF/goat-transformers", tag = "v0.8.0" }
```

```rust
let mut engine = goat_transformers::Engine::new();
engine.load_model_dir(std::path::Path::new("vendor/goat/model"))?;
engine.load_pack_dir_only(std::path::Path::new("vendor/goat/packs"), &["cot-xml", "geojson"])?;
let geojson = engine.convert("cot-xml", "geojson", cot_event)?;
```

The crate holds the engine. The packs are data: `tools/goat-pkg bundle` in the
repository writes the ones you name, and the model modules they use, to a
directory you vendor. `docs/using.md` in the repository shows the whole path,
including packs compiled into the binary.

The command-line tool: `cargo install --git https://github.com/USAREUR-AF/goat-transformers --tag v0.8.0 goat-transformers`
installs `goat-xf`.
