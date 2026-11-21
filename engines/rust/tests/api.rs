//! Behaviour a conversion vector cannot reach, because `convert` never hands
//! `encode` an entity whose kind is foreign to the pack: ruling 24 of 0.5, and
//! the 0.6 steps on their own (`fill`, `complete`), the rulings of 0.6 that are
//! about the API or about the last bits of a float (rulings 1 and 9), and the
//! 0.7 list API (`Entity.lists`, `model_keys`, `capability`), and the 0.8 item
//! kind (`Item.kind`).
// The packs this test loads need these wires (engine-spec 0.24).
#![cfg(all(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]

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
        "conformance-seq-kinds",
        "conformance-seq-json",
        "conformance-seq-nested",
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

/// Engine-spec 0.8, items by kind: an item records the kind it selected, and
/// encode selects by it. A kind of another format, and a kind of this format
/// that the group does not have, are ignored and the item selects by
/// `requires` (ruling 26 of 0.8).
#[test]
fn item_kind_is_recorded_and_selects_on_encode() {
    let e = engine();
    // n 1, two recs: (x 5, alt, y 258) (x 7, empty)
    let input = "010253010270";
    let mut ent = e.decode("conformance-seq-kinds", input).unwrap();
    assert_eq!(ent.kind, None, "the message has no kinds");
    let kinds: Vec<Option<(String, String)>> = ent.lists["probe.recs"].iter().map(|i| i.kind.clone()).collect();
    let k = |name: &str| Some(("conformance-seq-kinds".to_string(), name.to_string()));
    assert_eq!(kinds, vec![k("alt"), k("empty")]);
    assert_eq!(e.encode("conformance-seq-kinds", &ent).unwrap(), input);
    // no kind recorded: `point` is the first kind whose `requires` (probe.y) the item satisfies
    let recs = ent.lists.get_mut("probe.recs").unwrap();
    recs[0].kind = None;
    recs[0].fields.insert("probe.y".to_string(), Value::I64(34));
    assert_eq!(e.encode("conformance-seq-kinds", &ent).unwrap(), "0102512270");
    // a kind of another format is ignored
    ent.lists.get_mut("probe.recs").unwrap()[0].kind = Some(("geojson".to_string(), "alt".to_string()));
    assert_eq!(e.encode("conformance-seq-kinds", &ent).unwrap(), "0102512270");
    // a kind of this format that the group does not have: by `requires` too
    ent.lists.get_mut("probe.recs").unwrap()[0].kind = k("nosuchkind");
    assert_eq!(e.encode("conformance-seq-kinds", &ent).unwrap(), "0102512270");
    // no kind recorded and the required keys of no kind but `empty`, which requires none
    let recs = ent.lists.get_mut("probe.recs").unwrap();
    recs[0].kind = k("nosuchkind");
    recs[0].fields.remove("probe.y");
    assert_eq!(e.encode("conformance-seq-kinds", &ent).unwrap(), "01025070");
}

/// `Engine::load_pack_dir_only` loads the named packs and no other; a name
/// with no pack is an error.
#[test]
fn load_pack_dir_only_loads_the_named_packs() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).unwrap();
    e.load_pack_dir_only(&root.join("packs"), &["geojson", "cot-xml", "geojson"]).unwrap();
    assert_eq!(e.formats(), vec!["cot-xml".to_string(), "geojson".to_string()]);
    assert!(e.load_pack_dir_only(&root.join("packs"), &["no-such-pack"]).is_err());
    assert!(e.load_pack_dir_only(&root.join("packs"), &["../packs/geojson"]).is_err());
}

/// Ruling 29 of 0.8, the order of checks for a module, on the API:
/// `distribution-refused` comes before `unknown-module`, and `Module::parse`
/// alone, which has no engine and so no limit, reports `unknown-module`.
#[test]
fn module_checks_run_in_the_order_of_ruling_29() {
    let text = "module m\nversion 1\ndistribution controlled\nsource \"s\"\nuses nosuch\nkey k int -\n";
    let mut e = Engine::new();
    e.set_max_distribution(goat_transformers::Distribution::Public);
    let err = e.load_model(text).unwrap_err();
    assert!(err.msg.starts_with("distribution-refused:"), "{}", err.msg);
    let err = goat_transformers::Module::parse(text).unwrap_err();
    assert!(err.msg.starts_with("unknown-module:"), "{}", err.msg);
}

/// `model_keys` and `capability` of a sequential pack: keys inside `if`,
/// `chain` and `length` blocks, lists and item keys, in first appearance order.
#[test]
fn model_keys_of_a_sequential_pack() {
    let e = engine();
    assert_eq!(
        e.model_keys("conformance-seq-nested"),
        vec![
            "probe.n",
            "probe.items[]",
            "probe.items[].probe.qty",
            "probe.items[].probe.x",
            "probe.items[].probe.y",
            "probe.items[].probe.val",
            "probe.nums[]",
            "probe.nums[].probe.val",
        ]
    );
    assert_eq!(
        e.model_keys("conformance-seq-kinds"),
        vec!["probe.n", "probe.recs[]", "probe.recs[].probe.x", "probe.recs[].probe.y", "probe.recs[].probe.label"]
    );
    let c = e.capability("conformance-seq-kinds", "conformance-seq-json");
    assert_eq!(c.grade, Grade::Full);
}

/// Engine-spec 0.8, model additions: the directory loader loads each module
/// after the modules it uses. `aaa` uses `mmm`, which uses `zzz`; in file-name
/// order `aaa` would be first and fail with `unknown-module`. A cycle of
/// `uses` lines is `bad-directive`. A load vector lists its modules in order
/// and cannot express a directory.
#[test]
fn directory_loader_loads_a_module_after_the_modules_it_uses() {
    let dir = std::env::temp_dir().join(format!("goat-xf-uses-order-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let head = "version 0.1.0\ndistribution public\nsource \"probe\"\n";
    let module = |name: &str, uses: &str, from: &str| {
        format!("module {n}\n{h}uses {u}\nkey v int -\nderive {n}.v copy {f}.v\n", n = name, h = head, u = uses, f = from)
    };
    std::fs::write(dir.join("core.def"), format!("module core\n{}key uid string -\n", head)).unwrap();
    std::fs::write(dir.join("aaa.def"), module("aaa", "mmm", "mmm")).unwrap();
    std::fs::write(dir.join("mmm.def"), module("mmm", "zzz", "zzz")).unwrap();
    std::fs::write(dir.join("zzz.def"), format!("module zzz\n{}key v int -\n", head)).unwrap();
    let mut e = Engine::new();
    let loaded = e.load_model_dir(&dir);
    let mut alone = Engine::new();
    let first = alone.load_model(&std::fs::read_to_string(dir.join("aaa.def")).unwrap());
    // the derivations cross the modules: zzz.v sets mmm.v, which sets aaa.v
    let mut ent = Entity::default();
    ent.fields.insert("zzz.v".to_string(), Value::I64(4));
    e.complete(&mut ent);
    // a cycle: zzz now uses aaa
    std::fs::write(dir.join("zzz.def"), module("zzz", "aaa", "aaa")).unwrap();
    let cycle = Engine::new().load_model_dir(&dir);
    let _ = std::fs::remove_dir_all(&dir);
    loaded.unwrap();
    assert_eq!(e.modules(), vec!["aaa", "core", "mmm", "zzz"]);
    assert!(first.unwrap_err().msg.starts_with("unknown-module:"));
    assert_eq!(ent.fields.get("aaa.v"), Some(&Value::I64(4)));
    assert!(cycle.unwrap_err().msg.starts_with("bad-directive:"));
}

/// Ruling 5 of 0.11: a format that is not loaded is `unknown-format` for
/// `decode`, `encode`, `model_keys` and the capability report; `convert`
/// checks `from`, then `to`, before it reads the input.
#[test]
fn a_format_that_is_not_loaded_is_unknown_format() {
    let e = engine();
    let kind = |r: Result<String, goat_transformers::Error>| r.unwrap_err().msg.split(':').next().unwrap().to_string();
    assert_eq!(kind(e.decode("no-such-format", "x").map(|_| String::new())), "unknown-format");
    assert_eq!(kind(e.encode("no-such-format", &Entity::default())), "unknown-format");
    assert_eq!(kind(e.try_model_keys("no-such-format").map(|_| String::new())), "unknown-format");
    assert_eq!(kind(e.try_capability("cot-xml", "no-such-format").map(|_| String::new())), "unknown-format");
    assert_eq!(kind(e.try_capability("no-such-format", "cot-xml").map(|_| String::new())), "unknown-format");
    // the input is not read: a document cut short is not `malformed-wire` here
    assert_eq!(kind(e.convert("cot-xml", "no-such-format", "<event")), "unknown-format");
}

/// Ruling 7 of 0.11: the limit on list items is an engine option; 0 refuses
/// any item, and `encode` of an entity a program built is not limited.
#[test]
fn the_limit_on_list_items_is_an_engine_option() {
    let mut e = engine();
    let input = r#"{"id":"u","items":[{"name":"aa"},{"name":"bb"}],"names":[]}"#;
    assert_eq!(e.max_items(), goat_transformers::DEFAULT_MAX_ITEMS);
    let ent = e.decode("conformance-groups-json", input).unwrap();
    e.set_max_items(1);
    let err = e.decode("conformance-groups-json", input).unwrap_err();
    assert!(err.msg.starts_with("malformed-wire:"), "{}", err.msg);
    assert!(e.decode_limited("conformance-groups-json", input, 2).is_ok());
    e.set_max_items(0);
    assert!(e.encode("conformance-groups-json", &ent).is_ok());
}

/// Ruling 5b of 0.11: the values of an `absent` option are a line check, so
/// they are reported before an unknown directive on a later line; a bit
/// length against its transform is checked after the file.
#[test]
fn absent_values_are_a_line_check() {
    let head = "format probe\nversion 0.11.0\ndistribution public\nsource \"probe\"\nwire bits\nword_bytes 1\n";
    let load = |body: &str| {
        let mut e = Engine::new();
        e.load_model("module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey time_ms int ms\n").unwrap();
        e.load_def(&format!("{}{}", head, body)).unwrap_err().msg
    };
    assert!(load("field time_ms 0:0:8 uint absent +7\nbogus 1\n").starts_with("bad-directive:"));
    assert!(load("field time_ms 0:0:65 uint absent 7\nbogus 1\n").starts_with("unknown-directive:"));
}
