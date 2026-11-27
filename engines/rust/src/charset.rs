//! Engine-spec 0.46: character sets a pack declares, and the transforms
//! `code`, `codestr` and `codenum` over a sequence of them.

use super::*;
use std::sync::Arc;

/// One `charset` line: the characters in code order.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Set {
    name: String,
    chars: Vec<char>,
    /// bits per character (`bits` only)
    width: u32,
}

/// The positions of one `code`, `codestr` or `codenum` transform. Opaque: only
/// reading a pack makes one.
#[derive(Clone, Debug, PartialEq)]
pub struct CodeSeq {
    /// the list as written, after the first `:`
    names: String,
    /// one set per position, filled in once the file is read
    sets: Vec<Arc<Set>>,
}

impl CodeSeq {
    /// The list of a field's transform when it is one of the three. It is
    /// checked after the file is read, its syntax included (ruling 15).
    pub(crate) fn of(transform: &str) -> Option<Arc<CodeSeq>> {
        let (head, names) = transform.split_once(':').unwrap_or((transform, ""));
        if !matches!(head, "code" | "codestr" | "codenum") {
            return None;
        }
        Some(Arc::new(CodeSeq { names: names.to_string(), sets: Vec::new() }))
    }

    /// The product of the sets' sizes: at most 94^16, below 2^128.
    fn product(&self) -> u128 {
        self.sets.iter().map(|s| s.chars.len() as u128).product()
    }

    #[cfg(any(feature = "bits", feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
    fn text_of(&self, codes: &[usize]) -> String {
        self.sets.iter().zip(codes).map(|(s, c)| s.chars[*c]).collect()
    }

    /// One character per position, each in its position's set.
    #[cfg(any(feature = "bits", feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
    fn codes_of_text(&self, text: &str) -> Result<Vec<usize>, Error> {
        let n = text.chars().count();
        if n != self.sets.len() {
            return err(format!("`{}` is {} characters, not {}", text, n, self.sets.len()));
        }
        let code = |(c, s): (char, &Arc<Set>)| match s.chars.iter().position(|x| *x == c) {
            Some(i) => Ok(i),
            None => err(format!("character {:?} of `{}` is not in the set `{}`", c, text, s.name)),
        };
        text.chars().zip(&self.sets).map(code).collect()
    }

    /// The mixed-radix number of the codes, first position most significant.
    #[cfg(any(feature = "bits", feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
    fn number_of(&self, codes: &[usize]) -> Result<Value, Error> {
        let v = self.sets.iter().zip(codes).fold(0u128, |v, (s, c)| v * s.chars.len() as u128 + *c as u128);
        // the product is at most 2^63 (ruling 20), so it always fits
        i64::try_from(v).map(Value::I64).map_err(|_| Error { msg: format!("{} is beyond a 64-bit integer", v) })
    }

    #[cfg(any(feature = "bits", feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
    fn codes_of_number(&self, v: &Value) -> Result<Vec<usize>, Error> {
        let mut x = match v {
            Value::I64(x) if *x >= 0 && (*x as u128) < self.product() => *x as u128,
            other => return err(format!("{} is not an integer from 0 to {}", other.as_display(), self.product() - 1)),
        };
        let mut codes = vec![0; self.sets.len()];
        for (slot, s) in codes.iter_mut().zip(&self.sets).rev() {
            let n = s.chars.len() as u128;
            *slot = (x % n) as usize;
            x /= n;
        }
        Ok(codes)
    }

    /// The codes of a field's bits: position 0 is the most significant (ruling 6).
    #[cfg(feature = "bits")]
    fn codes_of_raw(&self, raw: u64) -> Result<Vec<usize>, Error> {
        let mut left: u32 = self.sets.iter().map(|s| s.width).sum();
        let mut codes = Vec::with_capacity(self.sets.len());
        for s in &self.sets {
            left -= s.width;
            let c = ((raw >> left) & ((1u64 << s.width) - 1)) as usize;
            if c >= s.chars.len() {
                return err(format!("code {} is not in the set `{}`", c, s.name));
            }
            codes.push(c);
        }
        Ok(codes)
    }

    #[cfg(feature = "bits")]
    fn raw_of(&self, codes: &[usize]) -> u64 {
        self.sets.iter().zip(codes).fold(0, |raw, (s, c)| raw << s.width | *c as u64)
    }

    /// `code` and `codenum` on `bits`.
    #[cfg(feature = "bits")]
    pub(crate) fn decode_raw(&self, t: Transform, raw: u64) -> Result<Value, Error> {
        let codes = self.codes_of_raw(raw)?;
        if t == Transform::Codenum {
            self.number_of(&codes)
        } else {
            Ok(Value::Str(self.text_of(&codes)))
        }
    }

    #[cfg(feature = "bits")]
    pub(crate) fn encode_raw(&self, t: Transform, v: &Value) -> Result<u64, Error> {
        let codes = match v {
            _ if t == Transform::Codenum => self.codes_of_number(v)?,
            Value::Str(s) => self.codes_of_text(s)?,
            other => return err(format!("code encodes text, got {}", other.as_display())),
        };
        Ok(self.raw_of(&codes))
    }
}

/// `codestr` and `codenum` on the text wires; None for another transform.
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
pub(crate) fn decode_text(f: &FieldDef, text: &str) -> Option<Result<Value, Error>> {
    let q = f.code.as_ref()?;
    Some(q.codes_of_text(text).and_then(|c| match f.transform {
        Transform::Codenum => q.number_of(&c),
        _ => Ok(Value::Str(text.to_string())),
    }))
}

#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "text"))]
pub(crate) fn encode_text(f: &FieldDef, v: &Value) -> Option<Result<String, Error>> {
    let q = f.code.as_ref()?;
    Some(match (f.transform, v) {
        (Transform::Codenum, v) => q.codes_of_number(v).map(|c| q.text_of(&c)),
        (_, Value::Str(s)) => q.codes_of_text(s).map(|_| s.clone()),
        (_, other) => err(format!("codestr encodes text, got {}", other.as_display())),
    })
}

/// A field's text through its transform, any transform of the wire.
#[cfg(any(feature = "xml", feature = "geojson"))]
pub(crate) fn decode_field(f: &FieldDef, text: &str) -> Result<Value, Error> {
    decode_text(f, text).unwrap_or_else(|| f.transform.decode(text))
}

#[cfg(feature = "xml")]
pub(crate) fn encode_field(f: &FieldDef, v: &Value) -> Result<String, Error> {
    encode_text(f, v).unwrap_or_else(|| f.transform.encode(v))
}

/// On `json` and `geojson` the member is a string, `codenum` included (ruling 11).
#[cfg(any(feature = "geojson", feature = "json"))]
pub(crate) fn decode_json(f: &FieldDef, j: &json::Json) -> Option<Result<Value, Error>> {
    f.code.as_ref()?;
    match j {
        json::Json::Str(s) => decode_text(f, s),
        _ => Some(err(format!("JSON value `{}` is not a string", json::serialize(j)))),
    }
}

#[cfg(any(feature = "geojson", feature = "json"))]
pub(crate) fn encode_json(f: &FieldDef, v: &Value) -> Option<Result<json::Json, Error>> {
    Some(encode_text(f, v)?.map(json::Json::Str))
}

/// The `charset` lines as read; every error but the number of arguments is
/// raised once the file is read.
#[derive(Default)]
pub(crate) struct CharsetLines {
    lines: Vec<(usize, Vec<String>, bool)>,
}

impl CharsetLines {
    pub(crate) fn record(&mut self, toks: &[String], ln: usize, after_kind: bool) {
        self.lines.push((ln, toks[1..].to_vec(), after_kind));
    }

    /// The declared sets, each line checked.
    pub(crate) fn check(&self, wire: Wire) -> Result<Vec<Arc<Set>>, Error> {
        let mut sets: Vec<Arc<Set>> = Vec::new();
        for (ln, args, after_kind) in &self.lines {
            let ln = *ln;
            if *after_kind {
                return bad(ln, "`charset` stands before the first `kind`");
            }
            let (name, text) = match args.as_slice() {
                [n, t] | [n, t, _] => (n, t),
                _ => return bad(ln, "charset needs <name> <characters> [<width>]"),
            };
            if name.is_empty() || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-') {
                return bad(ln, format!("`{}` is not a charset name", name));
            }
            if sets.iter().any(|s| s.name == *name) {
                return bad(ln, format!("a second `charset {}`", name));
            }
            let chars: Vec<char> = text.chars().collect();
            if chars.is_empty() {
                return bad(ln, format!("`charset {}` has no character", name));
            }
            for (i, c) in chars.iter().enumerate() {
                if !('!'..='~').contains(c) || *c == '"' {
                    return bad(ln, format!("`charset {}`: {:?} cannot be in a set", name, c));
                }
                if chars[..i].contains(c) {
                    return bad(ln, format!("`charset {}`: {:?} is repeated", name, c));
                }
            }
            // max(1, ceil(log2(size))), ruling 8
            let least = chars.len().next_power_of_two().trailing_zeros().max(1);
            // a width off `bits` is ignored entirely (ruling 14)
            let width = match args.get(2) {
                Some(w) if wire == Wire::Bits => match unsigned_text(w).and_then(|n| u32::try_from(n).ok()) {
                    Some(n) if (least..=8).contains(&n) => n,
                    _ => return bad(ln, format!("`charset {}`: the width `{}` is not from {} to 8", name, w, least)),
                },
                _ => least,
            };
            sets.push(Arc::new(Set { name: name.clone(), chars, width }));
        }
        Ok(sets)
    }
}

/// Give a field's transform its sets and check it against its place. `len`:
/// the bit length on `bits`; `conf`: the delimiter and checksum on `text`.
pub(crate) fn resolve(f: &mut FieldDef, sets: &[Arc<Set>], len: Option<u64>, conf: Option<&text::TextConf>) -> Result<(), Error> {
    let ln = f.line;
    let number = f.transform == Transform::Codenum;
    let q = match &mut f.code {
        Some(q) => q,
        None => return Ok(()),
    };
    let names: Vec<&str> = q.names.split(',').collect();
    if names.len() > 16 {
        return bad(ln, format!("{} positions; at most 16", names.len()));
    }
    let mut seq = CodeSeq { names: q.names.clone(), sets: Vec::with_capacity(names.len()) };
    for n in names {
        match sets.iter().find(|s| s.name == n) {
            Some(s) => seq.sets.push(s.clone()),
            None => return bad(ln, format!("`{}` is not a set a `charset` line declares", n)),
        }
    }
    if let Some(len) = len {
        let sum: u64 = seq.sets.iter().map(|s| s.width as u64).sum();
        if sum != len || sum > 64 {
            return bad(ln, format!("the positions take {} bits and the field has {}; at most 64", sum, len));
        }
    }
    if number && seq.product() > 1u128 << 63 {
        return bad(ln, "the product of the sizes of `codenum` is above 2^63");
    }
    if let Some(conf) = conf {
        for s in &seq.sets {
            let holds = |b: u8| s.chars.contains(&(b as char));
            if conf.delimiter.map_or(false, holds) || (conf.nmea && holds(b'*')) {
                return bad(ln, format!("the set `{}` holds a character the record cannot carry", s.name));
            }
        }
    }
    *q = Arc::new(seq);
    Ok(())
}
