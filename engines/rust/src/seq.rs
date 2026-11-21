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
    /// as many items as the `count` line of this id states (engine-spec v0.21)
    Named(usize),
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
    /// a `when` among common lines: it must hold for any message. `values`:
    /// every listed value and range (engine-spec v0.20); `value` is written
    When { len: u32, value: u64, values: Vec<(u64, u64)> },
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
    Length { len: u32, in_bits: bool, plus: i64, body: Vec<SeqLine> },
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
    /// the first line of the scope that maps the key: (field, bit length,
    /// `also` keys, UPER locator); the first prediction of encode (ruling 37
    /// of 0.20)
    pub first: (FieldDef, u32, Vec<FieldDef>, Option<crate::uper::Loc>),
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
    /// (bit length, value written, every value and range): the first lines of the kind
    pub whens: Vec<(u32, u64, Vec<(u64, u64)>)>,
    pub requires: Vec<ReqDef>,
    pub lines: Vec<SeqLine>,
    pub defaults: Vec<DefaultDef>,
}

/// The lines of a message, or of one item of a group: common lines, then kinds.
#[derive(Clone, Debug, Default)]
pub struct SeqBody {
    pub common: Vec<SeqLine>,
    pub kinds: Vec<SeqKind>,
    pub defaults: Vec<DefaultDef>,
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
                ff(&mut sw.first.0);
                sw.first.2.iter_mut().for_each(|a| ff(a));
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
        fn lines(prefix: &str, ls: &[SeqLine], out: &mut Vec<String>) {
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
                        lines(prefix, body, out)
                    }
                    SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| lines(prefix, p, out)),
                    SeqLine::Choice { alts, .. } => alts.iter().for_each(|(_, p)| lines(prefix, p, out)),
                    SeqLine::Group(g) => {
                        let name = format!("{}{}[]", prefix, g.list);
                        if !out.contains(&name) {
                            out.push(name.clone());
                        }
                        g.body.model_keys(&format!("{}.", name), out);
                    }
                    // keys mapped only inside a case are listed too (ruling 13 of 0.20)
                    SeqLine::Switch(sw) => sw.bodies().for_each(|c| lines(prefix, &c.lines, out)),
                    _ => {}
                }
            }
        }
        lines(prefix, &self.common, out);
        for k in &self.kinds {
            lines(prefix, &k.lines, out);
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
    mapped: Vec<(String, (FieldDef, u32, Vec<FieldDef>, Option<crate::uper::Loc>))>,
    /// the `default` lines of the scope being read
    defaults: Vec<DefaultDef>,
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

const HEADER: [&str; 17] = [
    "format", "version", "wire", "layout", "bit_order", "distribution", "source", "uses", "map", "typemap", "word_bytes", "root",
    "delimiter", "start", "checksum", "armor", "encoding",
];

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<&'a (usize, Vec<String>)> {
        self.lines.get(self.i)
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
                    });
                    kind_has_lines = false;
                    self.i += 1;
                }
                "when" => {
                    if toks.len() != 3 {
                        return bad(ln, "when needs <len> <value>");
                    }
                    let len = value_len(&toks[1], ln)?;
                    // a list of values and ranges (engine-spec v0.20)
                    if toks[2].split(',').any(|v| v == "present") {
                        return bad(ln, "`present` is not a value of a bits `when`");
                    }
                    let values = num_list(&toks[2], Some(len), ln)?;
                    let value = values[0].0;
                    when_line.get_or_insert(ln);
                    match out.kinds.last_mut() {
                        Some(_) if kind_has_lines => {
                            return bad(ln, "the `when` lines of a kind are its first lines");
                        }
                        Some(k) => k.whens.push((len, value, values)),
                        None => out.common.push(SeqLine::When { len, value, values }),
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
                };
                for table in field_options(&mut f, toks, ln, false)? {
                    self.vias.push((table, ln));
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
                let line = (f.clone(), len as u32, also.clone(), uper.clone());
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
                    SeqLine::Length { len, in_bits, plus, body: self.block(ln, "length")? }
                }
            }
            "group" => {
                let rep = match (toks.get(2).map(|s| s.as_str()), toks.len()) {
                    // `count @<name>`: the count of an earlier `count` line (engine-spec v0.21)
                    (Some("count"), 4) if toks[3].starts_with('@') => {
                        let name = &toks[3][1..];
                        match self.names.iter().rev().find(|(n, _, _)| n == name) {
                            Some((_, id, Named::Count(depth))) if *depth == self.body_depth => Rep::Named(*id),
                            Some((_, _, Named::Count(_))) => {
                                return bad(ln, format!("`count {}` names a count of another group body (ruling 9 of 0.21)", toks[3]));
                            }
                            Some((_, _, Named::Presence(_))) => return bad(ln, format!("`count {}` names a presence, not a count", toks[3])),
                            None => return bad(ln, format!("`count {}` names a count that is not visible here", toks[3])),
                        }
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
            SeqLine::Group(g) if g.rep == Rep::Named(id) => add(&mut at, (1, 1)),
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => {
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
                    return bad(*line, "the count is not referenced by a `group … count @` line on every reading path");
                }
                if hi > 1 {
                    return bad(*line, "the count is referenced by two groups on one reading path");
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
        uper_line: None,
        to_cot: BTreeMap::new(),
        from_cot: BTreeMap::new(),
    };
    let mut body = p.body(true, 0)?;
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
    check_rest_body(&body, false, true)?;
    match p.wire.as_deref() {
        Some("bits") => {}
        Some(_) => return err("bad-directive: `layout` is valid only on a bits wire"),
        None => return err("missing-wire: the pack has no `wire` line"),
    }
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
    for (table, ln) in &p.vias {
        if !p.maps.iter().any(|(name, _)| name == table) {
            return bad(*ln, format!("`via {}` names a table with no `map` line", table));
        }
    }
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
        armor,
        gates: Vec::new(),
        elements: Vec::new(),
        uper,
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
    counts: HashMap<usize, Option<u64>>,
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
        if self.end.saturating_sub(self.pos) < len {
            let place = if self.depth > 0 { "the `length` extent" } else { "the input" };
            return Err(self.short(format!("{} ends before {} at bit {}", place, what, self.pos)));
        }
        Ok(())
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
        if self.depth > 0 && self.pos >= self.end {
            return Ok(0);
        }
        self.read(1, what)
    }
}

/// The kind of a body the wire selects, after its common lines: the first
/// whose `when` lines all hold, read from the cursor.
#[cfg(feature = "bits")]
fn decode_body<'a>(body: &'a SeqBody, r: &mut Reader, d: &mut Decoded) -> Result<Option<&'a SeqKind>, Error> {
    decode_kind(body, r, d)
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
        let holds = k.whens.iter().all(|(len, _, values)| {
            // a `when` any of whose bits lies beyond the input does not hold
            let ok = r.end.saturating_sub(at) >= *len as u64
                && get_bits(r.raw, at, *len, r.p.order).map_or(false, |v| in_list(values, v));
            at += *len as u64;
            ok
        });
        if holds {
            r.pos = at;
            decode_lines(&k.lines, r, d)?;
            return Ok(Some(k));
        }
    }
    err(format!("no-kind: format `{}`: the bits at {} match no kind", r.p.format, start))
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
        if r.depth > 0 && r.pos >= r.end && !matches!(line, SeqLine::Switch(_) | SeqLine::If { .. } | SeqLine::Chain { .. }) {
            match line {
                SeqLine::Presence { id, .. } => {
                    r.presence.insert(*id, Vec::new());
                }
                SeqLine::Count { id, .. } => {
                    r.counts.insert(*id, None);
                }
                SeqLine::Group(g) if g.rep == Rep::Rest => d.put_list(&g.list, Vec::new()),
                _ => {}
            }
            continue;
        }
        match line {
            SeqLine::Field { f, also, .. } if f.until.is_some() => {
                let (bits, v) = read_until(r.p, f, r.raw, r.pos, r.end).map_err(|e| r.short(e.msg))?;
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
                r.pos = (r.pos + skip).min(r.end.max(r.pos));
            }
            SeqLine::When { len, value, values } => {
                if r.end.saturating_sub(r.pos) < *len as u64 || !in_list(values, r.read(*len, "a `when`")?) {
                    return err(format!("no-kind: format `{}`: common `when {} {}` does not hold", r.p.format, len, value));
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
                }
            }
            SeqLine::Opt { body } => {
                if r.read(1, "the bit of an `opt`")? == 1 {
                    decode_lines(body, r, d)?;
                }
            }
            SeqLine::Chain { parts, ends_fx } => {
                let mut whole = true;
                for (i, part) in parts.iter().enumerate() {
                    if i > 0 && r.indicator("an `fx` bit")? == 0 {
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
            SeqLine::Length { len, in_bits, plus, body } => {
                let stated = r.read(*len, "a `length`")? as i128 - *plus as i128;
                let unit: i128 = if *in_bits { 1 } else { 8 };
                let extent = stated * unit;
                if stated < 0 || r.pos as i128 + extent > r.end as i128 {
                    return Err(r.short(format!("a `length` of {} {} does not fit", stated, if *in_bits { "bits" } else { "bytes" })));
                }
                let stop = r.pos + extent as u64;
                let outer = std::mem::replace(&mut r.end, stop);
                let outer_unit = std::mem::replace(&mut r.unit, if *in_bits { 1 } else { 8 });
                r.depth += 1;
                let res = decode_lines(body, r, d);
                r.depth -= 1;
                r.unit = outer_unit;
                // content of the extent no line reads is skipped
                r.pos = stop;
                r.end = outer.min(r.whole);
                res?;
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
                r.whole = bits as u64;
                r.end = r.end.min(r.whole);
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
                d.replacing(&g.list);
                // a counted group takes its items at once (7d)
                let counted = matches!(g.rep, Rep::Count(_));
                let item = |r: &mut Reader, items: &mut Vec<Decoded>| -> Result<(), Error> {
                    if !counted {
                        limit::take(&format, &g.list, 1)?;
                    }
                    let mut di = Decoded::new();
                    let kind = decode_body(&g.body, r, &mut di)?;
                    di.ent.kind = kind.map(|k| (format.clone(), k.name.clone()));
                    items.push(di);
                    Ok(())
                };
                match &g.rep {
                    Rep::Count(len) => {
                        let n = r.read(*len, "the count of a group")?;
                        limit::take(&format, &g.list, n)?;
                        if n > r.end.saturating_sub(r.pos) {
                            return Err(r.short(format!("list `{}` has {} items, more than the input holds", g.list, n)));
                        }
                        for _ in 0..n {
                            item(r, &mut items)?;
                        }
                    }
                    Rep::Size(size) => {
                        let n = crate::uper::read_count(r, *size, "the count of a group")?;
                        if n > r.end.saturating_sub(r.pos) {
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
                        while r.end.saturating_sub(r.pos) >= r.unit {
                            let start = r.pos;
                            item(r, &mut items)?;
                            if r.pos == start {
                                return Err(r.short(format!("an item of list `{}` reads no bits (ruling 1 of 0.21)", g.list)));
                            }
                        }
                    }
                    Rep::Named(id) => {
                        let n = match r.counts.get(id).copied().flatten() {
                            Some(n) => n,
                            // the count line lay past the end of its extent: the list is absent
                            None => continue,
                        };
                        // the bits left at the group (ruling 20 of 0.21)
                        if n > r.end.saturating_sub(r.pos) {
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
                d.put_list(&g.list, items);
            }
            SeqLine::Switch(sw) => {
                // the key's value so far, as canonical text (engine-spec v0.20)
                // a key whose line failed its transform fails the decode (ruling 35 of 0.20)
                let value = match key_state(d, &sw.key) {
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
            SeqLine::Count { id, len, plus, .. } => {
                let v = r.read(*len, "a `count`")?;
                // `value − n` without overflow; below `n` is checked here (ruling 7 of 0.21)
                let n = v as i128 - *plus as i128;
                if n < 0 {
                    return Err(r.short(format!("a count of {} is below its `plus {}`", v, plus)));
                }
                // more items than u64 holds are more than any input's bits
                r.counts.insert(*id, Some(u64::try_from(n).unwrap_or(u64::MAX)));
            }
        }
    }
    Ok(())
}

/// `total`: the bits of the input (8 a byte of hex, 6 a character of armor).
#[cfg(feature = "bits")]
pub fn decode(p: &Pack, body: &SeqBody, raw: &[u8], total: u64) -> Result<Entity, Error> {
    let mut r = Reader {
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
    let (mut ent, failed) = d.close();
    if !failed.is_empty() {
        return err(format!("transform-decode: format `{}`: {}", p.format, failed.join("; ")));
    }
    ent.kind = kind.map(|k| (p.format.clone(), k.name.clone()));
    Ok(ent)
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
    match body.kinds.iter().find(|k| k.requires.iter().all(|r| r.holds(ent))) {
        Some(k) => Ok(Some(k)),
        None => err(format!("no-kind: format `{}`: the entity has the required keys of no kind", p.format)),
    }
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
        let (f, len, also, uper) = &sw.first;
        let mut back = Decoded::new();
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
        return Err(d.hard.last().cloned().unwrap_or_default());
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
    /// every `count` field written: (bit, len, plus, filled by its group),
    /// filled in once the group is laid out (engine-spec v0.21)
    count_fields: Vec<(u64, u32, i64, bool)>,
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
        for (len, value, _) in &k.whens {
            w.put(*len, *value);
        }
        encode_lines(kind_lines, &[], ent, defs, w)?;
    }
    w.back.pop();
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
            SeqLine::Const { len, value } | SeqLine::When { len, value, .. } => w.put(*len, *value),
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
            SeqLine::Length { len, in_bits, plus, body } => {
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
                    Rep::Named(id) => {
                        for item in items {
                            encode_body(&g.body, item, true, w)?;
                        }
                        // the count is written at its own place now the group is laid out
                        let k = *w.counts.get(id).expect("the count line is written before its group");
                        w.count_fields[k].3 = true;
                        let (at, len, plus, _) = w.count_fields[k];
                        let v = n as i128 + plus as i128;
                        if v < 0 || (len < 64 && v >> len != 0) || v > u64::MAX as i128 {
                            return Err(w.fail(format!("list `{}`: a count of {} does not fit its {} bits", g.list, v, len)));
                        }
                        set_bits(&mut w.buf, at, len, v as u64, p.order);
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
                let value = match key_state(w.back.last().expect("a scope"), &sw.key) {
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
            // the field holds `n` until its group is laid out: a group not
            // reached leaves it so (ruling 6 of 0.21)
            // (checked in `encode` once every group is written)
            SeqLine::Count { id, len, plus, .. } => {
                w.counts.insert(*id, w.count_fields.len());
                w.count_fields.push((w.pos, *len, *plus, false));
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
    let look = Look { p, picks: Default::default(), changed: Default::default() };
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
    // a count whose group was not written holds `n` (ruling 6 of 0.21)
    for (at, len, plus, filled) in std::mem::take(&mut w.count_fields) {
        if !filled {
            if plus < 0 || (len < 64 && (plus as u64) >> len != 0) {
                return Err(w.fail(format!("an absent list writes a count of {}, which does not fit its {} bits", plus, len)));
            }
            set_bits(&mut w.buf, at, len, plus as u64, p.order);
        }
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
