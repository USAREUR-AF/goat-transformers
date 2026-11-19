//! Shared parts of the host-side proof: load the reference engine and the
//! vectors, compile plans with `tools/gen/packc.py`, and compare what the
//! device engine holds with what the reference engine holds.
//!
//! The reference engine is the oracle here. The device engine was written
//! with the reference source open, so agreement between the two is a check
//! of the compiler and the port, not an independent reading of the spec.

use goat_transformers::json::{self, Json};
use goat_transformers::{Engine, Entity, Value as RefValue};
use gt_core::{Got, KeyId, Plan, Scope, Session, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::rc::Rc;

/// Value slots and list items of the scratch the proof runs with.
pub const SLOTS: usize = 4096;
pub type Scratch = gt_core::Scratch<SLOTS>;

pub fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..").canonicalize().expect("repository root")
}

pub struct Vector {
    /// the pack directory that owns the vector
    pub pack: String,
    pub name: String,
    pub from: String,
    pub to: String,
    pub input: String,
    pub expect: Option<String>,
    pub expect_error: Option<String>,
    /// `Some` when the vector has a `context` member, also an empty one
    pub context: Option<Vec<(String, String)>>,
    pub model: Vec<(String, String)>,
    pub complete: bool,
}

pub struct Proof {
    pub engine: Engine,
    root: PathBuf,
    wires: HashMap<String, String>,
    plans: HashMap<String, Result<Rc<Vec<u8>>, String>>,
}

impl Default for Proof {
    fn default() -> Proof {
        Proof::new()
    }
}

impl Proof {
    pub fn new() -> Proof {
        let root = repo_root();
        let mut engine = Engine::new();
        engine.load_model_dir(&root.join("model")).expect("model modules");
        engine.load_pack_dir(&root.join("packs")).expect("packs");
        let mut wires = HashMap::new();
        for dir in sorted(&root.join("packs")) {
            let text = match std::fs::read_to_string(dir.join("pack.def")) {
                Ok(t) => t,
                Err(_) => continue,
            };
            let word = |name: &str| {
                text.lines().find_map(|l| {
                    let mut t = l.split_whitespace();
                    (t.next() == Some(name)).then(|| t.next().unwrap_or("").to_string())
                })
            };
            if let (Some(format), Some(wire)) = (word("format"), word("wire")) {
                wires.insert(format, wire);
            }
        }
        Proof { engine, root, wires, plans: HashMap::new() }
    }

    pub fn is_bits(&self, format: &str) -> bool {
        self.wires.get(format).map(String::as_str) == Some("bits")
    }

    /// Every bits-wire format, in name order.
    pub fn bits_formats(&self) -> Vec<String> {
        let mut out: Vec<String> = self.wires.iter().filter(|(_, w)| *w == "bits").map(|(f, _)| f.clone()).collect();
        out.sort();
        out
    }

    fn plan_id(from: Option<&str>, to: Option<&str>, context: &[String]) -> String {
        format!("{:?}>{:?}+{}", from, to, context.join(","))
    }

    /// Compile plans with packc, names kept, in one run of the compiler.
    /// A refusal is kept as the plan's result.
    pub fn compile(&mut self, specs: &[(Option<String>, Option<String>, Vec<String>)]) {
        // build output: under the workspace target directory, never in the tree
        let dir = std::env::var_os("CARGO_TARGET_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("../target"))
            .join("gt-proof-plans");
        std::fs::create_dir_all(&dir).expect("plan directory");
        // file names are unique across the threads of one test run
        static RUN: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
        let run = RUN.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let mut todo: Vec<(String, PathBuf)> = Vec::new();
        let mut jobs = String::from("[");
        let quote = |s: &str| format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""));
        for (from, to, context) in specs {
            let id = Self::plan_id(from.as_deref(), to.as_deref(), context);
            if self.plans.contains_key(&id) || todo.iter().any(|(t, _)| *t == id) {
                continue;
            }
            let file = dir.join(format!("plan-{}-{}-{}.gtp", std::process::id(), run, todo.len()));
            if !todo.is_empty() {
                jobs.push(',');
            }
            jobs.push_str("{\"names\":true");
            if let Some(f) = from {
                jobs.push_str(&format!(",\"from\":{}", quote(f)));
            }
            if let Some(t) = to {
                jobs.push_str(&format!(",\"to\":{}", quote(t)));
            }
            let ctx: Vec<String> = context.iter().map(|c| quote(c)).collect();
            jobs.push_str(&format!(",\"context\":[{}],\"out_gtp\":{}}}", ctx.join(","), quote(&file.to_string_lossy())));
            todo.push((id, file));
        }
        if todo.is_empty() {
            return;
        }
        jobs.push(']');
        let job_file = dir.join(format!("jobs-{}-{}.json", std::process::id(), run));
        std::fs::write(&job_file, jobs).expect("job file");
        let out = Command::new("python3")
            .arg("-I")
            .arg(self.root.join("tools/gen/packc.py"))
            .arg("--batch")
            .arg(&job_file)
            .output()
            .expect("python3 runs");
        assert!(out.status.success(), "packc --batch failed: {}", String::from_utf8_lossy(&out.stderr));
        let result_file = PathBuf::from(format!("{}.out", job_file.to_string_lossy()));
        let results = json::parse(&std::fs::read_to_string(&result_file).expect("batch results")).expect("results are JSON");
        let results = match results {
            Json::Arr(r) => r,
            _ => panic!("batch results are not a list"),
        };
        assert_eq!(results.len(), todo.len());
        for ((id, file), r) in todo.into_iter().zip(results) {
            let result = match r.get("refused") {
                Some(Json::Str(why)) => Err(format!("packc: refused: {}", why)),
                _ => Ok(Rc::new(std::fs::read(&file).expect("the compiled plan"))),
            };
            let _ = std::fs::remove_file(&file);
            self.plans.insert(id, result);
        }
        let _ = std::fs::remove_file(&job_file);
        let _ = std::fs::remove_file(&result_file);
    }

    /// One plan: decode-only (`from`), encode-only (`to`) or a conversion.
    /// Err holds packc's refusal.
    pub fn plan(&mut self, from: Option<&str>, to: Option<&str>, context: &[String]) -> Result<Rc<Vec<u8>>, String> {
        let id = Self::plan_id(from, to, context);
        if !self.plans.contains_key(&id) {
            self.compile(&[(from.map(String::from), to.map(String::from), context.to_vec())]);
        }
        self.plans[&id].clone()
    }

    /// Every conversion vector of the repository.
    pub fn vectors(&self) -> Vec<Vector> {
        let mut out = Vec::new();
        for dir in sorted(&self.root.join("packs")) {
            let vdir = dir.join("vectors");
            if !vdir.is_dir() {
                continue;
            }
            for vf in sorted(&vdir) {
                if vf.extension().and_then(|s| s.to_str()) != Some("json") {
                    continue;
                }
                let v = json::parse(&std::fs::read_to_string(&vf).expect("vector file")).expect("vector is JSON");
                let s = |k: &str| match v.get(k) {
                    Some(Json::Str(s)) => Some(s.clone()),
                    _ => None,
                };
                let pairs = |k: &str| match v.get(k) {
                    Some(Json::Obj(m)) => Some(
                        m.iter()
                            .filter(|(k, _)| k != "@complete")
                            .map(|(k, v)| {
                                let text = match v {
                                    Json::Str(s) => s.clone(),
                                    Json::Int(n) => n.to_string(),
                                    Json::Num(x) => goat_transformers::fmt_f64(*x),
                                    other => format!("{:?}", other),
                                };
                                (k.clone(), text)
                            })
                            .collect::<Vec<_>>(),
                    ),
                    _ => None,
                };
                let complete = matches!(v.get("model").and_then(|m| m.get("@complete")), Some(Json::Bool(true)));
                out.push(Vector {
                    pack: dir.file_name().unwrap().to_string_lossy().to_string(),
                    name: s("name").unwrap_or_default(),
                    from: s("from").unwrap_or_default(),
                    to: s("to").unwrap_or_default(),
                    input: s("input").unwrap_or_default(),
                    expect: s("expect"),
                    expect_error: s("expect_error"),
                    context: pairs("context"),
                    model: pairs("model").unwrap_or_default(),
                    complete,
                });
            }
        }
        out
    }
}

fn sorted(dir: &Path) -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir).expect("directory").flatten().map(|e| e.path()).collect();
    v.sort();
    v
}

/// Hex text to bytes, as the reference engine reads it. None: not hex.
pub fn unhex(text: &str) -> Option<Vec<u8>> {
    goat_transformers::bits::from_hex(text.trim()).ok()
}

pub fn hex(bytes: &[u8]) -> String {
    goat_transformers::bits::to_hex(bytes)
}

/// The error kind of a reference error: the text before the first colon.
pub fn kind_of(e: &goat_transformers::Error) -> &str {
    e.msg.split(':').next().unwrap_or("")
}

/// A context in the reference engine's typed form, as the device takes it.
pub fn device_context<'a>(plan: &Plan, typed: &'a [(String, RefValue)]) -> Vec<(KeyId, Value<'a>)> {
    typed
        .iter()
        .map(|(k, v)| {
            let key = plan.find_key(k).unwrap_or(KeyId(0xFFFE));
            let value = match v {
                RefValue::I64(n) => Value::Int(*n),
                RefValue::F64(x) => Value::Float(*x),
                RefValue::Str(s) => Value::Str(s.as_bytes()),
            };
            (key, value)
        })
        .collect()
}

pub fn text_of(s: &Session, got: Got) -> String {
    match got {
        Got::Int(n) => n.to_string(),
        Got::Float(x) => goat_transformers::fmt_f64(x),
        Got::Text(t) => (0..s.text_len(t)).map(|i| s.text_byte(t, i) as char).collect(),
    }
}

/// Does the device hold exactly what the reference entity holds? Every key
/// the plan names is compared, absent keys included, and every list, item by
/// item. `tolerance`: relative difference allowed between floats (0: equal).
pub fn same_entity(s: &Session, plan: &Plan, scope: Scope, ent: &Entity, tolerance: f64) -> Result<(), String> {
    for k in (0..plan.key_count()).map(KeyId) {
        let name = match plan.key_name(k) {
            Some(n) => n,
            None => return Err("the plan has no names".into()),
        };
        match (ent.fields.get(name), s.get(scope, k)) {
            (None, None) => {}
            (Some(want), Some(got)) => {
                let ok = match (want, got) {
                    (RefValue::I64(a), Got::Int(b)) => *a == b,
                    (RefValue::F64(a), Got::Float(b)) => {
                        *a == b || (a - b).abs() <= tolerance * a.abs().max(b.abs())
                    }
                    (RefValue::Str(a), Got::Text(_)) => *a == text_of(s, got),
                    _ => false,
                };
                if !ok {
                    return Err(format!("`{}`: reference {}, device {}", name, want.as_display(), text_of(s, got)));
                }
            }
            (Some(want), None) => return Err(format!("`{}`: reference {}, device absent", name, want.as_display())),
            (None, Some(got)) => return Err(format!("`{}`: reference absent, device {}", name, text_of(s, got))),
        }
        match (ent.lists.get(name), s.list(scope, k)) {
            (None, None) => {}
            (Some(items), Some(n)) if items.len() == n as usize => {
                for (i, item) in items.iter().enumerate() {
                    let sc = s.list_item(scope, k, i as u16).ok_or(format!("`{}[{}]`: no such item", name, i))?;
                    same_entity(s, plan, sc, item, tolerance).map_err(|e| format!("{}[{}]: {}", name, i, e))?;
                    let want = item.kind.as_ref().map(|(_, n)| n.as_str());
                    if want != s.kind_name(sc) {
                        return Err(format!("{}[{}]: kind: reference {:?}, device {:?}", name, i, want, s.kind_name(sc)));
                    }
                }
            }
            (want, got) => {
                return Err(format!("list `{}`: reference {:?} items, device {:?}", name, want.map(|l| l.len()), got))
            }
        }
    }
    Ok(())
}

/// The texts of an entity, in the order `inject` refers to them.
pub fn texts_of<'a>(ent: &'a Entity, out: &mut Vec<&'a [u8]>) {
    for v in ent.fields.values() {
        if let RefValue::Str(s) = v {
            out.push(s.as_bytes());
        }
    }
    for items in ent.lists.values() {
        for item in items {
            texts_of(item, out);
        }
    }
}

/// Set the device's values from a reference entity: every key and list the
/// plan names. Call `set_texts` with `texts_of` first.
pub fn inject(s: &mut Session, plan: &Plan, scope: Scope, ent: &Entity, next_text: &mut u16) -> Result<(), gt_core::Error> {
    for (name, v) in &ent.fields {
        let key = plan.find_key(name);
        match (v, key) {
            (RefValue::Str(_), key) => {
                if let Some(k) = key {
                    s.put_text(scope, k, *next_text)?;
                }
                *next_text += 1;
            }
            (RefValue::I64(n), Some(k)) => s.put_int(scope, k, *n)?,
            (RefValue::F64(x), Some(k)) => s.put_float(scope, k, *x)?,
            _ => {}
        }
    }
    for (name, items) in &ent.lists {
        match plan.find_key(name) {
            Some(k) => {
                s.put_list(scope, k)?;
                for item in items {
                    let sc = s.add_item(scope, k)?;
                    inject(s, plan, sc, item, next_text)?;
                }
            }
            None => {
                // the plan does not name the list: step over its texts
                let mut skipped = Vec::new();
                for item in items {
                    texts_of(item, &mut skipped);
                }
                *next_text += skipped.len() as u16;
            }
        }
    }
    Ok(())
}

/// A small deterministic generator (xorshift64*), so a failing run can be repeated.
pub struct Rng(pub u64);

impl Rng {
    pub fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    pub fn below(&mut self, n: usize) -> usize {
        (self.next() % n.max(1) as u64) as usize
    }
    pub fn bytes(&mut self, n: usize) -> Vec<u8> {
        (0..n).map(|_| self.next() as u8).collect()
    }
}
