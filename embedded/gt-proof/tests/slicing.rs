//! A plan compiled for one kind of a format. For every same-format vector of
//! the formats below: when the vector's message is of the compiled kind the
//! output is the vector's `expect`; when it is of another kind the device
//! refuses it with `no-kind` and never reads it as the compiled kind.

use gt_core::{Error, Plan};
use gt_proof::*;
use std::collections::BTreeMap;

/// (format, how many of its kinds to compile one by one; 0 = all the vectors name)
const FORMATS: [(&str, usize); 9] = [
    ("remote-id", 0),
    ("adsb", 0),
    ("demo-kinds-bits", 0),
    ("demo-bits-bytes", 0),
    ("demo-bits-msb", 0),
    ("conformance-seq-kinds", 0),
    ("conformance-seq-msb", 0),
    ("mavlink2", 12),
    ("nmea2000", 12),
];

#[test]
fn a_plan_for_one_kind_refuses_the_others() {
    let mut p = Proof::new();
    let vectors = p.vectors();
    let kind_of_vector = |v: &Vector| v.model.iter().find(|(k, _)| k == "@kind").map(|(_, n)| n.clone());
    let mut specs = Vec::new();
    let mut kinds: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    for (format, limit) in FORMATS {
        let list = kinds.entry(format).or_default();
        for v in vectors.iter().filter(|v| v.from == format && v.to == format) {
            if let Some(k) = kind_of_vector(v) {
                if !list.contains(&k) && (limit == 0 || list.len() < limit) {
                    let side = format!("{}:{}", format, k);
                    specs.push((Some(side.clone()), Some(side), Vec::new()));
                    list.push(k);
                }
            }
        }
    }
    p.compile(&specs);
    let mut scratch = Box::new(Scratch::new());
    let mut out = vec![0u8; 1 << 16];
    let (mut plans, mut converted, mut refused, mut unsupported) = (0usize, 0usize, 0usize, 0usize);
    for (format, list) in &kinds {
        for kind in list {
            let side = format!("{}:{}", format, kind);
            // A kind the device profile refuses (as fuzz.rs and equivalence.rs do)
            // has no plan to slice; the refusal itself is tested by packc.
            let blob = match p.plan(Some(&side), Some(&side), &[]) {
                Ok(b) => b,
                Err(e) if e.contains("refused: unsupported-feature:") => {
                    unsupported += 1;
                    continue;
                }
                Err(e) => panic!("{}: {}", side, e),
            };
            let plan = Plan::parse(&blob).expect("plan");
            plans += 1;
            for v in vectors.iter().filter(|v| v.from == *format && v.to == *format && v.context.is_none()) {
                let (input, theirs) = match (unhex(&v.input), kind_of_vector(v)) {
                    (Some(i), Some(k)) => (i, k),
                    _ => continue,
                };
                let got = gt_core::convert(&plan, &input, &mut out, &mut scratch, &[]);
                if theirs == *kind {
                    let n = got.unwrap_or_else(|e| panic!("{} on {}/{}: {:?}", side, v.pack, v.name, e));
                    assert_eq!(Some(hex(&out[..n])), v.expect, "{} on {}/{}", side, v.pack, v.name);
                    converted += 1;
                } else {
                    assert_eq!(got, Err(Error::NoKind), "{} on {}/{} (a `{}` message)", side, v.pack, v.name, theirs);
                    refused += 1;
                }
            }
        }
    }
    eprintln!(
        "slicing: {} one-kind plans over {} formats ({} kinds the device profile refuses): {} messages of the compiled kind converted to the vector's bytes, {} messages of other kinds refused with no-kind",
        plans,
        kinds.len(),
        unsupported,
        converted,
        refused
    );
    assert!(converted > 0 && refused > 0);
}
