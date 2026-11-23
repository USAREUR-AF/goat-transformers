//! End to end: real packs, real sockets and files, the conformance vectors'
//! inputs as data, and the engine's own answer as the expectation.

use goat_adapters_core::engine::json::{self, Json};
use goat_adapters_core::engine::bits;
use goat_adapters_core::frame::Framing;
use goat_adapters_core::pipeline::{error_kind, Formats, OnError, Outcome, Output, Pipeline};
use goat_adapters_std::io::{TcpListenSink, UdpSource};
use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpStream, UdpSocket};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

const PACKS: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../packs");
const MODEL: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../model");
const PIPE: &str = env!("CARGO_BIN_EXE_goat-xf-pipe");

fn formats(only: &[&str]) -> Formats {
    let only: Vec<String> = only.iter().map(|s| s.to_string()).collect();
    Formats::load(Path::new(MODEL), Path::new(PACKS), Some(&only), None).unwrap()
}

/// The inputs of a pack's conversion vectors that convert from the pack's
/// own format and carry no context of their own, in file order; optionally
/// only those to one target.
fn vector_inputs(pack: &str, to: Option<&str>) -> Vec<String> {
    let dir = Path::new(PACKS).join(pack).join("vectors");
    let mut files: Vec<PathBuf> = std::fs::read_dir(dir).unwrap().flatten().map(|e| e.path()).collect();
    files.sort();
    let mut out = Vec::new();
    for f in files {
        let v = json::parse(&std::fs::read_to_string(&f).unwrap()).unwrap();
        let s = |k: &str| match v.get(k) {
            Some(Json::Str(s)) => Some(s.clone()),
            _ => None,
        };
        if s("from").as_deref() == Some(pack) && v.get("context").is_none() && to.map_or(true, |t| s("to").as_deref() == Some(t)) {
            if let Some(input) = s("input") {
                if !out.contains(&input) {
                    out.push(input);
                }
            }
        }
    }
    assert!(out.len() >= 3, "{} has too few vectors to test with", pack);
    out
}

fn temp_dir(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("goat-adapters-e2e-{}-{}", tag, std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// What the engine itself says each input converts to: the lines that
/// should come out, and the failures by error name.
fn expected(f: &Formats, from: &str, to: &str, inputs: &[String], context: &[(String, String)]) -> (Vec<String>, BTreeMap<String, u64>) {
    let (mut ok, mut failed) = (Vec::new(), BTreeMap::new());
    let context = if context.is_empty() { None } else { Some(context) };
    for i in inputs {
        match f.engine().convert_text(from, to, i.trim(), context) {
            Ok(s) => ok.push(s),
            Err(e) => *failed.entry(error_kind(&e.msg).to_string()).or_insert(0) += 1,
        }
    }
    (ok, failed)
}

#[test]
fn cot_xml_events_over_udp_come_out_as_geojson_lines_on_a_tcp_listener() {
    let f = formats(&["cot-xml", "geojson"]);
    let mut inputs = vector_inputs("cot-xml", Some("geojson"));
    inputs.insert(1, "<event this is not XML".to_string());
    let (want, want_failed) = expected(&f, "cot-xml", "geojson", &inputs, &[]);
    assert!(want.len() >= 2 && !want_failed.is_empty(), "the vectors should give both conversions and failures");
    // the first vector's expectation, pinned, so this test does not only compare the engine with itself
    assert_eq!(
        want[0],
        r#"{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}"#
    );

    let source = UdpSource::bind("127.0.0.1", 0, None, &Framing::whole()).unwrap();
    let udp_to = source.local_addr().unwrap();
    let sink = TcpListenSink::bind("127.0.0.1", 0, &Framing::parse("newline").unwrap()).unwrap();
    let tcp_at = sink.local_addr().unwrap();
    let mut p = Pipeline::new(&f, "cot-xml", Box::new(source), vec![Output { to: "geojson".into(), hex: false, sink: Box::new(sink) }]);
    p.on_error = OnError::Skip;
    p.name = "e2e".into();
    p.check().unwrap();

    let stop = AtomicBool::new(false);
    let client = TcpStream::connect(tcp_at).unwrap();
    client.set_read_timeout(Some(Duration::from_secs(20))).unwrap();
    let (outcome, got) = std::thread::scope(|s| {
        let run = s.spawn(|| p.run(&stop));
        let tx = UdpSocket::bind("127.0.0.1:0").unwrap();
        for i in &inputs {
            tx.send_to(i.as_bytes(), udp_to).unwrap();
            std::thread::sleep(Duration::from_millis(2)); // loopback keeps order; do not outrun the socket buffer
        }
        let mut got = Vec::new();
        let mut lines = BufReader::new(&client).lines();
        while got.len() < want.len() {
            got.push(lines.next().expect("the listener closed early").expect("no line within the timeout"));
        }
        stop.store(true, Ordering::Relaxed);
        (run.join().unwrap(), got)
    });
    assert_eq!(outcome, Outcome::Interrupted);
    assert_eq!(got, want);
    assert_eq!(p.stats.received.load(Ordering::Relaxed), inputs.len() as u64);
    assert_eq!(p.stats.converted.load(Ordering::Relaxed), want.len() as u64);
    // every message that did not convert is counted under the engine's error name
    assert_eq!(p.stats.failed(), want_failed);
}

#[test]
fn pipeline_refuses_wrong_settings_before_the_first_message() {
    let f = formats(&["cot-xml", "geojson", "remote-id"]);
    let make = |from: &str, to: &str| {
        let source = UdpSource::bind("127.0.0.1", 0, None, &Framing::whole()).unwrap();
        let sink = TcpListenSink::bind("127.0.0.1", 0, &Framing::whole()).unwrap();
        Pipeline::new(&f, from, Box::new(source), vec![Output { to: to.into(), hex: false, sink: Box::new(sink) }])
    };
    assert!(make("cot-xml", "geojson").check().is_ok());
    assert!(make("nmea-0183", "geojson").check().unwrap_err().contains("no pack loaded"));
    assert!(make("cot-xml", "kml").check().unwrap_err().contains("no pack loaded"));
    let mut p = make("cot-xml", "geojson");
    p.in_hex = true;
    assert!(p.check().unwrap_err().contains("`hex` is for a binary format"));
    let mut p = make("cot-xml", "geojson");
    p.context = vec![("no.such_key".into(), "1".into())];
    assert!(p.check().unwrap_err().starts_with("undeclared-key"));
    let mut p = make("cot-xml", "geojson");
    p.receive_time_key = Some("callsign".into());
    assert!(p.check().unwrap_err().starts_with("key-type-mismatch"));
    let mut p = make("remote-id", "geojson");
    p.in_hex = true;
    p.receive_time_key = Some("time_ms".into());
    assert!(p.check().is_ok());
}

struct Ran {
    status: i32,
    stdout: Vec<u8>,
    stderr: String,
}
fn pipe(args: &[&str], stdin: &[u8]) -> Ran {
    let mut c = Command::new(PIPE)
        .args(["--packs", PACKS, "--packs-only", "--status-every", "0"])
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    c.stdin.take().unwrap().write_all(stdin).unwrap();
    let o = c.wait_with_output().unwrap();
    Ran { status: o.status.code().unwrap(), stdout: o.stdout, stderr: String::from_utf8_lossy(&o.stderr).into_owned() }
}
fn lines(b: &[u8]) -> Vec<String> {
    String::from_utf8(b.to_vec()).unwrap().lines().map(|l| l.to_string()).collect()
}
fn failed_part(kinds: &BTreeMap<String, u64>) -> String {
    let total: u64 = kinds.values().sum();
    let list: Vec<String> = kinds.iter().map(|(k, n)| format!("{}={}", k, n)).collect();
    if total == 0 {
        "failed=0".to_string()
    } else {
        format!("failed={} [{}]", total, list.join(" "))
    }
}

#[test]
fn a_file_of_length_prefixed_asterix_blocks_becomes_canonical_track_lines_and_geojson_files() {
    let f = formats(&["asterix-cat062", "canonical-track-v2", "geojson"]);
    let inputs = vector_inputs("asterix-cat062", None);
    let context: Vec<(String, String)> =
        [("uid", "311"), ("track.source_id", "sensor-a"), ("track.generation", "generation-1"), ("time_ms", "1761739200123")]
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
    let (want_tracks, failed_tracks) = expected(&f, "asterix-cat062", "canonical-track-v2", &inputs, &context);
    let (want_geo, failed_geo) = expected(&f, "asterix-cat062", "geojson", &inputs, &context);
    assert!(want_tracks.len() >= 3);
    // vector 12 of the pack, pinned
    assert_eq!(
        want_tracks[0],
        r#"{"apiVersion":"billie.dev/track-v2","kind":"Track","trackId":"311","sourceId":"sensor-a","trackGeneration":"generation-1","simulated":false,"confirmed":true,"coasting":false,"finalUpdate":false,"observedAt":"2025-10-29T12:00:00.123Z","position":{"latitudeDeg":0,"longitudeDeg":0,"altitudeM":152.4},"velocity":{"eastMps":-12.5,"northMps":4.25}}"#
    );

    let d = temp_dir("asterix");
    let mut wire = Vec::new();
    for hex in &inputs {
        let b = bits::from_hex(hex).unwrap();
        wire.extend_from_slice(&(b.len() as u16).to_be_bytes());
        wire.extend_from_slice(&b);
    }
    let input = d.join("blocks.bin");
    std::fs::write(&input, &wire).unwrap();
    let tracks = d.join("tracks.jsonl");
    let geo = d.join("geo");
    let r = pipe(
        &[
            "--from-format", "asterix-cat062", "--in", &format!("file:{}", input.display()), "--in-frame", "len:2:be",
            "--set", "uid=311", "--set", "track.source_id=sensor-a", "--set", "track.generation=generation-1", "--set", "time_ms=1761739200123",
            "--out", &format!("file:{}", tracks.display()), "--to-format", "canonical-track-v2", "--out-frame", "newline",
            "--out", &format!("dir:{}?ext=geojson&prefix=trk-", geo.display()), "--to-format", "geojson",
        ],
        b"",
    );
    assert_eq!(lines(&std::fs::read(&tracks).unwrap()), want_tracks, "{}", r.stderr);
    let mut files: Vec<PathBuf> = std::fs::read_dir(&geo).unwrap().flatten().map(|e| e.path()).collect();
    files.sort();
    let got_geo: Vec<String> = files.iter().map(|p| std::fs::read_to_string(p).unwrap()).collect();
    assert_eq!(got_geo, want_geo);
    assert!(files[0].ends_with("trk-000001.geojson"), "{:?}", files[0]);

    let mut failed = failed_tracks.clone();
    for (k, n) in &failed_geo {
        *failed.entry(k.clone()).or_insert(0) += n;
    }
    let summary = format!("in={} converted={} {}", inputs.len(), want_tracks.len() + want_geo.len(), failed_part(&failed));
    assert!(r.stderr.contains(&summary), "want `{}` in:\n{}", summary, r.stderr);
    assert_eq!(r.status, if failed.is_empty() { 0 } else { 3 }, "{}", r.stderr);
    std::fs::remove_dir_all(d).unwrap();
}

#[test]
fn remote_id_messages_of_fixed_size_on_stdin_become_geojson_lines_and_hex_text_is_the_same_data() {
    let f = formats(&["remote-id", "geojson"]);
    // a Remote ID message is 25 bytes; the vectors also hold inputs of other sizes, which `fixed:25` cannot carry
    let inputs: Vec<String> = vector_inputs("remote-id", None).into_iter().filter(|h| h.len() == 50).collect();
    assert!(inputs.len() >= 3);
    let (want, failed) = expected(&f, "remote-id", "geojson", &inputs, &[]);
    let raw: Vec<u8> = inputs.iter().flat_map(|h| bits::from_hex(h).unwrap()).collect();
    let common = ["--from-format", "remote-id", "--in", "stdin:", "--out", "stdout:", "--to-format", "geojson", "--out-frame", "newline"];

    let r = pipe(&[&common[..], &["--in-frame", "fixed:25"]].concat(), &raw);
    assert_eq!(lines(&r.stdout), want, "{}", r.stderr);
    assert!(r.stderr.contains(&format!("in={} converted={} {}", inputs.len(), want.len(), failed_part(&failed))), "{}", r.stderr);
    assert_eq!(r.status, if failed.is_empty() { 0 } else { 3 });

    // the same messages as hexadecimal text, one per line
    let text = inputs.join("\n") + "\n";
    let r = pipe(&[&common[..], &["--in-frame", "newline,hex"]].concat(), text.as_bytes());
    assert_eq!(lines(&r.stdout), want, "{}", r.stderr);

    // and back out as binary: remote-id to remote-id through a length prefix is the input again
    let r = pipe(
        &["--from-format", "remote-id", "--in", "stdin:", "--in-frame", "fixed:25", "--out", "stdout:", "--to-format", "remote-id", "--out-frame", "len:1"],
        &raw[..50],
    );
    assert_eq!(r.stdout, [&[25u8][..], &raw[..25], &[25u8][..], &raw[25..50]].concat(), "{}", r.stderr);
    assert_eq!(r.status, 0, "{}", r.stderr);
}

const GOOD: &str = r#"<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>"#;

#[test]
fn a_message_that_does_not_convert_is_reported_and_never_passed_through() {
    let text = format!("{}\n<event uid=\"broken\"\n{}\n", GOOD, GOOD);
    let common = ["--from-format", "cot-xml", "--in", "stdin:", "--in-frame", "newline", "--out", "stdout:", "--to-format", "geojson", "--out-frame", "newline"];

    let r = pipe(&common, text.as_bytes());
    let out = lines(&r.stdout);
    assert_eq!(out.len(), 2, "{}", r.stderr);
    assert!(out.iter().all(|l| l.starts_with(r#"{"type":"Feature""#)));
    assert!(!String::from_utf8_lossy(&r.stdout).contains("broken"));
    assert_eq!(r.status, 3);
    assert!(r.stderr.contains("FAILED message 2 -> geojson: "), "{}", r.stderr);
    assert!(r.stderr.contains("done, WITH FAILURES: in=3 converted=2 failed=1 ["), "{}", r.stderr);

    let r = pipe(&[&common[..], &["--on-error", "stop"]].concat(), text.as_bytes());
    assert_eq!(lines(&r.stdout).len(), 1, "{}", r.stderr);
    assert_eq!(r.status, 1);
    assert!(r.stderr.contains("STOPPED on failure"), "{}", r.stderr);
    assert!(r.stderr.contains("in=2 converted=1 failed=1 ["), "{}", r.stderr);
}

#[test]
fn a_directory_of_xml_documents_becomes_a_directory_named_after_them_from_a_configuration_file() {
    let d = temp_dir("dirs");
    let (inbox, outbox) = (d.join("in"), d.join("out"));
    std::fs::create_dir_all(&inbox).unwrap();
    std::fs::write(inbox.join("alpha.xml"), format!("<?xml version=\"1.0\"?>\n{}\n", GOOD)).unwrap();
    std::fs::write(inbox.join("bravo.xml"), GOOD).unwrap();
    let conf = d.join("pipe.conf");
    std::fs::write(
        &conf,
        format!(
            "# one XML document per file in, one GeoJSON file out\nfrom-format cot-xml\nin \"dir:{}\"\nout \"dir:{}?name=origin&ext=geojson\"\n  to-format geojson\non-error stop\n",
            inbox.display(),
            outbox.display()
        ),
    )
    .unwrap();
    let r = pipe(&["--config", conf.to_str().unwrap()], b"");
    assert_eq!(r.status, 0, "{}", r.stderr);
    let a = std::fs::read_to_string(outbox.join("alpha.geojson")).unwrap();
    assert_eq!(a, std::fs::read_to_string(outbox.join("bravo.geojson")).unwrap());
    assert!(a.ends_with(r#""id":"J-01334"}"#), "{}", a);
    std::fs::remove_dir_all(d).unwrap();
}

#[test]
fn a_wrong_command_line_exits_2_and_says_why() {
    for (args, why) in [
        (vec!["--from-format", "cot-xml", "--in", "stdin:", "--out", "stdout:", "--to-format", "geojson"], "state how one message is delimited"),
        (vec!["--from-format", "cot-xml", "--in", "stdin:", "--in-frame", "lines", "--out", "stdout:", "--to-format", "geojson"], "bad-frame"),
        (vec!["--from-format", "cot-xml", "--in", "udp://127.0.0.1:0", "--out", "stdout:", "--out-frame", "newline"], "has no --to-format"),
        (vec!["--from-format", "cot-xml", "--in", "udp://127.0.0.1:0", "--out", "stdout:", "--out-frame", "newline,hex", "--to-format", "geojson"], "`hex` is for a binary format"),
        (vec!["--from-format", "cot-xml", "--in", "udp://127.0.0.1:0", "--out", "stdout:", "--out-frame", "newline", "--to-format", "geojson", "--set", "nope=1"], "undeclared-key"),
        (vec!["--from-format", "cot-xml", "--in", "smoke://signal", "--out", "stdout:", "--out-frame", "newline", "--to-format", "geojson"], "no input adapter"),
        (vec!["--from-format", "klingon", "--in", "udp://127.0.0.1:0", "--out", "stdout:", "--out-frame", "newline", "--to-format", "geojson"], "no pack for format `klingon`"),
    ] {
        let r = pipe(&args, b"");
        assert_eq!(r.status, 2, "{:?}: {}", args, r.stderr);
        assert!(r.stderr.contains(why), "{:?}: want `{}` in: {}", args, why, r.stderr);
        assert!(r.stdout.is_empty());
    }
}

#[test]
fn bytes_that_are_not_text_for_a_text_format_are_counted_as_not_utf8() {
    let mut input = GOOD.as_bytes().to_vec();
    input.extend_from_slice(b"\n\xff\xfe<event/>\n");
    let r = pipe(
        &["--from-format", "cot-xml", "--in", "stdin:", "--in-frame", "newline", "--out", "stdout:", "--to-format", "geojson", "--out-frame", "newline"],
        &input,
    );
    assert_eq!(lines(&r.stdout).len(), 1, "{}", r.stderr);
    assert!(r.stderr.contains("FAILED message 2: not-utf8: "), "{}", r.stderr);
    assert!(r.stderr.contains("in=2 converted=1 failed=1 [not-utf8=1]"), "{}", r.stderr);
    assert_eq!(r.status, 3);
}

/// One MAVLink 2 GLOBAL_POSITION_INT frame (message 33) from system 7, payload
/// trimmed of trailing zero bytes as a MAVLink 2 sender does. The checksum is
/// not mapped, so two placeholder bytes stand in for it.
fn gpi_frame(hdg_cdeg: u16) -> Vec<u8> {
    let mut p = Vec::new();
    p.extend(5000u32.to_le_bytes()); // time_boot_ms
    p.extend(473977420i32.to_le_bytes()); // lat 47.397742
    p.extend(85455940i32.to_le_bytes()); // lon 8.545594
    p.extend(120000i32.to_le_bytes()); // alt mm
    p.extend(50000i32.to_le_bytes()); // relative_alt mm
    p.extend(4515i16.to_le_bytes()); // vx cm/s, north
    p.extend((-873i16).to_le_bytes()); // vy cm/s, east
    p.extend(0i16.to_le_bytes()); // vz
    p.extend(hdg_cdeg.to_le_bytes());
    while p.last() == Some(&0) {
        p.pop();
    }
    let mut f = vec![0xFD, p.len() as u8, 0, 0, 1, 7, 1, 33, 0, 0];
    f.extend(&p);
    f.extend([0x12, 0x34]);
    f
}

#[test]
fn a_mavlink2_frame_trimmed_of_trailing_zeros_decodes_with_mavlink2_framing() {
    let full = gpi_frame(36000); // heading 360.00 deg: no trailing zero byte, 28 bytes
    let trimmed = gpi_frame(100); // heading 1.00 deg: the high byte is zero, so 27 bytes
    assert_eq!((full[1], trimmed[1]), (28, 27));
    let common = ["--from-format", "mavlink2", "--in", "stdin:", "--in-frame", "mavlink2", "--out", "stdout:", "--to-format", "geojson", "--out-frame", "newline"];

    let r = pipe(&common, &[full.clone(), trimmed.clone()].concat());
    assert_eq!(r.status, 0, "{}", r.stderr);
    let got = lines(&r.stdout);
    assert_eq!(got.len(), 2, "{}", r.stderr);
    for l in &got {
        assert!(l.contains("8.545594") && l.contains("47.397742"), "{}", l);
    }

    // without the framing the trimmed frame is refused: the pack is written for the full length
    let r = pipe(&["--from-format", "mavlink2", "--in", "stdin:", "--in-frame", "whole", "--out", "stdout:", "--to-format", "geojson", "--out-frame", "newline"], &trimmed);
    assert!(r.stderr.contains("no-kind"), "{}", r.stderr);

    // the framing needs a mavlink2 pack to know the full lengths
    let r = pipe(&["--from-format", "geojson", "--in", "stdin:", "--in-frame", "mavlink2", "--out", "stdout:", "--to-format", "geojson"], b"");
    assert_eq!(r.status, 2, "{}", r.stderr);
}
