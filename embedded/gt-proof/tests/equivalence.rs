//! Equivalence with the reference engine on the repository's vectors.
//!
//! Three groups, by which side of a vector is on the `bits` wire:
//!
//!   bits to bits   the device converts the input; the output is compared
//!                  byte for byte with the vector's `expect` (or its error
//!                  kind with `expect_error`), and the decoded values with
//!                  the reference engine's
//!   bits to text   the device decodes the input; every value it holds is
//!                  compared with the reference engine's decode, and the
//!                  vector's `model` values are checked
//!   text to bits   the reference engine decodes the text side; the device
//!                  takes those model values, fills the context, derives and
//!                  encodes; the output is compared byte for byte with the
//!                  vector's `expect` (or its error kind)
//!
//! A vector whose plan the compiler refuses does not qualify and is listed
//! with the reason. Counts are printed per pack.

use gt_core::{Plan, Session, ROOT};
use gt_proof::*;
use std::collections::BTreeMap;

#[derive(Default)]
struct Tally {
    qualify: usize,
    pass: usize,
}

/// The item scope a `<list>[<i>].` path names, and the rest of the path.
fn walk<'k>(s: &Session, plan: &Plan, key: &'k str) -> Result<(gt_core::Scope, &'k str), String> {
    let mut scope = ROOT;
    let mut rest = key;
    while let Some(open) = rest.find('[') {
        let close = rest.find(']').ok_or("no `]`")?;
        let list = plan.find_key(&rest[..open]).ok_or(format!("`{}`: list not in the plan", key))?;
        let index: u16 = rest[open + 1..close].parse().map_err(|_| "bad index")?;
        scope = s.list_item(scope, list, index).ok_or(format!("`{}`: no such item", key))?;
        rest = &rest[close + 2..];
    }
    Ok((scope, rest))
}

fn check_model(s: &Session, plan: &Plan, v: &Vector) -> Result<(), String> {
    // `"@absent"`: the key, the item's key or the list is not held; a name the
    // plan has no id for cannot be held
    for key in &v.absent {
        let (scope, rest) = walk(s, plan, key)?;
        if let Some(k) = plan.find_key(rest) {
            if let Some(got) = s.get(scope, k) {
                return Err(format!("`@absent` `{}` = {}", key, text_of(s, got)));
            }
            if let Some(n) = s.list(scope, k) {
                return Err(format!("`@absent` list `{}` has {} items", key, n));
            }
        }
    }
    for (key, want) in &v.model {
        // walk `<list>[<i>].` steps
        let (scope, rest) = walk(s, plan, key)?;
        if rest == "@kind" {
            if s.kind_name(scope) != Some(want.as_str()) {
                return Err(format!("`{}`: kind {:?}, want {}", key, s.kind_name(scope), want));
            }
            continue;
        }
        if let Some(list) = rest.strip_suffix(".#") {
            let k = plan.find_key(list).ok_or(format!("`{}`: list not in the plan", key))?;
            let got = s.list(scope, k).map_or("absent".to_string(), |n| n.to_string());
            if got != *want {
                return Err(format!("`{}` = {}, want {}", key, got, want));
            }
            continue;
        }
        let k = plan.find_key(rest).ok_or(format!("`{}`: key not in the plan", key))?;
        let got = s.get(scope, k).ok_or(format!("`{}` absent after decode", key))?;
        let ok = match (got, want.parse::<f64>()) {
            (gt_core::Got::Float(a), Ok(b)) => a == b || (a - b).abs() < 1e-9,
            _ => text_of(s, got) == *want,
        };
        if !ok {
            return Err(format!("`{}` = {}, want {}", key, text_of(s, got), want));
        }
    }
    Ok(())
}

/// One vector. Ok(false): it does not qualify (the reason is recorded).
fn run(p: &mut Proof, v: &Vector, scratch: &mut Scratch, skipped: &mut Vec<String>) -> Result<bool, String> {
    let (fb, tb) = (p.is_bits(&v.from), p.is_bits(&v.to));
    let ctx_keys: Vec<String> = v.context.iter().flatten().map(|(k, _)| k.clone()).collect();
    let mut skip = |why: String| {
        skipped.push(format!("{}/{} ({} -> {}): {}", v.pack, v.name, v.from, v.to, why));
        Ok(false)
    };
    let typed = match p.engine.context_from_text(v.context.as_deref().unwrap_or(&[])) {
        Ok(t) => t,
        Err(e) => return skip(format!("the context is refused before the bits side runs ({})", kind_of(&e))),
    };
    let mut out = vec![0u8; 1 << 16];
    if fb && tb {
        let input = match p.wire_in(&v.from, &v.input) {
            Some(b) => b,
            None => return skip("the input is not hex text; the device takes bytes".into()),
        };
        let blob = match p.plan(Some(&v.from), Some(&v.to), &ctx_keys) {
            Ok(b) => b,
            Err(why) => return skip(why),
        };
        let plan = Plan::parse(&blob).map_err(|e| format!("plan: {:?}", e))?;
        let ctx = device_context(&plan, &typed);
        let got = gt_core::convert_limited(
            &plan,
            &input,
            &mut out,
            scratch,
            v.context.as_ref().map(|_| ctx.as_slice()),
            v.max_items as u64,
        );
        match (&v.expect, &v.expect_error, got) {
            (Some(want), _, Ok(n)) if p.wire_out(&v.to, &out[..n]) == *want => {}
            (Some(want), _, Ok(n)) => return Err(format!("got {} want {}", p.wire_out(&v.to, &out[..n]), want)),
            (_, Some(kind), Err(e)) if e.name() == kind => {}
            // a device limit docs/embedded.md states: the proof's scratch
            // holds fewer items than the message
            (_, _, Err(gt_core::Error::ScratchFull)) => {
                return skip("scratch-full: the message holds more values or list items than the proof's scratch".into())
            }
            (_, _, got) => return Err(format!("got {:?}, want {:?}{:?}", got.map(|n| p.wire_out(&v.to, &out[..n])), v.expect, v.expect_error)),
        }
        // the decoded values, against the reference engine's and the vector's
        if let Ok(ent) = p.engine.decode_limited(&v.from, &v.input, v.max_items) {
            let dblob = p.plan(Some(&v.from), None, &[]).map_err(|e| format!("decode-only plan: {}", e))?;
            let dplan = Plan::parse(&dblob).map_err(|e| format!("plan: {:?}", e))?;
            let mut s = Session::new(&dplan, scratch);
            s.set_max_items(v.max_items as u64);
            s.decode(&input).map_err(|e| format!("device decode: {:?}", e))?;
            same_entity(&s, &dplan, ROOT, &ent, 0.0)?;
            let want = ent.kind.as_ref().map(|(_, n)| n.as_str());
            if s.kind_name(ROOT) != want {
                return Err(format!("kind {:?}, reference {:?}", s.kind_name(ROOT), want));
            }
            if !v.complete {
                check_model(&s, &dplan, v)?;
            }
        }
        return Ok(true);
    }
    if fb {
        // bits to text: the decode side
        let input = match p.wire_in(&v.from, &v.input) {
            Some(b) => b,
            None => return skip("the input is not hex text; the device takes bytes".into()),
        };
        let blob = match p.plan(Some(&v.from), None, &[]) {
            Ok(b) => b,
            Err(why) => return skip(why),
        };
        let plan = Plan::parse(&blob).map_err(|e| format!("plan: {:?}", e))?;
        let mut s = Session::new(&plan, scratch);
        s.set_max_items(v.max_items as u64);
        return match (p.engine.decode_limited(&v.from, &v.input, v.max_items), s.decode(&input)) {
            (Ok(ent), Ok(())) => {
                same_entity(&s, &plan, ROOT, &ent, 0.0)?;
                let want = ent.kind.as_ref().map(|(_, n)| n.as_str());
                if s.kind_name(ROOT) != want {
                    return Err(format!("kind {:?}, reference {:?}", s.kind_name(ROOT), want));
                }
                if !v.complete {
                    check_model(&s, &plan, v)?;
                }
                Ok(true)
            }
            (Err(e), Err(d)) if kind_of(&e) == d.name() => Ok(true),
            // a device limit docs/embedded.md states: the proof's scratch
            // holds fewer items than the message
            (_, Err(gt_core::Error::ScratchFull)) => skip("scratch-full: the message holds more values or list items than the proof's scratch".into()),
            (r, d) => Err(format!("decode: reference {:?}, device {:?}", r.map(|_| "ok").map_err(|e| e.msg), d)),
        };
    }
    // text to bits: the encode side, from the reference engine's model values
    let mut ent = match p.engine.decode_limited(&v.from, &v.input, v.max_items) {
        Ok(e) => e,
        Err(e) => return skip(format!("the text side fails to decode ({}); the bits side does not run", kind_of(&e))),
    };
    ent.kind = None;
    let blob = match p.plan(None, Some(&v.to), &ctx_keys) {
        Ok(b) => b,
        Err(why) => return skip(why),
    };
    let plan = Plan::parse(&blob).map_err(|e| format!("plan: {:?}", e))?;
    let ctx = device_context(&plan, &typed);
    let mut texts = Vec::new();
    texts_of(&ent, &mut texts);
    let mut s = Session::new(&plan, scratch);
    s.set_texts(&texts);
    let got = (|| {
        inject(&mut s, &plan, ROOT, &ent, &mut 0)?;
        s.fill(&ctx)?;
        s.complete()?;
        s.encode(&mut out)
    })();
    match (&v.expect, &v.expect_error, got) {
        (Some(want), _, Ok(n)) if p.wire_out(&v.to, &out[..n]) == *want => Ok(true),
        (Some(want), _, Ok(n)) => Err(format!("got {} want {}", p.wire_out(&v.to, &out[..n]), want)),
        (_, Some(kind), Err(e)) if e.name() == kind => Ok(true),
        (_, _, got) => Err(format!("got {:?}, want {:?}{:?}", got.map(|n| p.wire_out(&v.to, &out[..n])), v.expect, v.expect_error)),
    }
}

#[test]
fn vectors() {
    let mut p = Proof::new();
    let mut scratch = Box::new(Scratch::new());
    let mut tallies: BTreeMap<(String, &'static str), Tally> = BTreeMap::new();
    let mut failures = Vec::new();
    let mut skipped = Vec::new();
    let vectors = p.vectors();
    // every plan the vectors need, in one run of the compiler
    let mut specs = Vec::new();
    for v in &vectors {
        let (fb, tb) = (p.is_bits(&v.from), p.is_bits(&v.to));
        let ctx: Vec<String> = v.context.iter().flatten().map(|(k, _)| k.clone()).collect();
        if fb {
            specs.push((Some(v.from.clone()), None, Vec::new()));
        }
        if fb && tb {
            specs.push((Some(v.from.clone()), Some(v.to.clone()), ctx));
        } else if tb {
            specs.push((None, Some(v.to.clone()), ctx));
        }
    }
    p.compile(&specs);
    for v in vectors {
        let (fb, tb) = (p.is_bits(&v.from), p.is_bits(&v.to));
        if !fb && !tb {
            continue;
        }
        let group = match (fb, tb) {
            (true, true) => "bits to bits",
            (true, false) => "bits to text",
            _ => "text to bits",
        };
        match run(&mut p, &v, &mut scratch, &mut skipped) {
            Ok(false) => {}
            Ok(true) => {
                let t = tallies.entry((v.pack.clone(), group)).or_default();
                t.qualify += 1;
                t.pass += 1;
            }
            Err(why) => {
                tallies.entry((v.pack.clone(), group)).or_default().qualify += 1;
                failures.push(format!("{}/{} ({} -> {}): {}", v.pack, v.name, v.from, v.to, why));
            }
        }
    }
    let mut totals: BTreeMap<&str, Tally> = BTreeMap::new();
    eprintln!("{:<34} {:<13} {:>8} {:>6}", "pack", "group", "qualify", "pass");
    for ((pack, group), t) in &tallies {
        eprintln!("{:<34} {:<13} {:>8} {:>6}", pack, group, t.qualify, t.pass);
        let sum = totals.entry(group).or_default();
        sum.qualify += t.qualify;
        sum.pass += t.pass;
    }
    for (group, t) in &totals {
        eprintln!("{:<34} {:<13} {:>8} {:>6}", "TOTAL", group, t.qualify, t.pass);
    }
    eprintln!("not qualifying: {}", skipped.len());
    for s in &skipped {
        eprintln!("  {}", s);
    }
    for f in &failures {
        eprintln!("FAIL {}", f);
    }
    // A vector may stay out only for a reason the profile states: a feature it
    // does not have, an input that is not hex text, or a context the reference
    // engine refuses. Any other refusal of the compiler is a failure.
    let stated = |s: &String| {
        s.contains("refused: unsupported-feature:") || s.contains("the input is not hex text") || s.contains("): scratch-full: ")
            || s.contains("the context is refused before the bits side runs")
    };
    let unstated: Vec<&String> = skipped.iter().filter(|s| !stated(s)).collect();
    assert!(unstated.is_empty(), "{} vectors left out for a reason the profile does not state: {:?}", unstated.len(), unstated);
    assert!(failures.is_empty(), "{} vectors failed", failures.len());
    assert!(totals.values().map(|t| t.pass).sum::<usize>() > 0, "no vector ran");
}
