//! The `cdr` wire (engine-spec v0.43), with bytes built by hand from the
//! specification: alignment counted after the 4-byte header, `int64` on 8
//! under `cdr 1` and on 4 under `cdr 2`, strings, sequences and arrays with
//! and without a DHEADER, trailing padding and the option byte `p`, input in
//! the other byte order, kinds by `when <n>`, and the load checks.

use goat_transformers::{Engine, Entity, Value};
use std::path::Path;

fn root() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn header(format: &str, cdr: u8, repr: &str) -> String {
    format!(
        "format {}\nversion 0.0.1\ndistribution public\nsource \"engines/rust/tests/cdr.rs\"\nuses probe\nwire cdr\ncdr {}\nrepresentation {}\n",
        format, cdr, repr
    )
}

/// The probe packs, and small packs of this file.
fn engine() -> Engine {
    let mut e = Engine::new();
    e.load_model_dir(&root().join("model")).unwrap();
    for pack in ["conformance-cdr", "conformance-cdr2"] {
        e.load_def(&std::fs::read_to_string(root().join("packs").join(pack).join("pack.def")).unwrap()).unwrap();
    }
    for (name, v, repr, body) in [
        ("t-align1", 1, "0000", "field probe.y uint32\nfield probe.z int64\n"),
        ("t-align2", 2, "0006", "field probe.y uint32\nfield probe.z int64\n"),
        ("t-le", 1, "0001", "field probe.y uint32\nfield probe.z int64\nfield probe.n int16\n"),
        ("t-byte", 1, "0000", "field probe.x uint8\n"),
        ("t-str", 1, "0000", "field probe.s1 string\nfield probe.x uint8\n"),
        ("t-bool", 1, "0000", "field probe.w bool\n"),
        ("t-u64", 1, "0000", "field probe.n uint64\n"),
        ("t-f32", 1, "0000", "field probe.a float32\n"),
        (
            "t-seq1",
            1,
            "0000",
            "field probe.x uint8\ngroup probe.items seq\n  field probe.label string\n  field probe.qty uint16\nend\n",
        ),
        (
            "t-seq2",
            2,
            "0006",
            "field probe.x uint8\ngroup probe.items seq\n  field probe.label string\n  field probe.qty uint16\nend\n",
        ),
        ("t-strseq2", 2, "0006", "group probe.names seq\n  field probe.tag string\nend\n"),
        ("t-enumseq2", 2, "0006", "group probe.nums seq\n  field probe.val enum16\nend\n"),
        ("t-intseq2", 2, "0006", "group probe.nums seq\n  field probe.val int16\nend\n"),
        ("t-arr2", 2, "0006", "group probe.items array:2\n  field probe.qty uint8\n  const uint8 9\nend\n"),
        (
            "t-nested2",
            2,
            "0006",
            "group probe.items seq\n  field probe.qty uint8\n  group probe.subs seq\n    field probe.val int16\n  end\nend\n",
        ),
        ("t-default", 1, "0000", "field probe.n int32\nfield probe.s1 string\ndefault probe.n 17\n"),
        ("t-scale", 1, "0000", "field probe.a int16 uscale:0.5\nfield probe.scaled uint8 sscale:2:10\n"),
        ("t-via", 1, "0000", "field probe.s1 uint8 int via t\nmap t 1 one\nmap t 2 two\n"),
    ] {
        e.load_def(&format!("{}{}", header(name, v, repr), body)).unwrap_or_else(|err| panic!("{}: {}", name, err));
    }
    e
}

/// Hex text with the spaces of the layout taken out.
fn h(s: &str) -> String {
    s.split_whitespace().collect()
}

fn kind_of(msg: &str) -> &str {
    msg.split(':').next().unwrap_or("")
}

fn int(e: &Entity, k: &str) -> i64 {
    match e.fields.get(k) {
        Some(Value::I64(n)) => *n,
        other => panic!("{}: {:?}", k, other),
    }
}

fn float(e: &Entity, k: &str) -> f64 {
    match e.fields.get(k) {
        Some(Value::F64(x)) => *x,
        other => panic!("{}: {:?}", k, other),
    }
}

fn text(e: &Entity, k: &str) -> String {
    match e.fields.get(k) {
        Some(Value::Str(s)) => s.clone(),
        other => panic!("{}: {:?}", k, other),
    }
}

/// The probe message under `cdr 1`, big-endian. Offsets after the header.
fn probe1() -> String {
    h("00000000
       01 00 fffe 00000003
       0000000000000004
       3ff8000000000000
       00000003 616200 01
       00000005
       40000000
       0007 0000
       00000001 00000002 7800 0009
       00000002 0000000a fffffff6
       3f800000 40000000")
}

/// The same values under `cdr 2` (`representation 0006`): a DHEADER of 12
/// before the sequence of structs `items`, none before `nums` and `gains`.
fn probe2() -> String {
    h("00060000
       01 00 fffe 00000003
       0000000000000004
       3ff8000000000000
       00000003 616200 01
       00000005
       40000000
       0007 0000
       0000000c 00000001 00000002 7800 0009
       00000002 0000000a fffffff6
       3f800000 40000000")
}

fn check_probe(ent: &Entity, format: &str) {
    assert_eq!(ent.kind, Some((format.to_string(), "plain".to_string())));
    assert_eq!(int(ent, "probe.x"), 1);
    assert_eq!(int(ent, "probe.n"), -2);
    assert_eq!(int(ent, "probe.y"), 3);
    assert_eq!(int(ent, "probe.z"), 4);
    assert_eq!(float(ent, "probe.a"), 1.5);
    assert_eq!(text(ent, "uid"), "ab");
    assert_eq!(int(ent, "probe.w"), 1);
    assert_eq!(int(ent, "probe.c1"), 5);
    assert_eq!(float(ent, "lat"), 1073741824f64 * 90.0 / 2147483647.0);
    let items = &ent.lists["probe.items"];
    assert_eq!(items.len(), 1);
    assert_eq!(text(&items[0], "probe.label"), "x");
    assert_eq!(int(&items[0], "probe.qty"), 9);
    let nums: Vec<i64> = ent.lists["probe.nums"].iter().map(|i| int(i, "probe.val")).collect();
    assert_eq!(nums, vec![10, -10]);
    let gains: Vec<f64> = ent.lists["probe.gains"].iter().map(|i| float(i, "probe.ratio")).collect();
    assert_eq!(gains, vec![1.0, 2.0]);
}

#[test]
fn probe_message_under_cdr_1_and_cdr_2() {
    let e = engine();
    let ent = e.decode("conformance-cdr", &probe1()).unwrap();
    check_probe(&ent, "conformance-cdr");
    assert_eq!(e.encode("conformance-cdr", &ent).unwrap(), probe1());
    let ent2 = e.decode("conformance-cdr2", &probe2()).unwrap();
    check_probe(&ent2, "conformance-cdr2");
    assert_eq!(e.encode("conformance-cdr2", &ent2).unwrap(), probe2());
    // across the two versions
    assert_eq!(e.convert("conformance-cdr", "conformance-cdr2", &probe1()).unwrap(), probe2());
    assert_eq!(e.convert("conformance-cdr2", "conformance-cdr", &probe2()).unwrap(), probe1());
}

#[test]
fn int64_aligns_on_8_under_cdr_1_and_on_4_under_cdr_2() {
    let e = engine();
    let one = h("00000000 00000001 00000000 0000000000000002");
    let two = h("00060000 00000001 0000000000000002");
    let ent = e.decode("t-align1", &one).unwrap();
    assert_eq!((int(&ent, "probe.y"), int(&ent, "probe.z")), (1, 2));
    assert_eq!(e.encode("t-align1", &ent).unwrap(), one);
    assert_eq!(e.convert("t-align1", "t-align2", &one).unwrap(), two);
    assert_eq!(e.convert("t-align2", "t-align1", &two).unwrap(), one);
    // the padding is skipped whatever it holds
    let ent = e.decode("t-align1", &h("00000000 00000001 deadbeef 0000000000000002")).unwrap();
    assert_eq!(int(&ent, "probe.z"), 2);
    // cut inside the padding, inside the value
    for cut in [h("00000000 00000001 0000"), h("00000000 00000001 00000000 00000000")] {
        let m = e.decode("t-align1", &cut).unwrap_err().msg;
        assert_eq!(kind_of(&m), "malformed-wire", "{}", m);
    }
}

#[test]
fn byte_order_from_the_identifier() {
    let e = engine();
    // a pack whose identifier has the low bit set writes little-endian, and
    // pads after the int16: 2 bytes, so p is 2
    let le = h("00010002 01000000 00000000 0200000000000000 feff 0000");
    let be = h("00000002 00000001 00000000 0000000000000002 fffe 0000");
    for input in [&le, &be] {
        let ent = e.decode("t-le", input).unwrap();
        assert_eq!((int(&ent, "probe.y"), int(&ent, "probe.z"), int(&ent, "probe.n")), (1, 2, -2));
        assert_eq!(e.encode("t-le", &ent).unwrap(), le);
    }
    // a big-endian pack reads little-endian input
    let ent = e.decode("t-byte", "0001000307000000").unwrap();
    assert_eq!(int(&ent, "probe.x"), 7);
    // an identifier whose other bits differ
    for bad in ["0002000307000000", "0100000307000000", "000a000307"] {
        let m = e.decode("t-byte", bad).unwrap_err().msg;
        assert_eq!(kind_of(&m), "malformed-wire", "{}: {}", bad, m);
    }
}

#[test]
fn trailing_padding_and_p() {
    let e = engine();
    let mut ent = Entity::default();
    ent.fields.insert("probe.x".into(), Value::I64(5));
    assert_eq!(e.encode("t-byte", &ent).unwrap(), "0000000305000000");
    // decode never reads p; up to 3 zero bytes may follow the last member
    for ok in ["00000000 05", "00000003 05 00", "00000001 05 000000", "00000000 05000000"] {
        assert_eq!(int(&e.decode("t-byte", &h(ok)).unwrap(), "probe.x"), 5, "{}", ok);
    }
    // ruling 20: three zero bytes after a body already a multiple of 4
    let ent = e.decode("t-align2", &h("00060000 00000001 0000000000000002 000000")).unwrap();
    assert_eq!(int(&ent, "probe.z"), 2);
    for bad in ["00000003 05 00000000", "00000003 05 000001", "000000", "", "00000000"] {
        let m = e.decode("t-byte", &h(bad)).unwrap_err().msg;
        assert_eq!(kind_of(&m), "malformed-wire", "{}: {}", bad, m);
    }
    // an absent key writes zero bits
    assert_eq!(e.encode("t-byte", &Entity::default()).unwrap(), "0000000300000000");
}

#[test]
fn strings() {
    let e = engine();
    // "héllo": 6 bytes and the NUL, then a uint8 at offset 11, then p = 0
    let msg = h("00000000 00000007 68c3a96c6c6f00 2a");
    let ent = e.decode("t-str", &msg).unwrap();
    assert_eq!(text(&ent, "probe.s1"), "héllo");
    assert_eq!(int(&ent, "probe.x"), 42);
    assert_eq!(e.encode("t-str", &ent).unwrap(), msg);
    // an absent string writes the empty string: length 1, one zero byte
    assert_eq!(e.encode("t-str", &Entity::default()).unwrap(), h("00000002 00000001 00 00 0000"));
    let ent = e.decode("t-str", &h("00000000 00000001 00 07")).unwrap();
    assert_eq!(text(&ent, "probe.s1"), "");
    for (input, kind) in [
        ("00000000 00000000 07", "malformed-wire"),             // length 0
        ("00000000 00000002 4141 07", "malformed-wire"),        // no NUL last
        ("00000000 00000009 4100 07", "malformed-wire"),        // runs past the input
        ("00000000 ffffffff 00", "malformed-wire"),             // a huge length
        ("00000000 000000", "malformed-wire"),                  // cut in the length
        ("00000000 00000003 410000 07", "transform-decode"),    // a NUL before the last byte
        ("00000000 00000002 ff00 07", "transform-decode"),      // not UTF-8
    ] {
        let m = e.decode("t-str", &h(input)).unwrap_err().msg;
        assert_eq!(kind_of(&m), kind, "{}: {}", input, m);
    }
    let mut ent = Entity::default();
    ent.fields.insert("probe.s1".into(), Value::Str("a\u{0}b".into()));
    let m = e.encode("t-str", &ent).unwrap_err().msg;
    assert_eq!(kind_of(&m), "transform-encode", "{}", m);
}

fn items_entity(qtys: &[(&str, i64)]) -> Entity {
    let mut ent = Entity::default();
    ent.fields.insert("probe.x".into(), Value::I64(1));
    let items = qtys
        .iter()
        .map(|(l, q)| {
            let mut i = Entity::default();
            i.fields.insert("probe.label".into(), Value::Str(l.to_string()));
            i.fields.insert("probe.qty".into(), Value::I64(*q));
            i
        })
        .collect();
    ent.lists.insert("probe.items".into(), items);
    ent
}

#[test]
fn sequence_of_structs_with_and_without_a_dheader() {
    let e = engine();
    let ent = items_entity(&[("ab", 1), ("c", 2)]);
    // cdr 1: the count at 4, "ab" at 8..15, qty at 16, "c" at 20..25, qty at 26, p = 0
    let one = h("00000000 01000000 00000002 00000003 616200 00 0001 0000 00000002 6300 0002");
    assert_eq!(e.encode("t-seq1", &ent).unwrap(), one);
    // cdr 2: a DHEADER at 4 counting the count and both elements, 24 bytes
    let two = h("00060000 01000000 00000018 00000002 00000003 616200 00 0001 0000 00000002 6300 0002");
    assert_eq!(e.encode("t-seq2", &ent).unwrap(), two);
    for (f, msg) in [("t-seq1", &one), ("t-seq2", &two)] {
        let d = e.decode(f, msg).unwrap();
        assert_eq!(d.lists["probe.items"].len(), 2);
        assert_eq!(text(&d.lists["probe.items"][1], "probe.label"), "c");
        assert_eq!(int(&d.lists["probe.items"][1], "probe.qty"), 2);
    }
    // an absent list writes a count of 0 (with its DHEADER of 4 under cdr 2),
    // and a count of 0 decodes as a present, empty list
    let mut none = Entity::default();
    none.fields.insert("probe.x".into(), Value::I64(1));
    assert_eq!(e.encode("t-seq1", &none).unwrap(), h("00000000 01000000 00000000"));
    assert_eq!(e.encode("t-seq2", &none).unwrap(), h("00060000 01000000 00000004 00000000"));
    assert_eq!(e.decode("t-seq2", &h("00060000 01000000 00000004 00000000")).unwrap().lists["probe.items"].len(), 0);
    // a DHEADER that lies, short or long
    for lie in ["00000017", "00000019", "00000000", "ffffffff"] {
        let input = two.replacen("00000018", lie, 1);
        let m = e.decode("t-seq2", &input).unwrap_err().msg;
        assert_eq!(kind_of(&m), "malformed-wire", "{}: {}", lie, m);
    }
    // a count far beyond the bytes left
    for count in ["ffffffff", "00000100", "00000003"] {
        let input = one.replacen("00000002", count, 1);
        let m = e.decode("t-seq1", &input).unwrap_err().msg;
        assert_eq!(kind_of(&m), "malformed-wire", "{}: {}", count, m);
    }
    // every prefix of both messages is malformed, none panics
    for msg in [&one, &two] {
        for cut in (0..msg.len()).step_by(2) {
            let r = e.decode(if msg == &one { "t-seq1" } else { "t-seq2" }, &msg[..cut]);
            // a cut on a padding boundary can still be whole: only at the end
            if let Err(err) = r {
                assert_eq!(kind_of(&err.msg), "malformed-wire", "{}: {}", cut, err.msg);
            }
        }
    }
}

#[test]
fn which_collections_take_a_dheader() {
    let e = engine();
    // strings and enums are not primitive (ruling 8): a DHEADER
    let mut ent = Entity::default();
    let names = ["a", "bc"]
        .iter()
        .map(|s| {
            let mut i = Entity::default();
            i.fields.insert("probe.tag".into(), Value::Str(s.to_string()));
            i
        })
        .collect();
    ent.lists.insert("probe.names".into(), names);
    let msg = h("00060000 00000013 00000002 00000002 6100 0000 00000003 626300 00");
    assert_eq!(e.encode("t-strseq2", &ent).unwrap(), h("00060001 00000013 00000002 00000002 6100 0000 00000003 626300 00"));
    assert_eq!(e.decode("t-strseq2", &msg).unwrap().lists["probe.names"].len(), 2);
    let vals = |vs: &[i64]| -> Entity {
        let mut ent = Entity::default();
        ent.lists.insert(
            "probe.nums".into(),
            vs.iter()
                .map(|v| {
                    let mut i = Entity::default();
                    i.fields.insert("probe.val".into(), Value::I64(*v));
                    i
                })
                .collect(),
        );
        ent
    };
    assert_eq!(e.encode("t-enumseq2", &vals(&[1, -1])).unwrap(), h("00060000 00000008 00000002 0001 ffff"));
    // int16 is primitive: no DHEADER; trailing padding 2
    assert_eq!(e.encode("t-intseq2", &vals(&[1, -1])).unwrap(), h("00060000 00000002 0001 ffff"));
    assert_eq!(e.encode("t-intseq2", &vals(&[3])).unwrap(), h("00060002 00000001 0003 0000"));
    // an array of structs: a DHEADER, no count; a const in the body
    let mut arr = Entity::default();
    arr.lists.insert(
        "probe.items".into(),
        [4, 5]
            .iter()
            .map(|q| {
                let mut i = Entity::default();
                i.fields.insert("probe.qty".into(), Value::I64(*q));
                i
            })
            .collect(),
    );
    let a = h("00060000 00000004 0409 0509");
    assert_eq!(e.encode("t-arr2", &arr).unwrap(), a);
    let d = e.decode("t-arr2", &h("00060000 00000004 04ff 05ff")).unwrap();
    assert_eq!(int(&d.lists["probe.items"][1], "probe.qty"), 5);
    // an array of another length, or absent, is transform-encode
    arr.lists.get_mut("probe.items").unwrap().pop();
    assert_eq!(kind_of(&e.encode("t-arr2", &arr).unwrap_err().msg), "transform-encode");
    assert_eq!(kind_of(&e.encode("t-arr2", &Entity::default()).unwrap_err().msg), "transform-encode");
    // nested: the outer DHEADER covers the inner sequence of int16 (no DHEADER)
    let mut outer = Entity::default();
    let mut item = Entity::default();
    item.fields.insert("probe.qty".into(), Value::I64(7));
    item.lists.insert("probe.subs".into(), vec![vals(&[2]).lists["probe.nums"][0].clone()]);
    outer.lists.insert("probe.items".into(), vec![item]);
    // DHEADER at 0, count at 4, qty at 8, inner count at 12, val at 16: 14 bytes after the DHEADER
    let n = h("00060002 0000000e 00000001 07000000 00000001 0002 0000");
    assert_eq!(e.encode("t-nested2", &outer).unwrap(), n);
    let d = e.decode("t-nested2", &n).unwrap();
    assert_eq!(int(&d.lists["probe.items"][0].lists["probe.subs"][0], "probe.val"), 2);
}

#[test]
fn kinds_by_when_n() {
    let e = engine();
    // x = 2 selects `other`; c2 (uint64) follows `gains` at 76, aligned to 80
    let other = format!("{}{}", probe1().replacen("000000000100fffe", "000000000200fffe", 1), h("00000000 000000000000000b"));
    let ent = e.decode("conformance-cdr", &other).unwrap();
    assert_eq!(ent.kind, Some(("conformance-cdr".to_string(), "other".to_string())));
    assert_eq!(int(&ent, "probe.c2"), 11);
    assert_eq!(e.encode("conformance-cdr", &ent).unwrap(), other);
    // under cdr 2 the uint64 aligns on 4: right after `gains` at 80
    let other2 = format!("{}{}", probe2().replacen("000600000100fffe", "000600000200fffe", 1), h("000000000000000b"));
    // convert clears the kind across formats and `plain` has no `requires`:
    // the kind is named for the encode
    let mut ent2 = ent.clone();
    ent2.kind = Some(("conformance-cdr2".to_string(), "other".to_string()));
    assert_eq!(e.encode("conformance-cdr2", &ent2).unwrap(), other2);
    // x = 3: no kind
    let none = probe1().replacen("000000000100fffe", "000000000300fffe", 1);
    assert_eq!(kind_of(&e.decode("conformance-cdr", &none).unwrap_err().msg), "no-kind");
    // encode writes the `when` value over the field
    let mut ent = e.decode("conformance-cdr", &probe1()).unwrap();
    ent.fields.insert("probe.x".into(), Value::I64(200));
    assert_eq!(e.encode("conformance-cdr", &ent).unwrap(), probe1());
    // input ending inside the common lines
    assert_eq!(kind_of(&e.decode("conformance-cdr", &probe1()[..40]).unwrap_err().msg), "malformed-wire");
}

#[test]
fn ranges_and_values() {
    let e = engine();
    let one = |k: &str, v: Value| {
        let mut ent = Entity::default();
        ent.fields.insert(k.into(), v);
        ent
    };
    // bool: 0 or 1; another byte is transform-decode
    assert_eq!(int(&e.decode("t-bool", "0000000301000000").unwrap(), "probe.w"), 1);
    assert_eq!(kind_of(&e.decode("t-bool", "0000000302000000").unwrap_err().msg), "transform-decode");
    assert_eq!(kind_of(&e.encode("t-bool", &one("probe.w", Value::I64(2))).unwrap_err().msg), "transform-encode");
    // ruling 11: a structural failure wins over a transform-decode
    assert_eq!(kind_of(&e.decode("t-bool", "000000030200000001").unwrap_err().msg), "malformed-wire");
    // uint64: 0 to 2^63-1
    assert_eq!(int(&e.decode("t-u64", "000000007fffffffffffffff").unwrap(), "probe.n"), i64::MAX);
    assert_eq!(kind_of(&e.decode("t-u64", "000000008000000000000000").unwrap_err().msg), "transform-decode");
    assert_eq!(kind_of(&e.encode("t-u64", &one("probe.n", Value::I64(-1))).unwrap_err().msg), "transform-encode");
    // uint8 out of range
    assert_eq!(kind_of(&e.encode("t-byte", &one("probe.x", Value::I64(256))).unwrap_err().msg), "transform-encode");
    assert_eq!(kind_of(&e.encode("t-byte", &one("probe.x", Value::I64(-1))).unwrap_err().msg), "transform-encode");
    // float32: single range on encode, NaN and infinity on decode
    assert_eq!(e.encode("t-f32", &one("probe.a", Value::F64(-2.0))).unwrap(), "00000000c0000000");
    assert_eq!(kind_of(&e.encode("t-f32", &one("probe.a", Value::F64(1e39))).unwrap_err().msg), "transform-encode");
    for bad in ["000000007fc00000", "000000007f800000"] {
        assert_eq!(kind_of(&e.decode("t-f32", bad).unwrap_err().msg), "transform-decode");
    }
    // a default in scope; zero bits only when none applies
    assert_eq!(e.encode("t-default", &Entity::default()).unwrap(), h("00000003 00000011 00000001 00 000000"));
    // scales: read from the integer the type decodes, signed as the type says
    let ent = e.decode("t-scale", &h("00000001 fffe ff")).unwrap();
    assert_eq!(float(&ent, "probe.a"), -1.0);
    assert_eq!(float(&ent, "probe.scaled"), 255.0 * 2.0 + 10.0);
    assert_eq!(e.encode("t-scale", &ent).unwrap(), h("00000001 fffe ff 00"));
    let mut big = ent.clone();
    big.fields.insert("probe.scaled".into(), Value::F64(1000.0));
    assert_eq!(kind_of(&e.encode("t-scale", &big).unwrap_err().msg), "transform-encode");
    // a value table on a member
    let ent = e.decode("t-via", "0000000302000000").unwrap();
    assert_eq!(text(&ent, "probe.s1"), "two");
    assert_eq!(e.encode("t-via", &ent).unwrap(), "0000000302000000");
}

#[test]
fn item_limit_and_hostile_counts() {
    let mut e = engine();
    e.set_max_items(1);
    let ent = items_entity(&[("a", 1), ("b", 2)]);
    let two = e.encode("t-seq1", &ent).unwrap();
    assert_eq!(kind_of(&e.decode("t-seq1", &two).unwrap_err().msg), "malformed-wire");
    e.set_max_items(2);
    assert!(e.decode("t-seq1", &two).is_ok());
    // a huge count with no elements behind it
    for input in ["00000000 01000000 ffffffff", "00060000 01000000 ffffffff ffffffff", "00060000 01000000 00000008 7fffffff"] {
        for f in ["t-seq1", "t-seq2"] {
            if let Err(m) = e.decode(f, &h(input)) {
                assert_eq!(kind_of(&m.msg), "malformed-wire", "{} {}: {}", f, input, m.msg);
            }
        }
    }
}

/// The load error of a pack text: its kind.
fn load_kind(body: &str) -> String {
    let mut e = Engine::new();
    for m in ["core", "probe"] {
        e.load_model(&std::fs::read_to_string(root().join("model").join(format!("{}.def", m))).unwrap()).unwrap();
    }
    match e.load_def(body) {
        Ok(()) => "ok".to_string(),
        Err(err) => kind_of(&err.msg).to_string(),
    }
}

#[test]
fn load_checks() {
    let base = header("t-load", 1, "0000");
    let ok = format!("{}field probe.x uint8\n", base);
    assert_eq!(load_kind(&ok), "ok");
    let no_cdr = ok.replace("cdr 1\n", "");
    let no_repr = ok.replace("representation 0000\n", "");
    for (what, text, kind) in [
        ("no cdr", no_cdr.clone(), "bad-directive"),
        ("no representation", no_repr, "bad-directive"),
        ("cdr 3", ok.replace("cdr 1\n", "cdr 3\n"), "bad-directive"),
        ("upper-case hex", ok.replace("representation 0000", "representation 000A"), "bad-directive"),
        ("three digits", ok.replace("representation 0000", "representation 000"), "bad-directive"),
        ("cdr twice", format!("{}cdr 1\n", ok), "bad-directive"),
        ("cdr with two arguments", ok.replace("cdr 1\n", "cdr 1 2\n"), "bad-directive"),
        ("cdr on bits", format!("{}cdr 1\n", ok.replace("wire cdr\ncdr 1\nrepresentation 0000\n", "wire bits\nword_bytes 1\n").replace("uint8", "0:0:8 uint")), "bad-directive"),
        ("unknown type", format!("{}field probe.y uint128\n", base), "bad-directive"),
        ("unknown type, a later line", format!("{}field probe.y uint128\nbogus\n", base), "unknown-directive"),
        ("unknown transform", format!("{}field probe.y uint32 nosuch\nbogus\n", base), "unknown-transform"),
        ("float on int32", format!("{}field probe.a int32 float\n", base), "bad-directive"),
        ("sscale on enum32", format!("{}field probe.a enum32 sscale:2\n", base), "bad-directive"),
        ("uscale on octet", format!("{}field probe.a octet uscale:2\n", base), "ok"),
        ("the default named", format!("{}field probe.y uint32 int\nfield probe.w bool bool\nfield uid string string\n", base), "ok"),
        ("swap", format!("{}field probe.y uint32 swap\n", base), "bad-directive"),
        ("absent", format!("{}field probe.y uint32 int absent 0\n", base), "bad-directive"),
        ("stop", format!("{}field probe.y uint32 stop 0\n", base), "bad-directive"),
        ("an unknown option", format!("{}field probe.y uint32 int nosuch\nbogus\n", base), "bad-directive"),
        ("array:0", format!("{}group probe.nums array:0\n  field probe.val int8\nend\n", base), "bad-directive"),
        ("an empty group", format!("{}group probe.nums seq\n  default probe.val 1\nend\n", base), "bad-directive"),
        ("another shape", format!("{}group probe.nums list\n  field probe.val int8\nend\n", base), "bad-directive"),
        ("when 0", format!("{}kind a\nwhen 0 1\n", ok), "bad-directive"),
        ("when past the last line", format!("{}kind a\nwhen 2 1\n", ok), "bad-directive"),
        ("when on a string", format!("{}field uid string\nkind a\nwhen 2 1\n", ok), "bad-directive"),
        ("when on a float", format!("{}field probe.a float64\nkind a\nwhen 2 1\n", ok), "bad-directive"),
        ("when on a group", format!("{}group probe.nums seq\n  field probe.val int8\nend\nkind a\nwhen 2 1\n", ok), "bad-directive"),
        ("when on a const", format!("{}const uint16 7\nkind a\nwhen 2 7\n", ok), "ok"),
        ("when too large", format!("{}kind a\nwhen 1 256\n", ok), "bad-directive"),
        ("when list and range", format!("{}kind a\nwhen 1 1,3..5\n", ok), "ok"),
        ("when in a group", format!("{}group probe.nums seq\n  field probe.val int8\n  when 1 1\nend\nkind a\n", ok), "bad-directive"),
        ("when in a group, a later line", format!("{}group probe.nums seq\n  field probe.val int8\n  when 1 1\nend\nbogus\n", ok), "unknown-directive"),
        ("const too large", format!("{}const uint8 256\n", ok), "bad-directive"),
        ("const signed", format!("{}const int8 -1\n", ok), "bad-directive"),
        ("const string", format!("{}const string 1\n", ok), "bad-directive"),
        ("a field with no type", format!("{}field probe.y\n", base), "bad-directive"),
    ] {
        assert_eq!(load_kind(&text), kind, "{}", what);
    }
    // `cdr` and `representation` may stand before the `wire` line
    let before = ok.replace("wire cdr\ncdr 1\nrepresentation 0000\n", "cdr 1\nrepresentation 0000\nwire cdr\n");
    assert_eq!(load_kind(&before), "ok");
}
