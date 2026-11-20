//! goat-xf: the command-line tool of the reference engine, as the contract
//! of spec 0.23 states it (spec/engine-spec.md, Version 0.23).
//!
//! ```text
//! goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options>
//! goat-xf list-formats <options>
//! goat-xf capability --from <format> --to <format> <options>
//! goat-xf matrix <options>
//! goat-xf help
//! ```
//!
//! `<options>`: `--packs <dir>` (default `../../packs`), `--models <dir>`
//! (default `<packs>/../model`), `--packs-only <name>[,<name>...]`,
//! `--max-items <n>`, `--max-distribution <public|controlled>`.
//!
//! Exit status 0 on success, 1 on a load or call failure (standard error's
//! first line begins with the kind and a colon), 2 on a usage error.

use goat_transformers::{Capability, Distribution, Engine, Grade};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

const USAGE: &str = "\
usage: goat-xf <subcommand> [options]

  goat-xf convert --from <format> --to <format> [--set <key>=<value>]... <options> < input
  goat-xf list-formats <options>
  goat-xf capability --from <format> --to <format> <options>
  goat-xf matrix <options>
  goat-xf help

options:
  --packs <dir>                        the pack directory (default ../../packs)
  --models <dir>                       the model modules (default <packs>/../model)
  --packs-only <name>[,<name>...]      load only these packs of --packs, in this order
  --max-items <n>                      the limit on list items one decode holds (default 100000)
  --max-distribution <public|controlled>  refuse controlled modules and packs with `public`

Exit status: 0 success, 1 load or conversion error (stderr begins with its kind), 2 usage error.
";

#[derive(Clone, Copy, PartialEq)]
enum Sub {
    Convert,
    ListFormats,
    Capability,
    Matrix,
}

#[derive(Default)]
struct Args {
    from: Option<String>,
    to: Option<String>,
    set: Vec<(String, String)>,
    packs: Option<String>,
    models: Option<String>,
    packs_only: Option<Vec<String>>,
    max_items: Option<usize>,
    max_distribution: Option<Distribution>,
}

fn usage_error(why: &str) -> ! {
    eprintln!("goat-xf: {}", why);
    eprint!("{}", USAGE);
    std::process::exit(2);
}

fn fail(msg: &str) -> ! {
    eprintln!("{}", msg);
    std::process::exit(1);
}

/// `--max-items`: one or more ASCII digits, value at most 2^63 - 1; leading
/// zeros allowed.
fn max_items(text: &str) -> Option<usize> {
    if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let digits = text.trim_start_matches('0');
    if digits.len() > 19 {
        return None;
    }
    let n: u64 = if digits.is_empty() { 0 } else { digits.parse().ok()? };
    if n > i64::MAX as u64 {
        return None;
    }
    // on a 32-bit target a limit above usize::MAX is no limit at all
    Some(usize::try_from(n).unwrap_or(usize::MAX))
}

/// Check every argument before anything is loaded (the usage errors 1 to 10).
fn parse(argv: &[String]) -> (Sub, Args) {
    let first = match argv.first() {
        Some(a) => a.as_str(),
        None => usage_error("no subcommand"),
    };
    let sub = match first {
        "help" | "-h" | "--help" => {
            print!("{}", USAGE);
            std::process::exit(0);
        }
        "convert" => Sub::Convert,
        "list-formats" => Sub::ListFormats,
        "capability" => Sub::Capability,
        "matrix" => Sub::Matrix,
        other => usage_error(&format!("unknown subcommand `{}`", other)),
    };
    let takes_pair = matches!(sub, Sub::Convert | Sub::Capability);
    let mut a = Args::default();
    let mut seen: Vec<&str> = Vec::new();
    let mut i = 1;
    while i < argv.len() {
        let name = argv[i].as_str();
        let known = match name {
            "--packs" | "--models" | "--packs-only" | "--max-items" | "--max-distribution" => true,
            "--from" | "--to" => takes_pair,
            "--set" => sub == Sub::Convert,
            _ => false,
        };
        if !known {
            usage_error(&format!("`{}` is not an option of this subcommand", name));
        }
        let value = match argv.get(i + 1) {
            Some(v) => v.clone(),
            None => usage_error(&format!("{} needs a value", name)),
        };
        if name != "--set" {
            if seen.contains(&name) {
                usage_error(&format!("{} is given twice", name));
            }
            seen.push(name);
        }
        match name {
            "--from" => a.from = Some(value),
            "--to" => a.to = Some(value),
            "--set" => match value.split_once('=') {
                Some((k, v)) if !k.is_empty() => a.set.push((k.to_string(), v.to_string())),
                _ => usage_error("--set needs <key>=<value>"),
            },
            "--packs" => a.packs = Some(value),
            "--models" => a.models = Some(value),
            "--packs-only" => {
                let names: Vec<String> = value.split(',').map(str::to_string).collect();
                if value.is_empty() || names.iter().any(|n| n.is_empty()) {
                    usage_error("--packs-only needs <name>[,<name>...] with no empty name");
                }
                a.packs_only = Some(names);
            }
            "--max-items" => match max_items(&value) {
                Some(n) => a.max_items = Some(n),
                None => usage_error("--max-items is an unsigned decimal integer of at most 2^63 - 1"),
            },
            "--max-distribution" => match value.as_str() {
                "public" | "controlled" => a.max_distribution = Distribution::parse(&value),
                _ => usage_error("--max-distribution is `public` or `controlled`"),
            },
            _ => unreachable!(),
        }
        i += 2;
    }
    if takes_pair && (a.from.is_none() || a.to.is_none()) {
        usage_error("--from and --to are required");
    }
    (sub, a)
}

/// A `--packs-only` name: one path component, not `.` or `..`.
fn plain_name(name: &str) -> bool {
    !(name.is_empty() || name == "." || name == ".." || name.contains('/') || name.contains('\\'))
}

fn load_pack_file(engine: &mut Engine, def: &Path) -> Result<(), String> {
    let text = std::fs::read(def).map_err(|e| format!("cannot read {}: {}", def.display(), e))?;
    let text = String::from_utf8(text).map_err(|_| format!("cannot read {}: not UTF-8", def.display()))?;
    engine.load_def(&text).map_err(|e| format!("{} (in {})", e, def.display()))
}

/// Loading, step 2: the packs, in the order the contract states.
fn load_packs(engine: &mut Engine, packs: &Path, only: Option<&[String]>) -> Result<(), String> {
    match only {
        Some(names) => {
            for name in names {
                let def = packs.join(name).join("pack.def");
                if !plain_name(name) || !def.is_file() {
                    return Err(format!(
                        "unknown-format: `{}` is not a pack directory of {}",
                        name,
                        packs.display()
                    ));
                }
                load_pack_file(engine, &def)?;
            }
        }
        None => {
            let rd = std::fs::read_dir(packs).map_err(|e| format!("cannot read {}: {}", packs.display(), e))?;
            let mut names: Vec<Vec<u8>> = Vec::new();
            for entry in rd {
                let entry = entry.map_err(|e| format!("cannot read {}: {}", packs.display(), e))?;
                let name = entry.file_name().into_string().map_err(|n| {
                    format!("cannot read {}: a name that is not UTF-8 ({:?})", packs.display(), n)
                })?;
                if !name.starts_with('.') {
                    names.push(name.into_bytes());
                }
            }
            names.sort();
            for name in names {
                let name = String::from_utf8(name).expect("checked above");
                let def = packs.join(&name).join("pack.def");
                if def.is_file() {
                    load_pack_file(engine, &def)?;
                }
            }
        }
    }
    Ok(())
}

fn grade(g: Grade) -> &'static str {
    match g {
        Grade::Full => "full",
        Grade::Partial => "partial",
        Grade::None => "none",
    }
}

fn line(c: &Capability) -> String {
    format!("{}\t{}\t{}\t{}\t{}\n", c.from, c.to, grade(c.grade), c.carried.join(" "), c.dropped.join(" "))
}

/// Format names in byte order (BTreeMap order of `String` is byte order).
fn formats(engine: &Engine) -> Vec<String> {
    let mut f = engine.formats();
    f.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
    f
}

fn write_out(bytes: &[u8]) {
    let mut out = std::io::stdout().lock();
    if out.write_all(bytes).and_then(|_| out.flush()).is_err() {
        // a closed pipe: nothing more can be said on standard output
        std::process::exit(1);
    }
}

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let (sub, a) = parse(&argv);

    let packs = a.packs.clone().unwrap_or_else(|| "../../packs".to_string());
    // `<packs>` as given, then `/../model`, resolved by the operating system
    let models = a.models.clone().unwrap_or_else(|| format!("{}/../model", packs));
    let mut engine = Engine::new();
    if let Some(d) = a.max_distribution {
        engine.set_max_distribution(d);
    }
    if let Some(n) = a.max_items {
        engine.set_max_items(n);
    }
    let models_dir = PathBuf::from(&models);
    if models_dir.is_dir() {
        if let Err(e) = engine.load_model_dir(&models_dir) {
            fail(&e.to_string());
        }
    }
    if let Err(e) = load_packs(&mut engine, Path::new(&packs), a.packs_only.as_deref()) {
        fail(&e);
    }

    match sub {
        Sub::ListFormats => {
            let mut out = String::new();
            for f in formats(&engine) {
                let (version, wire) = engine.pack_header(&f).expect("a loaded format");
                out.push_str(&format!("{}\t{}\t{}\n", f, version, wire));
            }
            write_out(out.as_bytes());
        }
        Sub::Capability => {
            let (from, to) = (a.from.as_deref().unwrap(), a.to.as_deref().unwrap());
            for f in [from, to] {
                if engine.wire(f).is_none() {
                    fail(&format!("unknown-format: no pack loaded for format `{}`", f));
                }
            }
            write_out(line(&engine.capability(from, to)).as_bytes());
        }
        Sub::Matrix => {
            let fmts = formats(&engine);
            let mut out = String::from("from\tto\tgrade\tcarried\tdropped\n");
            for f in &fmts {
                for t in &fmts {
                    out.push_str(&line(&engine.capability(f, t)));
                }
            }
            write_out(out.as_bytes());
        }
        Sub::Convert => {
            let (from, to) = (a.from.as_deref().unwrap(), a.to.as_deref().unwrap());
            // `--from`, then `--to`, before standard input is read
            for f in [from, to] {
                if engine.wire(f).is_none() {
                    fail(&format!("unknown-format: no pack loaded for format `{}`", f));
                }
            }
            let mut input = Vec::new();
            if let Err(e) = std::io::stdin().read_to_end(&mut input) {
                fail(&format!("cannot read standard input: {}", e));
            }
            let input = match String::from_utf8(input) {
                Ok(s) => s,
                Err(_) => fail("malformed-wire: the input is not valid UTF-8"),
            };
            // a key given twice: its last value, at the place of its first
            let mut context: Vec<(String, String)> = Vec::new();
            for (k, v) in &a.set {
                match context.iter_mut().find(|(ck, _)| ck == k) {
                    Some(slot) => slot.1 = v.clone(),
                    None => context.push((k.clone(), v.clone())),
                }
            }
            let context = if a.set.is_empty() { None } else { Some(context.as_slice()) };
            match engine.convert_text(from, to, &input, context) {
                Ok(out) => write_out(out.as_bytes()),
                Err(e) => fail(&e.to_string()),
            }
        }
    }
}
