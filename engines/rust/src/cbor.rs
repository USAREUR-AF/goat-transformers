//! The `cbor` wire (engine-spec v0.28): one CBOR data item (RFC 8949), a map
//! or an array whose items may be maps, arrays and scalars at any depth.
//! Input and output are hex text.
//!
//! Paths: steps separated by `.`; a step is an integer key (`4`, `-1`), an
//! array position (`[0]`) or a text key (`name`). Output is the core
//! deterministic encoding of RFC 8949 4.2.1.

use super::*;
use std::collections::BTreeMap;

/// Arrays, maps and tags count one level each, the top item level 1.
pub(crate) const MAX_DEPTH: usize = 64;

/// The cbor directives of a pack, as the encoder and decoder use them.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct CborConf {
    /// `tag <n>`: the message is tag `n` enclosing the item
    pub tag: Option<u64>,
    /// the paths decide an array as the top item (else a map)
    pub top_array: bool,
}

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

/// One step of a path.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub(crate) enum Step {
    /// an integer key, -2^63 to 2^64-1 (major type 0 or 1)
    Int(i128),
    /// a text key the step grammar can write (major type 3)
    Text(String),
    /// an array position, 0 to 65535
    Pos(usize),
}

impl Step {
    fn is_pos(&self) -> bool {
        matches!(self, Step::Pos(_))
    }
    fn text(&self) -> String {
        match self {
            Step::Int(n) => n.to_string(),
            Step::Text(s) => s.clone(),
            Step::Pos(i) => format!("[{}]", i),
        }
    }
}

const MIN_INT: i128 = -(1i128 << 63);
const MAX_INT: i128 = u64::MAX as i128;
const MAX_POS: usize = 65535;

/// A text key the step grammar can write: ASCII letters, digits, `_` and
/// `-`, not beginning with a digit or `-`.
fn text_writable(s: &str) -> bool {
    let b = s.as_bytes();
    !b.is_empty()
        && (b[0].is_ascii_alphabetic() || b[0] == b'_')
        && b.iter().all(|c| c.is_ascii_alphanumeric() || *c == b'_' || *c == b'-')
}

fn parse_step(s: &str) -> Result<Step, String> {
    if s.is_empty() {
        return Err("an empty step".into());
    }
    if let Some(inner) = s.strip_prefix('[') {
        let digits = match inner.strip_suffix(']') {
            Some(d) => d,
            None => return Err(format!("`{}`: a position is `[<i>]`", s)),
        };
        if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) || (digits.len() > 1 && digits.starts_with('0')) {
            return Err(format!("`{}`: a position is a decimal integer with no leading zero", s));
        }
        return match digits.parse::<usize>() {
            Ok(i) if i <= MAX_POS => Ok(Step::Pos(i)),
            _ => Err(format!("`{}`: a position is 0 to 65535", s)),
        };
    }
    let b = s.as_bytes();
    if b[0].is_ascii_digit() || b[0] == b'-' {
        let (neg, digits) = match s.strip_prefix('-') {
            Some(d) => (true, d),
            None => (false, s),
        };
        if digits.is_empty() || !digits.bytes().all(|c| c.is_ascii_digit()) {
            return Err(format!("`{}`: an integer key is an optional `-` and decimal digits", s));
        }
        if digits.len() > 1 && digits.starts_with('0') {
            return Err(format!("`{}`: an integer key has no leading zero", s));
        }
        if neg && digits == "0" {
            return Err(format!("`{}`: `-0` is not an integer key", s));
        }
        let n: i128 = if digits.len() > 20 { i128::MAX } else { digits.parse().unwrap_or(i128::MAX) };
        let v = if neg { -n } else { n };
        if !(MIN_INT..=MAX_INT).contains(&v) {
            return Err(format!("`{}`: an integer key is -2^63 to 2^64-1", s));
        }
        return Ok(Step::Int(v));
    }
    if !text_writable(s) {
        return Err(format!("`{}`: a text key is ASCII letters, digits, `_` and `-`, not beginning with a digit or `-`", s));
    }
    Ok(Step::Text(s.to_string()))
}

/// A path: one or more steps separated by `.`; `.` alone is the item itself
/// (no step).
pub(crate) fn parse_path(s: &str) -> Result<Vec<Step>, String> {
    if s == "." {
        return Ok(Vec::new());
    }
    s.split('.').map(parse_step).collect()
}

/// The path of a line already checked at load.
fn path(s: &str) -> Vec<Step> {
    parse_path(s).unwrap_or_default()
}

fn path_text(p: &[Step]) -> String {
    if p.is_empty() {
        return ".".into();
    }
    p.iter().map(|s| s.text()).collect::<Vec<_>>().join(".")
}

// ---------------------------------------------------------------------------
// Load checks
// ---------------------------------------------------------------------------

/// The transforms of the cbor wire, and of no other.
pub(crate) fn cbor_only(t: &Transform) -> bool {
    matches!(t, Transform::CborText | Transform::CborBytes | Transform::EpochS)
}

/// On `cbor` the transforms of its table are valid and every other is `bad-directive`.
pub(crate) fn valid_transform(t: &Transform) -> bool {
    cbor_only(t) || matches!(t, Transform::Uint | Transform::Int | Transform::Float | Transform::Bool)
}

/// The value of a `when` or `const` line on `cbor`.
#[derive(Clone, Debug, PartialEq)]
pub(crate) enum WhenValue {
    Int(i128),
    Bool(bool),
    Text(String),
}

/// An integer when 2a of 0.11 accepts it (a sign and leading zeros allowed)
/// and it lies in -2^63 to 2^64-1; `true` or `false` a bool; any other value
/// a text string, one leading `=` stripped.
pub(crate) fn when_value(s: &str) -> WhenValue {
    let (neg, digits) = match s.strip_prefix('-') {
        Some(d) => (true, d),
        None => (false, s),
    };
    if !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit()) {
        let trimmed = digits.trim_start_matches('0');
        if trimmed.len() <= 20 {
            let n: i128 = if trimmed.is_empty() { 0 } else { trimmed.parse().unwrap_or(i128::MAX) };
            let v = if neg { -n } else { n };
            if (MIN_INT..=MAX_INT).contains(&v) {
                return WhenValue::Int(v);
            }
        }
    }
    match s {
        "true" => WhenValue::Bool(true),
        "false" => WhenValue::Bool(false),
        _ => WhenValue::Text(s.strip_prefix('=').unwrap_or(s).to_string()),
    }
}

/// A `when` or `const` line: its path, and `present`.
pub(crate) fn resolve_when(w: &mut WhenDef) -> Result<(), Error> {
    if w.locator == "." {
        return bad(w.line, "`.` names the item of a group; a `when` or `const` takes a path");
    }
    parse_path(&w.locator).or_else(|m| bad(w.line, m))?;
    if w.value == "present" {
        w.present = true;
    }
    Ok(())
}

/// A `group` locator on `cbor`: a path, or `.`.
pub(crate) fn group_locator_ok(s: &str) -> bool {
    parse_path(s).is_ok()
}

/// The type a body or the top item takes, from its paths.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Shape {
    /// no path decides
    Any,
    Map,
    Array,
    /// only `.` lines
    Scalar,
}

/// One line of a scope as the checks and the codec see it.
struct ScopeLine {
    line: usize,
    path: Vec<Step>,
    group: bool,
    /// `when … present`, which may name a proper prefix of another line's path
    present: bool,
}

fn scope_lines(fields: &[FieldDef], whens: &[WhenDef], consts: &[WhenDef], groups: &[GroupDef]) -> Vec<ScopeLine> {
    let mut out: Vec<ScopeLine> = fields
        .iter()
        .map(|f| ScopeLine { line: f.line, path: path(&f.locator), group: false, present: false })
        .chain(
            whens
                .iter()
                .chain(consts)
                .map(|w| ScopeLine { line: w.line, path: path(&w.locator), group: false, present: w.present }),
        )
        .chain(groups.iter().map(|g| ScopeLine { line: g.line, path: path(&g.locator), group: true, present: false }))
        .collect();
    out.sort_by_key(|l| l.line);
    out
}

/// Within one scope: a step whose item is used both as a map and as an
/// array, and a `field`, `when` or `const` at or under a `group`'s path, are
/// `bad-directive`.
fn check_scope(lines: &[ScopeLine]) -> Result<(), Error> {
    // prefix -> true when the item there is used as an array
    let mut uses: HashMap<Vec<Step>, bool> = HashMap::new();
    for l in lines {
        let mut need = |prefix: &[Step], array: bool| -> Result<(), Error> {
            match uses.get(prefix) {
                Some(a) if *a != array => {
                    bad(l.line, format!("the item at `{}` is used both as a map and as an array", path_text(prefix)))
                }
                Some(_) => Ok(()),
                None => {
                    uses.insert(prefix.to_vec(), array);
                    Ok(())
                }
            }
        };
        for k in 0..l.path.len() {
            need(&l.path[..k], l.path[k].is_pos())?;
        }
        if l.group {
            need(&l.path[..], true)?;
        }
    }
    for g in lines.iter().filter(|l| l.group) {
        for l in lines.iter().filter(|l| !l.group) {
            if l.path.len() >= g.path.len() && l.path[..g.path.len()] == g.path[..] {
                return bad(l.line, format!("`{}` lies at or under the path `{}` of a group", path_text(&l.path), path_text(&g.path)));
            }
        }
    }
    // ruling 13 of 0.28: a path that is a proper prefix of another line's
    // path (so a body that mixes `.` with other paths), and a group at or
    // under another group's path; reported at the later line of the first pair
    let mut first: Option<(usize, String)> = None;
    for (i, a) in lines.iter().enumerate() {
        for b in &lines[i + 1..] {
            let under = |x: &ScopeLine, y: &ScopeLine| y.path.len() >= x.path.len() && y.path[..x.path.len()] == x.path[..];
            let (short, long) = if a.path.len() < b.path.len() { (a, b) } else { (b, a) };
            // a `when … present` may name a proper prefix of another line's path
            let why = if a.path.len() != b.path.len() && under(short, long) && !short.present {
                format!("`{}` is a value and also a container of `{}`", path_text(&short.path), path_text(&long.path))
            } else if a.group && b.group && (under(a, b) || under(b, a)) {
                format!("two groups at or under `{}`", path_text(if a.path.len() <= b.path.len() { &a.path } else { &b.path }))
            } else {
                continue;
            };
            let at = a.line.max(b.line);
            if first.as_ref().map_or(true, |(l, _)| at < *l) {
                first = Some((at, why));
            }
        }
    }
    match first {
        Some((ln, why)) => bad(ln, why),
        None => Ok(()),
    }
}

/// The shape of a body (or of the top item) from its lines: an array when a
/// path begins with a position or a group is `.`; else a map when any path
/// has a step; else a scalar when a field is `.`.
fn shape_of(lines: &[ScopeLine]) -> Shape {
    if lines.iter().any(|l| l.path.first().map_or(l.group, |s| s.is_pos())) {
        Shape::Array
    } else if lines.iter().any(|l| !l.path.is_empty()) {
        Shape::Map
    } else if lines.iter().any(|l| !l.group) {
        Shape::Scalar
    } else {
        Shape::Any
    }
}

fn body_shape(g: &GroupDef) -> Shape {
    shape_of(&scope_lines(&g.fields, &[], &g.consts, &g.groups))
}

/// The checks that run once the file is read (engine-spec v0.28): the `tag`
/// directive, `.` outside a group, the type of the top item, and the types
/// and group paths of each scope. Returns the directives.
pub(crate) fn check_pack(
    lines: &tlv::TlvLines,
    fields: &[FieldDef],
    whens: &[WhenDef],
    consts: &[WhenDef],
    groups: &[GroupDef],
    kinds: &[KindDef],
) -> Result<CborConf, Error> {
    let tag = lines.cbor_tag()?;
    let top_fields = fields.iter().chain(kinds.iter().flat_map(|k| k.fields.iter()));
    for f in top_fields {
        if f.locator == "." {
            return bad(f.line, "`.` names the item of a group; outside a group a field takes a path");
        }
    }
    let mut every: Vec<&GroupDef> = Vec::new();
    for g in groups.iter().chain(kinds.iter().flat_map(|k| k.groups.iter())) {
        g.walk(&mut every);
    }
    for g in &every {
        if let Some(c) = g.consts.iter().find(|c| c.locator == ".") {
            return bad(c.line, "`const .` is not valid");
        }
    }
    // the type of the top item, decided by every path outside a group body
    let mut top = scope_lines(fields, whens, consts, groups);
    for k in kinds {
        top.extend(scope_lines(&k.fields, &k.whens, &k.consts, &k.groups));
    }
    top.sort_by_key(|l| l.line);
    let mut decided: Option<(bool, usize)> = None;
    for l in &top {
        let array = match l.path.first() {
            Some(s) => s.is_pos(),
            None if l.group => true,
            None => continue,
        };
        match decided {
            Some((a, ln)) if a != array => {
                return bad(
                    l.line,
                    format!("`{}` takes the top item as {}, line {} as {}", path_text(&l.path), kind(array), ln, kind(a)),
                )
            }
            Some(_) => {}
            None => decided = Some((array, l.line)),
        }
    }
    // each scope: the common lines with one kind's, or one group body
    let common = scope_lines(fields, whens, consts, groups);
    if kinds.is_empty() {
        check_scope(&common)?;
    }
    for k in kinds {
        let mut ls = scope_lines(fields, whens, consts, groups);
        ls.extend(scope_lines(&k.fields, &k.whens, &k.consts, &k.groups));
        ls.sort_by_key(|l| l.line);
        check_scope(&ls)?;
    }
    for g in &every {
        check_scope(&scope_lines(&g.fields, &[], &g.consts, &g.groups))?;
    }
    Ok(CborConf { tag, top_array: decided.map_or(false, |(a, _)| a) })
}

fn kind(array: bool) -> &'static str {
    if array {
        "an array"
    } else {
        "a map"
    }
}

// ---------------------------------------------------------------------------
// Reading a data item
// ---------------------------------------------------------------------------

/// One data item of the input and the bytes it stood in.
#[derive(Debug)]
pub(crate) struct Node {
    start: usize,
    end: usize,
    v: V,
}

#[derive(Debug)]
enum V {
    Uint(u64),
    /// the negative integer -1-n
    Nint(u64),
    Bytes(Vec<u8>),
    Text(String),
    Array(Vec<Node>),
    Map(Vec<(Node, Node)>),
    Tag(u64, Box<Node>),
    Simple(u8),
    /// a half, single or double float, widened exactly: the bits of the double
    Float(u64),
}

struct Reader<'a> {
    b: &'a [u8],
    at: usize,
}

impl<'a> Reader<'a> {
    fn left(&self) -> u64 {
        (self.b.len() - self.at) as u64
    }
    fn byte(&mut self) -> Result<u8, String> {
        match self.b.get(self.at) {
            Some(c) => {
                self.at += 1;
                Ok(*c)
            }
            None => Err(format!("the item runs past the input at byte {}", self.at)),
        }
    }
    fn peek(&self) -> Result<u8, String> {
        self.b.get(self.at).copied().ok_or_else(|| format!("the item runs past the input at byte {}", self.at))
    }
    /// `n` bytes, compared with the bytes left before any memory is taken.
    fn take(&mut self, n: u64) -> Result<&'a [u8], String> {
        if n > self.left() {
            return Err(format!("a length of {} at byte {} is greater than the bytes left", n, self.at));
        }
        let s = &self.b[self.at..self.at + n as usize];
        self.at += n as usize;
        Ok(s)
    }
    /// The argument of a head whose additional information is 0 to 27, in
    /// any length.
    fn arg(&mut self, ai: u8) -> Result<u64, String> {
        let n = match ai {
            0..=23 => return Ok(ai as u64),
            24 => 1,
            25 => 2,
            26 => 4,
            27 => 8,
            _ => return Err(format!("additional information {} at byte {}", ai, self.at - 1)),
        };
        Ok(self.take(n)?.iter().fold(0u64, |a, c| (a << 8) | *c as u64))
    }

    /// A string: definite, or indefinite as definite chunks of its own major type.
    fn string(&mut self, major: u8, ai: u8) -> Result<Vec<u8>, String> {
        let text = major == 3;
        let check = |chunk: &[u8], at: usize| -> Result<(), String> {
            if text && std::str::from_utf8(chunk).is_err() {
                return Err(format!("a text string at byte {} is not valid UTF-8", at));
            }
            Ok(())
        };
        if ai != 31 {
            let at = self.at;
            let n = self.arg(ai)?;
            let s = self.take(n)?;
            check(s, at)?;
            return Ok(s.to_vec());
        }
        let mut out = Vec::new();
        loop {
            let at = self.at;
            let ib = self.byte()?;
            if ib == 0xff {
                return Ok(out);
            }
            if ib >> 5 != major || ib & 0x1f == 31 {
                return Err(format!("a chunk at byte {} is not a definite string of its string's type", at));
            }
            let n = self.arg(ib & 0x1f)?;
            let s = self.take(n)?;
            check(s, at)?;
            out.extend_from_slice(s);
        }
    }

    fn item(&mut self, depth: usize) -> Result<Node, String> {
        let start = self.at;
        let ib = self.byte()?;
        let (major, ai) = (ib >> 5, ib & 0x1f);
        if (28..=30).contains(&ai) {
            return Err(format!("additional information {} at byte {}", ai, start));
        }
        let deep = || Err(format!("the item at byte {} lies deeper than {} levels", start, MAX_DEPTH));
        let v = match major {
            0 | 1 if ai == 31 => return Err(format!("an integer with indefinite length at byte {}", start)),
            0 => V::Uint(self.arg(ai)?),
            1 => V::Nint(self.arg(ai)?),
            2 => V::Bytes(self.string(2, ai)?),
            3 => V::Text(String::from_utf8(self.string(3, ai)?).map_err(|_| format!("invalid UTF-8 at byte {}", start))?),
            4 => {
                if depth > MAX_DEPTH {
                    return deep();
                }
                let mut items = Vec::new();
                if ai == 31 {
                    while self.peek()? != 0xff {
                        items.push(self.item(depth + 1)?);
                    }
                    self.at += 1;
                } else {
                    let n = self.arg(ai)?;
                    // every item takes at least one byte
                    if n > self.left() {
                        return Err(format!("an array of {} items at byte {} is longer than the bytes left", n, start));
                    }
                    items.reserve(n as usize);
                    for _ in 0..n {
                        items.push(self.item(depth + 1)?);
                    }
                }
                V::Array(items)
            }
            5 => {
                if depth > MAX_DEPTH {
                    return deep();
                }
                let mut members = Vec::new();
                if ai == 31 {
                    while self.peek()? != 0xff {
                        let k = self.item(depth + 1)?;
                        // a break in a value's place is not well formed
                        let v = self.item(depth + 1)?;
                        members.push((k, v));
                    }
                    self.at += 1;
                } else {
                    let n = self.arg(ai)?;
                    // every member takes at least two bytes
                    if n > self.left() / 2 {
                        return Err(format!("a map of {} members at byte {} is longer than the bytes left", n, start));
                    }
                    members.reserve(n as usize);
                    for _ in 0..n {
                        let k = self.item(depth + 1)?;
                        let v = self.item(depth + 1)?;
                        members.push((k, v));
                    }
                }
                // step 4: two equal keys
                let mut seen: HashSet<Vec<u8>> = HashSet::with_capacity(members.len());
                for (k, _) in &members {
                    let mut e = Vec::new();
                    encode_det(k, &mut e);
                    if !seen.insert(e) {
                        return Err(format!("the map at byte {} holds two equal keys (the key at byte {})", start, k.start));
                    }
                }
                V::Map(members)
            }
            6 => {
                if ai == 31 {
                    return Err(format!("a tag with indefinite length at byte {}", start));
                }
                if depth > MAX_DEPTH {
                    return deep();
                }
                let t = self.arg(ai)?;
                V::Tag(t, Box::new(self.item(depth + 1)?))
            }
            _ => match ai {
                0..=23 => V::Simple(ai),
                24 => {
                    let s = self.byte()?;
                    if s < 32 {
                        return Err(format!("a simple value below 32 in two bytes at byte {}", start));
                    }
                    V::Simple(s)
                }
                25 => {
                    let h = self.take(2)?;
                    V::Float(half_to_f64_bits(u16::from_be_bytes([h[0], h[1]])))
                }
                26 => {
                    let s = self.take(4)?;
                    V::Float(single_to_f64_bits(u32::from_be_bytes([s[0], s[1], s[2], s[3]])))
                }
                27 => {
                    let d = self.take(8)?;
                    let mut a = [0u8; 8];
                    a.copy_from_slice(d);
                    V::Float(u64::from_be_bytes(a))
                }
                _ => return Err(format!("a break at byte {} outside an item of indefinite length", start)),
            },
        };
        Ok(Node { start, end: self.at, v })
    }
}

/// The input: exactly one well-formed data item.
pub(crate) fn parse(b: &[u8]) -> Result<Node, String> {
    if b.is_empty() {
        return Err("the input is empty".into());
    }
    let mut r = Reader { b, at: 0 };
    let n = r.item(1)?;
    if r.at != b.len() {
        return Err(format!("{} bytes after the data item", b.len() - r.at));
    }
    Ok(n)
}

/// 2^k for k in the range of a normal double.
fn pow2(k: i32) -> f64 {
    f64::from_bits(((1023 + k) as u64) << 52)
}

fn half_to_f64_bits(h: u16) -> u64 {
    let sign = (h >> 15) as u64;
    let e = ((h >> 10) & 0x1f) as i32;
    let m = (h & 0x3ff) as u64;
    if e == 0x1f {
        // an infinity, or a NaN with its payload
        return sign << 63 | 0x7ff << 52 | m << 42;
    }
    let mag = if e == 0 { m as f64 * pow2(-24) } else { (1024 + m) as f64 * pow2(e - 25) };
    (if sign == 1 { -mag } else { mag }).to_bits()
}

fn single_to_f64_bits(s: u32) -> u64 {
    if s & 0x7f80_0000 == 0x7f80_0000 && s & 0x007f_ffff != 0 {
        return ((s >> 31) as u64) << 63 | 0x7ff << 52 | ((s & 0x007f_ffff) as u64) << 29;
    }
    (f32::from_bits(s) as f64).to_bits()
}

// ---------------------------------------------------------------------------
// The core deterministic encoding
// ---------------------------------------------------------------------------

/// A head in its shortest form.
fn head(major: u8, n: u64, out: &mut Vec<u8>) {
    let m = major << 5;
    if n < 24 {
        out.push(m | n as u8);
    } else if n <= 0xff {
        out.extend_from_slice(&[m | 24, n as u8]);
    } else if n <= 0xffff {
        out.push(m | 25);
        out.extend_from_slice(&(n as u16).to_be_bytes());
    } else if n <= 0xffff_ffff {
        out.push(m | 26);
        out.extend_from_slice(&(n as u32).to_be_bytes());
    } else {
        out.push(m | 27);
        out.extend_from_slice(&n.to_be_bytes());
    }
}

/// An integer from -2^64 to 2^64-1: major type 0 when 0 or more, else 1.
fn int(v: i128, out: &mut Vec<u8>) {
    if v >= 0 {
        head(0, v as u64, out)
    } else {
        head(1, (-1 - v) as u64, out)
    }
}

fn text(s: &str, out: &mut Vec<u8>) {
    head(3, s.len() as u64, out);
    out.extend_from_slice(s.as_bytes());
}

/// A double, at the shortest of half, single and double that holds it
/// exactly (RFC 8949 4.2.2), subnormal halves and NaN payloads included.
fn float(bits: u64, out: &mut Vec<u8>) {
    let x = f64::from_bits(bits);
    if x.is_nan() {
        let sign = bits >> 63;
        let m = bits & ((1 << 52) - 1);
        if m & ((1 << 42) - 1) == 0 {
            out.push(0xf9);
            out.extend_from_slice(&((sign << 15 | 0x7c00 | m >> 42) as u16).to_be_bytes());
        } else if m & ((1 << 29) - 1) == 0 {
            out.push(0xfa);
            out.extend_from_slice(&((sign << 31 | 0x7f80_0000 | m >> 29) as u32).to_be_bytes());
        } else {
            out.push(0xfb);
            out.extend_from_slice(&bits.to_be_bytes());
        }
        return;
    }
    let s = x as f32;
    if (s as f64).to_bits() != bits {
        out.push(0xfb);
        out.extend_from_slice(&bits.to_be_bytes());
        return;
    }
    match half_exact(s) {
        Some(h) => {
            out.push(0xf9);
            out.extend_from_slice(&h.to_be_bytes());
        }
        None => {
            out.push(0xfa);
            out.extend_from_slice(&s.to_bits().to_be_bytes());
        }
    }
}

/// A single that is not a NaN, as a half when a half holds it exactly.
fn half_exact(s: f32) -> Option<u16> {
    let b = s.to_bits();
    let sign = ((b >> 31) as u16) << 15;
    let exp = ((b >> 23) & 0xff) as i32;
    let mant = b & 0x7f_ffff;
    if exp == 0xff {
        return Some(sign | 0x7c00);
    }
    if exp == 0 {
        // zero; a single subnormal is below every half
        return if mant == 0 { Some(sign) } else { None };
    }
    let e = exp - 127;
    if (-14..=15).contains(&e) {
        if mant & 0x1fff != 0 {
            return None;
        }
        return Some(sign | ((e + 15) as u16) << 10 | (mant >> 13) as u16);
    }
    if (-24..=-15).contains(&e) {
        let full = (1u32 << 23) | mant;
        let shift = (-(e + 1)) as u32;
        if full & ((1 << shift) - 1) != 0 {
            return None;
        }
        return Some(sign | (full >> shift) as u16);
    }
    None
}

/// A data item in the core deterministic encoding (RFC 8949 4.2.1): heads in
/// their shortest form, floats at the shortest width, definite lengths, map
/// members sorted by the bytewise order of their encoded keys.
fn encode_det(n: &Node, out: &mut Vec<u8>) {
    match &n.v {
        V::Uint(u) => head(0, *u, out),
        V::Nint(u) => head(1, *u, out),
        V::Bytes(b) => {
            head(2, b.len() as u64, out);
            out.extend_from_slice(b);
        }
        V::Text(s) => text(s, out),
        V::Array(a) => {
            head(4, a.len() as u64, out);
            for i in a {
                encode_det(i, out);
            }
        }
        V::Map(m) => {
            let mut members: Vec<(Vec<u8>, Vec<u8>)> = m
                .iter()
                .map(|(k, v)| {
                    let (mut kb, mut vb) = (Vec::new(), Vec::new());
                    encode_det(k, &mut kb);
                    encode_det(v, &mut vb);
                    (kb, vb)
                })
                .collect();
            members.sort();
            head(5, members.len() as u64, out);
            for (k, v) in members {
                out.extend_from_slice(&k);
                out.extend_from_slice(&v);
            }
        }
        V::Tag(t, inner) => {
            head(6, *t, out);
            encode_det(inner, out);
        }
        V::Simple(s) if *s < 24 => out.push(0xe0 | s),
        V::Simple(s) => out.extend_from_slice(&[0xf8, *s]),
        V::Float(bits) => float(*bits, out),
    }
}

// ---------------------------------------------------------------------------
// Decode
// ---------------------------------------------------------------------------

fn malformed(p: &Pack, why: impl AsRef<str>) -> Error {
    Error { msg: format!("malformed-wire: format `{}`: {}", p.format, why.as_ref()) }
}

/// The item with every tag on it passed over.
fn untag(mut n: &Node) -> &Node {
    while let V::Tag(_, inner) = &n.v {
        n = inner;
    }
    n
}

/// `null` (simple value 22) and `undefined` (23).
fn is_absent(n: &Node) -> bool {
    matches!(untag(n).v, V::Simple(22) | V::Simple(23))
}

/// The step a map key is addressed by; None for a key that is not
/// addressable (another type, a tag, a text the grammar cannot write, an
/// integer below -2^63).
fn key_step(k: &Node) -> Option<Step> {
    match &k.v {
        V::Uint(n) => Some(Step::Int(*n as i128)),
        V::Nint(n) => Some(-1 - *n as i128).filter(|v| *v >= MIN_INT).map(Step::Int),
        V::Text(s) if text_writable(s) => Some(Step::Text(s.clone())),
        _ => None,
    }
}

fn key_matches(k: &Node, step: &Step) -> bool {
    match (&k.v, step) {
        (V::Uint(n), Step::Int(i)) => *n as i128 == *i,
        (V::Nint(n), Step::Int(i)) => -1 - *n as i128 == *i,
        (V::Text(s), Step::Text(t)) => s == t,
        _ => false,
    }
}

/// The item a path names under `node`: None when a step finds nothing. Err:
/// an item on the way exists and is not a map or array of the type its next
/// step needs.
fn resolve<'a>(node: &'a Node, path: &[Step]) -> Result<Option<&'a Node>, String> {
    let mut cur = node;
    for (i, s) in path.iter().enumerate() {
        let c = untag(cur);
        // ruling 12 of 0.28: `null` or `undefined` partway down a path makes
        // the line's item absent
        if matches!(c.v, V::Simple(22) | V::Simple(23)) {
            return Ok(None);
        }
        let next = match (&c.v, s) {
            (V::Map(m), Step::Int(_) | Step::Text(_)) => m.iter().find(|(k, _)| key_matches(k, s)).map(|(_, v)| v),
            (V::Array(a), Step::Pos(i)) => a.get(*i),
            _ => {
                return Err(format!(
                    "the item at `{}` is not {}, which the step `{}` needs",
                    path_text(&path[..i]),
                    kind(s.is_pos()),
                    s.text()
                ))
            }
        };
        match next {
            Some(n) => cur = n,
            None => return Ok(None),
        }
    }
    Ok(Some(cur))
}

fn when_holds(top: &Node, w: &WhenDef) -> bool {
    let n = match resolve(top, &path(&w.locator)) {
        Ok(Some(n)) => untag(n),
        _ => return false,
    };
    if w.present {
        return !is_absent(n);
    }
    match (when_value(&w.value), &n.v) {
        (WhenValue::Int(i), V::Uint(u)) => *u as i128 == i,
        (WhenValue::Int(i), V::Nint(u)) => -1 - *u as i128 == i,
        (WhenValue::Bool(b), V::Simple(20)) => !b,
        (WhenValue::Bool(b), V::Simple(21)) => b,
        (WhenValue::Text(t), V::Text(s)) => *s == t,
        _ => false,
    }
}

/// An item (tags passed over, not `null` or `undefined`) -> model value.
fn decode_value(t: &Transform, n: &Node) -> Result<Value, Error> {
    let i64_of = |v: i128| -> Result<Value, Error> {
        i64::try_from(v).map(Value::I64).or_else(|_| err(format!("{} is outside the signed 64-bit range", v)))
    };
    match (t, &n.v) {
        (Transform::Uint | Transform::Int, V::Uint(u)) => i64_of(*u as i128),
        (Transform::Int, V::Nint(u)) => i64_of(-1 - *u as i128),
        (Transform::Float, V::Float(bits)) => finite(f64::from_bits(*bits)),
        // the nearest double, ties to even
        (Transform::Float, V::Uint(u)) => Ok(Value::F64(*u as f64)),
        (Transform::Float, V::Nint(u)) => Ok(Value::F64(-((*u as u128 + 1) as f64))),
        (Transform::CborText, V::Text(s)) => Ok(Value::Str(s.clone())),
        (Transform::CborBytes, V::Bytes(b)) => Ok(Value::Str(bits::to_hex(b))),
        (Transform::Bool, V::Simple(20)) => Ok(Value::I64(0)),
        (Transform::Bool, V::Simple(21)) => Ok(Value::I64(1)),
        (Transform::EpochS, V::Uint(u)) => i64_of(*u as i128 * 1000),
        (Transform::EpochS, V::Nint(u)) => i64_of((-1 - *u as i128) * 1000),
        _ => err(format!("the item at byte {} is of another type than the transform takes", n.start)),
    }
}

/// Decode the fields and groups of one scope: the top item, or one element
/// of a group. `node` has its tags passed over.
fn decode_scope(p: &Pack, sel: &Sel, node: &Node, d: &mut Decoded) -> Result<(), Error> {
    for f in &sel.fields {
        let found = if f.locator == "." { Some(node) } else { resolve(node, &path(&f.locator)).map_err(|m| malformed(p, m))? };
        match found {
            None => {}
            Some(n) if is_absent(n) => {}
            Some(n) => d.put(p, f, decode_value(&f.transform, untag(n))),
        }
    }
    // step 8 holds for every line of the scope, `const` included
    for c in &sel.consts {
        resolve(node, &path(&c.locator)).map_err(|m| malformed(p, m))?;
    }
    for g in &sel.groups {
        let at = resolve(node, &path(&g.locator)).map_err(|m| malformed(p, m))?;
        let elements = match at.map(untag) {
            None => continue,
            Some(n) if is_absent(n) => continue,
            Some(Node { v: V::Array(a), .. }) => a,
            Some(_) => return Err(malformed(p, format!("the item at `{}` of list `{}` is not an array", g.locator, g.list))),
        };
        let body = g.body();
        let shape = body_shape(g);
        d.replacing(&g.list);
        let mut items = Vec::new();
        for e in elements {
            limit::take(&p.format, &g.list, 1)?;
            let mut di = Decoded::new();
            let e = untag(e);
            // an element of the wrong type for the body is an item with no keys
            let fits = match shape {
                Shape::Map => matches!(e.v, V::Map(_)),
                Shape::Array => matches!(e.v, V::Array(_)),
                Shape::Scalar | Shape::Any => true,
            };
            if fits {
                decode_scope(p, &body, e, &mut di)?;
            }
            items.push(di);
        }
        d.put_list(&g.list, items);
    }
    Ok(())
}

/// The places the lines of the selected scope name, as a tree.
#[derive(Default)]
struct Names {
    kids: HashMap<Step, Names>,
    /// a line maps the item
    mapped: bool,
}

impl Names {
    /// A line at `path`: every item before the last is walked into; the last
    /// is mapped, except by `when … present` (ruling 27 of 0.5).
    fn add(&mut self, path: &[Step], maps: bool) {
        let (last, prefix) = match path.split_last() {
            Some(x) => x,
            None => {
                self.mapped |= maps;
                return;
            }
        };
        let mut node = self;
        for s in prefix {
            node = node.kids.entry(s.clone()).or_default();
        }
        if maps {
            node.kids.entry(last.clone()).or_default().mapped = true;
        }
    }
}

fn join(prefix: &str, step: &str) -> String {
    if prefix.is_empty() {
        step.to_string()
    } else {
        format!("{}.{}", prefix, step)
    }
}

/// The residue of a container a line walks into: every member or element no
/// line maps or walks into, with the hex of its item as it stood in the input.
fn residue(b: &[u8], node: &Node, names: &Names, prefix: &str, out: &mut Vec<(String, String)>) {
    let one = |step: Option<Step>, key: Option<&Node>, v: &Node, out: &mut Vec<(String, String)>| {
        let hex = |n: &Node| bits::to_hex(&b[n.start..n.end]);
        let step = match step {
            Some(s) => s,
            None => {
                let k = key.map(hex).unwrap_or_default();
                out.push((join(prefix, &format!("#{}", k)), hex(v)));
                return;
            }
        };
        let at = join(prefix, &step.text());
        match names.kids.get(&step) {
            Some(n) if n.mapped => {}
            Some(n) if !n.kids.is_empty() => residue(b, untag(v), n, &at, out),
            _ => out.push((at, hex(v))),
        }
    };
    match &node.v {
        V::Map(m) => {
            for (k, v) in m {
                one(key_step(k), Some(k), v, out);
            }
        }
        V::Array(a) => {
            for (i, v) in a.iter().enumerate() {
                one(Some(Step::Pos(i)), None, v, out);
            }
        }
        _ => {}
    }
}

pub fn decode(p: &Pack, input: &str) -> Result<Entity, Error> {
    let _scope = limit::scope();
    let b = bits::from_hex(input).map_err(|e| malformed(p, e.msg.trim_start_matches("malformed-wire: ")))?;
    let root = parse(&b).map_err(|m| malformed(p, m))?;
    let top = match p.cbor.tag {
        Some(n) => match &root.v {
            V::Tag(t, inner) if *t == n => &**inner,
            _ => return Err(malformed(p, format!("the input is not enclosed in tag {}", n))),
        },
        None => &root,
    };
    let top = untag(top);
    // step 6: the type the paths decide
    let fits = if p.cbor.top_array { matches!(top.v, V::Array(_)) } else { matches!(top.v, V::Map(_)) };
    if !fits {
        return Err(malformed(p, format!("the top item is not {}", kind(p.cbor.top_array))));
    }
    let sel = p.select_decode(None, |w| when_holds(top, w))?;
    let mut d = Decoded::new();
    decode_scope(p, &sel, top, &mut d)?;
    let mut names = Names::default();
    for f in &sel.fields {
        names.add(&path(&f.locator), true);
    }
    for w in sel.whens.iter().chain(sel.consts.iter()) {
        names.add(&path(&w.locator), !w.present);
    }
    for g in &sel.groups {
        names.add(&path(&g.locator), true);
    }
    if !names.mapped {
        let mut res = Vec::new();
        residue(&b, top, &names, "", &mut res);
        d.ent.residue.extend(res.into_iter().map(|(k, v)| (p.format.clone(), k, v)));
    }
    d.finish(p, &sel)
}

// ---------------------------------------------------------------------------
// Encode
// ---------------------------------------------------------------------------

/// One step of a place being written: an encoded map key, or a position.
#[derive(Clone, Debug)]
enum Place {
    Key(Vec<u8>),
    Pos(usize),
}

fn places(path: &[Step]) -> Vec<Place> {
    path.iter()
        .map(|s| match s {
            Step::Int(i) => {
                let mut k = Vec::new();
                int(*i, &mut k);
                Place::Key(k)
            }
            Step::Text(t) => {
                let mut k = Vec::new();
                text(t, &mut k);
                Place::Key(k)
            }
            Step::Pos(i) => Place::Pos(*i),
        })
        .collect()
}

/// An item being written.
enum Out {
    /// an encoded item
    Val(Vec<u8>),
    /// members by encoded key, so in the bytewise order of their keys
    Map(BTreeMap<Vec<u8>, Out>),
    Arr(BTreeMap<usize, Out>),
}

impl Out {
    fn container(next: &Place) -> Out {
        match next {
            Place::Key(_) => Out::Map(BTreeMap::new()),
            Place::Pos(_) => Out::Arr(BTreeMap::new()),
        }
    }
}

/// Write `val` at `path` under `cur`. Ok(false): a value is already there
/// (the earlier line stands). Err: the place is both a value and a map or
/// array, or a map and an array.
fn put(cur: &mut Out, path: &[Place], val: Vec<u8>) -> Result<bool, ()> {
    let (first, rest) = match path.split_first() {
        Some(x) => x,
        None => return Err(()),
    };
    let slot: &mut Out = match (cur, first) {
        (Out::Map(m), Place::Key(k)) => {
            if rest.is_empty() {
                // ruling 31 of 0.28: a container the lines walk into but
                // leave empty takes a value (residue) whole
                return match m.get(k) {
                    Some(Out::Val(_)) => Ok(false),
                    Some(o) if !empty(o) => Err(()),
                    _ => {
                        m.insert(k.clone(), Out::Val(val));
                        Ok(true)
                    }
                };
            }
            m.entry(k.clone()).or_insert_with(|| Out::container(&rest[0]))
        }
        (Out::Arr(a), Place::Pos(i)) => {
            if rest.is_empty() {
                // ruling 31 of 0.28: a container the lines walk into but
                // leave empty takes a value (residue) whole
                return match a.get(i) {
                    Some(Out::Val(_)) => Ok(false),
                    Some(o) if !empty(o) => Err(()),
                    _ => {
                        a.insert(*i, Out::Val(val));
                        Ok(true)
                    }
                };
            }
            a.entry(*i).or_insert_with(|| Out::container(&rest[0]))
        }
        _ => return Err(()),
    };
    put(slot, rest, val)
}

/// A map or array with no value anywhere in it.
fn empty(o: &Out) -> bool {
    match o {
        Out::Val(_) => false,
        Out::Map(m) => m.values().all(empty),
        Out::Arr(a) => a.values().all(empty),
    }
}

/// The containers on the way to the last step of `path`, created empty
/// where they are missing. A place already taken otherwise is left alone.
fn skeleton(cur: &mut Out, path: &[Place]) {
    if path.len() < 2 {
        return;
    }
    let next = &path[1];
    let slot = match (cur, &path[0]) {
        (Out::Map(m), Place::Key(k)) => m.entry(k.clone()).or_insert_with(|| Out::container(next)),
        (Out::Arr(a), Place::Pos(i)) => a.entry(*i).or_insert_with(|| Out::container(next)),
        _ => return,
    };
    skeleton(slot, &path[1..]);
}

/// The bytes of an item; None for a map or array with nothing in it.
fn emit(o: &Out) -> Option<Vec<u8>> {
    match o {
        Out::Val(v) => Some(v.clone()),
        Out::Map(m) => {
            let members: Vec<(&Vec<u8>, Vec<u8>)> = m.iter().filter_map(|(k, v)| emit(v).map(|b| (k, b))).collect();
            if members.is_empty() {
                return None;
            }
            let mut out = Vec::new();
            head(5, members.len() as u64, &mut out);
            for (k, v) in members {
                out.extend_from_slice(k);
                out.extend_from_slice(&v);
            }
            Some(out)
        }
        Out::Arr(a) => {
            let items: BTreeMap<usize, Vec<u8>> = a.iter().filter_map(|(i, v)| emit(v).map(|b| (*i, b))).collect();
            // written up to its highest present position; a hole is `null`
            let hi = *items.keys().next_back()?;
            let mut out = Vec::new();
            head(4, hi as u64 + 1, &mut out);
            for i in 0..=hi {
                match (items.get(&i), a.get(&i)) {
                    (Some(b), _) => out.extend_from_slice(b),
                    // ruling 23 of 0.28: a gap the lines walk into as a map
                    // or an array is that container, empty; else `null`
                    (None, Some(Out::Map(_))) => out.push(0xa0),
                    (None, Some(Out::Arr(_))) => out.push(0x80),
                    (None, _) => out.push(0xf6),
                }
            }
            Some(out)
        }
    }
}

/// A model value -> the encoded item.
fn encode_value(t: &Transform, v: &Value) -> Result<Vec<u8>, Error> {
    let mut out = Vec::new();
    match (t, v) {
        (Transform::Uint, Value::I64(x)) if *x < 0 => return err(format!("{} is negative; `uint` writes major type 0", x)),
        (Transform::Uint | Transform::Int, Value::I64(x)) => int(*x as i128, &mut out),
        (Transform::Float, Value::F64(x)) if !x.is_finite() => return err(format!("{} is not a finite number", x)),
        (Transform::Float, Value::F64(x)) => float(x.to_bits(), &mut out),
        (Transform::CborText, Value::Str(s)) => text(s, &mut out),
        (Transform::CborBytes, Value::Str(s)) => {
            let h = s.as_bytes();
            if h.len() % 2 != 0 || !h.iter().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(c)) {
                return err(format!("`{}` is not an even number of lowercase hex digits", s));
            }
            let nib = |c: u8| if c.is_ascii_digit() { c - b'0' } else { c - b'a' + 10 };
            head(2, (h.len() / 2) as u64, &mut out);
            out.extend(h.chunks(2).map(|d| nib(d[0]) << 4 | nib(d[1])));
        }
        (Transform::Bool, Value::I64(1)) => out.push(0xf5),
        (Transform::Bool, Value::I64(0)) => out.push(0xf4),
        (Transform::Bool, other) => return err(format!("bool encodes 1 or 0, got {}", other.as_display())),
        (Transform::EpochS, Value::I64(ms)) => {
            // divided by 1000 exactly, rounded half away from zero
            let (q, r) = (*ms / 1000, *ms % 1000);
            let s = if r >= 500 {
                q + 1
            } else if r <= -500 {
                q - 1
            } else {
                q
            };
            int(s as i128, &mut out)
        }
        _ => return err(format!("transform/value mismatch on cbor: {:?} with {:?}", t, v)),
    }
    Ok(out)
}

/// The item a `when` value or a `const` writes, with its type.
fn fixed_value(w: &WhenDef) -> Vec<u8> {
    let mut out = Vec::new();
    match when_value(&w.value) {
        WhenValue::Int(i) => int(i, &mut out),
        WhenValue::Bool(b) => out.push(if b { 0xf5 } else { 0xf4 }),
        WhenValue::Text(t) => text(&t, &mut out),
    }
    out
}

fn conflict(p: &Pack, locator: &str) -> Error {
    Error {
        msg: format!(
            "transform-encode: format `{}`: the place `{}` is written both as a value and as a map or array, or as a map and an array",
            p.format, locator
        ),
    }
}

/// The item one scope writes, before residue: the top item, or one element
/// of a group. A `when` or `const` value stands over a field; of several
/// fields on one path the earliest present one is written (ruling 16 of 0.5).
fn build(p: &Pack, sel: &Sel, ent: &Entity, array: bool) -> Result<Out, Error> {
    let mut root = if array { Out::Arr(BTreeMap::new()) } else { Out::Map(BTreeMap::new()) };
    // every map and array the lines walk into, empty until a value lands in
    // it: an empty one is not written, except as a gap (ruling 23 of 0.28)
    let walked = sel
        .fields
        .iter()
        .map(|f| f.locator.as_str())
        .chain(sel.whens.iter().chain(sel.consts.iter()).map(|w| w.locator.as_str()))
        .chain(sel.groups.iter().map(|g| g.locator.as_str()));
    for loc in walked {
        let path = places(&path(loc));
        if path.len() > 1 {
            skeleton(&mut root, &path);
        }
    }
    let mut fixed: Vec<&WhenDef> = sel.fixed().collect();
    fixed.sort_by_key(|w| w.line);
    for w in fixed {
        put(&mut root, &places(&path(&w.locator)), fixed_value(w)).map_err(|_| conflict(p, &w.locator))?;
    }
    let mut fields: Vec<&&FieldDef> = sel.fields.iter().filter(|f| f.locator != ".").collect();
    fields.sort_by_key(|f| f.line);
    // ruling 29 of 0.28: a field at a path a `when` value or `const` names
    // is not encoded, so its value is never converted
    let fixed_paths: Vec<Vec<Step>> = sel.fixed().map(|w| path(&w.locator)).collect();
    for f in fields {
        if fixed_paths.contains(&path(&f.locator)) {
            continue;
        }
        if let Some(v) = sel.value_of(ent, f) {
            let bytes = p.to_wire(f, v).and_then(|w| encode_value(&f.transform, &w)).map_err(|e| transform_encode_err(p, f, e))?;
            put(&mut root, &places(&path(&f.locator)), bytes).map_err(|_| conflict(p, &f.locator))?;
        }
    }
    let mut groups: Vec<&&GroupDef> = sel.groups.iter().collect();
    groups.sort_by_key(|g| g.line);
    for g in groups {
        let items = match ent.lists.get(&g.list) {
            Some(items) => items,
            None => continue,
        };
        let bytes = list(p, g, items)?;
        if g.locator == "." {
            root = Out::Val(bytes);
        } else {
            put(&mut root, &places(&path(&g.locator)), bytes).map_err(|_| conflict(p, &g.locator))?;
        }
    }
    Ok(root)
}

/// A present list: its array, one element per item in list order.
fn list(p: &Pack, g: &GroupDef, items: &[Entity]) -> Result<Vec<u8>, Error> {
    let body = g.body();
    let shape = body_shape(g);
    let mut out = Vec::new();
    head(4, items.len() as u64, &mut out);
    for item in items {
        // a `.` line with a value: the element is that scalar
        let scalar = body.fields.iter().filter(|f| f.locator == ".").find_map(|f| body.value_of(item, f).map(|v| (f, v)));
        if let Some((f, v)) = scalar {
            let bytes = p.to_wire(f, v).and_then(|w| encode_value(&f.transform, &w)).map_err(|e| transform_encode_err(p, f, e))?;
            out.extend_from_slice(&bytes);
            continue;
        }
        let tree = build(p, &body, item, shape == Shape::Array)?;
        match emit(&tree) {
            Some(b) => out.extend_from_slice(&b),
            // an item with nothing written
            None => out.push(match shape {
                Shape::Array => 0x80,
                Shape::Scalar => 0xf6,
                Shape::Map | Shape::Any => 0xa0,
            }),
        }
    }
    Ok(out)
}

/// A residue key: a path, the last step of which may be `#<hex>`, the hex of
/// a key that is not addressable. None when it is neither.
fn residue_places(key: &str) -> Option<Vec<Place>> {
    let steps: Vec<&str> = key.split('.').collect();
    let mut out = Vec::with_capacity(steps.len());
    for (i, s) in steps.iter().enumerate() {
        match s.strip_prefix('#') {
            Some(h) if i + 1 == steps.len() => {
                let item = parse(&bits::from_hex(h).ok()?).ok()?;
                let mut k = Vec::new();
                encode_det(&item, &mut k);
                out.push(Place::Key(k));
            }
            Some(_) => return None,
            None => out.extend(places(&[parse_step(s).ok()?])),
        }
    }
    Some(out)
}

pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
    let sel = p.select_encode(ent)?;
    let mut root = build(p, &sel, ent, p.cbor.top_array)?;
    // residue goes back into its map or array, re-encoded, where no line writes
    for (fmt, key, value) in &ent.residue {
        if fmt != &p.format {
            continue;
        }
        let path = match residue_places(key) {
            Some(path) if !path.is_empty() => path,
            _ => continue,
        };
        let item = match bits::from_hex(value).ok().and_then(|b| parse(&b).ok()) {
            Some(item) => item,
            None => continue,
        };
        let mut bytes = Vec::new();
        encode_det(&item, &mut bytes);
        let _ = put(&mut root, &path, bytes);
    }
    let item = emit(&root).unwrap_or_else(|| vec![if p.cbor.top_array { 0x80 } else { 0xa0 }]);
    let mut out = Vec::with_capacity(item.len() + 9);
    if let Some(t) = p.cbor.tag {
        head(6, t, &mut out);
    }
    out.extend_from_slice(&item);
    Ok(bits::to_hex(&out))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn det(hex: &str) -> String {
        let b = bits::from_hex(hex).unwrap();
        let n = parse(&b).unwrap();
        let mut out = Vec::new();
        encode_det(&n, &mut out);
        bits::to_hex(&out)
    }

    #[test]
    fn floats_take_the_shortest_width() {
        let f = |x: f64| {
            let mut o = Vec::new();
            float(x.to_bits(), &mut o);
            bits::to_hex(&o)
        };
        assert_eq!(f(pow2(-24)), "f90001");
        assert_eq!(f(-0.0), "f98000");
        assert_eq!(f(0.0), "f90000");
        assert_eq!(f(1.5), "f93e00");
        assert_eq!(f(100000.0), "fa47c35000");
        assert_eq!(f(65504.0), "f97bff");
        assert_eq!(f(1.1), "fb3ff199999999999a");
        assert_eq!(f(pow2(-14)), "f90400");
        assert_eq!(f(pow2(-25)), "fa33000000");
        assert_eq!(f(f64::INFINITY), "f97c00");
        assert_eq!(f(f64::NAN), "f97e00");
    }

    #[test]
    fn deterministic_encoding_of_items() {
        // RFC 8949 4.2.1: shortest heads, definite lengths, keys in bytewise order
        assert_eq!(det("1b0000000000000001"), "01");
        assert_eq!(det("9f0102ff"), "820102");
        assert_eq!(det("7f6161626262ff"), "63616262");
        assert_eq!(det("a3616101200a0102"), "a30102200a616101");
        assert_eq!(det("fa3fc00000"), "f93e00");
        assert_eq!(det("fb3ff8000000000000"), "f93e00");
    }

    #[test]
    fn paths() {
        assert_eq!(parse_path("4").unwrap(), vec![Step::Int(4)]);
        assert_eq!(parse_path("-1.[0].a_b-c").unwrap(), vec![Step::Int(-1), Step::Pos(0), Step::Text("a_b-c".into())]);
        assert_eq!(parse_path("18446744073709551615").unwrap(), vec![Step::Int(u64::MAX as i128)]);
        assert_eq!(parse_path("-9223372036854775808").unwrap(), vec![Step::Int(MIN_INT)]);
        for bad in ["", "a..b", "a[0]", "[01]", "-0", "+1", "01", "18446744073709551616", "-9223372036854775809", "[65536]", "a b", "4a", "-a", "a.", "é"] {
            assert!(parse_path(bad).is_err(), "{:?} should not be a path", bad);
        }
    }

    #[test]
    fn when_values() {
        assert_eq!(when_value("007"), WhenValue::Int(7));
        assert_eq!(when_value("-0"), WhenValue::Int(0));
        assert_eq!(when_value("18446744073709551615"), WhenValue::Int(u64::MAX as i128));
        assert_eq!(when_value("true"), WhenValue::Bool(true));
        assert_eq!(when_value("=true"), WhenValue::Text("true".into()));
        assert_eq!(when_value("=5"), WhenValue::Text("5".into()));
        assert_eq!(when_value("+1"), WhenValue::Text("+1".into()));
    }
}
