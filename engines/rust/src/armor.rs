//! Six-bit armor (engine-spec v0.14): a `bits` pack with `armor sixbit` reads
//! and writes its message as printable text, six bits per character, instead
//! of hex. The message is then any number of bits. Also the `sixbit`
//! transform, a text field whose characters are six-bit codes, which any
//! `bits` pack may use.

#[cfg(feature = "bits")]
use super::bits::{get_bits, set_bits, span};
use super::seq::{SeqBody, SeqLine};
use super::*;

// ---------------------------------------------------------------------------
// The `armor` directive
// ---------------------------------------------------------------------------

/// How a `bits` message travels as text.
#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub enum Armor {
    /// lowercase hex, two digits a byte (Version 0.2)
    #[default]
    Hex,
    /// six bits a character, `0`..`W` and `` ` ``..`w`
    Sixbit,
}

/// The `armor` lines as read, checked once the file is read and the wire is
/// known (ruling 10 of 0.10).
#[derive(Default)]
pub(crate) struct ArmorLines {
    /// the first `armor` line
    line: Option<usize>,
    value: Armor,
    /// the first line that is wrong in itself: repeated, after a `kind`, or
    /// with a value that is neither `hex` nor `sixbit`
    fault: Option<(usize, String)>,
}

impl ArmorLines {
    /// Record one `armor` line. `after_kind`: a `kind` line came before it.
    pub(crate) fn record(&mut self, toks: &[String], ln: usize, after_kind: bool) {
        let fault = if self.line.is_some() {
            Some("`armor` given twice")
        } else if after_kind {
            Some("`armor` stands before the first `kind`")
        } else {
            match (toks.len(), toks.get(1).map(|s| s.as_str())) {
                (2, Some("hex")) => {
                    self.value = Armor::Hex;
                    None
                }
                (2, Some("sixbit")) => {
                    self.value = Armor::Sixbit;
                    None
                }
                _ => Some("`armor` is `hex` or `sixbit`"),
            }
        };
        self.line.get_or_insert(ln);
        if let (None, Some(m)) = (&self.fault, fault) {
            self.fault = Some((ln, m.to_string()));
        }
    }

    /// The armor of the pack. `bits`: the wire is `bits`; `msb`: the pack's
    /// bit order is `msb`.
    pub(crate) fn check(&self, bits: bool, msb: bool) -> Result<Armor, Error> {
        let ln = match self.line {
            Some(ln) => ln,
            None => return Ok(Armor::Hex),
        };
        if !bits {
            return bad(ln, "`armor` is valid only on a bits wire");
        }
        if let Some((at, m)) = &self.fault {
            return bad(*at, m);
        }
        if self.value == Armor::Sixbit && !msb {
            return bad(ln, "`armor sixbit` needs `bit_order msb`");
        }
        Ok(self.value)
    }
}

/// Ruling 3 of 0.14: `length ... whole` in a sequential pack with
/// `armor sixbit` is `bad-directive`, at any depth.
pub(crate) fn check_no_whole(body: &SeqBody) -> Result<(), Error> {
    fn lines(ls: &[SeqLine]) -> bool {
        ls.iter().any(|l| match l {
            SeqLine::Whole { .. } => true,
            SeqLine::If { body, .. } | SeqLine::Opt { body } | SeqLine::Length { body, .. } | SeqLine::Ext { body } => lines(body),
            SeqLine::Chain { parts, .. } => parts.iter().any(|p| lines(p)),
            SeqLine::Choice { alts, .. } => alts.iter().any(|(_, p)| lines(p)),
            SeqLine::Group(g) => in_body(&g.body),
            _ => false,
        })
    }
    fn in_body(b: &SeqBody) -> bool {
        lines(&b.common) || b.kinds.iter().any(|k| lines(&k.lines))
    }
    if in_body(body) {
        return err("bad-directive: `length ... whole` with `armor sixbit`: the armored text has no whole-byte length");
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// The armored text
// ---------------------------------------------------------------------------

/// Armored text to the message bits, most significant first, and the number
/// of bits (6 per character). Every character is checked before any line is
/// read: one outside `0`..`W` and `` ` ``..`w` is `malformed-wire`.
#[cfg(feature = "bits")]
pub(crate) fn read(p: &Pack, text: &str) -> Result<(Vec<u8>, u64), Error> {
    let chars = text.as_bytes();
    let total = chars.len() as u64 * 6;
    let mut raw = vec![0u8; ((total + 7) / 8) as usize];
    for (at, c) in chars.iter().enumerate() {
        let v = match c {
            0x30..=0x57 => c - 0x30,
            0x60..=0x77 => c - 0x38,
            _ => {
                return err(format!(
                    "malformed-wire: format `{}`: byte {} (0x{:02x}) is not a six-bit armor character",
                    p.format, at, c
                ))
            }
        };
        set_bits(&mut raw, at as u64 * 6, 6, v as u64, BitOrder::Msb);
    }
    Ok((raw, total))
}

/// The first `l` bits of `msg` (most significant first), then zero bits up
/// to a multiple of 6, as armored text.
#[cfg(feature = "bits")]
pub(crate) fn write(msg: &[u8], l: u64) -> String {
    let n = (l + 5) / 6;
    let mut out = String::with_capacity(n as usize);
    for k in 0..n {
        let mut v = 0u8;
        for b in 0..6 {
            let i = k * 6 + b;
            v <<= 1;
            if i < l && get_bits(msg, i, 1, BitOrder::Msb) == Some(1) {
                v |= 1;
            }
        }
        out.push((if v < 40 { 0x30 + v } else { 0x38 + v }) as char);
    }
    out
}

/// The length `L` of a fixed-layout message on encode: one more than the
/// highest bit of any field, `when` or `const` line of the selected scope, or
/// of a group's items (and counts), whether or not its key is present,
/// except an `optional` field whose key is absent and has no `default`. A
/// field with `absent` whose key is absent writes its first sentinel, so it
/// counts, optional or not (ruling 12 of 0.14).
#[cfg(feature = "bits")]
pub(crate) fn fixed_len(p: &Pack, sel: &Sel, ent: &Entity) -> Result<u64, Error> {
    let mut end = bits::group_reach(p, sel, ent, 0)?;
    for f in &sel.fields {
        // an `optional` field that writes nothing: its key absent with no
        // default and no sentinel, or the line suppressed by `with`, which
        // writes no sentinel either (ruling 23 of 0.18)
        let suppressed = !crate::live(ent, f);
        if f.optional && (suppressed || (f.absent.is_empty() && sel.value_of(ent, f).is_none())) {
            continue;
        }
        let (start, len) = span(p, &f.locator)?;
        end = end.max(start + len as u64);
    }
    for w in sel.fixed() {
        let (start, len) = span(p, &w.locator)?;
        end = end.max(start + len as u64);
    }
    Ok(end)
}

// ---------------------------------------------------------------------------
// The `sixbit` transform
// ---------------------------------------------------------------------------

/// A `len` the `sixbit` transform allows: a multiple of 6, from 6 to 1530.
pub(crate) fn sixbit_len_ok(len: u64) -> bool {
    len % 6 == 0 && (6..=1530).contains(&len)
}

/// Decode: each six bits, first to last in the pack's bit order, as one
/// character (0..31 as `@`..`_`, 32..63 as space..`?`), then the trailing `@`
/// removed; with `trim`, the whole trailing run of `@` and space.
#[cfg(feature = "bits")]
pub(crate) fn read_sixbit(p: &Pack, f: &FieldDef, raw: &[u8], start: u64, len: u32) -> Result<Value, Error> {
    let mut s: Vec<u8> = (0..len as u64 / 6)
        .map(|k| {
            let v = get_bits(raw, start + k * 6, 6, p.order).unwrap_or(0) as u8;
            if v < 32 {
                0x40 + v
            } else {
                v
            }
        })
        .collect();
    while matches!(s.last(), Some(b'@')) || (f.trim && matches!(s.last(), Some(b' '))) {
        s.pop();
    }
    Ok(Value::Str(s.iter().map(|b| *b as char).collect()))
}

/// Encode: each character as its six-bit value, padded with `@` (0) to
/// `len / 6` characters. A character outside 0x20..0x5F, or text longer than
/// the field, is `transform-encode`.
#[cfg(feature = "bits")]
pub(crate) fn write_sixbit(p: &Pack, f: &FieldDef, v: &Value, start: u64, len: u32, msg: &mut [u8]) -> Result<(), Error> {
    let fail = |m: String| transform_encode_err(p, f, Error { msg: m });
    let text = match v {
        Value::Str(s) => s.as_bytes(),
        other => return Err(fail(format!("sixbit encodes text, got {:?}", other))),
    };
    if let Some(b) = text.iter().find(|b| !(0x20..=0x5f).contains(*b)) {
        return Err(fail(format!("byte 0x{:02x} has no six-bit code", b)));
    }
    let room = (len / 6) as usize;
    if text.len() > room {
        return Err(fail(format!("text is {} characters, the field holds {}", text.len(), room)));
    }
    for k in 0..room {
        let c = text.get(k).copied().unwrap_or(b'@');
        let v = if c >= 0x40 { c - 0x40 } else { c };
        set_bits(msg, start + k as u64 * 6, 6, v as u64, p.order);
    }
    Ok(())
}
