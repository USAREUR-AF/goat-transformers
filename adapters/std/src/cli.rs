//! The `goat-xf-pipe` command line.
//!
//! Everything is an option, and a configuration file is the same options
//! one per line without the dashes, so there is one grammar. An adapter
//! crate with its own dependency calls [`run`] with its [`Scheme`] and gets
//! the same tool with one more transport.

use crate::uri::{open_sink, open_source, Scheme};
use goat_adapters_core::frame::Framing;
use goat_adapters_core::pipeline::{Formats, OnError, Outcome, Output, Pipeline};
use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::time::Duration;

pub const USAGE: &str = "\
goat-xf-pipe: messages arrive on one endpoint and leave, converted, on others.

  goat-xf-pipe --packs <dir> --from-format <format> --in <uri> [--in-frame <framing>]
               --out <uri> --to-format <format> [--out-frame <framing>]  [--out ...]...

Formats
  --packs <dir>            the packs directory
  --models <dir>           the model modules (default: model/ beside the packs directory)
  --packs-only             load only the packs of the formats this command names
  --max-distribution <d>   public or controlled: refuse anything marked above it
  --from-format <format>   the format of the messages that arrive
  --to-format <format>     the format of the messages that leave

Endpoints
  --in <uri>               where messages arrive (one)
  --out <uri>              where converted messages leave (one or more)
  --in-frame <framing>     how one message is delimited on the input
  --out-frame <framing>    how one message is delimited on an output
  --to-format and --out-frame written before the first --out are the default
  for every output; written after an --out they apply to that output.

  uri        stdin:   stdout:   file:<path>   dir:<path>   serial:<device>
             tcp://<host>:<port>   tcp-listen://[<host>]:<port>
             udp://[<host>]:<port>   udp://<group>:<port>?iface=<address>
  framing    newline | len:<N>:<be|le> | fixed:<N> | start:<byte>:len:<N>:<be|le>[:total]
             | at:<offset>:len:<N>:<be|le>:<whole|rest> | whole
             | mavlink2 (MAVLink 2 frames; a trimmed payload is zero-filled to its full length)
             then optionally ,max=<bytes> and ,hex
  udp and dir endpoints are `whole` unless stated (one datagram or one file is
  one message). Every other endpoint is a stream and its framing must be stated.

Conversion
  --set <key>=<value>      a model key the input does not carry (repeatable)
  --set-receive-time <key> give this model key the time a message was received
                           (epoch milliseconds) when the message has no value for it

Failure
  --on-error skip|stop     skip: count the message, report it, go on (default)
                           stop: count it, report it, stop
  --status-every <seconds> the status line on stderr (default 10; 0 for none)
  --metrics <addr>         serve the counters for Prometheus on GET /metrics at
                           <addr> (`:9464` for every address, `127.0.0.1:9464`):
                           messages in and out by format, errors by stage
                           (decode, encode, deliver, source), format and name

  --config <file>          read options from a file: one per line, no dashes,
                           `#` starts a comment
  --help

Exit status: 0 every message converted and delivered; 1 stopped on a failure;
2 the command line or the configuration is wrong; 3 the input ended and some
messages failed and were skipped.
";

#[derive(Debug, Clone, Default, PartialEq)]
pub struct OutSpec {
    pub uri: String,
    pub to: Option<String>,
    pub frame: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Config {
    pub packs: Option<String>,
    pub models: Option<String>,
    pub packs_only: bool,
    pub max_distribution: Option<String>,
    pub from: Option<String>,
    pub input: Option<String>,
    pub in_frame: Option<String>,
    pub default_to: Option<String>,
    pub default_out_frame: Option<String>,
    pub outs: Vec<OutSpec>,
    pub sets: Vec<(String, String)>,
    pub receive_time_key: Option<String>,
    pub on_error: OnError,
    pub status_every: u64,
    pub metrics: Option<String>,
    pub help: bool,
}

impl Default for Config {
    fn default() -> Config {
        Config {
            packs: None,
            models: None,
            packs_only: false,
            max_distribution: None,
            from: None,
            input: None,
            in_frame: None,
            default_to: None,
            default_out_frame: None,
            outs: Vec::new(),
            sets: Vec::new(),
            receive_time_key: None,
            on_error: OnError::Skip,
            status_every: 10,
            metrics: None,
            help: false,
        }
    }
}

/// The options of a configuration file, as arguments. A line is an option
/// name without its dashes and, for an option that takes one, its value:
/// the rest of the line, or the text between double quotes. `#` at the start
/// of a line, or after white space, starts a comment.
pub fn config_args(text: &str) -> Result<Vec<String>, String> {
    let mut out = Vec::new();
    for (i, line) in text.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let (key, rest) = line.split_once(char::is_whitespace).unwrap_or((line, ""));
        let rest = rest.trim();
        let value = if let Some(q) = rest.strip_prefix('"') {
            let (v, after) = q.split_once('"').ok_or(format!("line {}: a quote is not closed", i + 1))?;
            let after = after.trim();
            if !after.is_empty() && !after.starts_with('#') {
                return Err(format!("line {}: text after the closing quote", i + 1));
            }
            v.to_string()
        } else {
            let end = rest.find(" #").or(rest.find("\t#")).unwrap_or(rest.len());
            rest[..if rest.starts_with('#') { 0 } else { end }].trim().to_string()
        };
        if key.starts_with('-') {
            return Err(format!("line {}: write `{}` without dashes", i + 1, key));
        }
        out.push(format!("--{}", key));
        if !value.is_empty() || rest.starts_with('"') {
            out.push(value);
        }
    }
    Ok(out)
}

pub fn parse_args(args: &[String]) -> Result<Config, String> {
    parse_into(args, Config::default(), 0)
}

fn parse_into(args: &[String], mut c: Config, depth: usize) -> Result<Config, String> {
    let mut i = 0;
    let once = |slot: &mut Option<String>, name: &str, v: String| match slot.replace(v) {
        Some(_) => Err(format!("{} is given twice", name)),
        None => Ok(()),
    };
    while i < args.len() {
        let name = args[i].as_str();
        i += 1;
        match name {
            "--help" | "-h" => {
                c.help = true;
                continue;
            }
            "--packs-only" => {
                c.packs_only = true;
                continue;
            }
            _ => {}
        }
        if !name.starts_with("--") {
            return Err(format!("unexpected `{}`", name));
        }
        let v = match args.get(i) {
            Some(v) if !v.starts_with("--") => v.clone(),
            _ => return Err(format!("{} needs a value", name)),
        };
        i += 1;
        match name {
            "--packs" => once(&mut c.packs, name, v)?,
            "--models" => once(&mut c.models, name, v)?,
            "--max-distribution" => once(&mut c.max_distribution, name, v)?,
            "--from-format" => once(&mut c.from, name, v)?,
            "--in" => once(&mut c.input, name, v)?,
            "--in-frame" => once(&mut c.in_frame, name, v)?,
            "--out" => c.outs.push(OutSpec { uri: v, to: None, frame: None }),
            "--to-format" => match c.outs.last_mut() {
                Some(o) => once(&mut o.to, name, v)?,
                None => once(&mut c.default_to, name, v)?,
            },
            "--out-frame" => match c.outs.last_mut() {
                Some(o) => once(&mut o.frame, name, v)?,
                None => once(&mut c.default_out_frame, name, v)?,
            },
            "--set" => match v.split_once('=') {
                Some((k, val)) if !k.is_empty() => c.sets.push((k.to_string(), val.to_string())),
                _ => return Err("--set needs <key>=<value>".to_string()),
            },
            "--set-receive-time" => once(&mut c.receive_time_key, name, v)?,
            "--on-error" => {
                c.on_error = match v.as_str() {
                    "skip" => OnError::Skip,
                    "stop" => OnError::Stop,
                    _ => return Err("--on-error is `skip` or `stop`".to_string()),
                }
            }
            "--status-every" => c.status_every = v.parse().map_err(|_| "--status-every is a number of seconds".to_string())?,
            "--metrics" => once(&mut c.metrics, name, v)?,
            "--config" => {
                if depth > 0 {
                    return Err("a configuration file cannot name another".to_string());
                }
                let text = std::fs::read_to_string(&v).map_err(|e| format!("cannot read {}: {}", v, e))?;
                let more = config_args(&text).map_err(|e| format!("{}: {}", v, e))?;
                c = parse_into(&more, c, depth + 1).map_err(|e| format!("{}: {}", v, e))?;
            }
            _ => return Err(format!("unknown option `{}`", name)),
        }
    }
    Ok(c)
}

/// Run the tool. `name` begins each line on stderr; `extra` are the schemes
/// of adapter crates beyond the standard-library ones. Returns the exit status.
pub fn run(name: &str, args: &[String], extra: &[&dyn Scheme]) -> i32 {
    let usage = |why: String| {
        eprintln!("{}: {}\n{}: `{} --help` prints the options", name, why, name, name);
        2
    };
    let c = match parse_args(args) {
        Ok(c) => c,
        Err(e) => return usage(e),
    };
    if c.help || args.is_empty() {
        print!("{}", USAGE.replace("goat-xf-pipe", name));
        for s in extra {
            println!("\nAlso in this build\n  {}", s.help());
        }
        return if c.help { 0 } else { 2 };
    }
    let need = |v: &Option<String>, flag: &str| v.clone().ok_or(format!("{} is required", flag));
    let (packs, from, input) = match (need(&c.packs, "--packs"), need(&c.from, "--from-format"), need(&c.input, "--in")) {
        (Ok(p), Ok(f), Ok(i)) => (p, f, i),
        (Err(e), _, _) | (_, Err(e), _) | (_, _, Err(e)) => return usage(e),
    };
    if c.outs.is_empty() {
        return usage("--out is required".to_string());
    }
    let mut outs = Vec::new();
    for o in &c.outs {
        let Some(to) = o.to.clone().or(c.default_to.clone()) else {
            return usage(format!("--out {} has no --to-format", o.uri));
        };
        outs.push((o.uri.clone(), to, o.frame.clone().or(c.default_out_frame.clone())));
    }
    let frame = |s: &Option<String>| s.as_deref().map(Framing::parse).transpose();
    let in_frame = match frame(&c.in_frame) {
        Ok(f) => f,
        Err(e) => return usage(format!("--in-frame {}", e)),
    };

    // the formats
    let max = match c.max_distribution.as_deref().map(|d| goat_adapters_core::pipeline::parse_distribution(d)) {
        Some(None) => return usage("--max-distribution is `public` or `controlled`".to_string()),
        Some(d) => d,
        None => None,
    };
    let models = c.models.clone().unwrap_or_else(|| Path::new(&packs).join("../model").to_string_lossy().into_owned());
    let mut named: Vec<String> = vec![from.clone()];
    named.extend(outs.iter().map(|o| o.1.clone()));
    named.dedup();
    let only = if c.packs_only { Some(named.as_slice()) } else { None };
    let formats = match Formats::load(Path::new(&models), Path::new(&packs), only, max) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("{}: cannot load the formats: {}", name, e);
            return 2;
        }
    };

    // MAVLink 2 framing reads each message's full payload length from the packs it decodes
    let in_frame = match in_frame {
        Some(mut f) => {
            if let goat_adapters_core::frame::FrameSpec::Mavlink2 { .. } = f.spec {
                let mut lengths = std::collections::BTreeMap::new();
                for fmt in named.iter().filter(|n| n.starts_with("mavlink2")) {
                    if let Ok(text) = std::fs::read_to_string(Path::new(&packs).join(fmt).join("pack.def")) {
                        goat_adapters_core::frame::mavlink2_lengths(&text, &mut lengths);
                    }
                }
                if lengths.is_empty() {
                    return usage("--in-frame mavlink2 needs --from-format mavlink2 (or a mavlink2 dialect) and its pack".to_string());
                }
                f.spec = goat_adapters_core::frame::FrameSpec::Mavlink2 { lengths: std::sync::Arc::new(lengths) };
            }
            Some(f)
        }
        None => None,
    };

    // the endpoints
    let source = match open_source(&input, in_frame.as_ref(), extra) {
        Ok(s) => s,
        Err(e) => return usage(format!("--in {}", e)),
    };
    let mut outputs = Vec::new();
    let mut shown = Vec::new();
    for (uri, to, fr) in &outs {
        let fr = match frame(fr) {
            Ok(f) => f,
            Err(e) => return usage(format!("--out-frame {}", e)),
        };
        let sink = match open_sink(uri, fr.as_ref(), extra) {
            Ok(s) => s,
            Err(e) => return usage(format!("--out {}", e)),
        };
        shown.push(format!("{} to {}", to, uri));
        outputs.push(Output { to: to.clone(), hex: fr.map_or(false, |f| f.hex), sink });
    }

    let mut p = Pipeline::new(&formats, &from, source, outputs);
    p.in_hex = in_frame.map_or(false, |f| f.hex);
    p.context = c.sets.clone();
    p.receive_time_key = c.receive_time_key.clone();
    p.on_error = c.on_error;
    p.status_every = if c.status_every == 0 { None } else { Some(Duration::from_secs(c.status_every)) };
    p.name = name.to_string();
    if let Err(e) = p.check() {
        return usage(e);
    }
    if let Some(addr) = &c.metrics {
        match crate::metrics::serve(addr, p.stats.clone(), from.clone()) {
            Ok(bound) => eprintln!("{}: metrics at http://{}/metrics", name, bound),
            Err(e) => return usage(format!("--metrics {}", e)),
        }
    }
    let policy = if c.on_error == OnError::Stop { "stop" } else { "skip" };
    eprintln!("{}: {} from {} -> {}; on-error {}", name, from, input, shown.join(", "), policy);
    let outcome = p.run(&AtomicBool::new(false));
    let line = p.stats.line();
    match outcome {
        Outcome::Completed => {
            eprintln!("{}: done: {}", name, line);
            0
        }
        Outcome::CompletedWithFailures => {
            eprintln!("{}: done, WITH FAILURES: {}", name, line);
            3
        }
        Outcome::Stopped(why) => {
            eprintln!("{}: STOPPED on failure ({}): {}", name, why, line);
            1
        }
        Outcome::Interrupted => {
            eprintln!("{}: interrupted: {}", name, line);
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(s: &[&str]) -> Vec<String> {
        s.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn options_before_the_first_out_are_defaults_and_after_an_out_belong_to_it() {
        let c = parse_args(&args(&[
            "--packs", "p", "--from-format", "cot-xml", "--in", "udp://:4242", "--to-format", "geojson", "--out-frame", "newline",
            "--out", "stdout:", "--out", "dir:out", "--to-format", "cot-xml", "--out-frame", "whole", "--out", "tcp://h:1",
            "--set", "uid=a=b", "--set", "time_ms=5", "--on-error", "stop", "--status-every", "0", "--packs-only",
            "--metrics", ":9464",
        ]))
        .unwrap();
        assert_eq!(c.default_to.as_deref(), Some("geojson"));
        assert_eq!(c.default_out_frame.as_deref(), Some("newline"));
        assert_eq!(c.outs[0], OutSpec { uri: "stdout:".into(), to: None, frame: None });
        assert_eq!(c.outs[1], OutSpec { uri: "dir:out".into(), to: Some("cot-xml".into()), frame: Some("whole".into()) });
        assert_eq!(c.outs[2], OutSpec { uri: "tcp://h:1".into(), to: None, frame: None });
        assert_eq!(c.sets, vec![("uid".to_string(), "a=b".to_string()), ("time_ms".to_string(), "5".to_string())]);
        assert_eq!((c.on_error, c.status_every, c.packs_only), (OnError::Stop, 0, true));
        assert_eq!(c.metrics.as_deref(), Some(":9464"));
    }

    #[test]
    fn wrong_command_lines_are_refused() {
        for (bad, why) in [
            (vec!["--in"], "needs a value"),
            (vec!["--in", "a", "--in", "b"], "given twice"),
            (vec!["--on-error", "ignore"], "`skip` or `stop`"),
            (vec!["--set", "novalue"], "<key>=<value>"),
            (vec!["--loud", "1"], "unknown option"),
            (vec!["stray"], "unexpected"),
            (vec!["--status-every", "soon"], "number of seconds"),
        ] {
            let e = parse_args(&args(&bad)).unwrap_err();
            assert!(e.contains(why), "{:?}: {}", bad, e);
        }
    }

    #[test]
    fn a_configuration_file_is_the_same_options_one_per_line() {
        let text = "# a pipe\nfrom-format cot-xml\npacks \"my packs\"  # quoted\npacks-only\nin udp://:4242   # the feed\n\nout tcp-listen://:9000\n  to-format geojson\n  out-frame newline\nset track.source_id=radar 1\n";
        let a = config_args(text).unwrap();
        assert_eq!(
            a,
            args(&[
                "--from-format", "cot-xml", "--packs", "my packs", "--packs-only", "--in", "udp://:4242", "--out", "tcp-listen://:9000",
                "--to-format", "geojson", "--out-frame", "newline", "--set", "track.source_id=radar 1"
            ])
        );
        let c = parse_args(&a).unwrap();
        assert_eq!(c.packs.as_deref(), Some("my packs"));
        assert_eq!(c.outs[0].to.as_deref(), Some("geojson"));
        assert_eq!(c.sets[0], ("track.source_id".to_string(), "radar 1".to_string()));
        assert!(config_args("packs \"open").unwrap_err().contains("line 1"));
        assert!(config_args("--packs x").unwrap_err().contains("without dashes"));
    }

    #[test]
    fn a_configuration_file_and_arguments_combine_and_a_file_cannot_name_another() {
        let d = std::env::temp_dir().join(format!("goat-adapters-cli-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        let f = d.join("pipe.conf");
        std::fs::write(&f, "from-format cot-xml\nin stdin:\nin-frame newline\n").unwrap();
        let c = parse_args(&args(&["--config", f.to_str().unwrap(), "--out", "stdout:", "--to-format", "geojson"])).unwrap();
        assert_eq!((c.from.as_deref(), c.input.as_deref(), c.outs.len()), (Some("cot-xml"), Some("stdin:"), 1));
        std::fs::write(&f, "config other.conf\n").unwrap();
        assert!(parse_args(&args(&["--config", f.to_str().unwrap()])).unwrap_err().contains("cannot name another"));
        std::fs::remove_dir_all(d).unwrap();
    }
}
