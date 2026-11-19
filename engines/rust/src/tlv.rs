//! The `tlv` wire (engine-spec v0.13): a set of items, each a tag, a length
//! and a value, as in a local set of SMPTE ST 336 and MISB ST 0601. A value
//! may itself be a set. The set may follow a fixed key and a length, and may
//! end with a checksum item. Input and output are hex text.
//!
//! Locators: `<tag>[.<tag>...][:<n>]`, a path of tags into nested sets, and
//! the size of the value in bytes where the transform needs one.

use super::*;

// ---------------------------------------------------------------------------
// Directives
// ---------------------------------------------------------------------------

/// How a tag or a length is written.
#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub enum Enc {
    /// a tag: BER-OID (base 128); a length: BER (short or long form)
    #[default]
    Ber,
    /// an unsigned big-endian integer of 1, 2 or 4 bytes
    Fixed(u8),
}

/// The tlv directives of a pack, as the encoder and decoder use them.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct TlvConf {
    pub tag: Enc,
    pub length: Enc,
    /// `key <hex>`: the bytes the message begins with (empty: no key)
    pub key: Vec<u8>,
    /// `checksum sum16 <tag>`
    pub checksum: Option<u32>,
}

/// The largest tag: 2^28-1, four bytes of BER-OID.
const MAX_TAG: u64 = (1 << 28) - 1;

/// The `tag`, `length`, `key` and `checksum sum16` lines as read, checked
/// once the file is read and the wire is known (ruling 2 of 0.10).
#[derive(Clone, Debug, Default)]
pub(crate) struct TlvLines {
    /// (line, tokens) of `tag`, `length`, `key`, `checksum`
    lines: [Option<(usize, Vec<String>)>; 4],
    /// the first line after a `kind`, or the first repeated line: an error
    /// raised after the file is read, with the other checks of 0.13
    misplaced: Option<usize>,
}

impl TlvLines {
    /// Record one line. A line after the first `kind`, or a second line of
    /// one directive, is `bad-directive` on any wire, once the file is read.
    pub(crate) fn record(&mut self, toks: &[String], ln: usize, after_kind: bool) -> Result<(), Error> {
        let slot = match toks[0].as_str() {
            "tag" => 0,
            "length" => 1,
            "key" => 2,
            _ => 3,
        };
        if after_kind || self.lines[slot].is_some() {
            self.misplaced.get_or_insert(ln);
            return Ok(());
        }
        self.lines[slot] = Some((ln, toks.to_vec()));
        Ok(())
    }

    /// The first line recorded, if any: on a wire other than `tlv` it is `bad-directive`.
    pub(crate) fn first_line(&self) -> Option<usize> {
        self.lines.iter().flatten().map(|(ln, _)| *ln).chain(self.misplaced).min()
    }

    fn conf(&self) -> Result<TlvConf, Error> {
        if let Some(ln) = self.misplaced {
            return bad(ln, "`tag`, `length`, `key` and `checksum sum16` stand once each, before the first `kind`");
        }
        let mut c = TlvConf::default();
        let one = |slot: usize| -> Option<(usize, &[String])> { self.lines[slot].as_ref().map(|(ln, t)| (*ln, t.as_slice())) };
        let size = |v: &str| match v {
            "1" => Some(1u8),
            "2" => Some(2),
            "4" => Some(4),
            _ => None,
        };
        if let Some((ln, t)) = one(0) {
            c.tag = match t {
                [_, v] if v == "ber-oid" => Enc::Ber,
                [_, v] if size(v).is_some() => Enc::Fixed(size(v).unwrap_or(1)),
                _ => return bad(ln, "`tag` is `ber-oid`, `1`, `2` or `4`"),
            };
        }
        if let Some((ln, t)) = one(1) {
            c.length = match t {
                [_, v] if v == "ber" => Enc::Ber,
                [_, v] if size(v).is_some() => Enc::Fixed(size(v).unwrap_or(1)),
                _ => return bad(ln, "`length` is `ber`, `1`, `2` or `4` on the tlv wire"),
            };
        }
        if let Some((ln, t)) = one(2) {
            let v = match t {
                [_, v] => v.as_bytes(),
                _ => return bad(ln, "`key` takes one value"),
            };
            let lower = v.iter().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(b));
            if !lower || v.len() % 2 != 0 || v.is_empty() || v.len() > 128 {
                return bad(ln, "`key` is 1 to 64 bytes as an even number of lowercase hex digits");
            }
            c.key = v.chunks(2).map(|d| (nibble(d[0]) << 4) | nibble(d[1])).collect();
        }
        if let Some((ln, t)) = one(3) {
            c.checksum = match t {
                [_, s, tag] if s == "sum16" => Some(tag_number(tag, c.tag).or_else(|m| bad(ln, m))?),
                _ => return bad(ln, "`checksum` on the tlv wire is `sum16 <tag>`"),
            };
        }
        Ok(c)
    }
}

fn nibble(c: u8) -> u8 {
    match c {
        b'0'..=b'9' => c - b'0',
        b'a'..=b'f' => c - b'a' + 10,
        b'A'..=b'F' => c - b'A' + 10,
        _ => 0,
    }
}

/// A tag as written in a pack: decimal, no leading zero, 0 to 2^28-1, and
/// under a fixed `tag <n>` below 2^(8n).
fn tag_number(s: &str, enc: Enc) -> Result<u32, String> {
    let digits = !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
    if !digits || (s.len() > 1 && s.starts_with('0')) {
        return Err(format!("`{}` is not a tag (a decimal integer with no leading zero)", s));
    }
    let n = match s.parse::<u64>() {
        Ok(n) if n <= MAX_TAG => n,
        _ => return Err(format!("the tag `{}` is above 2^28-1", s)),
    };
    if let Enc::Fixed(b) = enc {
        if b < 4 && n >> (8 * b as u32) != 0 {
            return Err(format!("the tag `{}` does not fit `tag {}`", s, b));
        }
    }
    Ok(n as u32)
}

// ---------------------------------------------------------------------------
// Locators
// ---------------------------------------------------------------------------

/// A locator of the tlv wire: a path of tags and an optional size in bytes.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Loc {
    pub tags: Vec<u32>,
    pub size: Option<u8>,
}

impl Loc {
    /// The syntax of a locator. Tags are checked against `tag <n>` by `check_pack`.
    pub(crate) fn parse(s: &str, enc: Enc) -> Result<Loc, String> {
        let (path, size) = match s.split_once(':') {
            Some((p, n)) => {
                let n = match n.as_bytes() {
                    [c @ b'1'..=b'8'] => c - b'0',
                    _ => return Err(format!("`{}`: a size is 1 to 8 bytes", s)),
                };
                (p, Some(n))
            }
            None => (s, None),
        };
        let tags = path.split('.').map(|t| tag_number(t, enc)).collect::<Result<Vec<u32>, String>>()?;
        Ok(Loc { tags, size })
    }
}

/// The locator of a line already checked at load.
fn loc(p: &Pack, s: &str) -> Option<Loc> {
    Loc::parse(s, p.tlv.tag).ok()
}

// ---------------------------------------------------------------------------
// Load checks
// ---------------------------------------------------------------------------

/// The transforms of the tlv wire, and of no other.
pub(crate) fn tlv_only(t: &Transform) -> bool {
    matches!(t, Transform::Utf8 | Transform::Hex)
}

/// Load checks a `field` transform owes the wire (engine-spec v0.13):
/// on `tlv` only the transforms of its table; `utf8` and `hex` only on `tlv`.
pub(crate) fn check_transform(wire: Wire, f: &FieldDef) -> Result<(), Error> {
    let t = &f.transform;
    let ok_on_tlv = tlv_only(t)
        || matches!(t, Transform::Uint | Transform::Twos | Transform::Uscale(_) | Transform::Sscale(_) | Transform::F32 | Transform::F64);
    match wire {
        Wire::Tlv if !ok_on_tlv => bad(f.line, format!("the transform of `{}` is not valid on the tlv wire", f.model_key)),
        Wire::Tlv => Ok(()),
        _ if tlv_only(t) => bad(f.line, format!("the transform of `{}` is valid only on the tlv wire", f.model_key)),
        _ => Ok(()),
    }
}

/// A `when` or `const` line: its path, `present` without a size, a value
/// with a size it fits (engine-spec v0.13, "`when` and `const`").
pub(crate) fn resolve_when(w: &mut WhenDef) -> Result<(), Error> {
    let l = Loc::parse(&w.locator, Enc::Ber).or_else(|m| bad(w.line, m))?;
    if w.value == "present" {
        if l.size.is_some() {
            return bad(w.line, "`present` takes a path with no size");
        }
        w.present = true;
        return Ok(());
    }
    let n = match l.size {
        Some(n) => n,
        None => return bad(w.line, format!("`{}` needs a size `:<n>` for the value `{}`", w.locator, w.value)),
    };
    if w.value.is_empty() || !w.value.bytes().all(|b| b.is_ascii_digit()) {
        return bad(w.line, format!("the value `{}` is not an unsigned decimal integer", w.value));
    }
    w.num = w.value.parse::<u64>().or_else(|_| bad(w.line, format!("the value `{}` is too large", w.value)))?;
    if n < 8 && w.num >> (8 * n as u32) != 0 {
        return bad(w.line, format!("the value {} does not fit {} bytes", w.num, n));
    }
    Ok(())
}

/// The checks that run once the file is read: the directives, every path
/// against `tag <n>` and the checksum tag, and every size against its
/// transform. Returns the directives.
pub(crate) fn check_pack(
    lines: &TlvLines,
    fields: &[FieldDef],
    whens: &[WhenDef],
    consts: &[WhenDef],
    groups: &[GroupDef],
    kinds: &[KindDef],
) -> Result<TlvConf, Error> {
    let conf = lines.conf()?;
    let path = |line: usize, s: &str| -> Result<Loc, Error> {
        let l = Loc::parse(s, conf.tag).or_else(|m| bad(line, m))?;
        if conf.checksum.is_some() && l.tags.first().copied() == conf.checksum {
            return bad(line, format!("`{}` names the checksum tag", s));
        }
        Ok(l)
    };
    for f in fields.iter().chain(kinds.iter().flat_map(|k| k.fields.iter())) {
        let l = path(f.line, &f.locator)?;
        let ok = match (&f.transform, l.size) {
            (Transform::Uint | Transform::Twos | Transform::Uscale(_) | Transform::Sscale(_), n) => n.is_some(),
            (Transform::F32, n) => n.map_or(true, |n| n == 4),
            (Transform::F64, n) => n.map_or(true, |n| n == 8),
            (_, n) => n.is_none(),
        };
        if !ok {
            return bad(f.line, format!("the size of `{}` does not fit the transform of `{}`", f.locator, f.model_key));
        }
    }
    let fixed = whens.iter().chain(consts).chain(kinds.iter().flat_map(|k| k.whens.iter().chain(k.consts.iter())));
    for w in fixed {
        path(w.line, &w.locator)?;
    }
    if let Some(g) = groups.iter().chain(kinds.iter().flat_map(|k| k.groups.iter())).next() {
        return bad(g.line, "`group` is not valid on the tlv wire in 0.13");
    }
    // ruling 5 of 0.13: a line at a path and another line at a path under it,
    // in one scope (common lines, with each kind's)
    let scope = |ls: Vec<(usize, &str)>| -> Result<(), Error> {
        let paths: Vec<(usize, Vec<u32>)> =
            ls.iter().filter_map(|(ln, s)| Loc::parse(s, conf.tag).ok().map(|l| (*ln, l.tags))).collect();
        let mut values: HashSet<&[u32]> = HashSet::new();
        for (_, p) in &paths {
            values.insert(p.as_slice());
        }
        for (ln, p) in &paths {
            if let Some(k) = (1..p.len()).find(|k| values.contains(&p[..*k])) {
                return bad(*ln, format!("a line at a path under `{}`, which another line takes as a value", join(&p[..k])));
            }
        }
        Ok(())
    };
    let lines_of = |fs: &'_ [FieldDef], ws: &'_ [WhenDef], cs: &'_ [WhenDef]| -> Vec<(usize, String)> {
        fs.iter().map(|f| (f.line, f.locator.clone())).chain(ws.iter().chain(cs).map(|w| (w.line, w.locator.clone()))).collect()
    };
    let common = lines_of(fields, whens, consts);
    if kinds.is_empty() {
        scope(common.iter().map(|(l, s)| (*l, s.as_str())).collect())?;
    }
    for k in kinds {
        let own = lines_of(&k.fields, &k.whens, &k.consts);
        scope(common.iter().chain(own.iter()).map(|(l, s)| (*l, s.as_str())).collect())?;
    }
    Ok(conf)
}

fn join(tags: &[u32]) -> String {
    tags.iter().map(|t| t.to_string()).collect::<Vec<_>>().join(".")
}

// ---------------------------------------------------------------------------
// Reading
// ---------------------------------------------------------------------------

/// One item of a set: its tag, where it starts, and its value `val..end`.
#[derive(Clone, Copy, Debug)]
struct Item {
    tag: u32,
    val: usize,
    end: usize,
}

fn be(b: &[u8]) -> u64 {
    b.iter().fold(0u64, |a, c| (a << 8) | *c as u64)
}

/// A tag at `at`, within `end`: (tag, the offset after it).
fn read_tag(enc: Enc, b: &[u8], at: usize, end: usize) -> Result<(u32, usize), String> {
    match enc {
        Enc::Fixed(n) => {
            let n = n as usize;
            if end - at < n {
                return Err(format!("a tag at byte {} runs past its set", at));
            }
            Ok((be(&b[at..at + n]) as u32, at + n))
        }
        Enc::Ber => {
            let mut v: u32 = 0;
            for k in 0..4 {
                if at + k >= end {
                    return Err(format!("a tag at byte {} runs past its set", at));
                }
                let c = b[at + k];
                if k == 0 && c == 0x80 {
                    return Err(format!("a tag at byte {} begins with 0x80", at));
                }
                v = (v << 7) | (c & 0x7f) as u32;
                if c & 0x80 == 0 {
                    return Ok((v, at + k + 1));
                }
            }
            Err(format!("a tag at byte {} has a fifth byte", at))
        }
    }
}

/// A length at `at`, within `end`: (length, the offset after it).
fn read_len(enc: Enc, b: &[u8], at: usize, end: usize) -> Result<(u64, usize), String> {
    let short = || format!("a length at byte {} runs past its set", at);
    match enc {
        Enc::Fixed(n) => {
            let n = n as usize;
            if end - at < n {
                return Err(short());
            }
            Ok((be(&b[at..at + n]), at + n))
        }
        Enc::Ber => {
            if at >= end {
                return Err(short());
            }
            let c = b[at];
            match c {
                0..=0x7f => Ok((c as u64, at + 1)),
                0x81..=0x88 => {
                    let n = (c - 0x80) as usize;
                    if end - at - 1 < n {
                        return Err(short());
                    }
                    Ok((be(&b[at + 1..at + 1 + n]), at + 1 + n))
                }
                _ => Err(format!("a length at byte {} begins with 0x{:02x}", at, c)),
            }
        }
    }
}

/// The items of the set `start..end`, read whole.
fn read_set(c: &TlvConf, b: &[u8], start: usize, end: usize) -> Result<Vec<Item>, String> {
    let mut out = Vec::new();
    let mut at = start;
    while at < end {
        let (tag, after) = read_tag(c.tag, b, at, end)?;
        let (len, val) = read_len(c.length, b, after, end)?;
        // compared with the bytes left, never added to an offset first
        if len > (end - val) as u64 {
            return Err(format!("the item of tag {} at byte {} runs past its set", tag, at));
        }
        let item_end = val + len as usize;
        out.push(Item { tag, val, end: item_end });
        at = item_end;
    }
    Ok(out)
}

fn malformed(p: &Pack, why: impl AsRef<str>) -> Error {
    Error { msg: format!("malformed-wire: format `{}`: {}", p.format, why.as_ref()) }
}

/// The value `val..end` of the first item at `path`, or None when it is not
/// in its set. Err: a set on the way is not well formed.
fn find(c: &TlvConf, b: &[u8], top: &[Item], path: &[u32]) -> Result<Option<(usize, usize)>, String> {
    let mut inner: Vec<Item>;
    let mut items: &[Item] = top;
    for (k, t) in path.iter().enumerate() {
        let it = match items.iter().find(|i| i.tag == *t) {
            Some(i) => *i,
            None => return Ok(None),
        };
        if k + 1 == path.len() {
            return Ok(Some((it.val, it.end)));
        }
        inner = read_set(c, b, it.val, it.end)?;
        items = &inner;
    }
    Ok(None)
}

/// The tags the lines of a scope name, as a tree: a tag a line names or
/// walks into, and under it the tags named in its value read as a set.
#[derive(Default)]
struct Names {
    tags: HashMap<u32, Names>,
    /// a line walks into the value as a set
    walked: bool,
}

impl Names {
    fn add(&mut self, tags: &[u32], present: bool) {
        let (last, prefix) = match tags.split_last() {
            Some(x) => x,
            None => return,
        };
        let mut node = self;
        for t in prefix {
            node = node.tags.entry(*t).or_default();
            node.walked = true;
        }
        // `when … present` does not name its path (ruling 27 of 0.5)
        if !present {
            node.tags.entry(*last).or_default();
        }
    }
}

/// Residue of one set: every item whose tag no line names there, every
/// occurrence, in input order; the first item of a tag that a line walks
/// into is read as a set and its residue taken in turn.
fn residue(c: &TlvConf, b: &[u8], items: &[Item], names: &Names, prefix: &str, out: &mut Vec<(String, String)>) -> Result<(), String> {
    let mut seen: HashSet<u32> = HashSet::new();
    for it in items {
        let path = format!("{}{}", prefix, it.tag);
        match names.tags.get(&it.tag) {
            None => out.push((path, bits::to_hex(&b[it.val..it.end]))),
            // a later occurrence of a named tag is neither mapped nor residue
            Some(_) if !seen.insert(it.tag) => {}
            Some(node) if node.walked => {
                let inner = read_set(c, b, it.val, it.end)?;
                residue(c, b, &inner, node, &format!("{}.", path), out)?;
            }
            Some(_) => {}
        }
    }
    Ok(())
}

fn when_holds(p: &Pack, b: &[u8], top: &[Item], w: &WhenDef) -> bool {
    let l = match loc(p, &w.locator) {
        Some(l) => l,
        None => return false,
    };
    // a `when` whose item lies in a value that is not a well-formed set does not hold
    match find(&p.tlv, b, top, &l.tags) {
        Ok(Some((s, e))) => w.present || ((1..=8).contains(&(e - s)) && be(&b[s..e]) == w.num),
        _ => false,
    }
}

/// A value's bytes -> model value.
pub(crate) fn decode_value(t: &Transform, v: &[u8]) -> Result<Value, Error> {
    match t {
        Transform::Utf8 => match std::str::from_utf8(v) {
            Ok(s) => Ok(Value::Str(s.to_string())),
            Err(_) => err("the value is not valid UTF-8"),
        },
        Transform::Hex => Ok(Value::Str(bits::to_hex(v))),
        Transform::F32 if v.len() != 4 => err(format!("an `f32` value is 4 bytes, not {}", v.len())),
        Transform::F64 if v.len() != 8 => err(format!("an `f64` value is 8 bytes, not {}", v.len())),
        _ if v.len() > 8 => err(format!("an integer value of {} bytes is longer than 8", v.len())),
        // read at its own length, whatever `:<n>` states
        _ => t.decode_bits(be(v), v.len() as u32 * 8),
    }
}

pub fn decode(p: &Pack, input: &str) -> Result<Entity, Error> {
    let c = &p.tlv;
    let b = bits::from_hex(input).map_err(|e| malformed(p, e.msg.trim_start_matches("malformed-wire: ")))?;
    // step 2: the key and the length of the set
    let (start, end) = if c.key.is_empty() {
        (0, b.len())
    } else {
        if !b.starts_with(&c.key) {
            return Err(malformed(p, "the input does not begin with the key"));
        }
        let (len, at) = read_len(c.length, &b, c.key.len(), b.len()).map_err(|m| malformed(p, m))?;
        if len > (b.len() - at) as u64 {
            return Err(malformed(p, "the set runs past the input"));
        }
        (at, at + len as usize)
    };
    // step 3: the top set, read whole
    let mut top = read_set(c, &b, start, end).map_err(|m| malformed(p, m))?;
    // step 4: the checksum item
    if let Some(t) = c.checksum {
        let last = match top.pop() {
            Some(last) if last.tag == t && last.end - last.val == 2 => last,
            _ => return Err(malformed(p, format!("the last item is not a checksum of tag {} and two bytes", t))),
        };
        if top.iter().any(|i| i.tag == t) {
            return Err(malformed(p, format!("an item of the checksum tag {} before the last", t)));
        }
        let stated = be(&b[last.val..last.end]) as u16;
        let sum = sum16(&b[..last.val]);
        if sum != stated {
            return Err(malformed(p, format!("the checksum is {:04x}, the message states {:04x}", sum, stated)));
        }
    }
    let sel = p.select_decode(None, |w| when_holds(p, &b, &top, w))?;
    // every set a line of the selected scope walks into, read whole; its residue
    let mut names = Names::default();
    for (tags, present) in sel
        .fields
        .iter()
        .map(|f| (&f.locator, false))
        .chain(sel.whens.iter().map(|w| (&w.locator, w.present)))
        .chain(sel.consts.iter().map(|w| (&w.locator, false)))
        .filter_map(|(s, present)| loc(p, s).map(|l| (l.tags, present)))
    {
        names.add(&tags, present);
    }
    let mut res = Vec::new();
    residue(c, &b, &top, &names, "", &mut res).map_err(|m| malformed(p, m))?;
    let mut d = Decoded::new();
    for f in &sel.fields {
        let l = match loc(p, &f.locator) {
            Some(l) => l,
            None => continue,
        };
        match find(c, &b, &top, &l.tags) {
            Err(m) => return Err(malformed(p, m)),
            Ok(None) => {}
            // an empty value is absent, except as a string
            Ok(Some((s, e))) if s == e && !tlv_only(&f.transform) => {}
            Ok(Some((s, e))) => d.put(p, f, decode_value(&f.transform, &b[s..e])),
        }
    }
    d.ent.residue.extend(res.into_iter().map(|(k, v)| (p.format.clone(), k, v)));
    d.finish(p, &sel)
}

/// The sum of the bytes, a byte at an even offset counting `b * 256` and
/// one at an odd offset `b`, modulo 65536.
fn sum16(b: &[u8]) -> u16 {
    b.iter().enumerate().fold(0u16, |a, (i, c)| a.wrapping_add(if i % 2 == 0 { (*c as u16) << 8 } else { *c as u16 }))
}

// ---------------------------------------------------------------------------
// Writing
// ---------------------------------------------------------------------------

/// A line of the scope as the writer takes it.
#[derive(Clone, Copy)]
enum Line<'a> {
    Field(&'a FieldDef),
    /// a `when` with a value, or a `const`
    Fixed(&'a WhenDef),
    Present,
}

/// One item of a set being written, at the position of the first line that
/// names it or a path under it.
#[derive(Default)]
struct Slot<'a> {
    tag: u32,
    fields: Vec<&'a FieldDef>,
    fixed: Option<&'a WhenDef>,
    /// the set in the value, when a line walks into it
    sub: Option<Node<'a>>,
    /// `when … present`: an empty item unless another item stands at the tag
    present: bool,
}

/// A set being written: the items of the lines, then the residue.
#[derive(Default)]
struct Node<'a> {
    slots: Vec<Slot<'a>>,
    /// tag -> the slot of the first line that names it
    named: HashMap<u32, usize>,
    residue: Vec<Res<'a>>,
    /// tag -> the residue set created for residue under it
    res_sets: HashMap<u32, usize>,
}

enum Res<'a> {
    Item(u32, Vec<u8>),
    Set(u32, Node<'a>),
}

impl<'a> Node<'a> {
    fn add(&mut self, tags: &[u32], line: Line<'a>) {
        let t = tags[0];
        if tags.len() == 1 {
            if let Line::Present = line {
                self.slots.push(Slot { tag: t, present: true, ..Slot::default() });
                return;
            }
        }
        let i = match self.named.get(&t) {
            Some(i) => *i,
            None => {
                self.slots.push(Slot { tag: t, ..Slot::default() });
                self.named.insert(t, self.slots.len() - 1);
                self.slots.len() - 1
            }
        };
        let slot = &mut self.slots[i];
        if tags.len() > 1 {
            slot.sub.get_or_insert_with(Node::default).add(&tags[1..], line);
            return;
        }
        match line {
            Line::Field(f) => slot.fields.push(f),
            Line::Fixed(w) => {
                // the earlier `when` or `const` stands
                if slot.fixed.is_none() {
                    slot.fixed = Some(w)
                }
            }
            Line::Present => {}
        }
    }

    /// A residue entry: written unless a line names its tag at that place.
    fn add_residue(&mut self, tags: &[u32], value: Vec<u8>) {
        let t = tags[0];
        if tags.len() == 1 {
            if !self.named.contains_key(&t) {
                self.residue.push(Res::Item(t, value));
            }
            return;
        }
        if let Some(i) = self.named.get(&t) {
            if let Some(sub) = self.slots[*i].sub.as_mut() {
                sub.add_residue(&tags[1..], value);
            }
            return;
        }
        let i = match self.res_sets.get(&t) {
            Some(i) => *i,
            None => {
                self.residue.push(Res::Set(t, Node::default()));
                self.res_sets.insert(t, self.residue.len() - 1);
                self.residue.len() - 1
            }
        };
        if let Res::Set(_, n) = &mut self.residue[i] {
            n.add_residue(&tags[1..], value);
        }
    }

    fn has_residue(&self, t: u32) -> bool {
        self.residue.iter().any(|r| matches!(r, Res::Item(x, _) | Res::Set(x, _) if *x == t))
    }
}

/// `v` as `n` big-endian bytes.
fn be_bytes(v: u64, n: u8) -> Vec<u8> {
    v.to_be_bytes()[8 - n as usize..].to_vec()
}

/// A model value -> the value's bytes.
pub(crate) fn encode_value(t: &Transform, v: &Value, n: Option<u8>) -> Result<Vec<u8>, Error> {
    let n = n.unwrap_or(8);
    let bits = n as u32 * 8;
    match (t, v) {
        (Transform::Utf8, Value::Str(s)) => Ok(s.as_bytes().to_vec()),
        (Transform::Hex, Value::Str(s)) => {
            let h = s.as_bytes();
            if h.len() % 2 != 0 || !h.iter().all(|c| c.is_ascii_hexdigit()) {
                return err(format!("`{}` is not hex text of an even number of digits", s));
            }
            Ok(h.chunks(2).map(|d| (nibble(d[0]) << 4) | nibble(d[1])).collect())
        }
        (Transform::Uint, Value::I64(x)) => {
            if n < 8 && (*x < 0 || (*x as u64) >> bits != 0) {
                return err(format!("{} does not fit {} unsigned bytes", x, n));
            }
            Ok(be_bytes(*x as u64, n))
        }
        (Transform::Twos, Value::I64(x)) => {
            if n < 8 && !(-(1i64 << (bits - 1))..(1i64 << (bits - 1))).contains(x) {
                return err(format!("{} does not fit {} signed bytes", x, n));
            }
            Ok(be_bytes(*x as u64, n))
        }
        (Transform::F32, _) => Ok(be_bytes(t.encode_bits(v, 32)?, 4)),
        (Transform::F64, _) => Ok(be_bytes(t.encode_bits(v, 64)?, 8)),
        (Transform::Uscale(_) | Transform::Sscale(_), _) => Ok(be_bytes(t.encode_bits(v, bits)?, n)),
        _ => err(format!("transform/value mismatch on tlv: {:?} with {:?}", t, v)),
    }
}

/// An item: its tag, its length and its value in the pack's encodings.
fn put_item(p: &Pack, tag: u32, value: &[u8], out: &mut Vec<u8>) -> Result<(), Error> {
    let fail = |m: String| Error { msg: format!("transform-encode: format `{}`: {}", p.format, m) };
    match p.tlv.tag {
        Enc::Fixed(n) => {
            if n < 4 && (tag as u64) >> (8 * n as u32) != 0 {
                return Err(fail(format!("the tag {} does not fit {} bytes", tag, n)));
            }
            out.extend_from_slice(&be_bytes(tag as u64, n));
        }
        Enc::Ber => {
            let mut groups = vec![(tag & 0x7f) as u8];
            let mut t = tag >> 7;
            while t > 0 {
                groups.push((t & 0x7f) as u8 | 0x80);
                t >>= 7;
            }
            out.extend(groups.iter().rev());
        }
    }
    put_len(p, value.len() as u64, out)?;
    out.extend_from_slice(value);
    Ok(())
}

fn put_len(p: &Pack, len: u64, out: &mut Vec<u8>) -> Result<(), Error> {
    match p.tlv.length {
        Enc::Fixed(n) => {
            if n < 8 && len >> (8 * n as u32) != 0 {
                return Err(Error {
                    msg: format!("transform-encode: format `{}`: a length of {} does not fit {} bytes", p.format, len, n),
                });
            }
            out.extend_from_slice(&be_bytes(len, n));
        }
        Enc::Ber if len < 0x80 => out.push(len as u8),
        Enc::Ber => {
            let bytes = len.to_be_bytes();
            let skip = bytes.iter().take_while(|b| **b == 0).count();
            out.push(0x80 + (8 - skip) as u8);
            out.extend_from_slice(&bytes[skip..]);
        }
    }
    Ok(())
}

/// The items of one set: the lines' items in line order, then the residue.
fn write_node(p: &Pack, sel: &Sel, ent: &Entity, node: &Node, out: &mut Vec<u8>) -> Result<(), Error> {
    // the value of each slot that is not `present` (None: no item)
    let mut values: Vec<Option<Vec<u8>>> = Vec::with_capacity(node.slots.len());
    for slot in &node.slots {
        if slot.present {
            values.push(None);
            continue;
        }
        let v = if let Some(w) = slot.fixed {
            loc(p, &w.locator).and_then(|l| l.size).map(|n| be_bytes(w.num, n))
        } else if let Some((f, v)) = slot.fields.iter().find_map(|f| sel.value_of(ent, f).map(|v| (*f, v))) {
            let e = |e: Error| transform_encode_err(p, f, e);
            let v = p.to_wire(f, v).map_err(e)?;
            let size = loc(p, &f.locator).and_then(|l| l.size);
            Some(encode_value(&f.transform, &v, size).map_err(e)?)
        } else {
            None
        };
        // a path is never both a value and a set (ruling 5 of 0.13, checked at load)
        let v = match (v, &slot.sub) {
            (Some(v), _) => Some(v),
            (None, Some(sub)) => {
                let mut inner = Vec::new();
                write_node(p, sel, ent, sub, &mut inner)?;
                // a nested set with no items is not written
                Some(inner).filter(|i| !i.is_empty())
            }
            (None, None) => None,
        };
        values.push(v);
    }
    // `when … present`: an empty item, unless a line or residue writes an item at the path
    for i in 0..node.slots.len() {
        let t = node.slots[i].tag;
        if node.slots[i].present && !node.has_residue(t) && !node.slots.iter().zip(&values).any(|(s, v)| s.tag == t && v.is_some()) {
            values[i] = Some(Vec::new());
        }
    }
    for (slot, v) in node.slots.iter().zip(&values) {
        if let Some(v) = v {
            put_item(p, slot.tag, v, out)?;
        }
    }
    for r in &node.residue {
        match r {
            Res::Item(t, v) => put_item(p, *t, v, out)?,
            Res::Set(t, n) => {
                let mut inner = Vec::new();
                write_node(p, sel, ent, n, &mut inner)?;
                put_item(p, *t, &inner, out)?;
            }
        }
    }
    Ok(())
}

pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
    let c = &p.tlv;
    let sel = p.select_encode(ent)?;
    // the lines of the scope in line order: common lines stand before the first `kind`
    let mut lines: Vec<(usize, &str, Line)> = sel.fields.iter().map(|f| (f.line, f.locator.as_str(), Line::Field(f))).collect();
    for w in sel.whens.iter().chain(sel.consts.iter()) {
        lines.push((w.line, w.locator.as_str(), if w.present { Line::Present } else { Line::Fixed(w) }));
    }
    lines.sort_by_key(|l| l.0);
    let mut root = Node::default();
    for (_, s, line) in lines {
        if let Some(l) = loc(p, s) {
            root.add(&l.tags, line);
        }
    }
    for (fmt, key, value) in &ent.residue {
        if fmt != &p.format {
            continue;
        }
        let tags = match Loc::parse(key, c.tag) {
            Ok(l) if l.size.is_none() => l.tags,
            _ => continue,
        };
        let bytes = match bits::from_hex(value) {
            Ok(b) if !value.bytes().any(|c| c.is_ascii_whitespace()) => b,
            _ => continue,
        };
        // the checksum item is never residue
        if c.checksum.is_some() && tags.len() == 1 && Some(tags[0]) == c.checksum {
            continue;
        }
        root.add_residue(&tags, bytes);
    }
    let mut set = Vec::new();
    write_node(p, &sel, ent, &root, &mut set)?;
    if let Some(t) = c.checksum {
        put_item(p, t, &[0, 0], &mut set)?;
    }
    let mut out = Vec::with_capacity(set.len() + c.key.len() + 9);
    if !c.key.is_empty() {
        out.extend_from_slice(&c.key);
        put_len(p, set.len() as u64, &mut out)?;
    }
    out.extend_from_slice(&set);
    if c.checksum.is_some() {
        let n = out.len();
        let sum = sum16(&out[..n - 2]);
        out[n - 2..].copy_from_slice(&sum.to_be_bytes());
    }
    Ok(bits::to_hex(&out))
}
