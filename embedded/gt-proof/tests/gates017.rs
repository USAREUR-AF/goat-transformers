//! Gate blocks of spec 0.17 on the device against the reference engine,
//! beyond the vectors and the same-format fuzz runs:
//!
//!   encode   seeded random JSON entities of `conformance-gates-json` (any of
//!            its keys present or absent, values that fit, do not fit, or sit
//!            on the gate bits and the sentinels) decoded by the reference
//!            engine and encoded by the device to each `conformance-gates-*`
//!            bits pack. Output bytes, or the error kind, must be the
//!            reference engine's `convert`.
//!   decode   seeded random messages, and vector inputs with bits flipped and
//!            tails cut, decoded by the device and the reference engine for
//!            every bits pack with gate blocks. Every value, list, item and
//!            kind must be the reference engine's, or the error kind.

use gt_core::{Plan, Session, ROOT};
use gt_proof::*;

const JSON: &str = "conformance-gates-json";
const KEYS: [&str; 9] = ["w", "x", "y", "z", "c1", "c2", "n", "val", "qty"];

fn value(rng: &mut Rng) -> i64 {
    match rng.below(6) {
        0 => [0, 1, 2, 3, 255, 256, -1, 15, 16, 7][rng.below(10)],
        1 | 2 => rng.below(4) as i64,
        3 => rng.below(256) as i64,
        _ => rng.below(70_000) as i64,
    }
}

fn entity(rng: &mut Rng) -> String {
    let mut parts = Vec::new();
    for k in KEYS {
        if rng.below(2) == 0 {
            parts.push(format!("\"{}\":{}", k, value(rng)));
        }
    }
    if rng.below(3) == 0 {
        let alt = [0.0, 25.0, 100.0, 250.0, 6375.0, 25500.0, 1.0e6, -25.0][rng.below(8)];
        parts.push(format!("\"alt\":{}", alt));
    }
    if rng.below(3) == 0 {
        let n = rng.below(4);
        let mut items = Vec::new();
        for _ in 0..n {
            let mut f = Vec::new();
            if rng.below(3) != 0 {
                f.push(format!("\"v\":{}", value(rng)));
            }
            if rng.below(2) == 0 {
                f.push(format!("\"q\":{}", value(rng)));
            }
            items.push(format!("{{{}}}", f.join(",")));
        }
        parts.push(format!("\"items\":[{}]", items.join(",")));
    }
    format!("{{{}}}", parts.join(","))
}

/// The bits packs with gate blocks: their `pack.def` has an `if` line and no
/// `layout sequential`.
fn gated_formats(p: &Proof) -> Vec<String> {
    let root = repo_root();
    let mut gated = std::collections::HashSet::new();
    for d in std::fs::read_dir(root.join("packs")).unwrap().flatten() {
        let text = std::fs::read_to_string(d.path().join("pack.def")).unwrap_or_default();
        let first = |l: &str| l.split_whitespace().next().map(str::to_string);
        let format = text.lines().find_map(|l| {
            let mut t = l.split_whitespace();
            (t.next() == Some("format")).then(|| t.next().unwrap_or("").to_string())
        });
        let sequential = text.lines().any(|l| l.split_whitespace().collect::<Vec<_>>() == ["layout", "sequential"]);
        if let Some(f) = format {
            if !sequential && text.lines().any(|l| first(l).as_deref() == Some("if")) {
                gated.insert(f);
            }
        }
    }
    p.bits_formats().into_iter().filter(|f| gated.contains(f)).collect()
}

#[test]
fn gate_blocks_encode_as_the_reference_does() {
    let mut p = Proof::new();
    let targets: Vec<String> =
        gated_formats(&p).into_iter().filter(|f| f.starts_with("conformance-gates-")).collect();
    let specs: Vec<_> = targets.iter().map(|t| (None, Some(t.clone()), Vec::new())).collect();
    p.compile(&specs);
    let mut scratch = Box::new(Scratch::new());
    let mut out = vec![0u8; 4096];
    let mut rng = Rng(0x0017_6A7E_B10C_5EED);
    let (mut runs, mut equal, mut errors, mut plans) = (0usize, 0usize, 0usize, 0usize);
    let mut differ = Vec::new();
    for t in &targets {
        let blob = match p.plan(None, Some(t), &[]) {
            Ok(b) => b,
            Err(e) => panic!("{}: {}", t, e),
        };
        plans += 1;
        let plan = Plan::parse(&blob).expect("plan");
        for _ in 0..3_000 {
            let input = entity(&mut rng);
            let mut ent = match p.engine.decode_limited(JSON, &input, goat_transformers::DEFAULT_MAX_ITEMS) {
                Ok(e) => e,
                Err(e) => panic!("{} does not decode: {}", input, e.msg),
            };
            ent.kind = None;
            runs += 1;
            // The plan has no source format: the device encodes the entity it
            // is given, as `encode` does. The check of spec 0.94 is made by
            // `convert` only (its ruling 2), so where `convert` refuses an
            // entity for it, the reference is `encode` of the same entity.
            let want = match p.engine.convert(JSON, t, &input) {
                Err(e) if e.msg.contains("the entity holds no key of the kind chosen") => p.engine.encode(t, &ent),
                w => w,
            };
            let mut texts = Vec::new();
            texts_of(&ent, &mut texts);
            let mut s = Session::new(&plan, &mut scratch);
            s.set_texts(&texts);
            let got = (|| {
                inject(&mut s, &plan, ROOT, &ent, &mut 0)?;
                s.fill(&[])?;
                s.complete()?;
                s.encode(&mut out)
            })();
            match (want, got) {
                (Ok(w), Ok(n)) if p.wire_out(t, &out[..n]) == w => equal += 1,
                (Err(e), Err(d)) if kind_of(&e) == d.name() => errors += 1,
                (w, g) => differ.push(format!(
                    "{} -> {}: {}: reference {:?}, device {:?}",
                    JSON,
                    t,
                    input,
                    w.map_err(|e| e.msg),
                    g.map(|n| p.wire_out(t, &out[..n]))
                )),
            }
        }
    }
    eprintln!(
        "gates 0.17, encode: {} entities through {} plans: {} equal outputs, {} equal error kinds, {} differ",
        runs,
        plans,
        equal,
        errors,
        differ.len()
    );
    for d in differ.iter().take(20) {
        eprintln!("DIFFER {}", d);
    }
    assert!(differ.is_empty(), "the device and the reference engine encode gate blocks differently");
    assert!(equal > 0 && errors > 0);
}

#[test]
fn gate_blocks_decode_as_the_reference_does() {
    let mut p = Proof::new();
    let formats = gated_formats(&p);
    let specs: Vec<_> = formats.iter().map(|f| (Some(f.clone()), None, Vec::new())).collect();
    p.compile(&specs);
    let vectors = p.vectors();
    let mut scratch = Box::new(Scratch::new());
    let mut rng = Rng(0x0017_DEC0_DE00_6A7E);
    let (mut runs, mut equal, mut errors) = (0usize, 0usize, 0usize);
    let mut differ = Vec::new();
    let mut compiled = 0usize;
    for f in &formats {
        let blob = match p.plan(Some(f), None, &[]) {
            Ok(b) => b,
            // a pack that also uses a line of a later version the device does not have
            Err(e) if e.contains("refused: unsupported-feature:") => continue,
            Err(e) => panic!("{}: {}", f, e),
        };
        compiled += 1;
        let plan = Plan::parse(&blob).expect("plan");
        let seeds: Vec<Vec<u8>> =
            vectors.iter().filter(|v| v.from == *f).filter_map(|v| p.wire_in(f, &v.input)).collect();
        let armored = p.is_armored(f);
        for _ in 0..4_000 {
            let mut m = if seeds.is_empty() || rng.below(3) == 0 {
                let n = rng.below(24);
                rng.bytes(n)
            } else {
                let mut m = seeds[rng.below(seeds.len())].clone();
                for _ in 0..1 + rng.below(3) {
                    if !m.is_empty() && rng.below(3) != 0 {
                        let i = rng.below(m.len());
                        m[i] ^= 1 << rng.below(8);
                    } else {
                        m.truncate(rng.below(m.len() + 1));
                    }
                }
                m
            };
            if armored {
                for b in m.iter_mut() {
                    let v = *b & 0x3F;
                    *b = if v < 40 { 0x30 + v } else { 0x38 + v };
                }
            }
            runs += 1;
            let text = if armored { String::from_utf8_lossy(&m).into_owned() } else { hex(&m) };
            let want = p.engine.decode_limited(f, &text, goat_transformers::DEFAULT_MAX_ITEMS);
            let mut s = Session::new(&plan, &mut scratch);
            match (want, s.decode(&m)) {
                (Ok(ent), Ok(())) => {
                    let same = same_entity(&s, &plan, ROOT, &ent, 0.0).and_then(|_| {
                        let k = ent.kind.as_ref().map(|(_, n)| n.as_str());
                        if s.kind_name(ROOT) == k {
                            Ok(())
                        } else {
                            Err(format!("kind {:?}, reference {:?}", s.kind_name(ROOT), k))
                        }
                    });
                    match same {
                        Ok(()) => equal += 1,
                        Err(e) => differ.push(format!("{} {}: {}", f, text, e)),
                    }
                }
                (Err(e), Err(d)) if kind_of(&e) == d.name() => errors += 1,
                (w, d) => differ.push(format!("{} {}: reference {:?}, device {:?}", f, text, w.map(|_| "ok").map_err(|e| e.msg), d)),
            }
        }
    }
    eprintln!(
        "gates 0.17, decode: {} messages through {} formats: {} equal entities, {} equal error kinds, {} differ",
        runs,
        compiled,
        equal,
        errors,
        differ.len()
    );
    for d in differ.iter().take(20) {
        eprintln!("DIFFER {}", d);
    }
    assert!(differ.is_empty(), "the device and the reference engine decode gate blocks differently");
    assert!(compiled >= 20 && equal > 0);
}
