//! ASN.1 unaligned PER (engine-spec 0.19): checks derived by hand from the
//! section, beside the conformance vectors.

use goat_transformers::{Engine, Entity, Value};
use std::path::Path;

fn engine() -> Engine {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).unwrap();
    e.load_def(&std::fs::read_to_string(root.join("packs/conformance-uper/pack.def")).unwrap()).unwrap();
    e
}

const HEAD: &str = "format p\nversion 0.19.0\ndistribution public\nsource \"probe\"\nuses probe\nwire bits\nlayout sequential\nbit_order msb\n";

fn load(body: &str) -> Result<Engine, String> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).unwrap();
    e.load_def(&format!("{}{}", HEAD, body)).map(|_| e).map_err(|x| x.msg)
}

/// Every key absent (ruling 1): n 8 bits, lat 31, x 1+3, y `01 00`, z `01 00`,
/// w 1+2, qty 3, c1 1, label 3 + one character 0 in 7, s1 3, s2 `00`, ext 1
/// and presence 2, choice 1+1 and `a` 2, items 2, names `00`: 120 bits.
#[test]
fn absent_keys_write_ruling_1() {
    let e = engine();
    assert_eq!(e.encode("conformance-uper", &Entity::default()).unwrap(), "000000000000200020000000000000");
}

#[test]
fn a_populated_message_round_trips() {
    let e = engine();
    let mut ent = Entity::default();
    let f = &mut ent.fields;
    f.insert("probe.n".into(), Value::I64(255));
    f.insert("lat".into(), Value::F64(-12.5));
    f.insert("probe.x".into(), Value::I64(300)); // outside the root: the extension form
    f.insert("probe.y".into(), Value::I64(1000));
    f.insert("probe.z".into(), Value::I64(-129));
    f.insert("probe.w".into(), Value::I64(70)); // an extension index, 67, in the long form
    f.insert("probe.qty".into(), Value::I64(4));
    f.insert("probe.c1".into(), Value::I64(1));
    f.insert("probe.label".into(), Value::Str("AB\u{1}".into()));
    f.insert("probe.s1".into(), Value::Str("beef".into()));
    f.insert("probe.s2".into(), Value::Str("h\u{e9}".into()));
    f.insert("probe.val".into(), Value::I64(1000));
    f.insert("probe.tag".into(), Value::Str("xy".into()));
    let hex = e.encode("conformance-uper", &ent).unwrap();
    let back = e.decode("conformance-uper", &hex).unwrap();
    for (k, v) in &ent.fields {
        assert_eq!(back.fields.get(k), Some(v), "{} in {}", k, hex);
    }
    assert!(!back.fields.contains_key("probe.c2"));
    assert!(!back.fields.contains_key("probe.a"));
    assert_eq!(back.lists.get("probe.items").map(|l| l.len()), Some(0));
}

/// `n` 8 bits, then the extension bit of `x` 1 and a length of 2 octets.
#[test]
fn hand_derived_fields() {
    let e = load("encoding uper\nfield probe.n int:0:255 uint\nfield probe.x int:0:7:ext uint\n").unwrap();
    let mut ent = Entity::default();
    ent.fields.insert("probe.n".into(), Value::I64(7));
    ent.fields.insert("probe.x".into(), Value::I64(300));
    // 00000111 1 00000010 00000001 00101100 -> 07 81 00 96 00
    assert_eq!(e.encode("p", &ent).unwrap(), "0781009600");
    ent.fields.insert("probe.x".into(), Value::I64(5));
    // 00000111 0 101 -> 07 50
    assert_eq!(e.encode("p", &ent).unwrap(), "0750");
    // a non-minimal extension form inside the root is accepted (ruling 7)
    let d = e.decode("p", "078080").unwrap_err();
    assert!(d.msg.starts_with("malformed-wire"), "{}", d.msg);
    let d = e.decode("p", "07808280").unwrap();
    assert_eq!(d.fields.get("probe.x"), Some(&Value::I64(5)));
}

/// A constrained whole number whose range is not 2^k - 1, read above `ub`.
#[test]
fn value_above_ub_is_malformed() {
    let e = load("encoding uper\nfield probe.n int:0:4 uint\n").unwrap();
    assert!(e.decode("p", "a0").unwrap_err().msg.starts_with("malformed-wire"));
    assert_eq!(e.decode("p", "80").unwrap().fields.get("probe.n"), Some(&Value::I64(4)));
}

#[test]
fn an_empty_encoding_is_one_octet() {
    let e = load("encoding uper\nfield probe.n int:3:3 uint\n").unwrap();
    assert_eq!(e.encode("p", &Entity::default()).unwrap(), "00");
    assert_eq!(e.decode("p", "").unwrap().fields.get("probe.n"), Some(&Value::I64(3)));
}

#[test]
fn integers_beyond_64_bits() {
    let e = load("encoding uper\nfield probe.n int:: twos\n").unwrap();
    assert!(e.decode("p", "09000000000000000000").unwrap_err().msg.starts_with("transform-decode"));
    assert!(e.decode("p", "00").unwrap_err().msg.starts_with("malformed-wire"));
    assert!(e.decode("p", "0900").unwrap_err().msg.starts_with("malformed-wire"));
    assert!(e.decode("p", "c0").unwrap_err().msg.starts_with("malformed-wire"));
    let e = load("encoding uper\nfield probe.n int:-9223372036854775808:9223372036854775807 twos\n").unwrap();
    let mut ent = Entity::default();
    ent.fields.insert("probe.n".into(), Value::I64(i64::MAX));
    assert_eq!(e.encode("p", &ent).unwrap(), "ffffffffffffffff");
    let e = load("encoding uper\nfield probe.n int:1: uint\n").unwrap();
    // 2^64 - 1 + 1 does not fit
    assert!(e.decode("p", "08ffffffffffffffff").unwrap_err().msg.starts_with("transform-decode"));
}

#[test]
fn extension_additions_are_skipped() {
    let e = load("encoding uper\next\n  field probe.n int:0:15 uint\nend\nfield probe.x 4 uint\n").unwrap();
    // 1 0101 | 0 000001 (m = 2) | 1 0 | 00000001 0xab | 1111
    // 10101000 00011000 00000110 10101111 11
    let d = e.decode("p", "a81806afc0").unwrap();
    assert_eq!(d.fields.get("probe.n"), Some(&Value::I64(5)));
    assert_eq!(d.fields.get("probe.x"), Some(&Value::I64(15)));
}

#[test]
fn load_errors() {
    let cases = [
        "encoding uper\nencoding uper\n",
        "encoding sometimes\n",
        "field probe.n int:0:7 uint\n",
        "ext\nend\n",
        "encoding uper\nfield probe.n int:01:7 uint\n",
        "encoding uper\nfield probe.n int:-0:7 uint\n",
        "encoding uper\nfield probe.n int:7:0 uint\n",
        "encoding uper\nfield probe.n int:0:7 f32\n",
        "encoding uper\nfield probe.label chars:0:8 ascii trim\n",
        "encoding uper\nfield probe.n enum:0 uint\n",
        "encoding uper\nchoice 2\nfield probe.n 1 uint\nalt 0\nend\n",
        "encoding uper\nchoice 2\nalt 0\nalt 0\nend\n",
        "encoding uper\nchoice 2\nalt 2\nend\n",
        "encoding uper\nalt 0\n",
        "encoding uper\next\nfield probe.n 1 uint\npresence p 1\nif p.1\nend\nend\n",
        "encoding uper\ngroup probe.items size 3 2\nend\n",
        "group probe.items size\nend\n",
        "encoding uper\narmor sixbit\n",
        "encoding uper\nwhen 1:0:1 1\n",
        "encoding uper\next\nencoding uper\nend\n",
    ];
    for c in cases {
        match load(c) {
            Ok(_) => panic!("loaded: {:?}", c),
            Err(m) => assert!(m.starts_with("bad-directive"), "{:?}: {}", c, m),
        }
    }
    let lsb = "format p\nversion 0\ndistribution public\nsource \"s\"\nwire bits\nlayout sequential\nbit_order lsb\nencoding uper\n";
    let mut e = Engine::new();
    e.load_model_dir(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../model")).unwrap();
    assert!(e.load_def(lsb).unwrap_err().msg.starts_with("bad-directive"));
    let fixed = "format p\nversion 0\ndistribution public\nsource \"s\"\nwire bits\nword_bytes 1\nencoding uper\n";
    assert!(e.load_def(fixed).unwrap_err().msg.starts_with("bad-directive"));
    let fixed_ext = "format p\nversion 0\ndistribution public\nsource \"s\"\nwire bits\nword_bytes 1\next\nend\n";
    assert!(e.load_def(fixed_ext).unwrap_err().msg.starts_with("bad-directive"));
}

/// Ruling 18 of 0.19.
#[test]
fn ruling_18() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).unwrap();
    let json = "format j\nversion 0\ndistribution public\nsource \"s\"\nuses probe\nwire json\nencoding none\nfield probe.n n int\n";
    assert!(e.load_def(json).unwrap_err().msg.starts_with("bad-directive"));
    let fixed = "format f\nversion 0\ndistribution public\nsource \"s\"\nuses probe\nwire bits\nword_bytes 1\nencoding none\nfield probe.n 0:0:8 uint\n";
    e.load_def(fixed).unwrap();
    let e = load("encoding uper\nfield probe.s2 octets: hex\nfield probe.w enum:3:ext uint\next\nend\nchoice 2\n  alt 0\n  alt 1\n    field probe.n int:0:3 uint\nend\n").unwrap();
    // absent octets: a length of 0; ext bit 0; choice index 1 then n = 2
    let mut ent = Entity::default();
    ent.fields.insert("probe.n".into(), Value::I64(2));
    // 00000000 000 0 1 10 -> 00 0c
    assert_eq!(e.encode("p", &ent).unwrap(), "000c");
    ent.fields.insert("probe.w".into(), Value::I64(-1));
    assert!(e.encode("p", &ent).unwrap_err().msg.starts_with("transform-encode"));
}
