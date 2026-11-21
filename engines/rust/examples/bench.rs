//! The benchmark of engine-spec 0.25 (ruling 2).
//!
//! ```text
//! cargo run --release --manifest-path engines/rust/Cargo.toml --example bench -- bench/set.json
//! ```
//!
//! Run from the repository root (a vector's path is read as written in the
//! set). It loads only the packs the set's vectors name (`from` and `to`), and
//! the model modules those packs use, into one engine, and times that. For
//! each vector in order it converts the input once and checks the output
//! against `expect` (a difference fails the run, on standard error, exit 1),
//! then converts it `iterations` times and times that. Standard output holds
//! one JSON line per vector, then one for the load, and nothing else.
//!
//! A vector `packs/<name>/vectors/<file>` gives the pack directory `packs`;
//! the pack of a format is `packs/<format>/pack.def` and a model module is
//! `<packs>/../model/<module>.def`.

use goat_transformers::json::{self, Json};
use goat_transformers::Engine;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::process::exit;
use std::time::Instant;

fn fail(msg: impl AsRef<str>) -> ! {
    eprintln!("bench: {}", msg.as_ref());
    exit(1)
}

fn read(p: &Path) -> String {
    std::fs::read_to_string(p).unwrap_or_else(|e| fail(format!("cannot read {}: {}", p.display(), e)))
}

fn jstr<'a>(o: &'a Json, k: &str) -> Option<&'a str> {
    match o.get(k) {
        Some(Json::Str(s)) => Some(s.as_str()),
        _ => None,
    }
}

/// The values of every `<word> <value>` line of a pack or module text.
fn lines_of(text: &str, word: &str) -> Vec<String> {
    text.lines()
        .filter_map(|l| {
            let t: Vec<&str> = l.split_whitespace().collect();
            match t.as_slice() {
                [w, v] if *w == word => Some(v.to_string()),
                _ => None,
            }
        })
        .collect()
}

struct Vector {
    path: String,
    from: String,
    to: String,
    input: String,
    context: Option<Vec<(String, String)>>,
    expect: String,
}

fn vector(path: &str) -> Vector {
    let v = json::parse(&read(Path::new(path))).unwrap_or_else(|e| fail(format!("{}: not JSON: {}", path, e)));
    let field = |k: &str| jstr(&v, k).unwrap_or_else(|| fail(format!("{}: no `{}`", path, k))).to_string();
    let context = match v.get("context") {
        None => None,
        Some(Json::Obj(members)) => Some(
            members
                .iter()
                .map(|(k, cv)| match cv {
                    Json::Str(s) => (k.clone(), s.clone()),
                    _ => fail(format!("{}: context value of `{}` is not a string", path, k)),
                })
                .collect(),
        ),
        Some(_) => fail(format!("{}: `context` is not an object", path)),
    };
    Vector {
        path: path.to_string(),
        from: field("from"),
        to: field("to"),
        input: field("input"),
        context,
        expect: field("expect"),
    }
}

/// The pack directory of a vector `<packs>/<name>/vectors/<file>`.
fn packs_dir(path: &str) -> PathBuf {
    Path::new(path)
        .ancestors()
        .nth(3)
        .unwrap_or_else(|| fail(format!("{}: not <packs>/<name>/vectors/<file>", path)))
        .to_path_buf()
}

/// Load the named packs and the modules they use, each file read once:
/// `core` first, then each module after the modules it uses (as
/// `load_model_dir` orders a directory), then the packs in byte order of name.
fn load(packs: &Path, formats: &BTreeSet<String>) -> Engine {
    let models = packs.join("../model");
    let mut pack_texts: Vec<(PathBuf, String)> = Vec::new();
    let mut wanted: Vec<String> = vec!["core".to_string()];
    for f in formats {
        let p = packs.join(f).join("pack.def");
        let text = read(&p);
        wanted.extend(lines_of(&text, "uses"));
        pack_texts.push((p, text));
    }
    // every module used, and every module those use, each read once
    let mut modules: BTreeMap<String, (String, Vec<String>)> = BTreeMap::new();
    while let Some(m) = wanted.pop() {
        if modules.contains_key(&m) {
            continue;
        }
        let text = read(&models.join(format!("{}.def", m)));
        let uses = lines_of(&text, "uses");
        wanted.extend(uses.iter().cloned());
        modules.insert(m, (text, uses));
    }
    let mut e = Engine::new();
    let mut loaded: BTreeSet<String> = BTreeSet::new();
    let mut order: Vec<String> = modules.keys().cloned().collect();
    order.sort_by_key(|m| (m != "core", m.clone()));
    while loaded.len() < order.len() {
        let next = order
            .iter()
            .find(|m| !loaded.contains(*m) && modules[*m].1.iter().all(|u| u == *m || loaded.contains(u)))
            .unwrap_or_else(|| fail("the `uses` lines of the model modules form a cycle"))
            .clone();
        e.load_model(&modules[&next].0).unwrap_or_else(|err| fail(format!("module `{}`: {}", next, err)));
        loaded.insert(next);
    }
    for (p, text) in &pack_texts {
        e.load_def(text).unwrap_or_else(|err| fail(format!("{}: {}", p.display(), err)));
    }
    e
}

fn main() {
    let set_path = std::env::args().nth(1).unwrap_or_else(|| "bench/set.json".to_string());
    let set = json::parse(&read(Path::new(&set_path))).unwrap_or_else(|e| fail(format!("{}: not JSON: {}", set_path, e)));
    let iterations = match set.get("iterations") {
        Some(Json::Int(n)) if *n > 0 => *n as u64,
        _ => fail(format!("{}: `iterations` must be an integer above 0", set_path)),
    };
    let vectors: Vec<Vector> = match set.get("vectors") {
        Some(Json::Arr(items)) => items
            .iter()
            .map(|i| match i {
                Json::Str(s) => vector(s),
                _ => fail(format!("{}: a vector is a path", set_path)),
            })
            .collect(),
        _ => fail(format!("{}: no `vectors` array", set_path)),
    };
    if vectors.is_empty() {
        fail(format!("{}: no vector", set_path));
    }
    let packs = packs_dir(&vectors[0].path);
    if let Some(v) = vectors.iter().find(|v| packs_dir(&v.path) != packs) {
        fail(format!("{}: not under {}", v.path, packs.display()));
    }
    let formats: BTreeSet<String> = vectors.iter().flat_map(|v| [v.from.clone(), v.to.clone()]).collect();

    let t = Instant::now();
    let engine = load(&packs, &formats);
    let load_ns = t.elapsed().as_nanos();

    let mut out = String::new();
    for v in &vectors {
        let convert = || engine.convert_text(&v.from, &v.to, &v.input, v.context.as_deref());
        match convert() {
            Ok(got) if got == v.expect => {}
            Ok(got) => fail(format!("{}: output differs\n  got  {}\n  want {}", v.path, got, v.expect)),
            Err(e) => fail(format!("{}: convert failed: {}", v.path, e)),
        }
        let t = Instant::now();
        for _ in 0..iterations {
            std::hint::black_box(convert().ok());
        }
        let ns = t.elapsed().as_nanos();
        out.push_str(&format!(
            "{{\"vector\": {}, \"iterations\": {}, \"ns_per_op\": {}}}\n",
            json::serialize(&Json::Str(v.path.clone())),
            iterations,
            ns / iterations as u128
        ));
    }
    out.push_str(&format!("{{\"load\": {}, \"ns\": {}}}\n", formats.len(), load_ns));
    print!("{}", out);
}
