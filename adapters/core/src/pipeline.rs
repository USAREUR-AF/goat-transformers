//! The pipeline: source -> engine.convert(from, to, context) -> sinks.
//!
//! One thread, one message at a time, no queue. A slow sink slows the
//! source; nothing is buffered between them. A message that does not convert
//! or cannot be delivered is counted under its error name and reported on
//! stderr; it is never passed through unconverted.

use crate::{AdapterError, Message, Meta, Recv, Sink, Source};
use goat_transformers::{bits, Distribution, Engine, Error, Pack, Value, Wire};
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// The engine and, for each loaded format, whether its wire is binary.
///
/// The engine takes and returns text, and gives a binary message as
/// hexadecimal text. An adapter carries real bytes, so the pipeline has to
/// know which formats are binary.
pub struct Formats {
    engine: Engine,
    binary: BTreeMap<String, bool>,
}

impl Formats {
    /// Load the model modules of `models` and the packs of `packs`. With
    /// `only`, load just the named formats; a name with no pack is an error.
    pub fn load(models: &Path, packs: &Path, only: Option<&[String]>, max: Option<Distribution>) -> Result<Formats, Error> {
        let mut engine = Engine::new();
        if let Some(d) = max {
            engine.set_max_distribution(d);
        }
        if only.is_none() {
            engine.load_model_dir(models)?;
        }
        let mut dirs: Vec<std::path::PathBuf> = std::fs::read_dir(packs)
            .map_err(|e| Error { msg: format!("cannot read {}: {}", packs.display(), e) })?
            .flatten()
            .map(|e| e.path())
            .collect();
        dirs.sort();
        let mut binary = BTreeMap::new();
        let mut wanted: Vec<(Pack, std::path::PathBuf)> = Vec::new();
        for d in dirs {
            let def = d.join("pack.def");
            if !def.exists() {
                continue;
            }
            let located = |e: Error| Error { msg: format!("{} (in {})", e.msg, def.display()) };
            let text = std::fs::read_to_string(&def).map_err(|e| Error { msg: format!("cannot read {}: {}", def.display(), e) })?;
            if let Some(only) = only {
                // the `format` line says whether this pack was asked for;
                // a pack that was not is neither parsed nor checked
                let format = text.lines().find_map(|l| {
                    let mut t = l.split_whitespace();
                    (t.next() == Some("format")).then(|| t.next()).flatten()
                });
                if !format.map_or(false, |f| only.iter().any(|o| o == f)) {
                    continue;
                }
            }
            let pack = Pack::parse(&text).map_err(located)?;
            binary.insert(pack.format.clone(), matches!(pack.wire, Wire::Bits | Wire::Protobuf));
            if only.is_some() {
                wanted.push((pack, def));
            } else {
                engine.load(pack).map_err(located)?;
            }
        }
        if only.is_some() {
            let uses: Vec<String> = wanted.iter().flat_map(|(p, _)| p.uses.iter().cloned()).collect();
            load_modules(&mut engine, models, &uses)?;
            for (pack, def) in wanted {
                engine.load(pack).map_err(|e| Error { msg: format!("{} (in {})", e.msg, def.display()) })?;
            }
        }
        for name in only.unwrap_or(&[]) {
            if !binary.contains_key(name) {
                return Err(Error { msg: format!("no pack for format `{}` in {}", name, packs.display()) });
            }
        }
        Ok(Formats { engine, binary })
    }

    pub fn engine(&self) -> &Engine {
        &self.engine
    }
    /// Is this format's wire binary? `None`: the format is not loaded.
    pub fn is_binary(&self, format: &str) -> Option<bool> {
        self.binary.get(format).copied()
    }
    pub fn names(&self) -> Vec<String> {
        self.binary.keys().cloned().collect()
    }
}

/// Load `core` and the model modules named in `uses`, with the modules they
/// use in turn, each after the modules it uses. The engine's own directory
/// loader loads every module; a pipe that names two formats needs few.
fn load_modules(engine: &mut Engine, dir: &Path, uses: &[String]) -> Result<(), Error> {
    let mut files: Vec<std::path::PathBuf> = match std::fs::read_dir(dir) {
        Ok(rd) => rd.flatten().map(|e| e.path()).filter(|p| p.extension().and_then(|s| s.to_str()) == Some("def")).collect(),
        Err(_) => return Ok(()),
    };
    files.sort();
    // (module name, the modules it uses, its text, its file)
    let mut modules: Vec<(String, Vec<String>, String, std::path::PathBuf)> = Vec::new();
    for f in files {
        let text = std::fs::read_to_string(&f).map_err(|e| Error { msg: format!("cannot read {}: {}", f.display(), e) })?;
        let word = |line: &str, key: &str| {
            let mut t = line.split_whitespace();
            (t.next() == Some(key)).then(|| t.next().map(|s| s.to_string())).flatten()
        };
        let name = text.lines().find_map(|l| word(l, "module")).unwrap_or_default();
        let used = text.lines().filter_map(|l| word(l, "uses")).filter(|u| *u != name).collect();
        modules.push((name, used, text, f));
    }
    let mut need: Vec<String> = vec!["core".to_string()];
    need.extend(uses.iter().cloned());
    let mut i = 0;
    while i < need.len() {
        if let Some(m) = modules.iter().find(|m| m.0 == need[i]) {
            let more: Vec<String> = m.1.iter().filter(|u| !need.contains(u)).cloned().collect();
            need.extend(more);
        }
        i += 1;
    }
    let mut pending: Vec<_> = modules.into_iter().filter(|m| need.contains(&m.0)).collect();
    pending.sort_by_key(|m| m.0 != "core");
    let mut loaded: Vec<String> = Vec::new();
    while !pending.is_empty() {
        let names: Vec<String> = pending.iter().map(|m| m.0.clone()).collect();
        let ready = pending.iter().position(|m| m.1.iter().all(|u| loaded.contains(u) || !names.contains(u)));
        let Some(at) = ready else {
            return Err(Error { msg: format!("bad-directive: the `uses` lines of model modules {} form a cycle", names.join(", ")) });
        };
        let (name, _, text, file) = pending.remove(at);
        engine.load_model(&text).map_err(|e| Error { msg: format!("{} (in {})", e.msg, file.display()) })?;
        loaded.push(name);
    }
    Ok(())
}

/// `public` or `controlled`.
pub fn parse_distribution(s: &str) -> Option<Distribution> {
    Distribution::parse(s)
}

/// What the pipeline does when a message fails.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum OnError {
    /// Count it, report it, go on with the next message.
    Skip,
    /// Count it, report it, stop.
    Stop,
}

/// The counters. `received` counts messages from the source. `converted`
/// and `failed` count per output: with two outputs one message adds two.
///
/// The same counts are kept by format for `/metrics`: messages delivered by
/// target format, and failures by stage, format and error name. The stages:
/// `decode` (the input did not decode: the format is the input's), `encode`
/// (it decoded, and the rest of the conversion to the target failed: filling
/// the context, a derivation or the encoder; the format is the target's),
/// `deliver` (a sink refused the converted message; the target's format) and
/// `source` (the source failed; the input's format).
pub struct Stats {
    pub received: AtomicU64,
    pub converted: AtomicU64,
    failed: Mutex<BTreeMap<String, u64>>,
    delivered_by: Mutex<BTreeMap<String, u64>>,
    failed_by: Mutex<BTreeMap<(String, String, String), u64>>,
    started: Instant,
}

impl Default for Stats {
    fn default() -> Stats {
        Stats {
            received: AtomicU64::new(0),
            converted: AtomicU64::new(0),
            failed: Mutex::new(BTreeMap::new()),
            delivered_by: Mutex::new(BTreeMap::new()),
            failed_by: Mutex::new(BTreeMap::new()),
            started: Instant::now(),
        }
    }
}

impl Stats {
    /// Failures by error name.
    pub fn failed(&self) -> BTreeMap<String, u64> {
        self.failed.lock().map(|m| m.clone()).unwrap_or_default()
    }
    pub fn failed_total(&self) -> u64 {
        self.failed().values().sum()
    }
    fn fail(&self, kind: &str) -> u64 {
        let mut m = self.failed.lock().unwrap_or_else(|p| p.into_inner());
        let n = m.entry(kind.to_string()).or_insert(0);
        *n += 1;
        *n
    }
    /// Count a failure under its error name, and by stage and format.
    pub fn fail_at(&self, stage: &str, format: &str, kind: &str) -> u64 {
        let mut m = self.failed_by.lock().unwrap_or_else(|p| p.into_inner());
        *m.entry((stage.to_string(), format.to_string(), kind.to_string())).or_insert(0) += 1;
        drop(m);
        self.fail(kind)
    }
    /// Count one message delivered in `format`.
    pub fn delivered(&self, format: &str) {
        self.converted.fetch_add(1, Ordering::Relaxed);
        let mut m = self.delivered_by.lock().unwrap_or_else(|p| p.into_inner());
        *m.entry(format.to_string()).or_insert(0) += 1;
    }
    /// Messages delivered, by target format.
    pub fn delivered_by(&self) -> BTreeMap<String, u64> {
        self.delivered_by.lock().map(|m| m.clone()).unwrap_or_default()
    }
    /// Failures by (stage, format, error name).
    pub fn failed_by(&self) -> BTreeMap<(String, String, String), u64> {
        self.failed_by.lock().map(|m| m.clone()).unwrap_or_default()
    }
    /// Seconds since the counters started.
    pub fn uptime_secs(&self) -> f64 {
        self.started.elapsed().as_secs_f64()
    }
    /// The one-line status: `in=12 converted=11 failed=1 [malformed-wire=1] 4s`.
    pub fn line(&self) -> String {
        let failed = self.failed();
        let mut s = format!(
            "in={} converted={} failed={}",
            self.received.load(Ordering::Relaxed),
            self.converted.load(Ordering::Relaxed),
            failed.values().sum::<u64>()
        );
        if !failed.is_empty() {
            let kinds: Vec<String> = failed.iter().map(|(k, n)| format!("{}={}", k, n)).collect();
            s.push_str(&format!(" [{}]", kinds.join(" ")));
        }
        s.push_str(&format!(" {}s", self.started.elapsed().as_secs()));
        s
    }
}

/// One output of a pipeline: a target format and where it goes.
pub struct Output {
    pub to: String,
    /// A binary message leaves as hexadecimal text.
    pub hex: bool,
    pub sink: Box<dyn Sink>,
}

/// How a run ended.
#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    /// The source ended and every message was converted and delivered.
    Completed,
    /// The source ended; some messages failed and were skipped.
    CompletedWithFailures,
    /// The run stopped on a failure: `OnError::Stop`, or a source or sink
    /// that could not continue.
    Stopped(String),
    /// The caller set the stop flag.
    Interrupted,
}

/// The engine's error name: the text before the first `: `, when it is a
/// name. Anything else is counted as `unnamed`.
pub fn error_kind(msg: &str) -> &str {
    match msg.split_once(": ") {
        Some((k, _)) if !k.is_empty() && k.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-') => k,
        _ => "unnamed",
    }
}

/// How many failures of one kind are printed in full; the rest are counted.
const PRINTED_PER_KIND: u64 = 10;

pub struct Pipeline<'a> {
    pub formats: &'a Formats,
    pub from: String,
    /// A binary message arrives as hexadecimal text.
    pub in_hex: bool,
    pub source: Box<dyn Source>,
    pub outputs: Vec<Output>,
    /// Model keys the input does not carry, for every message (`--set`).
    pub context: Vec<(String, String)>,
    /// The model key that takes a message's receive time when the message
    /// carries none.
    pub receive_time_key: Option<String>,
    pub on_error: OnError,
    /// Print the status line on stderr this often.
    pub status_every: Option<Duration>,
    /// The name that begins each line on stderr.
    pub name: String,
    pub stats: Arc<Stats>,
}

impl<'a> Pipeline<'a> {
    pub fn new(formats: &'a Formats, from: &str, source: Box<dyn Source>, outputs: Vec<Output>) -> Pipeline<'a> {
        Pipeline {
            formats,
            from: from.to_string(),
            in_hex: false,
            source,
            outputs,
            context: Vec::new(),
            receive_time_key: None,
            on_error: OnError::Skip,
            status_every: None,
            name: "pipeline".to_string(),
            stats: Arc::new(Stats::default()),
        }
    }

    /// Everything that can be refused before the first message is: an
    /// unknown format, `hex` on a text format, a context key that is not
    /// declared or does not hold its type.
    pub fn check(&self) -> Result<(), String> {
        let wire = |f: &str, hex: bool| match self.formats.is_binary(f) {
            None => Err(format!("no pack loaded for format `{}`", f)),
            Some(false) if hex => Err(format!("`hex` is for a binary format; `{}` is text", f)),
            Some(_) => Ok(()),
        };
        wire(&self.from, self.in_hex)?;
        if self.outputs.is_empty() {
            return Err("no output".to_string());
        }
        for o in &self.outputs {
            wire(&o.to, o.hex)?;
        }
        let engine = self.formats.engine();
        engine.context_from_text(&self.context).map_err(|e| e.msg)?;
        if let Some(k) = &self.receive_time_key {
            let read = engine.context_from_text(&[(k.clone(), "0".to_string())]).map_err(|e| e.msg)?;
            if !matches!(read.first(), Some((_, Value::I64(_)))) {
                return Err(format!("key-type-mismatch: the receive time is epoch milliseconds, and `{}` is not an int key", k));
            }
        }
        Ok(())
    }

    fn report(&self, stage: &str, format: &str, kind: &str, line: String) {
        let n = self.stats.fail_at(stage, format, kind);
        if n <= PRINTED_PER_KIND {
            eprintln!("{}: FAILED {}", self.name, line);
        }
        if n == PRINTED_PER_KIND {
            eprintln!("{}: further `{}` failures are counted and not printed", self.name, kind);
        }
    }

    /// The input bytes as the text the engine takes.
    fn input_text(&self, bytes: &[u8]) -> Result<String, AdapterError> {
        let binary = self.formats.is_binary(&self.from).unwrap_or(false);
        if binary && !self.in_hex {
            return Ok(bits::to_hex(bytes));
        }
        match std::str::from_utf8(bytes) {
            Ok(s) => Ok(s.trim().to_string()),
            Err(e) => Err(AdapterError::new("not-utf8", format!("the message is not UTF-8 text: {}", e))),
        }
    }

    /// One message to every output. `Err` is the reason to stop.
    fn handle(&mut self, seq: u64, msg: &Message) -> Result<(), String> {
        let origin = msg.origin.as_deref();
        let at = |to: &str| match origin {
            Some(o) => format!("message {} from {} -> {}", seq, o, to),
            None => format!("message {} -> {}", seq, to),
        };
        let stop = self.on_error == OnError::Stop;
        let text = match self.input_text(&msg.bytes) {
            Ok(t) => t,
            Err(e) => {
                let from = origin.map(|o| format!(" from {}", o)).unwrap_or_default();
                self.report("decode", &self.from, &e.kind, format!("message {}{}: {}", seq, from, e));
                return if stop { Err(e.to_string()) } else { Ok(()) };
            }
        };
        // the message's own context first: the engine keeps the first value of a key
        let mut context = msg.context.clone();
        if let (Some(k), Some(ms)) = (&self.receive_time_key, msg.received_ms) {
            context.push((k.clone(), ms.to_string()));
        }
        context.extend(self.context.iter().cloned());
        let context = if context.is_empty() { None } else { Some(context.as_slice()) };
        let engine = self.formats.engine();
        // one conversion per target format, however many outputs share it
        let mut done: Vec<(String, Result<String, Error>)> = Vec::new();
        for i in 0..self.outputs.len() {
            let to = self.outputs[i].to.clone();
            if !done.iter().any(|(t, _)| *t == to) {
                done.push((to.clone(), engine.convert_text(&self.from, &to, &text, context)));
            }
            let result = &done.iter().find(|(t, _)| *t == to).unwrap().1;
            // (stage, error name, text, fatal)
            let delivered = match result {
                Err(e) => {
                    // which side failed: decode the input alone (only on a failure)
                    let stage = if engine.decode(&self.from, &text).is_err() { "decode" } else { "encode" };
                    Err((stage, error_kind(&e.msg).to_string(), e.msg.clone(), false))
                }
                Ok(out) => {
                    let binary = self.formats.is_binary(&to).unwrap_or(false);
                    let bytes = if binary && !self.outputs[i].hex {
                        bits::from_hex(out).map_err(|e| ("encode", error_kind(&e.msg).to_string(), e.msg, false))
                    } else {
                        Ok(out.clone().into_bytes())
                    };
                    bytes.and_then(|b| {
                        self.outputs[i].sink.send(&b, &Meta { seq, origin }).map_err(|e| {
                            ("deliver", e.kind.clone(), format!("{} at {}", e, self.outputs[i].sink.describe()), e.fatal)
                        })
                    })
                }
            };
            match delivered {
                Ok(()) => {
                    self.stats.delivered(&to);
                }
                Err((stage, kind, text, fatal)) => {
                    let format = if stage == "decode" { self.from.clone() } else { to.clone() };
                    self.report(stage, &format, &kind, format!("{}: {}", at(&to), text));
                    if stop || fatal {
                        return Err(text);
                    }
                }
            }
        }
        Ok(())
    }

    fn main_loop(&mut self, stop: &AtomicBool) -> Outcome {
        let mut seq = 0u64;
        loop {
            if stop.load(Ordering::Relaxed) {
                return Outcome::Interrupted;
            }
            match self.source.recv() {
                Ok(Recv::Idle) => {}
                Ok(Recv::End) => break,
                Ok(Recv::Message(m)) => {
                    seq += 1;
                    self.stats.received.fetch_add(1, Ordering::Relaxed);
                    if let Err(why) = self.handle(seq, &m) {
                        return Outcome::Stopped(why);
                    }
                }
                Err(e) => {
                    self.report("source", &self.from, &e.kind, format!("source {}: {}", self.source.describe(), e));
                    if e.fatal || self.on_error == OnError::Stop {
                        return Outcome::Stopped(e.to_string());
                    }
                }
            }
        }
        if self.stats.failed_total() == 0 {
            Outcome::Completed
        } else {
            Outcome::CompletedWithFailures
        }
    }

    /// Run until the source ends, a failure stops the run, or `stop` is set.
    /// Sinks are flushed before this returns.
    pub fn run(&mut self, stop: &AtomicBool) -> Outcome {
        let done = AtomicBool::new(false);
        let every = self.status_every;
        let name = self.name.clone();
        let stats = self.stats.clone();
        // the status line is printed from its own thread, so a source that
        // waits for input does not hold it back
        let mut outcome = std::thread::scope(|s| {
            if let Some(every) = every {
                let done = &done;
                s.spawn(move || {
                    let mut last = Instant::now();
                    while !done.load(Ordering::Relaxed) {
                        std::thread::sleep(Duration::from_millis(50));
                        if last.elapsed() >= every {
                            eprintln!("{}: {}", name, stats.line());
                            last = Instant::now();
                        }
                    }
                });
            }
            let outcome = self.main_loop(stop);
            done.store(true, Ordering::Relaxed);
            outcome
        });
        for o in &mut self.outputs {
            if let Err(e) = o.sink.flush() {
                self.stats.fail_at("deliver", &o.to, &e.kind);
                eprintln!("{}: FAILED flush of {}: {}", self.name, o.sink.describe(), e);
                if !matches!(outcome, Outcome::Stopped(_)) {
                    outcome = Outcome::Stopped(e.to_string());
                }
            }
        }
        outcome
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn error_kind_is_the_engine_name_or_unnamed() {
        assert_eq!(error_kind("malformed-wire: unexpected end"), "malformed-wire");
        assert_eq!(error_kind("no-kind: format `x`"), "no-kind");
        assert_eq!(error_kind("no pack loaded for format `x`"), "unnamed");
        assert_eq!(error_kind("Something: odd"), "unnamed");
    }

    #[test]
    fn stats_line_lists_failures_by_kind() {
        let s = Stats::default();
        s.received.store(3, Ordering::Relaxed);
        s.converted.store(1, Ordering::Relaxed);
        s.fail("no-kind");
        s.fail("malformed-wire");
        s.fail("no-kind");
        assert!(s.line().starts_with("in=3 converted=1 failed=3 [malformed-wire=1 no-kind=2] "), "{}", s.line());
    }

    #[test]
    fn stats_by_format_and_stage() {
        let s = Stats::default();
        s.delivered("geojson");
        s.delivered("geojson");
        s.delivered("cot-xml");
        s.fail_at("decode", "nmea0183", "malformed-wire");
        s.fail_at("encode", "geojson", "transform-encode");
        s.fail_at("decode", "nmea0183", "malformed-wire");
        assert_eq!(s.converted.load(Ordering::Relaxed), 3);
        assert_eq!(s.delivered_by().into_iter().collect::<Vec<_>>(), vec![("cot-xml".to_string(), 1), ("geojson".to_string(), 2)]);
        let f = s.failed_by();
        assert_eq!(f[&("decode".to_string(), "nmea0183".to_string(), "malformed-wire".to_string())], 2);
        assert_eq!(f[&("encode".to_string(), "geojson".to_string(), "transform-encode".to_string())], 1);
        assert_eq!(s.failed_total(), 3);
    }
}
