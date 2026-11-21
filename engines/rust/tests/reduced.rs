//! Engine-spec 0.24, ruling 1c: in a build with fewer wires, a pack whose
//! `wire` is a wire of the specification the build lacks is `unknown-wire`,
//! and the message names the wire and says this build does not have it. For
//! every wire the build lacks, one pack of the repository on that wire is
//! loaded; a `wire` value that is no wire at all stays `unknown-wire` with the
//! message it had. In a build with all seven wires only the second check runs.
//! `engines/rust/reduced-build-check.sh` runs this test with `xml`, `json` and
//! `geojson`, beside `tests/vectors.rs`.

use goat_transformers::{build_wires, Engine, Wire};
use std::path::{Path, PathBuf};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn engine() -> Engine {
    let mut e = Engine::new();
    e.load_model_dir(&root().join("model")).unwrap();
    e
}

/// The `wire` value of a pack text.
fn wire_of(text: &str) -> Option<&str> {
    text.lines().find_map(|l| {
        let t: Vec<&str> = l.split_whitespace().collect();
        match t.as_slice() {
            ["wire", w] => Some(*w),
            _ => None,
        }
    })
}

/// The first pack of the repository, by directory name, on `wire`.
fn pack_on(wire: &str) -> Option<(String, String)> {
    let mut dirs: Vec<_> = std::fs::read_dir(root().join("packs")).unwrap().flatten().map(|d| d.path()).collect();
    dirs.sort();
    dirs.into_iter().find_map(|d| {
        let text = std::fs::read_to_string(d.join("pack.def")).ok()?;
        (wire_of(&text) == Some(wire)).then(|| (d.file_name().unwrap().to_string_lossy().into_owned(), text))
    })
}

#[test]
fn a_wire_the_build_lacks_is_unknown_wire() {
    use std::io::Write;
    let built = build_wires();
    let mut out = std::io::stderr();
    let _ = writeln!(out, "this build has the wires {}", built.join(","));
    let mut failures = Vec::new();
    let mut checked = 0;
    for w in Wire::ALL.iter().filter(|w| !w.in_build()) {
        let name = w.name();
        let (pack, text) = pack_on(name).unwrap_or_else(|| panic!("no pack of the repository is on `{}`", name));
        checked += 1;
        match engine().load_def(&text) {
            Ok(()) => failures.push(format!("{} (wire {}): loaded", pack, name)),
            Err(e) => {
                let named = e.msg.contains(&format!("`{}`", name));
                let says = e.msg.contains("this build does not have");
                if e.msg.starts_with("unknown-wire:") && named && says {
                    let _ = writeln!(out, "  {} (wire {}): {}", pack, name, e.msg);
                } else {
                    failures.push(format!("{} (wire {}): {}", pack, name, e.msg));
                }
            }
        }
    }
    let _ = writeln!(out, "loaded {} packs on a wire this build lacks, {} failed", checked, failures.len());
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn a_value_that_is_no_wire_is_unknown_wire_as_before() {
    let text = "format p\nversion 0.24.0\ndistribution public\nsource \"probe\"\nuses core\nwire morse\n";
    let e = engine().load_def(text).unwrap_err();
    assert!(e.msg.starts_with("unknown-wire:"), "{}", e.msg);
    assert!(!e.msg.contains("this build"), "{}", e.msg);
    assert!(e.msg.contains("`morse` is not a wire"), "{}", e.msg);
}
