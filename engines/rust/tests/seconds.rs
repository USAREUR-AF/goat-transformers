//! The line checks of `iso8601_s` (engine-spec 0.26, ruling 1): it loads on the
//! xml, geojson, json and text wires, is `bad-directive` on another wire and
//! with a parameter, and yields `int`, so another key type is
//! `key-type-mismatch`.
#![cfg(all(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]

use goat_transformers::Engine;

const CORE: &str =
    "module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\nkey lat float deg\nkey time_ms int ms\n";

fn load(body: &str) -> Result<(), String> {
    let mut e = Engine::new();
    e.load_model(CORE).unwrap();
    let head = "format probe\nversion 0.26.0\ndistribution public\nsource \"probe\"\n";
    e.load_def(&format!("{}{}", head, body)).map(|_| ()).map_err(|x| x.msg)
}

fn refused(body: &str, code: &str) {
    match load(body) {
        Ok(()) => panic!("loaded: {:?}", body),
        Err(m) => assert!(m.starts_with(code), "{:?}: {}", body, m),
    }
}

#[test]
fn valid_on_xml_geojson_json_and_text() {
    for body in [
        "wire xml\nroot e\nfield time_ms @t iso8601_s\n",
        "wire geojson\nfield time_ms properties.t iso8601_s\n",
        "wire json\nfield time_ms t iso8601_s\n",
        "wire text\nfield time_ms 0 iso8601_s\n",
    ] {
        load(body).unwrap_or_else(|m| panic!("{:?}: {}", body, m));
    }
}

#[test]
fn another_wire_is_bad_directive() {
    refused("wire bits\nword_bytes 1\nfield time_ms 0:0:8 iso8601_s\n", "bad-directive");
    refused("wire protobuf\nfield time_ms 1 iso8601_s\n", "bad-directive");
}

#[test]
fn a_parameter_is_bad_directive() {
    refused("wire xml\nroot e\nfield time_ms @t iso8601_s:3\n", "bad-directive");
    refused("wire json\nfield time_ms t iso8601_s:0\n", "bad-directive");
}

#[test]
fn another_key_type_is_key_type_mismatch() {
    refused("wire xml\nroot e\nfield uid @t iso8601_s\n", "key-type-mismatch");
    refused("wire json\nfield lat t iso8601_s\n", "key-type-mismatch");
}

#[test]
fn encode_drops_the_milliseconds() {
    use goat_transformers::ms_to_iso8601_s;
    assert_eq!(ms_to_iso8601_s(999).unwrap(), "1970-01-01T00:00:00Z");
    assert_eq!(ms_to_iso8601_s(-1).unwrap(), "1969-12-31T23:59:59Z");
    assert_eq!(ms_to_iso8601_s(1_709_210_096_789).unwrap(), "2024-02-29T12:34:56Z");
    assert_eq!(ms_to_iso8601_s(253_402_300_799_999).unwrap(), "9999-12-31T23:59:59Z");
    assert!(ms_to_iso8601_s(253_402_300_800_000).is_err());
    assert_eq!(ms_to_iso8601_s(-62_135_596_800_000).unwrap(), "0001-01-01T00:00:00Z");
    assert!(ms_to_iso8601_s(-62_135_596_800_001).is_err());
}
