//! Packs compiled into the binary, the pattern of docs/using.md: the texts are
//! included at build time, so the program reads no file when it runs. Modules
//! go in before the packs, a module after the modules it uses.

use goat_transformers::Engine;

const COT: &str = r#"<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>"#;
const GEOJSON: &str = r#"{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}"#;

#[test]
fn packs_compiled_into_the_binary() {
    let mut e = Engine::new();
    e.load_model(include_str!("../../../model/core.def")).unwrap();
    e.load_model(include_str!("../../../model/track.def")).unwrap();
    e.load_def(include_str!("../../../packs/cot-xml/pack.def")).unwrap();
    e.load_def(include_str!("../../../packs/geojson/pack.def")).unwrap();
    assert_eq!(e.formats(), ["cot-xml", "geojson"]);
    assert_eq!(e.convert("cot-xml", "geojson", COT).unwrap(), GEOJSON);
}
