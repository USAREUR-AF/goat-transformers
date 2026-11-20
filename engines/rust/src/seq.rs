//! Sequential binary layouts (engine-spec v0.8): a `bits` pack with
//! `layout sequential`. The lines of a message are read, and written, in file
//! order from a cursor; the place of a field depends on what came before it.

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
    /// `also`: the keys of the `also` lines after the field, on the same bits
    Field { f: FieldDef, len: u32, also: Vec<FieldDef> },
    Const { len: u32, value: u64 },
    Pad { len: u64 },
    Align { n: u64 },
    /// a `when` among common lines: it must hold for any message
    When { len: u32, value: u64 },
    /// `bits`: the number of presence bits; None: `fx` octets
    /// `named`: the bits some `if` block names; any other bit set on the wire is `malformed-wire`
    Presence { id: usize, bits: Option<u32>, named: Vec<u32> },
    If { conds: Vec<Cond>, body: Vec<SeqLine> },
    Opt { body: Vec<SeqLine> },
    Group(SeqGroup),
    /// the parts between `fx` lines; `ends_fx`: the last line of the chain is `fx`
    Chain { parts: Vec<Vec<SeqLine>>, ends_fx: bool },
    Length { len: u32, in_bits: bool, plus: i64, body: Vec<SeqLine> },
    /// `length ... whole`: the length of the whole message in bytes plus `plus`
    Whole { len: u32, plus: i64 },
}

/// One kind of a message or of an item.
#[derive(Clone, Debug)]
pub struct SeqKind {
    pub name: String,
    /// (bit length, value): the first lines of the kind
    pub whens: Vec<(u32, u64)>,
    /// (model key, line)
    pub requires: Vec<(String, usize)>,
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
    /// (line, model key)
    Requires(usize, &'a str),
}

fn visit_lines<'a>(lines: &'a [SeqLine], f: &mut dyn FnMut(Visit<'a>)) {
    for l in lines {
        match l {
            SeqLine::Field { f: field, also, .. } => {
                f(Visit::Field(field));
                also.iter().for_each(|a| f(Visit::Field(a)));
            }
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } => visit_lines(body, f),
            SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| visit_lines(p, f)),
            SeqLine::Group(g) => {
                f(Visit::Group(g.line, &g.list));
                g.body.visit(f);
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
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } => visit_lines_mut(body, ff, fd),
            SeqLine::Chain { parts, .. } => parts.iter_mut().for_each(|p| visit_lines_mut(p, ff, fd)),
            SeqLine::Group(g) => g.body.visit_mut(ff, fd),
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
            k.requires.iter().for_each(|(key, line)| f(Visit::Requires(*line, key)));
            visit_lines(&k.lines, f);
            k.defaults.iter().for_each(|d| f(Visit::Default(d)));
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
                    SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } => lines(prefix, body, out),
                    SeqLine::Chain { parts, .. } => parts.iter().for_each(|p| lines(prefix, p, out)),
                    SeqLine::Group(g) => {
                        let name = format!("{}{}[]", prefix, g.list);
                        if !out.contains(&name) {
                            out.push(name.clone());
                        }
                        g.body.model_keys(&format!("{}.", name), out);
                    }
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
    /// the presences visible here, innermost last: (name, id, bits)
    names: Vec<(String, usize, Option<u32>)>,
    /// kind names of the whole pack
    /// where the names of the block being read start in `names`
    block_start: usize,
    /// per presence id: the bits `if` lines name
    named: Vec<Vec<u32>>,
    /// the `default` lines of the scope being read
    defaults: Vec<DefaultDef>,
    /// every `via` table a field names: (table, line)
    vias: Vec<(String, usize)>,
    // header
    format: Option<String>,
    version: Option<String>,
    wire: Option<String>,
    msb: bool,
    distribution: Option<Distribution>,
    sources: Vec<String>,
    uses: Vec<String>,
    maps: Vec<(String, Vec<(String, String)>)>,
    /// engine-spec v0.14: `armor`
    armor: crate::armor::ArmorLines,
    to_cot: BTreeMap<String, String>,
    from_cot: BTreeMap<String, String>,
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

const HEADER: [&str; 16] = [
    "format", "version", "wire", "layout", "bit_order", "distribution", "source", "uses", "map", "typemap", "word_bytes", "root",
    "delimiter", "start", "checksum", "armor",
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
                    return bad(ln, "bit_order needs `lsb` or `msb`");
                }
                self.msb = match toks[1].as_str() {
                    "lsb" => false,
                    "msb" => true,
                    o => return bad(ln, format!("bit_order is `lsb` or `msb`, got `{}`", o)),
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
        let mut out = SeqBody::default();
        let visible = self.names.len();
        let outer_block = std::mem::replace(&mut self.block_start, visible);
        // kind names are unique within one body (ruling 11 of 0.8)
        let mut kind_names: Vec<String> = Vec::new();
        let outer_defaults = std::mem::take(&mut self.defaults);
        // the presences visible when the first `kind` starts: those of a
        // kind's own lines end with the kind
        let mut common_names: Option<usize> = None;
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
                    let value = value_of(&toks[2], len, ln)?;
                    when_line.get_or_insert(ln);
                    match out.kinds.last_mut() {
                        Some(_) if kind_has_lines => {
                            return bad(ln, "the `when` lines of a kind are its first lines");
                        }
                        Some(k) => k.whens.push((len, value)),
                        None => out.common.push(SeqLine::When { len, value }),
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
                    for key in &toks[1..] {
                        k.requires.push((key.clone(), ln));
                    }
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
                let len = bit_len(&toks[2], ln)?;
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
                };
                for table in field_options(&mut f, toks, ln, false)? {
                    self.vias.push((table, ln));
                }
                let t = &f.transform;
                if !t.is_bits() {
                    return bad(ln, format!("transform of `{}` is not valid on a bits wire", f.model_key));
                }
                if !u32::try_from(len).map_or(false, |l| t.bits_len_ok(l)) {
                    return bad(ln, format!("bit length {} is not allowed for the transform of `{}`", len, f.model_key));
                }
                if f.swap && *t == Transform::Sixbit {
                    return bad(ln, "`swap` is not valid on `sixbit`");
                }
                if f.swap && len % 8 != 0 {
                    return bad(ln, format!("`swap` needs a bit length that is a multiple of 8, got {}", len));
                }
                if f.trim && !matches!(t, Transform::Ascii | Transform::Sixbit) {
                    return bad(ln, "`trim` is valid only with `ascii` or `sixbit`");
                }
                if f.swap && t.refuses_swap() {
                    return bad(ln, "`swap` is not valid with `chars` or `octal`");
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
                SeqLine::Field { f, len: len as u32, also }
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
                self.names.push((name.clone(), id, bits));
                SeqLine::Presence { id, bits, named: Vec::new() }
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
                        Some((_, id, size)) => (*id, *size),
                        None => return bad(ln, format!("`{}` names a presence that is not visible here", t)),
                    };
                    if size.map_or(false, |n| bit > n) {
                        return bad(ln, format!("`{}` names a bit beyond the {} bits of the presence", t, size.unwrap_or(0)));
                    }
                    if !self.named[id].contains(&bit) {
                        self.named[id].push(bit);
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
                    (Some("count"), 4) => Rep::Count(value_len(&toks[3], ln)?),
                    (Some("while"), 3) => Rep::While,
                    (Some("more"), 3) => Rep::More,
                    (Some("fx"), 3) => Rep::Fx,
                    (Some(l), _) if l.contains(':') => {
                        return bad(ln, format!("`{}` is a positional locator; a sequential group is `count <len>`, `while`, `more` or `fx`", l));
                    }
                    _ => return bad(ln, "group needs <list> and `count <len>`, `while`, `more` or `fx`"),
                };
                SeqLine::Group(SeqGroup { list: toks[1].clone(), rep, body: self.body(false, ln)?, line: ln })
            }
            "fx" => return bad(ln, "`fx` outside a `chain`"),
            "also" => return bad(ln, "`also` stands directly after a `field` line"),
            "end" => return bad(ln, "`end` with no open block"),
            d @ ("kind" | "when" | "requires") => {
                return bad(ln, format!("`{}` is not allowed inside an `if`, `opt`, `chain` or `length` block", d));
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
                SeqLine::Length { body, .. } => walk(body, blocks, next, out)?,
                SeqLine::Chain { parts, .. } => {
                    for part in parts {
                        walk(part, blocks, next, out)?;
                    }
                }
                SeqLine::Group(g) => {
                    out.push((&g.list, g.line, blocks.clone()));
                    check_lists(&g.body)?;
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
        block_start: 0,
        named: Vec::new(),
        defaults: Vec::new(),
        vias: Vec::new(),
        format: None,
        version: None,
        wire: None,
        msb: false,
        distribution: None,
        sources: Vec::new(),
        uses: Vec::new(),
        maps: Vec::new(),
        armor: Default::default(),
        to_cot: BTreeMap::new(),
        from_cot: BTreeMap::new(),
    };
    let mut body = p.body(true, 0)?;
    fn fill(lines: &mut [SeqLine], named: &[Vec<u32>]) {
        for l in lines {
            match l {
                SeqLine::Presence { id, named: n, .. } => *n = named[*id].clone(),
                SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } => fill(body, named),
                SeqLine::Chain { parts, .. } => parts.iter_mut().for_each(|p| fill(p, named)),
                SeqLine::Group(g) => fill_body(&mut g.body, named),
                _ => {}
            }
        }
    }
    fn fill_body(b: &mut SeqBody, named: &[Vec<u32>]) {
        fill(&mut b.common, named);
        b.kinds.iter_mut().for_each(|k| fill(&mut k.lines, named));
    }
    fill_body(&mut body, &p.named);
    check_lists(&body)?;
    // after the file is read (ruling 5b of 0.11): the missing header lines first
    if p.format.is_none() {
        return err("missing-format: the pack has no `format` line");
    }
    if p.version.is_none() {
        return err("missing-version: the pack has no `version` line");
    }
    match p.wire.as_deref() {
        Some("bits") => {}
        Some(_) => return err("bad-directive: `layout` is valid only on a bits wire"),
        None => return err("missing-wire: the pack has no `wire` line"),
    }
    let armor = p.armor.check(true, p.msb)?;
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
        msb: p.msb,
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
    })
}

// ---------------------------------------------------------------------------
// Decode
// ---------------------------------------------------------------------------

struct Reader<'a> {
    p: &'a Pack,
    raw: &'a [u8],
    pos: u64,
    /// the first bit the lines may not read: the end of the input, of the
    /// message (`length ... whole`) or of the innermost `length` extent
    end: u64,
    /// the end of the message
    whole: u64,
    /// how many `length` blocks are open
    depth: usize,
    /// the bits of each presence read so far, by id; a bit not held is 0
    presence: BTreeMap<usize, Vec<bool>>,
}

impl<'a> Reader<'a> {
    fn short(&self, what: impl AsRef<str>) -> Error {
        Error { msg: format!("malformed-wire: format `{}`: {}", self.p.format, what.as_ref()) }
    }
    fn need(&self, len: u64, what: &str) -> Result<(), Error> {
        // `pos` may stand past `end` after a `length` block; nothing overflows
        if self.end.saturating_sub(self.pos) < len {
            let place = if self.depth > 0 { "the `length` extent" } else { "the input" };
            return Err(self.short(format!("{} ends before {} at bit {}", place, what, self.pos)));
        }
        Ok(())
    }
    /// `len` (1..=64) bits at the cursor as an unsigned value.
    fn read(&mut self, len: u32, what: &str) -> Result<u64, Error> {
        self.need(len as u64, what)?;
        let v = get_bits(self.raw, self.pos, len, self.p.msb).unwrap_or(0);
        self.pos += len as u64;
        Ok(v)
    }
    fn bit(&self, c: &Cond) -> bool {
        let set = self.presence.get(&c.id).and_then(|b| b.get(c.bit as usize - 1)).copied().unwrap_or(false);
        set != c.neg
    }
    /// The indicator bit of a `while`, `more` or `fx` group, or an `fx` bit
    /// of a chain. At or after the end of a `length` extent it reads as 0
    /// (ruling 21 of 0.8); past the end of the input it is `malformed-wire`.
    fn indicator(&mut self, what: &str) -> Result<u64, Error> {
        if self.depth > 0 && self.pos >= self.end {
            return Ok(0);
        }
        self.read(1, what)
    }
}

/// The kind of a body the wire selects, after its common lines: the first
/// whose `when` lines all hold, read from the cursor.
fn decode_body<'a>(body: &'a SeqBody, r: &mut Reader, d: &mut Decoded) -> Result<Option<&'a SeqKind>, Error> {
    decode_lines(&body.common, r, d)?;
    if body.kinds.is_empty() {
        return Ok(None);
    }
    let start = r.pos;
    for k in &body.kinds {
        let mut at = start;
        let holds = k.whens.iter().all(|(len, value)| {
            // a `when` any of whose bits lies beyond the input does not hold
            let ok = r.end.saturating_sub(at) >= *len as u64 && get_bits(r.raw, at, *len, r.p.msb) == Some(*value);
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

fn decode_lines(lines: &[SeqLine], r: &mut Reader, d: &mut Decoded) -> Result<(), Error> {
    for line in lines {
        // inside a `length` block, lines beyond its extent read as absent
        if r.depth > 0 && r.pos >= r.end {
            if let SeqLine::Presence { id, .. } = line {
                r.presence.insert(*id, Vec::new());
            }
            continue;
        }
        match line {
            SeqLine::Field { f, len, also } => {
                r.need(*len as u64, &format!("`{}`", f.model_key))?;
                // a sentinel: neither the field's key nor an `also` key gets a value (engine-spec v0.9)
                if is_sentinel(r.p, f, r.raw, r.pos, *len) {
                    r.pos += *len as u64;
                    continue;
                }
                let v = read_field(r.p, f, r.raw, r.pos, *len);
                r.pos += *len as u64;
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
            SeqLine::When { len, value } => {
                if r.end.saturating_sub(r.pos) < *len as u64 || r.read(*len, "a `when`")? != *value {
                    return err(format!("no-kind: format `{}`: common `when {} {}` does not hold", r.p.format, len, value));
                }
            }
            SeqLine::Presence { id, bits, named } => {
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
                // ruling 1 of 0.8: a bit that is 1 and that no `if` block names
                if let Some(i) = set.iter().enumerate().position(|(i, b)| *b && !named.contains(&(i as u32 + 1))) {
                    return Err(r.short(format!("presence bit {} is 1 and no `if` block names it", i + 1)));
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
                r.depth += 1;
                let res = decode_lines(body, r, d);
                r.depth -= 1;
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
                }
                d.put_list(&g.list, items);
            }
        }
    }
    Ok(())
}

/// `total`: the bits of the input (8 a byte of hex, 6 a character of armor).
pub fn decode(p: &Pack, body: &SeqBody, raw: &[u8], total: u64) -> Result<Entity, Error> {
    let mut r = Reader { p, raw, pos: 0, end: total, whole: total, depth: 0, presence: BTreeMap::new() };
    let mut d = Decoded::new();
    let kind = decode_body(body, &mut r, &mut d)?;
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
/// this format, else the first kind whose `requires` keys are all present.
/// An item (`item`) whose kind names this format and a kind its group does
/// not have is selected by `requires` too (ruling 26 of 0.8); for a message
/// that is `no-kind` (ruling 24 of 0.5).
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
    let has = |key: &String| ent.fields.contains_key(key) || ent.lists.get(key).map_or(false, |l| !l.is_empty());
    match body.kinds.iter().find(|k| k.requires.iter().all(|(key, _)| has(key))) {
        Some(k) => Ok(Some(k)),
        None => err(format!("no-kind: format `{}`: the entity has the required keys of no kind", p.format)),
    }
}

/// The defaults in force: the selected kind's first, then the common ones.
#[derive(Clone, Copy)]
struct Defaults<'a> {
    kind: &'a [DefaultDef],
    common: &'a [DefaultDef],
}

impl<'a> Defaults<'a> {
    fn of(body: &'a SeqBody, kind: Option<&'a SeqKind>) -> Defaults<'a> {
        Defaults { kind: kind.map_or(&[], |k| k.defaults.as_slice()), common: &body.defaults }
    }
    /// The `default` of a key, if it has one.
    fn default(&self, key: &str) -> Option<&'a Value> {
        self.kind.iter().chain(self.common.iter()).find(|d| d.model_key == key).and_then(|d| d.value.as_ref())
    }
    /// The value encode uses for a key: the entity's, else the `default`.
    fn value(&self, ent: &'a Entity, key: &str) -> Option<&'a Value> {
        ent.fields.get(key).or_else(|| self.default(key))
    }
}

/// Would these lines write a present key or a non-empty list? A key with a
/// `default` in scope counts as present (ruling 2 of 0.8).
fn content(lines: &[SeqLine], ent: &Entity, defs: Defaults) -> bool {
    lines.iter().any(|l| match l {
        // a line suppressed by `with` is not content, nor is its default (ruling 1 of 0.18)
        SeqLine::Field { f, also, .. } => {
            std::iter::once(f).chain(also.iter()).any(|k| live(ent, k) && defs.value(ent, &k.model_key).is_some())
        }
        SeqLine::Group(g) => ent.lists.get(&g.list).map_or(false, |l| !l.is_empty()),
        SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } => content(body, ent, defs),
        SeqLine::Chain { parts, .. } => parts.iter().any(|p| content(p, ent, defs)),
        _ => false,
    })
}

/// The bits of presence `id`: bit i is 1 when some `if` block naming it
/// without `!` would write a present key or a non-empty list.
fn presence_bits(p: &Pack, lines: &[SeqLine], ent: &Entity, defs: Defaults, id: usize, bits: &mut Vec<bool>) {
    for l in lines {
        match l {
            SeqLine::If { conds, body } => {
                if content(body, ent, defs) {
                    for c in conds.iter().filter(|c| c.id == id && !c.neg) {
                        let i = c.bit as usize;
                        if bits.len() < i {
                            bits.resize(i, false);
                        }
                        bits[i - 1] = true;
                    }
                }
                presence_bits(p, body, ent, defs, id, bits);
            }
            SeqLine::Opt { body } | SeqLine::Length { body, .. } => presence_bits(p, body, ent, defs, id, bits),
            SeqLine::Chain { parts, .. } => parts.iter().for_each(|part| presence_bits(p, part, ent, defs, id, bits)),
            SeqLine::Group(g) => {
                for item in ent.lists.get(&g.list).into_iter().flatten() {
                    let kind = select(p, &g.body, item, true).ok().flatten();
                    let item_defs = Defaults::of(&g.body, kind);
                    presence_bits(p, &g.body.common, item, item_defs, id, bits);
                    if let Some(k) = kind {
                        presence_bits(p, &k.lines, item, item_defs, id, bits);
                    }
                }
            }
            _ => {}
        }
    }
}

struct Writer<'a> {
    p: &'a Pack,
    buf: Vec<u8>,
    pos: u64,
    presence: BTreeMap<usize, Vec<bool>>,
    /// `length ... whole` fields to fill once the message is laid out: (bit, len, plus)
    wholes: Vec<(u64, u32, i64)>,
}

impl<'a> Writer<'a> {
    /// `n` zero bits.
    fn zeros(&mut self, n: u64) {
        self.pos += n;
        let bytes = ((self.pos + 7) / 8) as usize;
        if self.buf.len() < bytes {
            self.buf.resize(bytes, 0);
        }
    }
    fn put(&mut self, len: u32, v: u64) {
        let at = self.pos;
        self.zeros(len as u64);
        set_bits(&mut self.buf, at, len, v, self.p.msb);
    }
    fn fail(&self, what: impl AsRef<str>) -> Error {
        Error { msg: format!("transform-encode: format `{}`: {}", self.p.format, what.as_ref()) }
    }
    fn bit(&self, c: &Cond) -> bool {
        let set = self.presence.get(&c.id).and_then(|b| b.get(c.bit as usize - 1)).copied().unwrap_or(false);
        set != c.neg
    }
}

fn encode_body(body: &SeqBody, ent: &Entity, item: bool, w: &mut Writer) -> Result<(), Error> {
    let kind = select(w.p, body, ent, item)?;
    let defs = Defaults::of(body, kind);
    let kind_lines: &[SeqLine] = kind.map_or(&[], |k| k.lines.as_slice());
    // a presence among the common lines is visible in the kind's lines
    encode_lines(&body.common, kind_lines, ent, defs, w)?;
    if let Some(k) = kind {
        for (len, value) in &k.whens {
            w.put(*len, *value);
        }
        encode_lines(kind_lines, &[], ent, defs, w)?;
    }
    Ok(())
}

/// Write `lines`. `tail`: the lines that follow them in the same block, which
/// may name a presence declared here.
fn encode_lines(lines: &[SeqLine], tail: &[SeqLine], ent: &Entity, defs: Defaults, w: &mut Writer) -> Result<(), Error> {
    let p = w.p;
    for (i, line) in lines.iter().enumerate() {
        match line {
            SeqLine::Field { f, len, also } => {
                // the earliest of the field's keys that the entity holds; when
                // it holds none, the default of the earliest key that has one
                // (rulings 13 and 16 of 0.8)
                // (a line suppressed by `with` is none of them: engine-spec v0.18)
                let keys = || std::iter::once(f).chain(also.iter()).filter(|k| live(ent, k));
                let value = keys()
                    .find_map(|k| ent.fields.get(&k.model_key).map(|v| (k, v)))
                    .or_else(|| keys().find_map(|k| defs.default(&k.model_key).map(|v| (k, v))));
                let at = w.pos;
                // an absent key writes zero bits
                w.zeros(*len as u64);
                match value {
                    Some((k, v)) => {
                        let v = p.to_wire(k, v).map_err(|e| transform_encode_err(p, k, e))?;
                        write_field(p, k, &v, at, *len, &mut w.buf)?;
                    }
                    // with `absent`, the first sentinel in place of the zero bits (engine-spec v0.9)
                    None if live(ent, f) => {
                        write_sentinel(p, f, at, *len, &mut w.buf);
                    }
                    None => {}
                }
            }
            SeqLine::Const { len, value } | SeqLine::When { len, value } => w.put(*len, *value),
            SeqLine::Pad { len } => w.zeros(*len),
            SeqLine::Align { n } => w.zeros((n - w.pos % n) % n),
            SeqLine::Presence { id, bits, .. } => {
                // presence is computed before it is written: the first of the two passes
                let mut set = vec![false; bits.unwrap_or(0) as usize];
                presence_bits(p, &lines[i + 1..], ent, defs, *id, &mut set);
                presence_bits(p, tail, ent, defs, *id, &mut set);
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
                let present = content(body, ent, defs);
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
                        let more = parts[k..].iter().any(|later| content(later, ent, defs));
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
                encode_lines(body, &[], ent, defs, w)?;
                // a block counted in bytes is padded with zero bits to a whole byte
                if !*in_bits {
                    w.zeros((8 - (w.pos - start) % 8) % 8);
                }
                let size = (w.pos - start) / if *in_bits { 1 } else { 8 };
                let stated = size as i128 + *plus as i128;
                if stated < 0 || (*len < 64 && stated >> *len != 0) {
                    return Err(w.fail(format!("a length of {} does not fit its {} bits", stated, len)));
                }
                set_bits(&mut w.buf, at, *len, stated as u64, p.msb);
            }
            SeqLine::Whole { len, plus } => {
                w.wholes.push((w.pos, *len, *plus));
                w.zeros(*len as u64);
            }
            SeqLine::Group(g) => {
                let none: Vec<Entity> = Vec::new();
                let items = ent.lists.get(&g.list).unwrap_or(&none);
                let n = items.len();
                match &g.rep {
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
        }
    }
    Ok(())
}

pub fn encode(p: &Pack, body: &SeqBody, ent: &Entity) -> Result<Vec<u8>, Error> {
    encode_bits(p, body, ent).map(|(b, _)| b)
}

/// The message as whole bytes, and the cursor after the last line.
pub fn encode_bits(p: &Pack, body: &SeqBody, ent: &Entity) -> Result<(Vec<u8>, u64), Error> {
    let mut w = Writer { p, buf: Vec::new(), pos: 0, presence: BTreeMap::new(), wholes: Vec::new() };
    encode_body(body, ent, false, &mut w)?;
    // a message is a whole number of bytes; the last bits are zero
    let bytes = w.buf.len() as i128;
    for (at, len, plus) in std::mem::take(&mut w.wholes) {
        let stated = bytes + plus as i128;
        if stated < 0 || (len < 64 && stated >> len != 0) {
            return Err(w.fail(format!("a message length of {} does not fit its {} bits", stated, len)));
        }
        set_bits(&mut w.buf, at, len, stated as u64, p.msb);
    }
    Ok((w.buf, w.pos))
}
