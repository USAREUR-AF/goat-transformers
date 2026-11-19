//! Fuzz-style runs of the device engine. The generator is seeded, so a run
//! repeats. `GT_FUZZ_SCALE` multiplies the iteration counts (default 1).
//!
//!   random_and_mutated_inputs_never_panic   random bytes, and vector inputs
//!       with bits flipped, through every bits format and four conversions
//!   differential_against_reference          the same kinds of input; the
//!       device result must be the reference engine's: equal bytes, or the
//!       same error kind
//!   truncated_inputs_match_reference        every proper prefix of every
//!       vector input
//!   corrupted_plans_never_panic             plan blobs with bytes changed

use gt_core::{Error, Plan};
use gt_proof::*;
use std::collections::BTreeMap;
use std::rc::Rc;

type Small = gt_core::Scratch<256>;

fn scale() -> usize {
    std::env::var("GT_FUZZ_SCALE").ok().and_then(|s| s.parse().ok()).unwrap_or(1)
}

/// Cross-format conversions with the context keys their targets need.
const PAIRS: [(&str, &str, &[&str]); 4] = [
    ("remote-id", "asterix-cat062", &["cat062.sac", "cat062.sic", "cat062.time_of_day_s", "cat062.track_number", "track.confirmed"]),
    ("mavlink2", "remote-id", &["rid.status", "rid.direction_raw", "rid.speed_h_raw", "rid.timestamp_ds"]),
    ("conformance-groups-bits-msb", "conformance-groups-bits-var", &[]),
    ("conformance-seq-msb", "conformance-seq-lsb", &[]),
];

struct Case {
    from: String,
    to: String,
    blob: Rc<Vec<u8>>,
    seeds: Vec<Vec<u8>>,
}

fn cases(p: &mut Proof) -> Vec<Case> {
    let vectors = p.vectors();
    let mut specs: Vec<(Option<String>, Option<String>, Vec<String>)> =
        p.bits_formats().into_iter().map(|f| (Some(f.clone()), Some(f), Vec::new())).collect();
    for (from, to, ctx) in PAIRS {
        specs.push((Some(from.into()), Some(to.into()), ctx.iter().map(|s| s.to_string()).collect()));
    }
    p.compile(&specs);
    let mut out = Vec::new();
    for (from, to, ctx) in specs {
        let (from, to) = (from.unwrap(), to.unwrap());
        let blob = match p.plan(Some(&from), Some(&to), &ctx) {
            Ok(b) => b,
            // a format that uses a feature outside the device profile has no plan
            Err(e) if e.contains("refused: unsupported-feature:") => continue,
            Err(e) => panic!("{} -> {}: {}", from, to, e),
        };
        let seeds = vectors.iter().filter(|v| v.from == from).filter_map(|v| unhex(&v.input)).collect();
        out.push(Case { from, to, blob, seeds });
    }
    out
}

/// A random message, or a vector input with a few bits flipped, a byte
/// replaced, or its tail cut or extended.
fn input(rng: &mut Rng, seeds: &[Vec<u8>]) -> Vec<u8> {
    if seeds.is_empty() || rng.below(3) == 0 {
        let n = rng.below(81);
        return rng.bytes(n);
    }
    let mut m = seeds[rng.below(seeds.len())].clone();
    for _ in 0..1 + rng.below(4) {
        match rng.below(4) {
            0 if !m.is_empty() => {
                let i = rng.below(m.len());
                m[i] ^= 1 << rng.below(8);
            }
            1 if !m.is_empty() => {
                let i = rng.below(m.len());
                m[i] = rng.next() as u8;
            }
            2 => m.truncate(rng.below(m.len() + 1)),
            _ => {
                let extra = rng.below(6);
                m.extend(rng.bytes(extra));
            }
        }
    }
    m
}

#[test]
fn random_and_mutated_inputs_never_panic() {
    let mut p = Proof::new();
    let cases = cases(&mut p);
    let mut scratch = Box::new(Small::new());
    let mut out = vec![0u8; 4096];
    let mut rng = Rng(0x9E37_79B9_7F4A_7C15);
    let per_case = 11_000 * scale();
    let mut results: BTreeMap<&'static str, usize> = BTreeMap::new();
    let mut total = 0usize;
    for c in &cases {
        let plan = Plan::parse(&c.blob).expect("plan");
        for _ in 0..per_case {
            let m = input(&mut rng, &c.seeds);
            let name = match gt_core::convert(&plan, &m, &mut out, &mut scratch, &[]) {
                Ok(n) => {
                    assert!(n <= out.len());
                    "ok"
                }
                Err(e) => e.name(),
            };
            *results.entry(name).or_default() += 1;
            total += 1;
        }
    }
    eprintln!("fuzz: {} inputs through {} plans, no panic. results: {:?}", total, cases.len(), results);
    assert!(results.get("bad-plan").is_none(), "a compiled plan was refused as bad");
}

#[test]
fn differential_against_reference() {
    let mut p = Proof::new();
    let cases = cases(&mut p);
    let mut scratch = Box::new(Scratch::new());
    let mut out = vec![0u8; 1 << 16];
    let mut rng = Rng(0x0123_4567_89AB_CDEF);
    let per_case = 1_500 * scale();
    let (mut total, mut same_ok, mut same_err, mut capacity) = (0usize, 0usize, 0usize, 0usize);
    let mut differ = Vec::new();
    for c in &cases {
        // the four conversions need a context; the reference takes the same one
        let ctx_text: Vec<(String, String)> = PAIRS
            .iter()
            .find(|(f, t, _)| *f == c.from && *t == c.to)
            .map(|(_, _, keys)| keys.iter().map(|k| (k.to_string(), "1".to_string())).collect())
            .unwrap_or_default();
        let typed = p.engine.context_from_text(&ctx_text).expect("context");
        let plan = Plan::parse(&c.blob).expect("plan");
        let ctx = device_context(&plan, &typed);
        let given = (!ctx_text.is_empty()).then_some(ctx_text.as_slice());
        for _ in 0..per_case {
            let m = input(&mut rng, &c.seeds);
            let want = p.engine.convert_text(&c.from, &c.to, &hex(&m), given);
            let got = gt_core::convert(&plan, &m, &mut out, &mut scratch, &ctx);
            total += 1;
            match (want, got) {
                (Ok(w), Ok(n)) if w == hex(&out[..n]) => same_ok += 1,
                (Err(e), Err(d)) if kind_of(&e) == d.name() => same_err += 1,
                (_, Err(Error::ScratchFull | Error::OutputFull)) => capacity += 1,
                (w, g) => {
                    if differ.len() < 20 {
                        differ.push(format!(
                            "{} -> {} input {}: reference {:?}, device {:?}",
                            c.from,
                            c.to,
                            hex(&m),
                            w.map_err(|e| e.msg),
                            g.map(|n| hex(&out[..n]))
                        ));
                    }
                }
            }
        }
    }
    eprintln!(
        "differential: {} inputs through {} plans: {} equal outputs, {} equal error kinds, {} beyond the device's buffers, {} differ",
        total,
        cases.len(),
        same_ok,
        same_err,
        capacity,
        total - same_ok - same_err - capacity
    );
    for d in &differ {
        eprintln!("DIFFER {}", d);
    }
    assert!(differ.is_empty(), "the device and the reference engine differ");
}

#[test]
fn truncated_inputs_match_reference() {
    let mut p = Proof::new();
    let vectors = p.vectors();
    let formats = p.bits_formats();
    p.compile(&formats.iter().map(|f| (Some(f.clone()), Some(f.clone()), Vec::new())).collect::<Vec<_>>());
    let mut scratch = Box::new(Scratch::new());
    let mut out = vec![0u8; 1 << 16];
    let (mut total, mut errors, mut accepted) = (0usize, 0usize, 0usize);
    let mut differ = Vec::new();
    for v in vectors.iter().filter(|v| v.from == v.to && v.expect.is_some() && v.context.is_none()) {
        if !p.is_bits(&v.from) {
            continue;
        }
        let full = match unhex(&v.input) {
            Some(b) => b,
            None => continue,
        };
        let blob = match p.plan(Some(&v.from), Some(&v.to), &[]) {
            Ok(b) => b,
            Err(e) if e.contains("refused: unsupported-feature:") => continue,
            Err(e) => panic!("plan: {}", e),
        };
        let plan = Plan::parse(&blob).expect("plan");
        for cut in 0..full.len() {
            let m = &full[..cut];
            let want = p.engine.convert(&v.from, &v.to, &hex(m));
            let got = gt_core::convert(&plan, m, &mut out, &mut scratch, &[]);
            total += 1;
            match (want, got) {
                (Ok(w), Ok(n)) if w == hex(&out[..n]) => accepted += 1,
                (Err(e), Err(d)) if kind_of(&e) == d.name() => errors += 1,
                (w, g) => differ.push(format!(
                    "{}/{} cut to {} bytes: reference {:?}, device {:?}",
                    v.pack,
                    v.name,
                    cut,
                    w.map_err(|e| e.msg),
                    g.map(|n| hex(&out[..n]))
                )),
            }
        }
    }
    eprintln!(
        "truncation: {} prefixes of vector inputs: {} refused with the reference's error kind, {} accepted with the reference's bytes (a shorter message of the format), {} differ",
        total,
        errors,
        accepted,
        differ.len()
    );
    for d in differ.iter().take(20) {
        eprintln!("DIFFER {}", d);
    }
    assert!(differ.is_empty());
    assert!(errors > 0);
}

#[test]
fn corrupted_plans_never_panic() {
    let mut p = Proof::new();
    let cases = cases(&mut p);
    let mut scratch = Box::new(Small::new());
    let mut out = vec![0u8; 4096];
    let mut rng = Rng(0xDEAD_BEEF_0BAD_F00D);
    let per_case = 2_000 * scale();
    let (mut total, mut parsed) = (0usize, 0usize);
    for c in &cases {
        for _ in 0..per_case {
            let mut blob = (*c.blob).clone();
            for _ in 0..1 + rng.below(4) {
                let i = rng.below(blob.len());
                blob[i] = rng.next() as u8;
            }
            let m = input(&mut rng, &c.seeds);
            total += 1;
            if let Ok(plan) = Plan::parse(&blob) {
                parsed += 1;
                let _ = gt_core::convert(&plan, &m, &mut out, &mut scratch, &[]);
            }
        }
    }
    eprintln!("corrupted plans: {} blobs, {} still parsed and were run, no panic", total, parsed);
}
