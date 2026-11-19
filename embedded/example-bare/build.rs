//! Compile the plan this example links: Remote ID `location` messages to
//! ASTERIX CAT062 track records. The blob is build output, written to
//! OUT_DIR as a Rust `static`; nothing generated is kept in the tree.

use std::path::PathBuf;
use std::process::Command;

fn main() {
    let here = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let root = here.join("../..");
    let out = PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("plan.rs");
    let status = Command::new("python3")
        .arg("-I")
        .arg(root.join("tools/gen/packc.py"))
        .args(["--from", "remote-id:location", "--to", "asterix-cat062"])
        .args(["--context", "cat062.sac,cat062.sic,cat062.time_of_day_s,cat062.track_number,track.confirmed"])
        .args(["--static", "PLAN", "--quiet", "--out-rs"])
        .arg(&out)
        .status()
        .expect("python3 runs tools/gen/packc.py");
    assert!(status.success(), "packc refused the plan");
    for watched in ["tools/gen/packc.py", "packs/remote-id/pack.def", "packs/asterix-cat062/pack.def", "model"] {
        println!("cargo:rerun-if-changed={}", root.join(watched).display());
    }
}
