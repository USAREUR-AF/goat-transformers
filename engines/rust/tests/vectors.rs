//! Conformance: load every pack under packs/ and run every vector.
//! A vector is one JSON object (spec/vector-format.md). The reference engine
//! must reproduce `expect` from `convert(from, to, input)` (or fail with the
//! error kind in `expect_error`) and, if `model` is present, match each decoded
//! field and the selected kind (`"@kind"`). `context` is passed to `convert`;
//! with `"@complete": true` in `model` the checks run on the decoded entity
//! after the context is filled in and the derivations are applied. Every
//! failing vector is reported before the test fails. A model key `"<list>.#"`
//! is the number of items of a list (`"absent"`: the list is absent) and
//! `"<list>[<i>].<key>"` a value of one item, nested lists likewise;
//! `"<list>[<i>].@kind"` is the kind an item selected (engine-spec 0.8).
//! `"@absent"` is an array of keys, item paths `<list>[<i>].<key>` and list
//! names the entity must not have (engine-spec 0.9); a listed key that is also
//! a member of `model` makes the vector invalid, and it fails.
//! Version 0.11: `max_items` sets the limit on list items for one vector
//! (ruling 7); a `model` value is read by the grammar of its key's declared
//! type (ruling 2c), and a value that grammar refuses makes the vector
//! invalid; a load vector may carry `packs`; capability vectors pin
//! `capability(from, to)` (ruling 6).
//! Version 0.24: in a build with fewer wires (a Cargo feature per wire), a
//! pack on a wire the build lacks is not loaded, and a vector that names such
//! a pack (its `from` or `to`, a pack text of a load vector) is not run; the
//! count of vectors left out is printed. A build with all seven leaves out none.
//! Version 0.34: `"@inner_kind"` in `model` is the kind name of
//! `Entity.inner_kind`, and `"@absent"` may list it. Every pack is loaded, so
//! the packs `inner` lines name are loaded too.

use goat_transformers::json::Json;
use goat_transformers::{json, Distribution, Engine, Entity, Grade, KeyType, Value, Wire};
use std::path::{Path, PathBuf};

fn repo_packs_dir() -> PathBuf {
    // tests run with CWD = engines/rust
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../packs")
        .canonicalize()
        .expect("packs dir")
}

/// Engine-spec 0.24: the wire of the specification a pack text names that
/// this build does not have, if any (the value of its `wire` line).
fn unbuilt_wire(text: &str) -> Option<String> {
    let built = goat_transformers::build_wires();
    text.lines().find_map(|l| {
        let t: Vec<&str> = l.split_whitespace().collect();
        match t.as_slice() {
            ["wire", w] if Wire::from_name(w).is_some() && !built.contains(w) => Some(w.to_string()),
            _ => None,
        }
    })
}

/// The formats of the packs under packs/ that are on a wire this build does
/// not have (engine-spec 0.24); empty in a build with all seven wires.
fn unbuilt_formats() -> Vec<String> {
    let mut out = Vec::new();
    for d in std::fs::read_dir(repo_packs_dir()).unwrap().flatten() {
        if let Ok(text) = std::fs::read_to_string(d.path().join("pack.def")) {
            if unbuilt_wire(&text).is_some() {
                let format = text.lines().find_map(|l| l.trim().strip_prefix("format ").map(|f| f.trim().to_string()));
                out.extend(format);
            }
        }
    }
    out
}

/// Load every model module and every pack. A pack that fails to load is a
/// failure of the run, named; the other packs still load. A pack on a wire
/// this build does not have is left out (engine-spec 0.24).
fn load_engine() -> (Engine, Vec<(String, String)>) {
    let mut e = Engine::new();
    e.load_model_dir(&repo_packs_dir().join("../model")).unwrap_or_else(|err| panic!("model: {}", err));
    let mut failures = Vec::new();
    let mut dirs: Vec<_> = std::fs::read_dir(repo_packs_dir()).unwrap().flatten().map(|d| d.path()).collect();
    dirs.sort();
    for d in dirs {
        let def = d.join("pack.def");
        if let Ok(text) = std::fs::read_to_string(&def) {
            if unbuilt_wire(&text).is_some() {
                continue;
            }
            if let Err(err) = e.load_def(&text) {
                failures.push((format!("{}/pack.def", d.file_name().unwrap().to_string_lossy()), format!("load: {}", err)));
            }
        }
    }
    (e, failures)
}

/// The item path or key a `model` member names, reduced to its last key:
/// `a[0].b[1].c` is `c`. None for `<list>.#` and the `@` members.
fn last_key(member: &str) -> &str {
    match member.rfind("].") {
        Some(i) => &member[i + 2..],
        None => member,
    }
}

/// Read a `model` value by the grammar of the key's declared type (ruling 2c
/// of 0.11). Err: the vector is invalid.
fn read_model_value(engine: &Engine, member: &str, want: &str) -> Result<Option<Value>, String> {
    let key = last_key(member);
    if key == "#" || key.ends_with(".#") || member.ends_with(".#") {
        if want == "absent" || (!want.is_empty() && want.bytes().all(|b| b.is_ascii_digit())) {
            return Ok(None);
        }
        return Err(format!("invalid vector: `{}` = `{}` is not an unsigned decimal integer or `absent`", member, want));
    }
    if key.starts_with('@') {
        return Ok(None);
    }
    let ty = match engine.key_type(key) {
        Some(t) => t,
        None => return Ok(None),
    };
    let v = match ty {
        KeyType::Str => Some(Value::Str(want.to_string())),
        KeyType::Int => goat_transformers::int_text(want).map(Value::I64),
        KeyType::Float => goat_transformers::number_text(want).map(Value::F64),
    };
    match v {
        Some(v) => Ok(Some(v)),
        None => Err(format!("invalid vector: `{}` = `{}` is not {} text", member, want, ty.name())),
    }
}

/// What a `model` key of a vector names in a decoded entity.
enum Got<'a> {
    Value(&'a Value),
    /// the number of items of a list; None: the list is absent
    Count(Option<usize>),
    /// `@kind` after `[<i>].`: the kind an item selected
    Kind(Option<&'a str>),
}

/// Resolve a `model` key: a model key, `<list>.#`, or `<list>[<i>].<rest>`.
fn model_lookup<'a>(ent: &'a Entity, key: &str) -> Result<Got<'a>, String> {
    if let Some(open) = key.find('[') {
        let close = key[open..].find(']').map(|c| open + c).ok_or(format!("`{}`: no `]`", key))?;
        let index: usize = key[open + 1..close].parse().map_err(|_| format!("`{}`: bad item index", key))?;
        let rest = key[close + 1..].strip_prefix('.').ok_or(format!("`{}`: `].` expected", key))?;
        let list = &key[..open];
        let items = ent.lists.get(list).ok_or(format!("list `{}` absent after decode", list))?;
        let item = items.get(index).ok_or(format!("list `{}` has {} items, no item {}", list, items.len(), index))?;
        return model_lookup(item, rest).map_err(|e| format!("{}[{}]: {}", list, index, e));
    }
    if key == "@kind" {
        return Ok(Got::Kind(ent.kind.as_ref().map(|(_, name)| name.as_str())));
    }
    if let Some(list) = key.strip_suffix(".#") {
        return Ok(Got::Count(ent.lists.get(list).map(|l| l.len())));
    }
    ent.fields.get(key).map(Got::Value).ok_or(format!("model key `{}` absent after decode", key))
}

/// Resolve one `"@absent"` entry: a key or a list name of the entity, or
/// `<list>[<i>].<rest>` inside an item that must exist. Ok(true) when the
/// entity has no such key and no such list.
fn absent_lookup(ent: &Entity, entry: &str) -> Result<bool, String> {
    if let Some(open) = entry.find('[') {
        let close = entry[open..].find(']').map(|c| open + c).ok_or(format!("`{}`: no `]`", entry))?;
        let index: usize = entry[open + 1..close].parse().map_err(|_| format!("`{}`: bad item index", entry))?;
        let rest = entry[close + 1..].strip_prefix('.').ok_or(format!("`{}`: `].` expected", entry))?;
        let list = &entry[..open];
        let items = ent.lists.get(list).ok_or(format!("list `{}` absent after decode", list))?;
        let item = items.get(index).ok_or(format!("list `{}` has {} items, no item {}", list, items.len(), index))?;
        return absent_lookup(item, rest).map_err(|e| format!("{}[{}]: {}", list, index, e));
    }
    Ok(!ent.fields.contains_key(entry) && !ent.lists.contains_key(entry))
}

fn jstr<'a>(o: &'a Json, k: &str) -> Option<&'a str> {
    match o.get(k) {
        Some(Json::Str(s)) => Some(s.as_str()),
        _ => None,
    }
}

/// Run one conversion vector. Err holds what went wrong.
fn check_vector(engine: &Engine, v: &Json) -> Result<(), String> {
    let from = jstr(v, "from").ok_or("no `from`")?;
    let to = jstr(v, "to").ok_or("no `to`")?;
    let input = jstr(v, "input").ok_or("no `input`")?;

    // `context`: caller-supplied keys, values in string form
    let mut pairs: Vec<(String, String)> = Vec::new();
    match v.get("context") {
        None => {}
        Some(Json::Obj(members)) => {
            for (k, cv) in members {
                match cv {
                    Json::Str(s) => pairs.push((k.clone(), s.clone())),
                    _ => return Err(format!("context value of `{}` must be a string", k)),
                }
            }
        }
        Some(_) => return Err("`context` must be an object".into()),
    }
    // a `context` member, even an empty one, is a context given (ruling 10 of 0.6)
    let given = if v.get("context").is_some() { Some(pairs.as_slice()) } else { None };
    // `max_items`: the limit on list items for this vector (ruling 7 of 0.11)
    let max_items = match v.get("max_items") {
        None => goat_transformers::DEFAULT_MAX_ITEMS,
        Some(Json::Int(n)) if *n >= 0 => *n as usize,
        Some(_) => return Err("invalid vector: `max_items` must be an integer of 0 or more".into()),
    };
    let convert = || engine.convert_text_limited(from, to, input, given, max_items);

    // `expect_error` in place of `expect`: convert must fail with that named error
    if let Some(kind) = jstr(v, "expect_error") {
        return match convert() {
            Ok(out) => Err(format!("should fail with {}, produced {}", kind, out)),
            Err(e) if e.msg.starts_with(&format!("{}:", kind)) => Ok(()),
            Err(e) => Err(format!("want error kind `{}`, got `{}`", kind, e.msg)),
        };
    }
    let expect = jstr(v, "expect").ok_or("no `expect`")?;
    let got = convert().map_err(|e| format!("convert failed: {}", e))?;
    if got != expect {
        return Err(format!("({} -> {}) output mismatch\n      got  {}\n      want {}", from, to, got, expect));
    }

    // optional model checks
    if let Some(Json::Obj(model)) = v.get("model") {
        let mut ent = engine.decode_limited(from, input, max_items).map_err(|e| format!("decode failed: {}", e))?;
        // "@complete": true: the entity as `convert` hands it to the encoder
        let complete = match model.iter().find(|(k, _)| k == "@complete") {
            None | Some((_, Json::Bool(false))) => false,
            Some((_, Json::Bool(true))) => true,
            Some(_) => return Err("`@complete` must be true or false".into()),
        };
        if complete {
            let context = engine.context_from_text(&pairs).map_err(|e| format!("context: {}", e))?;
            engine.fill(&mut ent, &context).map_err(|e| format!("context: {}", e))?;
            engine.complete(&mut ent);
        }
        // "@absent": keys, item paths and list names the entity must not have
        if let Some((_, listed)) = model.iter().find(|(k, _)| k == "@absent") {
            let entries = match listed {
                Json::Arr(a) => a,
                _ => return Err("invalid vector: `@absent` must be an array".into()),
            };
            for e in entries {
                let entry = match e {
                    Json::Str(s) => s.as_str(),
                    _ => return Err("invalid vector: an `@absent` entry must be a string".into()),
                };
                // `@inner_kind` may be listed: `Entity.inner_kind` is absent (Version 0.34)
                if entry == "@inner_kind" {
                    if model.iter().any(|(k, _)| k == entry) {
                        return Err("invalid vector: `@inner_kind` is in `@absent` and is a member of `model`".into());
                    }
                    if let Some(k) = &ent.inner_kind {
                        return Err(format!("`@inner_kind` must be absent, got {:?}", k));
                    }
                    continue;
                }
                if entry.starts_with('@') {
                    return Err(format!("invalid vector: `@absent` lists `{}`, which is not a key", entry));
                }
                if model.iter().any(|(k, _)| k == entry) {
                    return Err(format!("invalid vector: `{}` is in `@absent` and is a member of `model`", entry));
                }
                if !absent_lookup(&ent, entry)? {
                    let got = ent.fields.get(entry).map(|v| v.as_display()).unwrap_or_else(|| "present".into());
                    return Err(format!("`{}` must be absent, got `{}`", entry, got));
                }
            }
        }
        for (k, mv) in model {
            if k == "@complete" || k == "@absent" {
                continue;
            }
            let want = match mv {
                Json::Str(s) => s.clone(),
                Json::Int(n) => n.to_string(),
                Json::Num(x) => goat_transformers::fmt_f64(*x),
                _ => return Err(format!("model value of `{}` must be scalar", k)),
            };
            // "@kind": the kind name decode must select
            if k == "@kind" {
                if ent.kind != Some((from.to_string(), want.clone())) {
                    return Err(format!("selected kind {:?}, want `{}`", ent.kind, want));
                }
                continue;
            }
            // "@inner_kind": the kind name `Entity.inner_kind` must hold (Version 0.34)
            if k == "@inner_kind" {
                if ent.inner_kind.as_ref().map(|(_, name)| name.as_str()) != Some(want.as_str()) {
                    return Err(format!("inner kind {:?}, want `{}`", ent.inner_kind, want));
                }
                continue;
            }
            // every value is checked against its grammar first: an invalid vector fails
            read_model_value(engine, k, &want)?;
            let got_field = match model_lookup(&ent, k)? {
                Got::Value(v) => v,
                Got::Kind(name) => {
                    if name != Some(want.as_str()) {
                        return Err(format!("`{}` = {:?} want `{}`", k, name, want));
                    }
                    continue;
                }
                Got::Count(n) => {
                    let got = n.map(|n| n.to_string()).unwrap_or_else(|| "absent".to_string());
                    if got != want {
                        return Err(format!("`{}` = {} want {}", k, got, want));
                    }
                    continue;
                }
            };
            // the value read as its key's type (ruling 2c of 0.11)
            let typed = read_model_value(engine, k, &want)?;
            if let (Value::I64(a), Some(Value::I64(b))) = (got_field, &typed) {
                if a != b {
                    return Err(format!("field `{}` = {} want {}", k, a, b));
                }
                continue;
            }
            // float-tolerant compare
            if let (Value::F64(a), Some(Value::F64(b))) = (got_field, &typed) {
                let b = *b;
                // decoded: within 1e-9; completed: within 1e-9 relative, or
                // within 1e-7 absolute (vector-format step 3, Version 0.16)
                let tolerance = if complete { 1e-9 * a.abs().max(b.abs()) } else { 1e-9 };
                let absolute = complete && (a - b).abs() < 1e-7;
                if *a != b && (a - b).abs() >= tolerance && !absolute {
                    return Err(format!("field `{}` = {} want {}", k, a, b));
                }
            } else if got_field.as_display() != want {
                return Err(format!("field `{}` = `{}` want `{}`", k, got_field.as_display(), want));
            }
        }
    }
    Ok(())
}

/// Print every failure, then fail once with the count and the names.
/// `skipped`: the vectors left out for a wire this build lacks (engine-spec 0.24).
fn report(what: &str, total: usize, skipped: usize, failures: &[(String, String)]) {
    use std::io::Write;
    assert!(total > 0, "no {} were run", what);
    // written to stderr directly, so the counts show on a passing run too
    let mut out = std::io::stderr();
    let _ = writeln!(out, "ran {} {}, {} failed", total, what, failures.len());
    if skipped > 0 {
        let wires = goat_transformers::build_wires().join(",");
        let _ = writeln!(out, "left out {} {} on a wire this build ({}) does not have", skipped, what, wires);
    }
    for (name, why) in failures {
        let _ = writeln!(out, "  FAIL `{}`: {}", name, why);
    }
    if !failures.is_empty() {
        let names: Vec<&str> = failures.iter().map(|(n, _)| n.as_str()).collect();
        panic!("{} of {} {} failed: {}", failures.len(), total, what, names.join(", "));
    }
}

#[test]
fn run_all_vectors() {
    let (engine, mut failures) = load_engine();
    let unbuilt = unbuilt_formats();
    let mut skipped = 0;
    let packs = repo_packs_dir();
    let mut total = 0;
    let mut dirs: Vec<_> = std::fs::read_dir(&packs).unwrap().flatten().map(|e| e.path()).collect();
    dirs.sort();
    for dir in dirs {
        let vdir = dir.join("vectors");
        if !vdir.exists() {
            continue;
        }
        let mut files: Vec<_> = std::fs::read_dir(&vdir).unwrap().flatten().map(|e| e.path()).collect();
        files.sort();
        for vf in files {
            if vf.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            let label = |name: &str| format!("{}/{}", dir.file_name().unwrap().to_string_lossy(), name);
            let text = std::fs::read_to_string(&vf).unwrap();
            let v = match json::parse(&text) {
                Ok(v) => v,
                Err(e) => {
                    total += 1;
                    failures.push((label(&vf.file_name().unwrap().to_string_lossy()), format!("not JSON: {}", e)));
                    continue;
                }
            };
            if ["from", "to"].iter().any(|k| jstr(&v, k).is_some_and(|f| unbuilt.iter().any(|u| u == f))) {
                skipped += 1;
                continue;
            }
            total += 1;
            let name = label(jstr(&v, "name").unwrap_or("?"));
            if let Err(why) = check_vector(&engine, &v) {
                failures.push((name, why));
            }
        }
    }
    report("conversion vectors", total, skipped, &failures);
}

/// Load vectors (spec/vector-format.md, "Load vectors"): a set of model modules
/// and one pack either load, or fail with the named error kind.
#[test]
fn run_load_vectors() {
    let dir = repo_packs_dir().join("conformance/load-vectors");
    let mut files: Vec<_> = std::fs::read_dir(&dir).unwrap().flatten().map(|e| e.path()).collect();
    files.sort();
    let mut total = 0;
    let mut skipped = 0;
    let mut failures: Vec<(String, String)> = Vec::new();
    for vf in files {
        if vf.extension().and_then(|s| s.to_str()) != Some("json") {
            continue;
        }
        let v = json::parse(&std::fs::read_to_string(&vf).unwrap()).unwrap();
        let name = jstr(&v, "name").unwrap_or("?").to_string();
        let texts: Vec<&str> = match (v.get("pack"), v.get("packs")) {
            (Some(Json::Str(t)), _) => vec![t.as_str()],
            (_, Some(Json::Arr(a))) => a.iter().filter_map(|t| if let Json::Str(t) = t { Some(t.as_str()) } else { None }).collect(),
            _ => vec![],
        };
        if texts.iter().any(|t| unbuilt_wire(t).is_some()) {
            skipped += 1;
            continue;
        }
        total += 1;
        let mut e = Engine::new();
        if let Some(d) = jstr(&v, "max_distribution") {
            e.set_max_distribution(Distribution::parse(d).expect("max_distribution"));
        }
        let mut result: Result<(), goat_transformers::Error> = Ok(());
        if let Some(Json::Arr(models)) = v.get("models") {
            for m in models {
                if let Json::Str(text) = m {
                    if result.is_ok() {
                        result = e.load_model(text);
                    }
                }
            }
        }
        match (v.get("pack"), v.get("packs")) {
            (Some(Json::Str(text)), None) => {
                if result.is_ok() {
                    result = e.load_def(text);
                }
            }
            (None, Some(Json::Arr(texts))) => {
                for t in texts {
                    match t {
                        Json::Str(text) if result.is_ok() => result = e.load_def(text),
                        Json::Str(_) => {}
                        _ => panic!("load vector `{}`: a `packs` entry must be a string", name),
                    }
                }
            }
            _ => panic!("load vector `{}`: exactly one of `pack` and `packs`", name),
        }
        let why = match (jstr(&v, "expect_error"), result) {
            (None, Ok(())) => None,
            (None, Err(err)) => Some(format!("should load, failed: {}", err)),
            (Some(kind), Ok(())) => Some(format!("should fail with {}, loaded", kind)),
            (Some(kind), Err(err)) if err.msg.starts_with(&format!("{}:", kind)) => None,
            (Some(kind), Err(err)) => Some(format!("want error kind `{}`, got `{}`", kind, err.msg)),
        };
        if let Some(why) = why {
            failures.push((name, why));
        }
    }
    report("load vectors", total, skipped, &failures);
}

fn str_array(v: &Json, k: &str) -> Option<Vec<String>> {
    match v.get(k) {
        Some(Json::Arr(a)) => a
            .iter()
            .map(|e| match e {
                Json::Str(s) => Some(s.clone()),
                _ => None,
            })
            .collect(),
        _ => None,
    }
}

/// Capability vectors (spec/vector-format.md, "Capability vectors"): the grade
/// and the two lists of `capability(from, to)`, in order.
#[test]
fn run_capability_vectors() {
    let (engine, load_failures) = load_engine();
    assert!(load_failures.is_empty(), "packs failed to load: {:?}", load_failures);
    let unbuilt = unbuilt_formats();
    let mut skipped = 0;
    let dir = repo_packs_dir().join("conformance/capability-vectors");
    let mut files: Vec<_> = std::fs::read_dir(&dir).unwrap().flatten().map(|e| e.path()).collect();
    files.sort();
    let mut total = 0;
    let mut failures: Vec<(String, String)> = Vec::new();
    for vf in files {
        if vf.extension().and_then(|s| s.to_str()) != Some("json") {
            continue;
        }
        let v = json::parse(&std::fs::read_to_string(&vf).unwrap()).unwrap();
        if ["from", "to"].iter().any(|k| jstr(&v, k).is_some_and(|f| unbuilt.iter().any(|u| u == f))) {
            skipped += 1;
            continue;
        }
        total += 1;
        let name = jstr(&v, "name").unwrap_or("?").to_string();
        let check = || -> Result<(), String> {
            let from = jstr(&v, "from").ok_or("no `from`")?;
            let to = jstr(&v, "to").ok_or("no `to`")?;
            let grade = jstr(&v, "grade").ok_or("no `grade`")?;
            let carried = str_array(&v, "carried").ok_or("no `carried` array of strings")?;
            let dropped = str_array(&v, "dropped").ok_or("no `dropped` array of strings")?;
            let c = engine.try_capability(from, to).map_err(|e| format!("capability failed: {}", e))?;
            let got_grade = match c.grade {
                Grade::Full => "full",
                Grade::Partial => "partial",
                Grade::None => "none",
            };
            if got_grade != grade {
                return Err(format!("grade `{}` want `{}`", got_grade, grade));
            }
            if c.carried != carried {
                return Err(format!("carried {:?} want {:?}", c.carried, carried));
            }
            if c.dropped != dropped {
                return Err(format!("dropped {:?} want {:?}", c.dropped, dropped));
            }
            Ok(())
        };
        if let Err(why) = check() {
            failures.push((name, why));
        }
    }
    report("capability vectors", total, skipped, &failures);
}
