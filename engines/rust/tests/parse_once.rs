//! Engine-spec 0.25, ruling 1: an engine instance keeps what it parsed and
//! computed at load, and keeping changes nothing that can be observed.
//!
//! - 1b: every conversion vector of the repository, failing ones included,
//!   gives the same output or the same error message on one instance that
//!   has converted every other vector before, whatever the order, as in line
//!   order; and each vector of `bench/set.json`, and one failing vector of
//!   each wire, gives on a new instance (every module, the vector's two
//!   packs) the result it gave on the instance with every pack, which had
//!   converted every vector before it.
//! - 1c: one instance used from several threads at once, each thread taking
//!   the vectors in its own order, gives each conversion that same result.
//! - 1d: a second load of the same pack or module into the instance is
//!   `duplicate-format` or `duplicate-module`, as before.
//!
//! A debug build (CI's `cargo test`) runs the reverse order and the threads
//! on every eighth vector and every failing one, after converting them all
//! once, and a new instance for the failing vectors only; `cargo test
//! --release` runs everything.
//!
//! In a build with fewer wires (engine-spec 0.24) a pack on a wire the build
//! lacks is not loaded and a vector naming one is not run.

use goat_transformers::json::{self, Json};
use goat_transformers::{Engine, Wire};
use std::path::{Path, PathBuf};

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..").canonicalize().expect("repository root")
}

fn jstr<'a>(o: &'a Json, k: &str) -> Option<&'a str> {
    match o.get(k) {
        Some(Json::Str(s)) => Some(s.as_str()),
        _ => None,
    }
}

/// The wire a pack text names, when this build lacks it.
fn unbuilt(text: &str) -> bool {
    let built = goat_transformers::build_wires();
    text.lines().any(|l| {
        let t: Vec<&str> = l.split_whitespace().collect();
        matches!(t.as_slice(), ["wire", w] if Wire::from_name(w).is_some() && !built.contains(w))
    })
}

/// One conversion as a vector states it.
#[derive(Clone)]
struct Conv {
    name: String,
    from: String,
    to: String,
    input: String,
    context: Option<Vec<(String, String)>>,
    max_items: usize,
}

/// The result as it can be observed: the output, or the whole error message.
type Outcome = Result<String, String>;

fn run(e: &Engine, c: &Conv) -> Outcome {
    e.convert_text_limited(&c.from, &c.to, &c.input, c.context.as_deref(), c.max_items).map_err(|err| err.msg)
}

fn conv(name: String, v: &Json) -> Option<Conv> {
    let context = match v.get("context") {
        Some(Json::Obj(m)) => Some(
            m.iter()
                .map(|(k, cv)| match cv {
                    Json::Str(s) => Some((k.clone(), s.clone())),
                    _ => None,
                })
                .collect::<Option<Vec<_>>>()?,
        ),
        Some(_) => return None,
        None => None,
    };
    let max_items = match v.get("max_items") {
        None => goat_transformers::DEFAULT_MAX_ITEMS,
        Some(Json::Int(n)) if *n >= 0 => *n as usize,
        Some(_) => return None,
    };
    Some(Conv {
        name,
        from: jstr(v, "from")?.to_string(),
        to: jstr(v, "to")?.to_string(),
        input: jstr(v, "input")?.to_string(),
        context,
        max_items,
    })
}

/// The formats of the packs this build leaves out.
fn unbuilt_formats(packs: &Path) -> Vec<String> {
    let mut out = Vec::new();
    for d in std::fs::read_dir(packs).unwrap().flatten() {
        if let Ok(text) = std::fs::read_to_string(d.path().join("pack.def")) {
            if unbuilt(&text) {
                out.push(d.file_name().to_string_lossy().into_owned());
            }
        }
    }
    out
}

/// Every conversion vector under packs/, in path order (the name is the path
/// from the repository root).
fn all_vectors(root: &Path) -> Vec<(Conv, Json)> {
    let packs = root.join("packs");
    let left_out = unbuilt_formats(&packs);
    let mut dirs: Vec<PathBuf> = std::fs::read_dir(&packs).unwrap().flatten().map(|e| e.path()).collect();
    dirs.sort();
    let mut out = Vec::new();
    for dir in dirs {
        let vdir = dir.join("vectors");
        let mut files: Vec<PathBuf> = match std::fs::read_dir(&vdir) {
            Ok(rd) => rd.flatten().map(|e| e.path()).filter(|p| p.extension().is_some_and(|x| x == "json")).collect(),
            Err(_) => continue,
        };
        files.sort();
        for f in files {
            let v = match json::parse(&std::fs::read_to_string(&f).unwrap()) {
                Ok(v) => v,
                Err(_) => continue,
            };
            let name = f.strip_prefix(root).unwrap().to_string_lossy().into_owned();
            if let Some(c) = conv(name, &v) {
                if !left_out.contains(&c.from) && !left_out.contains(&c.to) {
                    out.push((c, v));
                }
            }
        }
    }
    out
}

/// An instance with every module and every pack this build has.
fn load_all(root: &Path) -> Engine {
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).expect("model");
    let mut dirs: Vec<PathBuf> = std::fs::read_dir(root.join("packs")).unwrap().flatten().map(|e| e.path()).collect();
    dirs.sort();
    for d in dirs {
        if let Ok(text) = std::fs::read_to_string(d.join("pack.def")) {
            if !unbuilt(&text) {
                // a pack that does not load is the business of tests/vectors.rs
                let _ = e.load_def(&text);
            }
        }
    }
    e
}

/// An instance with every module and only the packs of one conversion.
fn load_pair(root: &Path, c: &Conv) -> Engine {
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).expect("model");
    e.load_pack_dir_only(&root.join("packs"), &[c.from.as_str(), c.to.as_str()]).expect("the vector's packs");
    e
}

fn differences(what: &str, convs: &[Conv], want: &[Outcome], got: &[Outcome]) -> Vec<String> {
    convs
        .iter()
        .zip(want.iter().zip(got))
        .filter(|(_, (w, g))| w != g)
        .map(|(c, (w, g))| format!("{}: {}\n      first  {:?}\n      then   {:?}", what, c.name, w, g))
        .collect()
}

#[test]
fn engine_is_send_and_sync() {
    fn both<T: Send + Sync>() {}
    both::<Engine>();
}

#[test]
fn kept_layout_changes_nothing_across_orders_instances_and_threads() {
    let root = repo();
    let vectors = all_vectors(&root);
    let convs: Vec<Conv> = vectors.iter().map(|(c, _)| c.clone()).collect();
    assert!(convs.len() > 1000, "only {} conversion vectors found", convs.len());
    let failing = vectors.iter().filter(|(_, v)| v.get("expect_error").is_some()).count();
    assert!(failing > 0, "no failing vector among {}", convs.len());
    let engine = load_all(&root);
    let mut problems: Vec<String> = Vec::new();

    // 1b: in line order, then in reverse order on the same instance, which by
    // then has converted every vector once
    let all_first: Vec<Outcome> = convs.iter().map(|c| run(&engine, c)).collect();
    let stride = if cfg!(debug_assertions) { 8 } else { 1 };
    let (convs, first): (Vec<Conv>, Vec<Outcome>) = convs
        .iter()
        .zip(&all_first)
        .enumerate()
        .filter(|(i, _)| i % stride == 0 || vectors[*i].1.get("expect_error").is_some())
        .map(|(_, (c, o))| (c.clone(), o.clone()))
        .unzip();
    let mut again: Vec<Outcome> = convs.iter().rev().map(|c| run(&engine, c)).collect();
    again.reverse();
    problems.extend(differences("reverse order", &convs, &first, &again));

    // 1c: several threads at once on the one instance, each starting at its
    // own place and going round
    let threads = 4;
    let n = convs.len();
    let per_thread: Vec<Vec<Outcome>> = std::thread::scope(|s| {
        let handles: Vec<_> = (0..threads)
            .map(|t| {
                let (engine, convs) = (&engine, &convs);
                s.spawn(move || {
                    let start = t * n / threads;
                    let mut out: Vec<Option<Outcome>> = vec![None; n];
                    for k in 0..n {
                        let i = (start + k) % n;
                        out[i] = Some(run(engine, &convs[i]));
                    }
                    out.into_iter().map(|o| o.expect("every vector run")).collect()
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().expect("thread")).collect()
    });
    for (t, got) in per_thread.iter().enumerate() {
        problems.extend(differences(&format!("thread {}", t), &convs, &first, got));
    }

    // 1b: a new instance, for each vector of the benchmark set and for one
    // failing vector of each wire, against the first pass above
    let set = json::parse(&std::fs::read_to_string(root.join("bench/set.json")).unwrap()).unwrap();
    let mut fresh: Vec<usize> = match set.get("vectors") {
        // a debug build reads a catalog pack slowly: the failing vectors only
        _ if cfg!(debug_assertions) => Vec::new(),
        Some(Json::Arr(items)) => items
            .iter()
            .filter_map(|i| match i {
                Json::Str(p) => vectors.iter().position(|(c, _)| &c.name == p),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    };
    let mut wires_seen: Vec<Wire> = Vec::new();
    for (i, (c, v)) in vectors.iter().enumerate() {
        if v.get("expect_error").is_none() {
            continue;
        }
        if let Some(w) = engine.wire(&c.from) {
            if !wires_seen.contains(&w) {
                wires_seen.push(w);
                fresh.push(i);
            }
        }
    }
    for i in fresh {
        let c = &vectors[i].0;
        let got = run(&load_pair(&root, c), c);
        if got != all_first[i] {
            problems.push(format!("new instance: {}\n      new    {:?}\n      used   {:?}", c.name, got, all_first[i]));
        }
    }

    if !problems.is_empty() {
        for p in &problems {
            eprintln!("  FAIL {}", p);
        }
        panic!("{} differences over {} conversion vectors", problems.len(), n);
    }
    println!(
        "ran {} conversion vectors ({} failing) in line order, then {} of them in reverse and on {} threads at once: no difference",
        vectors.len(),
        failing,
        n,
        threads
    );
}

#[test]
fn second_load_is_still_a_duplicate() {
    let root = repo();
    let mut e = Engine::new();
    e.load_model_dir(&root.join("model")).expect("model");
    let core = std::fs::read_to_string(root.join("model/core.def")).unwrap();
    let err = e.load_model(&core).expect_err("a second core");
    assert!(err.msg.starts_with("duplicate-module:"), "{}", err.msg);
    for name in ["cot-xml", "geojson"] {
        let text = std::fs::read_to_string(root.join("packs").join(name).join("pack.def")).unwrap();
        if unbuilt(&text) {
            continue;
        }
        e.load_def(&text).expect("first load");
        let before = e.convert_text(name, name, "", None).map_err(|x| x.msg);
        let err = e.load_def(&text).expect_err("a second load");
        assert!(err.msg.starts_with("duplicate-format:"), "{}", err.msg);
        // the refused load leaves the first pack, and what it keeps, as they were
        assert_eq!(before, e.convert_text(name, name, "", None).map_err(|x| x.msg));
    }
}
