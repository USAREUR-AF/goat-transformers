//! Engine-spec 0.92, a run of inner messages: `decode_run`, which no vector
//! calls, and that the time of a run grows with its length, not its square.
#![cfg(feature = "bits")]

use goat_transformers::{Engine, Value};
use std::path::Path;
use std::time::{Duration, Instant};

const HEAD: &str = "version 0.92.0\ndistribution public\nsource \"synthetic\"\nuses probe\nwire bits\nlayout sequential\nbit_order msb\n";

fn engine(packs: &[(&str, &str)]) -> Engine {
    let mut e = Engine::new();
    e.load_model_dir(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../model")).unwrap();
    for (name, lines) in packs {
        e.load_def(&format!("format {}\n{}{}\n", name, HEAD, lines)).unwrap();
    }
    e
}

fn xy() -> Engine {
    engine(&[
        ("in", "framing self\nfield probe.x 8 uint\nfield probe.y 8 uint"),
        ("out", "field probe.w 8 uint\ninner in run"),
        ("other", "field probe.n 8 uint\ninner in run"),
        ("kinds", "kind a\nwhen 8 1\ninner in run\nkind b\nwhen 8 2\nfield probe.w 8 uint"),
    ])
}

/// The outer entity alone, and one joined entity or error per message.
#[test]
fn decode_run_of_a_carrier() {
    let (outer, messages) = xy().decode_run("out", "090102030405").unwrap();
    assert_eq!(outer.fields.keys().collect::<Vec<_>>(), ["probe.w"]);
    assert_eq!(messages.len(), 3);
    let second = messages[1].as_ref().unwrap();
    for (k, n) in [("probe.w", 9), ("probe.x", 3), ("probe.y", 4)] {
        assert_eq!(second.fields.get(k), Some(&Value::I64(n)));
    }
    let last = messages[2].as_ref().unwrap_err();
    assert!(last.msg.starts_with("malformed-wire:"), "{}", last.msg);
}

/// Ruling 4: an ordinary message gives one entity, or its error as the one
/// result; a decode that stops before it is known to be one fails the call.
#[test]
fn decode_run_of_an_ordinary_message() {
    let e = xy();
    let (_, messages) = e.decode_run("kinds", "0207").unwrap();
    assert_eq!(messages.len(), 1);
    assert_eq!(messages[0].as_ref().unwrap().fields.get("probe.w"), Some(&Value::I64(7)));
    let (_, messages) = e.decode_run("kinds", "02").unwrap();
    assert_eq!(messages.len(), 1);
    assert!(messages[0].as_ref().unwrap_err().msg.starts_with("malformed-wire:"));
    assert!(e.decode_run("kinds", "05").unwrap_err().msg.starts_with("no-kind:"));
}

/// Ten times the messages take about ten times as long; a step that copies or
/// scans the rest of the run for each message would take a hundred times.
#[test]
fn a_run_is_read_and_written_in_linear_time() {
    let e = xy();
    let time = |n: usize| {
        let input = format!("09{}", "0102".repeat(n));
        let once = || {
            let started = Instant::now();
            assert_eq!(e.decode_run("out", &input).unwrap().1.len(), n);
            assert_eq!(e.convert_run("out", "other", &input, None).unwrap().len(), 1);
            started.elapsed()
        };
        (0..3).map(|_| once()).min().unwrap_or(Duration::ZERO)
    };
    let (short, long) = (time(2_000), time(20_000));
    let floor = Duration::from_millis(1);
    assert!(long < short.max(floor) * 40, "2000 messages took {:?}, 20000 took {:?}", short, long);
}
