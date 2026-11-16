//! Behaviour a conversion vector cannot reach, because `convert` never hands
//! `encode` an entity whose kind is foreign to the pack: ruling 24 of 0.5, and
//! the 0.6 steps on their own (`fill`, `complete`), the rulings of 0.6 that are
//! about the API or about the last bits of a float (rulings 1 and 9), and the
//! 0.7 list API (`Entity.lists`, `model_keys`, `capability`).

use goat_transformers::{Engine, Entity, Grade, Value};
use std::path::Path;

fn engine() -> Engine {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).unwrap();
    for pack in [
        "canonical-track-v2",
        "cot-xml",
        "demo-kinds-protobuf",
        "geojson",
        "conformance-groups-json",
        "conformance-groups-xml",
        "conformance-groups-bits",
        "conformance-groups-bits-msb",
        "conformance-groups-kinds",
    ] {
        e.load_def(&std::fs::read_to_string(root.join("packs").join(pack).join("pack.def")).unwrap()).unwrap();
    }
    e
}

/// Ruling 24 of 0.5: `Entity.kind` naming this format and a kind the pack does
/// not have is `no-kind`.
#[test]
fn entity_kind_the_pack_does_not_have_is_no_kind() {
    let e = engine();
    // field 1 "u", field 3 = 1: kind `status`
    let mut ent = e.decode("demo-kinds-protobuf", "0a01751801").unwrap();
    assert_eq!(ent.kind, Some(("demo-kinds-protobuf".to_string(), "status".to_string())));
    ent.kind = Some(("demo-kinds-protobuf".to_string(), "nosuchkind".to_string()));
    let err = e.encode("demo-kinds-protobuf", &ent).unwrap_err();
    assert!(err.msg.starts_with("no-kind:"), "{}", err.msg);
    // a kind naming another format is ignored: the kind is chosen by `requires`
    ent.kind = Some(("geojson".to_string(), "nosuchkind".to_string()));
    assert_eq!(e.encode("demo-kinds-protobuf", &ent).unwrap(), "0a01751801");
}

/// `decode` alone does not derive; `complete` does, and sets only absent keys.
#[test]
fn complete_derives_and_decode_does_not() {
    let e = engine();
    let input = r#"{"type":"Feature","geometry":{"type":"Point","coordinates":[2,1]},"properties":{"course":90,"speed_ms":10},"id":"g"}"#;
    let mut ent = e.decode("geojson", input).unwrap();
    assert!(!ent.fields.contains_key("track.vel_east_ms"));
    e.complete(&mut ent);
    match (ent.fields.get("track.vel_east_ms"), ent.fields.get("track.vel_north_ms")) {
        (Some(Value::F64(east)), Some(Value::F64(north))) => {
            assert!((east - 10.0).abs() < 1e-9 && north.abs() < 1e-9, "{} {}", east, north);
        }
        other => panic!("velocity not derived: {:?}", other),
    }
    assert_eq!(ent.fields.get("course"), Some(&Value::F64(90.0)));
    let again = ent.clone();
    e.complete(&mut ent);
    assert_eq!(ent, again, "a second `complete` changes nothing");
}

/// `fill` sets a context key the entity lacks and leaves one it has.
#[test]
fn fill_sets_only_absent_keys() {
    let e = engine();
    let mut ent = e.decode("cot-xml", r#"<event uid="a" how="m-g"><point lat="1" lon="2"/></event>"#).unwrap();
    let context = e
        .context_from_text(&[("how".to_string(), "h-e".to_string()), ("stale_ms".to_string(), "1000".to_string())])
        .unwrap();
    e.fill(&mut ent, &context).unwrap();
    assert_eq!(ent.fields.get("how"), Some(&Value::Str("m-g".to_string())));
    assert_eq!(ent.fields.get("stale_ms"), Some(&Value::I64(1000)));
    let bad = e.fill(&mut ent, &[("stale_ms".to_string(), Value::Str("soon".to_string()))]).unwrap_err();
    assert!(bad.msg.starts_with("key-type-mismatch:"), "{}", bad.msg);
}

/// Ruling 1 of 0.6: `bearing` turns radians into degrees by multiplying by
/// `180/pi`, the quotient computed first. A vector compares a derived float
/// within 1e-9 relative and cannot tell this from dividing by `pi/180`; here
/// the result is compared bit for bit. For east 2, north 1 the product is
/// 63.43494882292201 (0x404fb7ac672cf11e) and the quotient 63.434948822922;
/// for east 5, north 4 they are 51.34019174590991 (0x4049ab8b673386af) and
/// 51.340191745909905. Expected values computed outside the engine, with the
/// same platform `atan2`.
#[test]
fn bearing_multiplies_by_180_over_pi() {
    let e = engine();
    for (east, north, bits) in [(2.0, 1.0, 0x404fb7ac672cf11e_u64), (5.0, 4.0, 0x4049ab8b673386af_u64)] {
        let mut ent = Entity::default();
        ent.fields.insert("track.vel_east_ms".to_string(), Value::F64(east));
        ent.fields.insert("track.vel_north_ms".to_string(), Value::F64(north));
        e.complete(&mut ent);
        match ent.fields.get("course") {
            Some(Value::F64(course)) => assert_eq!(course.to_bits(), bits, "east {} north {}: {:?}", east, north, course),
            other => panic!("course not derived: {:?}", other),
        }
    }
}

/// Ruling 9 of 0.6: the directory loader loads `core.def` first whatever its
/// name sorts as. `aaa.def` sorts before `core.def` and derives from a `core`
/// key, which is `bad-directive` unless `core` is loaded already. A load
/// vector lists its modules in order and cannot express a directory.
#[test]
fn directory_loader_loads_core_first() {
    let dir = std::env::temp_dir().join(format!("goat-xf-core-first-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let head = "version 0.1.0\ndistribution public\nsource \"probe\"\n";
    std::fs::write(dir.join("aaa.def"), format!("module aaa\n{}key name string -\nderive aaa.name copy uid\n", head)).unwrap();
    std::fs::write(dir.join("core.def"), format!("module core\n{}key uid string -\n", head)).unwrap();
    std::fs::write(dir.join("zzz.def"), format!("module zzz\n{}key name string -\nderive zzz.name copy uid\n", head)).unwrap();
    let mut e = Engine::new();
    let loaded = e.load_model_dir(&dir);
    // in file-name order `aaa` fails: its derive names a key of a `core` not yet loaded
    let mut in_name_order = Engine::new();
    let first = in_name_order.load_model(&std::fs::read_to_string(dir.join("aaa.def")).unwrap());
    let _ = std::fs::remove_dir_all(&dir);
    loaded.unwrap();
    assert_eq!(e.modules(), vec!["aaa".to_string(), "core".to_string(), "zzz".to_string()]);
    assert!(first.unwrap_err().msg.starts_with("bad-directive:"));
    // ruling 4 of 0.4: no model directory loads no modules
    let mut none = Engine::new();
    none.load_model_dir(&dir.join("no-such-directory")).unwrap();
    assert!(none.modules().is_empty());
}

fn item(pairs: &[(&str, Value)]) -> Entity {
    let mut it = Entity::default();
    for (k, v) in pairs {
        it.fields.insert(k.to_string(), v.clone());
    }
    it
}

/// `Entity.lists`: decode fills it, a caller can build it, and a present,
/// empty list is distinct from an absent one.
#[test]
fn entity_lists_decode_build_and_encode() {
    let e = engine();
    let ent = e.decode("conformance-groups-json", r#"{"id":"u","items":[{"name":"aa","subs":[{"v":4}]}],"names":[]}"#).unwrap();
    let items = &ent.lists["probe.items"];
    assert_eq!(items.len(), 1);
    assert_eq!(items[0].fields.get("probe.label"), Some(&Value::Str("aa".to_string())));
    assert_eq!(items[0].lists["probe.subs"][0].fields.get("probe.val"), Some(&Value::I64(4)));
    // an item has no residue and no kind
    assert!(items[0].residue.is_empty() && items[0].kind.is_none());
    assert_eq!(ent.lists.get("probe.names").map(|l| l.len()), Some(0));
    assert!(!ent.lists.contains_key("probe.nums"));

    let mut built = Entity::default();
    built.fields.insert("uid".to_string(), Value::Str("u".to_string()));
    built.lists.insert(
        "probe.items".to_string(),
        vec![item(&[("probe.label", Value::Str("aa".to_string()))]), item(&[("probe.qty", Value::I64(7))])],
    );
    assert_eq!(
        e.encode("conformance-groups-xml", &built).unwrap(),
        r#"<msg id="u"><body><item name="aa" k="i"><qty>1</qty></item><item k="i"><qty>7</qty></item></body></msg>"#
    );
    // `requires <list>`: one item selects `listed`, an empty list does not
    assert_eq!(
        e.encode("conformance-groups-kinds", &built).unwrap(),
        r#"{"id":"u","shape":"listed","items":[{"name":"aa"},{}]}"#
    );
    built.lists.insert("probe.items".to_string(), Vec::new());
    assert_eq!(e.encode("conformance-groups-kinds", &built).unwrap(), r#"{"id":"u","shape":"bare"}"#);
    // ruling 5 of 0.7: an absent list under a fixed `count <n>` is `transform-encode`
    let mut bare = Entity::default();
    bare.fields.insert("probe.n".to_string(), Value::I64(5));
    let err = e.encode("conformance-groups-bits-msb", &bare).unwrap_err();
    assert!(err.msg.starts_with("transform-encode:"), "{}", err.msg);
    // with the fixed-count list present and the counted list absent: count 0, no item
    bare.lists.insert(
        "probe.nums".to_string(),
        vec![item(&[("probe.val", Value::I64(3))]), item(&[("probe.val", Value::I64(12))])],
    );
    assert_eq!(e.encode("conformance-groups-bits-msb", &bare).unwrap(), "143c");
}

/// `model_keys` lists a list as `<list>[]` and an item key as
/// `<list>[].<key>`, nested lists likewise, in first appearance order; the
/// capability of a conversion is computed over those names.
#[test]
fn model_keys_and_capability_list_lists() {
    let e = engine();
    assert_eq!(
        e.model_keys("conformance-groups-json"),
        [
            "uid",
            "probe.label",
            "probe.items[]",
            "probe.items[].probe.label",
            "probe.items[].probe.qty",
            "probe.items[].probe.ratio",
            "probe.items[].probe.subs[]",
            "probe.items[].probe.subs[].probe.tag",
            "probe.items[].probe.subs[].probe.val",
            "callsign",
            "probe.nums[]",
            "probe.nums[].probe.val",
            "probe.names[]",
            "probe.names[].probe.tag",
            "probe.ratios[]",
            "probe.ratios[].probe.ratio",
        ]
    );
    // a pack with kinds: common first, then each kind
    assert_eq!(
        e.model_keys("conformance-groups-kinds"),
        ["uid", "probe.names[]", "probe.names[].probe.tag", "probe.items[]", "probe.items[].probe.label"]
    );
    let c = e.capability("conformance-groups-bits", "conformance-groups-json");
    assert_eq!(c.grade, Grade::Full);
    assert!(c.carried.contains(&"probe.items[].probe.subs[].probe.val".to_string()));
    let c = e.capability("conformance-groups-json", "conformance-groups-bits");
    assert_eq!(c.grade, Grade::Partial);
    assert!(c.dropped.contains(&"probe.items[].probe.subs[].probe.tag".to_string()));
    assert!(c.dropped.contains(&"probe.names[]".to_string()));
}
