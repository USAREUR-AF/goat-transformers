//! The derive functions of spec 0.16 on the device against the reference
//! engine. No pack of the repository runs them on a `bits` side, so this test
//! writes two synthetic `bits` packs over the keys of `model/probe.def`: one
//! that carries the arguments, one that carries the results. A cross-format
//! conversion derives every result the target reads. The inputs are seeded
//! random values and edge values; the device's output must equal the
//! reference engine's:
//!
//!   - byte for byte for every integer function and for `deg`, `rad`, `add`
//!     and `sub`, which take only IEEE operations;
//!   - for the WGS 84 and ECEF functions, within the comparison of the
//!     specification (1e-9 relative or 1e-7 absolute, Vector additions of
//!     0.16), and absent exactly where the reference engine leaves the target
//!     absent: their sines, cosines and arctangents are gt-core's own, which
//!     stay within 2.3e-16 relative of the platform library.
//!
//! The functions the device does not compute (`deg_lat_of`, `m_lat_of`,
//! `lat_of_ecef`, `hae_of_ecef`) must be refused by the compiler as
//! `unsupported-feature` when a conversion needs one.

use gt_core::Plan;
use gt_proof::*;
use std::path::Path;
use std::process::Command;

const HEAD: &str = "version       0.1.0\ndistribution  public\nsource        \"test\"\nuses          probe\nwire          bits\nword_bytes    1\nbit_order     msb\n";

/// A f64 pattern no finite value has: the sentinel of an absent float.
const ABSENT_F: u64 = u64::MAX;
/// The sentinel of an absent integer argument.
const ABSENT_I: u64 = 0x8000_0000_0000_0001;

/// (key, is an integer)
const ARGS: [(&str, bool); 18] = [
    ("t_ms", true),
    ("u_sec", true),
    ("u_nsec", true),
    ("ang_r", false),
    ("ang_d", false),
    ("i0", true),
    ("i1", true),
    ("f0", false),
    ("f1", false),
    ("dist", false),
    ("at_lat", false),
    ("arc", false),
    ("g_lat", false),
    ("g_lon", false),
    ("g_hae", false),
    ("e_x", false),
    ("e_y", false),
    ("e_z", false),
];

/// (key, is an integer, compared byte for byte)
const RESULTS: [(&str, bool, bool); 17] = [
    ("t_sec", true, true),
    ("t_nsec", true, true),
    ("u_ms", true, true),
    ("isum", true, true),
    ("idiff", true, true),
    ("ang_r_deg", false, true),
    ("ang_d_rad", false, true),
    ("fsum", false, true),
    ("fdiff", false, true),
    ("dist_dlon", false, false),
    ("arc_mlon", false, false),
    ("back_mlon", false, false),
    ("g_x", false, false),
    ("g_y", false, false),
    ("g_z", false, false),
    ("g_rlon", false, false),
    ("e_lon", false, false),
];

fn pack(name: &str, keys: &[(&str, bool)], sentinel_ints: bool) -> String {
    let mut t = format!("format        {}\n{}", name, HEAD);
    for (i, (k, int)) in keys.iter().enumerate() {
        let (xf, absent) = if *int { ("twos", if sentinel_ints { ABSENT_I } else { 0 }) } else { ("f64", ABSENT_F) };
        let opt = if absent != 0 { format!("  absent {}", absent) } else { String::new() };
        t.push_str(&format!("field  probe.{}  {}:0:64  {}{}\n", k, i * 8, xf, opt));
    }
    t
}

fn write(dir: &Path, name: &str, text: &str) {
    let d = dir.join(name);
    std::fs::create_dir_all(&d).unwrap();
    std::fs::write(d.join("pack.def"), text).unwrap();
}

fn packc(root: &Path, packs: &Path, from: &str, to: &str, out: &Path) -> Result<Vec<u8>, String> {
    let o = Command::new("python3")
        .arg("-I")
        .arg(root.join("tools/gen/packc.py"))
        .args(["--from", from, "--to", to, "--quiet", "--out-gtp"])
        .arg(out)
        .arg("--model")
        .arg(root.join("model"))
        .arg("--packs")
        .arg(packs)
        .output()
        .expect("python3 runs");
    if o.status.success() {
        Ok(std::fs::read(out).unwrap())
    } else {
        Err(String::from_utf8_lossy(&o.stderr).into_owned())
    }
}

fn int_value(rng: &mut Rng) -> u64 {
    const EDGE: [i64; 14] =
        [0, 1, -1, 999, 1000, -999, -1000, 999_999, 1_000_000, -1_000_001, i64::MAX, i64::MIN, i64::MAX / 1000, i64::MIN / 1000];
    match rng.below(8) {
        0 => ABSENT_I,
        1..=3 => EDGE[rng.below(EDGE.len())] as u64,
        4 => (rng.next() as i64 % 10_000_000_000) as u64,
        _ => rng.next(),
    }
}

fn float_value(rng: &mut Rng, key: &str) -> u64 {
    let r = |rng: &mut Rng| (rng.next() >> 11) as f64 / (1u64 << 53) as f64;
    let sym = |rng: &mut Rng, m: f64| (r(rng) * 2.0 - 1.0) * m;
    if rng.below(10) == 0 {
        return ABSENT_F;
    }
    let v = match (key, rng.below(6)) {
        (_, 0) => [0.0, -0.0, 90.0, -90.0, 180.0, -180.0, 1e-300, 6378137.0][rng.below(8)],
        ("at_lat" | "g_lat", _) => sym(rng, 100.0),
        ("g_lon", _) => sym(rng, 1e6),
        ("e_x" | "e_y" | "e_z", 1) => sym(rng, 1e-3),
        ("e_x" | "e_y" | "e_z", _) => sym(rng, 7e6),
        ("g_hae", _) => sym(rng, 2e4),
        ("ang_r" | "ang_d", _) => sym(rng, 1e4),
        (_, 2) => sym(rng, 1e300),
        _ => sym(rng, 1e7),
    };
    v.to_bits()
}

#[test]
fn derive_functions_of_016_match_the_reference() {
    let root = repo_root();
    let dir = std::env::var_os("CARGO_TARGET_DIR")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("../target"))
        .join(format!("gt-proof-d016-{}", std::process::id()));
    let packs = dir.join("packs");
    let _ = std::fs::remove_dir_all(&dir);
    write(&packs, "d16-args", &pack("d16-args", &ARGS, true));
    let results: Vec<(&str, bool)> = RESULTS.iter().map(|(k, i, _)| (*k, *i)).collect();
    write(&packs, "d16-results", &pack("d16-results", &results, false));
    // one target the device does not compute
    write(&packs, "d16-refused", &pack("d16-refused", &[("dist_dlat", false)], false));

    let plan_file = dir.join("plan.gtp");
    let refused = packc(&root, &packs, "d16-args", "d16-refused", &plan_file).expect_err("deg_lat_of is refused");
    assert!(refused.contains("refused: unsupported-feature:") && refused.contains("deg_lat_of"), "{}", refused);
    let blob = packc(&root, &packs, "d16-args", "d16-results", &plan_file).expect("plan");
    let plan = Plan::parse(&blob).expect("plan parses");

    let mut engine = goat_transformers::Engine::new();
    engine.load_model_dir(&root.join("model")).expect("model");
    engine.load_pack_dir(&packs).expect("the synthetic packs load in the reference engine");

    let mut scratch = Box::new(Scratch::new());
    let mut out = vec![0u8; 4096];
    let mut rng = Rng(0x0016_D0E5_1CE5_F00D);
    let (mut runs, mut equal, mut within, mut absent_both, mut errors) = (0usize, 0usize, 0usize, 0usize, 0usize);
    let mut differ = Vec::new();
    for _ in 0..20_000 {
        let mut msg = Vec::with_capacity(ARGS.len() * 8);
        for (k, int) in ARGS {
            let w = if int { int_value(&mut rng) } else { float_value(&mut rng, k) };
            msg.extend_from_slice(&w.to_be_bytes());
        }
        runs += 1;
        let want = engine.convert("d16-args", "d16-results", &hex(&msg));
        let got = gt_core::convert(&plan, &msg, &mut out, &mut scratch, &[]);
        let (want, n) = match (want, got) {
            (Ok(w), Ok(n)) => (unhex(&w).expect("reference hex"), n),
            (Err(e), Err(d)) if kind_of(&e) == d.name() => {
                errors += 1;
                continue;
            }
            (w, g) => {
                differ.push(format!("input {}: reference {:?}, device {:?}", hex(&msg), w.map_err(|e| e.msg), g));
                continue;
            }
        };
        let got = &out[..n];
        if got.len() != want.len() {
            differ.push(format!("input {}: {} bytes, reference {}", hex(&msg), got.len(), want.len()));
            continue;
        }
        for (i, (k, _, exact)) in RESULTS.iter().enumerate() {
            let g = u64::from_be_bytes(got[i * 8..i * 8 + 8].try_into().unwrap());
            let w = u64::from_be_bytes(want[i * 8..i * 8 + 8].try_into().unwrap());
            if g == w {
                if !exact && w == ABSENT_F {
                    absent_both += 1;
                } else {
                    equal += 1;
                }
                continue;
            }
            let (gf, wf) = (f64::from_bits(g), f64::from_bits(w));
            let close = !exact
                && g != ABSENT_F
                && w != ABSENT_F
                && ((gf - wf).abs() <= 1e-9 * wf.abs() || (gf - wf).abs() < 1e-7);
            if close {
                within += 1;
            } else {
                differ.push(format!("input {}: `{}` device {:?}, reference {:?}", hex(&msg), k, gf, wf));
            }
        }
    }
    let _ = std::fs::remove_dir_all(&dir);
    eprintln!(
        "derives 0.16: {} inputs through `d16-args` -> `d16-results`: {} results equal to the bit, {} within the comparison of 0.16, {} absent on both, {} inputs refused with the reference's error kind, {} differ",
        runs,
        equal,
        within,
        absent_both,
        errors,
        differ.len()
    );
    for d in differ.iter().take(20) {
        eprintln!("DIFFER {}", d);
    }
    assert!(differ.is_empty(), "the device and the reference engine differ on the derive functions of 0.16");
    assert!(equal > 0 && absent_both > 0);
}
