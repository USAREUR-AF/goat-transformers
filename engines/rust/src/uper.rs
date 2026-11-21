//! ASN.1 unaligned PER (engine-spec v0.19): a sequential `bits` pack with
//! `encoding uper`. Its locators compute the bit length of a field from the
//! ASN.1 constraint and the value; `ext` and `choice` blocks and
//! `group … size` read the X.691 forms of SEQUENCE extension markers, CHOICE
//! and SEQUENCE OF. The lines themselves are parsed and walked in `seq.rs`;
//! this module holds the locators, the `encoding` directive and the X.691
//! reading and writing.

#[cfg(feature = "bits")]
use super::seq::{Reader, Writer};
use super::*;

/// A SIZE constraint `(lb..ub)`, or none.
pub type Size = Option<(u32, u32)>;

/// A UPER locator of a `field` line.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Loc {
    /// `int:<lb>:<ub>[:ext]`: `INTEGER (lb..ub[, ...])`
    Int { lb: i64, ub: i64, ext: bool },
    /// `int:<lb>:`: `INTEGER (lb..MAX)`
    Semi { lb: i64 },
    /// `int::`: `INTEGER`
    Unc,
    /// `enum:<n>[:ext]`: `ENUMERATED` with `n` root values
    Enum { n: u32, ext: bool },
    /// `chars:[<lb>:<ub>]`: a known-multiplier string of 7-bit characters
    Chars(Size),
    /// `octets:[<lb>:<ub>]`: `OCTET STRING`
    Octets(Size),
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

/// A number of a locator, `choice`, `alt` or `size` line (ruling 15 of 0.19):
/// an optional `-` and digits with no leading zero, `-0` refused, within 64
/// signed bits.
pub(crate) fn num(s: &str) -> Option<i64> {
    let digits = s.strip_prefix('-').unwrap_or(s);
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) || (digits.len() > 1 && digits.starts_with('0')) {
        return None;
    }
    if s == "-0" {
        return None;
    }
    s.parse::<i64>().ok()
}

/// A SIZE `lb ub`: `0 <= lb <= ub < 65536`.
pub(crate) fn size(lb: &str, ub: &str) -> Option<(u32, u32)> {
    let (lb, ub) = (num(lb)?, num(ub)?);
    if 0 <= lb && lb <= ub && ub < 65536 {
        Some((lb as u32, ub as u32))
    } else {
        None
    }
}

/// The locator of a `field` line, when it is one of the UPER forms (None:
/// it is not; the caller reads a bit length). A locator that starts as one
/// of them and is not valid is `bad-directive`.
pub(crate) fn parse_loc(text: &str, ln: usize) -> Result<Option<Loc>, Error> {
    let (head, rest) = match text.split_once(':') {
        Some(x) => x,
        None => return Ok(None),
    };
    if !matches!(head, "int" | "enum" | "chars" | "octets") {
        return Ok(None);
    }
    let parts: Vec<&str> = rest.split(':').collect();
    let loc = match (head, parts.as_slice()) {
        ("int", ["", ""]) => Some(Loc::Unc),
        ("int", [lb, ""]) => num(lb).map(|lb| Loc::Semi { lb }),
        ("int", [lb, ub]) | ("int", [lb, ub, "ext"]) => match (num(lb), num(ub)) {
            (Some(lb), Some(ub)) if lb <= ub => Some(Loc::Int { lb, ub, ext: parts.len() == 3 }),
            _ => None,
        },
        ("enum", [n]) | ("enum", [n, "ext"]) => {
            num(n).filter(|n| (1..=65536).contains(n)).map(|n| Loc::Enum { n: n as u32, ext: parts.len() == 2 })
        }
        ("chars", [""]) => Some(Loc::Chars(None)),
        ("octets", [""]) => Some(Loc::Octets(None)),
        ("chars", [lb, ub]) => size(lb, ub).map(|s| Loc::Chars(Some(s))),
        ("octets", [lb, ub]) => size(lb, ub).map(|s| Loc::Octets(Some(s))),
        _ => None,
    };
    match loc {
        Some(l) => Ok(Some(l)),
        None => bad(ln, format!("`{}` is not a valid UPER locator", text)),
    }
}

/// The transform and the options of a field on a UPER locator.
pub(crate) fn check_field(loc: &Loc, f: &FieldDef) -> Result<(), Error> {
    if f.swap || f.trim {
        return bad(f.line, "`swap` and `trim` are not valid on a UPER locator");
    }
    let t = &f.transform;
    let ok = match loc {
        Loc::Int { .. } | Loc::Semi { .. } | Loc::Unc => {
            matches!(t, Transform::Uint | Transform::Twos | Transform::Uscale(_) | Transform::Sscale(_))
        }
        Loc::Enum { .. } => *t == Transform::Uint,
        Loc::Chars(_) => *t == Transform::Ascii,
        Loc::Octets(_) => matches!(t, Transform::Hex | Transform::Utf8),
    };
    if !ok {
        return bad(f.line, format!("the transform of `{}` is not valid on the locator `{}`", f.model_key, f.locator));
    }
    Ok(())
}

/// The `encoding` lines as read, checked once the file is read (ruling 10
/// of 0.10).
#[derive(Default)]
pub(crate) struct EncodingLines {
    /// the first `encoding` line
    line: Option<usize>,
    uper: bool,
    /// the first line that is wrong in itself: repeated, after a `kind`, or
    /// with a value that is neither `none` nor `uper`
    fault: Option<(usize, String)>,
}

impl EncodingLines {
    /// Record one `encoding` line. `after_kind`: a `kind` line came before it.
    pub(crate) fn record(&mut self, toks: &[String], ln: usize, after_kind: bool) {
        let fault = if self.line.is_some() {
            Some("`encoding` given twice")
        } else if after_kind {
            Some("`encoding` stands before the first `kind`")
        } else {
            match (toks.len(), toks.get(1).map(|s| s.as_str())) {
                (2, Some("none")) => None,
                (2, Some("uper")) => {
                    self.uper = true;
                    None
                }
                _ => Some("`encoding` is `none` or `uper`"),
            }
        };
        self.line.get_or_insert(ln);
        if let (None, Some(m)) = (&self.fault, fault) {
            self.fault = Some((ln, m.to_string()));
        }
    }

    /// Is the pack a UPER pack? `bits`: the wire is `bits`; `sequential`:
    /// `layout sequential`; `msb`: `bit_order msb`; `sixbit`: `armor sixbit`
    /// (ruling 11 of 0.19).
    pub(crate) fn check(&self, bits: bool, sequential: bool, msb: bool, sixbit: bool) -> Result<bool, Error> {
        let ln = match self.line {
            Some(ln) => ln,
            None => return Ok(false),
        };
        // ruling 18 of 0.19: whatever its value, on a wire other than `bits`
        if !bits {
            return bad(ln, "`encoding` is valid only on a bits wire");
        }
        if let Some((at, m)) = &self.fault {
            return bad(*at, m);
        }
        if !self.uper {
            return Ok(false);
        }
        if !sequential {
            return bad(ln, "`encoding uper` needs `layout sequential`");
        }
        if !msb {
            return bad(ln, "`encoding uper` needs `bit_order msb`");
        }
        if sixbit {
            return bad(ln, "`encoding uper` and `armor sixbit` in one pack");
        }
        Ok(true)
    }
}

/// The fewest bits that hold `range` (0 for 0).
#[cfg(feature = "bits")]
pub(crate) fn bits_for(range: u64) -> u32 {
    64 - range.leading_zeros()
}

/// `ub - lb` as an unsigned number: it never overflows (ruling 4 of 0.19).
#[cfg(feature = "bits")]
fn range(lb: i64, ub: i64) -> u64 {
    (ub as i128 - lb as i128) as u64
}

// ---------------------------------------------------------------------------
// Decode
// ---------------------------------------------------------------------------

/// A length determinant: `0` and 7 bits, or `10` and 14 bits. `11`, a
/// fragmented length, is `malformed-wire`.
#[cfg(feature = "bits")]
fn read_len(r: &mut Reader, what: &str) -> Result<u64, Error> {
    if r.read(1, what)? == 0 {
        return r.read(7, what);
    }
    if r.read(1, what)? == 0 {
        return r.read(14, what);
    }
    Err(r.short(format!("{}: a fragmented length (first bits 11) at bit {}", what, r.pos - 2)))
}

/// `n` units of `unit` bits must lie in the input, before any is read.
#[cfg(feature = "bits")]
fn hold(r: &Reader, n: u64, unit: u64, what: &str) -> Result<(), Error> {
    let left = r.end.saturating_sub(r.pos);
    if n.checked_mul(unit).map_or(true, |b| b > left) {
        return Err(r.short(format!("{}: {} at bit {} is more than the input holds", what, n, r.pos)));
    }
    Ok(())
}

/// A constrained whole number in `0..=range`: a value above it is
/// `malformed-wire`.
#[cfg(feature = "bits")]
fn read_constrained(r: &mut Reader, range: u64, what: &str) -> Result<u64, Error> {
    let at = r.pos;
    let v = r.read(bits_for(range), what)?;
    if v > range {
        return Err(r.short(format!("{}: {} at bit {} is above its constraint", what, v, at)));
    }
    Ok(v)
}

/// `k` octets of an integer, big-endian; None when they are more than 8
/// (skipped). 0 octets is `malformed-wire` (ruling 5 of 0.19).
#[cfg(feature = "bits")]
fn read_int_octets(r: &mut Reader, k: u64, what: &str) -> Result<Option<u64>, Error> {
    if k == 0 {
        return Err(r.short(format!("{}: an integer of 0 octets at bit {}", what, r.pos)));
    }
    hold(r, k, 8, what)?;
    if k > 8 {
        r.pos += k * 8;
        return Ok(None);
    }
    Ok(Some(r.read((k * 8) as u32, what)?))
}

/// The low `k` octets of `u` as a two's-complement number.
#[cfg(feature = "bits")]
fn signed(u: u64, k: u64) -> i64 {
    if k >= 8 {
        return u as i64;
    }
    let bits = k * 8;
    if u >> (bits - 1) & 1 == 1 {
        (u as i64) - (1i64 << bits)
    } else {
        u as i64
    }
}

/// A normally small non-negative whole number; None when it is longer than
/// 8 octets.
#[cfg(feature = "bits")]
fn read_small(r: &mut Reader, what: &str) -> Result<Option<u64>, Error> {
    if r.read(1, what)? == 0 {
        return Ok(Some(r.read(6, what)?));
    }
    let k = read_len(r, what)?;
    read_int_octets(r, k, what)
}

/// An open type, skipped: a length determinant of an octet count, then the octets.
#[cfg(feature = "bits")]
fn skip_open(r: &mut Reader, what: &str) -> Result<(), Error> {
    let k = read_len(r, what)?;
    hold(r, k, 8, what)?;
    r.pos += k * 8;
    Ok(())
}

/// A count in `size`: a constrained whole number, or a length determinant.
#[cfg(feature = "bits")]
pub(crate) fn read_count(r: &mut Reader, size: Size, what: &str) -> Result<u64, Error> {
    match size {
        Some((lb, ub)) => Ok(lb as u64 + read_constrained(r, (ub - lb) as u64, what)?),
        None => read_len(r, what),
    }
}

/// The extension additions after an `ext` block whose bit is 1: their
/// number as a normally small length (ruling 16), the presence bits, and an
/// open type for each bit that is 1. They are skipped.
#[cfg(feature = "bits")]
pub(crate) fn skip_additions(r: &mut Reader) -> Result<(), Error> {
    let what = "the extension additions of an `ext`";
    let m = if r.read(1, what)? == 0 { r.read(6, what)? + 1 } else { read_len(r, what)? };
    hold(r, m, 1, what)?;
    let mut present = 0u64;
    for _ in 0..m {
        present += r.read(1, what)?;
    }
    for _ in 0..present {
        skip_open(r, what)?;
    }
    Ok(())
}

/// The alternative of a `choice` the input selects; None for an extension
/// alternative, which is skipped.
#[cfg(feature = "bits")]
pub(crate) fn read_choice(r: &mut Reader, n: u32, ext: bool) -> Result<Option<u32>, Error> {
    let what = "the index of a `choice`";
    if ext && r.read(1, what)? == 1 {
        read_small(r, what)?;
        skip_open(r, what)?;
        return Ok(None);
    }
    Ok(Some(r.read(bits_for(n as u64 - 1), what)? as u32))
}

/// An integer value through the field's transform: `uint` and `twos` give
/// it, the scales `v * f + o`.
#[cfg(feature = "bits")]
fn int_value(f: &FieldDef, v: i64) -> Result<Value, Error> {
    match &f.transform {
        Transform::Uint | Transform::Twos => Ok(Value::I64(v)),
        Transform::Uscale(sc) | Transform::Sscale(sc) => finite(sc.decode(v as f64)),
        t => err(format!("transform {:?} is not valid on a UPER integer", t)),
    }
}

#[cfg(feature = "bits")]
fn too_large<T>() -> Result<T, Error> {
    err("the integer does not fit 64 signed bits")
}

/// Read one field at the cursor. The outer error is the wire's
/// (`malformed-wire`); the inner one the transform's, which fails the
/// field and not the read.
#[cfg(feature = "bits")]
pub(crate) fn read_field(r: &mut Reader, f: &FieldDef, loc: &Loc) -> Result<Result<Value, Error>, Error> {
    let what = format!("`{}`", f.model_key);
    let what = what.as_str();
    Ok(match *loc {
        Loc::Int { lb, ub, ext } => {
            if ext && r.read(1, what)? == 1 {
                let k = read_len(r, what)?;
                match read_int_octets(r, k, what)? {
                    Some(u) => int_value(f, signed(u, k)),
                    None => too_large(),
                }
            } else {
                let off = read_constrained(r, range(lb, ub), what)?;
                int_value(f, (lb as i128 + off as i128) as i64)
            }
        }
        Loc::Semi { lb } => {
            let k = read_len(r, what)?;
            match read_int_octets(r, k, what)? {
                Some(u) => match i64::try_from(lb as i128 + u as i128) {
                    Ok(v) => int_value(f, v),
                    Err(_) => too_large(),
                },
                None => too_large(),
            }
        }
        Loc::Unc => {
            let k = read_len(r, what)?;
            match read_int_octets(r, k, what)? {
                Some(u) => int_value(f, signed(u, k)),
                None => too_large(),
            }
        }
        Loc::Enum { n, ext } => {
            if ext && r.read(1, what)? == 1 {
                match read_small(r, what)?.and_then(|i| i64::try_from(n as u128 + i as u128).ok()) {
                    Some(v) => Ok(Value::I64(v)),
                    None => too_large(),
                }
            } else {
                Ok(Value::I64(read_constrained(r, n as u64 - 1, what)? as i64))
            }
        }
        Loc::Chars(size) => {
            let n = read_count(r, size, what)?;
            hold(r, n, 7, what)?;
            let mut s = String::with_capacity(n as usize);
            for _ in 0..n {
                s.push(r.read(7, what)? as u8 as char);
            }
            Ok(Value::Str(s))
        }
        Loc::Octets(size) => {
            let n = read_count(r, size, what)?;
            hold(r, n, 8, what)?;
            let mut b = Vec::with_capacity(n as usize);
            for _ in 0..n {
                b.push(r.read(8, what)? as u8);
            }
            tlv::decode_value(&f.transform, &b)
        }
    })
}

// ---------------------------------------------------------------------------
// Encode
// ---------------------------------------------------------------------------

/// A length determinant of `n`; 16384 or more (a fragmented length) is
/// `transform-encode`.
#[cfg(feature = "bits")]
fn write_len(w: &mut Writer, n: u64, what: &str) -> Result<(), Error> {
    if n < 128 {
        w.put(8, n);
    } else if n < 16384 {
        w.put(16, 0x8000 | n);
    } else {
        return Err(w.fail(format!("{}: a length of {} needs a fragmented length", what, n)));
    }
    Ok(())
}

/// An unsigned number in the fewest octets (at least one), after a length
/// determinant of their count.
#[cfg(feature = "bits")]
fn write_uint(w: &mut Writer, u: u64, what: &str) -> Result<(), Error> {
    let k = ((bits_for(u) + 7) / 8).max(1);
    write_len(w, k as u64, what)?;
    w.put(k * 8, u);
    Ok(())
}

/// A two's-complement number in the fewest octets, after a length
/// determinant of their count.
#[cfg(feature = "bits")]
fn write_twos(w: &mut Writer, x: i64, what: &str) -> Result<(), Error> {
    let k = (1u32..8).find(|k| {
        let half = 1i64 << (k * 8 - 1);
        (-half..half).contains(&x)
    });
    let k = k.unwrap_or(8);
    write_len(w, k as u64, what)?;
    let mask = if k == 8 { u64::MAX } else { (1u64 << (k * 8)) - 1 };
    w.put(k * 8, x as u64 & mask);
    Ok(())
}

/// A normally small non-negative whole number.
#[cfg(feature = "bits")]
fn write_small(w: &mut Writer, n: u64, what: &str) -> Result<(), Error> {
    if n <= 63 {
        w.put(7, n);
        return Ok(());
    }
    w.put(1, 1);
    write_uint(w, n, what)
}

/// A count in `size`; one outside `lb..ub` is `transform-encode`.
#[cfg(feature = "bits")]
pub(crate) fn write_count(w: &mut Writer, size: Size, n: usize, what: &str) -> Result<(), Error> {
    match size {
        Some((lb, ub)) => {
            if n < lb as usize || n > ub as usize {
                return Err(w.fail(format!("{}: a count of {} is outside {}..{}", what, n, lb, ub)));
            }
            w.put(bits_for((ub - lb) as u64), (n - lb as usize) as u64);
            Ok(())
        }
        None => write_len(w, n as u64, what),
    }
}

/// The integer a model value stands for, through the transform: the value,
/// or `round((x - o) / f)`.
#[cfg(feature = "bits")]
fn int_of(w: &Writer, k: &FieldDef, v: &Value) -> Result<i64, Error> {
    let fail = |m: String| transform_encode_err(w.p, k, Error { msg: m });
    match (&k.transform, v) {
        (Transform::Uint | Transform::Twos, Value::I64(n)) => Ok(*n),
        (Transform::Uscale(sc) | Transform::Sscale(sc), Value::F64(x)) => {
            // round((x - o) / f), halfway away from zero (4a of 0.11)
            let r = sc.quotient(*x).round();
            // 2^63 is exact in f64
            if r.is_finite() && r >= -(2f64.powi(63)) && r < 2f64.powi(63) {
                Ok(r as i64)
            } else {
                Err(fail(format!("{} is outside every integer constraint", x)))
            }
        }
        (t, v) => Err(fail(format!("transform/value mismatch on a UPER integer: {:?} with {:?}", t, v))),
    }
}

/// Write one field. `v`: the key that is written and its wire value, or
/// None for an absent key, which writes the values of ruling 1 of 0.19.
#[cfg(feature = "bits")]
pub(crate) fn write_field(w: &mut Writer, f: &FieldDef, loc: &Loc, v: Option<(&FieldDef, &Value)>) -> Result<(), Error> {
    let what = format!("`{}`", f.model_key);
    let what = what.as_str();
    let outside = |w: &Writer, k: &FieldDef, m: String| transform_encode_err(w.p, k, Error { msg: m });
    match *loc {
        Loc::Int { lb, ub, ext } => {
            let x = match v {
                Some((k, v)) => int_of(w, k, v)?,
                None => lb,
            };
            if (lb..=ub).contains(&x) {
                if ext {
                    w.put(1, 0);
                }
                w.put(bits_for(range(lb, ub)), range(lb, x));
            } else if ext {
                w.put(1, 1);
                write_twos(w, x, what)?;
            } else {
                return Err(outside(w, v.map_or(f, |(k, _)| k), format!("{} is outside {}..{}", x, lb, ub)));
            }
        }
        Loc::Semi { lb } => {
            let x = match v {
                Some((k, v)) => int_of(w, k, v)?,
                None => lb,
            };
            if x < lb {
                return Err(outside(w, v.map_or(f, |(k, _)| k), format!("{} is below {}", x, lb)));
            }
            write_uint(w, range(lb, x), what)?;
        }
        Loc::Unc => {
            let x = match v {
                Some((k, v)) => int_of(w, k, v)?,
                None => 0,
            };
            write_twos(w, x, what)?;
        }
        Loc::Enum { n, ext } => {
            let i = match v {
                None => 0,
                Some((_, Value::I64(i))) => *i,
                Some((k, other)) => return Err(outside(w, k, format!("an enumerated index is an integer, got {:?}", other))),
            };
            if (0..n as i64).contains(&i) {
                if ext {
                    w.put(1, 0);
                }
                w.put(bits_for(n as u64 - 1), i as u64);
            } else if ext && i >= n as i64 {
                w.put(1, 1);
                write_small(w, (i - n as i64) as u64, what)?;
            } else {
                return Err(outside(w, v.map_or(f, |(k, _)| k), format!("index {} is outside the {} root values", i, n)));
            }
        }
        Loc::Chars(size) => {
            let codes: Vec<u64> = match v {
                None => vec![0; size.map_or(0, |(lb, _)| lb as usize)],
                Some((k, Value::Str(s))) => {
                    let mut out = Vec::with_capacity(s.len());
                    for c in s.chars() {
                        if c as u32 > 127 {
                            return Err(outside(w, k, format!("character U+{:04X} has no 7-bit code", c as u32)));
                        }
                        out.push(c as u64);
                    }
                    out
                }
                Some((k, other)) => return Err(outside(w, k, format!("ascii encodes text, got {:?}", other))),
            };
            write_count(w, size, codes.len(), what)?;
            for c in codes {
                w.put(7, c);
            }
        }
        Loc::Octets(size) => {
            let bytes = match v {
                None => vec![0u8; size.map_or(0, |(lb, _)| lb as usize)],
                Some((k, v)) => tlv::encode_value(&k.transform, v, None).map_err(|e| transform_encode_err(w.p, k, e))?,
            };
            write_count(w, size, bytes.len(), what)?;
            for b in bytes {
                w.put(8, b as u64);
            }
        }
    }
    Ok(())
}
