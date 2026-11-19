//! Malformed input never panics. The engine parses messages from untrusted
//! senders, so for every loaded pack this test feeds `convert`:
//!
//! (a) random bytes and random text of random length, in the alphabets of
//!     the wires (hex digits, XML and JSON punctuation, the delimiters,
//!     start texts and checksums of text records);
//! (b) the input of every conversion vector cut at prefix lengths: every
//!     length when the input is short, an even spread of lengths when it is
//!     long;
//! (c) the input of every conversion vector with one byte replaced;
//! (d) fixed hostile shapes: nesting far beyond the depth limit, lengths and
//!     counts far beyond the input, tags cut at every point;
//! (e) random tag-length-value sets (engine-spec 0.13), bare and framed by a
//!     key, a length and a sum16 checksum item, so that a mutation reaches
//!     the items behind the checksum; and every hex vector input mutated
//!     and then given a correct sum16 in its last two bytes.
//!
//! Each call must return `Ok`, or an error whose message starts with one of
//! the error kinds `convert` may fail with, then a colon. A panic is caught,
//! and every failure is reported with its pack and its input before the test
//! fails.
//!
//! The inputs come from a xorshift generator with a fixed seed, so a run is
//! reproducible. `GOAT_FUZZ_ITERS=<n>` multiplies the number of random and
//! mutated inputs (default 1); `GOAT_FUZZ_SEED=<n>` changes the seed.

use goat_transformers::json::Json;
use goat_transformers::{json, Engine};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::{Path, PathBuf};

/// The error kinds `convert` with no context may fail with
/// (spec/vector-format.md, `expect_error`).
const KINDS: [&str; 5] = ["malformed-wire", "no-kind", "missing-root", "transform-decode", "transform-encode"];

/// Random inputs per pack and per alphabet, at `GOAT_FUZZ_ITERS=1`.
const RANDOM_PER_ALPHABET: usize = 32;
/// Prefix lengths tried per vector: every length up to this many, else an even spread.
const PREFIXES_PER_VECTOR: usize = 24;
/// One-byte mutations per vector, at `GOAT_FUZZ_ITERS=1`.
const MUTATIONS_PER_VECTOR: usize = 16;
/// A vector whose input is longer than this gets fewer prefixes and
/// mutations, in proportion, and never fewer than `LARGE_INPUT_FLOOR`: the
/// bytes read per vector stay near the count times this length.
const LARGE_INPUT: usize = 2048;
const LARGE_INPUT_FLOOR: usize = 2;

/// `count`, scaled down for an input of `len` bytes.
fn capped(count: usize, len: usize) -> usize {
    if len <= LARGE_INPUT {
        count
    } else {
        (count * LARGE_INPUT / len).max(LARGE_INPUT_FLOOR)
    }
}

fn repo_packs_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../packs").canonicalize().expect("packs dir")
}

/// xorshift64*: deterministic, std only.
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n.max(1) as u64) as usize
    }
    fn pick(&mut self, from: &[u8]) -> u8 {
        from[self.below(from.len())]
    }
}

const HEX: &[u8] = b"0123456789abcdef";
const XMLISH: &[u8] = b"<<<>>>//==\"\"'' \n?!-&;abeEvent:._019[]";
const JSONISH: &[u8] = b"{{}}[[]]\"\"::,,\\ \n-+.eE0123456789truefalsn/ua";
const TEXTISH: &[u8] = b"$$,,,;;;**  \r\n-+..0123456789ABCDEFabcdefNSEWPXTIMGC";

/// A text record framed with a start text and an NMEA checksum over `body`.
fn nmea(start: &str, body: &str) -> String {
    format!("{}{}*{:02X}", start, body, body.bytes().fold(0u8, |a, c| a ^ c))
}

/// sum16 of engine-spec 0.13: a byte at an even offset counts `b * 256`, at
/// an odd offset `b`, modulo 65536.
fn sum16(b: &[u8]) -> u16 {
    b.iter().enumerate().fold(0u16, |a, (i, c)| a.wrapping_add(if i % 2 == 0 { (*c as u16) << 8 } else { *c as u16 }))
}

fn to_hex(b: &[u8]) -> String {
    b.iter().map(|c| format!("{:02x}", c)).collect()
}

/// A BER length: the short form below 128, else the long form.
fn ber_len(n: usize, out: &mut Vec<u8>) {
    if n < 0x80 {
        out.push(n as u8);
    } else {
        let b = (n as u64).to_be_bytes();
        let skip = b.iter().take_while(|c| **c == 0).count();
        out.push(0x80 + (8 - skip) as u8);
        out.extend_from_slice(&b[skip..]);
    }
}

/// A BER-OID tag.
fn ber_tag(t: u32, out: &mut Vec<u8>) {
    let mut g = vec![(t & 0x7f) as u8];
    let mut t = t >> 7;
    while t > 0 {
        g.push((t & 0x7f) as u8 | 0x80);
        t >>= 7;
    }
    out.extend(g.iter().rev());
}

/// A random set of items with BER-OID tags and BER lengths, values nested
/// as sets up to `depth` levels; now and then a length or a tag broken.
fn tlv_set(rng: &mut Rng, depth: usize, out: &mut Vec<u8>) {
    const TAGS: [u32; 16] = [1, 2, 3, 4, 7, 9, 10, 13, 14, 15, 16, 20, 21, 48, 65, 200];
    for _ in 0..rng.below(12) {
        ber_tag(if rng.below(16) == 0 { rng.next() as u32 & 0x0fff_ffff } else { TAGS[rng.below(TAGS.len())] }, out);
        let mut value = Vec::new();
        if depth > 0 && rng.below(4) == 0 {
            tlv_set(rng, depth - 1, &mut value);
        } else {
            let n = [0usize, 1, 2, 4, 8, 9, 130][rng.below(7)];
            value.extend((0..n).map(|_| rng.next() as u8));
        }
        match rng.below(24) {
            0 => out.extend_from_slice(&[0x88, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]),
            1 => out.push(0x80),
            2 => out.extend_from_slice(&[0x84, 0, 0, 0, value.len() as u8]),
            _ => ber_len(value.len(), out),
        }
        out.extend_from_slice(&value);
    }
}

/// `set` after a key and its length, with a sum16 item of tag `tag` last.
fn tlv_framed(key: &[u8], tag: u32, set: &[u8]) -> String {
    let mut body = set.to_vec();
    ber_tag(tag, &mut body);
    body.extend_from_slice(&[2, 0, 0]);
    let mut out = key.to_vec();
    ber_len(body.len(), &mut out);
    out.extend_from_slice(&body);
    let n = out.len();
    let s = sum16(&out[..n - 2]);
    out[n - 2..].copy_from_slice(&s.to_be_bytes());
    to_hex(&out)
}

/// What one call did wrong, if anything.
fn check(engine: &Engine, from: &str, to: &str, input: &str) -> Option<String> {
    match catch_unwind(AssertUnwindSafe(|| engine.convert(from, to, input))) {
        Err(panic) => {
            let what = panic
                .downcast_ref::<String>()
                .cloned()
                .or_else(|| panic.downcast_ref::<&str>().map(|s| s.to_string()))
                .unwrap_or_else(|| "a panic with no message".to_string());
            Some(format!("PANIC: {}", what))
        }
        Ok(Ok(_)) => None,
        Ok(Err(e)) => match e.msg.split_once(':') {
            Some((kind, _)) if KINDS.contains(&kind) => None,
            _ => Some(format!("error with no named kind: {}", e.msg)),
        },
    }
}

/// A vector's `from`, `to` and `input`.
struct Case {
    from: String,
    to: String,
    input: String,
}

fn conversion_vectors(engine: &Engine) -> Vec<Case> {
    let formats = engine.formats();
    let mut dirs: Vec<_> = std::fs::read_dir(repo_packs_dir()).unwrap().flatten().map(|e| e.path()).collect();
    dirs.sort();
    let mut out = Vec::new();
    for dir in dirs {
        let vdir = dir.join("vectors");
        if !vdir.exists() {
            continue;
        }
        let mut files: Vec<_> = std::fs::read_dir(&vdir).unwrap().flatten().map(|e| e.path()).collect();
        files.sort();
        for vf in files {
            if vf.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            let v = match json::parse(&std::fs::read_to_string(&vf).unwrap()) {
                Ok(v) => v,
                Err(_) => continue, // the vector test reports it
            };
            let text = |k: &str| match v.get(k) {
                Some(Json::Str(s)) => Some(s.clone()),
                _ => None,
            };
            if let (Some(from), Some(to), Some(input)) = (text("from"), text("to"), text("input")) {
                if formats.contains(&from) && formats.contains(&to) {
                    out.push(Case { from, to, input });
                }
            }
        }
    }
    out
}

/// The largest index `<= at` that is a character boundary of `s`.
fn boundary(s: &str, mut at: usize) -> usize {
    at = at.min(s.len());
    while !s.is_char_boundary(at) {
        at -= 1;
    }
    at
}

/// The hostile shapes of (d).
fn hostile() -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    // nesting far beyond the depth limit: the recursion must stop at the limit
    for n in [63usize, 64, 65, 66, 1_000, 100_000] {
        out.push("[".repeat(n));
        out.push(format!("{}{}", "[".repeat(n), "]".repeat(n)));
        out.push("{\"a\":".repeat(n));
        out.push(format!("{}1{}", "{\"a\":".repeat(n), "}".repeat(n)));
        out.push("<a>".repeat(n));
        out.push(format!("{}{}", "<a>".repeat(n), "</a>".repeat(n)));
        out.push(format!("<event>{}", "<a b=\"1\">".repeat(n)));
    }
    // XML cut at every point of a tag, and tags that do not balance
    let doc = "<?xml version=\"1.0\"?><!-- c --><event uid=\"a\" type='b'><point lat=\"1\"/><detail>t&amp;</detail></event>";
    for at in 0..=doc.len() {
        out.push(doc[..at].to_string());
    }
    for s in [
        "<", "<event", "<event ", "<event uid", "<event uid=", "<event uid= ", "<event uid=\"", "<event uid=\"a",
        "<event uid=\"a\"", "<event/", "<event>", "<event></", "<event></event", "<event></other>", "<a><b></a></b>",
        "</event>", "<event/><event/>", "<event/>x", "<?", "<?xml", "<!", "<!--", "<!DOCTYPE", "<event><!--",
        "<event><?", "<>", "< event/>", "<event =\"a\"/>", "<event uid=a/>", "\u{feff}<event/>", "",
    ] {
        out.push(s.to_string());
    }
    // JSON cut inside every construct
    let doc = "{\"type\":\"Feature\",\"id\":\"a\\u00e9\\ud83d\\ude00\",\"n\":-1.5e+3,\"geometry\":{\"coordinates\":[1,2.5,null]},\"properties\":{\"t\":true,\"f\":false}}";
    for at in 0..=doc.len() {
        out.push(doc[..at].to_string());
    }
    for s in [
        "{", "{\"", "{\"a", "{\"a\"", "{\"a\":", "{\"a\":1", "{\"a\":1,", "[", "[1", "[1,", "\"", "\"\\", "\"\\u", "\"\\u12",
        "\"\\ud83d\\u", "\"\\ud83d\\ude0", "\"\\u+123\"", "t", "tru", "n", "nul", "-", "1.", "1e", "1e+", "01", "+1", ".5",
        "1e999", "-1e999", "{\"a\":1e999}", "{}x", "{} {}", "{\"a\":1,\"a\":2}", "{\"a\":\"\t\"}", "{\"a\":\"\\x\"}", "{a:1}",
        "{\"a\" 1}", "{\"a\":1 \"b\":2}", "[1 2]", "99999999999999999999999999", "-99999999999999999999999999",
        "{\"id\":99999999999999999999999999}", "null", "true", "\"s\"", "1",
    ] {
        out.push(s.to_string());
    }
    // hex text: odd length, a character that is not a hex digit, a sign
    for s in ["0", "000", "zz", "0g", "+f", "-1", "0x00", "00 0", "é0", "００"] {
        out.push(s.to_string());
    }
    // protobuf: a varint that never ends, a length far beyond the input,
    // field numbers out of range, every wire type cut short
    for s in [
        "08", "0880", "08ffffffffffffffffff", "08ffffffffffffffffffff01", "0a", "0a05", "0a0561", "0aff", "0affffffffffffffffff01",
        "0affffffffffffffff7f", "0a80808080808080808001", "09", "0900000000000000", "0d", "0d000000", "0b", "0c", "0e", "0f",
        "00", "0000", "f8ffffffffffffffff0100", "ffffffffffffffffffff", "80", "8080808080808080808080",
        "22ffffffffffffffffff0122", "2205220322012a",
    ] {
        out.push(s.to_string());
    }
    // bits: every length of all-ones and all-zeros up to 96 bytes, so every
    // count, length and presence field reads its largest and smallest value
    for n in 0..=96usize {
        out.push("ff".repeat(n));
        out.push("00".repeat(n));
    }
    for n in [255usize, 256, 4096] {
        out.push("ff".repeat(n));
        out.push("00".repeat(n));
        out.push("80".repeat(n));
        out.push("01".repeat(n));
    }
    out.push("ff".repeat(65_536));
    out.push("00".repeat(65_536));
    // text records: very many fields, very long fields, checksums right and
    // wrong, terminators, columns cut at every point, values at their limits
    for n in [0usize, 1, 2, 3, 64, 100_000] {
        out.push(",".repeat(n));
        out.push(";".repeat(n));
        out.push(" ".repeat(n));
        out.push(nmea("$", &",".repeat(n)));
        out.push(nmea("$", &format!("GPSAT,1{}", ",a,1,0.5".repeat(n))));
        out.push(nmea("$", &format!("GPFIX{}", ",9".repeat(n))));
        out.push(format!("P;{}", "x;".repeat(n)));
    }
    for s in [
        "$", "$*", "$*0", "$*00", "*00", "$GPFIX*", "$GPFIX*zz", "$GPFIX*4", "$GPFIX**00", "$a*b*00", "\n", "\r\n", "\r",
        "x\n\n", "x\r\r\n", "\t", "\u{7f}", "é", "$GPFIX\u{0}*00",
    ] {
        out.push(s.to_string());
    }
    for body in [
        "GPFIX,999999.99,9999.9999,N,99999.9999,E,99999999999999999999,99,99999999999999999999.9,-.,,x,y",
        "GPFIX,235959.999,0000.0000,S,00000.0000,W,-9223372036854775808,-0,-0.0,+.5,,,9223372036854775808",
        "GPFIX,240000,4860.0000,n,01131.0000,X,1e5,0x1,inf,nan,,,",
        "GPFIX,123519.,4807.,N,0113,E,,,,,,,",
        "GPTIM,123519.123456789,290200,1.5,A",
        "GPTIM,123519,290201,1.5,D",
        "GPTIM,123519,000000,-0,B",
        "GPTIM,,230394,,",
        "GPTIM,123519,,,",
        "GPSAT,,,,,,,,,,",
        "GPSAT,1,",
    ] {
        out.push(nmea("$", body));
    }
    let record = "ABCDEF-0042-30.5000 WXYZ-07";
    for at in 0..=record.len() {
        out.push(record[..at].to_string());
    }
    // tag-length-value sets: lengths of 2^64-1 and lengths far beyond the
    // input at every level, tags that never end, very many items
    let key = "060e2b34";
    for s in [
        "88ffffffffffffffff", "887fffffffffffffff", "84ffffffff", "81", "88", "80", "89", "ff", "0188ffffffffffffffff",
        "0180", "0189", "01ff", "8080808001", "8181818101", "ffffffff7f00", "300209", "3003020901", "30028800",
        "3088ffffffffffffffff", "30813002", "0102000101020001", "010000",
    ] {
        out.push(s.to_string());
        out.push(format!("{}{}", key, s));
    }
    for n in [1usize, 2, 1_000, 50_000] {
        out.push("0700".repeat(n));
        out.push(format!("{}{}", "3002".repeat(n), "0700"));
        let set = "0700".repeat(n);
        let mut framed = key.to_string();
        let mut len = Vec::new();
        ber_len(set.len() / 2, &mut len);
        framed.push_str(&to_hex(&len));
        framed.push_str(&set);
        out.push(framed);
        out.push(tlv_framed(&[0x06, 0x0e, 0x2b, 0x34], 1, &[0x07, 0x00].repeat(n)));
    }
    out.push(tlv_framed(&[0x06, 0x0e, 0x2b, 0x34], 1, &[]));
    out.push(tlv_framed(&[0x06, 0x0e, 0x2b, 0x34], 1, &[0x01, 0x02, 0x00, 0x00]));
    out
}

#[test]
fn malformed_input_never_panics() {
    let iters: usize = std::env::var("GOAT_FUZZ_ITERS").ok().and_then(|s| s.parse().ok()).unwrap_or(1).max(1);
    let seed: u64 = std::env::var("GOAT_FUZZ_SEED").ok().and_then(|s| s.parse().ok()).unwrap_or(0x9E37_79B9_7F4A_7C15);
    let mut rng = Rng(seed | 1);

    let mut engine = Engine::new();
    engine.load_model_dir(&repo_packs_dir().join("../model")).unwrap_or_else(|e| panic!("model: {}", e));
    engine.load_pack_dir(&repo_packs_dir()).unwrap_or_else(|e| panic!("pack: {}", e));
    let formats = engine.formats();
    let vectors = conversion_vectors(&engine);
    assert!(!formats.is_empty() && !vectors.is_empty(), "no packs or no vectors were loaded");

    // a caught panic is reported below with its input; keep the default
    // hook from printing each one as it happens
    let hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));

    let mut ran = 0usize;
    let mut failures: Vec<String> = Vec::new();
    let mut slowest = (std::time::Duration::ZERO, String::new());
    let mut run = |from: &str, to: &str, input: &str, class: &str| {
        ran += 1;
        let started = std::time::Instant::now();
        let result = check(&engine, from, to, input);
        let took = started.elapsed();
        if took > slowest.0 {
            let shown: String = input.chars().take(60).collect();
            slowest = (took, format!("[{}] {} -> {}, {} bytes: {:?}", class, from, to, input.len(), shown));
        }
        if std::env::var_os("GOAT_FUZZ_TRACE").is_some() && took.as_millis() > 200 {
            let shown: String = input.chars().take(60).collect();
            eprintln!("slow {:?} [{}] {} -> {}, {} bytes: {:?}", took, class, from, to, input.len(), shown);
        }
        if let Some(why) = result {
            if failures.len() < 200 {
                let shown: String = input.chars().take(160).collect();
                failures.push(format!("[{}] {} -> {}: {}\n      input ({} bytes): {:?}", class, from, to, why, input.len(), shown));
            }
        }
    };

    // (a) random bytes and random text, and (d) hostile shapes, for every pack
    let shapes = hostile();
    for format in &formats {
        for _ in 0..RANDOM_PER_ALPHABET * iters {
            let len = rng.below(96);
            let bytes: Vec<u8> = (0..len).map(|_| rng.next() as u8).collect();
            run(format, format, &String::from_utf8_lossy(&bytes), "random bytes");
            for alphabet in [HEX, XMLISH, JSONISH, TEXTISH] {
                let len = rng.below(96);
                let text: Vec<u8> = (0..len).map(|_| rng.pick(alphabet)).collect();
                run(format, format, &String::from_utf8_lossy(&text), "random text");
            }
        }
        for shape in &shapes {
            run(format, format, shape, "hostile shape");
        }
    }

    // (e) random tag-length-value sets, bare and framed, for every pack
    for format in &formats {
        for _ in 0..RANDOM_PER_ALPHABET * iters {
            let mut set = Vec::new();
            tlv_set(&mut rng, 3, &mut set);
            run(format, format, &to_hex(&set), "tlv set");
            run(format, format, &tlv_framed(&[0x06, 0x0e, 0x2b, 0x34], 1, &set), "tlv framed");
        }
    }

    // (b) prefixes and (c) one-byte mutations of every vector input
    for case in &vectors {
        let n = case.input.len();
        let hex = !case.input.is_empty() && case.input.bytes().all(|b| b.is_ascii_hexdigit() || b.is_ascii_whitespace());
        let mut last = usize::MAX;
        let prefixes = capped(PREFIXES_PER_VECTOR, n);
        for k in 0..prefixes.min(n) {
            // every length when the input is short, else an even spread
            let at = if n <= prefixes { k } else { k * n / prefixes };
            let at = boundary(&case.input, at);
            if at != last {
                run(&case.from, &case.to, &case.input[..at], "prefix");
                last = at;
            }
        }
        if n == 0 {
            continue;
        }
        for _ in 0..capped(MUTATIONS_PER_VECTOR, n) * iters {
            let mut bytes = case.input.clone().into_bytes();
            let at = rng.below(n);
            // hex text mostly stays hex, so the mutation reaches the decoder behind it
            bytes[at] = match rng.below(8) {
                0 => rng.next() as u8,
                _ if hex => rng.pick(HEX),
                1 | 2 => rng.pick(XMLISH),
                3 | 4 => rng.pick(JSONISH),
                5 => rng.pick(TEXTISH),
                _ => (rng.next() % 0x5f) as u8 + 0x20,
            };
            run(&case.from, &case.to, &String::from_utf8_lossy(&bytes), "mutation");
        }
        // (e) a hex input mutated, then a correct sum16 in its last two bytes
        if hex && (8..=LARGE_INPUT).contains(&n) && n % 2 == 0 {
            let b: Vec<u8> = (0..n / 2).filter_map(|i| u8::from_str_radix(&case.input[2 * i..2 * i + 2], 16).ok()).collect();
            if b.len() == n / 2 {
                for _ in 0..capped(MUTATIONS_PER_VECTOR, n) * iters {
                    let mut m = b.clone();
                    let at = rng.below(m.len() - 2);
                    m[at] = rng.next() as u8;
                    let k = m.len();
                    let s = sum16(&m[..k - 2]);
                    m[k - 2..].copy_from_slice(&s.to_be_bytes());
                    run(&case.from, &case.to, &to_hex(&m), "mutation, sum16 repaired");
                }
            }
        }
    }

    std::panic::set_hook(hook);
    use std::io::Write;
    let mut out = std::io::stderr();
    let _ = writeln!(
        out,
        "fuzz: ran {} inputs over {} packs and {} vectors (GOAT_FUZZ_ITERS={}, seed {}), {} failed",
        ran,
        formats.len(),
        vectors.len(),
        iters,
        seed,
        failures.len()
    );
    let _ = writeln!(out, "fuzz: slowest input took {:?}: {}", slowest.0, slowest.1);
    for f in &failures {
        let _ = writeln!(out, "  FAIL {}", f);
    }
    assert!(failures.is_empty(), "{} inputs panicked or failed with an error of no named kind", failures.len());
}
