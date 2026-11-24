//! Engine-spec 0.34 (an `inner` message) with ruling 20 of 0.52 (no key is
//! mapped by both packs), where no vector reaches.
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

/// Ruling 7, the part ruling 20c of 0.52 keeps: the counts (0.31) of an inner
/// list are checked against the budget the outer items left.
#[test]
fn counts_of_an_inner_list() {
    let e = engine(&[
        ("in", "count a 8\ncount b 8\ngroup probe.subs count @a @b\nfield probe.val 8 uint\nend"),
        ("out", &format!("{}\ninner in", NUMS)),
    ]);
    let input = "010702020809";
    let ent = e.decode_limited("out", input, 3).unwrap();
    assert_eq!(vals(&ent, "probe.nums"), [7]);
    assert_eq!(vals(&ent, "probe.subs"), [8, 9]);
    let err = e.decode_limited("out", input, 2).unwrap_err();
    assert!(err.msg.starts_with("malformed-wire:"), "{}", err.msg);
}

/// Ruling 20 of 0.52: a key or a list both packs map is `bad-directive` at the
/// `inner` line, on decode and on encode, wherever the outer line stands.
#[test]
fn a_key_both_packs_map_is_refused() {
    let refused = |inner: &str, outer: &str, hex: &str, key: &str| {
        let e = engine(&[("in", inner), ("out", outer)]);
        for err in [e.decode("out", hex).unwrap_err(), e.encode("out", &Entity::default()).unwrap_err()] {
            assert!(err.msg.starts_with("bad-directive:") && err.msg.contains(key), "{}: {}", outer, err.msg);
            assert!(err.msg.contains("`in`"), "{}", err.msg);
        }
    };
    let block = "length 8 bytes\ninner in\nend\n";
    let rest = "group probe.nums rest\nfield probe.val 8 uint\nend";
    let ascii = "field probe.s1 8 ascii";
    let via = "map t 1 one\nfield probe.s1 8 uint via t";
    // a list: counted before the inner line, `rest` after it, and in a block
    let counts = "count a 8\ncount b 8\ngroup probe.nums count @a @b\nfield probe.val 8 uint\nend";
    refused(counts, &format!("{}\ninner in", NUMS), "010702020809", "probe.nums[]");
    refused(NUMS, &format!("{}{}", block, rest), "0302070809", "probe.nums[]");
    refused(NUMS, &format!("{}length 8 bytes\n{}\nend", block, rest), "02010700", "probe.nums[]");
    // a list with a list in its items
    let sub = "group probe.subs count 8\nfield probe.val 8 uint\nend\n";
    let items = format!("group probe.items count 8\npresence p 8\nif p.1\n{}end\nif p.2\n{}end\nend\n", sub, sub);
    let inner = format!("group probe.items count 8\n{}end", sub);
    refused(&inner, &format!("{}{}group probe.nums count 8\nfield probe.val 8 uint\nend", block, items), "0301010701c001080109010a", "probe.items[]");
    // a field, also when the inner line of it fails its transform
    refused(ascii, &format!("{}{}", block, ascii), "010141", "probe.s1");
    refused(ascii, &format!("{}\ninner in", ascii), "4101", "probe.s1");
    // a line with a table, in either pack, hit or missed
    for value in ["01", "02"] {
        refused(via, &format!("{}\ninner in", ascii), &format!("41{}", value), "probe.s1");
        refused(via, &format!("{}{}", block, ascii), &format!("01{}41", value), "probe.s1");
        refused(ascii, &format!("{}{}", block, via), &format!("0141{}", value), "probe.s1");
    }
}
