//! The `cbor` wire (engine-spec 0.28) on byte strings built by hand from
//! RFC 8949: heads of every length, the core deterministic encoding of
//! 4.2.1 (key order, shortest floats), the depth limit, equal keys, UTF-8
//! across chunks, tags, residue and the `tag` directive. The conformance
//! vectors are derived elsewhere; these tests pin the engine's own reading.

use goat_transformers::{Engine, Entity, Value};
use std::path::Path;

const HEAD: &str = "format t\nversion 1\ndistribution public\nsource \"test\"\nuses probe\nwire cbor\n";

fn engine(body: &str) -> Engine {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).unwrap();
    e.load_def(&format!("{}{}", HEAD, body)).unwrap_or_else(|err| panic!("{}", err));
    e
}

fn load_error(body: &str) -> String {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).unwrap();
    match e.load_def(&format!("{}{}", HEAD, body)) {
        Ok(()) => "loaded".into(),
        Err(err) => err.msg.split(':').next().unwrap_or("").to_string(),
    }
}

fn kind_of(r: Result<impl std::fmt::Debug, goat_transformers::Error>) -> String {
    match r {
        Ok(v) => format!("ok {:?}", v),
        Err(e) => e.msg.split(':').next().unwrap_or("").to_string(),
    }
}

fn entity(fields: &[(&str, Value)]) -> Entity {
    let mut ent = Entity::default();
    for (k, v) in fields {
        ent.fields.insert(k.to_string(), v.clone());
    }
    ent
}

#[test]
fn a_small_map_and_heads_of_every_length() {
    let e = engine("field probe.n 1 int\n");
    // {1: 5}, then the key and the value in longer heads than they need
    for input in ["a10105", "a1180118 05", "a119000119 0005", "a11a000000011b0000000000000005", "bf0105ff"] {
        let ent = e.decode("t", input).unwrap();
        assert_eq!(ent.fields.get("probe.n"), Some(&Value::I64(5)), "{}", input);
        assert_eq!(e.encode("t", &ent).unwrap(), "a10105", "{}", input);
    }
    // negative integers: -1 is 20, -500 is 3901f3
    assert_eq!(e.decode("t", "a10120").unwrap().fields.get("probe.n"), Some(&Value::I64(-1)));
    assert_eq!(e.encode("t", &entity(&[("probe.n", Value::I64(-500))])).unwrap(), "a1013901f3");
}

#[test]
fn members_are_written_in_the_bytewise_order_of_their_encoded_keys() {
    // keys 1 (01), 10 (0a), 100 (1864), -1 (20), "z" (617a), "aa" (626161)
    let e = engine(
        "field probe.s1 aa text\nfield probe.n -1 int\nfield probe.k0 100 int\nfield probe.s2 z text\nfield probe.k1 10 int\nfield uid 1 text\n",
    );
    let ent = entity(&[
        ("probe.s1", Value::Str("A".into())),
        ("probe.n", Value::I64(0)),
        ("probe.k0", Value::I64(0)),
        ("probe.s2", Value::Str("Z".into())),
        ("probe.k1", Value::I64(0)),
        ("uid", Value::Str("u".into())),
    ]);
    assert_eq!(e.encode("t", &ent).unwrap(), "a60161750a001864002000617a615a6261616141");
}

#[test]
fn floats_are_written_at_the_shortest_width_that_holds_them() {
    let e = engine("field probe.a 1 float\n");
    let enc = |x: f64| e.encode("t", &entity(&[("probe.a", Value::F64(x))])).unwrap();
    assert_eq!(enc(2f64.powi(-24)), "a101f90001");
    assert_eq!(enc(-0.0), "a101f98000");
    assert_eq!(enc(1.5), "a101f93e00");
    assert_eq!(enc(100000.0), "a101fa47c35000");
    assert_eq!(enc(65504.0), "a101f97bff");
    assert_eq!(enc(0.1), "a101fb3fb999999999999a");
    // an integer item is read as its value, and written back as a float
    let ent = e.decode("t", "a10102").unwrap();
    assert_eq!(ent.fields.get("probe.a"), Some(&Value::F64(2.0)));
    assert_eq!(e.encode("t", &ent).unwrap(), "a101f94000");
    // 2^64-1 to the nearest double, ties to even: 2^64
    assert_eq!(e.decode("t", "a1011bffffffffffffffff").unwrap().fields.get("probe.a"), Some(&Value::F64(18446744073709551616.0)));
    // the same value in every width reads the same
    for input in ["a101f93e00", "a101fa3fc00000", "a101fb3ff8000000000000"] {
        assert_eq!(e.decode("t", input).unwrap().fields.get("probe.a"), Some(&Value::F64(1.5)));
    }
    // a NaN and an infinity are refused; `int` refuses a float item
    assert_eq!(kind_of(e.decode("t", "a101f97e00")), "transform-decode");
    assert_eq!(kind_of(e.decode("t", "a101f97c00")), "transform-decode");
    let i = engine("field probe.n 1 int\n");
    assert_eq!(kind_of(i.decode("t", "a101f93c00")), "transform-decode");
}

#[test]
fn integers_at_the_ends_of_their_ranges() {
    let e = engine("field probe.n 1 int\nfield probe.val 2 uint\n");
    // int: -2^63 reads, -2^63-1 does not; uint: 2^63-1 reads, 2^63 does not
    assert_eq!(e.decode("t", "a1013b7fffffffffffffff").unwrap().fields.get("probe.n"), Some(&Value::I64(i64::MIN)));
    assert_eq!(kind_of(e.decode("t", "a1013b8000000000000000")), "transform-decode");
    assert_eq!(e.decode("t", "a1021b7fffffffffffffff").unwrap().fields.get("probe.val"), Some(&Value::I64(i64::MAX)));
    assert_eq!(kind_of(e.decode("t", "a1021b8000000000000000")), "transform-decode");
    // uint refuses a negative item, and a negative value on encode
    assert_eq!(kind_of(e.decode("t", "a10220")), "transform-decode");
    assert_eq!(kind_of(e.encode("t", &entity(&[("probe.val", Value::I64(-1))]))), "transform-encode");
}

#[test]
fn the_depth_limit_counts_arrays_maps_and_tags() {
    let e = engine("field probe.n 0 int\n");
    // the top map is level 1; 63 arrays under it reach level 64
    let nested = |levels: usize, inner: &str| format!("a101{}{}", inner.repeat(levels), "00");
    assert!(e.decode("t", &nested(63, "81")).is_ok());
    assert_eq!(kind_of(e.decode("t", &nested(64, "81"))), "malformed-wire");
    // a tag counts one level; a scalar none
    assert_eq!(kind_of(e.decode("t", &nested(64, "c1"))), "malformed-wire");
    assert!(e.decode("t", &nested(63, "c1")).is_ok());
    // far beyond the limit: the recursion stops at it
    assert_eq!(kind_of(e.decode("t", &"81".repeat(100_000))), "malformed-wire");
}

#[test]
fn equal_keys_are_malformed() {
    let e = engine("field probe.n 0 int\n");
    // 00 and 1800 are both the integer 0
    assert_eq!(kind_of(e.decode("t", "a2000118000102")), "malformed-wire");
    // "ab" definite and in chunks
    assert_eq!(kind_of(e.decode("t", "a2626162007f61616162ff02")), "malformed-wire");
    // 1.0 as a half and as a double; in a map no line walks into
    assert_eq!(kind_of(e.decode("t", "a201a2f93c0000fb3ff000000000000001")), "malformed-wire");
    // 1, 1.0 and true are three keys
    assert!(e.decode("t", "a30100f93c0003f504").is_ok());
}

#[test]
fn text_is_valid_utf8_in_each_chunk() {
    let e = engine("field uid 1 text\n");
    // "é" (c3 a9) in one chunk of an indefinite text
    assert_eq!(e.decode("t", "a1017f62c3a9ff").unwrap().fields.get("uid"), Some(&Value::Str("é".into())));
    // the same two bytes split across two chunks
    assert_eq!(kind_of(e.decode("t", "a1017f61c361a9ff")), "malformed-wire");
    // invalid UTF-8 in a member no line maps
    assert_eq!(kind_of(e.decode("t", "a201600261c3")), "malformed-wire");
    // a chunk of another type
    assert_eq!(kind_of(e.decode("t", "a1017f4161ff")), "malformed-wire");
}

#[test]
fn input_that_is_not_one_well_formed_item() {
    let e = engine("field probe.n 1 int\n");
    for input in [
        "", "a10105 00", "a101", "a1011c", "a101f81f", "ff", "a101ff", "a1015bffffffffffffffff", "9bffffffffffffffff",
        "bf01ff", "a1015f6100ff", "a1011f", "a101df00", "zz",
    ] {
        assert_eq!(kind_of(e.decode("t", input)), "malformed-wire", "{:?}", input);
    }
    // the top item must be the type the paths decide
    assert_eq!(kind_of(e.decode("t", "8105")), "malformed-wire");
}

#[test]
fn residue_keeps_unmapped_items_and_unaddressable_keys() {
    let e = engine("field probe.n 1 int\nfield probe.val 7.1 uint\n");
    // {1: 5, "4": 9, 3: [1, 2], 7: {1: 2, 2: h'00'}}
    let input = "a401056134090382010207a20102024100";
    let ent = e.decode("t", input).unwrap();
    let mut res: Vec<(String, String)> = ent.residue.iter().map(|(_, k, v)| (k.clone(), v.clone())).collect();
    res.sort();
    assert_eq!(
        res,
        vec![("#6134".into(), "09".into()), ("3".into(), "820102".into()), ("7.2".into(), "4100".into())]
    );
    // written back into its map, in the key order
    assert_eq!(e.encode("t", &ent).unwrap(), "a401050382010207a20102024100613409");
    // a residue item read with a longer head and an indefinite length is re-encoded
    let ent = e.decode("t", "a2010518039f1801ff").unwrap();
    assert_eq!(e.encode("t", &ent).unwrap(), "a20105038101");
    // ruling 28: a NaN residue keeps its sign and payload, at the shortest exact width
    for (input, want) in [
        ("a20105f97e01", "a20105f97e01"),
        ("a20105f9fe00", "a20105f9fe00"),
        ("a20105fb7ff8000000000000", "a20105f97e00"),
        ("a20105fa7f800001", "a20105fa7f800001"),
        ("a20105fbfff0000000000001", "a20105fbfff0000000000001"),
    ] {
        let ent = e.decode("t", &input.replacen("a20105", "a2010502", 1)).unwrap();
        assert_eq!(e.encode("t", &ent).unwrap(), want.replacen("a20105", "a2010502", 1), "{}", input);
    }
    // a key in a nested map no line walks into stays inside its item
    let ent = e.decode("t", "a2010508a16134f6").unwrap();
    assert_eq!(ent.residue.iter().map(|(_, k, v)| (k.as_str(), v.as_str())).collect::<Vec<_>>(), vec![("8", "a16134f6")]);
    assert_eq!(e.encode("t", &ent).unwrap(), "a2010508a16134f6");
}

#[test]
fn null_and_undefined() {
    let e = engine("field probe.n 1 int\ngroup probe.items 9\n  field probe.qty n uint\nend\n");
    // a mapped null is absent and not written back; an unmapped one is residue
    let ent = e.decode("t", "a301f602f709f6").unwrap();
    assert!(ent.fields.get("probe.n").is_none());
    assert!(ent.lists.get("probe.items").is_none());
    assert_eq!(ent.residue.iter().map(|(_, k, v)| (k.as_str(), v.as_str())).collect::<Vec<_>>(), vec![("2", "f7")]);
    assert_eq!(e.encode("t", &ent).unwrap(), "a102f7");
    // ruling 12: null or undefined partway down a path makes the item absent
    let w = engine("field probe.n 7.1 int\nfield probe.val 8.[0].1 uint\ngroup probe.items 9.a\nend\n");
    for input in ["a107f6", "a107f7", "a107c1f6", "a20881f607f6", "a109f6"] {
        let ent = w.decode("t", input).unwrap_or_else(|e| panic!("{}: {}", input, e));
        assert!(ent.fields.get("probe.n").is_none() && ent.fields.get("probe.val").is_none(), "{}", input);
        assert!(ent.lists.get("probe.items").is_none(), "{}", input);
    }
    // the null a line passes through is walked into: not residue, not written back
    let ent = w.decode("t", "a207f60201").unwrap();
    assert_eq!(ent.residue.iter().map(|(_, k, v)| (k.as_str(), v.as_str())).collect::<Vec<_>>(), vec![("2", "01")]);
    assert_eq!(w.encode("t", &ent).unwrap(), "a10201");
    // a `when` through a null does not hold; a scalar where a map is needed stays malformed-wire
    assert_eq!(kind_of(w.decode("t", "a10701")), "malformed-wire");
    let k = engine("field uid 1 text\nkind a\nwhen 7.1 5\nkind b\n");
    assert_eq!(k.decode("t", "a107f6").unwrap().kind.unwrap().1, "b");
}

#[test]
fn tags_are_passed_over_and_the_tag_directive_encloses_the_item() {
    let e = engine("field probe.n 1 int\nfield probe.val 2.[0] uint\n");
    // tags on the top item, on a value and on a container a line walks into
    let ent = e.decode("t", "d9d9f7a201c10502c0d8208107").unwrap();
    assert_eq!(ent.fields.get("probe.n"), Some(&Value::I64(5)));
    assert_eq!(ent.fields.get("probe.val"), Some(&Value::I64(7)));
    assert_eq!(e.encode("t", &ent).unwrap(), "a20105028107");

    let t = engine("tag 18\nfield probe.s1 [0] bytes\nfield probe.n [1].1 int\n");
    let ent = t.decode("t", "d2824101a10120").unwrap();
    assert_eq!(ent.fields.get("probe.s1"), Some(&Value::Str("01".into())));
    assert_eq!(t.encode("t", &ent).unwrap(), "d2824101a10120");
    // the tag head may be long; a further tag inside it is passed over
    assert!(t.decode("t", "da00000012c1824101a10120").is_ok());
    // no tag, another tag, or tag 18 inside another tag
    for input in ["824101a10120", "d3824101a10120", "c1d2824101a10120"] {
        assert_eq!(kind_of(t.decode("t", input)), "malformed-wire", "{}", input);
    }
}

#[test]
fn positions_and_groups() {
    let e = engine(
        "field uid 8.[2] text\ngroup probe.items 9\n  field probe.label name text\n  field probe.qty n uint\nend\ngroup probe.nums 10\n  field probe.val . uint\nend\n",
    );
    // a position below the highest written one is null
    let ent = entity(&[("uid", Value::Str("x".into()))]);
    assert_eq!(e.encode("t", &ent).unwrap(), "a10883f6f66178");
    // ruling 23: a gap the lines walk into as a map is `a0`, as an array `80`, else `null`
    let g = engine("field probe.n [1].1 int\nfield probe.val [3].[0] uint\nfield probe.s1 [4] bytes\n");
    let ent = entity(&[("probe.s1", Value::Str("01".into()))]);
    assert_eq!(g.encode("t", &ent).unwrap(), "85f6a0f6804101");
    // an empty container that is not a gap is still not written
    assert_eq!(g.encode("t", &entity(&[("probe.n", Value::I64(2))])).unwrap(), "82f6a10102");
    assert_eq!(g.encode("t", &Entity::default()).unwrap(), "80");
    // COSE_Sign1 with an empty unprotected header map round-trips as `a0` at [1]
    let c = engine("tag 18\nfield probe.s1 [0] bytes\nfield probe.n [1].1 int\nfield uid [1].4 bytes\nfield probe.s2 [2] bytes\nfield probe.j1 [3] bytes\n");
    let ent = c.decode("t", "d2844100a0f64101").unwrap();
    assert_eq!(c.encode("t", &ent).unwrap(), "d2844100a0f64101");
    // items: one with members, one with nothing written, an empty list
    let mut ent = Entity::default();
    let mut item = Entity::default();
    item.fields.insert("probe.qty".into(), Value::I64(2));
    ent.lists.insert("probe.items".into(), vec![item, Entity::default()]);
    ent.lists.insert("probe.nums".into(), vec![Entity::default(), entity(&[("probe.val", Value::I64(3))])]);
    assert_eq!(e.encode("t", &ent).unwrap(), "a20982a1616e02a00a82f603");
    ent.lists.insert("probe.items".into(), Vec::new());
    assert_eq!(e.encode("t", &ent).unwrap(), "a209800a82f603");
    // an element that is not a map is an item with no keys
    let ent = e.decode("t", "a10983a1616e0105f6").unwrap();
    let items = ent.lists.get("probe.items").unwrap();
    assert_eq!(items.len(), 3);
    assert_eq!(items[0].fields.get("probe.qty"), Some(&Value::I64(1)));
    assert!(items[1].fields.is_empty() && items[2].fields.is_empty());
    // ruling 27: a deeper step of a body path meeting the wrong type is malformed-wire
    let d = engine("group probe.items 9\n  field probe.qty a.n uint\nend\n");
    assert_eq!(kind_of(d.decode("t", "a10981a1616101")), "malformed-wire");
    assert!(d.decode("t", "a10981a16161f6").unwrap().lists["probe.items"][0].fields.is_empty());
    // ruling 26: a line suppressed by `with` writes nothing
    let w = engine("field probe.n 1 int with uid\nfield probe.val 2 uint\n");
    assert_eq!(w.encode("t", &entity(&[("probe.n", Value::I64(1)), ("probe.val", Value::I64(2))])).unwrap(), "a10202");
    assert_eq!(
        w.encode("t", &entity(&[("probe.n", Value::I64(1)), ("probe.val", Value::I64(2)), ("uid", Value::Str("u".into()))])).unwrap(),
        "a201010202"
    );
    // a group path at an item that is not an array
    assert_eq!(kind_of(e.decode("t", "a109a0")), "malformed-wire");
    // the item limit
    assert_eq!(kind_of(e.decode_limited("t", "a10983a0a0a0", 2)), "malformed-wire");
    assert!(e.decode_limited("t", "a10983a0a0a0", 3).is_ok());
}

#[test]
fn transforms_on_encode() {
    let e = engine("field probe.s1 1 bytes\nfield time_ms 2 epoch_s\nfield probe.n 3 bool\n");
    let enc = |f: &[(&str, Value)]| kind_of(e.encode("t", &entity(f)));
    assert_eq!(enc(&[("probe.s1", Value::Str("00ff".into()))]), "ok \"a1014200ff\"");
    assert_eq!(enc(&[("probe.s1", Value::Str("".into()))]), "ok \"a10140\"");
    assert_eq!(enc(&[("probe.s1", Value::Str("00FF".into()))]), "transform-encode");
    assert_eq!(enc(&[("probe.s1", Value::Str("0".into()))]), "transform-encode");
    // epoch_s: divided by 1000 exactly, half away from zero
    assert_eq!(enc(&[("time_ms", Value::I64(1500))]), "ok \"a10202\"");
    assert_eq!(enc(&[("time_ms", Value::I64(1499))]), "ok \"a10201\"");
    assert_eq!(enc(&[("time_ms", Value::I64(-1500))]), "ok \"a10221\"");
    assert_eq!(enc(&[("time_ms", Value::I64(-1499))]), "ok \"a10220\"");
    assert_eq!(enc(&[("probe.n", Value::I64(1))]), "ok \"a103f5\"");
    assert_eq!(enc(&[("probe.n", Value::I64(2))]), "transform-encode");
    // epoch_s on decode: the product must lie in the signed 64-bit range
    assert_eq!(e.decode("t", "a1023901f3").unwrap().fields.get("time_ms"), Some(&Value::I64(-500_000)));
    assert_eq!(kind_of(e.decode("t", "a1021b0020c49ba5e353f8")), "transform-decode");
}

#[test]
fn kinds_by_integer_bool_and_text() {
    let e = engine(
        "field uid 1 text\nkind a\nwhen 0 18446744073709551615\nkind b\nwhen 0 true\nkind c\nwhen k =5\nkind d\nwhen 0 -0\nkind e\nwhen 0 present\nrequires uid\n",
    );
    let sel = |input: &str| e.decode("t", input).map(|ent| ent.kind.unwrap().1);
    assert_eq!(sel("a1001bffffffffffffffff").unwrap(), "a");
    assert_eq!(sel("a100f5").unwrap(), "b");
    assert_eq!(sel("a1616b6135").unwrap(), "c");
    assert_eq!(sel("a10000").unwrap(), "d");
    // a float never holds; null is not present
    assert_eq!(sel("a100f90000").unwrap(), "e");
    assert_eq!(kind_of(sel("a100f6")), "no-kind");
    // values written with their type
    let mut ent = entity(&[("uid", Value::Str("u".into()))]);
    for (k, want) in
        [("a", "a2001bffffffffffffffff016175"), ("b", "a200f5016175"), ("c", "a2016175616b6135"), ("d", "a20000016175"), ("e", "a1016175")]
    {
        ent.kind = Some(("t".into(), k.into()));
        assert_eq!(e.encode("t", &ent).unwrap(), want, "kind {}", k);
    }
}

#[test]
fn load_checks() {
    // the path grammar is a line check
    for loc in ["a[0]", "[01]", "-0", "+1", "a..b", "18446744073709551616", "[65536]", "4a"] {
        assert_eq!(load_error(&format!("field probe.n {} int\nbogus\n", loc)), "bad-locator", "{}", loc);
    }
    assert_eq!(load_error("group probe.items a[0]\nend\nbogus\n"), "bad-locator");
    // after the file: options, transforms, `.` outside a group, types
    assert_eq!(load_error("field probe.n 1 int absent 0\nbogus\n"), "unknown-directive");
    assert_eq!(load_error("field probe.n 1 int absent 0\n"), "bad-directive");
    assert_eq!(load_error("field probe.n 1 int swap\n"), "bad-directive");
    assert_eq!(load_error("field probe.n 1 twos\n"), "bad-directive");
    assert_eq!(load_error("field probe.n 1 string\n"), "bad-directive");
    // ruling 25: a transform name no wire has is `bad-directive` after the file
    assert_eq!(load_error("field probe.n 1 nosuch\n"), "bad-directive");
    assert_eq!(load_error("field probe.n 1 nosuch\nbogus\n"), "unknown-directive");
    // ruling 34: parameters too are checked after the file on cbor
    assert_eq!(load_error("field probe.a 1 uscale:0\nbogus\n"), "unknown-directive");
    assert_eq!(load_error("field probe.a 3 uscale:x\nbogus\n"), "unknown-directive");
    assert_eq!(load_error("field probe.a 3 uscale:x\n"), "bad-directive");
    // ruling 22: `.` is a path only on a `field` in a group body and on a `group` outside one
    assert_eq!(load_error("field probe.n . int\nbogus\n"), "bad-locator");
    assert_eq!(load_error("group probe.items 9\n  field probe.label name text\n  const . 1\nend\nbogus\n"), "bad-locator");
    assert_eq!(load_error("field uid 1 text\nkind a\nwhen . 1\nbogus\n"), "bad-locator");
    assert_eq!(load_error("group probe.items 9\n  group probe.subs .\n  end\nend\nbogus\n"), "bad-locator");
    assert_eq!(load_error("group probe.nums .\n  field probe.val . uint\nend\n"), "loaded");
    // ruling 22: the exemption holds only for the shorter path; a group takes part in the prefix rule
    assert_eq!(load_error("field uid 2 text\nkind a\nwhen 7.1 present\nfield probe.n 7 int\n"), "bad-directive");
    assert_eq!(load_error("field probe.n 9 int\ngroup probe.items 9.1\nend\n"), "bad-directive");
    assert_eq!(load_error("field uid 2 text\nkind a\nconst 1 present\n"), "bad-directive");
    assert_eq!(load_error("field probe.n [0] int\nfield probe.val 1 uint\n"), "bad-directive");
    assert_eq!(load_error("field probe.n 1.[0] int\nfield probe.val 1.2 uint\n"), "bad-directive");
    assert_eq!(load_error("group probe.items 9\nend\nfield probe.n 9.[0] int\n"), "bad-directive");
    assert_eq!(load_error("group probe.items .\nend\n"), "loaded");
    // ruling 13: a path that is a proper prefix of another line's path, in one scope
    assert_eq!(load_error("field probe.n 1 int\nfield probe.val 1.2 uint\n"), "bad-directive");
    assert_eq!(load_error("field probe.val 1.2 uint\nfield probe.n 1 int\nbogus\n"), "unknown-directive");
    assert_eq!(load_error("field probe.n 1.[0] int\nfield probe.val 1 uint\n"), "bad-directive");
    assert_eq!(load_error("field uid 2 text\nkind a\nwhen 1 5\nfield probe.n 1.2 int\n"), "bad-directive");
    assert_eq!(load_error("field uid 2 text\nkind a\nwhen 1 present\nkind b\nfield probe.n 1.2 int\n"), "loaded");
    assert_eq!(load_error("kind a\nwhen 1 5\nkind b\nwhen 0 1\nfield probe.n 1.2 int\n"), "loaded");
    // `when … present` may name a proper prefix of another line's path; the reverse is refused
    assert_eq!(load_error("field uid 2 text\nkind a\nwhen 1 present\nrequires probe.n\nfield probe.n 1.2 int\n"), "loaded");
    assert_eq!(load_error("field uid 2 text\nkind a\nwhen 1.2 present\nfield probe.n 1 int\n"), "bad-directive");
    // two lines on one path are not a prefix of each other
    assert_eq!(load_error("field probe.n 1 int\nfield probe.k0 1 int\n"), "loaded");
    // a group at or under another group's path
    assert_eq!(load_error("group probe.items 9\nend\ngroup probe.nums 9\nend\n"), "bad-directive");
    assert_eq!(load_error("group probe.items 9\nend\ngroup probe.nums 9.[0]\nend\n"), "bad-directive");
    assert_eq!(load_error("group probe.items 9\nend\ngroup probe.nums 10\nend\n"), "loaded");
    // a group body that mixes `.` with other paths
    assert_eq!(load_error("group probe.items 9\n  field probe.label . text\n  field probe.qty n uint\nend\n"), "bad-directive");
    assert_eq!(load_error("group probe.items 9\n  field probe.label . text\n  group probe.subs a\n  end\nend\n"), "bad-directive");
    assert_eq!(load_error("group probe.items 9\n  field probe.label . text\n  field probe.tag . text\nend\n"), "loaded");
    // `tag`: one argument as the line is read, its value after the file
    assert_eq!(load_error("tag 1 2\nbogus\n"), "bad-directive");
    assert_eq!(load_error("tag 01\nbogus\n"), "unknown-directive");
    assert_eq!(load_error("tag 01\n"), "bad-directive");
    assert_eq!(load_error("tag 18446744073709551615\n"), "loaded");
    assert_eq!(load_error("tag 18446744073709551616\n"), "bad-directive");
    assert_eq!(load_error("tag ber-oid\n"), "bad-directive");
    assert_eq!(load_error("tag 1\ntag 1\n"), "bad-directive");
    assert_eq!(load_error("length ber\n"), "bad-directive");
    // the cbor transforms on another wire
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).unwrap();
    let json = HEAD.replace("wire cbor", "wire json");
    assert!(e.load_def(&format!("{}field uid a text\n", json)).unwrap_err().msg.starts_with("bad-directive"));
}

#[test]
fn rulings_29_to_31() {
    // 29: a field at a path a `when` value names is not encoded, nor converted
    let e = engine("field probe.n 0 bool\nkind a\nwhen 0 1\n");
    let mut ent = entity(&[("probe.n", Value::I64(5))]);
    ent.kind = Some(("t".into(), "a".into()));
    assert_eq!(e.encode("t", &ent).unwrap(), "a10001");
    let c = engine("field probe.n 0 bool\nconst 0 7\n");
    assert_eq!(c.encode("t", &entity(&[("probe.n", Value::I64(5))])).unwrap(), "a10007");

    // 30: gaps follow the selected scope's lines only
    let k = engine("field uid [0] text\nkind a\nfield probe.n [1].1 int\nkind b\nfield probe.s1 [2] bytes\n");
    let mut ent = entity(&[("probe.s1", Value::Str("01".into()))]);
    ent.kind = Some(("t".into(), "b".into()));
    assert_eq!(k.encode("t", &ent).unwrap(), "83f6f64101");
    ent.kind = Some(("t".into(), "a".into()));
    ent.fields.insert("probe.n".into(), Value::I64(2));
    ent.fields.insert("uid".into(), Value::Str("u".into()));
    assert_eq!(k.encode("t", &ent).unwrap(), "826175a10102");

    // 31: residue at a container the selected lines walk into but leave empty is written whole
    let r = engine("field uid 1 text\nkind a\nwhen 0 1\nfield probe.n 7.1 int\nkind b\n");
    let mut ent = r.decode("t", "a201617507a10203").unwrap();
    assert_eq!(ent.kind.as_ref().unwrap().1, "b");
    assert_eq!(ent.residue.iter().map(|(_, k, v)| (k.as_str(), v.as_str())).collect::<Vec<_>>(), vec![("7", "a10203")]);
    ent.kind = Some(("t".into(), "a".into()));
    assert_eq!(r.encode("t", &ent).unwrap(), "a3000101617507a10203");
    // a line that writes a value there still wins over residue
    ent.fields.insert("probe.n".into(), Value::I64(4));
    assert_eq!(r.encode("t", &ent).unwrap(), "a3000101617507a10104");
}

#[test]
fn rulings_32_and_33() {
    // 32: a `const` path through an item of the wrong type is malformed-wire
    let c = engine("field probe.n 1 int\nconst 7.1 5\n");
    assert_eq!(kind_of(c.decode("t", "a201050701")), "malformed-wire");
    assert!(c.decode("t", "a2010507a10105").is_ok());
    // ... and through `null` the const's item is absent (ruling 12)
    assert!(c.decode("t", "a2010507f6").is_ok());

    // 33: residue through a place a line wrote a value at is dropped
    let v = engine("field probe.n 7 int\n");
    let mut ent = entity(&[("probe.n", Value::I64(1))]);
    ent.residue.push(("t".into(), "7.2".into(), "05".into()));
    assert_eq!(v.encode("t", &ent).unwrap(), "a10701");
    // ... and through a container of the other type
    let m = engine("field probe.n 7.1 int\n");
    let mut ent = entity(&[("probe.n", Value::I64(1))]);
    ent.residue.push(("t".into(), "7.[0]".into(), "05".into()));
    ent.residue.push(("t".into(), "8".into(), "06".into()));
    assert_eq!(m.encode("t", &ent).unwrap(), "a207a101010806");
}
