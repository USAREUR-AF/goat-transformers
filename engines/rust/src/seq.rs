//! Sequential binary layouts (engine-spec v0.8): a `bits` pack with
//! `layout sequential`. The lines of a message are read, and written, in file
//! order from a cursor; the place of a field depends on what came before it.

#[cfg(feature = "bits")]
use super::bits::{get_bits, is_sentinel, read_field, set_bits, write_field, write_sentinel};
use super::*;

// ---------------------------------------------------------------------------
// The lines of a sequential pack
// ---------------------------------------------------------------------------

/// One condition of an `if` line: bit `bit` (from 1) of the presence `id`.
#[derive(Clone, Debug)]
pub struct Cond {
    pub id: usize,
    pub bit: u32,
    /// `!<name>.<i>`: the bit must be 0
    pub neg: bool,
}

/// How a `group` repeats.
#[derive(Clone, Debug, PartialEq)]
pub enum Rep {
    /// a count of this many bits at the cursor, then that many items
    Count(u32),
    /// each item is preceded by one bit: 1 = an item follows, 0 = the list ends
    While,
    /// each item is preceded by one bit: 1 = another item follows this one
    More,
    /// each item ends with one bit: 1 = another item follows
    Fx,
    /// `size [<lb> <ub>]` (engine-spec v0.19): a constrained count, or a length determinant
    Size(crate::uper::Size),
    /// items until the end of the enclosing extent (engine-spec v0.21)
    Rest,
    /// as many items as the `count` line of this id states (engine-spec
    /// v0.21); two ids: two counts that must agree (engine-spec v0.31)
    Named(Vec<usize>),
    /// each item is preceded by one bit: 1 = this is the last item (engine-spec v0.21)
    Last,
}

#[derive(Clone, Debug)]
pub struct SeqGroup {
    pub list: String,
    pub rep: Rep,
    pub body: SeqBody,
    pub line: usize,
}

#[derive(Clone, Debug)]
pub enum SeqLine {
    /// `also`: the keys of the `also` lines after the field, on the same bits;
    /// `uper`: a UPER locator (engine-spec v0.19), `len` is then 0
    Field { f: FieldDef, len: u32, also: Vec<FieldDef>, uper: Option<crate::uper::Loc> },
    Const { len: u32, value: u64 },
    Pad { len: u64 },
    Align { n: u64 },
    /// a `when` among common lines: it must hold for any message
    When(SeqWhen),
    /// `bits`: the number of presence bits; None: `fx` octets
    /// `named`: the bits some `if` block outside every `case` names; any other
    /// bit set on the wire is `malformed-wire`, unless an `if` of a case that
    /// is read names it (`in_cases`: the bits `if` lines inside cases name)
    Presence { id: usize, bits: Option<u32>, named: Vec<u32>, in_cases: Vec<u32> },
    If { conds: Vec<Cond>, body: Vec<SeqLine> },
    Opt { body: Vec<SeqLine> },
    Group(SeqGroup),
    /// the parts between `fx` lines; `ends_fx`: the last line of the chain is `fx`
    Chain { parts: Vec<Vec<SeqLine>>, ends_fx: bool },
    /// `units`: `length @<name> units <u>` (engine-spec v0.83), the id of its
    /// `count` line and the bits of one unit; `len` and `plus` are then 0
    Length { len: u32, in_bits: bool, plus: i64, body: Vec<SeqLine>, units: Option<(usize, u32)> },
    /// `length ... whole`: the length of the whole message in bytes plus `plus`
    Whole { len: u32, plus: i64 },
    /// `ext` (engine-spec v0.19): a SEQUENCE with an extension marker
    Ext { body: Vec<SeqLine> },
    /// `choice <n> [ext]`: (index, lines) of each `alt`, in line order
    Choice { n: u32, ext: bool, alts: Vec<(u32, Vec<SeqLine>)> },
    /// `switch <key>` … `end` (engine-spec v0.20)
    Switch(Switch),
    /// `count <name> <len> [plus <n>]`: a count a later `group … count @<name>`
    /// uses (engine-spec v0.21)
    Count { id: usize, len: u32, plus: i64, line: usize },
    /// `inner <format> [partial]` (engine-spec v0.34): the bytes to the end of the
    /// enclosing extent are one message of another loaded pack
    /// `bad_arg`: a second argument other than `partial`, refused after the file
    /// `reach`: the keys the outer pack's lines in reach map (ruling 20 of 0.52)
    /// `run`: `inner <format> run` (engine-spec v0.92); `withs`: the keys `with`
    /// names on the lines in reach (ruling 9 of 0.92)
    Inner { format: String, partial: bool, run: bool, bad_arg: bool, line: usize, reach: Vec<String>, withs: Vec<String> },
}

/// One `when` line of a sequential pack. `values`: every listed value and
/// range (engine-spec v0.20); `value`: the first, written when no key says
/// otherwise; `key`: the key of `as <key>` (engine-spec v0.30).
#[derive(Clone, Debug)]
pub struct SeqWhen {
    pub len: u32,
    pub value: u64,
    pub values: Vec<(u64, u64)>,
    pub key: Option<String>,
    pub line: usize,
    /// `at <offset>`: read at kind start plus the offset, the cursor kept
    /// (engine-spec v0.33)
    pub at: Option<u64>,
    /// `optional` after the key of `as`: the line's implicit `requires` term
    /// holds when the entity does not hold the key (engine-spec v0.52)
    pub optional: bool,
}

/// The first line of a scope that maps a key a `switch` names: a `field` or
/// `also` line (field, bit length, `also` keys, UPER locator), or a `when …
/// as` line (engine-spec v0.30, ruling 2).
#[derive(Clone, Debug)]
pub enum First {
    Field(FieldDef, u32, Vec<FieldDef>, Option<crate::uper::Loc>),
    When(SeqWhen),
}

/// One `case` or `else` body of a `switch`.
#[derive(Clone, Debug)]
pub struct Case {
    /// the values as written (empty for `else`)
    pub values: Vec<String>,
    /// the values as canonical text of the key's type, set when the pack is loaded
    pub canon: Vec<String>,
    pub lines: Vec<SeqLine>,
    /// the `default` lines of the case (ruling 7 of 0.20)
    pub defaults: Vec<DefaultDef>,
    pub line: usize,
    /// (presence id, bit) named by the `if` lines of the case, those of
    /// nested switches' cases excepted
    pub names: Vec<(usize, u32)>,
}

/// A `switch` block: the lines read next chosen by a decoded value.
#[derive(Clone, Debug)]
pub struct Switch {
    pub key: String,
    pub line: usize,
    /// the first line of the scope that maps the key; the first prediction
    /// of encode (ruling 37 of 0.20)
    pub first: First,
    pub cases: Vec<Case>,
    pub other: Option<Case>,
}

/// The case a switch selects: an index into `cases`, `cases.len()` for
/// `else`; None when none is selected (`no-kind`).
#[cfg(feature = "bits")]
type Pick = Option<usize>;

impl Switch {
    /// The case for the key's value as canonical text (None: the key is absent).
    #[cfg(feature = "bits")]
    fn pick(&self, value: Option<&str>) -> Pick {
        if let Some(v) = value {
            let listed = |c: &Case| if c.canon.is_empty() { c.values.iter().any(|x| x == v) } else { c.canon.iter().any(|x| x == v) };
            if let Some(i) = self.cases.iter().position(listed) {
                return Some(i);
            }
        }
        self.other.as_ref().map(|_| self.cases.len())
    }
    #[cfg(feature = "bits")]
    fn case(&self, pick: usize) -> &Case {
        self.cases.get(pick).unwrap_or_else(|| self.other.as_ref().expect("an else"))
    }
    fn bodies(&self) -> impl Iterator<Item = &Case> {
        self.cases.iter().chain(self.other.iter())
    }
    fn bodies_mut(&mut self) -> impl Iterator<Item = &mut Case> {
        self.cases.iter_mut().chain(self.other.iter_mut())
    }
}

/// One kind of a message or of an item.
#[derive(Clone, Debug)]
pub struct SeqKind {
    pub name: String,
    /// the `when` lines: the first lines of the kind
    pub whens: Vec<SeqWhen>,
    pub requires: Vec<ReqDef>,
    pub lines: Vec<SeqLine>,
    pub defaults: Vec<DefaultDef>,
    /// how many of `lines` the windows of its `when … at` lines cover, from
    /// the first (engine-spec v0.33): encode settles the windows after them
    pub prefix: usize,
}

/// The lines of a message, or of one item of a group: common lines, then kinds.
#[derive(Clone, Debug, Default)]
pub struct SeqBody {
    pub common: Vec<SeqLine>,
    pub kinds: Vec<SeqKind>,
    pub defaults: Vec<DefaultDef>,
    /// of a message body: the first `at` error, raised after the key passes
    /// (rulings 10 and 14 of 0.33)
    pub at_err: Option<Error>,
}

/// What `SeqBody::visit` hands its caller.
pub enum Visit<'a> {
    Field(&'a FieldDef),
    Default(&'a DefaultDef),
    /// (line, list name)
    Group(usize, &'a str),
    Requires(&'a ReqDef),
    /// a `switch` block (engine-spec v0.20)
    Switch(&'a Switch),
    /// a `when … as <key>` line (engine-spec v0.30): (key, line)
    As(&'a str, usize),
}

fn visit_lines<'a>(lines: &'a [SeqLine], f: &mut dyn FnMut(Visit<'a>)) {
    for l in lines {
        match l {
            SeqLine::Field { f: field, also, .. } => {
                f(Visit::Field(field));
                also.iter().for_each(|a| f(Visit::Field(a)));
            }
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
                visit_lines(body, f)
            }
            SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| visit_lines(p, f)),
            SeqLine::Choice { alts, .. } => alts.iter().for_each(|(_, p)| visit_lines(p, f)),
            SeqLine::Group(g) => {
                f(Visit::Group(g.line, &g.list));
                g.body.visit(f);
            }
            SeqLine::Switch(sw) => {
                f(Visit::Switch(sw));
                for c in sw.bodies() {
                    visit_lines(&c.lines, f);
                    c.defaults.iter().for_each(|d| f(Visit::Default(d)));
                }
            }
            SeqLine::When(SeqWhen { key: Some(k), line, .. }) => f(Visit::As(k, *line)),
            _ => {}
        }
    }
}

fn visit_lines_mut(lines: &mut [SeqLine], ff: &mut dyn FnMut(&mut FieldDef), fd: &mut dyn FnMut(&mut DefaultDef)) {
    for l in lines {
        match l {
            SeqLine::Field { f, also, .. } => {
                ff(f);
                also.iter_mut().for_each(|a| ff(a));
            }
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
                visit_lines_mut(body, ff, fd)
            }
            SeqLine::Chain { parts, .. } => parts.iter_mut().for_each(|p| visit_lines_mut(p, ff, fd)),
            SeqLine::Choice { alts, .. } => alts.iter_mut().for_each(|(_, p)| visit_lines_mut(p, ff, fd)),
            SeqLine::Group(g) => g.body.visit_mut(ff, fd),
            SeqLine::Switch(sw) => {
                if let First::Field(f, _, also, _) = &mut sw.first {
                    ff(f);
                    also.iter_mut().for_each(|a| ff(a));
                }
                for c in sw.bodies_mut() {
                    visit_lines_mut(&mut c.lines, ff, fd);
                    c.defaults.iter_mut().for_each(|d| fd(d));
                }
            }
            _ => {}
        }
    }
}

/// Fill the canonical values of every `requires =` term and `case` line
/// (ruling 1 of 0.20): `ty` gives a key's declared type.
fn resolve_lines(lines: &mut [SeqLine], ty: &dyn Fn(&str) -> Option<KeyType>) {
    for l in lines {
        match l {
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
                resolve_lines(body, ty)
            }
            SeqLine::Chain { parts, .. } => parts.iter_mut().for_each(|p| resolve_lines(p, ty)),
            // a switch inside a 0.19 `choice` (ruling 40 of 0.20)
            SeqLine::Choice { alts, .. } => alts.iter_mut().for_each(|(_, p)| resolve_lines(p, ty)),
            SeqLine::Group(g) => g.body.resolve(ty),
            SeqLine::Switch(sw) => {
                let t = ty(&sw.key);
                for c in sw.bodies_mut() {
                    if let Some(t) = t {
                        c.canon = c.values.iter().filter_map(|v| canon_value(t, v)).collect();
                    }
                    resolve_lines(&mut c.lines, ty);
                }
            }
            _ => {}
        }
    }
}

impl SeqBody {
    /// Every field, default, group and `requires` key, nested bodies included.
    pub fn visit<'a>(&'a self, f: &mut dyn FnMut(Visit<'a>)) {
        visit_lines(&self.common, f);
        self.defaults.iter().for_each(|d| f(Visit::Default(d)));
        for k in &self.kinds {
            for w in &k.whens {
                if let Some(key) = &w.key {
                    f(Visit::As(key, w.line));
                }
            }
            k.requires.iter().for_each(|r| f(Visit::Requires(r)));
            visit_lines(&k.lines, f);
            k.defaults.iter().for_each(|d| f(Visit::Default(d)));
        }
    }

    /// Fill the canonical values of `requires =` terms and `case` lines.
    pub fn resolve(&mut self, ty: &dyn Fn(&str) -> Option<KeyType>) {
        resolve_lines(&mut self.common, ty);
        for k in &mut self.kinds {
            for r in &mut k.requires {
                if let (Some(vs), Some(t)) = (&r.values, ty(&r.key)) {
                    r.canon = vs.iter().filter_map(|v| canon_value(t, v)).collect();
                }
            }
            resolve_lines(&mut k.lines, ty);
        }
    }

    pub fn visit_mut(&mut self, ff: &mut dyn FnMut(&mut FieldDef), fd: &mut dyn FnMut(&mut DefaultDef)) {
        visit_lines_mut(&mut self.common, ff, fd);
        self.defaults.iter_mut().for_each(|d| fd(d));
        for k in &mut self.kinds {
            visit_lines_mut(&mut k.lines, ff, fd);
            k.defaults.iter_mut().for_each(|d| fd(d));
        }
    }

    /// The model keys the body maps, in first appearance order: a list is
    /// `<list>[]`, an item key `<list>[].<key>`.
    pub fn model_keys(&self, prefix: &str, out: &mut Vec<String>) {
        self.model_keys_with(prefix, out, &|_, _| {})
    }

    /// `model_keys`, with `inner` adding the entries of an `inner` line at
    /// its place (engine-spec v0.34): it is given the format and the list so far.
    pub fn model_keys_with(&self, prefix: &str, out: &mut Vec<String>, inner: &dyn Fn(&str, &mut Vec<String>)) {
        fn lines(prefix: &str, ls: &[SeqLine], out: &mut Vec<String>, inner: &dyn Fn(&str, &mut Vec<String>)) {
            for l in ls {
                match l {
                    SeqLine::Field { f, also, .. } => {
                        for k in std::iter::once(f).chain(also.iter()) {
                            let name = format!("{}{}", prefix, k.model_key);
                            if !out.contains(&name) {
                                out.push(name);
                            }
                        }
                    }
                    SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
                        lines(prefix, body, out, inner)
                    }
                    SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| lines(prefix, p, out, inner)),
                    SeqLine::Choice { alts, .. } => alts.iter().for_each(|(_, p)| lines(prefix, p, out, inner)),
                    SeqLine::Group(g) => {
                        let name = format!("{}{}[]", prefix, g.list);
                        if !out.contains(&name) {
                            out.push(name.clone());
                        }
                        g.body.model_keys_with(&format!("{}.", name), out, inner);
                    }
                    // keys mapped only inside a case are listed too (ruling 13 of 0.20)
                    SeqLine::Switch(sw) => sw.bodies().for_each(|c| lines(prefix, &c.lines, out, inner)),
                    // a key bound by `as`, at its `when` line (ruling 5 of 0.30)
                    SeqLine::When(SeqWhen { key: Some(k), .. }) => {
                        let name = format!("{}{}", prefix, k);
                        if !out.contains(&name) {
                            out.push(name);
                        }
                    }
                    SeqLine::Inner { format, .. } => inner(format, out),
                    _ => {}
                }
            }
        }
        lines(prefix, &self.common, out, inner);
        for k in &self.kinds {
            for w in &k.whens {
                if let Some(key) = &w.key {
                    let name = format!("{}{}", prefix, key);
                    if !out.contains(&name) {
                        out.push(name);
                    }
                }
            }
            lines(prefix, &k.lines, out, inner);
        }
    }
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

struct Parser<'a> {
    lines: &'a [(usize, Vec<String>)],
    i: usize,
    next_id: usize,
    /// the presences and counts visible here, innermost last: (name, id, what)
    names: Vec<(String, usize, Named)>,
    /// how many group bodies are open: a count is referenced from its own (ruling 9 of 0.21)
    body_depth: usize,
    /// kind names of the whole pack
    /// where the names of the block being read start in `names`
    block_start: usize,
    /// per presence id: the bits `if` lines outside every `case` name
    named: Vec<Vec<u32>>,
    /// per presence id: the bits `if` lines inside a `case` name (engine-spec v0.20)
    case_named: Vec<Vec<u32>>,
    /// the cases being read, innermost last: the (id, bit) their `if` lines name
    case_ifs: Vec<Vec<(usize, u32)>>,
    /// per presence id: how many cases were open where it was declared
    case_depth: Vec<usize>,
    /// the keys mapped so far in the scope being read (common lines and the
    /// current kind, or one group body): a `switch` names one of them
    mapped: Vec<(String, First)>,
    /// the `default` lines of the scope being read
    defaults: Vec<DefaultDef>,
    /// the first syntax error of an `as` (engine-spec v0.30)
    as_err: Option<Error>,
    /// the first error of the form of an `at` (engine-spec v0.33)
    at_form: Option<Error>,
    /// the first `framing` line and the first error of one (engine-spec v0.92)
    framing: Option<usize>,
    framing_err: Option<Error>,
    /// every `via` table a field names: (table, line)
    vias: Vec<(String, usize)>,
    // header
    format: Option<String>,
    version: Option<String>,
    wire: Option<String>,
    order: BitOrder,
    distribution: Option<Distribution>,
    sources: Vec<String>,
    uses: Vec<String>,
    maps: Vec<(String, Vec<(String, String)>)>,
    /// engine-spec v0.14: `armor`
    armor: crate::armor::ArmorLines,
    /// engine-spec v0.19: `encoding`, and the first line only a UPER pack may hold
    encoding: crate::uper::EncodingLines,
    /// engine-spec v0.46: `charset` lines
    charsets: crate::charset::CharsetLines,
    uper_line: Option<usize>,
    to_cot: BTreeMap<String, String>,
    from_cot: BTreeMap<String, String>,
}

/// What a name of `Parser::names` is.
#[derive(Clone, Copy, Debug)]
enum Named {
    /// a presence of this many bits (None: `fx` octets)
    Presence(Option<u32>),
    /// a count declared in the group body of this depth (engine-spec v0.21)
    Count(usize),
}

/// A `plus` value of a `count` line: an optional `-` then digits, leading
/// zeros allowed, within signed 64 bits (ruling 16 of 0.21).
fn plus_value(text: &str, ln: usize) -> Result<i64, Error> {
    let digits = text.strip_prefix('-').unwrap_or(text);
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return bad(ln, format!("`plus {}` is not an optional `-` then digits", text));
    }
    text.parse::<i64>().or_else(|_| bad(ln, format!("`plus {}` is outside signed 64 bits", text)))
}

/// A decimal bit length of at least 1. A positional locator is `bad-directive`.
fn bit_len(text: &str, ln: usize) -> Result<u64, Error> {
    if text.contains(':') {
        return bad(ln, format!("`{}` is a positional locator; a sequential pack takes a bit length", text));
    }
    match text.parse::<u64>() {
        Ok(n) if n >= 1 && text.bytes().all(|b| b.is_ascii_digit()) => Ok(n),
        _ => bad(ln, format!("`{}` is not a bit length of at least 1", text)),
    }
}

/// A bit length a single unsigned value can hold: 1 to 64.
fn value_len(text: &str, ln: usize) -> Result<u32, Error> {
    match bit_len(text, ln)? {
        n if n <= 64 => Ok(n as u32),
        n => bad(ln, format!("bit length {} is more than 64", n)),
    }
}

/// An unsigned decimal value that fits `len` bits.
fn value_of(text: &str, len: u32, ln: usize) -> Result<u64, Error> {
    if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
        return bad(ln, format!("`{}` is not an unsigned decimal integer", text));
    }
    let v = text.parse::<u64>().or_else(|_| bad(ln, format!("`{}` is too large", text)))?;
    if len < 64 && v >> len != 0 {
        return bad(ln, format!("{} does not fit {} bits", v, len));
    }
    Ok(v)
}

const HEADER: [&str; 19] = [
    "format", "version", "wire", "layout", "bit_order", "distribution", "source", "uses", "map", "typemap", "word_bytes", "root",
    "delimiter", "start", "checksum", "armor", "encoding", "framing", "charset",
];

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<&'a (usize, Vec<String>)> {
        self.lines.get(self.i)
    }

    /// A `framing self` line (engine-spec v0.92, ruling 16): what is wrong with
    /// it is reported after the file is read.
    fn framing(&mut self, toks: &[String], ln: usize, after_kind: bool) {
        let why = if self.framing.is_some() {
            Some("a second `framing` line")
        } else if toks.len() != 2 || toks[1] != "self" {
            Some("framing is `self`")
        } else if after_kind {
            Some("`framing` stands before the first `kind`")
        } else {
            None
        };
        self.framing.get_or_insert(ln);
        if let (Some(why), None) = (why, &self.framing_err) {
            self.framing_err = Some(Error { msg: format!("bad-directive: line {}: {}", ln, why) });
        }
    }

    /// One header directive of the pack, outside every block.
    fn header(&mut self, ln: usize, toks: &[String]) -> Result<(), Error> {
        match toks[0].as_str() {
            "format" => self.format = Some(req_arg(toks, 1, ln)?),
            "version" => self.version = Some(req_arg(toks, 1, ln)?),
            "wire" => self.wire = Some(req_arg(toks, 1, ln)?),
            "layout" => {}
            "bit_order" => {
                if toks.len() != 2 {
                    return bad(ln, "bit_order needs `lsb`, `msb` or `msb-lsb`");
                }
                self.order = match BitOrder::parse(&toks[1]) {
                    Some(o) => o,
                    None => return bad(ln, format!("bit_order is `lsb`, `msb` or `msb-lsb`, got `{}`", toks[1])),
                };
            }
            "distribution" => {
                let v = req_arg(toks, 1, ln)?;
                self.distribution = Some(Distribution::parse(&v).ok_or(Error {
                    msg: format!("bad-directive: line {}: distribution is `public` or `controlled`, got `{}`", ln, v),
                })?)
            }
            "source" => self.sources.push(req_arg(toks, 1, ln)?),
            "uses" => {
                let m = req_arg(toks, 1, ln)?;
                if !self.uses.contains(&m) {
                    self.uses.push(m);
                }
            }
            "map" => {
                if toks.len() != 4 {
                    return bad(ln, "map needs <table> <native> <model>");
                }
                let entry = (toks[2].clone(), toks[3].clone());
                match self.maps.iter_mut().find(|(name, _)| name == &toks[1]) {
                    Some((_, entries)) => entries.push(entry),
                    None => self.maps.push((toks[1].clone(), vec![entry])),
                }
            }
            "typemap" => {
                if toks.len() != 3 {
                    return err(format!("line {}: typemap needs <native> <cot>", ln));
                }
                self.to_cot.insert(toks[1].clone(), toks[2].clone());
                self.from_cot.insert(toks[2].clone(), toks[1].clone());
            }
            "word_bytes" => return bad(ln, "`word_bytes` is not used in a `layout sequential` pack"),
            _ => return bad(ln, format!("`{}` is not valid in a `layout sequential` pack", toks[0])),
        }
        Ok(())
    }

    /// The lines of a message (`top`) or of one group body, up to its `end`.
    fn body(&mut self, top: bool, open_line: usize) -> Result<SeqBody, Error> {
        self.body_depth += 1;
        let res = self.body_in(top, open_line);
        self.body_depth -= 1;
        res
    }

    fn body_in(&mut self, top: bool, open_line: usize) -> Result<SeqBody, Error> {
        let mut out = SeqBody::default();
        let visible = self.names.len();
        let outer_block = std::mem::replace(&mut self.block_start, visible);
        // kind names are unique within one body (ruling 11 of 0.8)
        let mut kind_names: Vec<String> = Vec::new();
        let outer_defaults = std::mem::take(&mut self.defaults);
        // a group body is a scope of its own for `switch` keys (engine-spec v0.20)
        let outer_mapped = std::mem::take(&mut self.mapped);
        // the presences visible when the first `kind` starts: those of a
        // kind's own lines end with the kind
        let mut common_names: Option<usize> = None;
        let mut common_mapped: Option<usize> = None;
        // a kind's `when` lines are its first lines
        let mut kind_has_lines = false;
        let mut when_line: Option<usize> = None;
        loop {
            let (ln, toks) = match self.peek() {
                Some((ln, toks)) => (*ln, toks),
                None if top => break,
                None => return bad(open_line, "the group has no `end`"),
            };
            match toks[0].as_str() {
                "end" if !top => {
                    if toks.len() != 1 {
                        return bad(ln, "`end` takes no argument");
                    }
                    self.i += 1;
                    break;
                }
                "end" => return bad(ln, "`end` with no open block"),
                d if HEADER.contains(&d) => {
                    if !top {
                        return bad(ln, format!("`{}` is not allowed inside a group", d));
                    }
                    if d == "armor" {
                        self.armor.record(toks, ln, !out.kinds.is_empty());
                    } else if d == "encoding" {
                        self.encoding.record(toks, ln, !out.kinds.is_empty());
                    } else if d == "framing" {
                        self.framing(toks, ln, !out.kinds.is_empty());
                    } else if d == "charset" {
                        self.charsets.record(toks, ln, !out.kinds.is_empty());
                    } else {
                        self.header(ln, toks)?;
                    }
                    self.i += 1;
                }
                "kind" => {
                    if toks.len() != 2 {
                        return bad(ln, "kind needs <name>");
                    }
                    if kind_names.contains(&toks[1]) {
                        return err(format!("duplicate-kind: line {}: kind `{}` declared twice", ln, toks[1]));
                    }
                    kind_names.push(toks[1].clone());
                    let defaults = std::mem::take(&mut self.defaults);
                    match out.kinds.last_mut() {
                        Some(k) => k.defaults = defaults,
                        None => out.defaults = defaults,
                    }
                    match common_names {
                        Some(n) => self.names.truncate(n),
                        None => common_names = Some(self.names.len()),
                    }
                    match common_mapped {
                        Some(n) => self.mapped.truncate(n),
                        None => common_mapped = Some(self.mapped.len()),
                    }
                    out.kinds.push(SeqKind {
                        name: toks[1].clone(),
                        whens: Vec::new(),
                        requires: Vec::new(),
                        lines: Vec::new(),
                        defaults: Vec::new(),
                        prefix: 0,
                    });
                    kind_has_lines = false;
                    self.i += 1;
                }
                "when" => {
                    // `as <model-key>` after the values (engine-spec v0.30)
                    // its syntax errors are reported after `missing-wire` (rulings 16, 29)
                    let as_err = |p: &mut Self, why: &str| {
                        if p.as_err.is_none() {
                            p.as_err = Some(Error { msg: format!("bad-directive: line {}: {}", ln, why) });
                        }
                    };
                    // `at <offset>` before it (engine-spec v0.33): `when <len> <values>
                    // [at <n>] [as <k> [optional]]` (0.52). A line that holds `at` is checked with the
                    // `at` checks, after the key passes (rulings 10 and 14 of 0.33)
                    let args = &toks[3..];
                    // the token after `as` is the key, `at` included (ruling 4 of 0.52)
                    let has_at = when_holds_at(args);
                    let mut optional = false;
                    let at_err = |p: &mut Self, why: &str| {
                        if p.at_form.is_none() {
                            p.at_form = Some(Error { msg: format!("bad-directive: line {}: {}", ln, why) });
                        }
                    };
                    let mut i = 0;
                    let mut offset: Option<u64> = None;
                    let mut key: Option<String> = None;
                    let mut form: Option<&str> = None;
                    // a bad offset still lets the key of `as` be read: the key
                    // passes come before the `at` form (ruling 10 of 0.33)
                    let mut bad_offset: Option<&str> = None;
                    if args.first().map(|t| t.as_str()) == Some("at") {
                        match args.get(1) {
                            None => form = Some("`at` needs an offset"),
                            Some(n) if !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()) => match n.parse::<u64>() {
                                Ok(v) => offset = Some(v),
                                Err(_) => bad_offset = Some("the offset of `at` does not fit in 64 bits"),
                            },
                            // a keyword in the offset's place is the broken order,
                            // never an offset alone bad (ruling 15 of 0.52)
                            Some(n) if matches!(n.as_str(), "at" | "as" | "optional") => form = Some("a keyword in the place of the offset of `at`"),
                            Some(_) => bad_offset = Some("the offset of `at` is not plain digits"),
                        }
                        i = 2;
                    }
                    if form.is_none() && i < args.len() {
                        if args[i] == "as" {
                            match args.get(i + 1) {
                                None => form = Some("`as` needs a <model-key>"),
                                Some(k) if k == "as" => form = Some("`as` given twice on one `when` line"),
                                Some(k) => key = Some(k.clone()),
                            }
                            if form.is_none() {
                                let rest = &args[i + 2..];
                                if rest.iter().any(|t| t == "as") {
                                    form = Some("`as` given twice on one `when` line");
                                } else if rest.iter().any(|t| t == "at") {
                                    form = Some("`at` after `as`, or twice");
                                } else if rest.first().map(|t| t.as_str()) == Some("optional") {
                                    match rest.get(1).map(|t| t.as_str()) {
                                        None => optional = true,
                                        Some("optional") => form = Some("`optional` given twice on one `when` line"),
                                        Some(_) => form = Some("a token after `optional`"),
                                    }
                                } else if !rest.is_empty() {
                                    form = Some("a token after the key of `as`");
                                }
                            }
                        } else if args[i] == "at" {
                            form = Some("`at` given twice on one `when` line");
                        } else {
                            form = Some("when needs <len> <values> [at <n>] [as <model-key>]");
                        }
                    }
                    if let (None, Some(why)) = (form, bad_offset) {
                        at_err(self, why);
                        offset = None;
                    }
                    if let Some(why) = form {
                        // an extra token with neither keyword is a line check (ruling 23 of 0.20)
                        if !has_at && args.first().map(|t| t.as_str()) != Some("as") {
                            return bad(ln, why);
                        }
                        if has_at {
                            at_err(self, why);
                        } else {
                            as_err(self, why);
                        }
                        key = None;
                        offset = None;
                    }
                    // `at` only on a kind's `when` (engine-spec v0.33)
                    // engine-spec v0.52: `optional` only on a kind's `when`. With `at`,
                    // the line is a late `at` form error whose key is read (ruling 3)
                    if optional && out.kinds.is_empty() && !has_at {
                        as_err(self, "`optional` on a common `when`");
                    }
                    if offset.is_some() && out.kinds.is_empty() {
                        at_err(self, "`at` on a common `when`");
                        offset = None;
                    }
                    let len = value_len(&toks[1], ln)?;
                    // a list of values and ranges (engine-spec v0.20)
                    if toks[2].split(',').any(|v| v == "present") {
                        return bad(ln, "`present` is not a value of a bits `when`");
                    }
                    let values = num_list(&toks[2], Some(len), ln)?;
                    let value = values[0].0;
                    when_line.get_or_insert(ln);
                    let w = SeqWhen { len, value, values, key, line: ln, at: offset, optional };
                    // a `switch` may name the key from here on (ruling 2 of 0.30)
                    if let Some(k) = &w.key {
                        self.mapped.push((k.clone(), First::When(w.clone())));
                    }
                    match out.kinds.last_mut() {
                        Some(_) if kind_has_lines => {
                            return bad(ln, "the `when` lines of a kind are its first lines");
                        }
                        Some(k) => k.whens.push(w),
                        None => out.common.push(SeqLine::When(w)),
                    }
                    self.i += 1;
                }
                "requires" => {
                    let k = match out.kinds.last_mut() {
                        Some(k) => k,
                        None => return bad(ln, "`requires` before the first `kind`"),
                    };
                    if toks.len() < 2 {
                        return bad(ln, "requires needs at least one <model-key>");
                    }
                    k.requires.extend(ReqDef::parse(&toks[1..], ln)?);
                    self.i += 1;
                }
                _ => {
                    if let Some(line) = self.line()? {
                        match out.kinds.last_mut() {
                            Some(k) => {
                                k.lines.push(line);
                                kind_has_lines = true;
                            }
                            None => out.common.push(line),
                        }
                    }
                }
            }
        }
        let defaults = std::mem::replace(&mut self.defaults, outer_defaults);
        match out.kinds.last_mut() {
            Some(k) => k.defaults = defaults,
            None => out.defaults = defaults,
        }
        // a name is visible to the end of the enclosing block
        self.names.truncate(visible);
        self.block_start = outer_block;
        self.mapped = outer_mapped;
        // ruling 8 of 0.5: a `when` needs kinds
        if let (true, Some(ln)) = (out.kinds.is_empty(), when_line) {
            return bad(ln, "`when` with no `kind`");
        }
        Ok(out)
    }

    /// The lines of an `if`, `opt` or `length` block, up to its `end`.
    fn block(&mut self, open_line: usize, what: &str) -> Result<Vec<SeqLine>, Error> {
        let visible = self.names.len();
        let outer_block = std::mem::replace(&mut self.block_start, visible);
        let mut out = Vec::new();
        loop {
            let (ln, toks) = match self.peek() {
                Some((ln, toks)) => (*ln, toks),
                None => return bad(open_line, format!("the `{}` block has no `end`", what)),
            };
            if toks[0] == "end" {
                if toks.len() != 1 {
                    return bad(ln, "`end` takes no argument");
                }
                self.i += 1;
                break;
            }
            if let Some(line) = self.line()? {
                out.push(line);
            }
        }
        self.names.truncate(visible);
        self.block_start = outer_block;
        Ok(out)
    }

    /// The id of the `count` line a reference `text` (`@<name>`) names: visible
    /// here, and of this group body (rulings 9 and 12 of 0.21).
    fn count_ref(&self, text: &str, name: &str, ln: usize) -> Result<usize, Error> {
        match self.names.iter().rev().find(|(n, _, _)| n == name) {
            Some((_, id, Named::Count(depth))) if *depth == self.body_depth => Ok(*id),
            Some((_, _, Named::Count(_))) => bad(ln, format!("`{}` names a count of another group body (ruling 9 of 0.21)", text)),
            Some((_, _, Named::Presence(_))) => bad(ln, format!("`{}` names a presence, not a count", text)),
            None => bad(ln, format!("`{}` names a count that is not visible here", text)),
        }
    }

    /// The lines of one `alt`, up to the next `alt` or the `end` of the
    /// `choice`, which are not taken.
    fn alt_block(&mut self) -> Result<Vec<SeqLine>, Error> {
        let visible = self.names.len();
        let outer_block = std::mem::replace(&mut self.block_start, visible);
        let mut out = Vec::new();
        while let Some((_, toks)) = self.peek() {
            if toks[0] == "end" || toks[0] == "alt" {
                break;
            }
            if let Some(line) = self.line()? {
                out.push(line);
            }
        }
        self.names.truncate(visible);
        self.block_start = outer_block;
        Ok(out)
    }

    /// A `switch <key>` line and its `case` and `else` bodies, up to its `end`
    /// (engine-spec v0.20).
    fn switch(&mut self, ln: usize, toks: &[String]) -> Result<Switch, Error> {
        if toks.len() != 2 {
            return bad(ln, "switch needs <model-key>");
        }
        let key = toks[1].clone();
        let first = match self.mapped.iter().find(|(k, _)| *k == key) {
            Some((_, line)) => line.clone(),
            None => return bad(ln, format!("`switch {}`: the key is not mapped by a line before it in its scope", key)),
        };
        let mut cases: Vec<Case> = Vec::new();
        let mut other: Option<Case> = None;
        loop {
            let (l, t) = match self.peek() {
                Some((l, t)) => (*l, t),
                None => return bad(ln, "the `switch` block has no `end`"),
            };
            match t[0].as_str() {
                "end" => {
                    if t.len() != 1 {
                        return bad(l, "`end` takes no argument");
                    }
                    self.i += 1;
                    break;
                }
                "case" => {
                    if other.is_some() {
                        return bad(l, "`else` before a `case`");
                    }
                    if t.len() != 2 {
                        return bad(l, "case needs <value>[,<value>…]");
                    }
                    let values: Vec<String> = t[1].split(',').map(|v| v.to_string()).collect();
                    if values.iter().any(|v| v.is_empty()) {
                        return bad(l, format!("`case {}` has an empty value", t[1]));
                    }
                    // a value listed twice is checked at load, after the key and
                    // type checks (ruling 19 of 0.20)
                    self.i += 1;
                    let c = self.case_body(ln, l, values)?;
                    cases.push(c);
                }
                "else" => {
                    if t.len() != 1 {
                        return bad(l, "`else` takes no argument");
                    }
                    if other.is_some() {
                        return bad(l, "two `else` in one switch");
                    }
                    if cases.is_empty() {
                        return bad(l, "`else` before a `case`");
                    }
                    self.i += 1;
                    other = Some(self.case_body(ln, l, Vec::new())?);
                }
                _ => return bad(l, "a line of a `switch` before its first `case`"),
            }
        }
        if cases.is_empty() {
            return bad(ln, "a `switch` with no `case`");
        }
        Ok(Switch { key, line: ln, first, cases, other })
    }

    /// The lines of one `case` or `else`, up to the next `case`, `else` or
    /// `end` of its switch. Each body is a block for presence names (ruling 8
    /// of 0.20) and has its own defaults (ruling 7).
    fn case_body(&mut self, switch_line: usize, ln: usize, values: Vec<String>) -> Result<Case, Error> {
        let visible = self.names.len();
        let outer_block = std::mem::replace(&mut self.block_start, visible);
        let outer_defaults = std::mem::take(&mut self.defaults);
        self.case_ifs.push(Vec::new());
        let mut lines = Vec::new();
        loop {
            let t = match self.peek() {
                Some((_, t)) => t,
                None => return bad(switch_line, "the `switch` block has no `end`"),
            };
            if matches!(t[0].as_str(), "case" | "else" | "end") {
                break;
            }
            if let Some(line) = self.line()? {
                lines.push(line);
            }
        }
        self.names.truncate(visible);
        self.block_start = outer_block;
        let defaults = std::mem::replace(&mut self.defaults, outer_defaults);
        let names = self.case_ifs.pop().expect("a case");
        Ok(Case { values, canon: Vec::new(), lines, defaults, line: ln, names })
    }

    /// One line at the cursor, with the block it opens. None: a `default`
    /// line, which belongs to the scope and not to a position.
    fn line(&mut self) -> Result<Option<SeqLine>, Error> {
        let (ln, toks) = match self.peek() {
            Some((ln, toks)) => (*ln, toks),
            None => return err("unexpected end of the pack"),
        };
        self.i += 1;
        Ok(Some(match toks[0].as_str() {
            "default" => {
                if toks.len() != 3 {
                    return bad(ln, "default needs <model-key> <value>");
                }
                self.defaults.push(DefaultDef { model_key: toks[1].clone(), text: toks[2].clone(), line: ln, value: None, gate: None });
                return Ok(None);
            }
            "field" => {
                if toks.len() < 4 {
                    return bad(ln, "field needs <model-key> <len> <transform> [options]");
                }
                // a UPER locator (engine-spec v0.19), `until:<code>` in place of a
                // bit length (engine-spec v0.22), else a bit length
                let uper = crate::uper::parse_loc(&toks[2], ln)?;
                let until_text = toks[2].strip_prefix("until:");
                let len = match (&uper, until_text) {
                    (Some(_), _) | (None, Some(_)) => 0,
                    (None, None) => bit_len(&toks[2], ln)?,
                };
                let mut f = FieldDef {
                    model_key: toks[1].clone(),
                    locator: toks[2].clone(),
                    transform: Transform::parse(&toks[3])?,
                    line: ln,
                    via: None,
                    swap: false,
                    trim: false,
                    optional: false,
                    key_type: None,
                    absent_arg: None,
                    absent: Vec::new(),
                    gate: None,
                    with: None,
                    until: None,
                    stop: None,
                    code: CodeSeq::of(&toks[3]),
                    unlisted: false,
                };
                for table in field_options(&mut f, toks, ln, false)? {
                    self.vias.push((table, ln));
                }
                if f.unlisted {
                    return bad(ln, "`unlisted` is valid only on a `part` line with `via`");
                }
                if let Some(code) = until_text {
                    let set = match f.transform {
                        Transform::Chars(set) => set,
                        _ => return bad(ln, "`until:` is valid only with `chars:<set>`"),
                    };
                    if f.absent_arg.is_some() || f.swap || f.trim {
                        return bad(ln, "`until:` takes no `absent`, `swap` or `trim`");
                    }
                    if f.stop.is_some() {
                        return bad(ln, "`stop` and `until:` cannot be combined (ruling 16 of 0.22)");
                    }
                    f.until = Some(char_code(code, set, ln, "until:")?);
                }
                let t = &f.transform;
                if let Some(loc) = &uper {
                    self.uper_line.get_or_insert(ln);
                    crate::uper::check_field(loc, &f)?;
                    // ruling 22 of 0.19: no raw value of 0.9 is stated for a UPER locator
                    if f.absent_arg.is_some() {
                        return bad(ln, format!("`absent` is not valid on the UPER locator of `{}`", f.model_key));
                    }
                } else if !t.is_bits() {
                    return bad(ln, format!("transform of `{}` is not valid on a bits wire", f.model_key));
                }
                let ok = uper.is_some() || f.until.is_some() || u32::try_from(len).map_or(false, |l| t.bits_len_ok(l));
                if !ok {
                    return bad(ln, format!("bit length {} is not allowed for the transform of `{}`", len, f.model_key));
                }
                if f.swap && *t == Transform::Sixbit {
                    return bad(ln, "`swap` is not valid on `sixbit`");
                }
                if f.swap && len % 8 != 0 && uper.is_none() {
                    return bad(ln, format!("`swap` needs a bit length that is a multiple of 8, got {}", len));
                }
                if f.trim && !matches!(t, Transform::Ascii | Transform::Sixbit) {
                    return bad(ln, "`trim` is valid only with `ascii` or `sixbit`");
                }
                if f.swap && t.refuses_swap() {
                    return bad(ln, "`swap` is not valid with `chars`, `octal` or `hex`");
                }
                resolve_absent(Wire::Bits, &mut f, Some(len as u32))?;
                // `also <key> [via <table>]` lines directly after the field (ruling 13 of 0.8)
                let mut also = Vec::new();
                while let Some((l, t)) = self.peek() {
                    if t[0] != "also" {
                        break;
                    }
                    let via = match t.len() {
                        2 => None,
                        4 if t[2] == "via" => {
                            self.vias.push((t[3].clone(), *l));
                            Some(t[3].clone())
                        }
                        _ => return bad(*l, "also needs <model-key> [via <table>]"),
                    };
                    also.push(FieldDef { model_key: t[1].clone(), via, line: *l, key_type: None, with: None, ..f.clone() });
                    self.i += 1;
                }
                let line = First::Field(f.clone(), len as u32, also.clone(), uper.clone());
                self.mapped.push((f.model_key.clone(), line.clone()));
                self.mapped.extend(also.iter().map(|a| (a.model_key.clone(), line.clone())));
                SeqLine::Field { f, len: len as u32, also, uper }
            }
            "const" => {
                if toks.len() != 3 {
                    return bad(ln, "const needs <len> <value>");
                }
                let len = value_len(&toks[1], ln)?;
                SeqLine::Const { len, value: value_of(&toks[2], len, ln)? }
            }
            "pad" => {
                if toks.len() != 2 {
                    return bad(ln, "pad needs <len>");
                }
                SeqLine::Pad { len: bit_len(&toks[1], ln)? }
            }
            "align" => {
                if toks.len() != 2 {
                    return bad(ln, "align needs <n>");
                }
                SeqLine::Align { n: bit_len(&toks[1], ln)? }
            }
            "presence" => {
                if toks.len() != 3 {
                    return bad(ln, "presence needs <name> <n> or <name> fx");
                }
                let name = &toks[1];
                if name.is_empty() || name.starts_with('!') {
                    return bad(ln, format!("`{}` is not a presence name", name));
                }
                let bits = match toks[2].as_str() {
                    "fx" => None,
                    n => Some(value_len(n, ln)?),
                };
                // ruling 12 of 0.8: twice in one block; a nested block may hide the name
                if self.names[self.block_start..].iter().any(|(n, _, _)| n == name) {
                    return bad(ln, format!("presence `{}` is declared twice in one block", name));
                }
                let id = self.next_id;
                self.next_id += 1;
                self.named.push(Vec::new());
                self.names.push((name.clone(), id, Named::Presence(bits)));
                self.case_named.push(Vec::new());
                self.case_depth.push(self.case_ifs.len());
                SeqLine::Presence { id, bits, named: Vec::new(), in_cases: Vec::new() }
            }
            "if" => {
                if toks.len() < 2 {
                    return bad(ln, "if needs at least one <name>.<i>");
                }
                let mut conds = Vec::new();
                for t in &toks[1..] {
                    let (neg, rest) = match t.strip_prefix('!') {
                        Some(r) => (true, r),
                        None => (false, t.as_str()),
                    };
                    let (name, bit) = match rest.rsplit_once('.') {
                        Some((n, b)) => (n, b),
                        None => return bad(ln, format!("`{}` is not <name>.<i>", t)),
                    };
                    let bit = match bit.parse::<u32>() {
                        Ok(b) if b >= 1 && bit.bytes().all(|c| c.is_ascii_digit()) => b,
                        _ => return bad(ln, format!("`{}` does not name a presence bit from 1", t)),
                    };
                    let (id, size) = match self.names.iter().rev().find(|(n, _, _)| n == name) {
                        Some((_, id, Named::Presence(size))) => (*id, *size),
                        // counts and presences share one namespace (ruling 15 of 0.21)
                        Some((_, _, Named::Count(_))) => return bad(ln, format!("`{}` names a count, not a presence", t)),
                        None => return bad(ln, format!("`{}` names a presence that is not visible here", t)),
                    };
                    if size.map_or(false, |n| bit > n) {
                        return bad(ln, format!("`{}` names a bit beyond the {} bits of the presence", t, size.unwrap_or(0)));
                    }
                    // an `if` of a case the presence is not in names the bit only
                    // when the case is read (engine-spec v0.20): the innermost
                    // case, read only when the cases around it are
                    let depth = self.case_depth[id];
                    let deeper = self.case_ifs.len() > depth;
                    match self.case_ifs.last_mut().filter(|_| deeper) {
                        Some(names) => {
                            if !self.case_named[id].contains(&bit) {
                                self.case_named[id].push(bit);
                            }
                            if !names.contains(&(id, bit)) {
                                names.push((id, bit));
                            }
                        }
                        None => {
                            if !self.named[id].contains(&bit) {
                                self.named[id].push(bit);
                            }
                        }
                    }
                    conds.push(Cond { id, bit, neg });
                }
                SeqLine::If { conds, body: self.block(ln, "if")? }
            }
            "opt" => {
                if toks.len() != 1 {
                    return bad(ln, "`opt` takes no argument");
                }
                SeqLine::Opt { body: self.block(ln, "opt")? }
            }
            "chain" => {
                if toks.len() != 1 {
                    return bad(ln, "`chain` takes no argument");
                }
                let visible = self.names.len();
                let outer_block = std::mem::replace(&mut self.block_start, visible);
                let mut parts: Vec<Vec<SeqLine>> = vec![Vec::new()];
                let mut ends_fx = false;
                loop {
                    let (l, t) = match self.peek() {
                        Some((l, t)) => (*l, t),
                        None => return bad(ln, "the `chain` block has no `end`"),
                    };
                    match t[0].as_str() {
                        "end" => {
                            if t.len() != 1 {
                                return bad(l, "`end` takes no argument");
                            }
                            self.i += 1;
                            break;
                        }
                        "fx" => {
                            if t.len() != 1 {
                                return bad(l, "`fx` takes no argument");
                            }
                            self.i += 1;
                            parts.push(Vec::new());
                            ends_fx = true;
                        }
                        _ => {
                            if let Some(line) = self.line()? {
                                parts.last_mut().expect("a part").push(line);
                                ends_fx = false;
                            }
                        }
                    }
                }
                if ends_fx {
                    parts.pop();
                }
                self.names.truncate(visible);
                self.block_start = outer_block;
                SeqLine::Chain { parts, ends_fx }
            }
            "length" => {
                if toks.len() < 2 {
                    return bad(ln, "length needs <len> [bytes|bits] [plus <n>] [whole]");
                }
                // `length @<name> units <u>` (engine-spec v0.83)
                if toks[1].starts_with('@') {
                    let u = match toks.as_slice() {
                        [_, _, word, u] if word == "units" && u.bytes().all(|b| b.is_ascii_digit()) => u.parse::<u32>().ok(),
                        _ => return bad(ln, "a length given by a count is `length @<name> units <u>`"),
                    };
                    let u = match u.filter(|u| (1..=65535).contains(u)) {
                        Some(u) => u,
                        None => return bad(ln, "the size of a unit is 1 to 65535 bits"),
                    };
                    let id = self.count_ref(&toks[1], &toks[1][1..], ln)?;
                    let body = self.block(ln, "length")?;
                    return Ok(Some(SeqLine::Length { len: 0, in_bits: u % 8 != 0, plus: 0, body, units: Some((id, u)) }));
                }
                let len = value_len(&toks[1], ln)?;
                let (mut unit, mut plus, mut whole): (Option<bool>, Option<i64>, bool) = (None, None, false);
                let mut i = 2;
                while i < toks.len() {
                    match toks[i].as_str() {
                        "bytes" if unit.is_none() => unit = Some(false),
                        "bits" if unit.is_none() => unit = Some(true),
                        "whole" if !whole => whole = true,
                        "plus" if plus.is_none() => {
                            i += 1;
                            // integer text (ruling 2c of 0.11)
                            plus = Some(match toks.get(i).and_then(|t| int_text(t)) {
                                Some(n) => n,
                                None => return bad(ln, "`plus` needs an integer"),
                            });
                        }
                        o => return bad(ln, format!("unknown or repeated length option `{}`", o)),
                    }
                    i += 1;
                }
                let (in_bits, plus) = (unit.unwrap_or(false), plus.unwrap_or(0));
                if whole {
                    if in_bits {
                        return bad(ln, "`length ... whole` counts the message in bytes");
                    }
                    SeqLine::Whole { len, plus }
                } else {
                    SeqLine::Length { len, in_bits, plus, body: self.block(ln, "length")?, units: None }
                }
            }
            "group" => {
                let rep = match (toks.get(2).map(|s| s.as_str()), toks.len()) {
                    // `count @<name>`: the count of an earlier `count` line (engine-spec v0.21)
                    // `count @<a> @<b>`: two counts of one list (engine-spec v0.31)
                    (Some("count"), n) if n >= 4 && toks[3..].iter().any(|t| t.starts_with('@')) => {
                        let refs = &toks[3..];
                        if refs.len() > 2 {
                            return bad(ln, "`count @<name>` takes at most two names");
                        }
                        let mut ids = Vec::new();
                        for t in refs {
                            let name = match t.strip_prefix('@') {
                                Some(n) if !n.is_empty() => n,
                                _ => return bad(ln, format!("`{}` after `count` is not `@<name>`", t)),
                            };
                            if refs.iter().filter(|o| *o == t).count() > 1 {
                                return bad(ln, format!("`{}` is named twice on one group", t));
                            }
                            ids.push(self.count_ref(t, name, ln)?);
                        }
                        Rep::Named(ids)
                    }
                    (Some("count"), 4) => Rep::Count(value_len(&toks[3], ln)?),
                    // engine-spec v0.19: SEQUENCE OF
                    (Some("size"), 3 | 5) => {
                        self.uper_line.get_or_insert(ln);
                        Rep::Size(match toks.len() {
                            3 => None,
                            _ => Some(crate::uper::size(&toks[3], &toks[4]).ok_or_else(|| Error {
                                msg: format!("bad-directive: line {}: `size` needs <lb> <ub> with 0 <= lb <= ub < 65536", ln),
                            })?),
                        })
                    }
                    (Some("while"), 3) => Rep::While,
                    (Some("more"), 3) => Rep::More,
                    (Some("fx"), 3) => Rep::Fx,
                    (Some("rest"), 3) => Rep::Rest,
                    (Some("last"), 3) => Rep::Last,
                    (Some(l), _) if l.contains(':') => {
                        return bad(ln, format!("`{}` is a positional locator; a sequential group is `count <len>`, `while`, `more` or `fx`", l));
                    }
                    _ => return bad(ln, "group needs <list> and one of `count <len>`, `count @<name>`, `while`, `more`, `fx`, `rest` or `last`"),
                };
                SeqLine::Group(SeqGroup { list: toks[1].clone(), rep, body: self.body(false, ln)?, line: ln })
            }
            "ext" => {
                if toks.len() != 1 {
                    return bad(ln, "`ext` takes no argument");
                }
                self.uper_line.get_or_insert(ln);
                let body = self.block(ln, "ext")?;
                // ruling 15 of 0.19: a `presence` line, when there is one, is the first line
                if body.iter().skip(1).any(|l| matches!(l, SeqLine::Presence { .. })) {
                    return bad(ln, "inside an `ext` block a `presence` line is the first line");
                }
                SeqLine::Ext { body }
            }
            "choice" => {
                let ext = match (toks.len(), toks.get(2).map(|s| s.as_str())) {
                    (2, _) => false,
                    (3, Some("ext")) => true,
                    _ => return bad(ln, "choice needs <n> [ext]"),
                };
                let n = match crate::uper::num(&toks[1]) {
                    Some(n) if (1..=65536).contains(&n) => n as u32,
                    _ => return bad(ln, format!("`choice {}`: <n> is 1 to 65536", toks[1])),
                };
                self.uper_line.get_or_insert(ln);
                let mut alts: Vec<(u32, Vec<SeqLine>)> = Vec::new();
                loop {
                    let (l, t) = match self.peek() {
                        Some((l, t)) => (*l, t),
                        None => return bad(ln, "the `choice` block has no `end`"),
                    };
                    match t[0].as_str() {
                        "end" => {
                            if t.len() != 1 {
                                return bad(l, "`end` takes no argument");
                            }
                            self.i += 1;
                            break;
                        }
                        "alt" => {
                            let i = match (t.len(), t.get(1).and_then(|s| crate::uper::num(s))) {
                                (2, Some(i)) if (0..n as i64).contains(&i) => i as u32,
                                _ => return bad(l, format!("`alt` needs an index from 0 to {}", n - 1)),
                            };
                            if alts.iter().any(|(a, _)| *a == i) {
                                return bad(l, format!("`alt {}` given twice", i));
                            }
                            self.i += 1;
                            alts.push((i, self.alt_block()?));
                        }
                        _ => return bad(l, "a line between `choice` and its first `alt`"),
                    }
                }
                if alts.is_empty() {
                    return bad(ln, "a `choice` with no `alt`");
                }
                SeqLine::Choice { n, ext, alts }
            }
            "alt" => return bad(ln, "`alt` outside a `choice`"),
            "switch" => SeqLine::Switch(self.switch(ln, toks)?),
            // engine-spec v0.21: a named count, written after its group is laid out
            "count" => {
                if toks.len() < 3 {
                    return bad(ln, "count needs <name> <len> [plus <n>]");
                }
                let name = &toks[1];
                // names as presence names are: no `.`, `!` or `@` (ruling 24 of 0.21)
                if name.is_empty() || name.contains(['.', '!', '@']) {
                    return bad(ln, format!("`{}` is not a count name", name));
                }
                let len = value_len(&toks[2], ln)?;
                let plus = match &toks[3..] {
                    [] => 0,
                    [p, n] if p == "plus" => plus_value(n, ln)?,
                    _ => return bad(ln, "a `count` line takes only `plus <n>`, once"),
                };
                // one namespace with presences (ruling 15 of 0.21, ruling 12 of 0.8);
                // common lines and kinds are one block, and a kind's names end
                // with the kind, so two kinds may each declare it (rulings 25, 36)
                if self.names[self.block_start..].iter().any(|(n, _, _)| n == name) {
                    return bad(ln, format!("`{}` is declared twice in one block", name));
                }
                let id = self.next_id;
                self.next_id += 1;
                // ids are shared with presences: keep the per-id tables aligned
                self.named.push(Vec::new());
                self.case_named.push(Vec::new());
                self.case_depth.push(self.case_ifs.len());
                self.names.push((name.clone(), id, Named::Count(self.body_depth)));
                SeqLine::Count { id, len, plus, line: ln }
            }
            // engine-spec v0.34: where it may stand is checked after the file is read
            "inner" => {
                if toks.len() != 2 && toks.len() != 3 {
                    return bad(ln, "inner needs <format> [partial | run]");
                }
                let partial = toks.get(2).is_some_and(|t| t == "partial");
                let run = toks.get(2).is_some_and(|t| t == "run");
                SeqLine::Inner {
                    format: toks[1].clone(),
                    partial,
                    run,
                    bad_arg: toks.len() == 3 && !partial && !run,
                    line: ln,
                    reach: Vec::new(),
                    withs: Vec::new(),
                }
            }
            "case" | "else" => return bad(ln, format!("`{}` outside a `switch`", toks[0])),
            "fx" => return bad(ln, "`fx` outside a `chain`"),
            "also" => return bad(ln, "`also` stands directly after a `field` line"),
            "end" => return bad(ln, "`end` with no open block"),
            d @ ("kind" | "when" | "requires") => {
                return bad(ln, format!("`{}` is not allowed inside an `if`, `opt`, `chain`, `length` or `switch` block", d));
            }
            d if HEADER.contains(&d) => return bad(ln, format!("`{}` is not allowed inside a block", d)),
            // engine-spec v0.18: `element` is a line of an `xml` pack
            "element" => return bad(ln, "`element` is valid only on the xml wire"),
            other => return err(format!("unknown-directive: line {}: `{}` is not a directive of a pack", ln, other)),
        }))
    }
}

/// Ruling 23 of 0.8: a list is mapped by two groups of one scope (the common
/// lines with one kind's, of a message or of a group body) only when the two
/// groups sit in different `if` or `opt` blocks: each in a block that does
/// not hold the other.
fn check_lists(body: &SeqBody) -> Result<(), Error> {
    /// (list, line, the `if` and `opt` blocks around the group, outermost first)
    type Found<'a> = Vec<(&'a str, usize, Vec<usize>)>;
    fn walk<'a>(lines: &'a [SeqLine], blocks: &mut Vec<usize>, next: &mut usize, out: &mut Found<'a>) -> Result<(), Error> {
        for l in lines {
            match l {
                SeqLine::If { body, .. } | SeqLine::Opt { body } => {
                    *next += 1;
                    blocks.push(*next);
                    walk(body, blocks, next, out)?;
                    blocks.pop();
                }
                SeqLine::Length { body, .. } | SeqLine::Ext { body } => walk(body, blocks, next, out)?,
                SeqLine::Chain { parts, .. } => {
                    for part in parts {
                        walk(part, blocks, next, out)?;
                    }
                }
                // each `alt` is a block of its own, as an `if` is
                SeqLine::Choice { alts, .. } => {
                    for (_, body) in alts {
                        *next += 1;
                        blocks.push(*next);
                        walk(body, blocks, next, out)?;
                        blocks.pop();
                    }
                }
                SeqLine::Group(g) => {
                    out.push((&g.list, g.line, blocks.clone()));
                    check_lists(&g.body)?;
                }
                // two cases are different blocks (ruling 10 of 0.20)
                SeqLine::Switch(sw) => {
                    for c in sw.bodies() {
                        *next += 1;
                        blocks.push(*next);
                        walk(&c.lines, blocks, next, out)?;
                        blocks.pop();
                    }
                }
                _ => {}
            }
        }
        Ok(())
    }
    fn check(groups: &Found) -> Result<(), Error> {
        for (i, (list, line, blocks)) in groups.iter().enumerate() {
            for (other, _, others) in &groups[..i] {
                let n = blocks.len().min(others.len());
                // one group lies in every block the other lies in
                if other == list && blocks[..n] == others[..n] {
                    return bad(*line, format!("list `{}` is mapped by two groups of one scope that are not in different `if` or `opt` blocks", list));
                }
            }
        }
        Ok(())
    }
    let mut next = 0usize;
    let mut common: Found = Vec::new();
    walk(&body.common, &mut Vec::new(), &mut next, &mut common)?;
    check(&common)?;
    for k in &body.kinds {
        let mut scope = common.clone();
        walk(&k.lines, &mut Vec::new(), &mut next, &mut scope)?;
        if scope.len() > common.len() {
            check(&scope)?;
        }
    }
    Ok(())
}

/// The fewest and the most groups that reference count `id` on one reading
/// path through `lines` (ruling 2 of 0.21): a switch is one of its cases.
/// Group bodies are not entered: a reference there is refused as it is read
/// (ruling 9).
fn count_refs(lines: &[SeqLine], id: usize) -> (usize, usize) {
    let mut at = (0, 0);
    let add = |at: &mut (usize, usize), r: (usize, usize)| {
        at.0 += r.0;
        at.1 += r.1;
    };
    for l in lines {
        match l {
            SeqLine::Group(g) if matches!(&g.rep, Rep::Named(ids) if ids.contains(&id)) => add(&mut at, (1, 1)),
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
                // `length @` is a reference as a group is (ruling 1 of 0.83)
                if matches!(l, SeqLine::Length { units: Some((u, _)), .. } if *u == id) {
                    add(&mut at, (1, 1));
                }
                add(&mut at, count_refs(body, id))
            }
            SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| add(&mut at, count_refs(p, id))),
            // reading paths split only at kinds and switch cases (ruling 33 of
            // 0.21): the `alt`s of a 0.19 `choice` count as `if` blocks do
            SeqLine::Choice { alts, .. } => alts.iter().for_each(|(_, p)| add(&mut at, count_refs(p, id))),
            SeqLine::Switch(sw) => {
                let rs: Vec<(usize, usize)> = sw.bodies().map(|c| count_refs(&c.lines, id)).collect();
                let lo = rs.iter().map(|r| r.0).min().unwrap_or(0);
                let hi = rs.iter().map(|r| r.1).max().unwrap_or(0);
                add(&mut at, (lo, hi));
            }
            _ => {}
        }
    }
    at
}

/// Every `count` line is referenced by exactly one group on each reading
/// path that holds it (rulings 2 and 12 of 0.21). `tail`: the reading paths
/// after `lines` that still see their names, as (fewest, most) for one count.
fn check_counts_lines(lines: &[SeqLine], tail: &dyn Fn(usize) -> (usize, usize)) -> Result<(), Error> {
    for (i, l) in lines.iter().enumerate() {
        match l {
            SeqLine::Count { id, line, .. } => {
                let (a, b) = count_refs(&lines[i + 1..], *id);
                let (c, d) = tail(*id);
                let (lo, hi) = (a + c, b + d);
                if lo == 0 {
                    return bad(*line, "the count is not referenced by a `group … count @` or `length @` line on every reading path");
                }
                if hi > 1 {
                    return bad(*line, "the count is referenced twice on one reading path");
                }
            }
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
                check_counts_lines(body, &|_| (0, 0))?
            }
            // each `alt` is a block of its own for names (ruling 21 of 0.19)
            SeqLine::Choice { alts, .. } => {
                for (_, part) in alts {
                    check_counts_lines(part, &|_| (0, 0))?;
                }
            }
            SeqLine::Chain { parts, .. } => {
                // a chain is one block for names: a count sees the parts after its own
                for (k, part) in parts.iter().enumerate() {
                    let later = &parts[k + 1..];
                    check_counts_lines(part, &|id| {
                        later.iter().fold((0, 0), |at, p| {
                            let r = count_refs(p, id);
                            (at.0 + r.0, at.1 + r.1)
                        })
                    })?;
                }
            }
            SeqLine::Switch(sw) => {
                for c in sw.bodies() {
                    check_counts_lines(&c.lines, &|_| (0, 0))?;
                }
            }
            SeqLine::Group(g) => check_counts(&g.body)?,
            _ => {}
        }
    }
    Ok(())
}

fn check_counts(body: &SeqBody) -> Result<(), Error> {
    // a count among the common lines is seen by every kind: one path per kind
    let kinds = |id: usize| {
        let rs: Vec<(usize, usize)> = body.kinds.iter().map(|k| count_refs(&k.lines, id)).collect();
        (rs.iter().map(|r| r.0).min().unwrap_or(0), rs.iter().map(|r| r.1).max().unwrap_or(0))
    };
    check_counts_lines(&body.common, &kinds)?;
    for k in &body.kinds {
        check_counts_lines(&k.lines, &|_| (0, 0))?;
    }
    Ok(())
}

/// Does a line read or write bits of the wire? `default` and `requires` are
/// not lines here; a block is a wire line when it reads a bit of its own or
/// holds one (ruling 11 of 0.21).
fn wire_line(l: &SeqLine) -> bool {
    match l {
        SeqLine::If { body, .. } => body.iter().any(wire_line),
        SeqLine::Switch(sw) => sw.bodies().any(|c| c.lines.iter().any(wire_line)),
        SeqLine::Chain { parts, ends_fx } => *ends_fx || parts.len() > 1 || parts.iter().flatten().any(wire_line),
        // a `choice` reads its index unless it has one root alternative and
        // no extension bit (engine-spec v0.19); an `ext` always reads its bit
        SeqLine::Choice { n, ext, alts } => *ext || *n > 1 || alts.iter().any(|(_, p)| p.iter().any(wire_line)),
        _ => true,
    }
}

/// A `rest` group is the last line of its extent (rulings 10 and 11 of
/// 0.21). `after`: some wire line follows `lines` in the same extent on a
/// reading path; `allow`: a `rest` may stand in this extent here.
fn check_rest_lines(lines: &[SeqLine], after: bool, allow: bool) -> Result<(), Error> {
    for (i, l) in lines.iter().enumerate() {
        let after = after || lines[i + 1..].iter().any(wire_line);
        match l {
            // engine-spec v0.34: `inner` is the last wire line of its extent, as a `rest` group is
            SeqLine::Inner { format, line, .. } if after => {
                return bad(*line, format!("`inner {}` is not the last line of its extent", format));
            }
            SeqLine::Group(g) => {
                if g.rep == Rep::Rest {
                    if !allow {
                        return bad(g.line, format!("`group {} rest` inside an item stands only in a `length` block of the item or at the end of an outer `rest` item", g.list));
                    }
                    if after {
                        return bad(g.line, format!("`group {} rest` is not the last line of its extent", g.list));
                    }
                }
                // the item of a `rest` group may end in a `rest` of the same extent
                check_rest_body(&g.body, false, g.rep == Rep::Rest)?;
            }
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Ext { body } => check_rest_lines(body, after, allow)?,
            // one `alt` is read, as one case of a switch (engine-spec v0.19)
            SeqLine::Choice { alts, .. } => {
                for (_, part) in alts {
                    check_rest_lines(part, after, allow)?;
                }
            }
            SeqLine::Chain { parts, ends_fx } => {
                for (k, part) in parts.iter().enumerate() {
                    let more = after || k + 1 < parts.len() || *ends_fx;
                    check_rest_lines(part, more, allow)?;
                }
            }
            SeqLine::Switch(sw) => {
                for c in sw.bodies() {
                    check_rest_lines(&c.lines, after, allow)?;
                }
            }
            // a `length` block is an extent of its own
            SeqLine::Length { body, .. } => check_rest_lines(body, false, true)?,
            _ => {}
        }
    }
    Ok(())
}

fn check_rest_body(body: &SeqBody, after: bool, allow: bool) -> Result<(), Error> {
    // a kind's `when` lines are wire lines after the common lines
    let kinds_wire = body.kinds.iter().any(|k| !k.whens.is_empty() || k.lines.iter().any(wire_line));
    check_rest_lines(&body.common, after || kinds_wire, allow)?;
    for k in &body.kinds {
        check_rest_lines(&k.lines, after, allow)?;
    }
    Ok(())
}

/// Engine-spec v0.30 (load errors, ruling 9): in one reading path (the
/// common lines plus one kind, one case of each switch) no two `when … as`
/// lines name one key, and no `field` or `also` line maps a key an `as` names.
/// Each group body is checked as a scope of its own.
fn check_as(body: &SeqBody) -> Result<(), Error> {
    /// the keys `field` and `also` lines of `lines` map, outside nested
    /// groups (any case of a switch: each lies on some reading path), and the
    /// `as` lines; nested group bodies are checked on the way
    fn walk<'a>(lines: &'a [SeqLine], fields: &mut Vec<&'a str>, ases: &mut Vec<(&'a str, usize)>) -> Result<(), Error> {
        for l in lines {
            match l {
                SeqLine::Field { f, also, .. } => {
                    fields.push(&f.model_key);
                    fields.extend(also.iter().map(|a| a.model_key.as_str()));
                }
                SeqLine::When(SeqWhen { key: Some(k), line, .. }) => ases.push((k, *line)),
                SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
                    walk(body, fields, ases)?
                }
                SeqLine::Chain { parts, .. } => {
                    for part in parts {
                        walk(part, fields, ases)?;
                    }
                }
                SeqLine::Choice { alts, .. } => {
                    for (_, part) in alts {
                        walk(part, fields, ases)?;
                    }
                }
                SeqLine::Switch(sw) => {
                    for c in sw.bodies() {
                        walk(&c.lines, fields, ases)?;
                    }
                }
                SeqLine::Group(g) => check_as(&g.body)?,
                _ => {}
            }
        }
        Ok(())
    }
    fn path(fields: &[&str], ases: &[(&str, usize)]) -> Result<(), Error> {
        for (i, (k, line)) in ases.iter().enumerate() {
            if let Some((_, first)) = ases[..i].iter().find(|(o, _)| o == k) {
                return bad(*line, format!("`as {}`: the key is named by the `as` of line {} in the same reading path", k, first));
            }
            if fields.contains(k) {
                return bad(*line, format!("`as {}`: the key is also mapped by a `field` or `also` line in the same reading path", k));
            }
        }
        Ok(())
    }
    let (mut fields, mut ases) = (Vec::new(), Vec::new());
    walk(&body.common, &mut fields, &mut ases)?;
    path(&fields, &ases)?;
    for k in &body.kinds {
        let (mut kf, mut ka) = (fields.clone(), ases.clone());
        ka.extend(k.whens.iter().filter_map(|w| w.key.as_deref().map(|key| (key, w.line))));
        walk(&k.lines, &mut kf, &mut ka)?;
        path(&kf, &ka)?;
    }
    Ok(())
}

/// Engine-spec v0.33: the window of every `when … at` is fixed in its kind.
/// Walking the kind's lines from its first, the lines that occupy no bits
/// skipped, every line up to the one that reaches the window's end is a plain
/// `when`, `const`, `pad`, or a `field` (with its `also` lines) whose locator
/// is a bit length. Sets each kind's `prefix`: how many of its lines the
/// windows cover. Group bodies are checked on the way.
fn check_windows(body: &mut SeqBody) -> Result<(), Error> {
    fn nested(lines: &mut [SeqLine]) -> Result<(), Error> {
        for l in lines {
            match l {
                SeqLine::Group(g) => check_windows(&mut g.body)?,
                SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => nested(body)?,
                SeqLine::Chain { parts, .. } => {
                    for p in parts {
                        nested(p)?;
                    }
                }
                SeqLine::Choice { alts, .. } => {
                    for (_, p) in alts {
                        nested(p)?;
                    }
                }
                SeqLine::Switch(sw) => {
                    for c in sw.bodies_mut() {
                        nested(&mut c.lines)?;
                    }
                }
                _ => {}
            }
        }
        Ok(())
    }
    nested(&mut body.common)?;
    for k in &mut body.kinds {
        let mut prefix = 0;
        for w in k.whens.iter().filter(|w| w.at.is_some()) {
            let end = w.at.unwrap_or(0) as u128 + w.len as u128;
            let mut sum: u128 = 0;
            let mut walked = 0;
            // the kind's plain `when` lines are its first lines
            for p in k.whens.iter().filter(|p| p.at.is_none()) {
                if sum >= end {
                    break;
                }
                sum += p.len as u128;
            }
            while sum < end {
                let l = match k.lines.get(walked) {
                    Some(l) => l,
                    None => return bad(w.line, "the window of `at` ends past the kind's last line, so it is not fixed in the kind"),
                };
                sum += match l {
                    SeqLine::Field { len, uper: None, f, .. } if f.until.is_none() => *len as u128,
                    SeqLine::Const { len, .. } => *len as u128,
                    SeqLine::Pad { len } => *len as u128,
                    _ => return bad(w.line, "the window of `at` is not fixed in the kind: a line of variable width comes before its end"),
                };
                walked += 1;
            }
            prefix = prefix.max(walked);
        }
        k.prefix = prefix;
        nested(&mut k.lines)?;
    }
    Ok(())
}

/// Engine-spec v0.34: where an `inner` line may stand. In the common lines,
/// in a kind and inside `length` blocks at any depth; anywhere else
/// `bad-directive`. At most one on any reading path (ruling 33 of 0.21).
/// The last-line rule is checked with `rest` (`check_rest_lines`).
fn check_inner(body: &SeqBody) -> Result<(), Error> {
    /// every `inner` line under a block it may not stand in
    fn misplaced(lines: &[SeqLine], allowed: bool) -> Option<usize> {
        lines.iter().find_map(|l| match l {
            SeqLine::Inner { line, .. } if !allowed => Some(*line),
            SeqLine::Length { body, .. } => misplaced(body, allowed),
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Ext { body } => misplaced(body, false),
            SeqLine::Chain { parts, .. } => parts.iter().find_map(|p| misplaced(p, false)),
            SeqLine::Choice { alts, .. } => alts.iter().find_map(|(_, p)| misplaced(p, false)),
            SeqLine::Switch(sw) => sw.bodies().find_map(|c| misplaced(&c.lines, false)),
            SeqLine::Group(g) => {
                misplaced(&g.body.common, false).or_else(|| g.body.kinds.iter().find_map(|k| misplaced(&k.lines, false)))
            }
            _ => None,
        })
    }
    if let Some(ln) = misplaced(&body.common, true).or_else(|| body.kinds.iter().find_map(|k| misplaced(&k.lines, true))) {
        return bad(ln, "`inner` stands only in the common lines, in a kind or inside `length` blocks");
    }
    /// the first `inner` line whose second argument is not `partial`
    fn bad_arg(lines: &[SeqLine]) -> Option<usize> {
        lines.iter().find_map(|l| match l {
            SeqLine::Inner { bad_arg: true, line, .. } => Some(*line),
            SeqLine::Length { body, .. } => bad_arg(body),
            _ => None,
        })
    }
    if let Some(ln) = bad_arg(&body.common).or_else(|| body.kinds.iter().find_map(|k| bad_arg(&k.lines))) {
        return bad(ln, "the second argument of `inner` is `partial` or `run`");
    }
    /// the `inner` lines of these lines, `length` blocks entered, in line order
    fn found(lines: &[SeqLine], out: &mut Vec<usize>) {
        for l in lines {
            match l {
                SeqLine::Inner { line, .. } => out.push(*line),
                SeqLine::Length { body, .. } => found(body, out),
                _ => {}
            }
        }
    }
    let mut common = Vec::new();
    found(&body.common, &mut common);
    if common.len() > 1 {
        return bad(common[1], "a second `inner` line on one reading path");
    }
    for k in &body.kinds {
        let mut path = common.clone();
        found(&k.lines, &mut path);
        if path.len() > 1 {
            return bad(path[1], format!("a second `inner` line on one reading path (kind `{}`)", k.name));
        }
    }
    Ok(())
}

/// Engine-spec v0.92, ruling 16: in a pack with `framing self` a `rest` group
/// whose extent is the message stands after a `length … whole` line that is
/// read whenever the `rest` is. A `rest` of an item is judged by its group's.
fn check_framing(body: &SeqBody) -> Result<(), Error> {
    /// `whole`: such a line stands before `lines`; gives whether one does after them
    fn walk(lines: &[SeqLine], mut whole: bool) -> Result<bool, Error> {
        for l in lines {
            match l {
                SeqLine::Whole { .. } => whole = true,
                SeqLine::Group(g) if g.rep == Rep::Rest && !whole => {
                    return bad(g.line, format!("`group {} rest` of a pack with `framing self` needs a `length … whole` line read before it", g.list));
                }
                SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Ext { body } => {
                    walk(body, whole)?;
                }
                // a part is read only after the parts before it
                SeqLine::Chain { parts, .. } => {
                    let mut w = whole;
                    for p in parts {
                        w = walk(p, w)?;
                    }
                }
                SeqLine::Choice { alts, .. } => {
                    for (_, p) in alts {
                        walk(p, whole)?;
                    }
                }
                SeqLine::Switch(sw) => {
                    for c in sw.bodies() {
                        walk(&c.lines, whole)?;
                    }
                }
                // a `length` block is an extent of its own
                _ => {}
            }
        }
        Ok(whole)
    }
    let whole = walk(&body.common, false)?;
    for k in &body.kinds {
        walk(&k.lines, whole)?;
    }
    Ok(())
}

/// The keys `with` names on the lines of a body, as entries of `model_keys`:
/// a key, or a list of that name.
fn with_keys(body: &SeqBody, prefix: &str, out: &mut Vec<String>) {
    fn lines(ls: &[SeqLine], prefix: &str, out: &mut Vec<String>) {
        for l in ls {
            match l {
                SeqLine::Field { f, .. } => {
                    if let Some((k, _)) = &f.with {
                        out.push(format!("{}{}", prefix, k));
                        out.push(format!("{}{}[]", prefix, k));
                    }
                }
                SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => lines(body, prefix, out),
                SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| lines(p, prefix, out)),
                SeqLine::Choice { alts, .. } => alts.iter().for_each(|(_, p)| lines(p, prefix, out)),
                SeqLine::Switch(sw) => sw.bodies().for_each(|c| lines(&c.lines, prefix, out)),
                SeqLine::Group(g) => with_keys(&g.body, &format!("{}{}[].", prefix, g.list), out),
                _ => {}
            }
        }
    }
    lines(&body.common, prefix, out);
    for k in &body.kinds {
        lines(&k.lines, prefix, out);
    }
}

/// Does one of these lines, `length` blocks entered, hold an `inner … run`?
/// Gives its format (engine-spec v0.92).
#[cfg(feature = "bits")]
fn run_in(lines: &[SeqLine]) -> Option<&str> {
    lines.iter().find_map(|l| match l {
        SeqLine::Inner { run: true, format, .. } => Some(format.as_str()),
        SeqLine::Length { body, .. } => run_in(body),
        _ => None,
    })
}

/// Is this the body of a carrier pack (engine-spec v0.92)?
#[cfg(feature = "bits")]
pub(crate) fn is_carrier(body: &SeqBody) -> bool {
    run_in(&body.common).is_some() || body.kinds.iter().any(|k| run_in(&k.lines).is_some())
}

/// Set the lines in reach of each `inner` line (ruling 20 of 0.52): of one in
/// a kind the common lines and that kind's; of one in the common lines, these
/// and the lines of every kind. Run on a pack `check_inner` accepted.
fn set_reach(body: &mut SeqBody) {
    fn set(lines: &mut [SeqLine], keys: &[String], with: &[String]) {
        for l in lines {
            match l {
                SeqLine::Inner { reach, withs, run, .. } => {
                    *reach = keys.to_vec();
                    if *run {
                        *withs = with.to_vec();
                    }
                }
                SeqLine::Length { body, .. } => set(body, keys, with),
                _ => {}
            }
        }
    }
    fn holds(lines: &[SeqLine]) -> bool {
        lines.iter().any(|l| match l {
            SeqLine::Inner { .. } => true,
            SeqLine::Length { body, .. } => holds(body),
            _ => false,
        })
    }
    if holds(&body.common) {
        let mut keys = Vec::new();
        let mut with = Vec::new();
        body.model_keys("", &mut keys);
        with_keys(body, "", &mut with);
        set(&mut body.common, &keys, &with);
    }
    let common = &body.common;
    for k in body.kinds.iter_mut().filter(|k| holds(&k.lines)) {
        let path = SeqBody { common: common.clone(), kinds: vec![k.clone()], ..Default::default() };
        let mut keys = Vec::new();
        let mut with = Vec::new();
        path.model_keys("", &mut keys);
        with_keys(&path, "", &mut with);
        set(&mut k.lines, &keys, &with);
    }
}

/// Every `inner` line of a body: (format, line), in line order.
pub(crate) fn inner_lines(body: &SeqBody) -> Vec<(&str, usize)> {
    fn walk<'a>(lines: &'a [SeqLine], out: &mut Vec<(&'a str, usize)>) {
        for l in lines {
            match l {
                SeqLine::Inner { format, line, .. } => out.push((format, *line)),
                SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => walk(body, out),
                SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| walk(p, out)),
                SeqLine::Choice { alts, .. } => alts.iter().for_each(|(_, p)| walk(p, out)),
                SeqLine::Switch(sw) => sw.bodies().for_each(|c| walk(&c.lines, out)),
                SeqLine::Group(g) => {
                    walk(&g.body.common, out);
                    g.body.kinds.iter().for_each(|k| walk(&k.lines, out));
                }
                _ => {}
            }
        }
    }
    let mut out = Vec::new();
    walk(&body.common, &mut out);
    body.kinds.iter().for_each(|k| walk(&k.lines, &mut out));
    out
}

/// Parse a `layout sequential` pack.
pub fn parse(text: &str) -> Result<Pack, Error> {
    let mut lines: Vec<(usize, Vec<String>)> = Vec::new();
    for (lineno, raw) in text.lines().enumerate() {
        let toks = tokenize(raw)?;
        if !toks.is_empty() {
            lines.push((lineno + 1, toks));
        }
    }
    let mut p = Parser {
        lines: &lines,
        i: 0,
        next_id: 0,
        names: Vec::new(),
        body_depth: 0,
        block_start: 0,
        named: Vec::new(),
        case_named: Vec::new(),
        case_ifs: Vec::new(),
        case_depth: Vec::new(),
        mapped: Vec::new(),
        defaults: Vec::new(),
        as_err: None,
        at_form: None,
        framing: None,
        framing_err: None,
        vias: Vec::new(),
        format: None,
        version: None,
        wire: None,
        order: BitOrder::Lsb,
        distribution: None,
        sources: Vec::new(),
        uses: Vec::new(),
        maps: Vec::new(),
        armor: Default::default(),
        encoding: Default::default(),
        charsets: Default::default(),
        uper_line: None,
        to_cot: BTreeMap::new(),
        from_cot: BTreeMap::new(),
    };
    let mut body = p.body(true, 0)?;
    // engine-spec v0.33: the `at` form, then the fixed windows, both raised
    // after the key passes (ruling 10)
    let windows = check_windows(&mut body);
    body.at_err = p.at_form.take().or(windows.err());
    type Named<'n> = (&'n [Vec<u32>], &'n [Vec<u32>]);
    fn fill(lines: &mut [SeqLine], named: Named) {
        for l in lines {
            match l {
                SeqLine::Presence { id, named: n, in_cases, .. } => {
                    *n = named.0[*id].clone();
                    *in_cases = named.1[*id].clone();
                }
                SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => fill(body, named),
                SeqLine::Chain { parts, .. } => parts.iter_mut().for_each(|p| fill(p, named)),
                SeqLine::Choice { alts, .. } => alts.iter_mut().for_each(|(_, p)| fill(p, named)),
                SeqLine::Group(g) => fill_body(&mut g.body, named),
                SeqLine::Switch(sw) => sw.bodies_mut().for_each(|c| fill(&mut c.lines, named)),
                _ => {}
            }
        }
    }
    fn fill_body(b: &mut SeqBody, named: Named) {
        fill(&mut b.common, named);
        b.kinds.iter_mut().for_each(|k| fill(&mut k.lines, named));
    }
    fill_body(&mut body, (&p.named, &p.case_named));
    check_lists(&body)?;
    // after the file is read (ruling 5b of 0.11): the missing header lines first
    if p.format.is_none() {
        return err("missing-format: the pack has no `format` line");
    }
    if p.version.is_none() {
        return err("missing-version: the pack has no `version` line");
    }
    check_counts(&body)?;
    // engine-spec v0.34: the block and path checks of `inner`, then its last-line check
    check_inner(&body)?;
    set_reach(&mut body);
    check_rest_body(&body, false, true)?;
    match p.wire.as_deref() {
        Some("bits") => {}
        Some(_) => return err("bad-directive: `layout` is valid only on a bits wire"),
        None => return err("missing-wire: the pack has no `wire` line"),
    }
    // engine-spec v0.30: the syntax of `as`, then the bans of ruling 9 (ruling 29)
    if let Some(e) = p.as_err.take() {
        return Err(e);
    }
    check_as(&body)?;
    // `armor sixbit` and `encoding uper` need `bit_order msb` (0.14, 0.19); `msb-lsb` is not `msb`
    let armor = p.armor.check(true, p.order == BitOrder::Msb)?;
    // engine-spec v0.19: `encoding uper`, and the lines only it allows (ruling 9)
    let uper = p.encoding.check(true, true, p.order == BitOrder::Msb, armor == crate::armor::Armor::Sixbit)?;
    if let (false, Some(ln)) = (uper, p.uper_line) {
        return bad(ln, "a UPER locator, `ext`, `choice` or `group ... size` needs `encoding uper`");
    }
    if armor == crate::armor::Armor::Sixbit {
        crate::armor::check_no_whole(&body)?;
    }
    // engine-spec v0.34: no `inner` line in a pack with `armor sixbit` or `encoding uper` (`armor hex` is the default)
    // engine-spec v0.92, ruling 16
    if let Some(e) = p.framing_err.take() {
        return Err(e);
    }
    if let Some(ln) = p.framing {
        if armor == crate::armor::Armor::Sixbit || uper {
            return bad(ln, "`framing self` in a pack with `armor sixbit` or `encoding uper`");
        }
        check_framing(&body)?;
    }
    if let Some((format, ln)) = inner_lines(&body).first().filter(|_| armor == crate::armor::Armor::Sixbit || uper) {
        return bad(*ln, format!("`inner {}` in a pack with `armor sixbit` or `encoding uper`", format));
    }
    for (table, ln) in &p.vias {
        if !p.maps.iter().any(|(name, _)| name == table) {
            return bad(*ln, format!("`via {}` names a table with no `map` line", table));
        }
    }
    // engine-spec v0.46: the sets, then the transforms that name them (the
    // locator of such a field is its bit length)
    let sets = p.charsets.check(Wire::Bits)?;
    let mut given: Result<(), Error> = Ok(());
    body.visit_mut(
        &mut |f| {
            if given.is_ok() {
                let len = f.locator.parse().ok();
                given = charset::resolve(f, &sets, len, None);
            }
        },
        &mut |_| {},
    );
    given?;
    let format = p.format.expect("checked above");
    let distribution =
        p.distribution.ok_or(Error { msg: format!("missing-distribution: pack `{}` has no `distribution`", format) })?;
    if p.sources.is_empty() {
        return err(format!("missing-source: pack `{}` has no `source`", format));
    }
    Ok(Pack {
        format,
        version: p.version.expect("checked above"),
        wire: Wire::Bits,
        root: String::new(),
        word_bytes: 1,
        order: p.order,
        distribution,
        sources: p.sources,
        uses: p.uses,
        fields: Vec::new(),
        whens: Vec::new(),
        kinds: Vec::new(),
        consts: Vec::new(),
        defaults: Vec::new(),
        groups: Vec::new(),
        maps: p.maps,
        typemap_to_cot: p.to_cot,
        typemap_from_cot: p.from_cot,
        seq: Some(body),
        text: crate::text::TextConf::default(),
        tlv: crate::tlv::TlvConf::default(),
        cbor: crate::cbor::CborConf::default(),
        armor,
        gates: Vec::new(),
        elements: Vec::new(),
        uper,
        framing: p.framing.is_some(),
        at_err: None,
    })
}

// ---------------------------------------------------------------------------
// Decode
// ---------------------------------------------------------------------------

#[cfg(feature = "bits")]
pub(crate) struct Reader<'a> {
    pub(crate) p: &'a Pack,
    raw: &'a [u8],
    pub(crate) pos: u64,
    /// the first bit the lines may not read: the end of the input, of the
    /// message (`length ... whole`) or of the innermost `length` extent
    pub(crate) end: u64,
    /// the end of the message
    whole: u64,
    /// how many `length` blocks are open
    depth: usize,
    /// the bits of each presence read so far, by id; a bit not held is 0
    presence: BTreeMap<usize, Vec<bool>>,
    /// presence bits that are 1 and that only `if` lines of cases name:
    /// checked when the body that read them ends (engine-spec v0.20)
    /// (id, bit, when it was read)
    pending: Vec<(usize, u32, u64)>,
    /// per presence id: the bits named by the `if` lines of the cases read
    /// (id, bit, when the case was read)
    case_named: Vec<(usize, u32, u64)>,
    /// counts the presence lines read: orders the two lists above
    clock: u64,
    /// the bits an item of a `rest` group needs left: 8 when the innermost
    /// extent is counted in bytes, 1 in bits (engine-spec v0.21)
    unit: u64,
    /// per `count` line id: the number of items it states, None when the
    /// line lay at or past the end of a `length` extent (engine-spec v0.21)
    counts: HashMap<usize, Option<i128>>,
    /// the engine that finds the pack of an `inner` line (engine-spec v0.34);
    /// None: a codec called without an engine, where no format is loaded
    host: Option<&'a dyn InnerHost>,
    /// the lists an inner message gave the entity: no later group replaces them
    inner_lists: Vec<String>,
    /// the length the message states in bits, the smallest of several
    /// `length ... whole` lines (ruling 13 of 0.34)
    stated: Option<u64>,
    /// counts that state units whose `length @` block was not read, in the
    /// scopes being read (ruling 9 of 0.83)
    unread: Vec<usize>,
    /// a run operation (engine-spec v0.92): the messages of the run are kept
    /// here; None: `decode`, which reads a carrier of one message
    run: Option<&'a std::cell::RefCell<RunCapture>>,
    /// a message of a run: a `switch` on a key one of whose lines failed stops
    /// the decode, forgiven or not (ruling 3 of 0.92)
    strict: bool,
}

/// What a run operation reads of a carrier (engine-spec v0.92).
#[cfg(feature = "bits")]
#[derive(Default)]
pub(crate) struct RunCapture {
    /// the format of the `run` line reached
    pub format: Option<String>,
    /// a kind was selected with no `run` line in reach: an ordinary message
    pub ordinary: bool,
    /// each message: its failed lines not yet judged, or what stopped its
    /// decode, which ends the run
    pub messages: Vec<Result<Decoded, Error>>,
}

/// What a sequential layout needs of the engine for an `inner` line
/// (engine-spec v0.34).
#[cfg(feature = "bits")]
pub(crate) trait InnerHost {
    /// Checks 1 to 4 of "Reaching the `inner` line", in order; on a `run` line
    /// that of 0.92 between 2 and 3.
    fn inner_check(&self, outer: &Pack, format: &str, run: bool) -> Result<(), Error>;
    /// `decode(<format>, bytes)` of a pack that passed the checks. `held`:
    /// the lists the outer entity holds, which keep their items: the items
    /// of the inner lists of those names are not counted (7g of 0.11).
    /// Without `partial`, bytes after the message's end are `malformed-wire`.
    fn inner_decode(&self, format: &str, bytes: &[u8], partial: bool, held: Vec<String>) -> Result<Decoded, Error>;
    /// One message of a run (engine-spec v0.92), from the first of `bytes`: its
    /// entity, its failed lines not yet judged, and the byte it ends at.
    fn inner_message(&self, format: &str, bytes: &[u8]) -> Result<(Decoded, usize), Error>;
    /// `encode(<format>, entity)` as a layer: the inner kind chosen by
    /// `Entity.inner_kind`, then `Entity.kind`, then `requires`.
    fn inner_encode(&self, format: &str, ent: &Entity) -> Result<Vec<u8>, Error>;
    /// The fifth check (ruling 20 of 0.52): the first of `reach`, entries as
    /// `model_keys` gives them, that the inner pack maps too.
    fn inner_clash<'k>(&self, format: &str, reach: &'k [String]) -> Option<&'k String>;
}

/// The checks made when decode or encode reaches an `inner` line: with no
/// engine, no format is loaded.
#[cfg(feature = "bits")]
fn inner_host<'h>(
    host: Option<&'h dyn InnerHost>,
    outer: &Pack,
    format: &str,
    run: bool,
    reach: &[String],
    withs: &[String],
) -> Result<&'h dyn InnerHost, Error> {
    let h = host.ok_or_else(|| Error { msg: format!("unknown-format: no pack loaded for format `{}`", format) })?;
    h.inner_check(outer, format, run)?;
    // 5. no key of the lines in reach is a key of the inner pack
    if let Some(k) = h.inner_clash(format, reach) {
        return err(format!("bad-directive: format `{}`: `{}` is mapped by this pack and by the `inner` pack `{}`", outer.format, k, format));
    }
    // ruling 9 of 0.92
    if let Some(k) = h.inner_clash(format, withs) {
        return err(format!("bad-directive: format `{}`: `with` names `{}`, which the messages of the `{}` run map", outer.format, k, format));
    }
    Ok(h)
}

/// An error of an inner message keeps its kind and names both formats.
#[cfg(feature = "bits")]
fn inner_error(outer: &Pack, e: Error) -> Error {
    Error { msg: format!("{} (the `inner` message of format `{}`)", e.msg, outer.format) }
}

#[cfg(feature = "bits")]
impl<'a> Reader<'a> {
    #[cfg(feature = "bits")]
    pub(crate) fn short(&self, what: impl AsRef<str>) -> Error {
        Error { msg: format!("malformed-wire: format `{}`: {}", self.p.format, what.as_ref()) }
    }
    #[cfg(feature = "bits")]
    fn need(&self, len: u64, what: &str) -> Result<(), Error> {
        // `pos` may stand past `end` after a `length` block; nothing overflows
        if self.left() < len {
            let place = if self.depth > 0 && self.end <= self.whole { "the `length` extent" } else { "the input" };
            return Err(self.short(format!("{} ends before {} at bit {}", place, what, self.pos)));
        }
        Ok(())
    }
    /// The first bit no line may read: the end of the extent or of the
    /// message, whichever comes first (ruling 16 of 0.83).
    #[cfg(feature = "bits")]
    fn limit(&self) -> u64 {
        self.end.min(self.whole)
    }
    /// The bits of the message left at the cursor in its extent.
    #[cfg(feature = "bits")]
    pub(crate) fn left(&self) -> u64 {
        self.limit().saturating_sub(self.pos)
    }
    /// Does the cursor stand at or past the end of a `length` extent?
    #[cfg(feature = "bits")]
    fn past_extent(&self) -> bool {
        self.depth > 0 && self.pos >= self.end
    }
    /// The bits of the innermost extent after the cursor, past a `length …
    /// whole` read in it or not (ruling 16 of 0.83).
    #[cfg(feature = "bits")]
    fn stated_left(&self) -> u64 {
        if self.depth > 0 {
            self.end.saturating_sub(self.pos)
        } else {
            self.left()
        }
    }
    /// Read `body` in an extent that ends at `stop`, counted in units of
    /// `unit` bits; content of it no line reads is skipped.
    #[cfg(feature = "bits")]
    fn block(&mut self, body: &[SeqLine], stop: u64, unit: u64, d: &mut Decoded) -> Result<(), Error> {
        let outer = (self.end, self.unit);
        self.end = stop;
        self.unit = unit;
        self.depth += 1;
        let res = decode_lines(body, self, d);
        self.depth -= 1;
        self.pos = stop;
        (self.end, self.unit) = outer;
        if self.depth == 0 {
            // a `length … whole` read in the block ends the message
            self.end = self.end.min(self.whole);
        }
        res
    }
    /// These lines are not read: a count that states units and whose `length
    /// @` block is one of them is an error once its scope is read (ruling 9 of
    /// 0.83). Group bodies have counts of their own.
    #[cfg(feature = "bits")]
    fn skip_blocks(&mut self, lines: &[SeqLine]) {
        for l in lines {
            match l {
                SeqLine::Length { body, units, .. } => {
                    if let Some((id, _)) = units {
                        if self.counts.get(id).copied().flatten().map_or(false, |n| n != 0) {
                            self.unread.push(*id);
                        }
                    }
                    self.skip_blocks(body);
                }
                // a count line not read states nothing, an earlier item's value included
                SeqLine::Count { id, .. } => {
                    self.counts.insert(*id, None);
                }
                SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Ext { body } => self.skip_blocks(body),
                SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| self.skip_blocks(p)),
                SeqLine::Choice { alts, .. } => alts.iter().for_each(|(_, p)| self.skip_blocks(p)),
                SeqLine::Switch(sw) => sw.bodies().for_each(|c| self.skip_blocks(&c.lines)),
                _ => {}
            }
        }
    }
    /// `len` (1..=64) bits at the cursor as an unsigned value.
    #[cfg(feature = "bits")]
    pub(crate) fn read(&mut self, len: u32, what: &str) -> Result<u64, Error> {
        self.need(len as u64, what)?;
        let v = get_bits(self.raw, self.pos, len, self.p.order).unwrap_or(0);
        self.pos += len as u64;
        Ok(v)
    }
    #[cfg(feature = "bits")]
    fn bit(&self, c: &Cond) -> bool {
        let set = self.presence.get(&c.id).and_then(|b| b.get(c.bit as usize - 1)).copied().unwrap_or(false);
        set != c.neg
    }
    /// The indicator bit of a `while`, `more` or `fx` group, or an `fx` bit
    /// of a chain. At or after the end of a `length` extent it reads as 0
    /// (ruling 21 of 0.8); past the end of the input it is `malformed-wire`.
    #[cfg(feature = "bits")]
    fn indicator(&mut self, what: &str) -> Result<u64, Error> {
        if self.past_extent() {
            return Ok(0);
        }
        self.read(1, what)
    }
}

/// The kind of a body the wire selects, after its common lines: the first
/// whose `when` lines all hold, read from the cursor.
#[cfg(feature = "bits")]
fn decode_body<'a>(body: &'a SeqBody, r: &mut Reader, d: &mut Decoded) -> Result<Option<&'a SeqKind>, Error> {
    let unread = r.unread.len();
    let kind = decode_kind(body, r, d)?;
    if r.unread.len() > unread {
        return Err(r.short("a count states units and its `length @` block is not read (ruling 9 of 0.83)"));
    }
    Ok(kind)
}

#[cfg(feature = "bits")]
fn decode_kind<'a>(body: &'a SeqBody, r: &mut Reader, d: &mut Decoded) -> Result<Option<&'a SeqKind>, Error> {
    decode_lines(&body.common, r, d)?;
    if body.kinds.is_empty() {
        return Ok(None);
    }
    let start = r.pos;
    for k in &body.kinds {
        let mut at = start;
        // the keys of `as` lines, set only once the kind is selected (ruling 12 of 0.30)
        let mut bound: Vec<(&str, u64)> = Vec::new();
        let holds = k.whens.iter().all(|w| {
            // a `when` any of whose bits lies beyond the input does not hold
            // `at`: at kind start plus the offset, the cursor kept (engine-spec v0.33)
            let pos = match w.at {
                Some(o) => start.checked_add(o),
                None => Some(at),
            };
            let v = pos
                .filter(|pos| r.limit().saturating_sub(*pos) >= w.len as u64)
                .and_then(|pos| get_bits(r.raw, pos, w.len, r.p.order))
                .filter(|v| in_list(&w.values, *v));
            if w.at.is_none() {
                at += w.len as u64;
            }
            if let (Some(v), Some(key)) = (v, &w.key) {
                bound.push((key, v));
            }
            v.is_some()
        });
        if holds {
            r.pos = at;
            if let Some(cap) = r.run {
                let message = r.p.seq.as_ref().is_some_and(|b| std::ptr::eq(b, body));
                if message && run_in(&body.common).is_none() && run_in(&k.lines).is_none() {
                    cap.borrow_mut().ordinary = true;
                }
            }
            for (key, v) in bound {
                set_as(d, key, v);
            }
            decode_lines(&k.lines, r, d)?;
            return Ok(Some(k));
        }
    }
    err(format!("no-kind: format `{}`: the bits at {} match no kind", r.p.format, start))
}

/// A key bound by `as` holds the bits read as an unsigned integer; 64 bits of
/// 2^63 or more are the negative integer with the same bits (ruling 7 of 0.30).
#[cfg(feature = "bits")]
fn set_as(d: &mut Decoded, key: &str, v: u64) {
    d.ent.fields.entry(key.to_string()).or_insert(Value::I64(v as i64));
}

/// Does a value lie in a list of values and ranges?
#[cfg(feature = "bits")]
fn in_list(values: &[(u64, u64)], v: u64) -> bool {
    values.iter().any(|(lo, hi)| *lo <= v && v <= *hi)
}

#[cfg(feature = "bits")]
fn decode_lines(lines: &[SeqLine], r: &mut Reader, d: &mut Decoded) -> Result<(), Error> {
    for line in lines {
        // inside a `length` block, lines beyond its extent read as absent; a
        // switch there still selects, and its lines read as absent (ruling 14 of 0.20)
        // an `if` or a chain there is read the same way, so that a `rest` group
        // in it is present and empty (ruling 3 of 0.21)
        // an `inner` line there is still read: its pack is called for no bytes
        // (engine-spec v0.34, Decode step 3)
        if r.past_extent()
            && !matches!(line, SeqLine::Switch(_) | SeqLine::If { .. } | SeqLine::Chain { .. } | SeqLine::Inner { .. })
        {
            match line {
                SeqLine::Presence { id, .. } => {
                    r.presence.insert(*id, Vec::new());
                }
                SeqLine::Count { id, .. } => {
                    r.counts.insert(*id, None);
                }
                // a list an inner message gave the entity is kept (engine-spec v0.34)
                SeqLine::Group(g) if g.rep == Rep::Rest && !r.inner_lists.contains(&g.list) => d.put_list(&g.list, Vec::new()),
                absent => {
                    // a `run` line passed in an absent block: an ordinary message
                    // (ruling 4 of 0.92)
                    if let Some(cap) = r.run.filter(|_| run_in(std::slice::from_ref(absent)).is_some()) {
                        cap.borrow_mut().ordinary = true;
                    }
                    r.skip_blocks(std::slice::from_ref(absent))
                }
            }
            continue;
        }
        match line {
            SeqLine::Field { f, also, .. } if f.until.is_some() => {
                let (bits, v) = read_until(r.p, f, r.raw, r.pos, r.limit()).map_err(|e| r.short(e.msg))?;
                r.pos += bits;
                for a in also {
                    d.put(r.p, a, v.clone());
                }
                d.put(r.p, f, v);
            }
            SeqLine::Field { f, len, also, uper } => {
                let v = match uper {
                    // engine-spec v0.19: the length follows from the constraint and the value
                    Some(loc) => crate::uper::read_field(r, f, loc)?,
                    None => {
                        r.need(*len as u64, &format!("`{}`", f.model_key))?;
                        // a sentinel: neither the field's key nor an `also` key gets a value (engine-spec v0.9)
                        if is_sentinel(r.p, f, r.raw, r.pos, *len) {
                            r.pos += *len as u64;
                            continue;
                        }
                        let v = read_field(r.p, f, r.raw, r.pos, *len);
                        r.pos += *len as u64;
                        v
                    }
                };
                // an `also` key takes the same value through its own table
                for a in also {
                    d.put(r.p, a, v.clone());
                }
                d.put(r.p, f, v);
            }
            SeqLine::Const { len, .. } => {
                r.read(*len, "a `const`")?;
            }
            SeqLine::Pad { len } => {
                r.need(*len, "a `pad`")?;
                r.pos += len;
            }
            SeqLine::Align { n } => {
                // stops at the end of the input or extent without error (ruling 20 of 0.8)
                let skip = (n - r.pos % n) % n;
                r.pos = (r.pos + skip).min(r.limit().max(r.pos));
            }
            SeqLine::When(w) => {
                let v = if r.left() < w.len as u64 { None } else { Some(r.read(w.len, "a `when`")?) };
                match v {
                    Some(v) if in_list(&w.values, v) => {
                        if let Some(key) = &w.key {
                            set_as(d, key, v);
                        }
                    }
                    _ => return err(format!("no-kind: format `{}`: common `when {} {}` does not hold", r.p.format, w.len, w.value)),
                }
            }
            SeqLine::Presence { id, bits, named, in_cases } => {
                let mut set = Vec::new();
                match bits {
                    Some(n) => {
                        r.need(*n as u64, "a `presence`")?;
                        for _ in 0..*n {
                            set.push(r.read(1, "a `presence`")? == 1);
                        }
                    }
                    None => loop {
                        r.need(8, "a `presence` octet")?;
                        for _ in 0..7 {
                            set.push(r.read(1, "a `presence`")? == 1);
                        }
                        if r.read(1, "a `presence`")? == 0 {
                            break;
                        }
                    },
                }
                // ruling 1 of 0.8: a bit that is 1 and that no `if` block names;
                // one only `if` lines of cases name waits for the cases read
                r.clock += 1;
                for (i, b) in set.iter().enumerate() {
                    let bit = i as u32 + 1;
                    if !*b || named.contains(&bit) {
                        continue;
                    }
                    if !in_cases.contains(&bit) {
                        return Err(r.short(format!("presence bit {} is 1 and no `if` block names it", bit)));
                    }
                    r.pending.push((*id, bit, r.clock));
                }
                r.presence.insert(*id, set);
            }
            SeqLine::If { conds, body } => {
                if conds.iter().all(|c| r.bit(c)) {
                    decode_lines(body, r, d)?;
                } else {
                    r.skip_blocks(body);
                }
            }
            SeqLine::Opt { body } => {
                if r.read(1, "the bit of an `opt`")? == 1 {
                    decode_lines(body, r, d)?;
                } else {
                    r.skip_blocks(body);
                }
            }
            SeqLine::Chain { parts, ends_fx } => {
                let mut whole = true;
                for (i, part) in parts.iter().enumerate() {
                    if i > 0 && r.indicator("an `fx` bit")? == 0 {
                        parts[i..].iter().for_each(|p| r.skip_blocks(p));
                        whole = false;
                        break;
                    }
                    decode_lines(part, r, d)?;
                }
                // ruling 3 of 0.8: the chain ends with an `fx` line and its bit is 1
                if whole && *ends_fx && r.indicator("an `fx` bit")? == 1 {
                    return Err(r.short("the last `fx` bit of a chain is 1: the item extends past what the pack describes"));
                }
            }
            // engine-spec v0.83: the extent an earlier count states
            SeqLine::Length { body, units: Some((id, u)), in_bits, .. } => {
                let n = match r.counts.get(id).copied().flatten() {
                    Some(n) => n,
                    // the count line lay past the end of its extent
                    None => continue,
                };
                let stop = r.pos as i128 + n * *u as i128;
                // beyond the extent around it, the input or a whole length read
                // before (rulings 4 and 5)
                if stop > r.limit() as i128 {
                    return Err(r.short(format!("a block of {} units of {} bits does not fit", n, u)));
                }
                r.block(body, stop as u64, if *in_bits { 1 } else { 8 }, d)?;
            }
            SeqLine::Length { len, in_bits, plus, body, units: None } => {
                let stated = r.read(*len, "a `length`")? as i128 - *plus as i128;
                let unit: i128 = if *in_bits { 1 } else { 8 };
                let stop = r.pos as i128 + stated * unit;
                if stated < 0 || stop > r.limit() as i128 {
                    return Err(r.short(format!("a `length` of {} {} does not fit", stated, if *in_bits { "bits" } else { "bytes" })));
                }
                r.block(body, stop as u64, unit as u64, d)?;
            }
            SeqLine::Whole { len, plus } => {
                let stated = r.read(*len, "a `length`")? as i128 - *plus as i128;
                let bits = stated * 8;
                if stated < 0 || bits > r.raw.len() as i128 * 8 {
                    return Err(r.short(format!("the message states {} bytes, the input is {}", stated, r.raw.len())));
                }
                if bits < r.pos as i128 {
                    return Err(r.short(format!("the message states {} bytes, fewer than its lines so far", stated)));
                }
                // the end of the input, not of an extent (ruling 8 of 0.8)
                r.whole = bits as u64;
                r.stated = Some(r.stated.map_or(r.whole, |s| s.min(r.whole)));
                if r.depth == 0 {
                    r.end = r.end.min(r.whole);
                }
            }
            SeqLine::Ext { body } => {
                let more = r.read(1, "the extension bit of an `ext`")?;
                decode_lines(body, r, d)?;
                if more == 1 {
                    crate::uper::skip_additions(r)?;
                }
            }
            SeqLine::Choice { n, ext, alts } => {
                let at = r.pos;
                if let Some(i) = crate::uper::read_choice(r, *n, *ext)? {
                    match alts.iter().find(|(a, _)| *a == i) {
                        Some((_, lines)) => decode_lines(lines, r, d)?,
                        None => return Err(r.short(format!("the `choice` at bit {} has index {}, which no `alt` holds", at, i))),
                    }
                }
            }
            SeqLine::Group(g) => {
                let mut items: Vec<Decoded> = Vec::new();
                let format = r.p.format.clone();
                // a list an inner message gave the entity is kept (engine-spec v0.34)
                let kept_inner = r.inner_lists.contains(&g.list);
                if !kept_inner {
                    d.replacing(&g.list);
                }
                // an inner list the outer entity discards is not counted (engine-spec v0.34)
                // nor an outer list discarded for the inner one read first (7g)
                let _uncounted = limit::group(&g.list, kept_inner);
                // a counted group takes its items at once (7d)
                let counted = matches!(g.rep, Rep::Count(_) | Rep::Named(_));
                let item = |r: &mut Reader, items: &mut Vec<Decoded>| -> Result<(), Error> {
                    if !counted {
                        limit::take(&format, &g.list, 1)?;
                    }
                    let mut di = Decoded::new();
                    let _item = limit::item();
                    // the lists of an item are not the message's: none is an inner one
                    let inner_lists = std::mem::take(&mut r.inner_lists);
                    let kind = decode_body(&g.body, r, &mut di)?;
                    r.inner_lists = inner_lists;
                    di.ent.kind = kind.map(|k| (format.clone(), k.name.clone()));
                    items.push(di);
                    Ok(())
                };
                match &g.rep {
                    Rep::Count(len) => {
                        let n = r.read(*len, "the count of a group")?;
                        limit::take_count(&format, &g.list, n)?;
                        if n > r.left() {
                            return Err(r.short(format!("list `{}` has {} items, more than the input holds", g.list, n)));
                        }
                        for _ in 0..n {
                            item(r, &mut items)?;
                        }
                    }
                    Rep::Size(size) => {
                        let n = crate::uper::read_count(r, *size, "the count of a group")?;
                        if n > r.left() {
                            return Err(r.short(format!("list `{}` has {} items, more than the input holds", g.list, n)));
                        }
                        for _ in 0..n {
                            item(r, &mut items)?;
                        }
                    }
                    Rep::While => {
                        while r.indicator("the bit before an item")? == 1 {
                            item(r, &mut items)?;
                        }
                    }
                    Rep::More => loop {
                        let more = r.indicator("the bit before an item")?;
                        item(r, &mut items)?;
                        if more == 0 {
                            break;
                        }
                    },
                    Rep::Fx => loop {
                        item(r, &mut items)?;
                        if r.indicator("the bit after an item")? == 0 {
                            break;
                        }
                    },
                    // items while a whole unit of the extent remains; fewer bits are padding
                    Rep::Rest => {
                        while r.stated_left() >= r.unit {
                            let start = r.pos;
                            item(r, &mut items)?;
                            if r.pos == start {
                                return Err(r.short(format!("an item of list `{}` reads no bits (ruling 1 of 0.21)", g.list)));
                            }
                        }
                    }
                    Rep::Named(ids) => {
                        let ns: Option<Vec<i128>> = ids.iter().map(|id| r.counts.get(id).copied().flatten()).collect();
                        let n = match ns {
                            // two counts agree, as exact integers (rulings 4 and 5 of 0.31)
                            Some(ns) if ns.iter().any(|m| *m != ns[0]) => {
                                return Err(r.short(format!("list `{}`: its two counts give {} and {} items", g.list, ns[0], ns[1])));
                            }
                            Some(ns) => ns[0],
                            // the count line lay past the end of its extent: the list is absent
                            None => continue,
                        };
                        // 7d of 0.11, also for a list that is discarded (ruling 7 of 0.34)
                        limit::take_count(&format, &g.list, u64::try_from(n).unwrap_or(u64::MAX))?;
                        // the bits left at the group (ruling 20 of 0.21)
                        if n > r.left() as i128 {
                            return Err(r.short(format!("list `{}` has {} items, more than the input holds", g.list, n)));
                        }
                        for _ in 0..n {
                            item(r, &mut items)?;
                        }
                    }
                    // an indicator after the first that starts at the extent end is
                    // `malformed-wire` (ruling 13 of 0.21)
                    Rep::Last => loop {
                        let last = r.read(1, "the bit before an item")?;
                        item(r, &mut items)?;
                        if last == 1 {
                            break;
                        }
                    },
                }
                if kept_inner {
                    d.discard_list(&g.list, items);
                } else {
                    d.put_list(&g.list, items);
                }
            }
            SeqLine::Switch(sw) => {
                // the key's value so far, as canonical text (engine-spec v0.20)
                // a key whose line failed its transform fails the decode (ruling 35 of 0.20)
                let failed = d.soft.iter().find(|(k, _)| r.strict && *k == sw.key).map(|(_, m)| m.clone());
                let state = match failed {
                    Some(m) => Err(m),
                    None => key_state(d, &sw.key),
                };
                let value = match state {
                    Ok(v) => v,
                    Err(m) => return err(format!("transform-decode: format `{}`: {}", r.p.format, m)),
                };
                let pick = match sw.pick(value.as_deref()) {
                    Some(i) => i,
                    None => {
                        return err(format!(
                            "no-kind: format `{}`: `switch {}` of line {}: {} selects no case and there is no `else`",
                            r.p.format,
                            sw.key,
                            sw.line,
                            value.map_or("the absent key".to_string(), |v| format!("`{}`", v))
                        ))
                    }
                };
                let case = sw.case(pick);
                for (id, bit) in &case.names {
                    r.case_named.push((*id, *bit, r.clock));
                }
                decode_lines(&case.lines, r, d)?;
            }
            SeqLine::Inner { format, partial, run, reach, withs, .. } => {
                let h = inner_host(r.host, r.p, format, *run, reach, withs)?;
                // Decode steps 1 and 2: whole bytes from the start of the message
                if r.pos % 8 != 0 {
                    return Err(r.short(format!("the `inner {}` message starts at bit {}, inside a byte", format, r.pos)));
                }
                // the input ends at a `length … whole`, also one read inside the
                // block (ruling 16 of 0.83)
                if r.end > r.whole || r.end % 8 != 0 {
                    return Err(r.short(format!("the extent of the `inner {}` message ends at bit {}, not on a whole byte of the input", format, r.end)));
                }
                let start = r.pos.min(r.end);
                let bytes = &r.raw[(start / 8) as usize..(r.end / 8) as usize];
                r.pos = r.end.max(r.pos);
                if *run {
                    let outer = r.p;
                    match r.run {
                        Some(cap) => read_run(outer, h, format, bytes, cap)?,
                        // `decode` and `convert`: exactly one message (ruling 1 of 0.92)
                        None => {
                            let count = |what: &str| err(format!("message-count: format `{}`: the `{}` run holds {}", outer.format, format, what));
                            if bytes.is_empty() {
                                return count("no message");
                            }
                            let (inner, end) = message(outer, h, format, bytes)?;
                            if end < bytes.len() {
                                return count("more than one message");
                            }
                            let kept = d.join(inner, |m| inner_error(outer, Error { msg: format!("format `{}`: {}", format, m) }).msg);
                            r.inner_lists.extend(kept);
                        }
                    }
                    continue;
                }
                match h.inner_decode(format, bytes, *partial, d.ent.lists.keys().cloned().collect()) {
                    // steps 4 and 5, also after a failed line of the inner message (ruling 19)
                    Ok(inner) => {
                        let outer = r.p;
                        let kept = d.join(inner, |m| inner_error(outer, Error { msg: format!("format `{}`: {}", format, m) }).msg);
                        r.inner_lists.extend(kept);
                    }
                    // an error that stops the inner decode stops the outer one (ruling 17 of
                    // 0.34); a failed line does not, and joined above
                    Err(e) => return Err(inner_error(r.p, e)),
                }
            }
            SeqLine::Count { id, len, plus, .. } => {
                let v = r.read(*len, "a `count`")?;
                // `value − n` without overflow; below `n` is checked here (ruling 7 of 0.21)
                let n = v as i128 - *plus as i128;
                if n < 0 {
                    return Err(r.short(format!("a count of {} is below its `plus {}`", v, plus)));
                }
                r.counts.insert(*id, Some(n));
            }
        }
    }
    Ok(())
}

/// One message of a run, from the first of `bytes`: it ends in them, and not
/// at its start (engine-spec v0.92, "Where one message ends").
#[cfg(feature = "bits")]
fn message(outer: &Pack, h: &dyn InnerHost, format: &str, bytes: &[u8]) -> Result<(Decoded, usize), Error> {
    let (d, end) = h.inner_message(format, bytes).map_err(|e| inner_error(outer, e))?;
    if end == 0 || end > bytes.len() {
        return err(format!(
            "malformed-wire: format `{}`: a message of the `{}` run ends at byte {} of the {} left",
            outer.format,
            format,
            end,
            bytes.len()
        ));
    }
    Ok((d, end))
}

/// Read the messages of a run in a run operation. A message whose decode stops
/// is the last (ruling 3 of 0.92); one more than `max_items` is an error of
/// the call (ruling 5). The outer lines after the run do not count their items.
#[cfg(feature = "bits")]
fn read_run(outer: &Pack, h: &dyn InnerHost, format: &str, bytes: &[u8], cap: &std::cell::RefCell<RunCapture>) -> Result<(), Error> {
    cap.borrow_mut().format = Some(format.to_string());
    let mut at = 0;
    while at < bytes.len() {
        let held = limit::held();
        if held.is_some_and(|(_, max)| cap.borrow().messages.len() as u64 >= max) {
            return err(format!("malformed-wire: format `{}`: the `{}` run holds more messages than the limit on items allows", outer.format, format));
        }
        let res = message(outer, h, format, &bytes[at..]);
        limit::restore(held);
        match res {
            Ok((d, end)) => {
                cap.borrow_mut().messages.push(Ok(d));
                at += end;
            }
            Err(e) => {
                cap.borrow_mut().messages.push(Err(e));
                break;
            }
        }
    }
    Ok(())
}

/// `total`: the bits of the input (8 a byte of hex, 6 a character of armor).
#[cfg(feature = "bits")]
pub fn decode(p: &Pack, body: &SeqBody, raw: &[u8], total: u64) -> Result<Entity, Error> {
    decode_host(p, body, raw, total, None)
}

/// `decode` with the engine that finds the pack of an `inner` line.
#[cfg(feature = "bits")]
pub(crate) fn decode_host(p: &Pack, body: &SeqBody, raw: &[u8], total: u64, host: Option<&dyn InnerHost>) -> Result<Entity, Error> {
    decode_parts(p, body, raw, total, host)?.0.finish_kind(p)
}

/// The decode of a sequential layout, its failed lines not yet judged, and
/// the bit the message ends at (ruling 13 of 0.34).
#[cfg(feature = "bits")]
pub(crate) fn decode_parts(p: &Pack, body: &SeqBody, raw: &[u8], total: u64, host: Option<&dyn InnerHost>) -> Result<(Decoded, u64), Error> {
    decode_as(p, body, raw, total, host, None, false)
}

/// `decode_parts`, in a run operation with `run`, as a message of a run with
/// `strict` (engine-spec v0.92).
#[cfg(feature = "bits")]
pub(crate) fn decode_as(
    p: &Pack,
    body: &SeqBody,
    raw: &[u8],
    total: u64,
    host: Option<&dyn InnerHost>,
    run: Option<&std::cell::RefCell<RunCapture>>,
    strict: bool,
) -> Result<(Decoded, u64), Error> {
    let mut r = Reader {
        host,
        inner_lists: Vec::new(),
        stated: None,
        p,
        raw,
        pos: 0,
        end: total,
        whole: total,
        depth: 0,
        presence: BTreeMap::new(),
        pending: Vec::new(),
        case_named: Vec::new(),
        clock: 0,
        unit: 8,
        counts: HashMap::new(),
        unread: Vec::new(),
        run,
        strict,
    };
    let mut d = Decoded::new();
    let kind = decode_body(body, &mut r, &mut d)?;
    // a bit only `if` lines of cases name: such a case read after the
    // presence, anywhere in the decode, names it (ruling 36 of 0.20)
    for (id, bit, at) in &r.pending {
        if !r.case_named.iter().any(|(i, b, t)| i == id && b == bit && t >= at) {
            return Err(r.short(format!("presence bit {} is 1 and no `if` block of the lines read names it", bit)));
        }
    }
    d.ent.kind = kind.map(|k| (p.format.clone(), k.name.clone()));
    // a message-level `rest` leaves less than a byte, so rounding up is the end of the input
    let end = r.stated.unwrap_or((r.pos + 7) / 8 * 8);
    Ok((d, end))
}

// ---------------------------------------------------------------------------
// Encode
// ---------------------------------------------------------------------------

/// The kind an entity, or an item, is written as: its own kind when it names
/// this format, else the first kind whose `requires` terms all hold.
/// An item (`item`) whose kind names this format and a kind its group does
/// not have is selected by `requires` too (ruling 26 of 0.8); for a message
/// that is `no-kind` (ruling 24 of 0.5).
#[cfg(feature = "bits")]
fn select<'a>(p: &Pack, body: &'a SeqBody, ent: &Entity, item: bool) -> Result<Option<&'a SeqKind>, Error> {
    if body.kinds.is_empty() {
        return Ok(None);
    }
    if let Some((fmt, name)) = &ent.kind {
        if fmt == &p.format {
            match body.kinds.iter().find(|k| &k.name == name) {
                Some(k) => return Ok(Some(k)),
                None if item => {}
                None => return err(format!("no-kind: format `{}` has no kind `{}`", p.format, name)),
            }
        }
    }
    // a `when … as <k>` line is an implicit `requires` term (engine-spec v0.30)
    let qualifies = |k: &SeqKind| k.requires.iter().all(|r| r.holds(ent)) && k.whens.iter().all(|w| when_qualifies(w, ent));
    match body.kinds.iter().find(|k| qualifies(k)) {
        Some(k) => Ok(Some(k)),
        None => err(format!("no-kind: format `{}`: the entity has the required keys of no kind", p.format)),
    }
}

/// The kind `encode` chooses for a message (0.5), for the check of 0.94.
#[cfg(feature = "bits")]
pub(crate) fn chosen_kind<'a>(p: &Pack, body: &'a SeqBody, ent: &Entity) -> Result<Option<&'a SeqKind>, Error> {
    select(p, body, ent, false)
}

/// The keys of a kind (engine-spec v0.94, Rule), over the common lines and
/// the lines of `kind`, every block, case and suppressed line included: the
/// keys of `field` and `also` lines, of `when … as` lines, a list by its
/// entry `<list>[]` (its items' keys not), the keys `inner` adds for an
/// `inner` line (format, `run`), and the keys of the kind's own `requires`
/// lines. Also the formats of the `inner` lines of those lines.
#[cfg(feature = "bits")]
pub(crate) fn kind_keys(
    body: &SeqBody,
    kind: Option<&SeqKind>,
    inner: &dyn Fn(&str, bool, &mut Vec<String>),
) -> (Vec<String>, Vec<String>) {
    fn add(out: &mut Vec<String>, key: String) {
        if !out.contains(&key) {
            out.push(key);
        }
    }
    fn walk(ls: &[SeqLine], out: &mut Vec<String>, formats: &mut Vec<String>, inner: &dyn Fn(&str, bool, &mut Vec<String>)) {
        for l in ls {
            match l {
                SeqLine::Field { f, also, .. } => {
                    std::iter::once(f).chain(also.iter()).for_each(|k| add(out, k.model_key.clone()))
                }
                SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
                    walk(body, out, formats, inner)
                }
                SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| walk(p, out, formats, inner)),
                SeqLine::Choice { alts, .. } => alts.iter().for_each(|(_, p)| walk(p, out, formats, inner)),
                // a list by its entry; an `inner` line cannot stand in a group
                // body (0.34), so no format of one keeps a kind (ruling 4)
                SeqLine::Group(g) => add(out, format!("{}[]", g.list)),
                SeqLine::Switch(sw) => sw.bodies().for_each(|c| walk(&c.lines, out, formats, inner)),
                SeqLine::When(SeqWhen { key: Some(k), .. }) => add(out, k.clone()),
                SeqLine::Inner { format, run, .. } => {
                    if !formats.contains(format) {
                        formats.push(format.clone());
                    }
                    inner(format, *run, out)
                }
                _ => {}
            }
        }
    }
    let mut out = Vec::new();
    let mut formats = Vec::new();
    walk(&body.common, &mut out, &mut formats, inner);
    if let Some(k) = kind {
        for w in &k.whens {
            if let Some(key) = &w.key {
                add(&mut out, key.clone());
            }
        }
        walk(&k.lines, &mut out, &mut formats, inner);
        k.requires.iter().for_each(|r| add(&mut out, r.key.clone()));
    }
    (out, formats)
}

/// The implicit `requires` term of a `when` line: none without `as`; else the
/// entity holds the key with a value the line matches, or, on an `optional`
/// line (engine-spec v0.52), does not hold it. The value is read as an
/// unsigned 64-bit pattern (ruling 7 of 0.30); a `default` does not count.
#[cfg(feature = "bits")]
fn when_qualifies(w: &SeqWhen, ent: &Entity) -> bool {
    match w.key.as_ref().map(|k| ent.fields.get(k)) {
        None => true,
        Some(None) => w.optional,
        Some(Some(v)) => as_bits(v).map_or(false, |b| in_list(&w.values, b)),
    }
}

/// An entity value of an `int` key as the unsigned bits a `when` compares.
#[cfg(feature = "bits")]
fn as_bits(v: &Value) -> Option<u64> {
    match v {
        Value::I64(n) => Some(*n as u64),
        Value::F64(x) if x.fract() == 0.0 && *x >= -9.223372036854775808e18 && *x < 9.223372036854775808e18 => Some(*x as i64 as u64),
        _ => None,
    }
}

/// The bits a `when` line writes: the value of its `as` key when the entity
/// holds it and the line matches it; the first listed value when the entity
/// does not hold it; `transform-encode` when it holds a value the line does
/// not match (engine-spec v0.30, Encode).
#[cfg(feature = "bits")]
fn when_bits(p: &Pack, w: &SeqWhen, ent: &Entity) -> Result<u64, Error> {
    let key = match &w.key {
        Some(k) => k,
        None => return Ok(w.value),
    };
    match ent.fields.get(key) {
        None => Ok(w.value),
        Some(v) => match as_bits(v).filter(|b| in_list(&w.values, *b)) {
            Some(b) => Ok(b),
            None => err(format!(
                "transform-encode: format `{}`: `{}` = {} does not match `when {}` of line {}: the output would decode a different value",
                p.format,
                key,
                v.as_display(),
                w.len,
                w.line
            )),
        },
    }
}

/// Write one `when` line, and what decode reads back from it.
#[cfg(feature = "bits")]
fn write_when(w: &mut Writer, line: &SeqWhen, ent: &Entity) -> Result<(), Error> {
    let v = when_bits(w.p, line, ent)?;
    w.put(line.len, v);
    if let Some(key) = &line.key {
        set_as(w.back.last_mut().expect("a scope"), key, v);
    }
    Ok(())
}

/// The defaults in force: those of the cases the lines are in, innermost
/// first (ruling 7 of 0.20), then the selected kind's, then the common ones.
#[derive(Clone, Copy)]
#[cfg(feature = "bits")]
struct Defaults<'a> {
    kind: &'a [DefaultDef],
    common: &'a [DefaultDef],
    /// a UPER pack: a `default` is not content (ruling 2 of 0.19)
    uper: bool,
    case: &'a [DefaultDef],
    up: Option<&'a Defaults<'a>>,
}

#[cfg(feature = "bits")]
impl<'a> Defaults<'a> {
    #[cfg(feature = "bits")]
    fn of(p: &Pack, body: &'a SeqBody, kind: Option<&'a SeqKind>) -> Defaults<'a> {
        Defaults {
            kind: kind.map_or(&[], |k| k.defaults.as_slice()),
            common: &body.defaults,
            uper: p.uper,
            case: &[],
            up: None,
        }
    }
    /// The defaults inside one case of a switch.
    #[cfg(feature = "bits")]
    fn inside<'b>(&'b self, c: &'b Case) -> Defaults<'b> {
        Defaults { kind: &[], common: &[], uper: self.uper, case: &c.defaults, up: Some(self) }
    }
    /// The `default` of a key, if it has one.
    #[cfg(feature = "bits")]
    fn default(&self, key: &str) -> Option<&'a Value> {
        if let Some(d) = self.case.iter().find(|d| d.model_key == key) {
            return d.value.as_ref();
        }
        if let Some(up) = self.up {
            return up.default(key);
        }
        self.kind.iter().chain(self.common.iter()).find(|d| d.model_key == key).and_then(|d| d.value.as_ref())
    }
    /// The value encode uses for a key: the entity's, else the `default`.
    #[cfg(feature = "bits")]
    fn value(&self, ent: &'a Entity, key: &str) -> Option<&'a Value> {
        ent.fields.get(key).or_else(|| self.default(key))
    }
}

/// The case each switch selects on encode (engine-spec v0.20). Presence,
/// `opt` and `fx` bits are computed before the lines they cover are written,
/// so the case of a switch they cover is looked up here: the case the last
/// pass selected, else a first estimate from the entity. A pass that selects
/// another case than the one looked up is run again.
#[cfg(feature = "bits")]
struct Look<'p> {
    p: &'p Pack,
    /// the engine that finds the pack of an `inner` line (engine-spec v0.34)
    host: Option<&'p dyn InnerHost>,
    /// the messages a `run` line writes (engine-spec v0.92); None: one, of the
    /// entity encoded
    messages: Option<&'p [Entity]>,
    /// (entity, switch line) -> case
    picks: std::cell::RefCell<HashMap<(usize, usize), Pick>>,
    changed: std::cell::Cell<bool>,
}

#[cfg(feature = "bits")]
impl<'p> Look<'p> {
    #[cfg(feature = "bits")]
    fn at(ent: &Entity, sw: &Switch) -> (usize, usize) {
        (ent as *const Entity as usize, sw.line)
    }
    /// The case taken as selected before the switch is written.
    #[cfg(feature = "bits")]
    fn get(&self, sw: &Switch, ent: &Entity, defs: Defaults) -> Pick {
        let at = Look::at(ent, sw);
        if let Some(pick) = self.picks.borrow().get(&at) {
            return *pick;
        }
        // the first prediction: what the first line mapping the key would
        // write, read back (ruling 37 of 0.20)
        let mut back = Decoded::new();
        let (f, len, also, uper) = match &sw.first {
            First::Field(f, len, also, uper) => (f, len, also, uper),
            // a `when … as` line (engine-spec v0.30): the value it would write
            First::When(line) => {
                if let Ok(v) = when_bits(self.p, line, ent) {
                    set_as(&mut back, line.key.as_deref().unwrap_or_default(), v);
                }
                let v = key_state(&back, &sw.key).ok().flatten();
                let pick = sw.pick(v.as_deref());
                self.picks.borrow_mut().insert(at, pick);
                return pick;
            }
        };
        match uper {
            // a UPER locator (engine-spec v0.19): its bits follow from the value
            Some(loc) => {
                let mut w = Writer {
                    p: self.p,
                    buf: Vec::new(),
                    pos: 0,
                    presence: BTreeMap::new(),
                    wholes: Vec::new(),
                    back: Vec::new(),
                    look: self,
                    count_fields: Vec::new(),
                    counts: HashMap::new(),
                    extents: vec![(0, false)],
                    rests: 0,
                };
                if write_uper_line(&mut w, f, loc, also, ent, defs).is_ok() {
                    read_back_uper(self.p, f, loc, also, &w.buf, 0, &mut back);
                }
            }
            // `until:` (engine-spec v0.22): the codes and the terminator
            None if f.until.is_some() => {
                if let Ok((codes, width)) = until_codes(self.p, f, also, ent, defs) {
                    let mut buf = vec![0u8; (codes.len() * width as usize).div_ceil(8)];
                    for (i, c) in codes.iter().enumerate() {
                        set_bits(&mut buf, i as u64 * width as u64, width, *c as u64, self.p.order);
                    }
                    if let Ok((_, v)) = read_until(self.p, f, &buf, 0, buf.len() as u64 * 8) {
                        for a in also {
                            back.put(self.p, a, v.clone());
                        }
                        back.put(self.p, f, v);
                    }
                }
            }
            None => {
                let mut buf = vec![0u8; ((*len as usize) + 7) / 8];
                if write_line(self.p, f, *len, also, ent, defs, 0, &mut buf).is_ok() {
                    read_back(self.p, f, *len, also, &buf, 0, &mut back);
                }
            }
        }
        let v = key_state(&back, &sw.key).ok().flatten();
        let pick = sw.pick(v.as_deref());
        self.picks.borrow_mut().insert(at, pick);
        pick
    }
    /// The case the switch selected as it was written.
    #[cfg(feature = "bits")]
    fn set(&self, sw: &Switch, ent: &Entity, pick: Pick) {
        if let Some(old) = self.picks.borrow_mut().insert(Look::at(ent, sw), pick) {
            if old != pick {
                self.changed.set(true);
            }
        }
    }
}

/// Would these lines write a present key or a non-empty list? A key with a
/// `default` in scope counts as present (ruling 2 of 0.8), except in a UPER
/// pack (ruling 2 of 0.19). Of a switch, only the selected case counts
/// (engine-spec v0.20).
#[cfg(feature = "bits")]
fn content(lines: &[SeqLine], ent: &Entity, defs: Defaults, look: &Look) -> bool {
    let present = |key: &str| if defs.uper { ent.fields.contains_key(key) } else { defs.value(ent, key).is_some() };
    lines.iter().any(|l| match l {
        // a line suppressed by `with` is not content, nor is its default
        // (ruling 1 of 0.18); in a UPER pack a default is not content
        // (ruling 2 of 0.19)
        SeqLine::Field { f, also, .. } => {
            std::iter::once(f).chain(also.iter()).any(|k| live(ent, k) && present(&k.model_key))
        }
        SeqLine::Group(g) => ent.lists.get(&g.list).map_or(false, |l| !l.is_empty()),
        SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
            content(body, ent, defs, look)
        }
        SeqLine::Chain { parts, .. } => parts.iter().any(|p| content(p, ent, defs, look)),
        // ruling 3 of 0.19
        SeqLine::Choice { alts, .. } => alts.iter().any(|(_, p)| content(p, ent, defs, look)),
        SeqLine::Switch(sw) => match look.get(sw, ent, defs) {
            Some(i) => {
                let c = sw.case(i);
                content(&c.lines, ent, defs.inside(c), look)
            }
            None => false,
        },
        _ => false,
    })
}

/// The bits of presence `id`: bit i is 1 when some `if` block naming it
/// without `!` would write a present key or a non-empty list.
#[cfg(feature = "bits")]
fn presence_bits(p: &Pack, lines: &[SeqLine], ent: &Entity, defs: Defaults, look: &Look, id: usize, bits: &mut Vec<bool>) {
    for l in lines {
        match l {
            SeqLine::If { conds, body } => {
                if content(body, ent, defs, look) {
                    for c in conds.iter().filter(|c| c.id == id && !c.neg) {
                        let i = c.bit as usize;
                        if bits.len() < i {
                            bits.resize(i, false);
                        }
                        bits[i - 1] = true;
                    }
                }
                presence_bits(p, body, ent, defs, look, id, bits);
            }
            SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
                presence_bits(p, body, ent, defs, look, id, bits)
            }
            SeqLine::Chain { parts, .. } => parts.iter().for_each(|part| presence_bits(p, part, ent, defs, look, id, bits)),
            SeqLine::Choice { alts, .. } => {
                alts.iter().for_each(|(_, part)| presence_bits(p, part, ent, defs, look, id, bits))
            }
            SeqLine::Group(g) => {
                for item in ent.lists.get(&g.list).into_iter().flatten() {
                    let kind = select(p, &g.body, item, true).ok().flatten();
                    let item_defs = Defaults::of(p, &g.body, kind);
                    presence_bits(p, &g.body.common, item, item_defs, look, id, bits);
                    if let Some(k) = kind {
                        presence_bits(p, &k.lines, item, item_defs, look, id, bits);
                    }
                }
            }
            // only the selected case sets a bit (engine-spec v0.20)
            SeqLine::Switch(sw) => {
                if let Some(i) = look.get(sw, ent, defs) {
                    let c = sw.case(i);
                    presence_bits(p, &c.lines, ent, defs.inside(c), look, id, bits);
                }
            }
            _ => {}
        }
    }
}

/// Write one `field` line, with its `also` keys, at bit `at` of `buf`, whose
/// bits there are zero: the earliest of the line's keys that the entity
/// holds; when it holds none, the default of the earliest key that has one
/// (rulings 13 and 16 of 0.8); else the first sentinel, else zero bits. A
/// line suppressed by `with` is none of them (engine-spec v0.18).
#[allow(clippy::too_many_arguments)]
#[cfg(feature = "bits")]
fn write_line(p: &Pack, f: &FieldDef, len: u32, also: &[FieldDef], ent: &Entity, defs: Defaults, at: u64, buf: &mut [u8]) -> Result<(), Error> {
    let keys = || std::iter::once(f).chain(also.iter()).filter(|k| live(ent, k));
    let value = keys()
        .find_map(|k| ent.fields.get(&k.model_key).map(|v| (k, v)))
        .or_else(|| keys().find_map(|k| defs.default(&k.model_key).map(|v| (k, v))));
    match value {
        Some((k, v)) => {
            let v = p.to_wire(k, v).map_err(|e| transform_encode_err(p, k, e))?;
            write_field(p, k, &v, at, len, buf)?;
        }
        // with `absent`, the first sentinel in place of the zero bits (engine-spec v0.9)
        None if live(ent, f) => {
            write_sentinel(p, f, at, len, buf);
        }
        None => {}
    }
    Ok(())
}

/// The set and terminator of an `until:` field.
#[cfg(feature = "bits")]
fn until_of(f: &FieldDef) -> (CharSet, u32) {
    match (f.transform, f.until) {
        (Transform::Chars(set), Some(code)) => (set, code),
        _ => unreachable!("an `until:` field is `chars` with a code"),
    }
}

/// Read an `until:` field from bit `start` (engine-spec v0.22): the bits it
/// takes, terminator included, and its value. The terminator is found from
/// the codes alone first; none before `end`, or more than `2040 / w`
/// characters before it, is the outer error (`malformed-wire`). A code the
/// set does not define is then the value's error (ruling 5).
#[cfg(feature = "bits")]
fn read_until(p: &Pack, f: &FieldDef, raw: &[u8], start: u64, end: u64) -> Result<(u64, Result<Value, Error>), Error> {
    let (set, term) = until_of(f);
    let w = set.width();
    let max = (2040 / w) as usize;
    let end = end.min(raw.len() as u64 * 8);
    let mut codes: Vec<u32> = Vec::new();
    let mut at = start;
    loop {
        if end.saturating_sub(at) < w as u64 {
            return err(format!("`{}` finds no terminator {} before the end of its extent at bit {}", f.model_key, term, at));
        }
        let c = get_bits(raw, at, w, p.order).unwrap_or(0) as u32;
        at += w as u64;
        if c == term {
            break;
        }
        if codes.len() == max {
            return err(format!("`{}` reads more than {} characters before its terminator {}", f.model_key, max, term));
        }
        codes.push(c);
    }
    // nothing is removed, and NUL is a character unless it is the terminator (rulings 6, 7)
    Ok((at - start, super::bits::chars_text(set, &codes).map(Value::Str)))
}

/// The codes an `until:` field writes, terminator last, and their width: the
/// earliest key of the line the entity holds, else the earliest default,
/// else the terminator alone (ruling 10 of 0.22).
#[cfg(feature = "bits")]
fn until_codes(p: &Pack, f: &FieldDef, also: &[FieldDef], ent: &Entity, defs: Defaults) -> Result<(Vec<u32>, u32), Error> {
    let (set, term) = until_of(f);
    let w = set.width();
    let keys = || std::iter::once(f).chain(also.iter()).filter(|k| live(ent, k));
    let value = keys()
        .find_map(|k| ent.fields.get(&k.model_key).map(|v| (k, v)))
        .or_else(|| keys().find_map(|k| defs.default(&k.model_key).map(|v| (k, v))));
    let mut codes = Vec::new();
    if let Some((k, v)) = value {
        let fail = |m: String| transform_encode_err(p, k, Error { msg: m });
        let text = match p.to_wire(k, v).map_err(|e| transform_encode_err(p, k, e))? {
            Value::Str(s) => s,
            other => return Err(fail(format!("chars encodes text, got {:?}", other))),
        };
        let max = (2040 / w) as usize;
        for ch in text.chars() {
            // NUL is a character with code 0 unless it is the terminator (ruling 6)
            let code = match (ch, set) {
                ('\0', CharSet::Ascii7 | CharSet::Ascii8) => Some(0),
                _ => set.code_of(ch),
            };
            match code {
                Some(c) if c == term => return Err(fail(format!("character {:?} is the terminator, code {}", ch, c))),
                Some(c) => codes.push(c),
                None => return Err(fail(format!("character {:?} is not in the character set {:?}", ch, set))),
            }
        }
        if codes.len() > max {
            return Err(fail(format!("text is {} characters, more than the {} before a terminator", codes.len(), max)));
        }
    }
    codes.push(term);
    Ok((codes, w))
}

/// What decode reads from the bits of one `field` line: a sentinel gives no
/// key a value; otherwise every key of the line takes the value.
#[cfg(feature = "bits")]
fn read_back(p: &Pack, f: &FieldDef, len: u32, also: &[FieldDef], buf: &[u8], at: u64, back: &mut Decoded) {
    if !is_sentinel(p, f, buf, at, len) {
        let v = read_field(p, f, buf, at, len);
        for a in also {
            back.put(p, a, v.clone());
        }
        back.put(p, f, v);
    }
}

/// Write one `field` line with a UPER locator (engine-spec v0.19) at the
/// cursor: the earliest of its keys that the entity holds, else the default
/// of the earliest key that has one (rulings 13 and 16 of 0.8; a line
/// suppressed by `with` is none of them, engine-spec v0.18); an absent key
/// writes the values of ruling 1 of 0.19.
#[cfg(feature = "bits")]
fn write_uper_line(
    w: &mut Writer,
    f: &FieldDef,
    loc: &crate::uper::Loc,
    also: &[FieldDef],
    ent: &Entity,
    defs: Defaults,
) -> Result<(), Error> {
    let p = w.p;
    let keys = || std::iter::once(f).chain(also.iter()).filter(|k| live(ent, k));
    let value = keys()
        .find_map(|k| ent.fields.get(&k.model_key).map(|v| (k, v)))
        .or_else(|| keys().find_map(|k| defs.default(&k.model_key).map(|v| (k, v))));
    let v = match value {
        Some((k, v)) => Some((k, p.to_wire(k, v).map_err(|e| transform_encode_err(p, k, e))?)),
        None => None,
    };
    crate::uper::write_field(w, f, loc, v.as_ref().map(|(k, v)| (*k, v)))
}

/// What decode reads from a field with a UPER locator written from bit `at`
/// of `buf`: every key of the line takes the value (engine-spec v0.19, v0.20).
#[cfg(feature = "bits")]
fn read_back_uper(p: &Pack, f: &FieldDef, loc: &crate::uper::Loc, also: &[FieldDef], buf: &[u8], at: u64, back: &mut Decoded) {
    let end = buf.len() as u64 * 8;
    let mut r = Reader {
        host: None,
        inner_lists: Vec::new(),
        stated: None,
        p,
        raw: buf,
        pos: at,
        end,
        whole: end,
        depth: 0,
        presence: BTreeMap::new(),
        pending: Vec::new(),
        case_named: Vec::new(),
        clock: 0,
        unit: 8,
        counts: HashMap::new(),
        unread: Vec::new(),
        run: None,
        strict: false,
    };
    if let Ok(v) = crate::uper::read_field(&mut r, f, loc) {
        for a in also {
            back.put(p, a, v.clone());
        }
        back.put(p, f, v);
    }
}

/// The key of a switch as decode holds it so far: its canonical text, None
/// when absent, or the failure of its line's transform or table.
#[cfg(feature = "bits")]
fn key_state(d: &Decoded, key: &str) -> Result<Option<String>, String> {
    if let Some(v) = d.ent.fields.get(key) {
        return Ok(Some(v.as_display()));
    }
    if d.hard_keys.iter().any(|k| k == key) {
        return Err(d.hard.iter().rev().find(|(k, _, _)| k == key).map(|(_, _, m)| m.clone()).unwrap_or_default());
    }
    if let Some((_, m)) = d.soft.iter().find(|(k, _)| k == key) {
        return Err(m.clone());
    }
    Ok(None)
}

#[cfg(feature = "bits")]
pub(crate) struct Writer<'a> {
    pub(crate) p: &'a Pack,
    buf: Vec<u8>,
    pos: u64,
    presence: BTreeMap<usize, Vec<bool>>,
    /// `length ... whole` fields to fill once the message is laid out: (bit, len, plus)
    wholes: Vec<(u64, u32, i64)>,
    /// what decode would read back from the lines written so far, one per
    /// scope being written, innermost last: a switch selects from it
    back: Vec<Decoded>,
    look: &'a Look<'a>,
    /// every `count` field written: (bit, len, plus, what its group or block
    /// counts), filled in and checked when the message is finished (ruling 30
    /// of 0.21)
    count_fields: Vec<(u64, u32, i64, Option<u64>)>,
    /// per `count` line id: its latest field in `count_fields`
    counts: HashMap<usize, usize>,
    /// the extents being written, innermost last: (first bit, counted in bits)
    extents: Vec<(u64, bool)>,
    /// how many `rest` groups the innermost extent has written so far
    rests: u64,
}

#[cfg(feature = "bits")]
impl<'a> Writer<'a> {
    /// `n` zero bits.
    #[cfg(feature = "bits")]
    fn zeros(&mut self, n: u64) {
        self.pos += n;
        let bytes = ((self.pos + 7) / 8) as usize;
        if self.buf.len() < bytes {
            self.buf.resize(bytes, 0);
        }
    }
    #[cfg(feature = "bits")]
    pub(crate) fn put(&mut self, len: u32, v: u64) {
        let at = self.pos;
        self.zeros(len as u64);
        set_bits(&mut self.buf, at, len, v, self.p.order);
    }
    #[cfg(feature = "bits")]
    pub(crate) fn fail(&self, what: impl AsRef<str>) -> Error {
        Error { msg: format!("transform-encode: format `{}`: {}", self.p.format, what.as_ref()) }
    }
    #[cfg(feature = "bits")]
    fn bit(&self, c: &Cond) -> bool {
        let set = self.presence.get(&c.id).and_then(|b| b.get(c.bit as usize - 1)).copied().unwrap_or(false);
        set != c.neg
    }
}

#[cfg(feature = "bits")]
fn encode_body(body: &SeqBody, ent: &Entity, item: bool, w: &mut Writer) -> Result<(), Error> {
    let kind = select(w.p, body, ent, item)?;
    let defs = Defaults::of(w.p, body, kind);
    let kind_lines: &[SeqLine] = kind.map_or(&[], |k| k.lines.as_slice());
    w.back.push(Decoded::new());
    // a presence among the common lines is visible in the kind's lines
    encode_lines(&body.common, kind_lines, ent, defs, w)?;
    if let Some(k) = kind {
        let start = w.pos;
        // what decode holds where the common lines end
        let windows = k.whens.iter().any(|l| l.at.is_some());
        let before = if windows { w.back.last().cloned() } else { None };
        // a `when … at` occupies no bits: its window is settled once the
        // lines it covers are written (engine-spec v0.33)
        for line in k.whens.iter().filter(|l| l.at.is_none()) {
            write_when(w, line, ent)?;
        }
        if let Some(before) = before {
            encode_lines(&kind_lines[..k.prefix], &[], ent, defs, w)?;
            settle_windows(k, start, before, ent, w)?;
            encode_lines(&kind_lines[k.prefix..], &[], ent, defs, w)?;
        } else {
            encode_lines(kind_lines, &[], ent, defs, w)?;
        }
    }
    w.back.pop();
    Ok(())
}

/// Settle the windows of the `when … at` lines of kind `k`, whose kind start
/// is `start` and where decode held `before`, in line order (engine-spec v0.33, Encode, rulings 1, 5, 12
/// and 13). The lines the windows cover are written; what decode reads back
/// from them is read again from the bits as they stand after.
#[cfg(feature = "bits")]
fn settle_windows(k: &SeqKind, start: u64, before: Decoded, ent: &Entity, w: &mut Writer) -> Result<(), Error> {
    let p = w.p;
    let order = p.order;
    // the bits a held key wrote (ruling 12), from kind start
    let span = (w.pos - start) as usize;
    let mut held = vec![false; span];
    let mark = |held: &mut Vec<bool>, at: u64, len: u32| {
        for q in at..at + len as u64 {
            if let Some(b) = held.get_mut((q - start) as usize) {
                *b = true;
            }
        }
    };
    // (bit, line) of each line the windows may cover
    let mut fields: Vec<(u64, &SeqLine)> = Vec::new();
    let mut plain: Vec<(u64, &SeqWhen)> = Vec::new();
    let mut pos = start;
    for l in k.whens.iter().filter(|l| l.at.is_none()) {
        plain.push((pos, l));
        // the line's held key wrote them (ruling 16 of 0.52)
        if l.key.as_ref().map_or(false, |key| ent.fields.contains_key(key)) {
            mark(&mut held, pos, l.len);
        }
        pos += l.len as u64;
    }
    for line in &k.lines[..k.prefix] {
        match line {
            SeqLine::Field { f, len, also, .. } => {
                if std::iter::once(f).chain(also.iter()).any(|x| has_key(ent, x)) {
                    mark(&mut held, pos, *len);
                }
                fields.push((pos, line));
                pos += *len as u64;
            }
            SeqLine::Const { len, .. } => pos += *len as u64,
            SeqLine::Pad { len } => pos += *len,
            _ => {}
        }
    }
    let mut looks: Vec<(u64, &SeqWhen)> = Vec::new();
    for line in k.whens.iter().filter(|l| l.at.is_some()) {
        let at = start + line.at.unwrap_or(0);
        let len = line.len;
        looks.push((at, line));
        let cur = get_bits(&w.buf, at, len, order).unwrap_or(0);
        let held_as = line.key.as_ref().and_then(|key| ent.fields.get(key));
        let stands = in_list(&line.values, cur) && held_as.map_or(true, |v| as_bits(v) == Some(cur));
        if !stands {
            let v = when_bits(p, line, ent)?;
            let mut next = w.buf.clone();
            set_bits(&mut next, at, len, v, order);
            for q in at..at + len as u64 {
                let is_held = held.get((q - start) as usize).copied().unwrap_or(false);
                if is_held && get_bits(&next, q, 1, order) != get_bits(&w.buf, q, 1, order) {
                    return Err(w.fail(format!(
                        "the window of `when {} … at {}` of line {} would change bits a held key wrote: the output would decode a different value",
                        len,
                        line.at.unwrap_or(0),
                        line.line
                    )));
                }
            }
            w.buf = next;
        }
        // the bits of a window whose key is held are that key's; those of
        // another window stay whose they were (ruling 16 of 0.52)
        if held_as.is_some() {
            mark(&mut held, at, len);
        }
    }
    // what decode reads from the kind's `when` lines, then from the covered
    // lines, from the bits as they stand after every window; a key the common
    // lines set keeps its value
    let mut back = before;
    for (at, line) in plain.iter().map(|(at, l)| (*at, *l)).chain(looks) {
        if let (Some(key), Some(v)) = (&line.key, get_bits(&w.buf, at, line.len, order)) {
            set_as(&mut back, key, v);
        }
    }
    for (at, line) in fields {
        if let SeqLine::Field { f, len, also, .. } = line {
            read_back(p, f, *len, also, &w.buf, at, &mut back);
        }
    }
    *w.back.last_mut().expect("a scope") = back;
    Ok(())
}

/// Write `lines`. `tail`: the lines that follow them in the same block, which
/// may name a presence declared here.
#[cfg(feature = "bits")]
fn encode_lines(lines: &[SeqLine], tail: &[SeqLine], ent: &Entity, defs: Defaults, w: &mut Writer) -> Result<(), Error> {
    let p = w.p;
    for (i, line) in lines.iter().enumerate() {
        match line {
            SeqLine::Field { f, also, .. } if f.until.is_some() => {
                let at = w.pos;
                let (codes, width) = until_codes(p, f, also, ent, defs)?;
                w.zeros(codes.len() as u64 * width as u64);
                for (i, c) in codes.iter().enumerate() {
                    set_bits(&mut w.buf, at + i as u64 * width as u64, width, *c as u64, p.order);
                }
                if let Ok((_, v)) = read_until(p, f, &w.buf, at, w.buf.len() as u64 * 8) {
                    let back = w.back.last_mut().expect("a scope");
                    for a in also {
                        back.put(p, a, v.clone());
                    }
                    back.put(p, f, v);
                }
            }
            SeqLine::Field { f, len, also, uper } => {
                // the earliest of the field's keys that the entity holds; when
                // it holds none, the default of the earliest key that has one
                // (rulings 13 and 16 of 0.8)
                // (a line suppressed by `with` is none of them: engine-spec v0.18)
                if let Some(loc) = uper {
                    let at = w.pos;
                    write_uper_line(w, f, loc, also, ent, defs)?;
                    // what decode reads back from these bits (engine-spec v0.20)
                    read_back_uper(p, f, loc, also, &w.buf, at, w.back.last_mut().expect("a scope"));
                    continue;
                }
                let at = w.pos;
                // an absent key writes zero bits
                w.zeros(*len as u64);
                write_line(p, f, *len, also, ent, defs, at, &mut w.buf)?;
                // what decode reads back from these bits (engine-spec v0.20)
                read_back(p, f, *len, also, &w.buf, at, w.back.last_mut().expect("a scope"));
            }
            SeqLine::Const { len, value } => w.put(*len, *value),
            SeqLine::When(line) => write_when(w, line, ent)?,
            SeqLine::Pad { len } => w.zeros(*len),
            SeqLine::Align { n } => w.zeros((n - w.pos % n) % n),
            SeqLine::Presence { id, bits, .. } => {
                // presence is computed before it is written: the first of the two passes
                let mut set = vec![false; bits.unwrap_or(0) as usize];
                presence_bits(p, &lines[i + 1..], ent, defs, w.look, *id, &mut set);
                presence_bits(p, tail, ent, defs, w.look, *id, &mut set);
                match bits {
                    Some(_) => set.iter().for_each(|b| w.put(1, *b as u64)),
                    None => {
                        // trailing octets that are all zero are not written, and at least one octet is
                        let last = set.iter().rposition(|b| *b).map_or(0, |i| i + 1);
                        let octets = ((last + 6) / 7).max(1);
                        for o in 0..octets {
                            for k in 0..7 {
                                w.put(1, set.get(o * 7 + k).copied().unwrap_or(false) as u64);
                            }
                            w.put(1, (o + 1 < octets) as u64);
                        }
                    }
                }
                w.presence.insert(*id, set);
            }
            SeqLine::If { conds, body } => {
                if conds.iter().all(|c| w.bit(c)) {
                    encode_lines(body, &[], ent, defs, w)?;
                }
            }
            SeqLine::Opt { body } => {
                let present = content(body, ent, defs, w.look);
                w.put(1, present as u64);
                if present {
                    encode_lines(body, &[], ent, defs, w)?;
                }
            }
            SeqLine::Chain { parts, ends_fx } => {
                let mut whole = true;
                for (k, part) in parts.iter().enumerate() {
                    if k > 0 {
                        // 1 when any line after it in the chain would write a present key
                        let more = parts[k..].iter().any(|later| content(later, ent, defs, w.look));
                        w.put(1, more as u64);
                        if !more {
                            whole = false;
                            break;
                        }
                    }
                    encode_lines(part, &[], ent, defs, w)?;
                }
                if whole && *ends_fx {
                    w.put(1, 0);
                }
            }
            SeqLine::Length { len, in_bits, plus, body, units } => {
                let at = w.pos;
                w.zeros(*len as u64);
                let start = w.pos;
                w.extents.push((start, *in_bits));
                let outer_rests = std::mem::replace(&mut w.rests, 0);
                let res = encode_lines(body, &[], ent, defs, w);
                w.rests = outer_rests;
                w.extents.pop();
                res?;
                // a block counted in bytes is padded with zero bits to a whole byte
                if !*in_bits {
                    w.zeros((8 - (w.pos - start) % 8) % 8);
                }
                // the count an earlier line wrote (engine-spec v0.83)
                if let Some((id, u)) = units {
                    let bits = w.pos - start;
                    if bits % *u as u64 != 0 {
                        return Err(w.fail(format!("a block of {} bits is not a whole number of units of {} bits", bits, u)));
                    }
                    let k = *w.counts.get(id).expect("the count line is written before its block");
                    w.count_fields[k].3 = Some(bits / *u as u64);
                    continue;
                }
                let size = (w.pos - start) / if *in_bits { 1 } else { 8 };
                let stated = size as i128 + *plus as i128;
                if stated < 0 || (*len < 64 && stated >> *len != 0) {
                    return Err(w.fail(format!("a length of {} does not fit its {} bits", stated, len)));
                }
                set_bits(&mut w.buf, at, *len, stated as u64, p.order);
            }
            SeqLine::Whole { len, plus } => {
                w.wholes.push((w.pos, *len, *plus));
                w.zeros(*len as u64);
            }
            // engine-spec v0.19: the extension bit 0, then the root components
            SeqLine::Ext { body } => {
                w.put(1, 0);
                encode_lines(body, &[], ent, defs, w)?;
            }
            // the first `alt` with content, else the first `alt`
            SeqLine::Choice { n, ext, alts } => {
                let (i, lines) = match alts.iter().find(|(_, ls)| content(ls, ent, defs, w.look)).or(alts.first()) {
                    Some(a) => a,
                    None => continue,
                };
                if *ext {
                    w.put(1, 0);
                }
                w.put(crate::uper::bits_for(*n as u64 - 1), *i as u64);
                encode_lines(lines, &[], ent, defs, w)?;
            }
            SeqLine::Group(g) => {
                let none: Vec<Entity> = Vec::new();
                let items = ent.lists.get(&g.list).unwrap_or(&none);
                let n = items.len();
                match &g.rep {
                    Rep::Size(size) => {
                        // an absent list: `lb` items with no keys (engine-spec v0.19)
                        let blank: Vec<Entity>;
                        let items = match ent.lists.get(&g.list) {
                            Some(items) => items,
                            None => {
                                blank = vec![Entity::default(); size.map_or(0, |(lb, _)| lb as usize)];
                                &blank
                            }
                        };
                        crate::uper::write_count(w, *size, items.len(), &format!("list `{}`", g.list))?;
                        for item in items {
                            encode_body(&g.body, item, true, w)?;
                        }
                    }
                    Rep::Count(len) => {
                        // an absent list writes a count of 0 (ruling 14 of 0.7)
                        if *len < 64 && (n as u64) >> *len != 0 {
                            return Err(w.fail(format!("list `{}`: {} items do not fit the {}-bit count", g.list, n, len)));
                        }
                        w.put(*len, n as u64);
                        for item in items {
                            encode_body(&g.body, item, true, w)?;
                        }
                    }
                    Rep::While => {
                        for item in items {
                            w.put(1, 1);
                            encode_body(&g.body, item, true, w)?;
                        }
                        w.put(1, 0);
                    }
                    Rep::Rest => {
                        // a `rest` group written in this extent (rulings 10 and 35 of 0.21)
                        w.rests += 1;
                        let mut starts = Vec::with_capacity(n);
                        for (k, item) in items.iter().enumerate() {
                            let start = w.pos;
                            let before = w.rests;
                            encode_body(&g.body, item, true, w)?;
                            // an item before the last that wrote an inner `rest` would take
                            // the rest of the extent (rulings 10 and 35)
                            if k + 1 < n && w.rests > before {
                                return Err(w.fail(format!(
                                    "list `{}`: item {} of {} writes a `rest` list that takes the rest of the extent",
                                    g.list, k, n
                                )));
                            }
                            if w.pos == start {
                                return Err(w.fail(format!("list `{}`: an item writes no bits (ruling 1 of 0.21)", g.list)));
                            }
                            starts.push(start);
                        }
                        // decode reads an item while a whole unit of the extent is left:
                        // an item that starts with less before the padded end would be lost
                        // (ruling 4 of 0.21). The group is the last line of its extent.
                        let (first, in_bits) = *w.extents.last().expect("an extent");
                        let unit = if in_bits { 1 } else { 8 };
                        let end = first + (w.pos - first).div_ceil(unit) * unit;
                        if let Some(at) = starts.iter().position(|s| end - s < unit) {
                            return Err(w.fail(format!(
                                "list `{}`: item {} starts with fewer than {} bits left in its extent; decode would not read it",
                                g.list, at, unit
                            )));
                        }
                    }
                    Rep::Named(ids) => {
                        for item in items {
                            encode_body(&g.body, item, true, w)?;
                        }
                        // each count is written at its own place when the message is finished
                        for id in ids {
                            let k = *w.counts.get(id).expect("the count line is written before its group");
                            w.count_fields[k].3 = Some(n as u64);
                        }
                    }
                    Rep::Last => {
                        if n == 0 {
                            return Err(w.fail(format!("list `{}` is absent or empty, the group holds at least one item", g.list)));
                        }
                        for (k, item) in items.iter().enumerate() {
                            w.put(1, (k + 1 == n) as u64);
                            encode_body(&g.body, item, true, w)?;
                        }
                    }
                    Rep::More | Rep::Fx => {
                        if n == 0 {
                            return Err(w.fail(format!("list `{}` is absent or empty, the group holds at least one item", g.list)));
                        }
                        for (k, item) in items.iter().enumerate() {
                            let more = (k + 1 < n) as u64;
                            if g.rep == Rep::More {
                                w.put(1, more);
                            }
                            encode_body(&g.body, item, true, w)?;
                            if g.rep == Rep::Fx {
                                w.put(1, more);
                            }
                        }
                    }
                }
            }
            SeqLine::Switch(sw) => {
                // the case decode would select from the bits the key's line
                // wrote; a key whose line wrote nothing is absent (engine-spec v0.20)
                // a key that does not read back: the output would not decode (ruling 31 of 0.20)
                // a later line of the key whose table fails fails the decode
                // (ruling 26 of 0.64), so the key does not read back then either
                let back = w.back.last().expect("a scope");
                let state = match back.hard_keys.contains(&sw.key) {
                    true => Err(back.hard.iter().rev().find(|(k, _, _)| *k == sw.key).map(|(_, _, m)| m.clone()).unwrap_or_default()),
                    false => key_state(back, &sw.key),
                };
                let value = match state {
                    Ok(v) => v,
                    Err(m) => {
                        w.look.set(sw, ent, None);
                        return Err(w.fail(format!("`switch {}` of line {}: the key does not read back: {}", sw.key, sw.line, m)));
                    }
                };
                let pick = sw.pick(value.as_deref());
                w.look.set(sw, ent, pick);
                let c = match pick {
                    Some(i) => sw.case(i),
                    None => {
                        return err(format!(
                            "no-kind: format `{}`: `switch {}` of line {}: {} selects no case and there is no `else`",
                            p.format,
                            sw.key,
                            sw.line,
                            value.map_or("the absent key".to_string(), |v| format!("`{}`", v))
                        ))
                    }
                };
                encode_lines(&c.lines, &[], ent, defs.inside(c), w)?;
            }
            // engine-spec v0.34: the checks, a whole byte, then the inner message
            SeqLine::Inner { format, run, reach, withs, .. } => {
                let h = inner_host(w.look.host, p, format, *run, reach, withs)?;
                if w.pos % 8 != 0 {
                    return Err(w.fail(format!("the `inner {}` message would start at bit {}, inside a byte", format, w.pos)));
                }
                let messages = match w.look.messages {
                    Some(m) if *run => m,
                    _ => std::slice::from_ref(ent),
                };
                for m in messages {
                    let bytes = h.inner_encode(format, m).map_err(|e| inner_error(p, e))?;
                    // ruling 8 of 0.92
                    if *run && bytes.is_empty() {
                        return Err(w.fail(format!("a message of the `{}` run writes no bytes: it could not be found again", format)));
                    }
                    let at = (w.pos / 8) as usize;
                    w.zeros(bytes.len() as u64 * 8);
                    w.buf[at..at + bytes.len()].copy_from_slice(&bytes);
                }
            }
            // a group or block not reached leaves the field its `plus`
            // (ruling 6 of 0.21)
            SeqLine::Count { id, len, plus, .. } => {
                w.counts.insert(*id, w.count_fields.len());
                w.count_fields.push((w.pos, *len, *plus, None));
                w.zeros(*len as u64);
            }
        }
    }
    Ok(())
}

#[cfg(feature = "bits")]
pub fn encode(p: &Pack, body: &SeqBody, ent: &Entity) -> Result<Vec<u8>, Error> {
    encode_bits(p, body, ent).map(|(b, _)| b)
}

/// The message as whole bytes, and the cursor after the last line.
#[cfg(feature = "bits")]
pub fn encode_bits(p: &Pack, body: &SeqBody, ent: &Entity) -> Result<(Vec<u8>, u64), Error> {
    encode_host(p, body, ent, None)
}

/// `encode_bits` with the engine that finds the pack of an `inner` line.
#[cfg(feature = "bits")]
pub(crate) fn encode_host(p: &Pack, body: &SeqBody, ent: &Entity, host: Option<&dyn InnerHost>) -> Result<(Vec<u8>, u64), Error> {
    encode_run(p, body, ent, host, None)
}

/// The kind encode chooses for an entity, and the format of the `run` line in
/// reach of it, when there is one (engine-spec v0.92, ruling 6).
#[cfg(feature = "bits")]
pub(crate) fn run_target<'b>(p: &Pack, body: &'b SeqBody, ent: &Entity) -> Result<(Option<&'b str>, Option<&'b str>), Error> {
    let kind = select(p, body, ent, false)?;
    let run = run_in(&body.common).or_else(|| kind.and_then(|k| run_in(&k.lines)));
    Ok((kind.map(|k| k.name.as_str()), run))
}

/// `encode_host` with the messages of the run (engine-spec v0.92).
#[cfg(feature = "bits")]
pub(crate) fn encode_run(
    p: &Pack,
    body: &SeqBody,
    ent: &Entity,
    host: Option<&dyn InnerHost>,
    messages: Option<&[Entity]>,
) -> Result<(Vec<u8>, u64), Error> {
    let look = Look { p, host, messages, picks: Default::default(), changed: Default::default() };
    // a pass whose switches select other cases than were looked up runs again
    let mut pass = 0;
    let mut w = loop {
        pass += 1;
        look.changed.set(false);
        let mut w = Writer { p, buf: Vec::new(), pos: 0, presence: BTreeMap::new(), wholes: Vec::new(), back: Vec::new(), look: &look, count_fields: Vec::new(), counts: HashMap::new(), extents: vec![(0, false)], rests: 0 };
        let res = encode_body(body, ent, false, &mut w);
        if !look.changed.get() {
            res?;
            break w;
        }
        if pass >= 16 {
            return err(format!(
                "transform-encode: format `{}`: the cases the switches select do not settle",
                p.format
            ));
        }
    };
    // each count, range-checked now (ruling 30 of 0.21); one whose group or
    // block was not written holds its `plus` (ruling 6 of 0.21)
    for (at, len, plus, n) in std::mem::take(&mut w.count_fields) {
        let v = n.unwrap_or(0) as i128 + plus as i128;
        if v < 0 || v >> len != 0 {
            return Err(w.fail(format!("a count of {} does not fit its {} bits", v, len)));
        }
        set_bits(&mut w.buf, at, len, v as u64, p.order);
    }
    // an encoding of no bits is one octet `00` (engine-spec v0.19, X.691 10.1.3)
    if p.uper && w.buf.is_empty() {
        w.buf.push(0);
    }
    // a message is a whole number of bytes; the last bits are zero
    let bytes = w.buf.len() as i128;
    for (at, len, plus) in std::mem::take(&mut w.wholes) {
        let stated = bytes + plus as i128;
        if stated < 0 || (len < 64 && stated >> len != 0) {
            return Err(w.fail(format!("a message length of {} does not fit its {} bits", stated, len)));
        }
        set_bits(&mut w.buf, at, len, stated as u64, p.order);
    }
    Ok((w.buf, w.pos))
}
