//! goat-xf: command-line driver for the reference engine.
//!
//! Usage:
//!   goat-xf convert --from <fmt> --to <fmt> [--set <key>=<value>]... --packs <dir> < input
//!   goat-xf list-formats --packs <dir>
//!   goat-xf matrix [--detail] --packs <dir>
//!
//! Model modules are read from `--models <dir>` (default: `model/` beside the
//! packs directory). `--max-distribution public` refuses controlled modules and
//! packs. `--set` supplies a model key the input does not carry (engine-spec
//! v0.6, caller-supplied keys); it is repeatable.
//!
//! `--packs-only <name>[,<name>...]` loads only the named packs of the packs
//! directory (a name is the directory of a pack, which is its format name)
//! and leaves the rest unread: a conversion needs its two packs, and loading
//! them takes a fraction of the time of loading every pack. Every command
//! then sees only those formats. A library caller does the same with
//! `Engine::load_pack_dir_only`, or with `Engine::load_def` per pack text.

use goat_transformers::{Distribution, Engine, Grade};
use std::io::Read;
use std::path::Path;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: goat-xf <convert|list-formats|matrix> [--packs <dir>] [--packs-only <name>[,<name>...]] [opts]");
        std::process::exit(2);
    }
    let packs_dir = opt(&args, "--packs").unwrap_or_else(|| "../../packs".to_string());
    let models_dir = opt(&args, "--models").unwrap_or_else(|| {
        Path::new(&packs_dir).join("../model").to_string_lossy().into_owned()
    });
    let mut engine = Engine::new();
    if let Some(d) = opt(&args, "--max-distribution") {
        match Distribution::parse(&d) {
            Some(d) => engine.set_max_distribution(d),
            None => {
                eprintln!("--max-distribution is `public` or `controlled`");
                std::process::exit(2);
            }
        }
    }
    if let Err(e) = engine.load_model_dir(Path::new(&models_dir)) {
        eprintln!("error loading model modules from {}: {}", models_dir, e);
        std::process::exit(1);
    }
    let loaded = match opt(&args, "--packs-only") {
        Some(list) => {
            let names: Vec<&str> = list.split(',').map(|n| n.trim()).filter(|n| !n.is_empty()).collect();
            if names.is_empty() {
                eprintln!("--packs-only needs <name>[,<name>...]");
                std::process::exit(2);
            }
            engine.load_pack_dir_only(Path::new(&packs_dir), &names)
        }
        None if args.iter().any(|a| a == "--packs-only") => {
            eprintln!("--packs-only needs <name>[,<name>...]");
            std::process::exit(2);
        }
        None => engine.load_pack_dir(Path::new(&packs_dir)),
    };
    if let Err(e) = loaded {
        eprintln!("error loading packs from {}: {}", packs_dir, e);
        std::process::exit(1);
    }
    match args[1].as_str() {
        "list-formats" => {
            // the packs are loaded: their formats, sorted
            for f in engine.formats() {
                println!("{}", f);
            }
        }
        "convert" => {
            let from = opt(&args, "--from").expect("--from required");
            let to = opt(&args, "--to").expect("--to required");
            let mut input = String::new();
            std::io::stdin().read_to_string(&mut input).unwrap();
            // --set <key>=<value>, repeatable: the context of the conversion
            let mut pairs: Vec<(String, String)> = Vec::new();
            for (i, a) in args.iter().enumerate() {
                if a == "--set" {
                    match args.get(i + 1).and_then(|kv| kv.split_once('=')) {
                        Some((k, v)) => pairs.push((k.to_string(), v.to_string())),
                        None => {
                            eprintln!("--set needs <key>=<value>");
                            std::process::exit(2);
                        }
                    }
                }
            }
            // no `--set`: no context given
            let context = if pairs.is_empty() { None } else { Some(pairs.as_slice()) };
            // a `text` record is taken as it is: its decode steps remove one
            // line terminator, and its spaces may be characters of a column
            let input = if engine.wire(&from) == Some(goat_transformers::Wire::Text) { input.as_str() } else { input.trim() };
            let result = engine.convert_text(&from, &to, input, context);
            match result {
                Ok(out) => println!("{}", out),
                Err(e) => {
                    eprintln!("convert error: {}", e);
                    std::process::exit(1);
                }
            }
        }
        "matrix" => {
            let detail = args.iter().any(|a| a == "--detail");
            print_matrix(&engine, detail);
        }
        other => {
            eprintln!("unknown command `{}`", other);
            std::process::exit(2);
        }
    }
}

fn opt(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned()
}

/// Print the N x N conversion capability matrix: for every ordered format pair,
/// whether a conversion carries all / some / none of the source's fields, and
/// (with --detail) exactly which fields carry and which are dropped and why.
fn print_matrix(engine: &Engine, detail: bool) {
    let fmts = engine.formats();
    let w = fmts.iter().map(|f| f.len()).max().unwrap_or(4).max(4);
    // header
    print!("{:>w$} ", "from\\to", w = w);
    for f in &fmts {
        print!("{:>6} ", &f[..f.len().min(6)]);
    }
    println!();
    // legend: F = full (lossless over mapped fields), P = partial (some dropped),
    // . = none (no shared fields), - = same format
    for a in &fmts {
        print!("{:>w$} ", a, w = w);
        for b in &fmts {
            let cell = if a == b {
                "-"
            } else {
                match engine.capability(a, b).grade {
                    Grade::Full => "F",
                    Grade::Partial => "P",
                    Grade::None => ".",
                }
            };
            print!("{:>6} ", cell);
        }
        println!();
    }
    println!("\nF = all mapped fields carry   P = some carry, some dropped   . = no shared fields   - = same format");
    if detail {
        println!("\nPer-pair detail (carried | dropped and why):");
        for c in engine.capability_matrix() {
            let why = if c.dropped.is_empty() {
                String::new()
            } else {
                format!(
                    "  dropped: {} (target `{}` has no field for them)",
                    c.dropped.join(", "),
                    c.to
                )
            };
            let grade = match c.grade {
                Grade::Full => "FULL",
                Grade::Partial => "PARTIAL",
                Grade::None => "NONE",
            };
            println!(
                "  {:>14} -> {:<14} {:7}  carries: [{}]{}",
                c.from,
                c.to,
                grade,
                c.carried.join(", "),
                why
            );
        }
    }
}
