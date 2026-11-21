//! The `text` wire (engine-spec v0.10): one record of ASCII text, fields
//! separated by a delimiter, optionally framed by a start text and an NMEA
//! checksum. A field may also be read as character columns, which covers
//! fixed-width records.
//!
//! Locators: `<i>` (field `i`), `<i>:<from>:<len>` (a column of field `i`)
//! and `<i>+<j>` (a pair, for `dm` and `hms_dmy`). Inside a group they count
//! from the item's first field.

use super::*;

// ---------------------------------------------------------------------------
// Locators
// ---------------------------------------------------------------------------

/// A locator of the text wire.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) enum Loc {
    /// field `i`, its whole text
    Field(usize),
    /// `len` characters of field `i` from character `from`
    Col(usize, usize, usize),
    /// fields `i` and `j` as one value, in that order
    Pair(usize, usize),
}

impl Loc {
    pub(crate) fn parse(s: &str) -> Result<Loc, String> {
        let num = |t: &str| -> Result<usize, String> {
            if t.is_empty() || !t.bytes().all(|b| b.is_ascii_digit()) {
                return Err(format!("`{}` is not a text locator (`<i>`, `<i>:<from>:<len>` or `<i>+<j>`)", s));
            }
            t.parse::<usize>().map_err(|_| format!("`{}`: a number is too large", s))
        };
        if let Some((a, b)) = s.split_once('+') {
            let (i, j) = (num(a)?, num(b)?);
            if i == j {
                return Err(format!("`{}`: the two fields of a pair differ", s));
            }
            return Ok(Loc::Pair(i, j));
        }
        let parts: Vec<&str> = s.split(':').collect();
        match parts.as_slice() {
            [i] => Ok(Loc::Field(num(i)?)),
            [i, from, len] => {
                let (i, from, len) = (num(i)?, num(from)?, num(len)?);
                if len == 0 {
                    return Err(format!("`{}`: a column is at least one character long", s));
                }
                if from.checked_add(len).is_none() {
                    return Err(format!("`{}`: the column is too long", s));
                }
                Ok(Loc::Col(i, from, len))
            }
            _ => Err(format!("`{}` is not a text locator (`<i>`, `<i>:<from>:<len>` or `<i>+<j>`)", s)),
        }
    }

    /// The fields this locator addresses.
    fn fields(&self) -> (usize, Option<usize>) {
        match *self {
            Loc::Field(i) | Loc::Col(i, _, _) => (i, None),
            Loc::Pair(i, j) => (i, Some(j)),
        }
    }

    #[cfg(feature = "text")]
    fn addresses(&self, i: usize) -> bool {
        let (a, b) = self.fields();
        a == i || b == Some(i)
    }

    fn highest(&self) -> usize {
        let (a, b) = self.fields();
        a.max(b.unwrap_or(0))
    }

    /// The locator moved to an item that starts at field `base`.
    fn shift(self, base: usize) -> Loc {
        match self {
            Loc::Field(i) => Loc::Field(base.saturating_add(i)),
            Loc::Col(i, from, len) => Loc::Col(base.saturating_add(i), from, len),
            Loc::Pair(i, j) => Loc::Pair(base.saturating_add(i), base.saturating_add(j)),
        }
    }
}

/// The locator of a line already checked at load.
fn loc(s: &str) -> Option<Loc> {
    Loc::parse(s).ok()
}

/// The locator of a line as the layout the engine keeps for the pack holds
/// it (engine-spec 0.25), else read now.
#[cfg(feature = "text")]
fn kept(lay: &Layout, s: &str) -> Option<Loc> {
    match lay.text_locs.get(&layout::line_key(s)) {
        Some(l) => *l,
        None => loc(s),
    }
}

/// The field a group's items start at, and the fields of one item.
fn group_span(g: &GroupDef) -> (usize, usize) {
    (g.locator.parse::<usize>().unwrap_or(usize::MAX), g.item_bits.unwrap_or(1).max(1) as usize)
}

// ---------------------------------------------------------------------------
// Transforms on this wire
// ---------------------------------------------------------------------------

/// `10^f` as the exact double, for `f` from 0 to 9.
#[cfg(feature = "text")]
const POW10: [f64; 10] = [1.0, 10.0, 100.0, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9];
/// 2^53: a rounded value this large or larger is refused on encode.
#[cfg(feature = "text")]
const TWO_53: f64 = 9_007_199_254_740_992.0;

/// The transforms that are read with a column's leading spaces removed and
/// padded with `0` on the left: `int`, `int:<w>`, `float`, `dec`.
#[cfg(feature = "text")]
pub(crate) fn numeric(t: &Transform) -> bool {
    matches!(t, Transform::Int | Transform::IntW(_) | Transform::Float | Transform::Dec(_, _))
}

/// The transforms that take two parts (a pair locator).
pub(crate) fn two_parts(t: &Transform) -> bool {
    matches!(t, Transform::Dm(..) | Transform::HmsDmy(_))
}

/// The transforms the text wire accepts.
pub(crate) fn valid_on_text(t: &Transform) -> bool {
    matches!(t, Transform::StringT | Transform::Int | Transform::Float | Transform::Iso8601Ms | Transform::Iso8601S)
        || t.is_text_only()
}

#[cfg(feature = "text")]
fn digits(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())
}

#[cfg(feature = "text")]
fn fail<T>(what: &str, s: &str) -> Result<T, Error> {
    err(format!("`{}` is not {}", s, what))
}

/// An optional `+` or `-` and one or more digits, within 64 bits.
#[cfg(feature = "text")]
fn read_int(s: &str) -> Result<i64, Error> {
    let body = s.strip_prefix(['+', '-']).unwrap_or(s);
    if !digits(body) {
        return fail("an integer", s);
    }
    s.parse::<i64>().or_else(|_| err(format!("`{}` is outside the 64-bit range", s)))
}

/// An optional sign, then digits with at most one `.`, at least one digit;
/// no exponent. The double nearest the decimal, which must be finite.
#[cfg(feature = "text")]
fn read_float(s: &str) -> Result<f64, Error> {
    let body = s.strip_prefix(['+', '-']).unwrap_or(s);
    let dots = body.bytes().filter(|b| *b == b'.').count();
    let ok = dots <= 1
        && body.bytes().any(|b| b.is_ascii_digit())
        && body.bytes().all(|b| b.is_ascii_digit() || b == b'.');
    if !ok {
        return fail("a decimal number", s);
    }
    match s.parse::<f64>() {
        Ok(x) if x.is_finite() => Ok(x),
        _ => err(format!("`{}` is not a finite number", s)),
    }
}

/// `hhmmss` then optionally `.` and digits: (h, m, s, the seconds text, the fraction digits).
#[cfg(feature = "text")]
fn read_hms(s: &str) -> Result<(i64, i64, i64, &str, &str), Error> {
    let b = s.as_bytes();
    if b.len() < 6 || !b[..6].iter().all(|c| c.is_ascii_digit()) {
        return fail("a time `hhmmss[.s]`", s);
    }
    let frac = match &s[6..] {
        "" => "",
        rest => match rest.strip_prefix('.') {
            Some(f) if digits(f) => f,
            _ => return fail("a time `hhmmss[.s]`", s),
        },
    };
    let n = |a: usize| (b[a] - b'0') as i64 * 10 + (b[a + 1] - b'0') as i64;
    let (h, m, sec) = (n(0), n(2), n(4));
    if h >= 24 || m >= 60 || sec >= 60 {
        return err(format!("`{}` is not a time of day", s));
    }
    Ok((h, m, sec, &s[4..], frac))
}

#[cfg(feature = "text")]
fn days_in_month(y: i64, m: i64) -> i64 {
    match m {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ if (y % 4 == 0 && y % 100 != 0) || y % 400 == 0 => 29,
        _ => 28,
    }
}

/// wire text -> model value, for a transform of one part
#[cfg(feature = "text")]
pub(crate) fn decode_one(t: &Transform, s: &str) -> Result<Value, Error> {
    match t {
        Transform::StringT => Ok(Value::Str(s.to_string())),
        Transform::Int | Transform::IntW(_) => read_int(s).map(Value::I64),
        Transform::Float | Transform::Dec(_, _) => read_float(s).map(Value::F64),
        Transform::Iso8601Ms | Transform::Iso8601S => iso8601_to_ms(s).map(Value::I64),
        Transform::Hms(_) => {
            let (h, m, _, secs, _) = read_hms(s)?;
            let secs = secs.parse::<f64>().or_else(|_| fail("a time `hhmmss[.s]`", s))?;
            Ok(Value::F64((h * 3600 + m * 60) as f64 + secs))
        }
        _ => err(format!("transform {:?} is not valid on the text wire", t)),
    }
}

/// wire text of the two fields of a pair -> model value
#[cfg(feature = "text")]
pub(crate) fn decode_two(t: &Transform, a: &str, b: &str) -> Result<Value, Error> {
    match *t {
        Transform::Dm(d, _, pos, neg) => {
            let d = d as usize;
            let shape = || Error { msg: format!("`{}` is not {} digits of degrees, two of minutes and an optional fraction", a, d) };
            let ab = a.as_bytes();
            if ab.len() < d + 2 || !ab[..d + 2].iter().all(|c| c.is_ascii_digit()) {
                return Err(shape());
            }
            match &a[d + 2..] {
                "" => {}
                rest => match rest.strip_prefix('.') {
                    Some(f) if digits(f) => {}
                    _ => return Err(shape()),
                },
            }
            let degrees = a[..d].parse::<f64>().map_err(|_| shape())?;
            let minutes = a[d..].parse::<f64>().map_err(|_| shape())?;
            // the two digits of minutes compared as an integer, before any fraction (ruling 15)
            if (ab[d] - b'0') * 10 + (ab[d + 1] - b'0') >= 60 {
                return err(format!("`{}`: minutes of 60 or more", a));
            }
            let x = degrees + minutes / 60.0;
            match b.as_bytes() {
                [c] if *c == pos => Ok(Value::F64(x)),
                [c] if *c == neg => Ok(Value::F64(-x)),
                _ => err(format!("`{}` is not `{}` or `{}`", b, pos as char, neg as char)),
            }
        }
        Transform::HmsDmy(_) => {
            let (h, m, sec, _, frac) = read_hms(a)?;
            let db = b.as_bytes();
            if db.len() != 6 || !db.iter().all(|c| c.is_ascii_digit()) {
                return fail("a date `ddmmyy`", b);
            }
            let n = |i: usize| (db[i] - b'0') as i64 * 10 + (db[i + 1] - b'0') as i64;
            let (day, mon, yy) = (n(0), n(2), n(4));
            let year = if yy >= 80 { 1900 + yy } else { 2000 + yy };
            if !(1..=12).contains(&mon) || day < 1 || day > days_in_month(year, mon) {
                return err(format!("`{}` is not a date", b));
            }
            // fraction digits beyond milliseconds are truncated
            let mut ms = 0i64;
            for k in 0..3 {
                ms = ms * 10 + frac.as_bytes().get(k).map_or(0, |c| (c - b'0') as i64);
            }
            Ok(Value::I64(days_from_civil(year, mon, day) * 86_400_000 + (h * 3600 + m * 60 + sec) * 1000 + ms))
        }
        _ => err(format!("transform {:?} does not take two parts", t)),
    }
}

/// `round(x * 10^f)`, refused when it is not finite or its magnitude is 2^53 or more.
#[cfg(feature = "text")]
fn scaled(x: f64, f: u32) -> Result<f64, Error> {
    let n = (x * POW10[f as usize]).round();
    if !n.is_finite() || n.abs() >= TWO_53 {
        return err(format!("{} times 10^{} is too large", x, f));
    }
    Ok(n)
}

/// `n` as digits with a `.` before the last `f`, zero-padded to at least `f + 1` digits.
#[cfg(feature = "text")]
fn fixed_point(n: u64, f: u32) -> String {
    let s = format!("{:0width$}", n, width = f as usize + 1);
    if f == 0 {
        s
    } else {
        let at = s.len() - f as usize;
        format!("{}.{}", &s[..at], &s[at..])
    }
}

/// Zeros after any `-` until the text without its sign is at least `w` characters.
#[cfg(feature = "text")]
fn zero_pad(s: String, w: usize) -> String {
    let (sign, body) = match s.strip_prefix('-') {
        Some(b) => ("-", b),
        None => ("", s.as_str()),
    };
    if body.len() >= w {
        return s;
    }
    format!("{}{}{}", sign, "0".repeat(w - body.len()), body)
}

/// `hh`, `mm`, `ss` of `secs`, then `.` and the `f` digits of `frac` (none when `f` is 0).
#[cfg(feature = "text")]
fn hms_text(secs: u64, frac: u64, f: u32) -> String {
    let base = format!("{:02}{:02}{:02}", secs / 3600, secs / 60 % 60, secs % 60);
    if f == 0 {
        base
    } else {
        format!("{}.{:0width$}", base, frac, width = f as usize)
    }
}

/// model value -> wire text, for a transform of one part
#[cfg(feature = "text")]
pub(crate) fn encode_one(t: &Transform, v: &Value) -> Result<String, Error> {
    match (t, v) {
        (Transform::StringT, Value::Str(s)) => Ok(s.clone()),
        (Transform::Int, Value::I64(n)) => Ok(n.to_string()),
        (Transform::IntW(w), Value::I64(n)) => Ok(zero_pad(n.to_string(), *w as usize)),
        (Transform::Float, Value::F64(x)) => finite(*x).map(|_| fmt_f64(*x)),
        (Transform::Dec(f, w), Value::F64(x)) => {
            let n = scaled(*x, *f)?;
            let s = fixed_point(n.abs() as u64, *f);
            let s = if n < 0.0 { format!("-{}", s) } else { s };
            Ok(zero_pad(s, *w as usize))
        }
        (Transform::Iso8601Ms, Value::I64(ms)) => ms_to_iso8601_checked(*ms),
        (Transform::Iso8601S, Value::I64(ms)) => ms_to_iso8601_s(*ms),
        (Transform::Hms(f), Value::F64(x)) => {
            let n = scaled(*x, *f)?;
            let p = POW10[*f as usize];
            if !(n >= 0.0 && n < 86400.0 * p) {
                return err(format!("{} is not a time of day", x));
            }
            let (n, p) = (n as u64, p as u64);
            Ok(hms_text(n / p, n % p, *f))
        }
        _ => err(format!("transform/value mismatch on text: {:?} with {:?}", t, v)),
    }
}

/// model value -> wire text of the two fields of a pair
#[cfg(feature = "text")]
pub(crate) fn encode_two(t: &Transform, v: &Value) -> Result<(String, String), Error> {
    match (*t, v) {
        (Transform::Dm(d, f, pos, neg), Value::F64(x)) => {
            finite(*x)?;
            let m = (x.abs() * 60.0 * POW10[f as usize]).round();
            if !m.is_finite() || m >= TWO_53 {
                return err(format!("{} is too large", x));
            }
            let m = m as u64;
            let p = POW10[f as usize] as u64;
            let (degrees, rest) = (m / (60 * p), m % (60 * p));
            if degrees >= 10u64.pow(d) {
                return err(format!("{} has more than {} digits of degrees", x, d));
            }
            let mut text = format!("{:0dw$}{:02}", degrees, rest / p, dw = d as usize);
            if f > 0 {
                text.push_str(&format!(".{:0fw$}", rest % p, fw = f as usize));
            }
            let letter = if *x < 0.0 && m > 0 { neg } else { pos };
            Ok((text, (letter as char).to_string()))
        }
        (Transform::HmsDmy(f), Value::I64(ms)) => {
            let days = ms.div_euclid(86_400_000);
            let tod = ms.rem_euclid(86_400_000) as u64;
            let (y, mon, day) = civil_from_days(days);
            if !(1980..=2079).contains(&y) {
                return err(format!("the year {} is outside 1980 to 2079", y));
            }
            let frac = (tod % 1000) / 10u64.pow(3 - f);
            Ok((hms_text(tod / 1000, frac, f), format!("{:02}{:02}{:02}", day, mon, y % 100)))
        }
        _ => err(format!("transform/value mismatch on text: {:?} with {:?}", t, v)),
    }
}

// ---------------------------------------------------------------------------
// Load checks
// ---------------------------------------------------------------------------

/// The text directives of a pack, as the encoder and decoder use them.
#[derive(Clone, Debug, PartialEq)]
pub struct TextConf {
    /// None: `delimiter none`, the record is one field
    pub delimiter: Option<u8>,
    pub start: String,
    /// `checksum nmea`
    pub nmea: bool,
}

impl Default for TextConf {
    fn default() -> TextConf {
        TextConf { delimiter: Some(b','), start: String::new(), nmea: false }
    }
}

/// A `field` line's locator: its syntax, and a pair exactly for the
/// transforms that take two parts.
pub(crate) fn check_field_locator(f: &FieldDef) -> Result<(), Error> {
    let l = Loc::parse(&f.locator).or_else(|m| bad(f.line, m))?;
    match (matches!(l, Loc::Pair(..)), two_parts(&f.transform)) {
        (true, false) => bad(f.line, format!("the pair `{}` needs a transform that takes two parts", f.locator)),
        (false, true) => bad(f.line, format!("the transform of `{}` takes a pair `<i>+<j>`", f.model_key)),
        _ => Ok(()),
    }
}

/// A `when` or `const` locator: a field or a column, not a pair.
pub(crate) fn check_when_locator(w: &WhenDef) -> Result<Loc, Error> {
    match Loc::parse(&w.locator).or_else(|m| bad(w.line, m))? {
        Loc::Pair(..) => bad(w.line, format!("`when` and `const` take a field or a column, not the pair `{}`", w.locator)),
        l => Ok(l),
    }
}

/// A group's locator: a field index.
pub(crate) fn check_group_locator(g: &GroupDef) -> Result<(), Error> {
    match Loc::parse(&g.locator) {
        Ok(Loc::Field(_)) => Ok(()),
        _ => bad(g.line, format!("`{}` is not a field index, where a text group's items start", g.locator)),
    }
}

/// The checks of ruling 2 of 0.10 that run once the file is read: the
/// directives against one another, the locators against `delimiter none`,
/// the `when` and `const` values, and the group and scope checks.
pub(crate) fn check_pack(
    conf: &TextConf,
    fields: &[FieldDef],
    whens: &[WhenDef],
    consts: &[WhenDef],
    groups: &[GroupDef],
    kinds: &[KindDef],
) -> Result<(), Error> {
    // field 0 only under `delimiter none`
    let one_field = |line: usize, l: Loc| -> Result<(), Error> {
        if conf.delimiter.is_none() && l.highest() != 0 {
            return bad(line, "under `delimiter none` the record is field 0 only");
        }
        Ok(())
    };
    let value_ok = |w: &WhenDef, l: Loc| -> Result<(), Error> {
        if w.present {
            return Ok(());
        }
        let t = w.text.as_bytes();
        let why = if t.is_empty() {
            Some("is empty")
        } else if conf.delimiter.map_or(false, |d| t.contains(&d)) {
            Some("holds the delimiter")
        } else if conf.nmea && t.contains(&b'*') {
            Some("holds `*` under `checksum nmea`")
        } else if !t.iter().all(|c| (0x20..=0x7e).contains(c)) {
            Some("holds a character outside 0x20 to 0x7E")
        } else if t[0] == b' ' || t[t.len() - 1] == b' ' {
            Some("starts or ends with a space")
        } else if matches!(l, Loc::Col(_, _, len) if t.len() > len) {
            Some("is longer than its column")
        } else {
            None
        };
        match why {
            Some(why) => bad(w.line, format!("the value `{}` {}", w.value, why)),
            None => Ok(()),
        }
    };
    let top_fields = fields.iter().chain(kinds.iter().flat_map(|k| k.fields.iter()));
    for f in top_fields {
        check_field_locator(f)?;
        one_field(f.line, loc(&f.locator).expect("checked"))?;
    }
    let top_fixed = whens.iter().chain(consts).chain(kinds.iter().flat_map(|k| k.whens.iter().chain(k.consts.iter())));
    for w in top_fixed {
        let l = check_when_locator(w)?;
        one_field(w.line, l)?;
        value_ok(w, l)?;
    }
    // every group, nested ones included
    let mut every: Vec<&GroupDef> = Vec::new();
    for g in groups.iter().chain(kinds.iter().flat_map(|k| k.groups.iter())) {
        g.walk(&mut every);
    }
    for g in &every {
        check_group_locator(g)?;
        if conf.delimiter.is_none() {
            return bad(g.line, "a group in a pack with `delimiter none` (ruling 12 of 0.10)");
        }
        if g.count.is_some() {
            return bad(g.line, "`count` is not valid on the text wire: the items run to the end of the record");
        }
        let n = match g.item_bits {
            Some(n) => n,
            None => return bad(g.line, "a group on the text wire needs `item <n>`"),
        };
        if let Some(inner) = g.groups.first() {
            return bad(inner.line, "a group on the text wire holds no group");
        }
        let (start, _) = group_span(g);
        let in_item = |line: usize, l: Loc| -> Result<(), Error> {
            if l.highest() as u64 >= n {
                return bad(line, format!("an item of `{}` is {} fields long", g.list, n));
            }
            one_field(line, l.shift(start))
        };
        for f in &g.fields {
            check_field_locator(f)?;
            if f.optional {
                return bad(f.line, "`optional` is not valid inside a group");
            }
            in_item(f.line, loc(&f.locator).expect("checked"))?;
        }
        for c in &g.consts {
            let l = check_when_locator(c)?;
            in_item(c.line, l)?;
            value_ok(c, l)?;
        }
    }
    // each scope: at most one group, and it is the last thing in the scope
    let scope = |fs: Vec<&FieldDef>, ws: Vec<&WhenDef>, gs: Vec<&GroupDef>| -> Result<(), Error> {
        if let Some(second) = gs.get(1) {
            return bad(second.line, "a second group in one scope: a text group runs to the end of the record");
        }
        if let Some(g) = gs.first() {
            let (start, _) = group_span(g);
            let lines = fs.iter().map(|f| (f.line, &f.locator)).chain(ws.iter().map(|w| (w.line, &w.locator)));
            for (line, l) in lines {
                if loc(l).map_or(false, |l| l.highest() >= start) {
                    return bad(line, format!("`{}` lies at or beyond the start of group `{}`", l, g.list));
                }
            }
        }
        Ok(())
    };
    let common_ws = || whens.iter().chain(consts.iter());
    if kinds.is_empty() {
        scope(fields.iter().collect(), common_ws().collect(), groups.iter().collect())?;
    }
    for k in kinds {
        scope(
            fields.iter().chain(k.fields.iter()).collect(),
            common_ws().chain(k.whens.iter()).chain(k.consts.iter()).collect(),
            groups.iter().chain(k.groups.iter()).collect(),
        )?;
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Decode
// ---------------------------------------------------------------------------

#[cfg(feature = "text")]
fn malformed(p: &Pack, why: impl AsRef<str>) -> Error {
    Error { msg: format!("malformed-wire: format `{}`: {}", p.format, why.as_ref()) }
}

/// Steps 1 to 5 of "Reading a record": the fields of the body.
#[cfg(feature = "text")]
fn record<'a>(p: &Pack, input: &'a str) -> Result<Vec<&'a str>, Error> {
    let conf = &p.text;
    let mut t = input;
    if let Some(s) = t.strip_suffix("\r\n") {
        t = s;
    } else if let Some(s) = t.strip_suffix('\n') {
        t = s;
    }
    if t.bytes().any(|b| !(0x20..=0x7e).contains(&b)) {
        return Err(malformed(p, "the record holds a character outside 0x20 to 0x7E"));
    }
    if !conf.start.is_empty() {
        t = t.strip_prefix(conf.start.as_str()).ok_or_else(|| malformed(p, format!("the record does not begin with `{}`", conf.start)))?;
    }
    if conf.nmea {
        let b = t.as_bytes();
        let n = b.len();
        if n < 3 || b[n - 3] != b'*' || !b[n - 2].is_ascii_hexdigit() || !b[n - 1].is_ascii_hexdigit() {
            return Err(malformed(p, "the record does not end with `*` and two hexadecimal digits"));
        }
        let sum = b[..n - 3].iter().fold(0u8, |a, c| a ^ c);
        let stated = u8::from_str_radix(&t[n - 2..], 16).map_err(|_| malformed(p, "bad checksum digits"))?;
        if sum != stated {
            return Err(malformed(p, format!("the checksum is {:02X}, the record states {}", sum, &t[n - 2..])));
        }
        t = &t[..n - 3];
        if t.contains('*') {
            return Err(malformed(p, "a `*` before the checksum"));
        }
    }
    Ok(match conf.delimiter {
        None => vec![t],
        Some(d) => t.split(d as char).collect(),
    })
}

/// Field `i` when the record has it and it is not empty.
#[cfg(feature = "text")]
fn whole<'a>(rec: &[&'a str], i: usize) -> Option<&'a str> {
    rec.get(i).copied().filter(|s| !s.is_empty())
}

/// A column: the characters field `i` has from `from` on, at most `len`,
/// trailing spaces removed (and leading ones for the numeric transforms).
#[cfg(feature = "text")]
fn column<'a>(rec: &[&'a str], i: usize, from: usize, len: usize, numeric: bool) -> Option<&'a str> {
    let f = rec.get(i)?;
    if from >= f.len() {
        return None;
    }
    let end = from.saturating_add(len).min(f.len());
    let mut s = f[from..end].trim_end_matches(' ');
    if numeric {
        s = s.trim_start_matches(' ');
    }
    Some(s).filter(|s| !s.is_empty())
}

#[cfg(feature = "text")]
fn when_holds(lay: &Layout, rec: &[&str], w: &WhenDef) -> bool {
    let text = match kept(lay, &w.locator) {
        Some(Loc::Field(i)) => whole(rec, i),
        Some(Loc::Col(i, from, len)) => column(rec, i, from, len, false),
        _ => None,
    };
    match text {
        None => false,
        Some(_) if w.present => true,
        Some(t) => t == w.text,
    }
}

/// Decode the field lines of one scope, their locators counted from `base`.
#[cfg(feature = "text")]
fn decode_fields(p: &Pack, lay: &Layout, fields: &[&FieldDef], rec: &[&str], base: usize, d: &mut Decoded) {
    for f in fields {
        let l = match kept(lay, &f.locator) {
            Some(l) => l.shift(base),
            None => continue,
        };
        match l {
            Loc::Field(i) => {
                if let Some(s) = whole(rec, i) {
                    d.put(p, f, decode_one(&f.transform, s));
                }
            }
            Loc::Col(i, from, len) => {
                if let Some(s) = column(rec, i, from, len, numeric(&f.transform)) {
                    d.put(p, f, decode_one(&f.transform, s));
                }
            }
            // a pair is absent when either of its fields is absent
            Loc::Pair(i, j) => {
                if let (Some(a), Some(b)) = (whole(rec, i), whole(rec, j)) {
                    d.put(p, f, decode_two(&f.transform, a, b));
                }
            }
        }
    }
}

#[cfg(feature = "text")]
pub fn decode(p: &Pack, input: &str) -> Result<Entity, Error> {
    decode_in(p, &Layout::default(), input)
}

/// `decode` with the layout the engine keeps for the pack (engine-spec 0.25).
#[cfg(feature = "text")]
pub(crate) fn decode_in(p: &Pack, lay: &Layout, input: &str) -> Result<Entity, Error> {
    let _scope = limit::scope();
    let rec = record(p, input)?;
    let sel = p.select_decode(None, |w| when_holds(lay, &rec, w))?;
    let mut d = Decoded::new();
    decode_fields(p, lay, &sel.fields, &rec, 0, &mut d);
    let mut group_start = usize::MAX;
    if let Some(g) = sel.groups.first() {
        let (start, n) = group_span(g);
        group_start = start;
        // present when the record has a field at index `start` or beyond
        if rec.len() > start {
            let body = g.body();
            let count = (rec.len() - start + n - 1) / n;
            // the number of items against the limit, before any field is read (7d)
            d.replacing(&g.list);
            limit::take(&p.format, &g.list, count as u64)?;
            let mut items = Vec::with_capacity(count);
            for j in 0..count {
                let mut di = Decoded::new();
                decode_fields(p, lay, &body.fields, &rec, start + j * n, &mut di);
                items.push(di);
            }
            d.put_list(&g.list, items);
        }
    }
    // residue: every field that is not empty and that no line addresses
    let mut addressed = vec![false; rec.len()];
    let mut mark = |l: Option<Loc>| {
        if let Some(l) = l {
            let (a, b) = l.fields();
            for i in std::iter::once(a).chain(b) {
                if let Some(x) = addressed.get_mut(i) {
                    *x = true;
                }
            }
        }
    };
    for f in &sel.fields {
        mark(kept(lay, &f.locator));
    }
    for w in sel.fixed() {
        mark(kept(lay, &w.locator));
    }
    for (i, s) in rec.iter().enumerate() {
        if i >= group_start {
            break;
        }
        if !s.is_empty() && !addressed[i] {
            d.ent.residue.push((p.format.clone(), i.to_string(), s.to_string()));
        }
    }
    d.finish(p, &sel)
}

// ---------------------------------------------------------------------------
// Encode
// ---------------------------------------------------------------------------

/// One field of the record being written.
#[derive(Clone, Default)]
#[cfg(feature = "text")]
struct Buf {
    text: Vec<u8>,
    /// a whole-field line (or a part of a pair) wrote the text
    whole: bool,
    /// the characters a column of a `field` line wrote
    by_col: Vec<bool>,
    /// a `when` or `const` wrote the whole field
    fixed_whole: bool,
    /// the characters a `when` or `const` column wrote
    by_fixed: Vec<bool>,
}

#[cfg(feature = "text")]
impl Buf {
    /// Spaces up to `end`, so a column can be written there.
    #[cfg(feature = "text")]
    fn reach(&mut self, end: usize) {
        if self.text.len() < end {
            self.text.resize(end, b' ');
        }
        let n = self.text.len();
        self.by_col.resize(n, false);
        self.by_fixed.resize(n, false);
    }
    #[cfg(feature = "text")]
    fn put_whole(&mut self, s: &str) {
        // the earlier whole-field line stands; a whole-field line stands over columns (ruling 3)
        if !self.whole {
            self.text = s.as_bytes().to_vec();
            self.whole = true;
        }
    }
    #[cfg(feature = "text")]
    fn put_col(&mut self, from: usize, s: &[u8]) {
        if self.whole {
            return;
        }
        self.reach(from + s.len());
        for (k, c) in s.iter().enumerate() {
            if !self.by_col[from + k] {
                self.text[from + k] = *c;
                self.by_col[from + k] = true;
            }
        }
    }
    #[cfg(feature = "text")]
    fn fix_whole(&mut self, s: &str) {
        if !self.fixed_whole && !self.by_fixed.iter().any(|b| *b) {
            self.text = s.as_bytes().to_vec();
            self.fixed_whole = true;
        }
    }
    #[cfg(feature = "text")]
    fn fix_col(&mut self, from: usize, s: &[u8]) {
        if self.fixed_whole {
            return;
        }
        self.reach(from + s.len());
        for (k, c) in s.iter().enumerate() {
            if !self.by_fixed[from + k] {
                self.text[from + k] = *c;
                self.by_fixed[from + k] = true;
            }
        }
    }
}

#[cfg(feature = "text")]
struct Record {
    fields: Vec<Buf>,
}

#[cfg(feature = "text")]
impl Record {
    #[cfg(feature = "text")]
    fn at(&mut self, i: usize) -> &mut Buf {
        if self.fields.len() <= i {
            self.fields.resize(i + 1, Buf::default());
        }
        &mut self.fields[i]
    }
}

/// Text a transform wrote: no delimiter, no `*` under `checksum nmea`, only
/// characters from 0x20 to 0x7E.
#[cfg(feature = "text")]
fn check_text(p: &Pack, s: &str) -> Result<(), Error> {
    for c in s.bytes() {
        if !(0x20..=0x7e).contains(&c) {
            return err(format!("`{}` holds a character outside 0x20 to 0x7E", s.escape_default()));
        }
        if Some(c) == p.text.delimiter {
            return err(format!("`{}` holds the delimiter", s));
        }
        if c == b'*' && p.text.nmea {
            return err(format!("`{}` holds `*` under `checksum nmea`", s));
        }
    }
    Ok(())
}

/// Text padded to a column of `len`: `0` on the left (after any `-`) for
/// the numeric transforms, spaces on the right for the others.
#[cfg(feature = "text")]
fn pad(s: &str, len: usize, numeric: bool) -> Result<Vec<u8>, String> {
    if s.len() > len {
        return Err(format!("`{}` is longer than its column of {}", s, len));
    }
    let fill = len - s.len();
    Ok(match (numeric, s.strip_prefix('-')) {
        (true, Some(body)) => format!("-{}{}", "0".repeat(fill), body),
        (true, None) => format!("{}{}", "0".repeat(fill), s),
        (false, _) => format!("{}{}", s, " ".repeat(fill)),
    }
    .into_bytes())
}

/// Write one scope (the message, or one item from field `base`): its
/// `field` lines in line order, then its `when` and `const` lines. Returns
/// one more than the highest field a line wrote (0: none).
#[cfg(feature = "text")]
fn write_scope(
    p: &Pack,
    lay: &Layout,
    sel: &Sel,
    fixed: &[&WhenDef],
    ent: &Entity,
    base: usize,
    rec: &mut Record,
) -> Result<usize, Error> {
    let mut reach = 0usize;
    for f in &sel.fields {
        let v = match sel.value_of(ent, f) {
            Some(v) => v,
            None => continue,
        };
        let l = match kept(lay, &f.locator) {
            Some(l) => l.shift(base),
            None => continue,
        };
        let e = |e: Error| transform_encode_err(p, f, e);
        let v = p.to_wire(f, v).map_err(e)?;
        reach = reach.max(l.highest() + 1);
        match l {
            Loc::Pair(i, j) => {
                let (a, b) = encode_two(&f.transform, &v).map_err(e)?;
                check_text(p, &a).map_err(e)?;
                check_text(p, &b).map_err(e)?;
                rec.at(i).put_whole(&a);
                rec.at(j).put_whole(&b);
            }
            Loc::Field(i) => {
                let s = encode_one(&f.transform, &v).map_err(e)?;
                check_text(p, &s).map_err(e)?;
                rec.at(i).put_whole(&s);
            }
            Loc::Col(i, from, len) => {
                let s = encode_one(&f.transform, &v).map_err(e)?;
                check_text(p, &s).map_err(e)?;
                let padded = pad(&s, len, numeric(&f.transform)).map_err(|m| e(Error { msg: m }))?;
                rec.at(i).put_col(from, &padded);
            }
        }
    }
    let mut fixed: Vec<&WhenDef> = fixed.to_vec();
    fixed.sort_by_key(|w| w.line);
    for w in fixed {
        let l = kept(lay, &w.locator).map(|l| l.shift(base));
        if let Some(l) = l {
            reach = reach.max(l.highest() + 1);
        }
        match l {
            Some(Loc::Field(i)) => rec.at(i).fix_whole(&w.text),
            Some(Loc::Col(i, from, len)) => {
                // a value is at most `len` characters (checked at load)
                if let Ok(padded) = pad(&w.text, len, false) {
                    rec.at(i).fix_col(from, &padded);
                }
            }
            _ => {}
        }
    }
    Ok(reach)
}

#[cfg(feature = "text")]
pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
    encode_in(p, &Layout::default(), ent)
}

/// `encode` with the layout the engine keeps for the pack (engine-spec 0.25).
#[cfg(feature = "text")]
pub(crate) fn encode_in(p: &Pack, lay: &Layout, ent: &Entity) -> Result<String, Error> {
    let sel = p.select_encode(ent)?;
    let mut rec = Record { fields: Vec::new() };
    let fixed: Vec<&WhenDef> = sel.fixed().collect();
    write_scope(p, lay, &sel, &fixed, ent, 0, &mut rec)?;
    // step 4: one more than the highest field a line (not a group) addresses
    let lines: Vec<(Loc, bool)> = sel
        .fields
        .iter()
        .filter_map(|f| kept(lay, &f.locator).map(|l| (l, f.optional)))
        .chain(fixed.iter().filter_map(|w| kept(lay, &w.locator).map(|l| (l, false))))
        .collect();
    let mut count = lines.iter().map(|(l, _)| l.highest() + 1).max().unwrap_or(0);
    // the group's items, back to back from its field
    let mut group: Option<(usize, usize)> = None;
    if let Some(g) = sel.groups.first() {
        let (start, n) = group_span(g);
        group = Some((start, usize::MAX));
        if let Some(items) = ent.lists.get(&g.list).filter(|items| !items.is_empty()) {
            let body = g.body();
            let consts: Vec<&WhenDef> = body.consts.clone();
            // each item is `n` fields long, whether or not its keys are present
            for (j, item) in items.iter().enumerate() {
                write_scope(p, lay, &body, &consts, item, start + j * n, &mut rec)?;
            }
            let end = start + items.len() * n;
            group = Some((start, end));
            count = count.max(end);
        }
    }
    // step 3: residue of this format at a field no line addresses
    let addressed = |i: usize| lines.iter().any(|(l, _)| l.addresses(i)) || group.map_or(false, |(s, _)| i >= s);
    for (fmt, key, text) in &ent.residue {
        if fmt != &p.format || !digits(key) {
            continue;
        }
        let i = match key.parse::<usize>() {
            Ok(i) if i.to_string() == *key && !addressed(i) => i,
            _ => continue,
        };
        if p.text.delimiter.is_none() && i != 0 {
            continue;
        }
        let b = rec.at(i);
        if b.text.is_empty() {
            b.text = text.as_bytes().to_vec();
        }
        count = count.max(i + 1);
    }
    // step 5: trailing empty fields that only `optional` lines address
    while count > 0 {
        let i = count - 1;
        if rec.fields.get(i).map_or(false, |b| !b.text.is_empty()) {
            break;
        }
        let by_group = group.map_or(false, |(s, e)| i >= s && i < e);
        let mut by = lines.iter().filter(|(l, _)| l.addresses(i)).peekable();
        if by_group || by.peek().is_none() || !by.all(|(_, optional)| *optional) {
            break;
        }
        count -= 1;
    }
    // step 6: the fields joined, the start text first, the checksum last
    let mut body: Vec<u8> = Vec::new();
    for i in 0..count {
        if i > 0 {
            if let Some(d) = p.text.delimiter {
                body.push(d);
            }
        }
        if let Some(b) = rec.fields.get(i) {
            body.extend_from_slice(&b.text);
        }
    }
    let mut out = p.text.start.clone();
    out.push_str(&String::from_utf8_lossy(&body));
    if p.text.nmea {
        let sum = body.iter().fold(0u8, |a, c| a ^ c);
        out.push_str(&format!("*{:02X}", sum));
    }
    Ok(out)
}
