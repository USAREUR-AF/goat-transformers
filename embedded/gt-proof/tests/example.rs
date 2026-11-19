//! The plan and wrapper of `embedded/example-bare`, run on the host: Remote
//! ID Location messages to ASTERIX CAT062, against the reference engine's
//! conversion with the same context.

use example_bare::{convert, GtCat062Context};
use gt_proof::*;

#[test]
fn example_gives_the_reference_bytes() {
    let p = Proof::new();
    let ctx = GtCat062Context { time_of_day_s: 43200.5, track_number: 311, sac: 1, sic: 7, confirmed: 1 };
    let text: Vec<(String, String)> = [
        ("cat062.sac", "1"),
        ("cat062.sic", "7"),
        ("cat062.time_of_day_s", "43200.5"),
        ("cat062.track_number", "311"),
        ("track.confirmed", "1"),
    ]
    .iter()
    .map(|(k, v)| (k.to_string(), v.to_string()))
    .collect();
    let mut ran = 0;
    for v in p.vectors().iter().filter(|v| v.from == "remote-id") {
        let input = match unhex(&v.input) {
            Some(b) => b,
            None => continue,
        };
        let mut out = [0u8; 32];
        let got = convert(&input, &mut out, &ctx);
        let want = p.engine.convert_text("remote-id", "asterix-cat062", &v.input, Some(&text));
        match (want, got) {
            (Ok(w), Ok(n)) => {
                assert_eq!(hex(&out[..n]), w, "{}", v.name);
                eprintln!("{}: {} -> {}", v.name, v.input, w);
                ran += 1;
            }
            // a message of another kind than `location`: the plan holds only that kind
            (_, Err(gt_core::Error::NoKind)) => {}
            (Err(e), Err(d)) => assert_eq!(kind_of(&e), d.name(), "{}", v.name),
            (w, g) => panic!("{}: reference {:?}, example {:?}", v.name, w.map_err(|e| e.msg), g),
        }
    }
    assert!(ran > 0, "no Location vector was converted");
}
