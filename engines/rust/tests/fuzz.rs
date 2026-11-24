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
//!     and then given a correct sum16 in its last two bytes;
//! (f) six-bit armored text (engine-spec 0.14): random runs of the 64 armor
//!     characters, at every length from none up, with now and then a
//!     character just outside the map; and every armored vector input
//!     mutated within the armor alphabet, so that the mutation reaches the
//!     lines behind the character check;
//! (g) for every pack with `encoding uper` (engine-spec 0.19): bit strings
//!     built from the pieces X.691 reads (single bits, short and long length
//!     determinants, the fragmented prefix `11`, normally small numbers,
//!     runs of ones and of zeros, lengths of 16383 with nothing behind them),
//!     each of which must also finish within `UPER_TIME_LIMIT`, so that no
//!     length read from the input makes the work unbounded.
//! (h) CBOR data items (engine-spec 0.28): random items of every major type,
//!     with definite and indefinite lengths, heads longer than they need,
//!     tags, every float width, keys of every type, nesting around the depth
//!     limit, and now and then a broken head, a reserved additional
//!     information, a stray break or a length beyond the input; each also
//!     enclosed in tag 18. And fixed hostile shapes: nesting far beyond the
//!     depth limit through arrays, maps and tags, counts and lengths of
//!     2^64-1, indefinite items that never end.
//!
//! Each call must return `Ok`, or an error whose message starts with one of
//! the error kinds `convert` may fail with, then a colon. A panic is caught,
//! and every failure is reported with its pack and its input before the test
//! fails.
//!
//! The inputs come from a xorshift generator with a fixed seed, so a run is
//! reproducible. `GOAT_FUZZ_ITERS=<n>` multiplies the number of random and
//! mutated inputs (default 1); `GOAT_FUZZ_SEED=<n>` changes the seed.
// The packs this test loads need these wires (engine-spec 0.24).
#![cfg(all(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]

use goat_transformers::json::Json;
use goat_transformers::{json, Engine};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::{Path, PathBuf};

/// The error kinds `convert` with no context may fail with
/// (spec/vector-format.md, `expect_error`). Version 0.34 adds the checks
/// made where decode or encode reaches an `inner` line: `unknown-format`,
/// `bad-directive` and `distribution-violation`.
const KINDS: [&str; 8] = [
    "malformed-wire",
    "no-kind",
    "missing-root",
    "transform-decode",
    "transform-encode",
    "unknown-format",
    "bad-directive",
    "distribution-violation",
];

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
/// The 64 characters of six-bit armor: `0` (0x30) to `W` (0x57), `` ` `` (0x60) to `w` (0x77).
const ARMOR: &[u8] = b"0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVW`abcdefghijklmnopqrstuvw";
/// The characters just outside the armor map, and the line terminators.
const ARMOR_EDGE: &[u8] = b"/X_x \r\n";

/// The longest one input of (g) may take.
const UPER_TIME_LIMIT: std::time::Duration = std::time::Duration::from_secs(2);

/// The formats whose pack has an `encoding uper` line.
fn uper_formats() -> Vec<String> {
    let mut out = Vec::new();
    for dir in std::fs::read_dir(repo_packs_dir()).unwrap().flatten() {
        let text = match std::fs::read_to_string(dir.path().join("pack.def")) {
            Ok(t) => t,
            Err(_) => continue,
        };
        let words = |l: &str| l.split('#').next().unwrap_or("").split_whitespace().map(|w| w.to_string()).collect::<Vec<_>>();
        if text.lines().any(|l| words(l) == ["encoding", "uper"]) {
            if let Some(f) = text.lines().map(words).find(|w| w.len() == 2 && w[0] == "format") {
                out.push(f[1].clone());
            }
        }
    }
    out.sort();
    out
}

/// A random bit string of the pieces X.691 reads, as hex.
fn uper_bits(rng: &mut Rng) -> String {
    let mut bits: Vec<bool> = Vec::new();
    let push = |bits: &mut Vec<bool>, v: u64, n: u32| (0..n).rev().for_each(|i| bits.push(v >> i & 1 == 1));
    for _ in 0..rng.below(40) {
        match rng.below(10) {
            0 => push(&mut bits, rng.next() & 1, 1),
            // a short length determinant, and as many octets now and then
            1 => {
                let n = rng.below(128) as u64;
                push(&mut bits, n, 8);
                if rng.below(2) == 0 {
                    (0..n).for_each(|_| push(&mut bits, rng.next() & 0xff, 8));
                }
            }
            // a long length determinant, up to 16383, with little behind it
            2 => push(&mut bits, 0x8000 | (rng.next() & 0x3fff), 16),
            3 => push(&mut bits, 0xbfff, 16),
            // the fragmented prefix
            4 => push(&mut bits, 0b11, 2),
            // a normally small number, short and long
            5 => push(&mut bits, rng.next() & 0x3f, 7),
            6 => push(&mut bits, 0x80 | 0x09, 9),
            7 => push(&mut bits, u64::MAX, rng.below(64) as u32 + 1),
            8 => push(&mut bits, 0, rng.below(64) as u32 + 1),
            _ => push(&mut bits, rng.next(), rng.below(64) as u32 + 1),
        }
    }
    while bits.len() % 8 != 0 {
        bits.push(rng.below(2) == 0);
    }
    let bytes: Vec<u8> = bits.chunks(8).map(|c| c.iter().fold(0u8, |a, b| a << 1 | *b as u8)).collect();
    to_hex(&bytes)
}

/// Is every byte of `s` an armor character (a hex input is one too)?
fn armored(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| ARMOR.contains(&b))
}

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

/// A CBOR head: the shortest form, or now and then a longer one.
fn cbor_head(rng: &mut Rng, major: u8, n: u64, out: &mut Vec<u8>) {
    let m = major << 5;
    let width = match n {
        0..=23 if rng.below(4) != 0 => 0,
        0..=0xff => 1,
        0x100..=0xffff => 2,
        0x1_0000..=0xffff_ffff => 4,
        _ => 8,
    };
    // a longer head than the value needs
    let width = if rng.below(6) == 0 { [1, 2, 4, 8][rng.below(4)].max(width) } else { width };
    match width {
        0 => out.push(m | n as u8),
        1 => out.extend_from_slice(&[m | 24, n as u8]),
        2 => {
            out.push(m | 25);
            out.extend_from_slice(&(n as u16).to_be_bytes());
        }
        4 => {
            out.push(m | 26);
            out.extend_from_slice(&(n as u32).to_be_bytes());
        }
        _ => {
            out.push(m | 27);
            out.extend_from_slice(&n.to_be_bytes());
        }
    }
}

/// A random CBOR data item nested up to `depth` levels below this one.
fn cbor_item(rng: &mut Rng, depth: usize, out: &mut Vec<u8>) {
    const NUMS: [u64; 12] = [0, 1, 5, 9, 23, 24, 255, 256, 65535, 1 << 32, (1 << 63) - 1, u64::MAX];
    const TEXTS: [&[u8]; 8] = [b"", b"a", b"name", b"n", b"4", b"a.b", b"\xc3\xa9", b"\xc3"];
    // now and then a broken item
    match rng.below(64) {
        0 => return out.push(0x1c + 0x20 * rng.below(8) as u8),
        1 => return out.push(0xff),
        2 => return out.extend_from_slice(&[0xf8, rng.below(32) as u8]),
        3 => return out.extend_from_slice(&[0x5b, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]),
        4 => return out.extend_from_slice(&[0x9b, 0x7f, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]),
        _ => {}
    }
    let containers = if depth > 0 { 3 } else { 0 };
    match rng.below(9 + containers) {
        0 => {
            let n = NUMS[rng.below(NUMS.len())];
            cbor_head(rng, 0, n, out)
        }
        1 => {
            let n = NUMS[rng.below(NUMS.len())];
            cbor_head(rng, 1, n, out)
        }
        2 => {
            let n = [0usize, 1, 2, 8, 40][rng.below(5)];
            cbor_head(rng, 2, n as u64, out);
            out.extend((0..n).map(|_| rng.next() as u8));
        }
        3 => {
            let t = TEXTS[rng.below(TEXTS.len())];
            if rng.below(4) == 0 {
                // indefinite, in chunks of one byte: a split UTF-8 sequence now and then
                out.push(0x7f);
                for c in t {
                    out.extend_from_slice(&[0x61, *c]);
                }
                out.push(0xff);
            } else {
                cbor_head(rng, 3, t.len() as u64, out);
                out.extend_from_slice(t);
            }
        }
        4 => match rng.below(6) {
            5 => out.extend_from_slice(&[0xf8, 0x20 + rng.below(0xe0) as u8]),
            k => out.push([0xf4, 0xf5, 0xf6, 0xf7, 0xe0][k]),
        },
        5 => {
            out.push(0xf9);
            out.extend_from_slice(&[[0x00, 0x01], [0x80, 0x00], [0x3e, 0x00], [0x7c, 0x00], [0x7e, 0x00], [0x7b, 0xff]][rng.below(6)]);
        }
        6 => {
            out.push(0xfa);
            out.extend_from_slice(&[[0x47, 0xc3, 0x50, 0x00], [0x7f, 0x80, 0x00, 0x01], [0x00, 0x00, 0x00, 0x01]][rng.below(3)]);
        }
        7 => {
            out.push(0xfb);
            out.extend((0..8).map(|_| rng.next() as u8));
        }
        8 => {
            let n = NUMS[rng.below(4)] + 18 * rng.below(2) as u64;
            cbor_head(rng, 6, n, out)
        }
        9 => {
            let n = rng.below(6);
            if rng.below(4) == 0 {
                out.push(0x9f);
            } else {
                cbor_head(rng, 4, n as u64, out);
            }
            for _ in 0..n {
                cbor_item(rng, depth - 1, out);
            }
            if out.last() != Some(&0xff) && rng.below(8) == 0 {
                out.push(0xff);
            }
        }
        10 => {
            let n = rng.below(6);
            let indefinite = rng.below(4) == 0;
            if indefinite {
                out.push(0xbf);
            } else {
                cbor_head(rng, 5, n as u64, out);
            }
            for i in 0..n {
                // keys of every type; mostly small integers and text, so a
                // pack's paths find them, and equal keys now and then
                match rng.below(5) {
                    0 | 1 => {
                        let n = (i + rng.below(3)) as u64;
                        cbor_head(rng, 0, n, out)
                    }
                    2 => out.extend_from_slice(&[0x20 + rng.below(2) as u8]),
                    3 => out.extend_from_slice(&[[0x61, b'n'], [0x61, b'a'], [0x61, b'4']][rng.below(3)]),
                    _ => cbor_item(rng, depth - 1, out),
                }
                cbor_item(rng, depth - 1, out);
            }
            if indefinite {
                out.push(0xff);
            }
        }
        _ => {
            // a tag on an item
            let t = [0, 1, 18, 24, 55799][rng.below(5)];
            cbor_head(rng, 6, t, out);
            cbor_item(rng, depth - 1, out);
        }
    }
}

/// A random top item: a map or an array, with items nested up to 6 levels.
fn cbor_top(rng: &mut Rng) -> Vec<u8> {
    let mut out = Vec::new();
    let n = rng.below(10);
    let array = rng.below(3) == 0;
    cbor_head(rng, if array { 4 } else { 5 }, n as u64, &mut out);
    for i in 0..n {
        if !array {
            match rng.below(3) {
                0 => cbor_head(rng, 3, 1, &mut out),
                _ => cbor_head(rng, 0, i as u64, &mut out),
            }
            if out.last().map_or(false, |b| *b == 0x61) {
                out.push([b'a', b'n', b'x'][rng.below(3)]);
            }
        }
        cbor_item(rng, 6, &mut out);
    }
    out
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
    // CBOR: nesting far beyond the depth limit through arrays, maps and
    // tags, closed and not; counts and lengths of 2^64-1; indefinite items
    // that never end; a break where a map value stands
    for n in [63usize, 64, 65, 66, 1_000, 50_000] {
        out.push(format!("{}00", "81".repeat(n)));
        out.push("81".repeat(n));
        out.push("9f".repeat(n));
        out.push(format!("{}{}", "9f".repeat(n), "ff".repeat(n)));
        out.push(format!("{}00", "a100".repeat(n)));
        out.push(format!("{}00", "c1".repeat(n)));
        out.push(format!("{}a0", "d8".repeat(n)));
        out.push(format!("d2{}00", "8100".repeat(n)));
    }
    for s in [
        "9bffffffffffffffff", "bbffffffffffffffff", "5bffffffffffffffff", "7bffffffffffffffff", "9b7fffffffffffffff",
        "bb7fffffffffffffff", "5b7fffffffffffffff00", "dbffffffffffffffffa0", "d2", "d2d2", "9f", "bf", "bf00", "bf00ff",
        "5f", "5f41", "5f4100", "7f6100", "7f61c3ff", "7f62c3a9ff", "7f61c361a9ff", "5f6100ff", "7f5f", "7f7fff", "a1", "a100",
        "a10000", "a2000000", "a200001800", "bf0000001800ff", "a2f93c00fb3ff0000000000000", "1c", "3d", "5e", "7f9f", "ff",
        "f8", "f81f", "f820", "f9", "f97c", "fa7fc0", "fb", "1b", "1bffffffff", "c0", "df", "a0ff", "8000", "a2616161616161",
        "a1d82400", "a1f600", "a1f700", "a10180", "a101a0", "a1098000", "a109a0", "a109f6", "a10982a0f6", "a109818101",
        "a10783f6f6f6", "a10781f6", "a108f6", "a1088200f6", "a10082", "a1006001", "a100fa7f800000", "a100fb7ff8000000000001",
        "d28440a0f640", "d2d28440a10101f640", "d18440a0f640", "d2a0", "848484848484", "84", "", "a0a0", "80",
    ] {
        out.push(s.to_string());
    }
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

    // (f) six-bit armored text for every pack: every length up to 40
    // characters, then random lengths, an edge character now and then
    for format in &formats {
        for len in 0..40 {
            let text: Vec<u8> = (0..len).map(|_| rng.pick(ARMOR)).collect();
            run(format, format, &String::from_utf8_lossy(&text), "armored text");
        }
        for _ in 0..RANDOM_PER_ALPHABET * iters {
            let len = rng.below(300);
            let mut text: Vec<u8> = (0..len).map(|_| rng.pick(ARMOR)).collect();
            if len > 0 && rng.below(4) == 0 {
                let at = rng.below(len);
                text[at] = rng.pick(ARMOR_EDGE);
            }
            run(format, format, &String::from_utf8_lossy(&text), "armored text");
        }
    }

    // (g) X.691 pieces for every UPER pack, each within the time limit
    let mut slow: Vec<String> = Vec::new();
    for format in &uper_formats() {
        for _ in 0..RANDOM_PER_ALPHABET * 8 * iters {
            let input = uper_bits(&mut rng);
            let started = std::time::Instant::now();
            run(format, format, &input, "uper bits");
            if started.elapsed() > UPER_TIME_LIMIT {
                slow.push(format!("{}: {:?} for {} bytes", format, started.elapsed(), input.len() / 2));
            }
        }
    }

    // (h) random CBOR items for every pack, bare and in tag 18
    for format in &formats {
        for _ in 0..RANDOM_PER_ALPHABET * iters {
            let item = cbor_top(&mut rng);
            run(format, format, &to_hex(&item), "cbor item");
            let mut tagged = vec![0xd2];
            tagged.extend_from_slice(&item);
            run(format, format, &to_hex(&tagged), "cbor item in tag 18");
        }
    }

    // (b) prefixes and (c) one-byte mutations of every vector input
    for case in &vectors {
        let n = case.input.len();
        let hex = !case.input.is_empty() && case.input.bytes().all(|b| b.is_ascii_hexdigit() || b.is_ascii_whitespace());
        // (f) armored text (hex digits excepted) mostly stays armored
        let armor = !hex && armored(&case.input);
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
                1 if armor => rng.pick(ARMOR_EDGE),
                _ if armor => rng.pick(ARMOR),
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
    for s in &slow {
        let _ = writeln!(out, "  SLOW {}", s);
    }
    assert!(slow.is_empty(), "{} UPER inputs took longer than {:?}", slow.len(), UPER_TIME_LIMIT);
    assert!(failures.is_empty(), "{} inputs panicked or failed with an error of no named kind", failures.len());
}
