//! `Engine::load_tree` loads the named packs and only the model modules they
//! need; a pack and its modules can also be compiled into the binary.

use goat_transformers::Engine;
use std::path::Path;

const COT: &str = r#"<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>"#;
const GEOJSON: &str = r#"{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}"#;

fn root() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[test]
fn load_tree_loads_the_named_packs_and_the_modules_they_use() {
    let mut e = Engine::new();
    e.load_tree(&root(), &["cot-xml", "geojson"]).unwrap();
    assert_eq!(e.formats(), ["cot-xml", "geojson"]);
    assert_eq!(e.modules(), ["core"]);
    assert_eq!(e.convert("cot-xml", "geojson", COT).unwrap(), GEOJSON);
}

#[test]
fn load_tree_follows_uses_through_modules_and_can_be_repeated() {
    let mut e = Engine::new();
    // asterix-cat062 uses cat062, and cat062 uses track
    e.load_tree(&root(), &["asterix-cat062"]).unwrap();
    assert_eq!(e.modules(), ["cat062", "core", "track"]);
    e.load_tree(&root(), &["canonical-track-v2"]).unwrap();
    assert_eq!(e.formats(), ["asterix-cat062", "canonical-track-v2"]);
    assert_eq!(e.modules(), ["cat062", "core", "track"]);
}

#[test]
fn load_tree_names_a_pack_the_tree_does_not_hold() {
    let mut e = Engine::new();
    let msg = e.load_tree(&root(), &["no-such-format"]).unwrap_err().to_string();
    assert!(msg.starts_with("unknown-format: "), "{}", msg);
}

/// The embedding pattern of docs/using.md: the texts are compiled in, so the
/// program reads no file when it runs. Modules go in before the packs.
#[test]
fn packs_compiled_into_the_binary() {
    let mut e = Engine::new();
    e.load_model(include_str!("../../../model/core.def")).unwrap();
    e.load_def(include_str!("../../../packs/cot-xml/pack.def")).unwrap();
    e.load_def(include_str!("../../../packs/geojson/pack.def")).unwrap();
    assert_eq!(e.convert("cot-xml", "geojson", COT).unwrap(), GEOJSON);
}
