//! The `cdr` wire (engine-spec v0.43): one value of a final IDL struct in
//! OMG Common Data Representation, as DDS writes it into an RTPS serialized
//! payload. A 4-byte encapsulation header, then the members in line order,
//! each aligned to its type, offsets counted from the byte after the header.
//! XCDR version 1 and version 2 (a DHEADER before a collection of structs or
//! strings, 8-byte types aligned to 4). Input and output are hex text.
//!
//! A `field` line has no locator: the token in that place is the member's
//! type, and the transform after it may be left out. A `group` line's
//! locator is `seq` or `array:<n>`. A `when` names a common line by its
//! 1-based position; a `const` is `const <type> <value>`.

use super::*;

// ---------------------------------------------------------------------------
// Directives
// ---------------------------------------------------------------------------

/// The `cdr` and `representation` lines of a pack.
#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub struct CdrConf {
    /// the XCDR version, 1 or 2 (0 on another wire)
    pub version: u8,
    /// the 2-byte representation identifier written on encode
    pub repr: [u8; 2],
}

/// The field options of the pack language; on `cdr` only `via` and `with`
/// are valid (ruling 13 of 0.43), the rest are refused after the file.
const OPTIONS: [&str; 7] = ["via", "with", "absent", "stop", "swap", "trim", "optional"];

/// Is this token of a `field` line an option name, so that the transform
/// before it was left out?
pub(crate) fn is_option(t: &str) -> bool {
    OPTIONS.contains(&t)
}

/// The tokens of a `cdr` field line with the transform's place filled, so
/// that the options start where `field_options` reads them (token 4).
pub(crate) fn options_from(toks: &[String], explicit: bool) -> Vec<String> {
    let mut t = toks.to_vec();
    if !explicit {
        t.insert(3.min(t.len()), String::new());
    }
    t
}

/// Does the option list (from token 4) hold `stop`? `via`, `with`, `absent`
/// and `stop` take an argument.
fn has_stop(toks: &[String]) -> bool {
    let mut i = 4;
    while i < toks.len() {
        match toks[i].as_str() {
            "stop" => return true,
            "via" | "with" | "absent" => i += 2,
            _ => i += 1,
        }
    }
    false
}

/// The `cdr` lines of a pack as read, checked once the file is read.
#[derive(Clone, Debug, Default)]
pub(crate) struct CdrLines {
    cdr: Option<(usize, Vec<String>)>,
    repr: Option<(usize, Vec<String>)>,
    /// a `cdr` or `representation` line after a `kind`, or a second one
    misplaced: Option<usize>,
    /// field lines whose transform is left out
    omitted: HashSet<usize>,
    /// field lines with a `stop` option
    stop: HashSet<usize>,
    /// a `when` inside a group body (ruling 3 of 0.43: after the file)
    when_in_group: Option<usize>,
}

impl CdrLines {
    /// Record a `cdr` or `representation` line.
    pub(crate) fn record(&mut self, toks: &[String], ln: usize, after_kind: bool) {
        let slot = if toks[0] == "cdr" { &mut self.cdr } else { &mut self.repr };
        if after_kind || slot.is_some() {
            self.misplaced.get_or_insert(ln);
            return;
        }
        *slot = Some((ln, toks.to_vec()));
    }

    /// Record a `field` line of a `cdr` pack: whether its transform is
    /// written, and its options (the tokens as `options_from` gives them).
    pub(crate) fn field(&mut self, ln: usize, explicit: bool, opts: &[String]) {
        if !explicit {
            self.omitted.insert(ln);
        }
        if has_stop(opts) {
            self.stop.insert(ln);
        }
    }

    pub(crate) fn when_in_group(&mut self, ln: usize) {
        self.when_in_group.get_or_insert(ln);
    }

    /// The first `cdr` or `representation` line: on another wire it is `bad-directive`.
    pub(crate) fn first_line(&self) -> Option<usize> {
        [self.cdr.as_ref().map(|c| c.0), self.repr.as_ref().map(|c| c.0), self.misplaced].into_iter().flatten().min()
    }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/// A member type of the types table.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) enum Ty {
    I8,
    U8,
    Char8,
    Octet,
    Bool,
    I16,
    U16,
    I32,
    U32,
    I64,
    U64,
    F32,
    F64,
    E8,
    E16,
    E32,
    Str,
}

impl Ty {
    pub(crate) fn parse(s: &str) -> Option<Ty> {
        Some(match s {
            "int8" => Ty::I8,
            "uint8" => Ty::U8,
            "char8" => Ty::Char8,
            "octet" => Ty::Octet,
            "bool" => Ty::Bool,
            "int16" => Ty::I16,
            "uint16" => Ty::U16,
            "int32" => Ty::I32,
            "uint32" => Ty::U32,
            "int64" => Ty::I64,
            "uint64" => Ty::U64,
            "float32" => Ty::F32,
            "float64" => Ty::F64,
            "enum8" => Ty::E8,
            "enum16" => Ty::E16,
            "enum32" => Ty::E32,
            "string" => Ty::Str,
            _ => return None,
        })
    }

    /// The size in bytes; a string's is that of its length.
    fn size(self) -> usize {
        match self {
            Ty::I8 | Ty::U8 | Ty::Char8 | Ty::Octet | Ty::Bool | Ty::E8 => 1,
            Ty::I16 | Ty::U16 | Ty::E16 => 2,
            Ty::I32 | Ty::U32 | Ty::F32 | Ty::E32 | Ty::Str => 4,
            Ty::I64 | Ty::U64 | Ty::F64 => 8,
        }
    }

    /// The alignment: the size, at most 4 under `cdr 2`.
    fn align(self, v2: bool) -> usize {
        if v2 {
            self.size().min(4)
        } else {
            self.size()
        }
    }

    fn signed(self) -> bool {
        matches!(self, Ty::I8 | Ty::I16 | Ty::I32 | Ty::I64 | Ty::E8 | Ty::E16 | Ty::E32)
    }

    fn float(self) -> bool {
        matches!(self, Ty::F32 | Ty::F64)
    }

    /// The types `uscale` and `sscale` may read (ruling 4 of 0.43).
    fn scalable(self) -> bool {
        matches!(self, Ty::I8 | Ty::U8 | Ty::I16 | Ty::U16 | Ty::I32 | Ty::U32 | Ty::I64 | Ty::U64 | Ty::Octet)
    }

    /// The default transform of the types table.
    fn default_transform(self) -> Transform {
        match self {
            Ty::Bool => Transform::Bool,
            Ty::F32 | Ty::F64 => Transform::Float,
            Ty::Str => Transform::StringT,
            _ => Transform::Int,
        }
    }

    /// The integer range, `lo` to `hi` both included (ruling 7 of 0.43).
    fn range(self) -> (i128, i128) {
        match self {
            Ty::Bool => (0, 1),
            Ty::U64 => (0, i64::MAX as i128),
            t if t.signed() => {
                let half = 1i128 << (8 * t.size() - 1);
                (-half, half - 1)
            }
            t => (0, (1i128 << (8 * t.size())) - 1),
        }
    }
}

/// The type of a line already checked at load.
fn ty_of(locator: &str) -> Ty {
    Ty::parse(locator).unwrap_or(Ty::U8)
}

/// The shape of a group: a sequence, or an array of `n` elements.
#[derive(Clone, Copy, Debug, PartialEq)]
enum Shape {
    Seq,
    Array(u64),
}

fn shape(locator: &str) -> Option<Shape> {
    if locator == "seq" {
        return Some(Shape::Seq);
    }
    let n = unsigned_text(locator.strip_prefix("array:")?)?;
    if n == 0 {
        return None;
    }
    Some(Shape::Array(n))
}

/// Does a collection of this group's elements take a DHEADER under `cdr 2`?
/// Every body but one `field` of a primitive type (ruling 8 of 0.43).
fn has_dheader(g: &GroupDef) -> bool {
    let primitive = g.fields.len() == 1
        && g.consts.is_empty()
        && g.groups.is_empty()
        && !matches!(ty_of(&g.fields[0].locator), Ty::Str | Ty::E8 | Ty::E16 | Ty::E32);
    !primitive
}

// ---------------------------------------------------------------------------
// Load checks
// ---------------------------------------------------------------------------

/// The first failure of the checks after the file, by line.
#[derive(Default)]
struct First(Option<(usize, Error)>);

impl First {
    fn keep(&mut self, ln: usize, e: Error) {
        if self.0.as_ref().map_or(true, |(at, _)| ln < *at) {
            self.0 = Some((ln, e));
        }
    }
    fn bad(&mut self, ln: usize, m: impl AsRef<str>) {
        self.keep(ln, Error { msg: format!("bad-directive: line {}: {}", ln, m.as_ref()) });
    }
}

/// A `field` line: a known type, only `via` and `with`, a transform the
/// type takes (ruling 4 of 0.43). Sets the default transform when left out.
fn check_field(lines: &CdrLines, f: &mut FieldDef, first: &mut First) {
    let ty = match Ty::parse(&f.locator) {
        Some(t) => t,
        None => return first.bad(f.line, format!("`{}` is not a type of the cdr wire", f.locator)),
    };
    if f.swap || f.trim || f.optional || f.absent_arg.is_some() || lines.stop.contains(&f.line) {
        return first.bad(f.line, "only `via` and `with` are field options on the cdr wire");
    }
    if lines.omitted.contains(&f.line) {
        f.transform = ty.default_transform();
        return;
    }
    let ok = f.transform == ty.default_transform()
        || (matches!(f.transform, Transform::Uscale(_) | Transform::Sscale(_)) && ty.scalable());
    if !ok {
        first.bad(f.line, format!("the transform of `{}` is not valid on a cdr `{}`", f.model_key, f.locator));
    }
}

/// A `const <type> <value>`: an integer type, an unsigned decimal that fits it.
fn check_const(c: &mut WhenDef, first: &mut First) {
    let ty = match Ty::parse(&c.locator) {
        Some(t) => t,
        None => return first.bad(c.line, format!("`{}` is not a type of the cdr wire", c.locator)),
    };
    if ty == Ty::Str || ty.float() {
        return first.bad(c.line, format!("a `const` of type `{}`: the value is an unsigned decimal of an integer type", c.locator));
    }
    let bits = 8 * ty.size() as u32;
    match unsigned_text(&c.value) {
        Some(v) if (bits >= 64 || v >> bits == 0) && (ty != Ty::Bool || v <= 1) => {
            c.num = v;
            c.nums = vec![(v, v)];
        }
        _ => first.bad(c.line, format!("`const {} {}`: the value is not an unsigned decimal that fits the type", c.locator, c.value)),
    }
}

/// A group, its body and every group nested in it.
fn check_group(lines: &CdrLines, g: &mut GroupDef, first: &mut First) {
    if shape(&g.locator).is_none() {
        first.bad(g.line, format!("`{}`: a cdr group is `seq` or `array:<n>` with n at least 1", g.locator));
    }
    if g.fields.is_empty() && g.consts.is_empty() && g.groups.is_empty() {
        first.bad(g.line, format!("group `{}` has no wire line in its body", g.list));
    }
    for f in g.fields.iter_mut() {
        check_field(lines, f, first);
    }
    for c in g.consts.iter_mut() {
        check_const(c, first);
    }
    for inner in g.groups.iter_mut() {
        check_group(lines, inner, first);
    }
}

/// One common line, as `when <n>` counts it: its line number, whether it is
/// a group, and its type (None: a group, or a type that is not known).
fn common_lines(fields: &[FieldDef], consts: &[WhenDef], groups: &[GroupDef]) -> Vec<(usize, bool, Option<Ty>)> {
    let mut out: Vec<(usize, bool, Option<Ty>)> = fields
        .iter()
        .map(|f| (f.line, false, Ty::parse(&f.locator)))
        .chain(consts.iter().map(|c| (c.line, false, Ty::parse(&c.locator))))
        .chain(groups.iter().map(|g| (g.line, true, None)))
        .collect();
    out.sort_by_key(|l| l.0);
    out
}

/// The checks of 0.43 that need the whole file. Sets each field's transform
/// and each `when` and `const` value. Returns the directives.
pub(crate) fn check_pack(
    lines: &CdrLines,
    fields: &mut [FieldDef],
    whens: &mut [WhenDef],
    consts: &mut [WhenDef],
    groups: &mut [GroupDef],
    kinds: &mut [KindDef],
) -> Result<CdrConf, Error> {
    let mut first = First::default();
    let mut conf = CdrConf::default();
    if let Some(ln) = lines.misplaced {
        first.bad(ln, "`cdr` and `representation` stand once each, before the first `kind`");
    }
    match &lines.cdr {
        Some((ln, t)) => match t.get(1).map(|s| s.as_str()) {
            Some("1") => conf.version = 1,
            Some("2") => conf.version = 2,
            _ => first.bad(*ln, "`cdr` is `1` or `2`"),
        },
        None => first.bad(usize::MAX, "a cdr pack has no `cdr` line"),
    }
    match &lines.repr {
        Some((ln, t)) => {
            let v = t.get(1).map(|s| s.as_bytes()).unwrap_or(b"");
            let lower = |c: &u8| c.is_ascii_digit() || (b'a'..=b'f').contains(c);
            if v.len() == 4 && v.iter().all(lower) {
                let n = |c: u8| if c.is_ascii_digit() { c - b'0' } else { c - b'a' + 10 };
                conf.repr = [n(v[0]) << 4 | n(v[1]), n(v[2]) << 4 | n(v[3])];
            } else {
                first.bad(*ln, "`representation` is four lowercase hex digits");
            }
        }
        None => first.bad(usize::MAX, "a cdr pack has no `representation` line"),
    }
    if let Some(ln) = lines.when_in_group {
        first.bad(ln, "`when` inside a group");
    }
    for f in fields.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.fields.iter_mut())) {
        check_field(lines, f, &mut first);
    }
    for c in consts.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.consts.iter_mut())) {
        check_const(c, &mut first);
    }
    for g in groups.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.groups.iter_mut())) {
        check_group(lines, g, &mut first);
    }
    // `when <n> <value>` (rulings 2 and 3 of 0.43)
    let common = common_lines(fields, consts, groups);
    for w in whens.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.whens.iter_mut())) {
        let at = match unsigned_text(&w.locator) {
            Some(n) if n >= 1 && (n as usize) <= common.len() && n <= usize::MAX as u64 => n as usize,
            _ => {
                first.bad(w.line, format!("`when {}`: not the position of a common line, 1 to {}", w.locator, common.len()));
                continue;
            }
        };
        let ty = match common[at - 1] {
            (_, true, _) => {
                first.bad(w.line, format!("`when {}` names a `group` line", w.locator));
                continue;
            }
            (_, false, Some(t)) if t != Ty::Str && !t.float() => t,
            (_, false, Some(_)) => {
                first.bad(w.line, format!("`when {}` names a string or a float line", w.locator));
                continue;
            }
            // a type that is not known is reported at its own line
            (_, false, None) => continue,
        };
        match num_list(&w.value, Some(8 * ty.size() as u32), w.line) {
            Ok(nums) => {
                w.num = nums[0].0;
                w.nums = nums;
            }
            Err(e) => first.keep(w.line, e),
        }
    }
    match first.0 {
        Some((_, e)) => Err(e),
        None => Ok(conf),
    }
}

// ---------------------------------------------------------------------------
// Lines of a scope
// ---------------------------------------------------------------------------

/// A wire line of a scope, in file order.
#[derive(Clone, Copy)]
enum Line<'a> {
    Field(&'a FieldDef),
    Const(&'a WhenDef),
    Group(&'a GroupDef),
}

fn lines_of<'a>(fields: &'a [FieldDef], consts: &'a [WhenDef], groups: &'a [GroupDef]) -> Vec<Line<'a>> {
    let mut out: Vec<(usize, Line<'a>)> = fields
        .iter()
        .map(|f| (f.line, Line::Field(f)))
        .chain(consts.iter().map(|c| (c.line, Line::Const(c))))
        .chain(groups.iter().map(|g| (g.line, Line::Group(g))))
        .collect();
    out.sort_by_key(|l| l.0);
    out.into_iter().map(|(_, l)| l).collect()
}

fn malformed(p: &Pack, why: impl AsRef<str>) -> Error {
    Error { msg: format!("malformed-wire: format `{}`: {}", p.format, why.as_ref()) }
}

fn encode_err(p: &Pack, why: impl AsRef<str>) -> Error {
    Error { msg: format!("transform-encode: format `{}`: {}", p.format, why.as_ref()) }
}

// ---------------------------------------------------------------------------
// Reading
// ---------------------------------------------------------------------------

/// A cursor over the body, the bytes after the header: offsets for
/// alignment count from its first byte.
struct Reader<'b> {
    b: &'b [u8],
    at: usize,
    le: bool,
    v2: bool,
}

impl<'b> Reader<'b> {
    fn left(&self) -> usize {
        self.b.len() - self.at
    }
    /// Skip the padding before a value of alignment `n`, whatever it holds.
    fn align(&mut self, n: usize) -> Result<(), String> {
        let pad = (n - self.at % n) % n;
        if pad > self.left() {
            return Err(format!("the input ends inside the padding at byte {}", self.at + 4));
        }
        self.at += pad;
        Ok(())
    }
    /// An unsigned integer of `n` bytes in the message's byte order, aligned.
    fn uint(&mut self, n: usize, align: usize, what: &str) -> Result<u64, String> {
        self.align(align)?;
        if n > self.left() {
            return Err(format!("the input ends inside {} at byte {}", what, self.at + 4));
        }
        let s = &self.b[self.at..self.at + n];
        self.at += n;
        Ok(if self.le {
            s.iter().rev().fold(0u64, |a, c| (a << 8) | *c as u64)
        } else {
            s.iter().fold(0u64, |a, c| (a << 8) | *c as u64)
        })
    }
    /// A string: its length, its bytes, its NUL. Err: malformed; the inner
    /// result: the value or its `transform-decode` failure.
    fn string(&mut self) -> Result<Result<Value, Error>, String> {
        let start = self.at;
        let n = self.uint(4, 4, "a string length")?;
        if n == 0 {
            return Err(format!("a string length of 0 at byte {}", start + 4));
        }
        if n > self.left() as u64 {
            return Err(format!("the input ends inside a string of {} bytes at byte {}", n, self.at + 4));
        }
        let s = &self.b[self.at..self.at + n as usize];
        self.at += n as usize;
        let (text, nul) = s.split_at(s.len() - 1);
        if nul[0] != 0 {
            return Err(format!("a string at byte {} does not end in a NUL", start + 4));
        }
        if text.contains(&0) {
            return Ok(err("a NUL before the last byte of a string"));
        }
        Ok(match std::str::from_utf8(text) {
            Ok(t) => Ok(Value::Str(t.to_string())),
            Err(_) => err("a string that is not UTF-8"),
        })
    }
}

/// The value of a member that is not a string, from its raw bits.
fn decode_value(ty: Ty, t: &Transform, raw: u64) -> Result<Value, Error> {
    match ty {
        Ty::F32 => return finite(f32::from_bits(raw as u32) as f64),
        Ty::F64 => return finite(f64::from_bits(raw)),
        _ => {}
    }
    let bits = 8 * ty.size() as u32;
    let v: i64 = if ty.signed() && bits < 64 {
        ((raw << (64 - bits)) as i64) >> (64 - bits)
    } else {
        raw as i64
    };
    if ty == Ty::U64 && raw > i64::MAX as u64 {
        return err(format!("the uint64 {} is above 2^63-1", raw));
    }
    if ty == Ty::Bool && raw > 1 {
        return err(format!("a bool of value {}", raw));
    }
    match t {
        Transform::Uscale(sc) | Transform::Sscale(sc) => Ok(Value::F64(sc.decode(v as f64))),
        _ => Ok(Value::I64(v)),
    }
}

/// Read the lines of one scope into `d`. `raws`: the raw value of each line
/// in order, for `when` (None: a string or a group).
fn read_lines(p: &Pack, r: &mut Reader, lines: &[Line], d: &mut Decoded, mut raws: Option<&mut Vec<Option<u64>>>) -> Result<(), Error> {
    for line in lines {
        let raw = match line {
            Line::Field(f) => {
                let ty = ty_of(&f.locator);
                if ty == Ty::Str {
                    let v = r.string().map_err(|m| malformed(p, m))?;
                    d.put(p, f, v);
                    None
                } else {
                    let raw = r.uint(ty.size(), ty.align(r.v2), "a value").map_err(|m| malformed(p, m))?;
                    d.put(p, f, decode_value(ty, &f.transform, raw));
                    Some(raw)
                }
            }
            Line::Const(c) => {
                let ty = ty_of(&c.locator);
                Some(r.uint(ty.size(), ty.align(r.v2), "a const").map_err(|m| malformed(p, m))?)
            }
            Line::Group(g) => {
                read_group(p, r, g, d)?;
                None
            }
        };
        if let Some(rs) = raws.as_deref_mut() {
            rs.push(raw);
        }
    }
    Ok(())
}

/// A sequence or an array of a group's elements, with its DHEADER under `cdr 2`.
fn read_group(p: &Pack, r: &mut Reader, g: &GroupDef, d: &mut Decoded) -> Result<(), Error> {
    let m = |s: String| malformed(p, s);
    let dheader = if r.v2 && has_dheader(g) {
        let stated = r.uint(4, 4, "a DHEADER").map_err(m)?;
        Some((stated, r.at))
    } else {
        None
    };
    let n = match shape(&g.locator) {
        Some(Shape::Seq) => r.uint(4, 4, "a sequence count").map_err(m)?,
        Some(Shape::Array(n)) => n,
        None => return Err(malformed(p, format!("group `{}` has no shape", g.list))),
    };
    // every element takes one byte at least: checked before any memory is taken
    if n > r.left() as u64 {
        return Err(malformed(p, format!("group `{}` states {} elements, more than the {} bytes left", g.list, n, r.left())));
    }
    limit::take(&p.format, &g.list, n)?;
    let body = lines_of(&g.fields, &g.consts, &g.groups);
    let mut items: Vec<Decoded> = Vec::with_capacity(n as usize);
    for _ in 0..n {
        let mut item = Decoded::new();
        read_lines(p, r, &body, &mut item, None)?;
        items.push(item);
    }
    if let Some((stated, start)) = dheader {
        let took = (r.at - start) as u64;
        if took != stated {
            return Err(malformed(p, format!("the DHEADER of group `{}` states {} bytes, the collection takes {}", g.list, stated, took)));
        }
    }
    d.put_list(&g.list, items);
    Ok(())
}

pub fn decode(p: &Pack, input: &str) -> Result<Entity, Error> {
    let b = bits::from_hex(input).map_err(|e| malformed(p, e.msg.trim_start_matches("malformed-wire: ")))?;
    if b.len() < 4 {
        return Err(malformed(p, format!("{} bytes, shorter than the 4-byte header", b.len())));
    }
    let repr = p.cdr.repr;
    if b[0] != repr[0] || (b[1] & 0xfe) != (repr[1] & 0xfe) {
        return Err(malformed(p, format!("the identifier {:02x}{:02x} is not {:02x}{:02x}", b[0], b[1], repr[0], repr[1])));
    }
    let mut r = Reader { b: &b[4..], at: 0, le: b[1] & 1 == 1, v2: p.cdr.version == 2 };
    let mut d = Decoded::new();
    let mut raws: Vec<Option<u64>> = Vec::new();
    read_lines(p, &mut r, &lines_of(&p.fields, &p.consts, &p.groups), &mut d, Some(&mut raws))?;
    let holds = |w: &WhenDef| {
        let at = w.locator.parse::<usize>().unwrap_or(0);
        match at.checked_sub(1).and_then(|i| raws.get(i)) {
            Some(Some(raw)) => w.holds_num(*raw),
            _ => false,
        }
    };
    // step 2: at most 3 zero bytes after the last line read
    let tail = |r: &Reader| -> Result<(), Error> {
        let rest = &r.b[r.at..];
        if rest.len() > 3 || rest.iter().any(|c| *c != 0) {
            return Err(malformed(p, format!("{} bytes after the last member, more than 3 zero bytes", rest.len())));
        }
        Ok(())
    };
    let sel = match p.select_decode(None, holds) {
        Ok(sel) => sel,
        // ruling 25: structural checks rank above `no-kind`; with no kind
        // the last line read is the last common line
        Err(e) => {
            tail(&r)?;
            return Err(e);
        }
    };
    if let Some(k) = sel.kind {
        read_lines(p, &mut r, &lines_of(&k.fields, &k.consts, &k.groups), &mut d, None)?;
    }
    tail(&r)?;
    d.finish(p, &sel)
}

// ---------------------------------------------------------------------------
// Writing
// ---------------------------------------------------------------------------

struct Writer {
    out: Vec<u8>,
    le: bool,
    v2: bool,
}

impl Writer {
    fn align(&mut self, n: usize) {
        while self.out.len() % n != 0 {
            self.out.push(0);
        }
    }
    fn uint(&mut self, v: u64, n: usize, align: usize) {
        self.align(align);
        let be = v.to_be_bytes();
        let bytes = &be[8 - n..];
        if self.le {
            self.out.extend(bytes.iter().rev());
        } else {
            self.out.extend_from_slice(bytes);
        }
    }
    fn patch_u32(&mut self, at: usize, v: u32) {
        let bytes = if self.le { v.to_le_bytes() } else { v.to_be_bytes() };
        self.out[at..at + 4].copy_from_slice(&bytes);
    }
}

/// A model value through the line's transform: the raw bits of a member
/// that is not a string.
fn encode_value(ty: Ty, t: &Transform, v: &Value) -> Result<u64, Error> {
    let mask = if ty.size() >= 8 { u64::MAX } else { (1u64 << (8 * ty.size())) - 1 };
    let (lo, hi) = ty.range();
    match (ty, t, v) {
        (Ty::F32, _, Value::F64(x)) => Ok(single(*x)?.to_bits() as u64),
        (Ty::F64, _, Value::F64(x)) => Ok(finite(*x)?.as_f64().to_bits()),
        (_, Transform::Uscale(sc) | Transform::Sscale(sc), Value::F64(x)) => {
            let q = sc.quotient(*x);
            if !q.is_finite() {
                return err(format!("the quotient {} is not finite", q));
            }
            // the nearest integer, halfway away from zero (4a of 0.11); the
            // bounds are 0 or powers of two, exact as doubles
            let r = q.round();
            if r < lo as f64 || r >= (hi + 1) as f64 {
                return err(format!("{} rounds to {}, outside the range of a cdr {:?}", q, r, ty));
            }
            Ok((r as i64 as u64) & mask)
        }
        (_, _, Value::I64(n)) => {
            if (*n as i128) < lo || (*n as i128) > hi {
                return err(format!("{} is outside the range of a cdr {:?}, {} to {}", n, ty, lo, hi));
            }
            Ok((*n as u64) & mask)
        }
        _ => err(format!("transform/value mismatch on cdr: {:?} with {:?}", t, v)),
    }
}

fn put_string(p: &Pack, w: &mut Writer, s: &str) -> Result<(), Error> {
    if s.contains('\0') {
        return Err(encode_err(p, "a string holding U+0000"));
    }
    let n = u32::try_from(s.len() + 1).map_err(|_| encode_err(p, "a string longer than a uint32 length counts"))?;
    w.uint(n as u64, 4, 4);
    w.out.extend_from_slice(s.as_bytes());
    w.out.push(0);
    Ok(())
}

/// Write the lines of one scope. `over[i]`: the `when` written over line i.
fn write_lines(p: &Pack, w: &mut Writer, lines: &[Line], ent: &Entity, sel: &Sel, over: &[Option<&WhenDef>]) -> Result<(), Error> {
    for (i, line) in lines.iter().enumerate() {
        let fixed = over.get(i).copied().flatten();
        match line {
            Line::Field(f) => {
                let ty = ty_of(&f.locator);
                if let Some(wd) = fixed {
                    w.uint(wd.num, ty.size(), ty.align(w.v2));
                    continue;
                }
                let v = match sel.value_of(ent, f) {
                    Some(v) => Some(p.to_wire(f, v).map_err(|e| transform_encode_err(p, f, e))?),
                    None => None,
                };
                match (ty, v) {
                    (Ty::Str, None) => put_string(p, w, "")?,
                    (Ty::Str, Some(Value::Str(s))) => put_string(p, w, &s)?,
                    (Ty::Str, Some(other)) => {
                        return Err(transform_encode_err(p, f, Error { msg: format!("a string member takes text, got {:?}", other) }))
                    }
                    (_, None) => w.uint(0, ty.size(), ty.align(w.v2)),
                    (_, Some(v)) => {
                        let raw = encode_value(ty, &f.transform, &v).map_err(|e| transform_encode_err(p, f, e))?;
                        w.uint(raw, ty.size(), ty.align(w.v2));
                    }
                }
            }
            Line::Const(c) => {
                let ty = ty_of(&c.locator);
                w.uint(fixed.unwrap_or(c).num, ty.size(), ty.align(w.v2));
            }
            Line::Group(g) => write_group(p, w, g, ent)?,
        }
    }
    Ok(())
}

fn write_group(p: &Pack, w: &mut Writer, g: &GroupDef, ent: &Entity) -> Result<(), Error> {
    let items: &[Entity] = match (ent.lists.get(&g.list), shape(&g.locator)) {
        (Some(l), _) => l,
        (None, Some(Shape::Seq)) => &[],
        (None, _) => return Err(encode_err(p, format!("list `{}` is absent, and its array has a fixed length", g.list))),
    };
    let dheader = if w.v2 && has_dheader(g) {
        w.uint(0, 4, 4);
        Some(w.out.len())
    } else {
        None
    };
    match shape(&g.locator) {
        Some(Shape::Array(n)) if items.len() as u64 != n => {
            return Err(encode_err(p, format!("list `{}` has {} items, its array {}", g.list, items.len(), n)))
        }
        Some(Shape::Array(_)) => {}
        _ => {
            let n = u32::try_from(items.len()).map_err(|_| encode_err(p, format!("list `{}` has more items than a uint32 counts", g.list)))?;
            w.uint(n as u64, 4, 4);
        }
    }
    let body = lines_of(&g.fields, &g.consts, &g.groups);
    let sel = g.body();
    for item in items {
        write_lines(p, w, &body, item, &sel, &[])?;
    }
    if let Some(start) = dheader {
        let len = u32::try_from(w.out.len() - start).map_err(|_| encode_err(p, format!("list `{}` is longer than a DHEADER counts", g.list)))?;
        w.patch_u32(start - 4, len);
    }
    Ok(())
}

pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
    let sel = p.select_encode(ent)?;
    let common = lines_of(&p.fields, &p.consts, &p.groups);
    // the `when` written over each common line: the kind's own, else the common one
    let mut over: Vec<Option<&WhenDef>> = vec![None; common.len()];
    for wd in sel.whens.iter() {
        if let Some(slot) = wd.locator.parse::<usize>().ok().and_then(|n| n.checked_sub(1)).and_then(|i| over.get_mut(i)) {
            *slot = Some(wd);
        }
    }
    let mut w = Writer { out: Vec::new(), le: p.cdr.repr[1] & 1 == 1, v2: p.cdr.version == 2 };
    write_lines(p, &mut w, &common, ent, &sel, &over)?;
    if let Some(k) = sel.kind {
        write_lines(p, &mut w, &lines_of(&k.fields, &k.consts, &k.groups), ent, &sel, &[])?;
    }
    let pad = (4 - w.out.len() % 4) % 4;
    w.out.extend(std::iter::repeat(0).take(pad));
    let mut out = Vec::with_capacity(w.out.len() + 4);
    out.extend_from_slice(&p.cdr.repr);
    out.extend_from_slice(&[0, pad as u8]);
    out.extend_from_slice(&w.out);
    Ok(bits::to_hex(&out))
}
