//! Engine-spec 0.34, Decode step 4 and ruling 7: lists that the outer and the
//! inner message both hold, where no vector reaches.
#![cfg(feature = "bits")]

use goat_transformers::{Engine, Entity, Value};
use std::path::Path;

const HEAD: &str = "version 0.34.0\ndistribution public\nsource \"synthetic\"\nuses probe\nwire bits\nlayout sequential\nbit_order msb\n";

fn engine(packs: &[(&str, &str)]) -> Engine {
    let mut e = Engine::new();
    e.load_model_dir(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../model")).unwrap();
    for (name, lines) in packs {
        e.load_def(&format!("format {}\n{}{}\n", name, HEAD, lines)).unwrap();
    }
    e
}

fn vals(ent: &Entity, list: &str) -> Vec<i64> {
    let val = |i: &Entity| match i.fields.get("probe.val") {
        Some(Value::I64(n)) => *n,
        v => panic!("{:?}", v),
    };
    ent.lists[list].iter().map(val).collect()
}

const NUMS: &str = "group probe.nums count 8\nfield probe.val 8 uint\nend";

/// A list inside an item is another list than the message's of the same name.
#[test]
fn a_list_of_an_item_is_not_the_inner_list() {
    let e = engine(&[
        ("in", "group probe.subs count 8\nfield probe.val 8 uint\nend"),
        ("out", "length 8 bytes\ninner in\nend\ngroup probe.items count 8\ngroup probe.subs count 8\nfield probe.val 8 uint\nend\nend"),
    ]);
    let ent = e.decode("out", "020107010109").unwrap();
    assert_eq!(vals(&ent, "probe.subs"), [7]);
    assert_eq!(vals(&ent.lists["probe.items"][0], "probe.subs"), [9]);
}

/// A `rest` group past the end of its extent is an empty list, which does not
/// replace the inner list read first.
#[test]
fn an_empty_rest_keeps_the_inner_list() {
    let e = engine(&[
        ("in", NUMS),
        ("out", "length 8 bytes\ninner in\nend\nlength 8 bytes\ngroup probe.nums rest\nfield probe.val 8 uint\nend\nend"),
    ]);
    assert_eq!(vals(&e.decode("out", "02010700").unwrap(), "probe.nums"), [7]);
    assert_eq!(vals(&e.decode("out", "0201070109").unwrap(), "probe.nums"), [7]);
}

/// Ruling 7: the two counts (0.31) of a discarded inner list are checked
/// against the budget left; its items are not counted.
#[test]
fn counts_of_a_discarded_list() {
    let e = engine(&[
        ("in", "count a 8\ncount b 8\ngroup probe.nums count @a @b\nfield probe.val 8 uint\nend"),
        ("out", &format!("{}\ninner in", NUMS)),
    ]);
    let input = "010702020809";
    assert_eq!(vals(&e.decode_limited("out", input, 3).unwrap(), "probe.nums"), [7]);
    let err = e.decode_limited("out", input, 2).unwrap_err();
    assert!(err.msg.starts_with("malformed-wire:"), "{}", err.msg);
}

/// 7g: the items of an outer list that the inner list read first discards are
/// not items the decoded entity holds.
#[test]
fn items_of_a_discarded_outer_list_are_not_counted() {
    let e = engine(&[
        ("in", NUMS),
        ("out", "length 8 bytes\ninner in\nend\ngroup probe.nums rest\nfield probe.val 8 uint\nend"),
    ]);
    assert_eq!(vals(&e.decode_limited("out", "0302070809", 2).unwrap(), "probe.nums"), [7, 8]);
}

/// Ruling 17: a `switch` on a key whose line failed stops the decode, in the
/// inner message too; an outer failure of the wire after it is not reached.
#[test]
fn a_switch_on_a_failed_inner_key_stops_the_decode() {
    let e = engine(&[
        ("in", "field probe.s1 8 ascii\nswitch probe.s1\ncase A\nfield probe.x 8 uint\nend"),
        ("out", "length 8 bytes\ninner in\nend\nfield probe.n 8 uint"),
    ]);
    let err = e.decode("out", "0101").unwrap_err();
    assert!(err.msg.starts_with("transform-decode:"), "{}", err.msg);
}

/// Decode step 4 and ruling 19: a failed inner line whose key another line
/// gives is forgiven (0.6), read before it or after it.
#[test]
fn a_failed_inner_line_whose_key_has_a_value() {
    let e = engine(&[
        ("in", "field probe.s1 8 ascii"),
        ("after", "length 8 bytes\ninner in\nend\nfield probe.s1 8 ascii"),
        ("before", "field probe.s1 8 ascii\ninner in"),
    ]);
    let s1 = |ent: &Entity| matches!(ent.fields.get("probe.s1"), Some(Value::Str(s)) if s == "A");
    assert!(s1(&e.decode("after", "010141").unwrap()));
    assert!(s1(&e.decode("before", "4101").unwrap()));
    assert!(e.decode("after", "010101").is_err());
}

/// Ruling 22: two groups of one nested list in an item of a discarded list
/// release nothing from the budget.
#[test]
fn a_discarded_list_releases_no_budget() {
    let sub = "group probe.subs count 8\nfield probe.val 8 uint\nend\n";
    let items = format!("group probe.items count 8\npresence p 8\nif p.1\n{}end\nif p.2\n{}end\nend\n", sub, sub);
    let e = engine(&[
        ("in", "group probe.items count 8\ngroup probe.subs count 8\nfield probe.val 8 uint\nend\nend"),
        ("out", &format!("length 8 bytes\ninner in\nend\n{}group probe.nums count 8\nfield probe.val 8 uint\nend", items)),
    ]);
    // kept: 1 item, 1 sub; discarded: 1 item of two lists of 1; then nums of 1
    let input = "03010107".to_string() + "01c001080109" + "010a";
    assert!(e.decode_limited("out", &input, 3).is_ok());
    assert!(e.decode_limited("out", &input, 2).is_err());
}

/// Ruling 23: a line whose transform succeeds and whose table has no entry
/// fails the decode also when the other pack gave the key, read before it or
/// after it; a hit of the table leaves the first value in place.
#[test]
fn a_table_miss_whose_key_the_other_pack_gave() {
    let via = "map t 1 one\nfield probe.s1 8 uint via t";
    let plain = "field probe.s1 8 ascii";
    let e = engine(&[
        ("in", via),
        ("plain", plain),
        ("before", &format!("{}\ninner in", plain)),
        ("after", &format!("length 8 bytes\ninner in\nend\n{}", plain)),
        ("outer", &format!("length 8 bytes\ninner plain\nend\n{}", via)),
    ]);
    let s1 = |ent: &Entity| match ent.fields.get("probe.s1") {
        Some(Value::Str(s)) => s.clone(),
        v => panic!("{:?}", v),
    };
    assert_eq!(s1(&e.decode("before", "4101").unwrap()), "A");
    assert_eq!(s1(&e.decode("after", "010141").unwrap()), "one");
    assert_eq!(s1(&e.decode("outer", "014101").unwrap()), "A");
    for (f, hex) in [("before", "4102"), ("after", "010241"), ("outer", "014102")] {
        let err = e.decode(f, hex).unwrap_err();
        assert!(err.msg.starts_with("transform-decode:"), "{}: {}", f, err.msg);
    }
}
