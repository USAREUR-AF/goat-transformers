//! goat-transformers reference engine (std-only).
//!
//! Data-driven any-to-any tactical message transformation. A `Pack` describes a
//! format as data (see `spec/engine-spec.md`); the engine interprets packs. No
//! message definition is compiled in. This is the reference implementation that
//! the other language engines are checked against via the shared vectors.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;

mod exact;
pub use exact::Exact;

// ---------------------------------------------------------------------------
// Shared model
// ---------------------------------------------------------------------------

/// A typed value in the shared model. One variant per model field type.
#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Str(String),
    F64(f64),
    I64(i64),
}

impl Value {
    fn as_f64(&self) -> f64 {
        match self {
            Value::F64(x) => *x,
            Value::I64(n) => *n as f64,
            Value::Str(_) => f64::NAN,
        }
    }
    pub fn key_type(&self) -> KeyType {
        match self {
            Value::Str(_) => KeyType::Str,
            Value::F64(_) => KeyType::Float,
            Value::I64(_) => KeyType::Int,
        }
    }
    pub fn as_display(&self) -> String {
        match self {
            Value::Str(s) => s.clone(),
            Value::F64(x) => fmt_f64(*x),
            Value::I64(n) => n.to_string(),
        }
    }
}

/// One entity: shared-model fields plus per-format residue for round-trip.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Entity {
    pub fields: BTreeMap<String, Value>,
    /// Lists (engine-spec v0.7): list name -> items, in order. An item is an
    /// entity with no residue and no kind. A present, empty list is distinct
    /// from an absent one.
    pub lists: BTreeMap<String, Vec<Entity>>,
    /// (format, locator, raw wire value) for fields the model does not hold.
    pub residue: Vec<(String, String, String)>,
    /// (format, kind name) selected by the last decode of a pack with kinds.
    pub kind: Option<(String, String)>,
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub struct Error {
    pub msg: String,
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.msg)
    }
}
impl std::error::Error for Error {}
fn err<T>(m: impl Into<String>) -> Result<T, Error> {
    Err(Error { msg: m.into() })
}

// ---------------------------------------------------------------------------
// Transforms: reversible string <-> Value
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Transform {
    StringT,
    Float,
    Int,
    Iso8601Ms,
    /// xml, json, geojson (engine-spec v0.18): `iso8601_ms` without a zero fraction
    Iso8601Short,
    /// xml, json, geojson (engine-spec v0.55): `iso8601_ms` with no fraction at
    /// a whole second, three digits otherwise
    Iso8601Si,
    // bits-wire transforms (raw integer <-> model value, bit length from the locator)
    Uint,
    Twos,
    /// signed N-bit two's complement scaled linearly: value / maxpos * range
    Linscale(f64, f64),
    // protobuf-wire transforms (a leaf field's wire value <-> model value)
    Pstring,
    Pvarint,
    Psint,
    Pdouble,
    Pfloat,
    /// json wire: `true`/`false` <-> int 1/0
    Bool,
    /// bits: unsigned v scaled, plus offset
    Uscale(Scale),
    /// bits: two's-complement v scaled, plus offset
    Sscale(Scale),
    /// bits: 32 bits as an IEEE-754 single
    F32,
    /// bits: 64 bits as an IEEE-754 double
    F64,
    /// bits: bytes in wire order as text, trailing NULs removed
    Ascii,
    /// bits: six-bit character codes as text, trailing `@` removed (engine-spec v0.14)
    Sixbit,
    /// text: `int:<w>`, an integer zero-padded to at least `w` digits
    IntW(u32),
    /// text: `dec:<f>[:<w>]`, a number with `f` fraction digits, zero-padded
    /// to at least `w` characters (0: no width)
    Dec(u32, u32),
    /// text: `dm:<d>:<f>:<PN>`, degrees and minutes in a pair, with the
    /// letters of the positive and the negative hemisphere
    Dm(u32, u32, u8, u8),
    /// text: `hms:<f>`, `hhmmss[.s]` as seconds since midnight
    Hms(u32),
    /// text: `hms_dmy:<f>`, a time and a date `ddmmyy` in a pair, as epoch ms
    HmsDmy(u32),
    /// tlv: the value bytes as UTF-8 text
    Utf8,
    /// tlv: the value bytes as lowercase hex text; bits: `len / 4` lowercase
    /// hex digits, digit k the 4-bit field at bit 4k (engine-spec v0.13, v0.22)
    Hex,
    // engine-spec v0.15: value transforms
    /// bits: unsigned v, then `round(v × factor) + offset`, exactly
    Uiscale(Exact),
    /// bits: two's-complement v, then `round(v × factor) + offset`, exactly
    Siscale(Exact),
    /// bits: sign and magnitude
    Smag,
    /// bits: the `smag` value scaled as `sscale` scales
    Smscale(Scale),
    /// bits: an IEEE-754 single, scaled
    F32scale(Scale),
    /// bits: an IEEE-754 double, scaled
    F64scale(Scale),
    /// bits: text in a 6-bit or 7-bit character set
    Chars(CharSet),
    /// bits: the unsigned value as `len / 3` octal digits
    Octal,
    /// xml, json, geojson: `scale:<factor>[:<offset>]`, a float scaled in doubles
    TextScale(Scale),
    /// xml, json, geojson: `iscale:<factor>[:<offset>]`, an exact decimal scaled to an int
    TextIscale(Exact),
}

/// The character set of `chars:<set>` (engine-spec v0.15).
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum CharSet {
    Icao6,
    Ais6,
    Ascii7,
    /// engine-spec v0.22: 8 bits, NUL and 32–126
    Ascii8,
}

impl CharSet {
    /// bits per character
    pub fn width(&self) -> u32 {
        match self {
            CharSet::Icao6 | CharSet::Ais6 => 6,
            CharSet::Ascii7 => 7,
            CharSet::Ascii8 => 8,
        }
    }
    /// the code of the padding character
    #[cfg(feature = "bits")]
    fn pad(&self) -> u32 {
        match self {
            CharSet::Icao6 => 32,
            CharSet::Ais6 | CharSet::Ascii7 | CharSet::Ascii8 => 0,
        }
    }
    /// code -> character; None for a code the set does not define. `ascii7`
    /// code 0 is NUL.
    #[cfg(feature = "bits")]
    fn char_of(&self, c: u32) -> Option<char> {
        match self {
            CharSet::Icao6 => match c {
                1..=26 => Some((b'A' + (c - 1) as u8) as char),
                32 => Some(' '),
                48..=57 => Some((b'0' + (c - 48) as u8) as char),
                _ => None,
            },
            CharSet::Ais6 => Some(if c < 32 { (c + 64) as u8 as char } else { c as u8 as char }),
            CharSet::Ascii7 | CharSet::Ascii8 => match c {
                0 => Some('\0'),
                32..=126 => Some(c as u8 as char),
                _ => None,
            },
        }
    }
    /// character -> code; None for a character the set cannot hold (NUL
    /// included, ruling 17 of 0.15)
    #[cfg(feature = "bits")]
    fn code_of(&self, ch: char) -> Option<u32> {
        let c = ch as u32;
        match self {
            CharSet::Icao6 => match ch {
                'A'..='Z' => Some(c - 'A' as u32 + 1),
                ' ' => Some(32),
                '0'..='9' => Some(c),
                _ => None,
            },
            CharSet::Ais6 => match c {
                64..=95 => Some(c - 64),
                32..=63 => Some(c),
                _ => None,
            },
            CharSet::Ascii7 | CharSet::Ascii8 => match c {
                32..=126 => Some(c),
                _ => None,
            },
        }
    }
}

/// The scale of `uscale` / `sscale`: a decimal factor, or a fraction
/// `num/den` (engine-spec v0.5, ruling 1), and an offset.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Scale {
    /// the factor, or the numerator of a fraction
    pub num: f64,
    /// the denominator when the factor was written `<num>/<den>`
    pub den: Option<f64>,
    pub offset: f64,
    /// `<places>` of `uscale` / `sscale` (engine-spec v0.55): the decoded
    /// value rounded to this many decimal places
    pub places: Option<u32>,
}

impl Scale {
    /// Ruling 4d of 0.11: the factor is number text and not zero, or
    /// `<num>/<den>` of two unsigned decimal integers, neither zero; the
    /// offset is number text.
    fn parse(args: &str) -> Option<Scale> {
        Scale::parse_places(args, false)
    }
    /// As `parse`; with `places`, a third argument `<places>` is allowed: a
    /// decimal integer (2c of 0.11) from 0 to 15 (engine-spec v0.55).
    fn parse_places(args: &str, places: bool) -> Option<Scale> {
        let parts: Vec<&str> = args.split(':').collect();
        if parts.is_empty() || parts.len() > if places { 3 } else { 2 } {
            return None;
        }
        let places = match parts.get(2) {
            Some(s) => Some(unsigned_text(s).filter(|n| *n <= 15)? as u32),
            None => None,
        };
        let offset = match parts.get(1) {
            Some(s) => number_text(s)?,
            None => 0.0,
        };
        let int = |s: &str| -> Option<f64> { unsigned_text(s).filter(|n| *n != 0).map(|_| s.parse::<f64>().ok()).flatten() };
        let (num, den) = match parts[0].split_once('/') {
            Some((n, d)) => (int(n)?, Some(int(d)?)),
            None => (number_text(parts[0]).filter(|x| *x != 0.0)?, None),
        };
        Some(Scale { num, den, offset, places })
    }
    /// `<places>` applied to a decoded value `x` (engine-spec v0.55, steps 1
    /// to 4): `round(x * p) / p` when that is finite and below 10^15, else `x`.
    /// A non-finite `x` is the caller's `transform-decode` (ruling 5).
    #[cfg(any(feature = "bits", feature = "tlv"))]
    fn round_places(&self, x: f64) -> Result<f64, Error> {
        let Some(places) = self.places else { return Ok(x) };
        if !x.is_finite() {
            return err(format!("the scaled value {} is not finite", x));
        }
        let p = 10f64.powi(places as i32);
        let y = x * p;
        let r = y.round();
        if y.is_finite() && r.abs() < 1e15 {
            let v = r / p;
            Ok(if v == 0.0 { 0.0 } else { v })
        } else {
            Ok(x)
        }
    }
    /// `v * factor` (or `v * num / den`), then `+ offset`
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "tlv"))]
    fn decode(&self, v: f64) -> f64 {
        match self.den {
            Some(den) => v * self.num / den + self.offset,
            None => v * self.num + self.offset,
        }
    }
    /// `(x - offset) / factor` (or `(x - offset) * den / num`), before rounding
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "tlv"))]
    fn quotient(&self, x: f64) -> f64 {
        match self.den {
            Some(den) => (x - self.offset) * den / self.num,
            None => (x - self.offset) / self.num,
        }
    }
}

impl Transform {
    fn parse(name: &str) -> Result<Transform, Error> {
        // ruling 5 of 0.11: the name is the text before the first `:`
        let head = name.split(':').next().unwrap_or("");
        const NAMES: &[&str] = &[
            "string", "float", "int", "iso8601_ms", "iso8601_short", "iso8601_si", "uint", "twos", "linscale", "pstring", "pvarint", "psint", "pdouble",
            "pfloat", "bool", "uscale", "sscale", "f32", "f64", "ascii", "sixbit", "dec", "dm", "hms", "hms_dmy", "utf8", "hex",
            // engine-spec v0.15
            "uiscale", "siscale", "smag", "smscale", "f32scale", "f64scale", "chars", "octal", "scale", "iscale",
        ];
        if !NAMES.contains(&head) {
            return err(format!("unknown-transform: `{}` is not a transform", head));
        }
        let params = |what: &str| err(format!("bad-directive: the parameters of transform `{}` are not valid: {}", name, what));
        if head == "linscale" {
            // ruling 4d of 0.11: exactly <maxpos>:<range>
            let args: Vec<&str> = name.split(':').skip(1).collect();
            if args.len() != 2 {
                return params("`linscale:<maxpos>:<range>` takes two");
            }
            let maxpos = match unsigned_text(args[0]) {
                Some(m) if m >= 1 => m as f64,
                _ => return params("<maxpos> is an unsigned decimal integer of at least 1"),
            };
            return match number_text(args[1]) {
                Some(r) if r != 0.0 => Ok(Transform::Linscale(maxpos, r)),
                _ => params("<range> is number text and not zero"),
            };
        }
        if let Some(t) = Transform::parse_text(name) {
            return t;
        }
        // factor and offset read as `sscale` reads them
        type Float = fn(Scale) -> Transform;
        let floats: [(&str, Float); 6] = [
            ("uscale", Transform::Uscale),
            ("sscale", Transform::Sscale),
            ("smscale", Transform::Smscale),
            ("f32scale", Transform::F32scale),
            ("f64scale", Transform::F64scale),
            ("scale", Transform::TextScale),
        ];
        for (prefix, make) in floats {
            if head == prefix {
                // engine-spec v0.55: `<places>` on `uscale` and `sscale` only
                let places = matches!(prefix, "uscale" | "sscale");
                return match name.strip_prefix(prefix).and_then(|a| a.strip_prefix(':')).and_then(|a| Scale::parse_places(a, places)) {
                    Some(sc) => Ok(make(sc)),
                    None => params("<factor>[:<offset>]: the factor is number text and not zero, or <num>/<den>"),
                };
            }
        }
        // exact factor and offset (engine-spec v0.15, Exact factors)
        type Int = fn(Exact) -> Transform;
        let ints: [(&str, Int); 3] =
            [("uiscale", Transform::Uiscale), ("siscale", Transform::Siscale), ("iscale", Transform::TextIscale)];
        for (prefix, make) in ints {
            if head == prefix {
                return match name.strip_prefix(prefix).and_then(|a| a.strip_prefix(':')).and_then(Exact::parse) {
                    Some(ex) => Ok(make(ex)),
                    None => params(
                        "<factor>[:<offset>]: an exact factor in lowest terms of at most 2^32 over 2^32 and an integer offset below 2^63",
                    ),
                };
            }
        }
        if head == "chars" {
            return match name.strip_prefix("chars:") {
                Some("icao6") => Ok(Transform::Chars(CharSet::Icao6)),
                Some("ais6") => Ok(Transform::Chars(CharSet::Ais6)),
                Some("ascii7") => Ok(Transform::Chars(CharSet::Ascii7)),
                Some("ascii8") => Ok(Transform::Chars(CharSet::Ascii8)),
                Some(other) => err(format!("bad-directive: unknown character set `{}`", other)),
                None => err(format!("bad-directive: `{}` needs a parameter", name)),
            };
        }
        if name.contains(':') {
            return params("this transform takes none");
        }
        match name {
            "smag" => Ok(Transform::Smag),
            "octal" => Ok(Transform::Octal),
            "hex" => Ok(Transform::Hex),
            "bool" => Ok(Transform::Bool),
            "f32" => Ok(Transform::F32),
            "f64" => Ok(Transform::F64),
            "ascii" => Ok(Transform::Ascii),
            "sixbit" => Ok(Transform::Sixbit),
            "string" => Ok(Transform::StringT),
            "float" => Ok(Transform::Float),
            "int" => Ok(Transform::Int),
            "iso8601_ms" => Ok(Transform::Iso8601Ms),
            "iso8601_short" => Ok(Transform::Iso8601Short),
            "iso8601_si" => Ok(Transform::Iso8601Si),
            "uint" => Ok(Transform::Uint),
            "twos" => Ok(Transform::Twos),
            "pstring" => Ok(Transform::Pstring),
            "pvarint" => Ok(Transform::Pvarint),
            "psint" => Ok(Transform::Psint),
            "pdouble" => Ok(Transform::Pdouble),
            "pfloat" => Ok(Transform::Pfloat),
            "utf8" => Ok(Transform::Utf8),
            other => err(format!("unknown-transform: `{}` is not a transform", other)),
        }
    }

    /// The transforms of the text wire (engine-spec v0.10), with their
    /// parameters. None when `name` is none of them.
    fn parse_text(name: &str) -> Option<Result<Transform, Error>> {
        let (head, args) = name.split_once(':').unwrap_or((name, ""));
        if !matches!(head, "int" | "dec" | "dm" | "hms" | "hms_dmy") || (head == "int" && !name.contains(':')) {
            return None;
        }
        let args: Vec<&str> = if name.contains(':') { args.split(':').collect() } else { Vec::new() };
        // a parameter: decimal digits within its range
        let n = |s: &str, lo: u32, hi: u32| -> Option<u32> {
            if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            s.parse::<u32>().ok().filter(|v| (lo..=hi).contains(v))
        };
        let t = match (head, args.as_slice()) {
            ("int", [w]) => n(w, 1, 20).map(Transform::IntW),
            ("dec", [f]) => n(f, 0, 9).map(|f| Transform::Dec(f, 0)),
            ("dec", [f, w]) => n(f, 0, 9).zip(n(w, 1, 20)).map(|(f, w)| Transform::Dec(f, w)),
            ("dm", [d, f, pn]) => {
                let pn = pn.as_bytes();
                let letters = pn.len() == 2 && pn[0] != pn[1] && pn.iter().all(|c| c.is_ascii_uppercase());
                n(d, 1, 3).zip(n(f, 0, 9)).filter(|_| letters).map(|(d, f)| Transform::Dm(d, f, pn[0], pn[1]))
            }
            ("hms", [f]) => n(f, 0, 3).map(Transform::Hms),
            ("hms_dmy", [f]) => n(f, 0, 3).map(Transform::HmsDmy),
            _ => None,
        };
        Some(t.ok_or(Error { msg: format!("bad-directive: the parameters of transform `{}` are not valid", name) }))
    }

    /// True for the transforms only the text wire accepts.
    fn is_text_only(&self) -> bool {
        matches!(self, Transform::IntW(_) | Transform::Dec(_, _) | Transform::Dm(..) | Transform::Hms(_) | Transform::HmsDmy(_))
    }

    /// The shared-model type this transform yields (spec/shared-model.md).
    pub fn value_type(&self) -> KeyType {
        match self {
            Transform::StringT
            | Transform::Pstring
            | Transform::Ascii
            | Transform::Sixbit
            | Transform::Utf8
            | Transform::Hex
            | Transform::Chars(_)
            | Transform::Octal => KeyType::Str,
            Transform::Dec(_, _) | Transform::Dm(..) | Transform::Hms(_) => KeyType::Float,
            Transform::IntW(_) | Transform::HmsDmy(_) => KeyType::Int,
            Transform::Float
            | Transform::Smscale(_)
            | Transform::F32scale(_)
            | Transform::F64scale(_)
            | Transform::TextScale(_)
            | Transform::Linscale(_, _)
            | Transform::Uscale(_)
            | Transform::Sscale(_)
            | Transform::F32
            | Transform::F64
            | Transform::Pdouble
            | Transform::Pfloat => KeyType::Float,
            Transform::Int
            | Transform::Bool
            | Transform::Iso8601Ms
            | Transform::Iso8601Short
            | Transform::Iso8601Si
            | Transform::Uint
            | Transform::Twos
            | Transform::Pvarint
            | Transform::Psint
            | Transform::Uiscale(_)
            | Transform::Siscale(_)
            | Transform::Smag
            | Transform::TextIscale(_) => KeyType::Int,
        }
    }

    /// True for the transforms a `bits` wire accepts.
    fn is_bits(&self) -> bool {
        matches!(
            self,
            Transform::Uint
                | Transform::Twos
                | Transform::Linscale(_, _)
                | Transform::Uscale(_)
                | Transform::Sscale(_)
                | Transform::F32
                | Transform::F64
                | Transform::Ascii
                | Transform::Sixbit
                | Transform::Uiscale(_)
                | Transform::Siscale(_)
                | Transform::Smag
                | Transform::Smscale(_)
                | Transform::F32scale(_)
                | Transform::F64scale(_)
                | Transform::Chars(_)
                | Transform::Octal
                | Transform::Hex
                // engine-spec v0.55
                | Transform::Utf8
        )
    }

    /// True for the scales of the text wires (engine-spec v0.15).
    fn is_text_scale(&self) -> bool {
        matches!(self, Transform::TextScale(_) | Transform::TextIscale(_))
    }

    /// The bit lengths a `bits` transform allows (engine-spec v0.5, v0.15).
    fn bits_len_ok(&self, len: u32) -> bool {
        match self {
            Transform::F32 | Transform::F32scale(_) => len == 32,
            Transform::F64 | Transform::F64scale(_) => len == 64,
            Transform::Ascii | Transform::Utf8 => len % 8 == 0 && (8..=2040).contains(&len),
            Transform::Sixbit => armor::sixbit_len_ok(len as u64),
            Transform::Chars(set) => len % set.width() == 0 && (set.width()..=2040).contains(&len),
            Transform::Octal => len % 3 == 0 && (3..=63).contains(&len),
            Transform::Hex => len % 4 == 0 && (4..=2040).contains(&len),
            Transform::Smag | Transform::Smscale(_) => (2..=64).contains(&len),
            _ => (1..=64).contains(&len),
        }
    }

    /// True for the transforms that take no `swap` (ruling 0.15).
    fn refuses_swap(&self) -> bool {
        matches!(self, Transform::Chars(_) | Transform::Octal | Transform::Hex)
    }

    fn is_protobuf(&self) -> bool {
        matches!(
            self,
            Transform::Pstring | Transform::Pvarint | Transform::Psint | Transform::Pdouble | Transform::Pfloat
        )
    }

    /// bits wire: raw unsigned field value + bit length -> model value
    /// (every bits transform but `ascii`, which the codec reads byte by byte)
    #[cfg(any(feature = "bits", feature = "tlv"))]
    fn decode_bits(&self, raw: u64, len: u32) -> Result<Value, Error> {
        // the sign extended from the field's highest bit, at every len from 1 to 64 (4c)
        let signed = |raw: u64, len: u32| -> i64 { ((raw << (64 - len)) as i64) >> (64 - len) };
        match self {
            Transform::Uint => Ok(Value::I64(raw as i64)),
            Transform::Twos => Ok(Value::I64(signed(raw, len))),
            Transform::Linscale(maxpos, range) => {
                Ok(Value::F64(signed(raw, len) as f64 / maxpos * range))
            }
            Transform::Uscale(sc) => Ok(Value::F64(sc.round_places(sc.decode(raw as f64))?)),
            Transform::Sscale(sc) => Ok(Value::F64(sc.round_places(sc.decode(signed(raw, len) as f64))?)),
            Transform::F32 => finite(f32::from_bits(raw as u32) as f64),
            Transform::F64 => finite(f64::from_bits(raw)),
            Transform::Uiscale(ex) => ex
                .decode(raw as i128)
                .map(Value::I64)
                .ok_or(Error { msg: format!("{} scaled is outside the signed 64-bit range", raw) }),
            Transform::Siscale(ex) => ex
                .decode(signed(raw, len) as i128)
                .map(Value::I64)
                .ok_or(Error { msg: format!("{} scaled is outside the signed 64-bit range", signed(raw, len)) }),
            Transform::Smag => Ok(Value::I64(smag(raw, len))),
            Transform::Smscale(sc) => finite(sc.decode(smag(raw, len) as f64)),
            Transform::F32scale(sc) => finite(sc.decode(f32::from_bits(raw as u32) as f64)),
            Transform::F64scale(sc) => finite(sc.decode(f64::from_bits(raw))),
            Transform::Octal => Ok(Value::Str(format!("{:0w$o}", raw, w = (len / 3) as usize))),
            _ => err(format!("transform {:?} is not valid on a bits wire", self)),
        }
    }

    /// bits wire: model value -> raw unsigned field value masked to bit length
    /// Ruling 4b of 0.11: a value outside the field's range is refused, never
    /// wrapped or clamped; the range is compared before any narrowing.
    #[cfg(any(feature = "bits", feature = "tlv"))]
    fn encode_bits(&self, v: &Value, len: u32) -> Result<u64, Error> {
        let mask = if len >= 64 { u64::MAX } else { (1u64 << len) - 1 };
        // 2^len and 2^(len-1) are exact in f64 for every len in 1..=64
        let two = |n: u32| (2.0f64).powi(n as i32);
        let unsigned_fits = |n: i128| n >= 0 && n <= mask as i128;
        let signed_fits = |n: i128| n >= -(1i128 << (len - 1)) && n < (1i128 << (len - 1));
        // a rounded quotient: finite, and within the range (as a double, exactly)
        let rounded = |q: f64, signed: bool| -> Result<u64, Error> {
            if !q.is_finite() {
                return err(format!("the quotient {} is not finite", q));
            }
            // f64::round: the nearest integer, halfway away from zero, exact (4a)
            let r = q.round();
            let ok = if signed { r >= -two(len - 1) && r < two(len - 1) } else { r >= 0.0 && r < two(len) };
            if !ok {
                return err(format!(
                    "{} rounds to {}, outside the {}-bit {} range of the field",
                    q,
                    r,
                    len,
                    if signed { "signed" } else { "unsigned" }
                ));
            }
            Ok(if signed { (r as i64 as u64) & mask } else { r as u64 })
        };
        match (self, v) {
            // `uint` of 64 bits: every model integer, as its two's-complement pattern
            (Transform::Uint, Value::I64(n)) if len == 64 => Ok(*n as u64),
            (Transform::Uint, Value::I64(n)) => {
                if !unsigned_fits(*n as i128) {
                    return err(format!("{} is outside the {}-bit unsigned range of the field", n, len));
                }
                Ok(*n as u64)
            }
            (Transform::Twos, Value::I64(n)) => {
                if !signed_fits(*n as i128) {
                    return err(format!("{} is outside the {}-bit signed range of the field", n, len));
                }
                Ok((*n as u64) & mask)
            }
            (Transform::Linscale(maxpos, range), Value::F64(x)) => rounded(x / range * maxpos, true),
            (Transform::Uscale(sc), Value::F64(x)) => rounded(sc.quotient(*x), false),
            (Transform::Sscale(sc), Value::F64(x)) => rounded(sc.quotient(*x), true),
            (Transform::F32, Value::F64(x)) => Ok(single(*x)?.to_bits() as u64),
            (Transform::F64, Value::F64(x)) => Ok(finite(*x)?.as_f64().to_bits()),
            (Transform::Uiscale(ex), Value::I64(x)) => {
                let r = ex.encode(*x);
                if !(r >= 0 && r < 1i128 << len) {
                    return err(format!("{} scales to {}, outside the {}-bit unsigned range of the field", x, r, len));
                }
                Ok(r as u64)
            }
            (Transform::Siscale(ex), Value::I64(x)) => {
                let r = ex.encode(*x);
                let half = 1i128 << (len - 1);
                if !(r >= -half && r < half) {
                    return err(format!("{} scales to {}, outside the {}-bit signed range of the field", x, r, len));
                }
                Ok((r as i64 as u64) & mask)
            }
            (Transform::Smag, Value::I64(x)) => to_smag(*x < 0, x.unsigned_abs() as f64, x.unsigned_abs(), len),
            (Transform::Smscale(sc), Value::F64(x)) => {
                let r = sc.quotient(*x).round();
                if !r.is_finite() || r.abs() >= two(len - 1) {
                    return err(format!("{} scales to a magnitude outside the {} bits of the field", x, len - 1));
                }
                // the sign of the integer after rounding: -0 writes sign 0 (ruling 15)
                to_smag(r < 0.0, r.abs(), r.abs() as u64, len)
            }
            (Transform::F32scale(sc), Value::F64(x)) => Ok(single(sc.quotient(*x))?.to_bits() as u64),
            (Transform::F64scale(sc), Value::F64(x)) => Ok(finite(sc.quotient(*x))?.as_f64().to_bits()),
            (Transform::Octal, Value::Str(s)) => {
                if s.len() != (len / 3) as usize || !s.bytes().all(|b| (b'0'..=b'7').contains(&b)) {
                    return err(format!("`{}` is not {} octal digits", s, len / 3));
                }
                u64::from_str_radix(s, 8).map_err(|_| Error { msg: format!("`{}` is not octal", s) })
            }
            _ => err(format!("transform/value mismatch on bits: {:?} with {:?}", self, v)),
        }
    }
    /// wire string -> model value
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json"))]
    fn decode(&self, raw: &str) -> Result<Value, Error> {
        match self {
            Transform::StringT => Ok(Value::Str(raw.to_string())),
            // rulings 2a, 2b and 1n of 0.11: no trimming, the grammars exactly
            Transform::Float => number_text(raw)
                .map(Value::F64)
                .ok_or(Error { msg: format!("float decode failed: `{}` is not number text", raw) }),
            Transform::Int => int_text(raw)
                .map(Value::I64)
                .ok_or(Error { msg: format!("int decode failed: `{}` is not integer text", raw) }),
            Transform::Iso8601Ms | Transform::Iso8601Short | Transform::Iso8601Si => iso8601_to_ms(raw).map(Value::I64),
            Transform::TextScale(sc) => match Transform::Float.decode(raw)? {
                Value::F64(v) => finite(sc.decode(v)),
                other => err(format!("scale decode failed: {:?}", other)),
            },
            Transform::TextIscale(ex) => ex.decode_text(raw).map(Value::I64).ok_or(Error {
                msg: format!("`{}` is not a number text with an exponent of at most 400 that scales into the signed 64-bit range", raw),
            }),
            t if t.is_bits() => err(format!("transform {:?} is only valid on a bits wire", self)),
            t if t.is_protobuf() => {
                err(format!("transform {:?} is only valid on a protobuf wire", self))
            }
            _ => err(format!("transform {:?} not valid on a text wire", self)),
        }
    }
    /// model value -> wire string
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json"))]
    fn encode(&self, v: &Value) -> Result<String, Error> {
        match (self, v) {
            (Transform::StringT, Value::Str(s)) => Ok(s.clone()),
            (Transform::Float, Value::F64(x)) => Ok(fmt_f64(*x)),
            (Transform::Int, Value::I64(n)) => Ok(n.to_string()),
            (Transform::Iso8601Ms, Value::I64(ms)) => ms_to_iso8601_checked(*ms),
            (Transform::Iso8601Short, Value::I64(ms)) => ms_to_iso8601_short(*ms),
            (Transform::Iso8601Si, Value::I64(ms)) => ms_to_iso8601_si(*ms),
            (Transform::TextScale(sc), Value::F64(x)) => Ok(fmt_f64(text_unscale(sc, *x)?)),
            (Transform::TextIscale(ex), Value::I64(x)) => ex
                .encode_decimal(*x)
                .ok_or(Error { msg: format!("{} unscaled does not terminate within 18 fraction digits", x) }),
            _ => err(format!("transform/value mismatch: {:?} with {:?}", self, v)),
        }
    }
    /// protobuf wire: a leaf field's wire value -> model value
    #[cfg(feature = "protobuf")]
    fn decode_pb(&self, v: &protobuf::WireVal) -> Result<Value, Error> {
        use protobuf::WireVal::*;
        match (self, v) {
            (Transform::Pstring, LenDelim(b)) => Ok(Value::Str(
                String::from_utf8(b.clone()).map_err(|_| Error { msg: "pstring: invalid utf8".into() })?,
            )),
            (Transform::Pvarint, Varint(u)) => Ok(Value::I64(*u as i64)),
            (Transform::Psint, Varint(u)) => Ok(Value::I64(((*u >> 1) as i64) ^ -((*u & 1) as i64))),
            (Transform::Pdouble, Fixed64(u)) => finite(f64::from_bits(*u)),
            (Transform::Pfloat, Fixed32(u)) => finite(f32::from_bits(*u) as f64),
            _ => err(format!("protobuf transform {:?} does not match wire value", self)),
        }
    }
    /// protobuf wire: model value -> a leaf field's wire value
    #[cfg(feature = "protobuf")]
    fn encode_pb(&self, v: &Value) -> Result<protobuf::WireVal, Error> {
        use protobuf::WireVal::*;
        match (self, v) {
            (Transform::Pstring, Value::Str(s)) => Ok(LenDelim(s.clone().into_bytes())),
            (Transform::Pvarint, Value::I64(n)) => Ok(Varint(*n as u64)),
            (Transform::Psint, Value::I64(n)) => Ok(Varint(((*n << 1) ^ (*n >> 63)) as u64)),
            (Transform::Pdouble, Value::F64(x)) => Ok(Fixed64(finite(*x)?.as_f64().to_bits())),
            (Transform::Pfloat, Value::F64(x)) => Ok(Fixed32(single(*x)?.to_bits())),
            _ => err(format!("protobuf transform/value mismatch: {:?} with {:?}", self, v)),
        }
    }

    /// The JSON kind this transform produces, so a JSON wire emits it correctly.
    #[cfg(feature = "geojson")]
    fn json_kind(&self) -> JsonKind {
        match self {
            Transform::StringT
            | Transform::Iso8601Ms
            | Transform::Iso8601Short
            | Transform::Iso8601Si
            | Transform::Pstring
            | Transform::Ascii
            | Transform::Sixbit
            | Transform::Utf8
            | Transform::Hex
            | Transform::Chars(_)
            | Transform::Octal => JsonKind::StringK,
            Transform::TextIscale(_) => JsonKind::ExactK,
            Transform::Float
            | Transform::TextScale(_)
            | Transform::Smscale(_)
            | Transform::F32scale(_)
            | Transform::F64scale(_)
            | Transform::Linscale(_, _)
            | Transform::Uscale(_)
            | Transform::Sscale(_)
            | Transform::F32
            | Transform::F64
            | Transform::Pdouble
            | Transform::Pfloat => JsonKind::NumK,
            Transform::Int
            | Transform::Bool
            | Transform::Uint
            | Transform::Twos
            | Transform::Pvarint
            | Transform::Psint
            | Transform::Uiscale(_)
            | Transform::Siscale(_)
            | Transform::Smag => JsonKind::IntK,
            Transform::Dec(_, _) | Transform::Dm(..) | Transform::Hms(_) => JsonKind::NumK,
            Transform::IntW(_) | Transform::HmsDmy(_) => JsonKind::IntK,
        }
    }
}

/// Integer text (ruling 2a of 0.11): an optional `-`, then one or more ASCII
/// digits, within a signed 64-bit integer. Leading zeros are allowed.
pub fn int_text(s: &str) -> Option<i64> {
    let digits = s.strip_prefix('-').unwrap_or(s);
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    s.parse::<i64>().ok()
}

/// Number text (ruling 2b of 0.11): an optional `-`, digits, optionally `.`
/// and digits, optionally `e` or `E`, an optional sign and digits. The value
/// is the nearest double, a tie to even; a text whose nearest double is
/// infinite is refused; `-0` is negative zero.
pub fn number_text(s: &str) -> Option<f64> {
    let b = s.as_bytes();
    let mut i = 0;
    if b.first() == Some(&b'-') {
        i += 1;
    }
    let digits = |i: &mut usize| {
        let at = *i;
        while *i < b.len() && b[*i].is_ascii_digit() {
            *i += 1;
        }
        *i > at
    };
    if !digits(&mut i) {
        return None;
    }
    if b.get(i) == Some(&b'.') {
        i += 1;
        if !digits(&mut i) {
            return None;
        }
    }
    if matches!(b.get(i), Some(b'e') | Some(b'E')) {
        i += 1;
        if matches!(b.get(i), Some(b'+') | Some(b'-')) {
            i += 1;
        }
        if !digits(&mut i) {
            return None;
        }
    }
    if i != b.len() {
        return None;
    }
    // the standard library's reading is correctly rounded, ties to even
    s.parse::<f64>().ok().filter(|x| x.is_finite())
}

/// An unsigned decimal integer (ruling 2c of 0.11): one or more ASCII digits
/// and nothing else, leading zeros allowed.
pub fn unsigned_text(s: &str) -> Option<u64> {
    if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    // more digits than fit: a value beyond every width
    Some(s.parse::<u64>().unwrap_or(u64::MAX))
}

/// The `smag` value of the low `len` bits of `raw`: the top bit the sign,
/// 1 negative; sign 1 with magnitude 0 is 0.
#[cfg(any(feature = "bits", feature = "tlv"))]
fn smag(raw: u64, len: u32) -> i64 {
    let mag = (raw & ((1u64 << (len - 1)) - 1)) as i64;
    if (raw >> (len - 1)) & 1 == 1 {
        -mag
    } else {
        mag
    }
}

/// Sign and magnitude in `len` bits; the magnitude must be below 2^(len-1).
#[cfg(any(feature = "bits", feature = "tlv"))]
fn to_smag(neg: bool, mag_f: f64, mag: u64, len: u32) -> Result<u64, Error> {
    let room = 1u64 << (len - 1);
    if mag_f >= room as f64 || mag >= room {
        return err(format!("magnitude {} does not fit {} bits", mag, len - 1));
    }
    // 0 is written with sign 0
    Ok(if neg && mag != 0 { room | mag } else { mag })
}

/// `scale` encode on a text wire: `(x - offset) / factor`, not rounded, and
/// finite (ruling 14 of 0.15).
#[cfg(any(feature = "xml", feature = "geojson", feature = "json"))]
fn text_unscale(sc: &Scale, x: f64) -> Result<f64, Error> {
    let y = sc.quotient(x);
    if y.is_finite() {
        Ok(y)
    } else {
        err(format!("{} unscaled is not a finite number", x))
    }
}

/// A float read from the wire: not-a-number and infinity are refused
/// (ruling 23 of 0.5, extended in 0.6).
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
fn finite(x: f64) -> Result<Value, Error> {
    if x.is_finite() {
        Ok(Value::F64(x))
    } else {
        err(format!("{} is not a finite number", x))
    }
}

/// A model float narrowed to a single: outside single range is refused.
#[cfg(any(feature = "bits", feature = "protobuf", feature = "tlv"))]
fn single(x: f64) -> Result<f32, Error> {
    let y = x as f32;
    if y.is_finite() {
        Ok(y)
    } else {
        err(format!("{} is outside the range of a single", x))
    }
}

#[cfg(feature = "geojson")]
enum JsonKind {
    StringK,
    NumK,
    IntK,
    /// the text is an exact decimal, written as a number as it is
    ExactK,
}

// ---------------------------------------------------------------------------
// Model modules (engine-spec v0.4)
// ---------------------------------------------------------------------------

/// The type of a shared-model key.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum KeyType {
    Str,
    Float,
    Int,
}
impl KeyType {
    fn parse(s: &str) -> Option<KeyType> {
        match s {
            "string" => Some(KeyType::Str),
            "float" => Some(KeyType::Float),
            "int" => Some(KeyType::Int),
            _ => None,
        }
    }
    pub fn name(&self) -> &'static str {
        match self {
            KeyType::Str => "string",
            KeyType::Float => "float",
            KeyType::Int => "int",
        }
    }
}

/// How far a module or pack may be distributed. Ordered: Public < Controlled.
#[derive(Clone, Copy, Debug, PartialEq, PartialOrd)]
pub enum Distribution {
    Public,
    Controlled,
}
impl Distribution {
    pub fn parse(s: &str) -> Option<Distribution> {
        match s {
            "public" => Some(Distribution::Public),
            "controlled" => Some(Distribution::Controlled),
            _ => None,
        }
    }
    pub fn name(&self) -> &'static str {
        match self {
            Distribution::Public => "public",
            Distribution::Controlled => "controlled",
        }
    }
}

#[derive(Clone, Debug)]
pub struct KeyDef {
    pub name: String,
    pub ty: KeyType,
    pub unit: String,
    pub meaning: String,
}

/// One model module: a named set of typed keys (`model/<module>.def`).
#[derive(Clone, Debug)]
pub struct Module {
    pub name: String,
    pub version: String,
    pub distribution: Distribution,
    pub sources: Vec<String>,
    pub keys: Vec<KeyDef>,
    /// `list` lines: (name, meaning) (engine-spec v0.7)
    pub lists: Vec<(String, String)>,
    /// `derive` lines, in file order (engine-spec v0.6)
    pub derives: Vec<DeriveDef>,
    /// `uses` lines: the modules whose keys a `derive` line may take as arguments (engine-spec v0.8)
    pub uses: Vec<String>,
}

/// The function of a `derive` line.
#[derive(Clone, Debug, PartialEq)]
pub enum DeriveFn {
    Copy,
    Hypot,
    Bearing,
    EastOf,
    NorthOf,
    Neg,
    Scale(Scale),
    /// the number as written, for a float and for an int target
    Offset(f64, Option<i64>),
    Join(String),
    /// seconds since UTC midnight of an instant in epoch ms (engine-spec v0.8)
    DaySeconds,
    /// 1 when any present argument is not 0
    Any,
    Not,
    ParseInt,
    TextOf,
    /// 1 when its one argument is held by the entity, whatever its value (engine-spec 0.12)
    Present,
    /// engine-spec v0.16: an instant in ms as seconds and nanoseconds, and back
    SecOf,
    NsecOf,
    MsOf,
    Deg,
    Rad,
    Add,
    Sub,
    /// engine-spec v0.16: a distance and an angle at a latitude, on WGS 84
    DegLatOf,
    DegLonOf,
    MLatOf,
    MLonOf,
    /// engine-spec v0.16: geodetic to Earth-centred, Earth-fixed, and back
    EcefX,
    EcefY,
    EcefZ,
    LatOfEcef,
    LonOfEcef,
    HaeOfEcef,
    /// engine-spec v0.18: the tokens whose argument is present and not 0, joined
    Tokens(char, Vec<String>),
    /// engine-spec v0.18: 1 when the token is one of the parts of the text
    HasToken(char, String),
    /// engine-spec v0.18: the text when the argument is not 0
    TextIf(String),
}

/// Whitespace in a derive parameter (engine-spec v0.18): space, tab, line
/// feed and carriage return only.
fn pack_space(c: char) -> bool {
    matches!(c, ' ' | '\t' | '\n' | '\r')
}

/// The `<sep>` of `tokens` and `has_token` (engine-spec v0.18): one
/// character other than `:`, `,` or whitespace, or `space`, `comma`, `colon`.
fn token_sep(text: &str) -> Option<char> {
    match text {
        "space" => return Some(' '),
        "comma" => return Some(','),
        "colon" => return Some(':'),
        _ => {}
    }
    let mut cs = text.chars();
    match (cs.next(), cs.next()) {
        (Some(c), None) if c != ':' && c != ',' && !pack_space(c) => Some(c),
        _ => None,
    }
}

/// A token of `tokens` and `has_token`: one or more characters other than
/// `:`, `,`, whitespace and the separator.
fn token_ok(t: &str, sep: char) -> bool {
    !t.is_empty() && t.chars().all(|c| c != ':' && c != ',' && c != sep && !pack_space(c))
}

/// One `derive` line: the target key follows from the argument keys.
#[derive(Clone, Debug)]
pub struct DeriveDef {
    pub target: String,
    pub func: DeriveFn,
    pub args: Vec<String>,
    pub line: usize,
}

impl DeriveFn {
    fn parse(name: &str) -> Option<DeriveFn> {
        if let Some(a) = name.strip_prefix("scale:") {
            if a.contains(':') {
                return None;
            }
            // ruling 2c of 0.11: number text, or <num>/<den> with <num> integer
            // text and <den> an unsigned decimal integer that is not zero
            return match a.split_once('/') {
                Some((n, d)) => {
                    let num = int_text(n)? as f64;
                    let den = unsigned_text(d).filter(|v| *v != 0).and_then(|_| d.parse::<f64>().ok())?;
                    Some(DeriveFn::Scale(Scale { num, den: Some(den), offset: 0.0, places: None }))
                }
                None => Scale::parse(a).map(DeriveFn::Scale),
            };
        }
        if let Some(a) = name.strip_prefix("offset:") {
            return match read_as(KeyType::Float, a) {
                Some(Value::F64(x)) => Some(DeriveFn::Offset(x, int_text(a))),
                _ => None,
            };
        }
        if let Some(a) = name.strip_prefix("join:") {
            return Some(DeriveFn::Join(a.to_string()));
        }
        // engine-spec v0.18: a malformed parameter is `bad-directive`, as an unknown function is
        if let Some(a) = name.strip_prefix("tokens:") {
            let (sep, list) = a.split_once(':')?;
            let sep = token_sep(sep)?;
            let toks: Vec<String> = list.split(',').map(|t| t.to_string()).collect();
            if !toks.iter().all(|t| token_ok(t, sep)) {
                return None;
            }
            if toks.iter().enumerate().any(|(i, t)| toks[..i].contains(t)) {
                return None;
            }
            return Some(DeriveFn::Tokens(sep, toks));
        }
        if let Some(a) = name.strip_prefix("has_token:") {
            let (sep, t) = a.split_once(':')?;
            let sep = token_sep(sep)?;
            return if token_ok(t, sep) { Some(DeriveFn::HasToken(sep, t.to_string())) } else { None };
        }
        if let Some(a) = name.strip_prefix("text_if:") {
            return if !a.is_empty() && !a.chars().any(|c| pack_space(c)) {
                Some(DeriveFn::TextIf(a.to_string()))
            } else {
                None
            };
        }
        Some(match name {
            "copy" => DeriveFn::Copy,
            "hypot" => DeriveFn::Hypot,
            "bearing" => DeriveFn::Bearing,
            "east_of" => DeriveFn::EastOf,
            "north_of" => DeriveFn::NorthOf,
            "neg" => DeriveFn::Neg,
            "day_seconds" => DeriveFn::DaySeconds,
            "any" => DeriveFn::Any,
            "not" => DeriveFn::Not,
            "parse_int" => DeriveFn::ParseInt,
            "text_of" => DeriveFn::TextOf,
            "present" => DeriveFn::Present,
            "sec_of" => DeriveFn::SecOf,
            "nsec_of" => DeriveFn::NsecOf,
            "ms_of" => DeriveFn::MsOf,
            "deg" => DeriveFn::Deg,
            "rad" => DeriveFn::Rad,
            "add" => DeriveFn::Add,
            "sub" => DeriveFn::Sub,
            "deg_lat_of" => DeriveFn::DegLatOf,
            "deg_lon_of" => DeriveFn::DegLonOf,
            "m_lat_of" => DeriveFn::MLatOf,
            "m_lon_of" => DeriveFn::MLonOf,
            "ecef_x" => DeriveFn::EcefX,
            "ecef_y" => DeriveFn::EcefY,
            "ecef_z" => DeriveFn::EcefZ,
            "lat_of_ecef" => DeriveFn::LatOfEcef,
            "lon_of_ecef" => DeriveFn::LonOfEcef,
            "hae_of_ecef" => DeriveFn::HaeOfEcef,
            _ => return None,
        })
    }

    /// Does the function accept this many arguments of these types, for this target type?
    fn fits(&self, target: KeyType, args: &[KeyType]) -> bool {
        let floats = |n: usize| args.len() == n && target == KeyType::Float && args.iter().all(|t| *t == KeyType::Float);
        match self {
            DeriveFn::Copy => args.len() == 1 && args[0] == target,
            DeriveFn::Hypot | DeriveFn::Bearing | DeriveFn::EastOf | DeriveFn::NorthOf => floats(2),
            DeriveFn::Neg | DeriveFn::Scale(_) => floats(1),
            DeriveFn::Offset(_, int) => {
                floats(1) || (args.len() == 1 && target == KeyType::Int && args[0] == KeyType::Int && int.is_some())
            }
            DeriveFn::Join(_) => !args.is_empty() && target == KeyType::Str && args.iter().all(|t| *t == KeyType::Str),
            DeriveFn::DaySeconds => args.len() == 1 && args[0] == KeyType::Int && target == KeyType::Float,
            DeriveFn::Any => !args.is_empty() && target == KeyType::Int && args.iter().all(|t| *t == KeyType::Int),
            DeriveFn::Not => args.len() == 1 && args[0] == KeyType::Int && target == KeyType::Int,
            DeriveFn::ParseInt => args.len() == 1 && args[0] == KeyType::Str && target == KeyType::Int,
            DeriveFn::TextOf => args.len() == 1 && args[0] == KeyType::Int && target == KeyType::Str,
            // any scalar argument
            DeriveFn::Present => args.len() == 1 && target == KeyType::Int,
            // engine-spec v0.16, ruling 4: the types of the table, no promotion
            DeriveFn::SecOf | DeriveFn::NsecOf => args.len() == 1 && args[0] == KeyType::Int && target == KeyType::Int,
            DeriveFn::MsOf => args.len() == 2 && target == KeyType::Int && args.iter().all(|t| *t == KeyType::Int),
            DeriveFn::Deg | DeriveFn::Rad => floats(1),
            DeriveFn::Add | DeriveFn::Sub => {
                args.len() == 2
                    && (target == KeyType::Int || target == KeyType::Float)
                    && args.iter().all(|t| *t == target)
            }
            DeriveFn::DegLatOf | DeriveFn::DegLonOf | DeriveFn::MLatOf | DeriveFn::MLonOf => floats(2),
            DeriveFn::EcefX
            | DeriveFn::EcefY
            | DeriveFn::EcefZ
            | DeriveFn::LatOfEcef
            | DeriveFn::LonOfEcef
            | DeriveFn::HaeOfEcef => floats(3),
            DeriveFn::Tokens(_, toks) => {
                args.len() == toks.len() && target == KeyType::Str && args.iter().all(|t| *t == KeyType::Int)
            }
            DeriveFn::HasToken(_, _) => args.len() == 1 && args[0] == KeyType::Str && target == KeyType::Int,
            DeriveFn::TextIf(_) => args.len() == 1 && args[0] == KeyType::Int && target == KeyType::Str,
        }
    }

    /// The derived value; None leaves the target absent.
    fn apply(&self, a: &[&Value]) -> Option<Value> {
        // degrees to radians: pi/180 with pi the double nearest to it
        let rad = std::f64::consts::PI / 180.0;
        let x = |i: usize| a[i].as_f64();
        let v = match self {
            DeriveFn::Copy => return Some(a[0].clone()),
            DeriveFn::Join(sep) => {
                let parts: Vec<String> = a.iter().map(|v| v.as_display()).collect();
                return Some(Value::Str(parts.join(sep)));
            }
            DeriveFn::DaySeconds => match a[0] {
                Value::I64(ms) => return Some(Value::F64(ms.rem_euclid(86_400_000) as f64 / 1000.0)),
                _ => return None,
            },
            // `a` holds the arguments that are present
            DeriveFn::Any => return Some(Value::I64(a.iter().any(|v| !matches!(v, Value::I64(0))) as i64)),
            DeriveFn::Not => return Some(Value::I64(matches!(a[0], Value::I64(0)) as i64)),
            DeriveFn::ParseInt => match a[0] {
                // an optional `-`, then decimal digits
                Value::Str(t) if t.strip_prefix('-').unwrap_or(t).bytes().all(|b| b.is_ascii_digit()) => {
                    return t.parse::<i64>().ok().map(Value::I64)
                }
                _ => return None,
            },
            DeriveFn::TextOf => return Some(Value::Str(a[0].as_display())),
            DeriveFn::Present => return Some(Value::I64(1)),
            // `Engine::complete` computes `tokens`, whose arguments may be partly absent
            DeriveFn::Tokens(_, _) => return None,
            DeriveFn::HasToken(sep, t) => match a[0] {
                Value::Str(text) => {
                    return Some(Value::I64(text.split(*sep).any(|part| !part.is_empty() && part == t) as i64))
                }
                _ => return None,
            },
            DeriveFn::TextIf(text) => match a[0] {
                Value::I64(0) => return None,
                Value::I64(_) => return Some(Value::Str(text.clone())),
                _ => return None,
            },
            // engine-spec v0.16, ruling 3: exact integers, only the result range-checked
            DeriveFn::SecOf | DeriveFn::NsecOf | DeriveFn::MsOf => {
                let int = |i: usize| match a[i] {
                    Value::I64(n) => Some(*n as i128),
                    _ => None,
                };
                let r: i128 = match self {
                    DeriveFn::SecOf => int(0)?.div_euclid(1000),
                    DeriveFn::NsecOf => int(0)?.rem_euclid(1000) * 1_000_000,
                    _ => int(0)? * 1000 + int(1)?.div_euclid(1_000_000),
                };
                return i64::try_from(r).ok().map(Value::I64);
            }
            DeriveFn::Add | DeriveFn::Sub if matches!(a[0], Value::I64(_)) => match (a[0], a[1]) {
                (Value::I64(p), Value::I64(q)) => {
                    let r = if *self == DeriveFn::Add { p.checked_add(*q) } else { p.checked_sub(*q) };
                    return r.map(Value::I64);
                }
                _ => return None,
            },
            DeriveFn::Add => x(0) + x(1),
            DeriveFn::Sub => x(0) - x(1),
            DeriveFn::Deg => x(0) * (180.0 / std::f64::consts::PI),
            DeriveFn::Rad => x(0) * rad,
            DeriveFn::DegLatOf
            | DeriveFn::DegLonOf
            | DeriveFn::MLatOf
            | DeriveFn::MLonOf
            | DeriveFn::EcefX
            | DeriveFn::EcefY
            | DeriveFn::EcefZ
            | DeriveFn::LatOfEcef
            | DeriveFn::LonOfEcef
            | DeriveFn::HaeOfEcef => wgs84(self, x(0), x(1), a.get(2).map(|v| v.as_f64()).unwrap_or(0.0))?,
            DeriveFn::Offset(_, Some(n)) if matches!(a[0], Value::I64(_)) => match a[0] {
                Value::I64(k) => return k.checked_add(*n).map(Value::I64),
                _ => return None,
            },
            DeriveFn::Offset(n, _) => x(0) + n,
            DeriveFn::Hypot => (x(0) * x(0) + x(1) * x(1)).sqrt(),
            DeriveFn::Bearing => {
                if x(0) == 0.0 && x(1) == 0.0 {
                    return None;
                }
                // radians to degrees: times 180/pi, as the platform libraries do
                let mut d = x(0).atan2(x(1)) * (180.0 / std::f64::consts::PI);
                if d < 0.0 {
                    d += 360.0;
                }
                if d >= 360.0 {
                    d = 0.0;
                }
                d
            }
            DeriveFn::EastOf => x(0) * (x(1) * rad).sin(),
            DeriveFn::NorthOf => x(0) * (x(1) * rad).cos(),
            DeriveFn::Neg => -x(0),
            DeriveFn::Scale(sc) => match sc.den {
                Some(den) => x(0) * sc.num / den,
                None => x(0) * sc.num,
            },
        };
        if v.is_finite() {
            Some(Value::F64(v))
        } else {
            None
        }
    }
}

/// WGS 84 (engine-spec v0.16): the distance, angle and ECEF functions. None
/// leaves the target absent: a latitude outside [-90, 90], an intermediate
/// that is not finite (a division by zero, a square root of a negative
/// number), `G <= 0` near the centre (rulings 1, 2, 6).
fn wgs84(f: &DeriveFn, x0: f64, x1: f64, x2: f64) -> Option<f64> {
    use std::f64::consts::PI;
    const A: f64 = 6378137.0;
    const FL: f64 = 1.0 / 298.257223563;
    let e2 = FL * (2.0 - FL);
    let b = A * (1.0 - FL);
    let to_rad = PI / 180.0;
    let to_deg = 180.0 / PI;
    // every intermediate must be finite (ruling 1)
    let fin = |v: f64| if v.is_finite() { Some(v) } else { None };
    let lat_arg = |lat: f64| if (-90.0..=90.0).contains(&lat) { Some(lat * to_rad) } else { None };
    // prime vertical and meridional radii at phi
    let radii = |phi: f64| -> Option<(f64, f64)> {
        let s = phi.sin();
        let w = fin(1.0 - e2 * s * s)?;
        let n = fin(A / fin(w.sqrt())?)?;
        let m = fin(A * (1.0 - e2) / fin(w.powf(1.5))?)?;
        Some((n, m))
    };
    let v = match f {
        DeriveFn::DegLatOf | DeriveFn::DegLonOf | DeriveFn::MLatOf | DeriveFn::MLonOf => {
            let phi = lat_arg(x1)?;
            let (n, m) = radii(phi)?;
            let c = phi.cos().abs();
            match f {
                DeriveFn::DegLatOf => fin(x0 / m)? * to_deg,
                DeriveFn::DegLonOf => {
                    if c <= 1e-12 {
                        return None;
                    }
                    fin(x0 / fin(n * c)?)? * to_deg
                }
                DeriveFn::MLatOf => fin(fin(x0 * to_rad)? * m)?,
                _ => fin(fin(fin(x0 * to_rad)? * n)? * c)?,
            }
        }
        DeriveFn::EcefX | DeriveFn::EcefY | DeriveFn::EcefZ => {
            let phi = lat_arg(x0)?;
            let lam = fin(x1 * to_rad)?;
            let (n, _) = radii(phi)?;
            let hae = fin(x2)?;
            match f {
                DeriveFn::EcefX => fin(n + hae)? * phi.cos() * lam.cos(),
                DeriveFn::EcefY => fin(n + hae)? * phi.cos() * lam.sin(),
                _ => fin(n * (1.0 - e2) + hae)? * phi.sin(),
            }
        }
        DeriveFn::LonOfEcef => {
            let (x, y) = (fin(x0)?, fin(x1)?);
            fin(x2)?;
            if x == 0.0 && y == 0.0 {
                return None;
            }
            // (-180, 180]: 180 where atan2 gives -180 (ruling 5)
            let d = y.atan2(x) * to_deg;
            if d <= -180.0 {
                d + 360.0
            } else {
                d
            }
        }
        DeriveFn::LatOfEcef | DeriveFn::HaeOfEcef => {
            // Heikkinen's closed form, in the order the specification gives
            let (x, y, z) = (fin(x0)?, fin(x1)?, fin(x2)?);
            let (a2, b2) = (A * A, b * b);
            let e4 = e2 * e2;
            let p = fin(fin(x * x + y * y)?.sqrt())?;
            let ff = fin(54.0 * b2 * z * z)?;
            let g = fin(p * p + (1.0 - e2) * z * z - e2 * (a2 - b2))?;
            if g <= 0.0 {
                return None;
            }
            let c = fin(e4 * ff * p * p / fin(g * g * g)?)?;
            let s = fin(fin(1.0 + c + fin(fin(c * c + 2.0 * c)?.sqrt())?)?.cbrt())?;
            let k = fin(s + 1.0 + fin(1.0 / s)?)?;
            let pp = fin(ff / fin(3.0 * k * k * g * g)?)?;
            let q = fin(fin(1.0 + 2.0 * e4 * pp)?.sqrt())?;
            let inner = fin(a2 / 2.0 * (1.0 + 1.0 / q) - pp * (1.0 - e2) * z * z / fin(q * (1.0 + q))? - pp * p * p / 2.0)?;
            // ruling 9: 0 in exact arithmetic on the polar axis; a negative argument is taken as 0
            let inner = if inner < 0.0 { 0.0 } else { inner };
            let r0 = fin(-pp * e2 * p / fin(1.0 + q)? + fin(inner.sqrt())?)?;
            let d = fin(p - e2 * r0)?;
            let u = fin(fin(d * d + z * z)?.sqrt())?;
            let v = fin(fin(d * d + (1.0 - e2) * z * z)?.sqrt())?;
            let av = fin(A * v)?;
            let z0 = fin(b2 * z / av)?;
            if *f == DeriveFn::HaeOfEcef {
                fin(u * (1.0 - fin(b2 / av)?))?
            } else {
                fin(fin(z + (a2 - b2) / b2 * z0)?.atan2(p))? * to_deg
            }
        }
        _ => return None,
    };
    fin(v)
}

impl Module {
    pub fn parse(text: &str) -> Result<Module, Error> {
        Module::parse_with(text, &BTreeMap::new())
    }

    /// Parse a module. `loaded` holds the modules loaded so far: a `derive`
    /// line may name the keys of `core`, and as arguments the keys of the
    /// modules its own `uses` lines name (engine-spec v0.8).
    pub fn parse_with(text: &str, loaded: &BTreeMap<String, Module>) -> Result<Module, Error> {
        Module::parse_within(text, loaded, Distribution::Controlled)
    }

    /// `parse_with` for an engine whose distribution limit is `max`. The
    /// checks run in the order of ruling 29 of 0.8: line errors as the text
    /// is read, then `missing-distribution`, `missing-source`,
    /// `distribution-refused`, `unknown-module`, `distribution-violation`,
    /// the `derive` checks. `duplicate-module` is the engine's, and last.
    fn parse_within(text: &str, loaded: &BTreeMap<String, Module>, max: Distribution) -> Result<Module, Error> {
        module_line_checks(text)?;
        let core = loaded.get("core");
        let mut uses: Vec<String> = Vec::new();
        let mut derives: Vec<DeriveDef> = Vec::new();
        let mut name = None;
        let mut version = None;
        let mut distribution = None;
        let mut sources = Vec::new();
        let mut keys: Vec<KeyDef> = Vec::new();
        let mut lists: Vec<(String, String)> = Vec::new();
        // the names declared so far, keys and lists together
        let mut declared: HashSet<String> = HashSet::new();
        for (lineno, raw) in text.lines().enumerate() {
            let ln = lineno + 1;
            let toks = tokenize_at(raw, ln)?;
            if toks.is_empty() {
                continue;
            }
            // the number of arguments, then a repeated header line (ruling 5 of 0.11)
            let args = toks.len() - 1;
            let count_ok = match toks[0].as_str() {
                "module" | "version" | "distribution" | "source" | "uses" => args == 1,
                _ => true,
            };
            if !count_ok {
                return bad(ln, format!("`{}` takes one argument, got {}", toks[0], args));
            }
            let repeated = match toks[0].as_str() {
                "module" => name.is_some(),
                "version" => version.is_some(),
                "distribution" => distribution.is_some(),
                _ => false,
            };
            if repeated {
                return bad(ln, format!("a second `{}` line", toks[0]));
            }
            match toks[0].as_str() {
                "list" => {
                    if toks.len() < 2 || toks.len() > 3 {
                        return bad(ln, "list needs <name> [meaning]");
                    }
                    if toks[1].contains('.') {
                        return bad(ln, format!("list name `{}` may not contain `.`", toks[1]));
                    }
                    // a list shares the key namespace of its module
                    if !declared.insert(toks[1].clone()) {
                        return err(format!("duplicate-key: line {}: `{}` declared twice", ln, toks[1]));
                    }
                    lists.push((toks[1].clone(), toks.get(2).cloned().unwrap_or_default()));
                }
                "module" => name = Some(req_arg(&toks, 1, ln)?),
                "uses" => {
                    if toks.len() != 2 {
                        return bad(ln, "uses needs <module>");
                    }
                    if !uses.contains(&toks[1]) {
                        uses.push(toks[1].clone());
                    }
                }
                "version" => version = Some(req_arg(&toks, 1, ln)?),
                "distribution" => {
                    let v = req_arg(&toks, 1, ln)?;
                    distribution = Some(Distribution::parse(&v).ok_or(Error {
                        msg: format!("bad-directive: line {}: distribution is `public` or `controlled`, got `{}`", ln, v),
                    })?)
                }
                "source" => sources.push(req_arg(&toks, 1, ln)?),
                "key" => {
                    if toks.len() < 4 || toks.len() > 5 {
                        return err(format!(
                            "bad-directive: line {}: key needs <name> <type> <unit> [meaning]",
                            ln
                        ));
                    }
                    let ty = KeyType::parse(&toks[2]).ok_or(Error {
                        msg: format!("bad-directive: line {}: key type is string, float or int, got `{}`", ln, toks[2]),
                    })?;
                    if toks[1].contains('.') {
                        return err(format!("bad-directive: line {}: key name `{}` may not contain `.`", ln, toks[1]));
                    }
                    if !declared.insert(toks[1].clone()) {
                        return err(format!("duplicate-key: line {}: key `{}` declared twice", ln, toks[1]));
                    }
                    keys.push(KeyDef {
                        name: toks[1].clone(),
                        ty,
                        unit: toks[3].clone(),
                        meaning: toks.get(4).cloned().unwrap_or_default(),
                    });
                }
                "derive" => {
                    if toks.len() < 4 {
                        return bad(ln, "derive needs <model-key> <function> <argument-key> [<argument-key>...]");
                    }
                    let func = DeriveFn::parse(&toks[2])
                        .ok_or(Error { msg: format!("bad-directive: line {}: unknown derive function `{}`", ln, toks[2]) })?;
                    // the count of `present` is a line error (ruling 3 of 0.12)
                    if func == DeriveFn::Present && toks.len() != 4 {
                        return bad(ln, "derive present takes exactly one argument key");
                    }
                    derives.push(DeriveDef { target: toks[1].clone(), func, args: toks[3..].to_vec(), line: ln });
                }
                other => return err(format!("unknown-directive: line {}: `{}` in a model module", ln, other)),
            }
        }
        let name = name.ok_or(Error { msg: "missing-module: the model module has no `module` line".into() })?;
        if version.is_none() {
            return err(format!("missing-version: model module `{}` has no `version` line", name));
        }
        let distribution = distribution.ok_or(Error {
            msg: format!("missing-distribution: model module `{}` has no `distribution`", name),
        })?;
        if sources.is_empty() {
            return err(format!("missing-source: model module `{}` has no `source`", name));
        }
        if distribution > max {
            return err(format!(
                "distribution-refused: model module `{}` is {}, this engine loads {} only",
                name,
                distribution.name(),
                max.name()
            ));
        }
        // a used module must be loaded: its keys are needed to check the `derive` lines
        if let Some(u) = uses.iter().find(|u| **u != name && !loaded.contains_key(*u)) {
            return err(format!("unknown-module: model module `{}` uses model module `{}`, which is not loaded", name, u));
        }
        // a public module uses only public modules
        if distribution == Distribution::Public {
            if let Some(u) = uses.iter().find(|u| loaded.get(*u).map_or(false, |m| m.distribution != Distribution::Public)) {
                return err(format!("distribution-violation: public model module `{}` uses controlled model module `{}`", name, u));
            }
        }
        // `derive` lines: keys of `core` or of this module, as arguments also
        // keys of a used module, and types that fit the function
        let own: HashMap<&str, KeyType> = keys.iter().map(|k| (k.name.as_str(), k.ty)).collect();
        let key_of = |m: &Module, k: &str| m.keys.iter().find(|d| d.name == k).map(|d| d.ty);
        for d in &derives {
            let type_of = |key: &str, argument: bool| -> Result<KeyType, Error> {
                let found = match key.split_once('.') {
                    None if name == "core" => own.get(key).copied(),
                    None => core.and_then(|c| key_of(c, key)),
                    Some((m, k)) if m == name && m != "core" => own.get(k).copied(),
                    Some((m, k)) if argument && m != "core" && uses.iter().any(|u| u == m) => {
                        loaded.get(m).and_then(|u| key_of(u, k))
                    }
                    Some(_) => None,
                };
                found.ok_or(Error {
                    msg: format!("bad-directive: line {}: derive names `{}`, not a declared key of `core` or `{}`", d.line, key, name),
                })
            };
            let target = type_of(&d.target, false)?;
            let args = d.args.iter().map(|a| type_of(a, true)).collect::<Result<Vec<_>, _>>()?;
            if !d.func.fits(target, &args) {
                return bad(d.line, format!("the arguments or types of `derive {}` do not fit its function", d.target));
            }
        }
        Ok(Module { name, version: version.expect("checked above"), distribution, sources, keys, lists, derives, uses })
    }
}

/// The line checks of a module (ruling 5b of 0.11): `unterminated-quote`,
/// `unknown-directive`, the number of arguments (5e), a repeated header line
/// and the `distribution` value, each line in order. Every other cause is
/// checked after the file is read.
fn module_line_checks(text: &str) -> Result<(), Error> {
    let mut seen: HashSet<String> = HashSet::new();
    for (lineno, raw) in text.lines().enumerate() {
        let ln = lineno + 1;
        let toks = tokenize_at(raw, ln)?;
        if toks.is_empty() {
            continue;
        }
        let d = toks[0].as_str();
        if !matches!(d, "module" | "version" | "distribution" | "source" | "uses" | "key" | "list" | "derive") {
            return err(format!("unknown-directive: line {}: `{}` is not a directive of a model module", ln, d));
        }
        if matches!(d, "module" | "version" | "distribution" | "source" | "uses") && toks.len() != 2 {
            return bad(ln, format!("`{}` takes one argument, got {}", d, toks.len() - 1));
        }
        if matches!(d, "module" | "version" | "distribution") && !seen.insert(d.to_string()) {
            return bad(ln, format!("a second `{}` line", d));
        }
        if d == "distribution" && Distribution::parse(&toks[1]).is_none() {
            return bad(ln, format!("distribution is `public` or `controlled`, got `{}`", toks[1]));
        }
    }
    Ok(())
}

/// Split a pack's model key into (module, key name). A bare key is in `core`.
pub fn split_key(model_key: &str) -> (&str, &str) {
    match model_key.find('.') {
        Some(i) => (&model_key[..i], &model_key[i + 1..]),
        None => ("core", model_key),
    }
}

// ---------------------------------------------------------------------------
// Pack
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Wire {
    Xml,
    GeoJson,
    /// fixed-size binary words, fields are bit ranges; I/O as hex text
    Bits,
    /// protobuf wire format; fields by number (dot-path for nested); I/O as hex text
    Protobuf,
    /// any JSON object; members addressed by dot-path
    Json,
    /// one record of ASCII text: delimited fields and columns (engine-spec v0.10)
    Text,
    /// a set of tag-length-value items, sets nested in values (engine-spec v0.13)
    Tlv,
}

impl Wire {
    /// The name the `wire` line gives.
    pub fn name(self) -> &'static str {
        match self {
            Wire::Xml => "xml",
            Wire::GeoJson => "geojson",
            Wire::Bits => "bits",
            Wire::Protobuf => "protobuf",
            Wire::Json => "json",
            Wire::Text => "text",
            Wire::Tlv => "tlv",
        }
    }

    /// The seven wires of the specification, in the order of ruling 1a of 0.24.
    pub const ALL: [Wire; 7] = [Wire::Xml, Wire::GeoJson, Wire::Json, Wire::Bits, Wire::Protobuf, Wire::Text, Wire::Tlv];

    /// The wire a `wire` line names, built or not; None: no wire of the specification.
    pub fn from_name(name: &str) -> Option<Wire> {
        Wire::ALL.iter().copied().find(|w| w.name() == name)
    }

    /// Engine-spec 0.24: whether this build has the codecs of the wire (the
    /// Cargo feature of the same name).
    pub fn in_build(self) -> bool {
        match self {
            Wire::Xml => cfg!(feature = "xml"),
            Wire::GeoJson => cfg!(feature = "geojson"),
            Wire::Bits => cfg!(feature = "bits"),
            Wire::Protobuf => cfg!(feature = "protobuf"),
            Wire::Json => cfg!(feature = "json"),
            Wire::Text => cfg!(feature = "text"),
            Wire::Tlv => cfg!(feature = "tlv"),
        }
    }
}

/// Engine-spec 0.24: the wires this build has, in the order of ruling 1a.
pub fn build_wires() -> Vec<&'static str> {
    Wire::ALL.iter().filter(|w| w.in_build()).map(|w| w.name()).collect()
}

/// The error of a decode or encode on a wire the build lacks. No pack on such
/// a wire loads (ruling 1c of 0.24), so no conversion reaches it.
#[allow(dead_code)]
fn not_built<T>(w: Wire) -> Result<T, Error> {
    err(format!("unknown-wire: this build does not have the `{}` wire", w.name()))
}

#[derive(Clone, Debug)]
pub struct FieldDef {
    pub model_key: String,
    pub locator: String,
    pub transform: Transform,
    /// line of the pack file, for line-order output
    pub line: usize,
    /// `via <table>`: the value table the value passes through (engine-spec v0.6)
    pub via: Option<String>,
    /// `swap` (bits): the field's bytes are taken in reverse order
    pub swap: bool,
    /// `trim` (bits, ascii): decode also removes trailing spaces
    pub trim: bool,
    /// `optional` (bits): a field beyond the end of the input is absent
    pub optional: bool,
    /// the declared type of the model key, set when the pack is loaded
    pub key_type: Option<KeyType>,
    /// `absent <value>[,<value>…]` (engine-spec v0.9): the argument as written
    pub absent_arg: Option<String>,
    /// the sentinels of `absent`, resolved for the wire when the pack is read
    pub absent: Vec<Sentinel>,
    /// fixed `bits` layout (engine-spec v0.17): the innermost gate block the
    /// line is in, an index into the gate table of its scope
    pub gate: Option<usize>,
    /// `with <other-key>` (engine-spec v0.18): encode writes the line only
    /// when the entity (inside a group, the item) holds that key
    pub with: Option<(String, usize)>,
    /// `until:<code>` (sequential, engine-spec v0.22): the field is characters
    /// up to this terminator code
    pub until: Option<u32>,
    /// `stop <code>` (engine-spec v0.22): the text of a fixed-size `chars`
    /// field ends at the first character of this code
    pub stop: Option<u32>,
    /// `null` (json, geojson; engine-spec v0.56): an absent key's member is
    /// written as JSON `null`
    pub null: bool,
    /// `implicit` (protobuf; engine-spec v0.56): a scalar equal to the proto3
    /// default is not written
    pub implicit: bool,
    /// `range <min> <max> [wrap]` (engine-spec v0.56)
    pub range: Option<RangeOpt>,
}

/// The `range` option of a field (engine-spec v0.56).
#[derive(Clone, Debug)]
pub struct RangeOpt {
    /// the bounds as written
    pub min: String,
    pub max: String,
    pub wrap: bool,
    /// the bounds read as the key's type, set when the pack is loaded
    pub val: Option<RangeVal>,
}

#[derive(Clone, Copy, Debug)]
pub enum RangeVal {
    Int(i64, i64),
    Float(f64, f64),
}

impl RangeVal {
    /// Read the bounds as the key's type; None when they are not its text, or
    /// `<min>` is not less than `<max>`.
    pub(crate) fn read(ty: KeyType, min: &str, max: &str) -> Option<RangeVal> {
        match ty {
            KeyType::Int => match (int_text(min), int_text(max)) {
                (Some(a), Some(b)) if a < b => Some(RangeVal::Int(a, b)),
                _ => None,
            },
            KeyType::Float => match (number_text(min), number_text(max)) {
                (Some(a), Some(b)) if a < b => Some(RangeVal::Float(a, b)),
                _ => None,
            },
            KeyType::Str => None,
        }
    }

    /// Check a model value against the range, or wrap it into it (engine-spec
    /// v0.56): the value `via` and the transform then see.
    pub(crate) fn apply(&self, wrap: bool, v: &Value) -> Result<Value, Error> {
        match (*self, v) {
            (RangeVal::Int(min, max), Value::I64(x)) => {
                let x = *x;
                if x >= min && (x < max || (!wrap && x == max)) {
                    return Ok(Value::I64(x));
                }
                if !wrap {
                    return err(format!("{} is outside the range [{}, {}]", x, min, max));
                }
                // exact: x − (max − min) × floor((x − min) / (max − min)) (ruling 7 of 0.56)
                let d = max as i128 - min as i128;
                let k = (x as i128 - min as i128).div_euclid(d);
                Ok(Value::I64((x as i128 - k * d) as i64))
            }
            (RangeVal::Float(min, max), Value::F64(x)) => {
                let x = *x;
                if !x.is_finite() {
                    return err(format!("{} is outside the range [{}, {}]", fmt_f64(x), fmt_f64(min), fmt_f64(max)));
                }
                if x >= min && (x < max || (!wrap && x == max)) {
                    return Ok(Value::F64(x));
                }
                if !wrap {
                    return err(format!(
                        "{} is outside the range [{}, {}]",
                        fmt_f64(x),
                        fmt_f64(min),
                        fmt_f64(max)
                    ));
                }
                let d = max - min;
                let mut r = x - d * ((x - min) / d).floor();
                if !(r >= min && r < max) {
                    r = min;
                }
                Ok(Value::F64(r))
            }
            _ => Ok(v.clone()),
        }
    }
}

/// One gate block `if [!]<locator> <value>[,…]` … `end` of a fixed-layout
/// `bits` pack (engine-spec v0.17).
#[derive(Clone, Debug)]
pub struct GateDef {
    pub locator: String,
    /// the values as written
    pub text: String,
    /// the values, resolved when the wire is known
    pub values: Vec<u64>,
    /// `!`: the block holds when the bits equal none of the values
    pub negate: bool,
    /// the block this one is nested in
    pub parent: Option<usize>,
    /// the kind the block is in (common and kind blocks share the pack's table)
    pub kind: Option<usize>,
    pub line: usize,
}

/// One wire value of an `absent` option that means "no value" (engine-spec v0.9).
#[derive(Clone, Debug, PartialEq)]
pub enum Sentinel {
    /// `bits`, and the integer forms of `protobuf`: the raw unsigned integer
    Num(u64),
    /// `xml`, `json`, `geojson` and `pstring`: the text compared, and how a
    /// `json` or `geojson` wire writes it
    Text(String, SentinelJson),
    /// a range sentinel on a raw unsigned integer (engine-spec v0.56): `>=`
    /// when true, `<=` when false; never written
    NumRange(bool, u64),
    /// a range sentinel on a raw text read as number text (engine-spec v0.56)
    TextRange(bool, f64),
}

impl Sentinel {
    /// An exact sentinel, the kind encode may write.
    pub(crate) fn exact(&self) -> bool {
        matches!(self, Sentinel::Num(_) | Sentinel::Text(..))
    }
}

/// How a sentinel is written on `json` and `geojson` (ruling 9 of 0.9).
#[derive(Clone, Debug, PartialEq)]
pub enum SentinelJson {
    Str,
    Num(f64),
    Bool(bool),
}

impl FieldDef {
    /// Is the raw unsigned integer of this field one of its sentinels?
    #[cfg(any(feature = "bits", feature = "protobuf"))]
    pub(crate) fn absent_num(&self, raw: u64) -> bool {
        self.absent.iter().any(|s| match s {
            Sentinel::Num(n) => *n == raw,
            Sentinel::NumRange(true, n) => raw >= *n,
            Sentinel::NumRange(false, n) => raw <= *n,
            _ => false,
        })
    }
    /// Is the raw text of this field one of its sentinels?
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "protobuf"))]
    pub(crate) fn absent_text(&self, raw: &str) -> bool {
        let num = || number_text(raw);
        self.absent.iter().any(|s| match s {
            Sentinel::Text(t, _) => t == raw,
            Sentinel::TextRange(ge, n) => num().map_or(false, |x| if *ge { x >= *n } else { x <= *n }),
            _ => false,
        })
    }
    /// The sentinel encode writes for an absent key: the first.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf"))]
    pub(crate) fn sentinel(&self) -> Option<&Sentinel> {
        self.absent.iter().find(|s| s.exact())
    }
}

/// Read the option list of a `field` line, from the token after the
/// transform. `optional` is refused where `allow_optional` is false (a
/// sequential pack). The token after `absent` is always its argument (ruling
/// 11 of 0.9).
fn field_options(f: &mut FieldDef, toks: &[String], ln: usize, allow_optional: bool) -> Result<Vec<String>, Error> {
    field_options_at(f, toks, ln, allow_optional, true)
}

/// `resolve` false: the line check of 5b of 0.11, as the line is read. Of
/// `stop` only its syntax is checked there (a code given, not twice); its
/// transform and its code are checks after the file (ruling 28 of 0.22).
fn field_options_at(f: &mut FieldDef, toks: &[String], ln: usize, allow_optional: bool, resolve: bool) -> Result<Vec<String>, Error> {
    let mut vias = Vec::new();
    let mut stop_seen = false;
    let mut i = 4;
    while i < toks.len() {
        let flag = match toks[i].as_str() {
            "via" => {
                i += 1;
                match toks.get(i) {
                    Some(t) if f.via.is_none() => f.via = Some(t.clone()),
                    Some(_) => return bad(ln, "`via` given twice"),
                    None => return bad(ln, "`via` needs <table>"),
                }
                vias.push(toks[i].clone());
                i += 1;
                continue;
            }
            "with" => {
                i += 1;
                match toks.get(i) {
                    Some(t) if f.with.is_none() => f.with = Some((t.clone(), ln)),
                    Some(_) => return bad(ln, "`with` given twice"),
                    None => return bad(ln, "`with` needs <other-key>"),
                }
                i += 1;
                continue;
            }
            "absent" => {
                i += 1;
                match toks.get(i) {
                    Some(t) if f.absent_arg.is_none() => f.absent_arg = Some(t.clone()),
                    Some(_) => return bad(ln, "`absent` given twice"),
                    None => return bad(ln, "`absent` needs <value>[,<value>…]"),
                }
                i += 1;
                continue;
            }
            "stop" => {
                i += 1;
                let text = match toks.get(i) {
                    Some(t) if !stop_seen => t,
                    Some(_) => return bad(ln, "`stop` given twice"),
                    None => return bad(ln, "`stop` needs <code>"),
                };
                stop_seen = true;
                if !resolve {
                    i += 1;
                    continue;
                }
                let set = match f.transform {
                    Transform::Chars(set) => set,
                    _ => return bad(ln, "`stop` is valid only on a `chars` field"),
                };
                f.stop = Some(char_code(text, set, ln, "stop")?);
                i += 1;
                continue;
            }
            // engine-spec v0.56: two bounds of number text (2b of 0.11), then
            // an optional `wrap`; the key's type is checked after the file
            "range" => {
                if f.range.is_some() {
                    return bad(ln, "`range` given twice");
                }
                let (min, max) = match (toks.get(i + 1), toks.get(i + 2)) {
                    (Some(a), Some(b)) => (a.clone(), b.clone()),
                    _ => return bad(ln, "`range` needs <min> <max>"),
                };
                for b in [&min, &max] {
                    if number_text(b).is_none() {
                        return bad(ln, format!("`range` bound `{}` is not number text", b));
                    }
                }
                i += 3;
                let wrap = toks.get(i).map_or(false, |t| t == "wrap");
                if wrap {
                    i += 1;
                }
                f.range = Some(RangeOpt { min, max, wrap, val: None });
                continue;
            }
            "wrap" => match &f.range {
                Some(r) if r.wrap => return bad(ln, "`wrap` given twice"),
                _ => return bad(ln, "`wrap` does not follow `range <min> <max>`"),
            },
            "null" => &mut f.null,
            "implicit" => &mut f.implicit,
            "swap" => &mut f.swap,
            "trim" => &mut f.trim,
            "optional" if allow_optional => &mut f.optional,
            "optional" => return bad(ln, "`optional` is not valid in a `layout sequential` pack"),
            o => return bad(ln, format!("unknown field option `{}`", o)),
        };
        if *flag {
            return bad(ln, format!("field option `{}` given twice", toks[i]));
        }
        *flag = true;
        i += 1;
    }
    Ok(vias)
}

/// A terminator code of `until:<code>` or `stop <code>` (engine-spec v0.22):
/// plain digits, below `2^w`.
pub(crate) fn char_code(text: &str, set: CharSet, ln: usize, what: &str) -> Result<u32, Error> {
    let w = set.width();
    if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
        return bad(ln, format!("`{} {}`: the code is not plain digits", what, text));
    }
    match text.parse::<u64>() {
        Ok(c) if c < 1u64 << w => Ok(c as u32),
        _ => bad(ln, format!("`{} {}`: the code is 2^{} or more", what, text, w)),
    }
}

/// Resolve the `absent` argument of a field for its wire (engine-spec v0.9,
/// Load errors). `bits_len`: the bit length of a `bits` field.
fn resolve_absent(wire: Wire, f: &mut FieldDef, bits_len: Option<u32>) -> Result<(), Error> {
    let arg = match &f.absent_arg {
        Some(a) => a.clone(),
        None => return Ok(()),
    };
    let ln = f.line;
    // ruling 16 of 0.10: not stated on the text wire yet
    if wire == Wire::Text {
        return bad(ln, "`absent` is not valid on the text wire");
    }
    // ruling 10 of 0.13: not stated on the tlv wire yet
    if wire == Wire::Tlv {
        return bad(ln, "`absent` is not valid on the tlv wire in 0.13");
    }
    // the quoted empty token `""` is the one value "the empty text"
    let values: Vec<&str> = if arg.is_empty() { vec![""] } else { arg.split(',').collect() };
    if arg.contains('"') || (values.len() > 1 && values.iter().any(|v| v.is_empty())) {
        return bad(ln, format!("`absent {}`: an empty value in the list", arg));
    }
    let number = |v: &str, max_bits: u32| -> Result<u64, Error> {
        if v.is_empty() || !v.bytes().all(|b| b.is_ascii_digit()) {
            return bad(ln, format!("`absent` value `{}` is not an unsigned decimal integer", v));
        }
        let n = v.parse::<u64>().or_else(|_| bad(ln, format!("`absent` value `{}` is too large", v)))?;
        if max_bits < 64 && n >> max_bits != 0 {
            return bad(ln, format!("`absent` value {} does not fit {} bits", n, max_bits));
        }
        Ok(n)
    };
    let mut out = Vec::new();
    for v in values {
        // engine-spec v0.56: a value that begins with `>=` or `<=`, as written,
        // is a range sentinel; it is never written
        let range = v.strip_prefix(">=").map(|n| (true, n)).or_else(|| v.strip_prefix("<=").map(|n| (false, n)));
        if let Some((ge, n)) = range {
            out.push(match (wire, &f.transform) {
                (Wire::Bits, _) => {
                    let len = bits_len.unwrap_or(0);
                    if len > 64 {
                        return bad(ln, format!("`absent` on a field of {} bits; at most 64", len));
                    }
                    Sentinel::NumRange(ge, number(n, len)?)
                }
                (Wire::Protobuf, Transform::Pvarint | Transform::Psint) => Sentinel::NumRange(ge, number(n, 64)?),
                (Wire::Protobuf, Transform::Pstring) | (Wire::Xml | Wire::Json | Wire::GeoJson, _)
                    if f.transform != Transform::Bool =>
                {
                    match number_text(n) {
                        Some(x) => Sentinel::TextRange(ge, x),
                        None => return bad(ln, format!("range sentinel `{}`: `{}` is not number text", v, n)),
                    }
                }
                _ => return bad(ln, format!("a range sentinel `{}` is not valid with the transform of `{}`", v, f.model_key)),
            });
            continue;
        }
        out.push(match wire {
            Wire::Bits => {
                let len = bits_len.unwrap_or(0);
                if len > 64 {
                    return bad(ln, format!("`absent` on a field of {} bits; at most 64", len));
                }
                Sentinel::Num(number(v, len)?)
            }
            Wire::Protobuf => match f.transform {
                // `=` is part of the text on `pstring` (ruling 12 of 0.9)
                Transform::Pstring => Sentinel::Text(v.to_string(), SentinelJson::Str),
                Transform::Pfloat => Sentinel::Num(number(v, 32)?),
                _ => Sentinel::Num(number(v, 64)?),
            },
            Wire::Xml | Wire::Json | Wire::GeoJson => {
                let forced = v.starts_with('=');
                let text = if forced { &v[1..] } else { v };
                if v != "" && text.is_empty() {
                    return bad(ln, "an `absent` value empty after `=`; only `\"\"` names the empty text");
                }
                let json = if wire == Wire::Xml || forced {
                    SentinelJson::Str
                } else {
                    match text {
                        "null" => return bad(ln, "`null` cannot be an `absent` value"),
                        "true" => SentinelJson::Bool(true),
                        "false" => SentinelJson::Bool(false),
                        // JSON number text (RFC 8259) is held as its canonical text (ruling 9 of 0.9)
                        _ => match json::parse(text) {
                            _ if text.trim() != text => SentinelJson::Str,
                            Ok(json::Json::Int(n)) => SentinelJson::Num(n as f64),
                            Ok(json::Json::Num(x)) if x.is_finite() => SentinelJson::Num(x),
                            Ok(json::Json::Num(_)) => {
                                return bad(ln, format!("`absent` value `{}` is not a finite number", text))
                            }
                            _ => SentinelJson::Str,
                        },
                    }
                };
                // ruling 25 of 0.9: a `geojson` coordinate takes number text only
                if wire == Wire::GeoJson && f.locator.starts_with("geometry.") && !matches!(json, SentinelJson::Num(_)) {
                    return bad(ln, format!("`absent` value `{}` on a coordinate is not number text", v));
                }
                // ruling 13 of 0.9: the `bool` transform holds `true` and `false` only
                if f.transform == Transform::Bool && !matches!(json, SentinelJson::Bool(_)) {
                    return bad(ln, format!("`absent` value `{}` on `bool` is not `true` or `false`", v));
                }
                let text = match json {
                    SentinelJson::Num(x) => fmt_f64(x),
                    _ => text.to_string(),
                };
                Sentinel::Text(text, json)
            }
            Wire::Text | Wire::Tlv => unreachable!("rejected above"),
        });
    }
    f.absent = out;
    Ok(())
}

/// The text a sentinel compares a JSON wire value with (ruling 9 of 0.9): a
/// string as it is, a number's canonical text, `true` or `false`. None for
/// `null`, arrays and objects.
#[cfg(any(feature = "geojson", feature = "json"))]
fn json_absent_text(j: &json::Json) -> Option<String> {
    match j {
        json::Json::Int(n) => Some(fmt_f64(*n as f64)),
        other => json_when_text(other),
    }
}

/// Does a JSON wire value hold one of the field's sentinels?
#[cfg(any(feature = "geojson", feature = "json"))]
fn json_absent(f: &FieldDef, j: &json::Json) -> bool {
    !f.absent.is_empty() && json_absent_text(j).map_or(false, |t| f.absent_text(&t))
}

/// The JSON value of a sentinel (ruling 11 of 0.5, ruling 9 of 0.9).
#[cfg(any(feature = "geojson", feature = "json"))]
fn sentinel_json(s: &Sentinel) -> json::Json {
    match s {
        Sentinel::Text(_, SentinelJson::Num(x)) => json::Json::Num(*x),
        Sentinel::Text(_, SentinelJson::Bool(b)) => json::Json::Bool(*b),
        Sentinel::Text(t, SentinelJson::Str) => json::Json::Str(t.clone()),
        Sentinel::Num(n) => json::Json::Num(*n as f64),
        Sentinel::NumRange(..) | Sentinel::TextRange(..) => json::Json::Null,
    }
}

/// The first line that names each locator of a scope (ruling 23 of 0.9).
#[cfg(any(feature = "xml", feature = "geojson", feature = "json"))]
fn first_lines<'a>(lines: impl Iterator<Item = (usize, &'a str)>) -> HashMap<&'a str, usize> {
    let mut out: HashMap<&str, usize> = HashMap::new();
    for (n, loc) in lines {
        let e = out.entry(loc).or_insert(n);
        *e = (*e).min(n);
    }
    out
}

/// The sentinel lines of one scope that encode may write: those of an absent
/// key whose place no line with a value (the entity's or a `default`) writes
/// (ruling 16 of 0.9). Each with its sentinel.
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "protobuf"))]
fn sentinel_lines<'a>(sel: &Sel<'a>, ent: &Entity, skip: impl Fn(&FieldDef) -> bool) -> Vec<(&'a FieldDef, &'a Sentinel)> {
    let written: Vec<&str> =
        sel.fields.iter().filter(|f| !skip(f) && sel.value_of(ent, f).is_some()).map(|f| f.locator.as_str()).collect();
    sel.fields
        .iter()
        .filter(|f| !skip(f) && live(ent, f) && sel.value_of(ent, f).is_none() && !written.contains(&f.locator.as_str()))
        .filter_map(|f| f.sentinel().map(|s| (*f, s)))
        .collect()
}

/// The `null` lines of one scope that encode writes (engine-spec v0.56): a
/// line in force whose key is absent, on a member no line in `written`
/// writes; of several on one member, the first.
#[cfg(any(feature = "geojson", feature = "json"))]
fn null_lines<'a>(sel: &Sel<'a>, ent: &Entity, written: &[&str]) -> Vec<&'a FieldDef> {
    let mut out: Vec<&'a FieldDef> = Vec::new();
    for f in sel.fields.iter().copied() {
        if f.null
            && f.locator != "."
            && live(ent, f)
            && sel.value_of(ent, f).is_none()
            && !written.contains(&f.locator.as_str())
            && !out.iter().any(|o| o.locator == f.locator)
        {
            out.push(f);
        }
    }
    out
}

/// Does the entity (inside a group, the item) hold `key`? A scalar when it
/// is present, whatever its value; a list when it has at least one item
/// (ruling 2 of 0.18).
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
pub(crate) fn holds(ent: &Entity, key: &str) -> bool {
    ent.fields.contains_key(key) || ent.lists.get(key).map_or(false, |l| !l.is_empty())
}

/// Is the line in force on encode? False when its `with` key is not held:
/// the line is then a line whose key is absent and that has neither a
/// `default` nor a sentinel (engine-spec v0.18).
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
pub(crate) fn live(ent: &Entity, f: &FieldDef) -> bool {
    f.with.as_ref().map_or(true, |(k, _)| holds(ent, k))
}

/// Does the entity hold the field's key, on a line that is in force?
#[cfg(any(feature = "bits", feature = "protobuf"))]
pub(crate) fn has_key(ent: &Entity, f: &FieldDef) -> bool {
    live(ent, f) && ent.fields.contains_key(&f.model_key)
}

/// One `default` line: the value encode uses for a key the entity lacks.
#[derive(Clone, Debug)]
pub struct DefaultDef {
    pub model_key: String,
    /// the value as written in the pack
    pub text: String,
    pub line: usize,
    /// the value read as the key's declared type, set when the pack is loaded
    pub value: Option<Value>,
    /// the innermost gate block the line is in (engine-spec v0.17)
    pub gate: Option<usize>,
}

/// One `when` line: a wire value that marks a kind (engine-spec v0.5).
#[derive(Clone, Debug)]
pub struct WhenDef {
    pub locator: String,
    /// the value as written in the pack
    pub value: String,
    /// `present` (protobuf and text wires)
    pub present: bool,
    /// text wires: the text to match and write (leading `=` stripped)
    pub text: String,
    /// text wires: the value was written with a leading `=` (json, geojson: write a string)
    pub forced: bool,
    /// bits and protobuf: the unsigned integer to match and write
    pub num: u64,
    pub line: usize,
    /// a `const` in a gate block: the innermost one (engine-spec v0.17)
    pub gate: Option<usize>,
    /// bits and protobuf: every listed value and range, `(lo, hi)` both
    /// included (engine-spec v0.20); the first `lo` is `num`
    pub nums: Vec<(u64, u64)>,
    /// text wires: every listed text, `=` stripped; the first is `text`
    pub texts: Vec<String>,
}

impl WhenDef {
    /// Does an unsigned wire value match the line (any value or range)?
    #[cfg(any(feature = "bits", feature = "protobuf"))]
    pub(crate) fn holds_num(&self, v: u64) -> bool {
        if self.nums.is_empty() {
            return v == self.num;
        }
        self.nums.iter().any(|(lo, hi)| *lo <= v && v <= *hi)
    }
    /// Does a wire text match the line (any listed text)?
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json"))]
    pub(crate) fn holds_text(&self, t: &str) -> bool {
        if self.texts.is_empty() {
            return t == self.text;
        }
        self.texts.iter().any(|x| x == t)
    }
    /// A list or a range: more than one wire value matches (ruling 3 of 0.20).
    #[cfg(any(feature = "bits", feature = "protobuf"))]
    pub(crate) fn several(&self) -> bool {
        self.nums.len() > 1 || self.nums.first().map_or(false, |(lo, hi)| lo != hi) || self.texts.len() > 1
    }
}

/// The `count` of a `bits` group.
#[derive(Clone, Debug, PartialEq)]
pub enum Count {
    /// a `<word>:<pos>:<len>` field of the enclosing scope, read as unsigned
    Locator(String),
    Fixed(u64),
}

/// One `group ... end` block: a repeating part mapped to a list (engine-spec v0.7).
#[derive(Clone, Debug)]
pub struct GroupDef {
    pub list: String,
    pub locator: String,
    pub line: usize,
    /// bits only: `item <bits>`
    pub item_bits: Option<u64>,
    /// bits only: `count <count-locator | n>`
    pub count: Option<Count>,
    pub fields: Vec<FieldDef>,
    pub consts: Vec<WhenDef>,
    pub defaults: Vec<DefaultDef>,
    pub groups: Vec<GroupDef>,
    /// the gate blocks of the item (engine-spec v0.17)
    pub gates: Vec<GateDef>,
}

impl GroupDef {
    /// The lines in force for one item.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]
    fn body(&self) -> Sel<'_> {
        Sel {
            kind: None,
            fields: self.fields.iter().collect(),
            whens: Vec::new(),
            consts: self.consts.iter().collect(),
            defaults: self.defaults.iter().collect(),
            groups: self.groups.iter().collect(),
            root: "",
            gates: &self.gates,
            elements: Vec::new(),
        }
    }
    /// This group and every group nested in it.
    fn walk<'a>(&'a self, out: &mut Vec<&'a GroupDef>) {
        out.push(self);
        for g in &self.groups {
            g.walk(out);
        }
    }
    fn walk_mut(&mut self, f: &mut dyn FnMut(&mut GroupDef)) {
        f(self);
        for g in &mut self.groups {
            g.walk_mut(f);
        }
    }
    /// The field of the body that reads the item itself (`.`), if any.
    fn scalar(&self) -> Option<&FieldDef> {
        self.fields.iter().find(|f| f.locator == ".")
    }
}

/// One term of a `requires` line: a key, or a key with `=` and values
/// (engine-spec v0.20).
#[derive(Clone, Debug)]
pub struct ReqDef {
    pub key: String,
    pub line: usize,
    /// the values after `=`, as written; None: the plain key of 0.5
    pub values: Option<Vec<String>>,
    /// the values as canonical text of the key's type, set when the pack is loaded
    pub canon: Vec<String>,
}

impl ReqDef {
    /// The terms of one `requires` line.
    pub(crate) fn parse(toks: &[String], ln: usize) -> Result<Vec<ReqDef>, Error> {
        let mut out = Vec::new();
        for term in toks {
            // split at the first `=`; the rest is the value list (ruling 4 of 0.20)
            let (key, values) = match term.split_once('=') {
                None => (term.clone(), None),
                Some((k, rest)) => {
                    // a term with nothing before `=` names no key (provisional: the
                    // grammar `<model-key>=<value>` needs one; vector 556)
                    if k.is_empty() {
                        return bad(ln, format!("`requires {}` has no key before `=`", term));
                    }
                    if rest.is_empty() {
                        return bad(ln, format!("`requires {}` has no value after `=`", term));
                    }
                    let vs: Vec<String> = rest.split(',').map(|v| v.to_string()).collect();
                    if vs.iter().any(|v| v.is_empty()) {
                        return bad(ln, format!("`requires {}` has an empty value in its list", term));
                    }
                    (k.to_string(), Some(vs))
                }
            };
            out.push(ReqDef { key, line: ln, values, canon: Vec::new() });
        }
        Ok(out)
    }
    /// Does the entity meet the term? A plain key: the key is present, or the
    /// list has an item. With `=`: the value's canonical text is listed.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    pub(crate) fn holds(&self, ent: &Entity) -> bool {
        match &self.values {
            None => ent.fields.contains_key(&self.key) || ent.lists.get(&self.key).map_or(false, |l| !l.is_empty()),
            Some(vs) => {
                let listed = if self.canon.is_empty() { vs } else { &self.canon };
                ent.fields.get(&self.key).map_or(false, |v| listed.contains(&v.as_display()))
            }
        }
    }
}

/// A value of a `requires =` term or of a `case`, read as the key's declared
/// type (engine-spec v0.20): its canonical text, or None when it is not one.
/// An `int` is an optional `-` then digits.
pub(crate) fn canon_value(ty: KeyType, text: &str) -> Option<String> {
    match ty {
        KeyType::Str => Some(text.to_string()),
        KeyType::Int => {
            let digits = text.strip_prefix('-').unwrap_or(text);
            if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            text.parse::<i64>().ok().map(|n| n.to_string())
        }
        // a JSON number: -?digits[.digits][(e|E)[+|-]digits] (ruling 24 of 0.20)
        KeyType::Float => {
            let b = text.as_bytes();
            let mut i = usize::from(b.first() == Some(&b'-'));
            let digits = |i: &mut usize| {
                let s = *i;
                while *i < b.len() && b[*i].is_ascii_digit() {
                    *i += 1;
                }
                *i > s
            };
            if !digits(&mut i) {
                return None;
            }
            if i < b.len() && b[i] == b'.' {
                i += 1;
                if !digits(&mut i) {
                    return None;
                }
            }
            if i < b.len() && (b[i] == b'e' || b[i] == b'E') {
                i += 1;
                if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
                    i += 1;
                }
                if !digits(&mut i) {
                    return None;
                }
            }
            if i != b.len() {
                return None;
            }
            text.parse::<f64>().ok().filter(|x| x.is_finite()).map(|x| fmt_f64(x))
        }
    }
}

/// One message layout of a format.
#[derive(Clone, Debug)]
pub struct KindDef {
    pub name: String,
    pub whens: Vec<WhenDef>,
    pub requires: Vec<ReqDef>,
    pub fields: Vec<FieldDef>,
    /// `const` lines of this kind (same shape as a `when`; never `present`)
    pub consts: Vec<WhenDef>,
    pub defaults: Vec<DefaultDef>,
    /// xml only: the root element of this kind, when it has its own
    pub root: Option<String>,
    /// `group` blocks of this kind
    pub groups: Vec<GroupDef>,
    /// xml only: `element <path>` lines of this kind (engine-spec v0.18)
    pub elements: Vec<(String, usize)>,
}

/// The lines in force for one message: common plus the selected kind.
pub struct Sel<'a> {
    pub kind: Option<&'a KindDef>,
    pub fields: Vec<&'a FieldDef>,
    pub whens: Vec<&'a WhenDef>,
    pub consts: Vec<&'a WhenDef>,
    /// the selected kind's defaults first, then the common ones
    pub defaults: Vec<&'a DefaultDef>,
    /// `group` blocks in force, common first
    pub groups: Vec<&'a GroupDef>,
    /// xml only: the root element in force
    pub root: &'a str,
    /// the gate table the lines' `gate` indices refer to (engine-spec v0.17)
    pub gates: &'a [GateDef],
    /// xml only: the `element` lines in force, common first (engine-spec v0.18)
    pub elements: Vec<&'a (String, usize)>,
}

impl<'a> Sel<'a> {
    /// The value encode uses for a field: the entity's, else the `default`.
    /// A default in a gate block applies to the fields of that block and of
    /// the blocks nested in it; the innermost wins (ruling 5 of 0.17).
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn value_of(&self, ent: &'a Entity, f: &FieldDef) -> Option<&'a Value> {
        // a line suppressed by `with` has no value, its default included (engine-spec v0.18)
        if !live(ent, f) {
            return None;
        }
        ent.fields.get(&f.model_key).or_else(|| {
            let mut at = f.gate;
            loop {
                if let Some(d) = self.defaults.iter().find(|d| d.gate == at && d.model_key == f.model_key) {
                    return d.value.as_ref();
                }
                at = self.gates.get(at?).and_then(|g| g.parent);
            }
        })
    }
    /// The values written over any field: every `when` that is not `present`, and every `const`.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]
    fn fixed(&self) -> impl Iterator<Item = &'a WhenDef> + '_ {
        self.whens.iter().copied().filter(|w| !w.present).chain(self.consts.iter().copied())
    }
    /// The locators a decode treats as mapped: every field, every `when` that
    /// is not `present` (ruling 27 of 0.5) and every `const`.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json"))]
    fn mapped(&self) -> Vec<&'a str> {
        self.fields
            .iter()
            .map(|f| f.locator.as_str())
            .chain(self.fixed().map(|w| w.locator.as_str()))
            .chain(self.groups.iter().map(|g| g.locator.as_str()))
            .collect()
    }
}

/// The bit order of a `bits` pack (engine-spec v0.5, v0.22).
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum BitOrder {
    /// bit i is bit `i mod 8` of byte `i div 8`; a field's first bit is least significant
    Lsb,
    /// bit i is bit `7 - (i mod 8)` of byte `i div 8`; a field's first bit is most significant
    Msb,
    /// positions as `msb`, values as `lsb`: a field's first bit is least significant
    MsbLsb,
}

impl BitOrder {
    fn parse(s: &str) -> Option<BitOrder> {
        match s {
            "lsb" => Some(BitOrder::Lsb),
            "msb" => Some(BitOrder::Msb),
            "msb-lsb" => Some(BitOrder::MsbLsb),
            _ => None,
        }
    }
}

#[derive(Clone, Debug)]
pub struct Pack {
    pub format: String,
    pub version: String,
    pub wire: Wire,
    pub root: String,       // xml only
    pub word_bytes: usize,  // bits only
    /// bits only: the bit order (`bit_order lsb`, `msb` or `msb-lsb`)
    pub order: BitOrder,
    pub distribution: Distribution,
    pub sources: Vec<String>,
    /// model modules this pack uses besides `core`
    pub uses: Vec<String>,
    /// every field of a pack without kinds; the common fields of a pack with kinds
    pub fields: Vec<FieldDef>,
    /// common `when` lines (a pack with kinds only)
    pub whens: Vec<WhenDef>,
    pub kinds: Vec<KindDef>,
    /// common `const` lines
    pub consts: Vec<WhenDef>,
    /// common `default` lines
    pub defaults: Vec<DefaultDef>,
    /// common `group` blocks
    pub groups: Vec<GroupDef>,
    /// value tables: (table name, [(native, model)]) in `map` line order
    pub maps: Vec<(String, Vec<(String, String)>)>,
    pub typemap_to_cot: BTreeMap<String, String>,
    pub typemap_from_cot: BTreeMap<String, String>,
    /// bits only, `layout sequential` (engine-spec v0.8): the lines of the
    /// message, read in order from a cursor. `fields`, `kinds` and `groups`
    /// are then empty.
    pub seq: Option<seq::SeqBody>,
    /// text only: the delimiter, the start text and the checksum
    pub text: text::TextConf,
    /// tlv only: the tag and length encodings, the key and the checksum
    pub tlv: tlv::TlvConf,
    /// bits only: how the message travels as text (engine-spec v0.14)
    pub armor: armor::Armor,
    /// fixed `bits` layout: the gate blocks of common lines and of every kind
    /// (engine-spec v0.17)
    pub gates: Vec<GateDef>,
    /// xml only: common `element <path>` lines, (path, line) (engine-spec v0.18)
    pub elements: Vec<(String, usize)>,
    /// bits only, `layout sequential`: `encoding uper` (engine-spec v0.19)
    pub uper: bool,
}

fn bad<T>(ln: usize, m: impl AsRef<str>) -> Result<T, Error> {
    err(format!("bad-directive: line {}: {}", ln, m.as_ref()))
}

impl Pack {
    pub fn parse(text: &str) -> Result<Pack, Error> {
        pack_line_checks(text)?;
        // `layout sequential` (engine-spec v0.8) changes how every line is read
        // (only a line that holds both words can be that line: the rest are not tokenized twice)
        let sequential = text.lines().filter(|l| l.contains("layout") && l.contains("sequential")).any(|l| match tokenize(l) {
            Ok(t) => t.len() == 2 && t[0] == "layout" && t[1] == "sequential",
            Err(_) => false,
        });
        if sequential {
            return seq::parse(text);
        }
        let mut layout_line: Option<usize> = None;
        let mut format = None;
        let mut version = None;
        let mut wire = None;
        let mut root = String::new();
        let mut word_bytes = 0usize;
        let mut bit_order: Option<(BitOrder, usize)> = None;
        let mut distribution = None;
        let mut sources = Vec::new();
        let mut uses: Vec<String> = Vec::new();
        let mut fields: Vec<FieldDef> = Vec::new();
        let mut whens: Vec<WhenDef> = Vec::new();
        let mut kinds: Vec<KindDef> = Vec::new();
        let mut consts: Vec<WhenDef> = Vec::new();
        let mut defaults: Vec<DefaultDef> = Vec::new();
        let mut groups: Vec<GroupDef> = Vec::new();
        // `group` blocks not yet closed by `end`, innermost last
        let mut open: Vec<GroupDef> = Vec::new();
        // the gate blocks of common lines and kinds (engine-spec v0.17)
        let mut gates: Vec<GateDef> = Vec::new();
        // gate blocks not yet closed by `end`, innermost last: indices into
        // the gate table of the innermost open group, else into `gates` (a
        // gate block holds no `group`, so every open block is in that scope)
        let mut gate_stack: Vec<usize> = Vec::new();
        // common `element` lines (engine-spec v0.18)
        let mut elements: Vec<(String, usize)> = Vec::new();
        let mut maps: Vec<(String, Vec<(String, String)>)> = Vec::new();
        // table name -> its place in `maps`
        let mut map_index: HashMap<String, usize> = HashMap::new();
        // `root` lines inside a kind, to check against the wire once it is known
        let mut kind_root_line: Option<usize> = None;
        let mut to_cot = BTreeMap::new();
        let mut from_cot = BTreeMap::new();
        // text wire (engine-spec v0.10): `delimiter`, `start`, `checksum` and the line of each
        let mut text_conf = text::TextConf::default();
        let mut text_lines: [Option<usize>; 3] = [None; 3];
        // tlv wire (engine-spec v0.13): `tag`, `length`, `key`, `checksum sum16`
        let mut tlv_lines = tlv::TlvLines::default();
        // a transform that does not parse, while the wire may still be `tlv`
        // (ruling 8 of 0.13): (line, error), raised once the wire is known
        let mut bad_transform: Option<(usize, Error)> = None;
        // engine-spec v0.14: `armor`
        let mut armor_lines = armor::ArmorLines::default();
        // engine-spec v0.19: `encoding`, the first line only a UPER pack may
        // hold, and the `ext` and `choice` blocks open (all refused once the
        // file is read: this pack is not sequential)
        let mut encoding_lines = uper::EncodingLines::default();
        let mut uper_line: Option<usize> = None;
        let mut uper_open = 0usize;
        for (lineno, raw) in text.lines().enumerate() {
            let toks = tokenize(raw)?;
            if toks.is_empty() {
                continue;
            }
            let ln = lineno + 1;
            match toks[0].as_str() {
                // engine-spec v0.17: only these lines inside a gate block
                d if !gate_stack.is_empty() && !matches!(d, "field" | "const" | "default" | "if" | "end") => {
                    return bad(ln, format!("`{}` is not allowed inside a gate block", d));
                }
                // ruling 18 of 0.7: only these five directives inside a group
                // (ruling 24 of 0.8: the header directives among the rest),
                // and gate blocks (engine-spec v0.17)
                d if !open.is_empty() && !matches!(d, "field" | "const" | "default" | "group" | "if" | "end") => {
                    return bad(ln, format!("`{}` is not allowed inside a group", d));
                }
                "if" => {
                    if toks.len() != 3 {
                        return bad(ln, "a gate block needs `if [!]<word>:<pos>:<len> <value>[,<value>…]`");
                    }
                    let (negate, locator) = match toks[1].strip_prefix('!') {
                        Some(l) => (true, l.to_string()),
                        None => (false, toks[1].clone()),
                    };
                    let g = GateDef {
                        locator,
                        text: toks[2].clone(),
                        values: Vec::new(),
                        negate,
                        parent: gate_stack.last().copied(),
                        kind: if open.is_empty() { kinds.len().checked_sub(1) } else { None },
                        line: ln,
                    };
                    let table = match open.last_mut() {
                        Some(group) => &mut group.gates,
                        None => &mut gates,
                    };
                    table.push(g);
                    gate_stack.push(table.len() - 1);
                }
                // engine-spec v0.18: an element written when empty (xml)
                "element" => {
                    if toks.len() != 2 {
                        return bad(ln, "element needs <path>");
                    }
                    let path = &toks[1];
                    if path.is_empty() || path.split('/').any(|s| s.is_empty()) {
                        return bad(ln, format!("`element {}`: an empty path or an empty step", path));
                    }
                    // ruling 16 of 0.18: a step holding `@` or `#` anywhere
                    if path.contains('@') || path.contains('#') {
                        return bad(ln, format!("`element {}`: a path of element names takes no `@` or `#`", path));
                    }
                    let e = (path.clone(), ln);
                    match kinds.last_mut() {
                        Some(k) => k.elements.push(e),
                        None => elements.push(e),
                    }
                }
                "format" => format = Some(req_arg(&toks, 1, ln)?),
                "armor" => armor_lines.record(&toks, ln, !kinds.is_empty()),
                "encoding" => encoding_lines.record(&toks, ln, !kinds.is_empty()),
                d @ ("ext" | "choice" | "alt") => {
                    uper_line.get_or_insert(ln);
                    if d != "alt" {
                        uper_open += 1;
                    }
                }
                "end" if open.is_empty() && uper_open > 0 => uper_open -= 1,
                "tag" | "length" | "key" => tlv_lines.record(&toks, ln, !kinds.is_empty())?,
                "checksum" if toks.get(1).map(|s| s.as_str()) == Some("sum16") => tlv_lines.record(&toks, ln, !kinds.is_empty())?,
                d @ ("delimiter" | "start" | "checksum") => {
                    let slot = match d {
                        "delimiter" => 0,
                        "start" => 1,
                        _ => 2,
                    };
                    if !kinds.is_empty() {
                        return bad(ln, format!("`{}` stands before the first `kind`", d));
                    }
                    if text_lines[slot].is_some() {
                        return bad(ln, format!("`{}` given twice", d));
                    }
                    text_lines[slot] = Some(ln);
                    if toks.len() != 2 {
                        return bad(ln, format!("`{}` takes one value", d));
                    }
                    let v = toks[1].as_bytes();
                    let printable = |c: &u8| (0x21..=0x7e).contains(c);
                    match (d, toks[1].as_str()) {
                        ("delimiter", "none") => text_conf.delimiter = None,
                        ("delimiter", _) if v.len() == 1 && printable(&v[0]) && v[0] != b'"' => {
                            text_conf.delimiter = Some(v[0])
                        }
                        ("start", _) if !v.is_empty() && v.iter().all(printable) => text_conf.start = toks[1].clone(),
                        ("checksum", "none") => text_conf.nmea = false,
                        ("checksum", "nmea") => text_conf.nmea = true,
                        _ => return bad(ln, format!("`{} {}` is not a valid value", d, toks[1])),
                    }
                }
                "version" => version = Some(req_arg(&toks, 1, ln)?),
                "wire" => {
                    wire = Some(match req_arg(&toks, 1, ln)?.as_str() {
                        "xml" => Wire::Xml,
                        "geojson" => Wire::GeoJson,
                        "bits" => Wire::Bits,
                        "protobuf" => Wire::Protobuf,
                        "json" => Wire::Json,
                        "text" => Wire::Text,
                        "tlv" => Wire::Tlv,
                        o => return err(format!("unknown-wire: line {}: unknown wire `{}`", ln, o)),
                    })
                }
                "group" => {
                    if toks.len() < 3 {
                        return bad(ln, "group needs <list> <locator>");
                    }
                    let mut g = GroupDef {
                        list: toks[1].clone(),
                        locator: toks[2].clone(),
                        line: ln,
                        item_bits: None,
                        count: None,
                        fields: Vec::new(),
                        consts: Vec::new(),
                        defaults: Vec::new(),
                        groups: Vec::new(),
                        gates: Vec::new(),
                    };
                    let mut i = 3;
                    while i < toks.len() {
                        let arg = match toks.get(i + 1) {
                            Some(a) => a,
                            None => return bad(ln, format!("`{}` needs a value", toks[i])),
                        };
                        match toks[i].as_str() {
                            "item" if g.item_bits.is_none() => match arg.parse::<u64>() {
                                Ok(n) if n >= 1 && arg.bytes().all(|b| b.is_ascii_digit()) => g.item_bits = Some(n),
                                _ => return bad(ln, format!("`item` needs a bit count of at least 1, got `{}`", arg)),
                            },
                            "count" if g.count.is_none() => {
                                g.count = Some(if arg.bytes().all(|b| b.is_ascii_digit()) && !arg.is_empty() {
                                    match arg.parse::<u64>() {
                                        Ok(n) => Count::Fixed(n),
                                        Err(_) => return bad(ln, format!("`count {}` is too large", arg)),
                                    }
                                } else {
                                    Count::Locator(arg.clone())
                                })
                            }
                            o => return bad(ln, format!("unknown or repeated group option `{}`", o)),
                        }
                        i += 2;
                    }
                    open.push(g);
                }
                "end" => {
                    if toks.len() != 1 {
                        return bad(ln, "`end` takes no argument");
                    }
                    // the innermost open block: a gate block, else a group
                    if gate_stack.pop().is_some() {
                        continue;
                    }
                    let g = match open.pop() {
                        Some(g) => g,
                        None => return bad(ln, "`end` with no open group"),
                    };
                    match (open.last_mut(), kinds.last_mut()) {
                        (Some(outer), _) => outer.groups.push(g),
                        (None, Some(k)) => k.groups.push(g),
                        (None, None) => groups.push(g),
                    }
                }
                "root" => match kinds.last_mut() {
                    Some(k) => {
                        k.root = Some(req_arg(&toks, 1, ln)?);
                        kind_root_line.get_or_insert(ln);
                    }
                    None => root = req_arg(&toks, 1, ln)?,
                },
                "distribution" => {
                    let v = req_arg(&toks, 1, ln)?;
                    distribution = Some(Distribution::parse(&v).ok_or(Error {
                        msg: format!("bad-directive: line {}: distribution is `public` or `controlled`, got `{}`", ln, v),
                    })?)
                }
                "source" => sources.push(req_arg(&toks, 1, ln)?),
                "const" => {
                    if toks.len() != 3 {
                        return bad(ln, "const needs <locator> <value>");
                    }
                    let c = WhenDef {
                        locator: toks[1].clone(),
                        value: toks[2].clone(),
                        present: false,
                        text: String::new(),
                        forced: false,
                        num: 0,
                        line: ln,
                        gate: gate_stack.last().copied(),
                        nums: Vec::new(),
                        texts: Vec::new(),
                    };
                    match (open.last_mut(), kinds.last_mut()) {
                        (Some(g), _) => g.consts.push(c),
                        (None, Some(k)) => k.consts.push(c),
                        (None, None) => consts.push(c),
                    }
                }
                "default" => {
                    if toks.len() != 3 {
                        return bad(ln, "default needs <model-key> <value>");
                    }
                    let d = DefaultDef {
                        model_key: toks[1].clone(),
                        text: toks[2].clone(),
                        line: ln,
                        value: None,
                        gate: gate_stack.last().copied(),
                    };
                    match (open.last_mut(), kinds.last_mut()) {
                        (Some(g), _) => g.defaults.push(d),
                        (None, Some(k)) => k.defaults.push(d),
                        (None, None) => defaults.push(d),
                    }
                }
                "map" => {
                    if toks.len() != 4 {
                        return bad(ln, "map needs <table> <native> <model>");
                    }
                    let entry = (toks[2].clone(), toks[3].clone());
                    match map_index.get(&toks[1]) {
                        Some(i) => maps[*i].1.push(entry),
                        None => {
                            map_index.insert(toks[1].clone(), maps.len());
                            maps.push((toks[1].clone(), vec![entry]));
                        }
                    }
                }
                "uses" => {
                    let m = req_arg(&toks, 1, ln)?;
                    if !uses.contains(&m) {
                        uses.push(m);
                    }
                }
                "word_bytes" => {
                    // an unsigned decimal integer (ruling 2c of 0.11): `01` loads
                    word_bytes = match unsigned_text(&toks[1]).and_then(|n| usize::try_from(n).ok()) {
                        Some(n) => n,
                        None => return bad(ln, format!("word_bytes needs an unsigned decimal integer, got `{}`", toks[1])),
                    }
                }
                "bit_order" => {
                    if toks.len() != 2 {
                        return bad(ln, "bit_order needs `lsb`, `msb` or `msb-lsb`");
                    }
                    bit_order = Some(match BitOrder::parse(&toks[1]) {
                        Some(o) => (o, ln),
                        None => return bad(ln, format!("bit_order is `lsb`, `msb` or `msb-lsb`, got `{}`", toks[1])),
                    });
                }
                "kind" => {
                    if toks.len() != 2 {
                        return bad(ln, "kind needs <name>");
                    }
                    if kinds.iter().any(|k| k.name == toks[1]) {
                        return err(format!("duplicate-kind: line {}: kind `{}` declared twice", ln, toks[1]));
                    }
                    kinds.push(KindDef {
                        name: toks[1].clone(),
                        whens: Vec::new(),
                        requires: Vec::new(),
                        fields: Vec::new(),
                        consts: Vec::new(),
                        defaults: Vec::new(),
                        root: None,
                        groups: Vec::new(),
                        elements: Vec::new(),
                    });
                }
                "when" => {
                    if toks.len() != 3 {
                        return bad(ln, "when needs <locator> <value>");
                    }
                    let w = WhenDef {
                        locator: toks[1].clone(),
                        value: toks[2].clone(),
                        present: false,
                        text: String::new(),
                        forced: false,
                        num: 0,
                        line: ln,
                        gate: None,
                        nums: Vec::new(),
                        texts: Vec::new(),
                    };
                    match kinds.last_mut() {
                        Some(k) => k.whens.push(w),
                        None => whens.push(w),
                    }
                }
                "requires" => {
                    let k = match kinds.last_mut() {
                        Some(k) => k,
                        None => return bad(ln, "`requires` before the first `kind`"),
                    };
                    if toks.len() < 2 {
                        return bad(ln, "requires needs at least one <model-key>");
                    }
                    k.requires.extend(ReqDef::parse(&toks[1..], ln)?);
                }
                "field" => {
                    if toks.len() < 4 {
                        return bad(ln, "field needs <model-key> <locator> <transform> [options]");
                    }
                    let mut f = FieldDef {
                        model_key: toks[1].clone(),
                        locator: toks[2].clone(),
                        transform: match Transform::parse(&toks[3]) {
                            Ok(t) => t,
                            Err(e) if wire == Some(Wire::Tlv) => {
                                bad_transform.get_or_insert((ln, e));
                                Transform::Hex
                            }
                            Err(e) => return Err(e),
                        },
                        line: ln,
                        via: None,
                        swap: false,
                        trim: false,
                        optional: false,
                        key_type: None,
                        absent_arg: None,
                        absent: Vec::new(),
                        gate: gate_stack.last().copied(),
                        with: None,
                        until: None,
                        stop: None,
                        null: false,
                        implicit: false,
                        range: None,
                    };
                    // options after the transform, in any order (engine-spec v0.6)
                    field_options(&mut f, &toks, ln, true)?;
                    match (open.last_mut(), kinds.last_mut()) {
                        (Some(g), _) => g.fields.push(f),
                        (None, Some(k)) => k.fields.push(f),
                        (None, None) => fields.push(f),
                    }
                }
                "typemap" => {
                    if toks.len() != 3 {
                        return bad(ln, "typemap needs <native> <cot>");
                    }
                    to_cot.insert(toks[1].clone(), toks[2].clone());
                    from_cot.insert(toks[2].clone(), toks[1].clone());
                }
                "layout" => {
                    if toks.len() != 2 || toks[1] != "fixed" {
                        return bad(ln, "layout is `fixed` or `sequential`");
                    }
                    layout_line = Some(ln);
                }
                // engine-spec v0.8: a sequential line in a fixed-layout pack
                "pad" | "align" | "presence" | "opt" | "chain" | "fx" | "also" | "count" => {
                    return bad(ln, format!("`{}` is a line of a `layout sequential` pack", toks[0]));
                }
                // engine-spec v0.20: a switch reads a sequential layout
                "switch" | "case" | "else" => {
                    return bad(ln, format!("`{}` is valid only in a `layout sequential` pack", toks[0]));
                }
                other => return err(format!("unknown-directive: line {}: `{}` is not a directive of a pack", ln, other)),
            }
        }
        if let Some(i) = gate_stack.first() {
            let line = match open.last() {
                Some(g) => g.gates[*i].line,
                None => gates[*i].line,
            };
            return bad(line, "the gate block has no `end`");
        }
        if let Some(g) = open.first() {
            return bad(g.line, format!("group `{}` has no `end`", g.list));
        }
        // after the file is read (ruling 5b of 0.11): the missing header lines first
        if format.is_none() {
            return err("missing-format: the pack has no `format` line");
        }
        if version.is_none() {
            return err("missing-version: the pack has no `version` line");
        }
        let wire = wire.ok_or(Error { msg: "missing-wire: the pack has no `wire` line".into() })?;
        // ruling 8 of 0.13: on tlv a transform that does not parse is
        // `bad-directive`, checked after the file is read
        if let Some((ln, e)) = bad_transform {
            return match wire {
                Wire::Tlv => bad(ln, format!("the transform is not one of the tlv wire: {}", e.msg)),
                _ => Err(e),
            };
        }
        // engine-spec v0.17: gate blocks, on the fixed `bits` layout only
        // (those of group items are resolved with the rest of each body below)
        for g in gates.iter_mut() {
            resolve_gate(wire, g)?;
        }
        // xml: a pack-level root, unless every kind has its own (engine-spec v0.6)
        if wire == Wire::Xml && root.is_empty() && (kinds.is_empty() || kinds.iter().any(|k| k.root.is_none())) {
            return err("missing-root: an xml pack has no `root` for the pack or for one of its kinds");
        }
        // engine-spec v0.18: `element` on the xml wire only, never on or through
        // a group's path (ruling 12); a strict prefix of one is allowed
        {
            let every = elements.iter().chain(kinds.iter().flat_map(|k| k.elements.iter()));
            if let Some((_, ln)) = every.clone().min_by_key(|e| e.1) {
                if wire != Wire::Xml {
                    return bad(*ln, "`element` is valid only on the xml wire");
                }
            }
            let through = |path: &str, g: &GroupDef| path == g.locator || path.starts_with(&format!("{}/", g.locator));
            let mut clash: Option<usize> = None;
            for (path, ln) in &elements {
                if groups.iter().chain(kinds.iter().flat_map(|k| k.groups.iter())).any(|g| through(path, g)) {
                    clash = Some(clash.map_or(*ln, |c| c.min(*ln)));
                }
            }
            for k in &kinds {
                for (path, ln) in &k.elements {
                    if groups.iter().chain(k.groups.iter()).any(|g| through(path, g)) {
                        clash = Some(clash.map_or(*ln, |c| c.min(*ln)));
                    }
                }
            }
            if let Some(ln) = clash {
                return bad(ln, "an `element` path equals or passes through a group's path");
            }
        }
        if let Some(ln) = kind_root_line {
            if wire != Wire::Xml {
                return bad(ln, "`root` inside a kind is valid only on the xml wire");
            }
        }
        if wire == Wire::Bits && word_bytes == 0 {
            return err("bad-directive: a fixed-layout bits pack has no `word_bytes` line");
        }
        if let Some((_, ln)) = bit_order {
            if wire != Wire::Bits {
                return bad(ln, "`bit_order` is valid only on a bits wire");
            }
        }
        if wire == Wire::Text {
            if let (Some(ln), Some(d)) = (text_lines[1], text_conf.delimiter) {
                if text_conf.start.as_bytes().contains(&d) {
                    return bad(ln, "the `start` text holds the delimiter");
                }
            }
            if text_conf.nmea && text_conf.delimiter == Some(b'*') {
                return bad(text_lines[0].or(text_lines[2]).unwrap_or(0), "`delimiter \"*\"` with `checksum nmea`");
            }
        } else if let Some(ln) = text_lines.iter().flatten().min() {
            return bad(*ln, "`delimiter`, `start` and `checksum` are valid only on the text wire");
        }
        if let Some(ln) = layout_line {
            if wire != Wire::Bits {
                return bad(ln, "`layout` is valid only on a bits wire");
            }
        }
        if kinds.is_empty() {
            if let Some(w) = whens.first() {
                return bad(w.line, "`when` in a pack with no `kind`");
            }
        }
        // wire-dependent checks of the lines, now the wire is known
        let via_ok = |f: &FieldDef| -> Result<(), Error> {
            match &f.via {
                Some(t) if !map_index.contains_key(t) => {
                    bad(f.line, format!("`via {}` names a table with no `map` line", t))
                }
                _ => Ok(()),
            }
        };
        for f in fields.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.fields.iter_mut())) {
            check_field_for_wire(wire, f, false)?;
            via_ok(f)?;
            resolve_absent(wire, f, fixed_bits_len(wire, f))?;
        }
        for w in whens.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.whens.iter_mut())) {
            resolve_when(wire, w, false, true)?;
        }
        let no_present = |c: &WhenDef| -> Result<(), Error> {
            if c.present {
                return bad(c.line, "a `const` value cannot be `present`; write `=present` for the text");
            }
            Ok(())
        };
        for c in consts.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.consts.iter_mut())) {
            resolve_when(wire, c, false, false)?;
            no_present(c)?;
        }
        // groups (engine-spec v0.7): the lines of every body, then each scope
        let mut first: Result<(), Error> = Ok(());
        for g in groups.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.groups.iter_mut())) {
            g.walk_mut(&mut |g| {
                if first.is_err() {
                    return;
                }
                first = (|| {
                    for gate in g.gates.iter_mut() {
                        resolve_gate(wire, gate)?;
                    }
                    check_group_for_wire(wire, g)?;
                    if wire == Wire::Bits {
                        check_item_bounds(word_bytes, g)?;
                    }
                    for f in g.fields.iter_mut() {
                        check_field_for_wire(wire, f, true)?;
                        via_ok(f)?;
                        resolve_absent(wire, f, fixed_bits_len(wire, f))?;
                    }
                    for c in g.consts.iter_mut() {
                        resolve_when(wire, c, true, false)?;
                        no_present(c)?;
                    }
                    Ok(())
                })();
            });
        }
        first?;
        {
            fn lines<'a>(fs: &'a [FieldDef], ws: &'a [WhenDef], cs: &'a [WhenDef]) -> Vec<(usize, &'a str)> {
                fs.iter()
                    .map(|f| (f.line, f.locator.as_str()))
                    .chain(ws.iter().chain(cs.iter()).map(|w| (w.line, w.locator.as_str())))
                    .collect()
            }
            let mut common = lines(&fields, &whens, &consts);
            // a gate locator lies in its scope as a field does (ruling 2 of 0.17)
            let gate_lines = |kind: Option<usize>| -> Vec<(usize, &str)> {
                gates.iter().filter(|g| g.kind == kind).map(|g| (g.line, g.locator.as_str())).collect()
            };
            common.extend(gate_lines(None));
            let common_fields = lines(&fields, &[], &[]);
            if kinds.is_empty() {
                let gs: Vec<&GroupDef> = groups.iter().collect();
                check_scope(wire, word_bytes, &common, &common_fields, &gs)?;
                check_gates_off_items(word_bytes, &gate_lines(None), &gs)?;
            }
            for (ki, k) in kinds.iter().enumerate() {
                let mut ls = common.clone();
                ls.extend(lines(&k.fields, &k.whens, &k.consts));
                ls.extend(gate_lines(Some(ki)));
                let mut fs = common_fields.clone();
                fs.extend(lines(&k.fields, &[], &[]));
                let gs: Vec<&GroupDef> = groups.iter().chain(k.groups.iter()).collect();
                check_scope(wire, word_bytes, &ls, &fs, &gs)?;
                let mut gl = gate_lines(None);
                gl.extend(gate_lines(Some(ki)));
                check_gates_off_items(word_bytes, &gl, &gs)?;
            }
            let mut every: Vec<&GroupDef> = Vec::new();
            for g in groups.iter().chain(kinds.iter().flat_map(|k| k.groups.iter())) {
                g.walk(&mut every);
            }
            for g in every {
                let mut ls = lines(&g.fields, &[], &g.consts);
                let gl: Vec<(usize, &str)> = g.gates.iter().map(|x| (x.line, x.locator.as_str())).collect();
                ls.extend(gl.iter().copied());
                let gs: Vec<&GroupDef> = g.groups.iter().collect();
                check_scope(wire, word_bytes, &ls, &lines(&g.fields, &[], &[]), &gs)?;
                check_gates_off_items(word_bytes, &gl, &gs)?;
            }
        }
        if wire == Wire::Text {
            text::check_pack(&text_conf, &fields, &whens, &consts, &groups, &kinds)?;
        }
        let format = format.expect("checked above");
        let tlv_conf = match (wire, tlv_lines.first_line()) {
            (Wire::Tlv, _) => tlv::check_pack(&tlv_lines, &fields, &whens, &consts, &groups, &kinds)?,
            (_, Some(ln)) => return bad(ln, "`tag`, `length`, `key` and `checksum sum16` are valid only on the tlv wire"),
            _ => tlv::TlvConf::default(),
        };
        // `armor sixbit` and `encoding uper` need `bit_order msb` (0.14, 0.19); `msb-lsb` is not `msb`
        let msb = bit_order.map_or(false, |(o, _)| o == BitOrder::Msb);
        let armor = armor_lines.check(wire == Wire::Bits, msb)?;
        encoding_lines.check(wire == Wire::Bits, false, msb, armor == armor::Armor::Sixbit)?;
        if let Some(ln) = uper_line {
            return bad(ln, "`ext`, `choice` and `alt` are lines of a pack with `encoding uper`");
        }
        let distribution = distribution.ok_or(Error {
            msg: format!("missing-distribution: pack `{}` has no `distribution`", format),
        })?;
        if sources.is_empty() {
            return err(format!("missing-source: pack `{}` has no `source`", format));
        }
        Ok(Pack {
            format,
            version: version.expect("checked above"),
            wire,
            root,
            word_bytes,
            order: bit_order.map(|(m, _)| m).unwrap_or(BitOrder::Lsb),
            distribution,
            sources,
            uses,
            fields,
            whens,
            kinds,
            consts,
            defaults,
            groups,
            maps,
            typemap_to_cot: to_cot,
            typemap_from_cot: from_cot,
            seq: None,
            text: text_conf,
            tlv: tlv_conf,
            armor,
            gates,
            elements,
            uper: false,
        })
    }

    /// The lines in force when `kind` is selected (None: a pack without kinds).
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn sel<'a>(&'a self, kind: Option<&'a KindDef>) -> Sel<'a> {
        let mut fields: Vec<&FieldDef> = self.fields.iter().collect();
        let mut whens: Vec<&WhenDef> = self.whens.iter().collect();
        let mut consts: Vec<&WhenDef> = self.consts.iter().collect();
        let mut defaults: Vec<&DefaultDef> = Vec::new();
        let mut groups: Vec<&GroupDef> = self.groups.iter().collect();
        let mut elements: Vec<&(String, usize)> = self.elements.iter().collect();
        let mut root = self.root.as_str();
        if let Some(k) = kind {
            groups.extend(k.groups.iter());
            elements.extend(k.elements.iter());
            fields.extend(k.fields.iter());
            whens.extend(k.whens.iter());
            consts.extend(k.consts.iter());
            defaults.extend(k.defaults.iter());
            if let Some(r) = &k.root {
                root = r;
            }
        }
        defaults.extend(self.defaults.iter());
        Sel { kind, fields, whens, consts, defaults, groups, root, gates: &self.gates, elements }
    }

    /// Decode-side kind selection: `holds` says whether a `when` matches the
    /// wire. `root` is the document's root element (xml): a kind is considered
    /// only when its root, or the pack's, has that name.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn select_decode<'a>(&'a self, root: Option<&str>, holds: impl Fn(&WhenDef) -> bool) -> Result<Sel<'a>, Error> {
        if self.kinds.is_empty() {
            return Ok(self.sel(None));
        }
        if let Some(w) = self.whens.iter().find(|w| !holds(w)) {
            return err(format!(
                "no-kind: format `{}`: common `when {} {}` does not hold",
                self.format, w.locator, w.value
            ));
        }
        let root_ok = |k: &KindDef| match root {
            Some(r) => k.root.as_deref().unwrap_or(&self.root) == r,
            None => true,
        };
        match self.kinds.iter().find(|k| root_ok(k) && k.whens.iter().all(|w| holds(w))) {
            Some(k) => Ok(self.sel(Some(k))),
            None => err(format!("no-kind: format `{}`: the message matches no kind", self.format)),
        }
    }

    /// Encode-side kind selection: the entity's own kind for this format, else
    /// the first kind whose `requires` keys are all present.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn select_encode<'a>(&'a self, ent: &Entity) -> Result<Sel<'a>, Error> {
        if self.kinds.is_empty() {
            return Ok(self.sel(None));
        }
        if let Some((fmt, name)) = &ent.kind {
            if fmt == &self.format {
                return match self.kinds.iter().find(|k| &k.name == name) {
                    Some(k) => Ok(self.sel(Some(k))),
                    None => err(format!("no-kind: format `{}` has no kind `{}`", self.format, name)),
                };
            }
        }
        match self
            .kinds
            .iter()
            // a key that is present, or a list that has at least one item; a
            // key with `=` that holds a listed value (engine-spec v0.20)
            .find(|k| k.requires.iter().all(|r| r.holds(ent)))
        {
            Some(k) => Ok(self.sel(Some(k))),
            None => err(format!(
                "no-kind: format `{}`: the entity has the required keys of no kind",
                self.format
            )),
        }
    }

    fn table(&self, name: &str) -> &[(String, String)] {
        self.maps.iter().find(|(n, _)| n == name).map(|(_, e)| e.as_slice()).unwrap_or(&[])
    }

    /// Decode: the value a transform yielded, on its way to the model. A
    /// `via` table (engine-spec v0.6), else the pack-wide typemap for `type`
    /// (every wire: ruling 18 of 0.5).
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn to_model(&self, f: &FieldDef, v: Value) -> Result<Value, Error> {
        if let Some(t) = &f.via {
            let native_ty = f.transform.value_type();
            let key_ty = f.key_type.unwrap_or(native_ty);
            let text = v.as_display();
            let model = match self.table(t).iter().find(|(native, _)| canon_text(native_ty, native) == text) {
                Some((_, model)) => read_as(key_ty, model)
                    .ok_or(Error { msg: format!("table `{}`: `{}` is not a {}", t, model, key_ty.name()) })?,
                None if native_ty == key_ty => v,
                None => return err(format!("table `{}` has no entry for wire value `{}`", t, text)),
            };
            // the table, then the typemap (ruling 6 of 0.6)
            return Ok(self.typemap_in(f, model));
        }
        Ok(self.typemap_in(f, v))
    }

    /// Decode: the pack-wide typemap, applied to the key `type`.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn typemap_in(&self, f: &FieldDef, v: Value) -> Value {
        if f.model_key == "type" {
            if let Value::Str(code) = &v {
                if let Some(cot) = self.typemap_to_cot.get(code) {
                    return Value::Str(cot.clone());
                }
            }
        }
        v
    }

    /// Encode: a model value on its way to the transform (the reverse of `to_model`).
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn to_wire(&self, f: &FieldDef, v: &Value) -> Result<Value, Error> {
        // the typemap, then the table (ruling 6 of 0.6)
        let mapped = match v {
            Value::Str(cot) if f.model_key == "type" => self.typemap_from_cot.get(cot).map(|n| Value::Str(n.clone())),
            _ => None,
        };
        let v = mapped.as_ref().unwrap_or(v);
        // engine-spec v0.56: the range is checked, or the value wrapped, before `via`
        let ranged;
        let v = match f.range.as_ref().and_then(|r| r.val.map(|rv| (rv, r.wrap))) {
            Some((rv, wrap)) => {
                ranged = rv.apply(wrap, v)?;
                &ranged
            }
            None => v,
        };
        if let Some(t) = &f.via {
            let native_ty = f.transform.value_type();
            let key_ty = f.key_type.unwrap_or(native_ty);
            let text = v.as_display();
            return match self.table(t).iter().find(|(_, model)| canon_text(key_ty, model) == text) {
                Some((native, _)) => read_as(native_ty, native)
                    .ok_or(Error { msg: format!("table `{}`: `{}` is not a {}", t, native, native_ty.name()) }),
                None if native_ty == key_ty => Ok(v.clone()),
                None => err(format!("table `{}` has no entry for model value `{}`", t, text)),
            };
        }
        Ok(v.clone())
    }

    /// The type of a table's `<model>` side: `int` when every value is an
    /// integer, `float` when every value is a number, else `string`.
    fn table_model_type(&self, name: &str) -> KeyType {
        let entries = self.table(name);
        if entries.iter().all(|(_, m)| read_as(KeyType::Int, m).is_some()) {
            KeyType::Int
        } else if entries.iter().all(|(_, m)| read_as(KeyType::Float, m).is_some()) {
            KeyType::Float
        } else {
            KeyType::Str
        }
    }

    /// The model keys this pack maps: union over common and every kind, in
    /// first appearance order. A list is `<list>[]`, an item key
    /// `<list>[].<key>`, nested lists likewise (engine-spec v0.7).
    pub fn model_keys(&self) -> Vec<String> {
        fn scope(prefix: &str, fields: &[FieldDef], groups: &[GroupDef], out: &mut Vec<String>) {
            let mut lines: Vec<(usize, Option<&FieldDef>, Option<&GroupDef>)> = fields
                .iter()
                .map(|f| (f.line, Some(f), None))
                .chain(groups.iter().map(|g| (g.line, None, Some(g))))
                .collect();
            lines.sort_by_key(|l| l.0);
            let add = |out: &mut Vec<String>, name: String| {
                if !out.contains(&name) {
                    out.push(name);
                }
            };
            for (_, f, g) in lines {
                if let Some(f) = f {
                    add(out, format!("{}{}", prefix, f.model_key));
                }
                if let Some(g) = g {
                    add(out, format!("{}{}[]", prefix, g.list));
                    scope(&format!("{}{}[].", prefix, g.list), &g.fields, &g.groups, out);
                }
            }
        }
        let mut out: Vec<String> = Vec::new();
        scope("", &self.fields, &self.groups, &mut out);
        for k in &self.kinds {
            scope("", &k.fields, &k.groups, &mut out);
        }
        if let Some(body) = &self.seq {
            body.model_keys("", &mut out);
        }
        out
    }

    /// Every `group` line of the pack: (line, list name).
    fn group_lists(&self) -> Vec<(usize, &str)> {
        let mut out: Vec<(usize, &str)> = self.every_group().into_iter().map(|g| (g.line, g.list.as_str())).collect();
        if let Some(body) = &self.seq {
            body.visit(&mut |v| {
                if let seq::Visit::Group(line, list) = v {
                    out.push((line, list));
                }
            });
        }
        out
    }

    /// Every `requires` key of the pack: (line, key).
    fn every_requires(&self) -> Vec<(usize, &str)> {
        self.every_require_def().into_iter().map(|r| (r.line, r.key.as_str())).collect()
    }

    /// Every `requires` term of the pack, in line order.
    fn every_require_def(&self) -> Vec<&ReqDef> {
        let mut out: Vec<&ReqDef> = self.kinds.iter().flat_map(|k| k.requires.iter()).collect();
        if let Some(body) = &self.seq {
            body.visit(&mut |v| {
                if let seq::Visit::Requires(r) = v {
                    out.push(r);
                }
            });
        }
        out.sort_by_key(|r| r.line);
        out
    }

    /// Every `group` block of the pack, nested ones included.
    fn every_group(&self) -> Vec<&GroupDef> {
        let mut out = Vec::new();
        for g in self.groups.iter().chain(self.kinds.iter().flat_map(|k| k.groups.iter())) {
            g.walk(&mut out);
        }
        out
    }

    /// Every `field` line of the pack: common, kinds and group bodies.
    fn every_field(&self) -> Vec<&FieldDef> {
        let mut out: Vec<&FieldDef> = self.fields.iter().chain(self.kinds.iter().flat_map(|k| k.fields.iter())).collect();
        out.extend(self.every_group().into_iter().flat_map(|g| g.fields.iter()));
        if let Some(body) = &self.seq {
            body.visit(&mut |v| {
                if let seq::Visit::Field(f) = v {
                    out.push(f);
                }
            });
        }
        out
    }

    /// Every `default` line of the pack: common, kinds and group bodies.
    fn every_default(&self) -> Vec<&DefaultDef> {
        let mut out: Vec<&DefaultDef> =
            self.defaults.iter().chain(self.kinds.iter().flat_map(|k| k.defaults.iter())).collect();
        out.extend(self.every_group().into_iter().flat_map(|g| g.defaults.iter()));
        if let Some(body) = &self.seq {
            body.visit(&mut |v| {
                if let seq::Visit::Default(d) = v {
                    out.push(d);
                }
            });
        }
        out
    }

    /// Apply `f` to every group of the pack, nested ones included.
    fn every_group_mut(&mut self, f: &mut dyn FnMut(&mut GroupDef)) {
        for g in self.groups.iter_mut().chain(self.kinds.iter_mut().flat_map(|k| k.groups.iter_mut())) {
            g.walk_mut(f);
        }
    }
}

#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
fn transform_encode_err(p: &Pack, f: &FieldDef, e: Error) -> Error {
    Error {
        msg: format!("transform-encode: format `{}`: `{}` at `{}`: {}", p.format, f.model_key, f.locator, e.msg),
    }
}

/// Read table or pack text as a value of the given type. None when it is not one.
/// Integers and numbers by the grammars of ruling 2 of 0.11.
fn read_as(ty: KeyType, text: &str) -> Option<Value> {
    match ty {
        KeyType::Str => Some(Value::Str(text.to_string())),
        KeyType::Int => int_text(text).map(Value::I64),
        KeyType::Float => number_text(text).map(Value::F64),
    }
}

/// Table text in the canonical form a value of that type is compared in.
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
fn canon_text(ty: KeyType, text: &str) -> String {
    match ty {
        KeyType::Str => text.to_string(),
        _ => read_as(ty, text).map(|v| v.as_display()).unwrap_or_else(|| text.to_string()),
    }
}

/// The limit on list items of one decode (ruling 7 of 0.11): every item of
/// every list the decoded entity holds, at every nesting level, counts one.
pub const DEFAULT_MAX_ITEMS: usize = 100_000;

pub(crate) mod limit {
    #[allow(unused_imports)]
    use super::{err, Entity, Error};
    use std::cell::Cell;

    thread_local! {
        /// (items held, the limit), while a decode runs on this thread
        static STATE: Cell<Option<(u64, u64)>> = const { Cell::new(None) };
    }

    /// Ends the decode's count when dropped, if it began it.
    pub struct Scope(bool);
    impl Drop for Scope {
        fn drop(&mut self) {
            if self.0 {
                STATE.with(|s| s.set(None));
            }
        }
    }

    /// Begin counting the items of one decode with this limit. Inside a
    /// decode already counting (a wire decoder called by the engine), the
    /// count of that decode goes on.
    pub fn begin(max: usize) -> Scope {
        STATE.with(|s| {
            if s.get().is_some() {
                Scope(false)
            } else {
                s.set(Some((0, max as u64)));
                Scope(true)
            }
        })
    }

    /// A decode called without the engine: the default limit.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]
    pub fn scope() -> Scope {
        begin(super::DEFAULT_MAX_ITEMS)
    }

    /// Hold `n` more items: past the limit is `malformed-wire` (7a, 7f).
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]
    pub fn take(format: &str, list: &str, n: u64) -> Result<(), Error> {
        STATE.with(|s| match s.get() {
            None => Ok(()),
            Some((held, max)) => {
                if n > max.saturating_sub(held) {
                    return err(format!(
                        "malformed-wire: format `{}`: list `{}` would take the decode beyond its limit of {} list items",
                        format, list, max
                    ));
                }
                s.set(Some((held + n, max)));
                Ok(())
            }
        })
    }

    /// The items of every list of an entity, at every nesting level.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]
    pub fn items_of(lists: &std::collections::BTreeMap<String, Vec<Entity>>) -> u64 {
        lists.values().map(|items| items.len() as u64 + items.iter().map(|i| items_of(&i.lists)).sum::<u64>()).sum()
    }

    /// The entity no longer holds `n` items: a later group replaces the
    /// list they were in (7g).
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]
    pub fn release(n: u64) {
        STATE.with(|s| {
            if let Some((held, max)) = s.get() {
                s.set(Some((held.saturating_sub(n), max)));
            }
        });
    }
}

/// The fields of one decode. A key takes the value of the earliest line whose
/// locator is present and whose transform succeeds (engine-spec v0.6); a key
/// with a failed line and no value fails the decode (ruling 9 of 0.1.1). A line
/// whose transform succeeds and whose table refuses the value fails the decode
/// whatever the other lines of the key do (ruling 4 of 0.6).
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
struct Decoded {
    ent: Entity,
    /// (key, message): a transform failed; an error unless the key gets a value
    soft: Vec<(String, String)>,
    /// a table refused a value, or an item failed
    hard: Vec<String>,
    hard_keys: Vec<String>,
}
#[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
impl Decoded {
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn new() -> Decoded {
        Decoded { ent: Entity::default(), soft: Vec::new(), hard: Vec::new(), hard_keys: Vec::new() }
    }
    /// Before the items of a group are read: the items of a list the group
    /// will replace are no longer held (ruling 7g of 0.11).
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]
    fn replacing(&self, list: &str) {
        if let Some(old) = self.ent.lists.get(list) {
            limit::release(old.len() as u64 + old.iter().map(|i| limit::items_of(&i.lists)).sum::<u64>());
        }
    }
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn has(&self, f: &FieldDef) -> bool {
        self.ent.fields.contains_key(&f.model_key)
    }
    /// One line whose locator is present: the transform's result, through the table.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn put(&mut self, p: &Pack, f: &FieldDef, v: Result<Value, Error>) {
        if self.has(f) || self.hard_keys.contains(&f.model_key) {
            return;
        }
        let at = |e: Error| format!("`{}` at `{}`: {}", f.model_key, f.locator, e.msg);
        match v {
            Err(e) => self.soft.push((f.model_key.clone(), at(e))),
            Ok(v) => match p.to_model(f, v) {
                Ok(v) => {
                    self.ent.fields.insert(f.model_key.clone(), v);
                }
                Err(e) => {
                    self.hard_keys.push(f.model_key.clone());
                    self.hard.push(at(e));
                }
            },
        }
    }
    /// The entity so far and every failure that stands.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn close(self) -> (Entity, Vec<String>) {
        let ent = self.ent;
        let mut failed: Vec<String> =
            self.soft.into_iter().filter(|(k, _)| !ent.fields.contains_key(k)).map(|(_, m)| m).collect();
        failed.extend(self.hard);
        (ent, failed)
    }
    /// Take the decoded items of a list: a failed item field fails the decode.
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text"))]
    fn put_list(&mut self, list: &str, items: Vec<Decoded>) {
        let mut out = Vec::new();
        for (i, item) in items.into_iter().enumerate() {
            let (ent, failed) = item.close();
            self.hard.extend(failed.into_iter().map(|m| format!("{}[{}]: {}", list, i, m)));
            out.push(ent);
        }
        self.ent.lists.insert(list.to_string(), out);
    }
    #[cfg(any(feature = "xml", feature = "geojson", feature = "json", feature = "bits", feature = "protobuf", feature = "text", feature = "tlv"))]
    fn finish(self, p: &Pack, sel: &Sel) -> Result<Entity, Error> {
        let (mut ent, failed) = self.close();
        if !failed.is_empty() {
            return err(format!("transform-decode: format `{}`: {}", p.format, failed.join("; ")));
        }
        ent.kind = sel.kind.map(|k| (p.format.clone(), k.name.clone()));
        Ok(ent)
    }
}

/// The bit length of a field of a fixed-layout `bits` pack; None on other wires.
fn fixed_bits_len(wire: Wire, f: &FieldDef) -> Option<u32> {
    match wire {
        Wire::Bits => bits::parse_locator(&f.locator).ok().map(|(_, _, len)| len),
        _ => None,
    }
}

/// Load checks a `field` line owes its wire (engine-spec v0.5).
fn check_field_for_wire(wire: Wire, f: &FieldDef, in_group: bool) -> Result<(), Error> {
    let t = &f.transform;
    if (f.swap || f.trim) && wire != Wire::Bits {
        return bad(f.line, "`swap` and `trim` are valid only on a bits wire");
    }
    if f.optional && !matches!(wire, Wire::Bits | Wire::Text) {
        return bad(f.line, "`optional` is valid only on the bits and text wires");
    }
    // engine-spec v0.56: `null` on json and geojson, not on a `geometry` locator
    if f.null && (!matches!(wire, Wire::Json | Wire::GeoJson) || (wire == Wire::GeoJson && f.locator.starts_with("geometry."))) {
        return bad(f.line, "`null` is valid only on json and on geojson members outside `geometry`");
    }
    // engine-spec v0.56: `implicit` on a protobuf scalar that is not an item
    if f.implicit {
        if wire != Wire::Protobuf || !f.transform.is_protobuf() {
            return bad(f.line, "`implicit` is valid only on protobuf with pvarint, psint, pdouble, pfloat or pstring");
        }
        if in_group && f.locator == "." {
            return bad(f.line, "`implicit` is not valid on a scalar item of a group");
        }
    }
    // engine-spec v0.10: the text wire's own transforms, and the transforms it takes
    // engine-spec v0.13: the tlv wire's own transforms, and the transforms it takes
    tlv::check_transform(wire, f)?;
    if t.is_text_only() && wire != Wire::Text {
        return bad(f.line, format!("the transform of `{}` is valid only on the text wire", f.model_key));
    }
    if wire == Wire::Text && !text::valid_on_text(t) {
        return bad(f.line, format!("the transform of `{}` is not valid on the text wire", f.model_key));
    }
    if f.trim && !matches!(t, Transform::Ascii | Transform::Sixbit | Transform::Utf8) {
        return bad(f.line, "`trim` is valid only with `ascii`, `sixbit` or `utf8`");
    }
    // engine-spec v0.14
    if *t == Transform::Sixbit && wire != Wire::Bits {
        return bad(f.line, "`sixbit` is valid only on a bits wire");
    }
    if *t == Transform::Bool && wire != Wire::Json {
        return bad(f.line, "`bool` is valid only on the json wire");
    }
    // engine-spec v0.15: each value transform on the wires it lists
    let v015_bits = t.is_bits()
        && !matches!(
            t,
            Transform::Uint
                | Transform::Twos
                | Transform::Linscale(_, _)
                | Transform::Uscale(_)
                | Transform::Sscale(_)
                | Transform::F32
                | Transform::F64
                | Transform::Ascii
                | Transform::Sixbit
                // `hex` and `utf8` are tlv transforms too (engine-spec v0.13, v0.22, v0.55)
                | Transform::Hex
                | Transform::Utf8
        );
    if v015_bits && wire != Wire::Bits {
        return bad(f.line, format!("the transform of `{}` is valid only on a bits wire", f.model_key));
    }
    if t.is_text_scale() && !matches!(wire, Wire::Xml | Wire::Json | Wire::GeoJson) {
        return bad(f.line, format!("the transform of `{}` is valid only on xml, json and geojson", f.model_key));
    }
    if f.swap && t.refuses_swap() {
        return bad(f.line, "`swap` is not valid with `chars`, `octal` or `hex`");
    }
    // ruling 5 of 0.11: a transform on a wire it is not valid for
    let valid = match wire {
        Wire::Xml | Wire::GeoJson => {
            matches!(
                t,
                Transform::StringT
                    | Transform::Float
                    | Transform::Int
                    | Transform::Iso8601Ms
                    | Transform::Iso8601Short
                    | Transform::Iso8601Si
                    | Transform::TextScale(_)
                    | Transform::TextIscale(_)
            )
        }
        Wire::Bits => t.is_bits(),
        Wire::Protobuf => t.is_protobuf(),
        // text and tlv: checked above, against their own tables
        Wire::Json | Wire::Text | Wire::Tlv => true,
    };
    if !valid {
        return bad(f.line, format!("the transform of `{}` is not valid on this wire", f.model_key));
    }
    // ruling 11 of 0.18: `iso8601_short` on xml, json and geojson only
    if *t == Transform::Iso8601Short && !matches!(wire, Wire::Xml | Wire::Json | Wire::GeoJson) {
        return bad(f.line, format!("`iso8601_short` of `{}` is valid only on xml, json and geojson", f.model_key));
    }
    // engine-spec v0.55: `iso8601_si` likewise
    if *t == Transform::Iso8601Si && !matches!(wire, Wire::Xml | Wire::Json | Wire::GeoJson) {
        return bad(f.line, format!("`iso8601_si` of `{}` is valid only on xml, json and geojson", f.model_key));
    }
    // inside a group `.` is the item itself (json, geojson, protobuf)
    let item_itself = in_group && f.locator == ".";
    match wire {
        Wire::Json => {
            if !matches!(
                t,
                Transform::StringT
                    | Transform::Float
                    | Transform::Int
                    | Transform::Iso8601Ms
                    | Transform::Iso8601Short
                    | Transform::Iso8601Si
                    | Transform::Bool
                    | Transform::TextScale(_)
                    | Transform::TextIscale(_)
            ) {
                return bad(f.line, format!("transform of `{}` is not valid on the json wire", f.model_key));
            }
            if !item_itself && (f.locator.is_empty() || f.locator.split('.').any(|s| s.is_empty())) {
                return bad(f.line, format!("bad json path `{}`", f.locator));
            }
        }
        Wire::GeoJson if in_group => {
            if !item_itself && (f.locator.is_empty() || f.locator.split('.').any(|s| s.is_empty())) {
                return bad(f.line, format!("bad member path `{}`", f.locator));
            }
        }
        Wire::Protobuf if in_group => {
            if !item_itself {
                protobuf::parse_path(&f.locator)
                    .map_err(|e| Error { msg: format!("bad-directive: line {}: {}", f.line, e.msg) })?;
            }
        }
        Wire::Bits => {
            let (_, _, len) = bits::parse_locator(&f.locator)
                .map_err(|e| Error { msg: format!("bad-directive: line {}: {}", f.line, e.msg) })?;
            if !t.bits_len_ok(len) {
                return bad(f.line, format!("bit length {} is not allowed for the transform of `{}`", len, f.model_key));
            }
            if f.swap && *t == Transform::Sixbit {
                return bad(f.line, "`swap` is not valid on `sixbit`");
            }
            if f.swap && len % 8 != 0 {
                return bad(f.line, format!("`swap` needs a bit length that is a multiple of 8, got {}", len));
            }
        }
        _ => {}
    }
    Ok(())
}

/// `bits` item bounds (ruling 4 of 0.7): a field or `const` of an item, or a
/// nested group with a fixed count, may not reach beyond `item <bits>`. A
/// nested group counted by a locator may: the next item starts where it ends.
fn check_item_bounds(word_bytes: usize, g: &GroupDef) -> Result<(), Error> {
    let wb = word_bytes as u64 * 8;
    let room = g.item_bits.unwrap_or(0);
    let gates = g.gates.iter().map(|x| (x.line, &x.locator));
    for (line, loc) in g.fields.iter().map(|f| (f.line, &f.locator)).chain(g.consts.iter().map(|c| (c.line, &c.locator))).chain(gates) {
        if let Ok((w, p, l)) = bits::parse_locator(loc) {
            if w as u64 * wb + p as u64 + l as u64 > room {
                return bad(line, format!("`{}` reaches beyond the {} bits of an item of `{}`", loc, room, g.list));
            }
        }
    }
    for n in &g.groups {
        // a nested group's count locator is bounded as a field is (ruling 15 of 0.7)
        if let Some(Count::Locator(l)) = &n.count {
            if let Ok((w, p, len)) = bits::parse_locator(l) {
                if w as u64 * wb + p as u64 + len as u64 > room {
                    return bad(n.line, format!("the count `{}` reaches beyond the {} bits of an item of `{}`", l, room, g.list));
                }
            }
        }
        if let (Some(Count::Fixed(count)), Ok((w, p))) = (&n.count, bits::parse_group_locator(&n.locator)) {
            let end = count.saturating_mul(n.item_bits.unwrap_or(0)).saturating_add(w as u64 * wb + p as u64);
            if end > room {
                return bad(n.line, format!("group `{}` reaches beyond the {} bits of an item of `{}`", n.list, room, g.list));
            }
        }
    }
    Ok(())
}

/// Load checks a `group` line owes its wire (engine-spec v0.7).
fn check_group_for_wire(wire: Wire, g: &GroupDef) -> Result<(), Error> {
    let names = |sep: char| !g.locator.is_empty() && g.locator.split(sep).all(|s| !s.is_empty());
    if wire != Wire::Bits {
        if g.count.is_some() {
            return bad(g.line, "`count` is valid only on a bits wire");
        }
        if g.item_bits.is_some() && wire != Wire::Text {
            return bad(g.line, "`item` is valid only on a bits wire");
        }
    }
    let ok = match wire {
        Wire::Tlv => return bad(g.line, "`group` is not valid on the tlv wire in 0.13"),
        Wire::Xml => names('/') && !g.locator.contains('@') && !g.locator.contains('#'),
        Wire::Json => names('.'),
        // engine-spec v0.10: `group <list> <i> item <n>`
        Wire::Text => {
            if g.item_bits.is_none() {
                return bad(g.line, "a group on the text wire needs `item <n>`");
            }
            text::check_group_locator(g)?;
            true
        }
        Wire::GeoJson => {
            names('.') && !g.locator.starts_with("geometry.") && (!g.locator.contains('.') || g.locator.starts_with("properties."))
        }
        Wire::Protobuf => {
            // ruling 13 of 0.7: a body mixing `.` with paths
            if g.scalar().is_some() && (g.fields.iter().any(|f| f.locator != ".") || !g.consts.is_empty() || !g.groups.is_empty())
            {
                return bad(g.line, format!("the body of group `{}` mixes `.` with paths", g.list));
            }
            // ruling 4 of 0.18: `with` on the `.` field of a packed group
            // (ruling 17: a packed group's body is `.` fields with a numeric transform only)
            let packed = !g.fields.is_empty() && g.fields.iter().all(|f| f.locator == "." && protobuf::numeric(&f.transform));
            if let Some(f) = g.fields.iter().find(|f| packed && f.with.is_some()) {
                return bad(f.line, format!("`with` on the `.` field of packed group `{}`", g.list));
            }
            protobuf::parse_path(&g.locator).is_ok()
        }
        Wire::Bits => {
            if g.item_bits.is_none() {
                return bad(g.line, "a group on a bits wire needs `item <bits>`");
            }
            match &g.count {
                None => return bad(g.line, "a group on a bits wire needs `count <count-locator | n>`"),
                Some(Count::Locator(l)) => match bits::parse_locator(l) {
                    Ok((_, _, len)) if len <= 64 => {}
                    _ => return bad(g.line, format!("`{}` is not a count locator", l)),
                },
                Some(Count::Fixed(_)) => {}
            }
            bits::parse_group_locator(&g.locator).is_ok()
        }
    };
    if !ok {
        return bad(g.line, format!("`{}` is not a group locator of this wire", g.locator));
    }
    Ok(())
}

/// Ruling 9 of 0.17: a gate of a scope any of whose bits lies within the
/// items of a fixed-count group of that scope is `bad-directive`.
fn check_gates_off_items(word_bytes: usize, gates: &[(usize, &str)], groups: &[&GroupDef]) -> Result<(), Error> {
    let wb = word_bytes as u64 * 8;
    for g in groups {
        let n = match &g.count {
            Some(Count::Fixed(n)) => *n,
            _ => continue,
        };
        let (w, p) = match bits::parse_group_locator(&g.locator) {
            Ok(x) => x,
            Err(_) => continue,
        };
        let start = w as u64 * wb + p as u64;
        let end = n.saturating_mul(g.item_bits.unwrap_or(0)).saturating_add(start);
        for (line, loc) in gates {
            if let Ok((gw, gp, gl)) = bits::parse_locator(loc) {
                let a = gw as u64 * wb + gp as u64;
                if a < end && a + gl as u64 > start {
                    return bad(*line, format!("the gate `{}` lies within the items of group `{}`", loc, g.list));
                }
            }
        }
    }
    Ok(())
}

/// Load checks of one scope (common plus one kind, or one group body): a list
/// is mapped by at most one `group`; on `bits`, a group whose count is a
/// locator is the last thing in its scope.
fn check_scope(
    wire: Wire,
    word_bytes: usize,
    lines: &[(usize, &str)],
    fields: &[(usize, &str)],
    groups: &[&GroupDef],
) -> Result<(), Error> {
    if groups.is_empty() {
        return Ok(());
    }
    let mut lists: HashSet<&str> = HashSet::with_capacity(groups.len());
    for g in groups {
        if !lists.insert(g.list.as_str()) {
            return bad(g.line, format!("list `{}` is mapped by two groups of one scope", g.list));
        }
    }
    // ruling 21 of 0.7: a `field` whose locator passes through a group's path:
    // the names of the group's path are the first names of the path the
    // locator addresses (xml: the names before `@name` or `#text`; json,
    // geojson, protobuf: the names before the last). Two paths have the same
    // names when their texts are equal, so each leading part of the field's
    // path is looked up among the group paths.
    let sep = match wire {
        Wire::Xml => Some('/'),
        Wire::Json | Wire::GeoJson | Wire::Protobuf => Some('.'),
        Wire::Bits | Wire::Text | Wire::Tlv => None,
    };
    if let Some(sep) = sep {
        // group path -> the first group of the scope with that path
        let mut by_path: HashMap<&str, usize> = HashMap::with_capacity(groups.len());
        for (i, g) in groups.iter().enumerate() {
            by_path.entry(g.locator.as_str()).or_insert(i);
        }
        for (line, loc) in fields {
            let path = match loc.rsplit_once(sep) {
                Some((path, _)) => path,
                None => continue,
            };
            // the first group, in line order, that the locator passes through
            let first = path
                .match_indices(sep)
                .map(|(i, _)| &path[..i])
                .chain(std::iter::once(path))
                .filter_map(|lead| by_path.get(lead))
                .min();
            if let Some(i) = first {
                return bad(*line, format!("`{}` passes through the path of group `{}`", loc, groups[*i].list));
            }
        }
    }
    if wire != Wire::Bits {
        return Ok(());
    }
    let wb = word_bytes as u64 * 8;
    let end_of = |loc: &str| bits::parse_locator(loc).map(|(w, p, l)| w as u64 * wb + p as u64 + l as u64);
    for g in groups {
        let count = match &g.count {
            Some(Count::Locator(l)) => l,
            _ => continue,
        };
        let (w, p) = bits::parse_group_locator(&g.locator)?;
        let start = w as u64 * wb + p as u64;
        if end_of(count).map_or(true, |e| e > start) {
            return bad(g.line, "the count locator lies at or beyond the start of its group");
        }
        for (line, loc) in lines {
            if end_of(loc).map_or(false, |e| e > start) {
                return bad(*line, format!("`{}` lies at or beyond the start of the counted group `{}`", loc, g.list));
            }
        }
        for o in groups {
            if o.line == g.line {
                continue;
            }
            let (ow, op) = bits::parse_group_locator(&o.locator)?;
            let ostart = ow as u64 * wb + op as u64;
            if ostart >= start {
                return bad(o.line, format!("group `{}` starts at or beyond the counted group `{}`", o.list, g.list));
            }
            // a fixed-count group that starts before it and whose items reach its start (ruling 16 of 0.7)
            if let Some(Count::Fixed(n)) = &o.count {
                if n.saturating_mul(o.item_bits.unwrap_or(0)).saturating_add(ostart) > start {
                    return bad(o.line, format!("the items of group `{}` reach the counted group `{}`", o.list, g.list));
                }
            }
        }
    }
    Ok(())
}

/// Validate one gate block's `if` line and read its values (engine-spec
/// v0.17): a fixed-layout locator of 1 to 64 bits, and a non-empty list of
/// distinct unsigned decimal integers, each below `2^len`.
fn resolve_gate(wire: Wire, g: &mut GateDef) -> Result<(), Error> {
    if wire != Wire::Bits {
        return bad(g.line, "a gate block is valid only on a bits wire");
    }
    let (_, _, len) = bits::parse_locator(&g.locator)
        .map_err(|e| Error { msg: format!("bad-directive: line {}: {}", g.line, e.msg) })?;
    if !(1..=64).contains(&len) {
        return bad(g.line, format!("bit length {} is not allowed on a gate", len));
    }
    let mut values: Vec<u64> = Vec::new();
    for v in g.text.split(',') {
        if v.is_empty() || !v.bytes().all(|b| b.is_ascii_digit()) {
            return bad(g.line, format!("gate value `{}` is not an unsigned decimal integer", v));
        }
        let n = v.parse::<u64>().or_else(|_| bad(g.line, format!("gate value `{}` is too large", v)))?;
        if len < 64 && n >> len != 0 {
            return bad(g.line, format!("gate value {} does not fit {} bits", n, len));
        }
        if values.contains(&n) {
            return bad(g.line, format!("gate value {} is listed twice", n));
        }
        values.push(n);
    }
    g.values = values;
    Ok(())
}

/// The values of a `when` on `bits` and `protobuf` (engine-spec v0.20): a
/// comma-separated list of unsigned decimal integers and ranges `lo..hi`,
/// each within `len` bits when the field has a bit length.
pub(crate) fn num_list(text: &str, len: Option<u32>, ln: usize) -> Result<Vec<(u64, u64)>, Error> {
    let number = |t: &str| -> Result<u64, Error> {
        if t.is_empty() || !t.bytes().all(|b| b.is_ascii_digit()) {
            return bad(ln, format!("`when` value `{}` is not an unsigned decimal integer or a range", text));
        }
        let v = t.parse::<u64>().or_else(|_| bad(ln, format!("`when` value `{}` is too large", t)))?;
        if let Some(len) = len {
            if len < 64 && v >> len != 0 {
                return bad(ln, format!("`when` value {} does not fit {} bits", v, len));
            }
        }
        Ok(v)
    };
    let mut out = Vec::new();
    for item in text.split(',') {
        let (lo, hi) = match item.split_once("..") {
            Some((a, b)) => (number(a)?, number(b)?),
            None => {
                let v = number(item)?;
                (v, v)
            }
        };
        if lo > hi {
            return bad(ln, format!("`when` range `{}` has its low end above its high end", item));
        }
        out.push((lo, hi));
    }
    Ok(out)
}

/// Validate one `when` line against the wire and work out its value. `list`:
/// the line is a `when`, whose value may be a list (engine-spec v0.20); a
/// `const` has one value.
fn resolve_when(wire: Wire, w: &mut WhenDef, in_group: bool, list: bool) -> Result<(), Error> {
    let numbers = |w: &mut WhenDef, len: Option<u32>| -> Result<(), Error> {
        if !list && w.value.contains(',') {
            return bad(w.line, format!("`const` value `{}` is not an unsigned decimal integer", w.value));
        }
        if !list && w.value.contains("..") {
            return bad(w.line, format!("`const` value `{}` is not an unsigned decimal integer", w.value));
        }
        if w.value.split(',').any(|v| v == "present") {
            return bad(w.line, "`present` may not be combined with other values");
        }
        w.nums = num_list(&w.value, len, w.line)?;
        w.num = w.nums[0].0;
        Ok(())
    };
    match wire {
        Wire::Bits => {
            let (_, _, len) = bits::parse_locator(&w.locator)
                .map_err(|e| Error { msg: format!("bad-directive: line {}: {}", w.line, e.msg) })?;
            if !(1..=64).contains(&len) {
                return bad(w.line, format!("bit length {} is not allowed on a `when`", len));
            }
            numbers(w, Some(len))?;
        }
        Wire::Protobuf => {
            protobuf::parse_path(&w.locator)
                .map_err(|e| Error { msg: format!("bad-directive: line {}: {}", w.line, e.msg) })?;
            if w.value == "present" {
                w.present = true;
            } else {
                numbers(w, None)?;
            }
        }
        Wire::Tlv => tlv::resolve_when(w)?,
        Wire::Text => {
            text::check_when_locator(w)?;
            if w.value == "present" {
                w.present = true;
            } else {
                w.text = w.value.strip_prefix('=').unwrap_or(&w.value).to_string();
                w.forced = w.value.starts_with('=');
            }
        }
        Wire::Xml | Wire::GeoJson | Wire::Json => {
            let ok = match wire {
                Wire::Xml => {
                    let last = w.locator.rsplit('/').next().unwrap_or("");
                    let _ = in_group;
                    (last.starts_with('@') && last.len() > 1) || last == "#text"
                }
                Wire::GeoJson if !in_group => {
                    !w.locator.is_empty()
                        && !w.locator.starts_with("geometry.")
                        && (!w.locator.contains('.') || w.locator.starts_with("properties."))
                }
                _ => !w.locator.is_empty() && w.locator.split('.').all(|s| !s.is_empty()),
            };
            if !ok {
                return bad(w.line, format!("`{}` is not a `when` locator of this wire", w.locator));
            }
            if w.value == "present" {
                w.present = true;
            } else if list && w.value.contains(',') {
                // a comma separates values (engine-spec v0.20); `..` is literal text here
                let items: Vec<&str> = w.value.split(',').collect();
                if items.iter().any(|v| *v == "present") {
                    return bad(w.line, "`present` may not be combined with other values");
                }
                if items.iter().any(|v| v.is_empty()) {
                    return bad(w.line, format!("`when` value `{}` has an empty value in its list", w.value));
                }
                w.forced = items[0].starts_with('=');
                w.texts = items.iter().map(|v| v.strip_prefix('=').unwrap_or(v).to_string()).collect();
                w.text = w.texts[0].clone();
            } else {
                w.forced = w.value.starts_with('=');
                w.text = w.value.strip_prefix('=').unwrap_or(&w.value).to_string();
                w.texts = vec![w.text.clone()];
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Engine
// ---------------------------------------------------------------------------

pub struct Engine {
    packs: BTreeMap<String, Pack>,
    modules: BTreeMap<String, Module>,
    /// module name -> key name -> the key's place in `Module::keys`
    key_index: HashMap<String, HashMap<String, usize>>,
    /// module name -> the names of its lists
    list_index: HashMap<String, HashSet<String>>,
    /// the most restricted distribution this engine instance may load
    max_distribution: Distribution,
    /// the limit on list items of one decode (ruling 7 of 0.11)
    max_items: usize,
}

impl Default for Engine {
    fn default() -> Engine {
        Engine {
            packs: BTreeMap::new(),
            modules: BTreeMap::new(),
            key_index: HashMap::new(),
            list_index: HashMap::new(),
            max_distribution: Distribution::Controlled,
            max_items: DEFAULT_MAX_ITEMS,
        }
    }
}

impl Engine {
    pub fn new() -> Engine {
        Engine::default()
    }

    /// Limit what this engine will load. With `Distribution::Public`, a
    /// controlled module or pack is refused with `distribution-refused`.
    pub fn set_max_distribution(&mut self, d: Distribution) {
        self.max_distribution = d;
    }

    /// Load one model module (the text of a `model/<module>.def`). Modules are
    /// loaded before the packs that use them.
    pub fn load_model(&mut self, text: &str) -> Result<(), Error> {
        let m = Module::parse_within(text, &self.modules, self.max_distribution)?;
        if self.modules.contains_key(&m.name) {
            return err(format!("duplicate-module: model module `{}` is already loaded", m.name));
        }
        self.key_index.insert(m.name.clone(), m.keys.iter().enumerate().map(|(i, k)| (k.name.clone(), i)).collect());
        self.list_index.insert(m.name.clone(), m.lists.iter().map(|(n, _)| n.clone()).collect());
        self.modules.insert(m.name.clone(), m);
        Ok(())
    }

    /// Loaded model module names, sorted.
    pub fn modules(&self) -> Vec<String> {
        self.modules.keys().cloned().collect()
    }

    /// Check a pack against the loaded model modules (engine-spec v0.4, v0.5).
    fn check_pack(&self, p: &Pack) -> Result<(), Error> {
        if p.distribution > self.max_distribution {
            return err(format!(
                "distribution-refused: pack `{}` is {}, this engine loads {} only",
                p.format,
                p.distribution.name(),
                self.max_distribution.name()
            ));
        }
        let mut used: Vec<&str> = vec!["core"];
        used.extend(p.uses.iter().map(|s| s.as_str()));
        for m in &used {
            let module = self.modules.get(*m).ok_or(Error {
                msg: format!("unknown-module: pack `{}` uses model module `{}`, which is not loaded", p.format, m),
            })?;
            if p.distribution == Distribution::Public && module.distribution != Distribution::Public {
                return err(format!(
                    "distribution-violation: public pack `{}` uses {} model module `{}`",
                    p.format,
                    module.distribution.name(),
                    m
                ));
            }
        }
        // every mapped key and every `requires` key, in line order
        let mut keys: Vec<(usize, &str, Option<&Transform>)> = Vec::new();
        for f in p.every_field() {
            keys.push((f.line, &f.model_key, Some(&f.transform)));
            // `with <other-key>` is checked like a `requires` key (engine-spec v0.18)
            if let Some((key, _)) = &f.with {
                keys.push((f.line, key, None));
            }
        }
        for (line, key) in p.every_requires() {
            keys.push((line, key, None));
        }
        for d in p.every_default() {
            keys.push((d.line, &d.model_key, None));
        }
        // a `group` line names a list, which is declared like a key
        for (line, list) in p.group_lists() {
            keys.push((line, list, None));
        }
        keys.sort_by_key(|k| k.0);
        // each check runs over every line before the next starts
        for (_, key, _) in &keys {
            let (m, _) = split_key(key);
            if !used.contains(&m) {
                return err(format!(
                    "module-not-used: pack `{}` maps `{}` but has no `uses {}`",
                    p.format, key, m
                ));
            }
        }
        for (_, key, _) in &keys {
            let (m, _) = split_key(key);
            if self.key_def(key).is_none() && !self.is_list(key) {
                return err(format!(
                    "undeclared-key: pack `{}` maps `{}`, which model module `{}` does not declare",
                    p.format, key, m
                ));
            }
        }
        // a list key with `=` (ruling 4 of 0.20)
        for r in p.every_require_def() {
            if r.values.is_some() && self.is_list(&r.key) {
                return err(format!(
                    "bad-directive: line {}: `requires {}=…` names a list; a list takes no value",
                    r.line, r.key
                ));
            }
        }
        // the type check: a field's transform, or the model side of its table
        // a `group` naming a scalar key, or a `field` naming a list (engine-spec v0.7)
        let mut lines: Vec<(usize, Option<&FieldDef>, Option<&str>)> = p
            .every_field()
            .into_iter()
            .map(|f| (f.line, Some(f), None))
            .chain(p.group_lists().into_iter().map(|(line, list)| (line, None, Some(list))))
            .collect();
        lines.sort_by_key(|l| l.0);
        // the type of each table's model side, worked out once per table
        let mut table_types: HashMap<&str, KeyType> = HashMap::new();
        for (_, f, g) in lines {
            if let Some(list) = g {
                if !self.is_list(list) {
                    return err(format!(
                        "key-type-mismatch: pack `{}`: `group {}` names a key, not a list",
                        p.format, list
                    ));
                }
            }
            let f = match f {
                Some(f) => f,
                None => continue,
            };
            if self.is_list(&f.model_key) {
                return err(format!(
                    "key-type-mismatch: pack `{}`: `field {}` names a list, not a key",
                    p.format, f.model_key
                ));
            }
            let def_ty = self.key_def(&f.model_key).expect("declared").ty;
            let (yields, how) = match &f.via {
                Some(t) => (*table_types.entry(t.as_str()).or_insert_with(|| p.table_model_type(t)), "table"),
                None => (f.transform.value_type(), "transform"),
            };
            // an all-integer table on a `float` key is read as float (ruling 4 of 0.6)
            let int_table_on_float = f.via.is_some() && yields == KeyType::Int && def_ty == KeyType::Float;
            if yields != def_ty && !int_table_on_float {
                let how = match (how, &f.via) {
                    ("table", Some(t)) => format!("table `{}`, whose model side is", t),
                    _ => "a transform that yields".to_string(),
                };
                return err(format!(
                    "key-type-mismatch: pack `{}` maps `{}` ({}) through {} {}",
                    p.format,
                    f.model_key,
                    def_ty.name(),
                    how,
                    yields.name()
                ));
            }
        }
        // engine-spec v0.56: `range` on an `int` or `float` key, its bounds
        // that key's text, `<min>` less than `<max>`
        let mut ranged: Vec<&FieldDef> = p.every_field().into_iter().filter(|f| f.range.is_some()).collect();
        ranged.sort_by_key(|f| f.line);
        for f in ranged {
            let r = f.range.as_ref().expect("filtered");
            let ty = self.key_def(&f.model_key).expect("declared").ty;
            if ty == KeyType::Str {
                return bad(f.line, format!("`range` on `{}`, a string key", f.model_key));
            }
            if RangeVal::read(ty, &r.min, &r.max).is_none() {
                return bad(
                    f.line,
                    format!("`range {} {}` is not two {} bounds with <min> below <max>", r.min, r.max, ty.name()),
                );
            }
        }
        for d in p.every_default() {
            if self.is_list(&d.model_key) {
                return err(format!(
                    "key-type-mismatch: pack `{}`: `default {}` names a list, not a key",
                    p.format, d.model_key
                ));
            }
            let def_ty = self.key_def(&d.model_key).expect("declared").ty;
            if read_as(def_ty, &d.text).is_none() {
                return err(format!(
                    "key-type-mismatch: pack `{}`: default `{}` of `{}` is not a {}",
                    p.format,
                    d.text,
                    d.model_key,
                    def_ty.name()
                ));
            }
        }
        // engine-spec v0.20: `requires =` and `case` values read as the key's
        // type, in line order; a value listed twice in one switch
        let mut valued: Vec<(usize, &str, &[String], Option<&seq::Switch>)> = Vec::new();
        for r in p.every_require_def() {
            if let Some(vs) = &r.values {
                valued.push((r.line, &r.key, vs, None));
            }
        }
        if let Some(body) = &p.seq {
            body.visit(&mut |v| {
                if let seq::Visit::Switch(sw) = v {
                    for c in &sw.cases {
                        valued.push((c.line, &sw.key, &c.values, Some(sw)));
                    }
                }
            });
        }
        valued.sort_by_key(|v| v.0);
        let mut seen: Vec<(usize, Vec<String>)> = Vec::new();
        for (line, key, values, sw) in valued {
            let def_ty = match self.key_def(key) {
                Some(d) => d.ty,
                None => continue,
            };
            // the types of the line's values, then its duplicates (ruling 19 of 0.20)
            let mut canon: Vec<(String, &String)> = Vec::new();
            for v in values {
                let c = match canon_value(def_ty, v) {
                    Some(c) => c,
                    None => {
                        return err(format!(
                            "key-type-mismatch: pack `{}`: line {}: value `{}` of `{}` is not a {}",
                            p.format,
                            line,
                            v,
                            key,
                            def_ty.name()
                        ))
                    }
                };
                canon.push((c, v));
            }
            for (c, v) in canon {
                if let Some(sw) = sw {
                    let i = match seen.iter().position(|(l, _)| *l == sw.line) {
                        Some(i) => i,
                        None => {
                            seen.push((sw.line, Vec::new()));
                            seen.len() - 1
                        }
                    };
                    if seen[i].1.contains(&c) {
                        return err(format!(
                            "bad-directive: line {}: `case` value `{}` is listed twice in the switch of line {}",
                            line, v, sw.line
                        ));
                    }
                    seen[i].1.push(c);
                }
            }
        }
        Ok(())
    }

    /// The declaration of a model key written as in a pack (`lat`, `track.class`).
    fn key_def(&self, key: &str) -> Option<&KeyDef> {
        let (m, k) = split_key(key);
        let i = *self.key_index.get(m)?.get(k)?;
        self.modules.get(m).and_then(|module| module.keys.get(i))
    }

    /// Is this name, written as in a pack, a declared list?
    fn is_list(&self, name: &str) -> bool {
        let (m, k) = split_key(name);
        self.list_index.get(m).map_or(false, |lists| lists.contains(k))
    }

    pub fn load(&mut self, mut pack: Pack) -> Result<(), Error> {
        self.check_pack(&pack)?;
        // last of the load checks (ruling 5 of 0.11): the first pack stays loaded
        if self.packs.contains_key(&pack.format) {
            return err(format!("duplicate-format: a pack with format `{}` is already loaded", pack.format));
        }
        // record each key's declared type, and read each default as it
        let set_field = |f: &mut FieldDef| {
            f.key_type = self.key_def(&f.model_key).map(|d| d.ty);
            if let (Some(r), Some(ty)) = (&mut f.range, f.key_type) {
                r.val = RangeVal::read(ty, &r.min, &r.max);
            }
        };
        let set_default = |d: &mut DefaultDef| d.value = self.key_def(&d.model_key).and_then(|k| read_as(k.ty, &d.text));
        pack.fields.iter_mut().chain(pack.kinds.iter_mut().flat_map(|k| k.fields.iter_mut())).for_each(set_field);
        pack.defaults.iter_mut().chain(pack.kinds.iter_mut().flat_map(|k| k.defaults.iter_mut())).for_each(set_default);
        pack.every_group_mut(&mut |g| {
            g.fields.iter_mut().for_each(set_field);
            g.defaults.iter_mut().for_each(set_default);
        });
        if let Some(body) = &mut pack.seq {
            body.visit_mut(&mut |f| set_field(f), &mut |d| set_default(d));
        }
        // the canonical text of `requires =` and `case` values (ruling 1 of 0.20)
        let ty = |key: &str| self.key_def(key).map(|d| d.ty);
        for r in pack.kinds.iter_mut().flat_map(|k| k.requires.iter_mut()) {
            if let (Some(vs), Some(t)) = (&r.values, ty(&r.key)) {
                r.canon = vs.iter().filter_map(|v| canon_value(t, v)).collect();
            }
        }
        if let Some(body) = &mut pack.seq {
            body.resolve(&ty);
        }
        self.packs.insert(pack.format.clone(), pack);
        Ok(())
    }

    /// The directory loader for model modules: `core.def` first, whatever its
    /// name sorts as (ruling 9 of 0.6), then every other `*.def` in byte order
    /// of file name. A directory that does not exist loads nothing (ruling 4
    /// of 0.4).
    pub fn load_model_dir(&mut self, dir: &std::path::Path) -> Result<(), Error> {
        let mut files: Vec<std::path::PathBuf> = match std::fs::read_dir(dir) {
            Ok(rd) => rd
                .flatten()
                .map(|e| e.path())
                .filter(|p| p.extension().and_then(|s| s.to_str()) == Some("def"))
                .collect(),
            Err(_) => return Ok(()),
        };
        files.sort_by(|a, b| {
            let core = |p: &std::path::PathBuf| p.file_name().and_then(|s| s.to_str()) != Some("core.def");
            (core(a), a.file_name()).cmp(&(core(b), b.file_name()))
        });
        // each module after the modules it uses (engine-spec v0.8): of the
        // files not yet loaded, the first in that order whose used modules
        // are all loaded or are in no file of the directory
        let mut pending: Vec<(std::path::PathBuf, String, String, Vec<String>)> = Vec::new();
        for f in files {
            let text = std::fs::read_to_string(&f).map_err(|e| Error { msg: format!("cannot read {}: {}", f.display(), e) })?;
            let (mut name, mut uses) = (String::new(), Vec::new());
            for line in text.lines() {
                match tokenize(line) {
                    Ok(t) if t.len() == 2 && t[0] == "module" => name = t[1].clone(),
                    Ok(t) if t.len() == 2 && t[0] == "uses" => uses.push(t[1].clone()),
                    _ => {}
                }
            }
            pending.push((f, text, name, uses));
        }
        while !pending.is_empty() {
            let names: Vec<String> = pending.iter().map(|p| p.2.clone()).collect();
            let ready = pending.iter().position(|(_, _, name, uses)| uses.iter().all(|u| u == name || !names.contains(u)));
            let (f, text, _, _) = match ready {
                Some(i) => pending.remove(i),
                None => {
                    return err(format!("bad-directive: the `uses` lines of model modules {} form a cycle", names.join(", ")));
                }
            };
            self.load_model(&text).map_err(|e| Error { msg: format!("{} (in {})", e.msg, f.display()) })?;
        }
        Ok(())
    }

    /// The directory loader for packs: every `<dir>/<name>/pack.def`, in byte
    /// order of `<name>`.
    pub fn load_pack_dir(&mut self, dir: &std::path::Path) -> Result<(), Error> {
        let mut dirs: Vec<std::path::PathBuf> = std::fs::read_dir(dir)
            .map_err(|e| Error { msg: format!("cannot read {}: {}", dir.display(), e) })?
            .flatten()
            .map(|e| e.path())
            .collect();
        dirs.sort();
        for d in dirs {
            let def = d.join("pack.def");
            if def.exists() {
                let text =
                    std::fs::read_to_string(&def).map_err(|e| Error { msg: format!("cannot read {}: {}", def.display(), e) })?;
                self.load_def(&text).map_err(|e| Error { msg: format!("{} (in {})", e.msg, def.display()) })?;
            }
        }
        Ok(())
    }
    /// Load only the named packs of a pack directory: `<dir>/<name>/pack.def`
    /// for each name, in byte order of `<name>` as `load_pack_dir` does. A
    /// name given twice is loaded once. A name with no `pack.def` is an
    /// error, and nothing is loaded after it. The model modules the packs
    /// use are loaded first, as for any pack.
    pub fn load_pack_dir_only(&mut self, dir: &std::path::Path, names: &[&str]) -> Result<(), Error> {
        let mut names: Vec<&str> = names.to_vec();
        names.sort();
        names.dedup();
        for name in names {
            // a name is one directory of `dir`, never a path
            if name.is_empty() || name == "." || name == ".." || name.contains('/') || name.contains('\\') {
                return err(format!("`{}` is not a pack name", name));
            }
            let def = dir.join(name).join("pack.def");
            let text = std::fs::read_to_string(&def)
                .map_err(|e| Error { msg: format!("no pack `{}`: cannot read {}: {}", name, def.display(), e) })?;
            self.load_def(&text).map_err(|e| Error { msg: format!("{} (in {})", e.msg, def.display()) })?;
        }
        Ok(())
    }
    pub fn load_def(&mut self, text: &str) -> Result<(), Error> {
        let p = Pack::parse(text)?;
        self.load(p)
    }
    fn pack(&self, format: &str) -> Result<&Pack, Error> {
        self.packs
            .get(format)
            .ok_or(Error { msg: format!("unknown-format: no pack loaded for format `{}`", format) })
    }

    /// The declared type of a model key written as in a pack (`lat`,
    /// `track.class`); None when no loaded module declares it.
    pub fn key_type(&self, key: &str) -> Option<KeyType> {
        self.key_def(key).map(|d| d.ty)
    }

    /// The limit on list items each decode holds (ruling 7 of 0.11); 0
    /// refuses any item. The default is `DEFAULT_MAX_ITEMS`.
    pub fn set_max_items(&mut self, n: usize) {
        self.max_items = n;
    }
    pub fn max_items(&self) -> usize {
        self.max_items
    }

    pub fn decode(&self, format: &str, bytes: &str) -> Result<Entity, Error> {
        self.decode_limited(format, bytes, self.max_items)
    }

    /// `decode` with the limit on list items given for this call.
    pub fn decode_limited(&self, format: &str, bytes: &str, max_items: usize) -> Result<Entity, Error> {
        let p = self.pack(format)?;
        let _scope = limit::begin(max_items);
        match p.wire {
            #[cfg(feature = "xml")]
            Wire::Xml => xml::decode(p, bytes),
            #[cfg(feature = "geojson")]
            Wire::GeoJson => geojson::decode(p, bytes),
            #[cfg(feature = "bits")]
            Wire::Bits => bits::decode(p, bytes),
            #[cfg(feature = "protobuf")]
            Wire::Protobuf => protobuf::decode(p, bytes),
            #[cfg(feature = "json")]
            Wire::Json => jsonwire::decode(p, bytes),
            #[cfg(feature = "text")]
            Wire::Text => text::decode(p, bytes),
            #[cfg(feature = "tlv")]
            Wire::Tlv => tlv::decode(p, bytes),
            #[allow(unreachable_patterns)]
            w => {
                let _ = bytes;
                not_built(w)
            }
        }
    }
    pub fn encode(&self, format: &str, ent: &Entity) -> Result<String, Error> {
        let p = self.pack(format)?;
        match p.wire {
            #[cfg(feature = "xml")]
            Wire::Xml => xml::encode(p, ent),
            #[cfg(feature = "geojson")]
            Wire::GeoJson => geojson::encode(p, ent),
            #[cfg(feature = "bits")]
            Wire::Bits => bits::encode(p, ent),
            #[cfg(feature = "protobuf")]
            Wire::Protobuf => protobuf::encode(p, ent),
            #[cfg(feature = "json")]
            Wire::Json => jsonwire::encode(p, ent),
            #[cfg(feature = "text")]
            Wire::Text => text::encode(p, ent),
            #[cfg(feature = "tlv")]
            Wire::Tlv => tlv::encode(p, ent),
            #[allow(unreachable_patterns)]
            w => {
                let _ = ent;
                not_built(w)
            }
        }
    }
    /// `convert` with no context.
    pub fn convert(&self, from: &str, to: &str, bytes: &str) -> Result<String, Error> {
        self.convert_with(from, to, bytes, None)
    }

    /// Engine-spec v0.6, "Order inside convert": decode; clear the kind unless
    /// `from == to`; check every context key and fill the absent ones; apply
    /// the derivations; encode. With `from == to` and no context the middle
    /// steps are skipped. An empty context counts as given (ruling 10 of 0.6).
    pub fn convert_with(
        &self,
        from: &str,
        to: &str,
        bytes: &str,
        context: Option<&[(String, Value)]>,
    ) -> Result<String, Error> {
        // `from`, then `to`, before the input is read (ruling 5 of 0.11)
        self.pack(from)?;
        self.pack(to)?;
        let mut ent = self.decode(from, bytes)?;
        if from != to {
            ent.kind = None;
        }
        if from != to || context.is_some() {
            self.fill(&mut ent, context.unwrap_or(&[]))?;
            self.complete(&mut ent);
        }
        self.encode(to, &ent)
    }

    /// `convert` with the context given as text (the CLI's `--set`, a vector's
    /// `context`). The context is read and checked after the decode.
    pub fn convert_text(
        &self,
        from: &str,
        to: &str,
        bytes: &str,
        context: Option<&[(String, String)]>,
    ) -> Result<String, Error> {
        self.convert_text_limited(from, to, bytes, context, self.max_items)
    }

    /// `convert_text` with the limit on list items given for this call.
    pub fn convert_text_limited(
        &self,
        from: &str,
        to: &str,
        bytes: &str,
        context: Option<&[(String, String)]>,
        max_items: usize,
    ) -> Result<String, Error> {
        // `from`, then `to`, before the input is read (ruling 5 of 0.11)
        self.pack(from)?;
        self.pack(to)?;
        let mut ent = self.decode_limited(from, bytes, max_items)?;
        if from != to {
            ent.kind = None;
        }
        if from != to || context.is_some() {
            let context = self.context_from_text(context.unwrap_or(&[]))?;
            self.fill(&mut ent, &context)?;
            self.complete(&mut ent);
        }
        self.encode(to, &ent)
    }

    /// A context key must be declared by a loaded module and hold its declared type.
    fn check_context(&self, context: &[(String, Value)]) -> Result<(), Error> {
        for (key, v) in context {
            let def = self.context_key(key)?;
            if v.key_type() != def.ty {
                return err(format!("key-type-mismatch: context key `{}` is a {}", key, def.ty.name()));
            }
        }
        Ok(())
    }

    /// The declaration of a context key. A list where a scalar key is expected
    /// is `key-type-mismatch` (ruling 18 of 0.7).
    fn context_key(&self, key: &str) -> Result<&KeyDef, Error> {
        if self.is_list(key) {
            return err(format!("key-type-mismatch: context key `{}` is a list, not a key", key));
        }
        self.key_def(key).ok_or(Error {
            msg: format!("undeclared-key: context key `{}` is declared by no loaded module", key),
        })
    }

    /// Context given as text (the CLI's `--set`, a vector's `context`): each
    /// value is read as its key's declared type.
    pub fn context_from_text(&self, pairs: &[(String, String)]) -> Result<Vec<(String, Value)>, Error> {
        let mut out = Vec::new();
        for (key, text) in pairs {
            let def = self.context_key(key)?;
            let v = read_as(def.ty, text).ok_or(Error {
                msg: format!("key-type-mismatch: context key `{}` is a {}, got `{}`", key, def.ty.name(), text),
            })?;
            out.push((key.clone(), v));
        }
        Ok(out)
    }

    /// Set each context key the entity lacks.
    pub fn fill(&self, ent: &mut Entity, context: &[(String, Value)]) -> Result<(), Error> {
        self.check_context(context)?;
        for (key, v) in context {
            ent.fields.entry(key.clone()).or_insert_with(|| v.clone());
        }
        Ok(())
    }

    /// Apply the derivations: the loaded modules in byte order of name, each
    /// module's `derive` lines in order; a line whose target is absent and
    /// whose arguments are all present sets the target. Repeats until a pass
    /// sets nothing, at most 8 times.
    pub fn complete(&self, ent: &mut Entity) {
        for _ in 0..8 {
            let mut set = false;
            for module in self.modules.values() {
                for d in &module.derives {
                    if ent.fields.contains_key(&d.target) {
                        continue;
                    }
                    // `tokens` too (ruling 7 of 0.18): the tokens whose argument is
                    // present and not 0; absent when there is none. A present
                    // argument that is not an int skips the line.
                    if let DeriveFn::Tokens(sep, toks) = &d.func {
                        let vals: Vec<Option<&Value>> = d.args.iter().map(|a| ent.fields.get(a)).collect();
                        if vals.iter().all(|v| v.is_none())
                            || vals.iter().flatten().any(|v| !matches!(v, Value::I64(_)))
                            || self.key_def(&d.target).map(|k| k.ty) != Some(KeyType::Str)
                        {
                            continue;
                        }
                        let on: Vec<&str> = toks
                            .iter()
                            .zip(&vals)
                            .filter(|(_, v)| matches!(v, Some(Value::I64(n)) if *n != 0))
                            .map(|(t, _)| t.as_str())
                            .collect();
                        if !on.is_empty() {
                            ent.fields.insert(d.target.clone(), Value::Str(on.join(&sep.to_string())));
                            set = true;
                        }
                        continue;
                    }
                    // `any` is set when only some of its arguments are present
                    let args: Option<Vec<&Value>> = if d.func == DeriveFn::Any {
                        Some(d.args.iter().filter_map(|a| ent.fields.get(a)).collect::<Vec<_>>()).filter(|v| !v.is_empty())
                    } else {
                        d.args.iter().map(|a| ent.fields.get(a)).collect()
                    };
                    let v = match args {
                        // the argument values hold the declared types, or the line is skipped
                        Some(args) => {
                            let types: Vec<KeyType> = args.iter().map(|v| v.key_type()).collect();
                            let target = self.key_def(&d.target).map(|k| k.ty);
                            match target {
                                Some(t) if d.func.fits(t, &types) => d.func.apply(&args),
                                _ => None,
                            }
                        }
                        None => None,
                    };
                    if let Some(v) = v {
                        ent.fields.insert(d.target.clone(), v);
                        set = true;
                    }
                }
            }
            if !set {
                break;
            }
        }
    }

    /// The wire of a loaded format.
    pub fn wire(&self, format: &str) -> Option<Wire> {
        self.packs.get(format).map(|p| p.wire)
    }

    /// The `version` value and the `wire` name of a loaded format, as the
    /// pack's lines give them with any quotes removed (`list-formats`, spec
    /// 0.23).
    pub fn pack_header(&self, format: &str) -> Option<(String, &'static str)> {
        self.packs.get(format).map(|p| (p.version.clone(), p.wire.name()))
    }

    /// All loaded format names, sorted.
    pub fn formats(&self) -> Vec<String> {
        self.packs.keys().cloned().collect()
    }

    /// The shared-model keys a format maps: field order, and for a pack with
    /// kinds the union over common and all kinds in first appearance order.
    pub fn model_keys(&self, format: &str) -> Vec<String> {
        self.packs.get(format).map(|p| p.model_keys()).unwrap_or_default()
    }

    /// Capability of one ordered conversion A -> B, computed from the field maps:
    /// which model keys carry across (translatable) and which A holds that B has
    /// no field for (dropped, with the reason). This answers "every type to every
    /// other, or clearly noted why not" without running a single conversion.
    /// `model_keys` of a loaded format; `unknown-format` otherwise.
    pub fn try_model_keys(&self, format: &str) -> Result<Vec<String>, Error> {
        self.pack(format).map(|p| p.model_keys())
    }

    /// `capability` (ruling 6 of 0.11); `unknown-format` when `from`, then
    /// `to`, is not loaded.
    pub fn try_capability(&self, from: &str, to: &str) -> Result<Capability, Error> {
        self.pack(from)?;
        self.pack(to)?;
        Ok(self.capability(from, to))
    }

    pub fn capability(&self, from: &str, to: &str) -> Capability {
        let ak = self.model_keys(from);
        let bk = self.model_keys(to);
        let carried: Vec<String> = ak.iter().filter(|k| bk.contains(k)).cloned().collect();
        let dropped: Vec<String> = ak.iter().filter(|k| !bk.contains(k)).cloned().collect();
        let grade = if carried.is_empty() {
            Grade::None
        } else if dropped.is_empty() {
            Grade::Full
        } else {
            Grade::Partial
        };
        Capability { from: from.into(), to: to.into(), carried, dropped, grade }
    }

    /// The full N x N capability matrix over every ordered pair of loaded formats.
    pub fn capability_matrix(&self) -> Vec<Capability> {
        let fmts = self.formats();
        let mut out = Vec::new();
        for a in &fmts {
            for b in &fmts {
                if a != b {
                    out.push(self.capability(a, b));
                }
            }
        }
        out
    }
}

/// How well an A -> B conversion carries A's information.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Grade {
    /// every field A maps is also in B
    Full,
    /// some fields carry, some are dropped
    Partial,
    /// no shared fields: the conversion is not meaningful
    None,
}

#[derive(Clone, Debug)]
pub struct Capability {
    pub from: String,
    pub to: String,
    /// model keys that carry across
    pub carried: Vec<String>,
    /// model keys A holds that B cannot represent (the "why not" for each)
    pub dropped: Vec<String>,
    pub grade: Grade,
}

// ---------------------------------------------------------------------------
// XML codec (minimal, sufficient for CoT)
// ---------------------------------------------------------------------------

#[cfg(feature = "xml")]
pub mod xml {
    use super::*;

    #[derive(Debug, Default, Clone)]
    pub struct Node {
        pub name: String,
        pub attrs: Vec<(String, String)>,
        pub children: Vec<Node>,
        pub text: Option<String>,
        /// the element text with references resolved, not trimmed, when the
        /// element holds any (the raw value a sentinel is compared with, v0.9)
        pub raw_text: Option<String>,
    }

    impl Node {
        fn child(&self, name: &str) -> Option<&Node> {
            self.children.iter().find(|c| c.name == name)
        }
        fn attr(&self, name: &str) -> Option<&str> {
            self.attrs.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str())
        }
    }

    /// Resolve a locator path under the root to (node, kind). kind: attr name, or #text.
    fn resolve<'a>(root: &'a Node, locator: &str) -> Option<(&'a Node, Loc)> {
        if let Some(attr) = locator.strip_prefix('@') {
            return Some((root, Loc::Attr(attr.to_string())));
        }
        // `#text` alone: the text of the scope's own element (an item)
        if locator == "#text" {
            return Some((root, Loc::Text));
        }
        // path/@attr or path/#text
        let (path, last) = match locator.rsplit_once('/') {
            Some((p, l)) => (p, l),
            None => return None,
        };
        let mut node = root;
        for step in path.split('/') {
            node = node.child(step)?;
        }
        if let Some(attr) = last.strip_prefix('@') {
            Some((node, Loc::Attr(attr.to_string())))
        } else if last == "#text" {
            Some((node, Loc::Text))
        } else {
            None
        }
    }

    enum Loc {
        Attr(String),
        Text,
    }

    /// Does a `when` line match the document? `present`: the attribute or
    /// element exists; text: the attribute value or element text equals it.
    fn when_holds(root: &Node, w: &WhenDef) -> bool {
        match resolve(root, &w.locator) {
            None => false,
            Some((node, Loc::Attr(a))) => match node.attr(&a) {
                None => false,
                Some(v) => w.present || w.holds_text(v),
            },
            // an element with no character data has no text: no value holds (1m of 0.11)
            Some((node, Loc::Text)) => w.present || node.text.as_deref().map_or(false, |t| w.holds_text(t)),
        }
    }

    /// The item elements of a group under `node`: each child named by the last
    /// name of the path, under the first element matched by the names before it.
    fn items<'a>(node: &'a Node, locator: &str) -> Vec<&'a Node> {
        let (path, name) = match locator.rsplit_once('/') {
            Some((p, n)) => (Some(p), n),
            None => (None, locator),
        };
        let mut parent = node;
        for step in path.into_iter().flat_map(|p| p.split('/')) {
            parent = match parent.child(step) {
                Some(c) => c,
                None => return Vec::new(),
            };
        }
        parent.children.iter().filter(|c| c.name == name).collect()
    }

    /// Decode the fields and groups of one scope: the root, or one item element.
    fn decode_scope(p: &Pack, sel: &Sel, node: &Node, d: &mut Decoded) -> Result<(), Error> {
        for f in &sel.fields {
            if let Some((n, loc)) = resolve(node, &f.locator) {
                // a sentinel at the place: the line yields no value (engine-spec v0.9)
                let sentinel = match &loc {
                    Loc::Attr(a) => n.attr(a).map_or(false, |v| f.absent_text(v)),
                    Loc::Text => n.text.as_deref().map_or(false, |v| f.absent_text(v)),
                };
                if sentinel {
                    continue;
                }
                let raw = match loc {
                    Loc::Attr(a) => n.attr(&a).map(|s| s.to_string()),
                    // the text untrimmed (ruling 1m of 0.11), so `iscale` reads it
                    // exactly: `<v>  </v>` and `<v> 1</v>` are `transform-decode`
                    // (ruling 24 of 0.15)
                    Loc::Text => n.text.clone(),
                };
                if let Some(r) = raw {
                    d.put(p, f, f.transform.decode(&r));
                }
            }
        }
        for g in &sel.groups {
            let found = items(node, &g.locator);
            // the list is present when at least one item occurs
            if found.is_empty() {
                continue;
            }
            let body = g.body();
            d.replacing(&g.list);
            let mut decoded = Vec::new();
            for n in found {
                limit::take(&p.format, &g.list, 1)?;
                let mut di = Decoded::new();
                decode_scope(p, &body, n, &mut di)?;
                decoded.push(di);
            }
            d.put_list(&g.list, decoded);
        }
        Ok(())
    }

    pub fn decode(p: &Pack, bytes: &str) -> Result<Entity, Error> {
        let _scope = limit::scope();
        let root = parse(bytes)?;
        if p.kinds.is_empty() && root.name != p.root {
            return err(format!("missing-root: format `{}`: expected root <{}>, found <{}>", p.format, p.root, root.name));
        }
        // a kind is considered only when the document's root is its root
        let sel = p.select_decode(Some(&root.name), |w| when_holds(&root, w))?;
        let mut d = Decoded::new();
        decode_scope(p, &sel, &root, &mut d)?;
        // residue: root attributes no field, `when` value or `const` maps
        let mapped_root_attrs: Vec<&str> = sel.mapped().into_iter().filter_map(|l| l.strip_prefix('@')).collect();
        for (k, v) in &root.attrs {
            if !mapped_root_attrs.contains(&k.as_str()) {
                d.ent.residue.push((p.format.clone(), format!("@{}", k), v.clone()));
            }
        }
        d.finish(p, &sel)
    }

    /// Write the lines of one scope into `node`: the root, or one item element.
    fn build(p: &Pack, sel: &Sel, ent: &Entity, node: &mut Node) -> Result<(), Error> {
        // fields, `when` and `const` values and groups in line order (ruling 10
        // of 0.5). Of two fields on one locator the earlier present line is
        // written (ruling 16); a `when` or `const` value is written over any field.
        enum Line<'a> {
            Value(&'a str, String, bool),
            Group(&'a GroupDef, &'a [Entity]),
            /// `element <path>` (engine-spec v0.18): the path, written even when empty
            Element(&'a str),
        }
        let mut lines: Vec<(usize, Line)> = Vec::new();
        for f in &sel.fields {
            let v = match sel.value_of(ent, f) {
                Some(v) => v,
                None => continue,
            };
            let raw = p
                .to_wire(f, v)
                .and_then(|w| f.transform.encode(&w))
                .map_err(|e| transform_encode_err(p, f, e))?;
            lines.push((f.line, Line::Value(&f.locator, raw, false)));
        }
        // an absent key whose field has `absent` writes its first sentinel (engine-spec v0.9)
        for (f, s) in sentinel_lines(sel, ent, |_| false) {
            if let Sentinel::Text(t, _) = s {
                lines.push((f.line, Line::Value(&f.locator, t.clone(), false)));
            }
        }
        for w in sel.fixed() {
            lines.push((w.line, Line::Value(&w.locator, w.text.clone(), true)));
        }
        for g in &sel.groups {
            // an absent list and an empty list write nothing
            match ent.lists.get(&g.list) {
                Some(items) if !items.is_empty() => lines.push((g.line, Line::Group(g, items))),
                _ => {}
            }
        }
        // `element` lines: one per path (a second line adds nothing, ruling 13
        // of 0.18), each placed at the first line of any kind that addresses
        // the element or a path under it
        let mut element_lines: Vec<(usize, &str)> = Vec::new();
        for (path, ln) in &sel.elements {
            // the element and each element on the way to it
            let ends = path.match_indices('/').map(|(i, _)| i).chain(std::iter::once(path.len()));
            for end in ends {
                let prefix = &path[..end];
                if !element_lines.iter().any(|(_, q)| *q == prefix) {
                    element_lines.push((*ln, prefix));
                }
            }
        }
        if !element_lines.is_empty() {
            let addressed: Vec<(usize, &str)> = sel
                .fields
                .iter()
                .map(|f| (f.line, f.locator.as_str()))
                // a `when <locator> present` line names no position (ruling 19 of 0.18)
                .chain(sel.whens.iter().filter(|w| !w.present).chain(sel.consts.iter()).map(|w| (w.line, w.locator.as_str())))
                .chain(sel.groups.iter().map(|g| (g.line, g.locator.as_str())))
                .chain(sel.elements.iter().map(|(p, n)| (*n, p.as_str())))
                .collect();
            for (ln, path) in element_lines {
                let under = |loc: &str| loc == path || loc.starts_with(path) && loc[path.len()..].starts_with('/');
                let at = addressed.iter().filter(|(_, loc)| under(loc)).map(|(n, _)| *n).min().unwrap_or(ln);
                lines.push((at, Line::Element(path)));
            }
        }
        fn loc_of<'b>(l: &Line<'b>) -> &'b str {
            match l {
                Line::Value(loc, _, _) => loc,
                Line::Group(g, _) => g.locator.as_str(),
                Line::Element(path) => path,
            }
        }
        // a place several lines name is written at the position of the first
        // of them, whichever line's value or sentinel is written (ruling 23 of 0.9)
        let firsts = first_lines(
            sel.fields.iter().map(|f| (f.line, f.locator.as_str())).chain(lines.iter().map(|(n, l)| (*n, loc_of(l)))),
        );
        lines.sort_by_key(|(n, l)| match l {
            Line::Element(_) => (*n, *n),
            _ => (firsts[loc_of(l)], *n),
        });
        for (_, line) in &lines {
            match line {
                Line::Value(locator, raw, is_when) => {
                    writable(raw).map_err(|e| Error {
                        msg: format!("transform-encode: format `{}`: `{}`: {}", p.format, locator, e.msg),
                    })?;
                    place(node, locator, raw, *is_when)?
                }
                Line::Element(path) => {
                    let mut at = &mut *node;
                    for step in path.split('/') {
                        at = child_mut(at, step);
                    }
                }
                Line::Group(g, items) => {
                    let (path, name) = match g.locator.rsplit_once('/') {
                        Some((p, n)) => (Some(p), n),
                        None => (None, g.locator.as_str()),
                    };
                    let mut parent = &mut *node;
                    for step in path.into_iter().flat_map(|p| p.split('/')) {
                        parent = child_mut(parent, step);
                    }
                    let body = g.body();
                    for item in items.iter() {
                        let mut n = Node { name: name.to_string(), ..Default::default() };
                        build(p, &body, item, &mut n)?;
                        parent.children.push(n);
                    }
                }
            }
        }
        Ok(())
    }

    /// The first child of that name, created at the end when there is none.
    fn child_mut<'a>(node: &'a mut Node, step: &str) -> &'a mut Node {
        let i = match node.children.iter().position(|c| c.name == step) {
            Some(i) => i,
            None => {
                node.children.push(Node { name: step.to_string(), ..Default::default() });
                node.children.len() - 1
            }
        };
        &mut node.children[i]
    }

    pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
        let sel = p.select_encode(ent)?;
        // Build a tree: root attrs, then child elements by first appearance.
        let mut root = Node { name: sel.root.to_string(), ..Default::default() };
        build(p, &sel, ent, &mut root)?;
        // residue belonging to this format, onto root attrs
        for (fmt, loc, raw) in &ent.residue {
            if fmt == &p.format {
                if let Some(attr) = loc.strip_prefix('@') {
                    // 1d holds for residue too (1f)
                    writable(raw).map_err(|e| Error {
                        msg: format!("transform-encode: format `{}`: residue `{}`: {}", p.format, loc, e.msg),
                    })?;
                    if !root.attrs.iter().any(|(k, _)| k == attr) {
                        root.attrs.push((attr.to_string(), raw.clone()));
                    }
                }
            }
        }
        Ok(serialize(&root))
    }

    /// Write `value` at `locator`. `replace`: overwrite a value already there;
    /// otherwise the value already there stays.
    fn place(root: &mut Node, locator: &str, value: &str, replace: bool) -> Result<(), Error> {
        fn set_attr(node: &mut Node, attr: &str, value: &str, replace: bool) {
            match node.attrs.iter().position(|(k, _)| k == attr) {
                Some(i) if replace => node.attrs[i].1 = value.to_string(),
                Some(_) => {}
                None => node.attrs.push((attr.to_string(), value.to_string())),
            }
        }
        if let Some(attr) = locator.strip_prefix('@') {
            set_attr(root, attr, value, replace);
            return Ok(());
        }
        // `#text` alone: the text of an item element
        if locator == "#text" {
            if replace || root.text.is_none() {
                root.text = Some(value.to_string());
            }
            return Ok(());
        }
        let (path, last) = locator
            .rsplit_once('/')
            .ok_or(Error { msg: format!("bad xml locator `{}`", locator) })?;
        let mut node = root;
        for step in path.split('/') {
            let idx = node.children.iter().position(|c| c.name == step);
            let i = match idx {
                Some(i) => i,
                None => {
                    node.children
                        .push(Node { name: step.to_string(), ..Default::default() });
                    node.children.len() - 1
                }
            };
            node = &mut node.children[i];
        }
        if let Some(attr) = last.strip_prefix('@') {
            set_attr(node, attr, value, replace);
        } else if last == "#text" {
            if replace || node.text.is_none() {
                node.text = Some(value.to_string());
            }
        } else {
            return err(format!("bad xml locator tail `{}`", last));
        }
        Ok(())
    }

    // --- canonical serializer ---
    pub fn serialize(n: &Node) -> String {
        let mut s = String::new();
        write_node(n, &mut s);
        s
    }
    fn write_node(n: &Node, out: &mut String) {
        out.push('<');
        out.push_str(&n.name);
        for (k, v) in &n.attrs {
            out.push(' ');
            out.push_str(k);
            out.push_str("=\"");
            out.push_str(&escape_attr(v));
            out.push('"');
        }
        let empty = n.children.is_empty() && n.text.as_deref().unwrap_or("").is_empty();
        if empty {
            out.push_str("/>");
            return;
        }
        out.push('>');
        if let Some(t) = &n.text {
            out.push_str(&escape_text(t));
        }
        for c in &n.children {
            write_node(c, out);
        }
        out.push_str("</");
        out.push_str(&n.name);
        out.push('>');
    }
    /// 1a: an attribute value between double quotes.
    fn escape_attr(s: &str) -> String {
        let mut out = String::with_capacity(s.len());
        for c in s.chars() {
            match c {
                '&' => out.push_str("&amp;"),
                '<' => out.push_str("&lt;"),
                '>' => out.push_str("&gt;"),
                '"' => out.push_str("&quot;"),
                '\t' => out.push_str("&#9;"),
                '\n' => out.push_str("&#10;"),
                '\r' => out.push_str("&#13;"),
                c => out.push(c),
            }
        }
        out
    }
    /// 1b: text content.
    fn escape_text(s: &str) -> String {
        let mut out = String::with_capacity(s.len());
        for c in s.chars() {
            match c {
                '&' => out.push_str("&amp;"),
                '<' => out.push_str("&lt;"),
                '>' => out.push_str("&gt;"),
                '\r' => out.push_str("&#13;"),
                c => out.push(c),
            }
        }
        out
    }

    // --- parser (ruling 1 of 0.11) ---

    /// The deepest nesting of elements a document may have; the root element
    /// is level 1. A document nested deeper is `malformed-wire`, so the
    /// parser's recursion is bounded whatever the input.
    pub const MAX_DEPTH: usize = 64;

    /// Parse one document: an optional byte order mark (1g), an optional
    /// prolog, one root element, then only whitespace, comments and processing
    /// instructions. Line ends are read as line feeds first (1h). Every
    /// failure is `malformed-wire`; no input makes the parser read out of
    /// bounds.
    pub fn parse(input: &str) -> Result<Node, Error> {
        let input = input.strip_prefix('\u{feff}').unwrap_or(input);
        let normalised;
        let input = if input.contains('\r') {
            normalised = input.replace("\r\n", "\n").replace('\r', "\n");
            normalised.as_str()
        } else {
            input
        };
        let mut p = XmlParser { s: input, b: input.as_bytes(), i: 0 };
        let root = p.document().map_err(|e| Error { msg: format!("malformed-wire: xml: {}", e.msg) })?;
        Ok(root)
    }
    struct XmlParser<'a> {
        s: &'a str,
        b: &'a [u8],
        /// the cursor; never beyond `b.len()`, always at a character boundary
        i: usize,
    }
    impl<'a> XmlParser<'a> {
        fn document(&mut self) -> Result<Node, Error> {
            self.skip_misc()?;
            if self.starts_with("<![CDATA[") {
                return err("a CDATA section outside the root element");
            }
            let root = self.parse_element(1)?;
            self.skip_misc()?;
            if self.i < self.b.len() {
                return err(format!("content after the root element at byte {}", self.i));
            }
            Ok(root)
        }
        fn ws(&mut self) {
            // XML whitespace: space, tab, line feed (a carriage return is a line feed by now)
            while self.i < self.b.len() && matches!(self.b[self.i], b' ' | b'\t' | b'\n' | b'\r') {
                self.i += 1;
            }
        }
        fn peek(&self) -> Option<u8> {
            self.b.get(self.i).copied()
        }
        fn starts_with(&self, s: &str) -> bool {
            self.b.get(self.i..).map_or(false, |rest| rest.starts_with(s.as_bytes()))
        }
        /// The text from the cursor to the next `end`, and the cursor moved
        /// past `end`. The input ending first is an error naming `what`.
        fn take_until(&mut self, end: &str, what: &str) -> Result<&'a str, Error> {
            let rest = &self.s[self.i..];
            match rest.find(end) {
                Some(at) => {
                    self.i += at + end.len();
                    Ok(&rest[..at])
                }
                None => err(format!("unexpected end in {}", what)),
            }
        }
        /// A comment or a processing instruction at the cursor, skipped; its
        /// content is not read (1l).
        fn skip_comment_or_pi(&mut self) -> Result<bool, Error> {
            if self.starts_with("<?") {
                self.i += 2;
                self.take_until("?>", "a processing instruction")?;
            } else if self.starts_with("<!--") {
                self.i += 4;
                self.take_until("-->", "a comment")?;
            } else {
                return Ok(false);
            }
            Ok(true)
        }
        /// Whitespace, comments and processing instructions.
        fn skip_misc(&mut self) -> Result<(), Error> {
            loop {
                self.ws();
                if !self.skip_comment_or_pi()? {
                    return Ok(());
                }
            }
        }
        fn parse_element(&mut self, depth: usize) -> Result<Node, Error> {
            // no entity is declared, expanded or fetched: a document type
            // declaration is refused wherever it stands
            if self.starts_with("<!DOCTYPE") {
                return err("a document type declaration is not accepted");
            }
            if self.peek() != Some(b'<') {
                return err(match self.peek() {
                    None => "unexpected end: expected '<'".to_string(),
                    Some(_) => format!("expected '<' at byte {}", self.i),
                });
            }
            if depth > MAX_DEPTH {
                return err(format!("elements nested deeper than {} levels", MAX_DEPTH));
            }
            self.i += 1;
            let name = self.read_name();
            if name.is_empty() {
                return err(match self.peek() {
                    None => "unexpected end after '<'".to_string(),
                    Some(_) => format!("expected an element name at byte {}", self.i),
                });
            }
            let mut node = Node { name, ..Default::default() };
            loop {
                self.ws();
                if self.i >= self.b.len() {
                    return err(format!("unexpected end in tag <{}>", node.name));
                }
                if self.starts_with("/>") {
                    self.i += 2;
                    return Ok(node);
                }
                if self.b[self.i] == b'>' {
                    self.i += 1;
                    break;
                }
                // attribute
                let an = self.read_name();
                if an.is_empty() {
                    return err(format!("bad attribute name at byte {}", self.i));
                }
                self.ws();
                match self.peek() {
                    Some(b'=') => self.i += 1,
                    None => return err(format!("unexpected end after attribute name `{}`", an)),
                    Some(_) => return err(format!("expected '=' after attribute name `{}`", an)),
                }
                self.ws();
                let q = match self.peek() {
                    Some(q) if q == b'"' || q == b'\'' => q,
                    None => return err(format!("unexpected end after '=' of attribute `{}`", an)),
                    Some(_) => return err(format!("expected a quote after '=' of attribute `{}`", an)),
                };
                self.i += 1;
                let start = self.i;
                while self.i < self.b.len() && self.b[self.i] != q {
                    if self.b[self.i] == b'<' {
                        return err(format!("`<` in the value of attribute `{}`", an));
                    }
                    self.i += 1;
                }
                if self.i >= self.b.len() {
                    return err(format!("unexpected end in the value of attribute `{}`", an));
                }
                // a literal tab or line feed is a space; one written as a reference is kept (1i)
                let literal = self.s[start..self.i].replace(['\t', '\n'], " ");
                let val = unescape(&literal)?;
                self.i += 1;
                // 1o: an attribute name twice on one element
                if node.attrs.iter().any(|(k, _)| *k == an) {
                    return err(format!("attribute `{}` given twice on <{}>", an, node.name));
                }
                node.attrs.push((an, val));
            }
            // content: text and CDATA sections joined in document order (1m)
            let mut text = String::new();
            loop {
                if self.starts_with("</") {
                    self.i += 2;
                    let close = self.read_name();
                    if close != node.name {
                        return err(format!("closing tag </{}> does not match <{}>", close, node.name));
                    }
                    self.ws();
                    if self.peek() != Some(b'>') {
                        return err(format!("closing tag </{}> has no '>'", close));
                    }
                    self.i += 1;
                    break;
                } else if self.starts_with("<![CDATA[") {
                    self.i += 9;
                    text.push_str(self.take_until("]]>", "a CDATA section")?);
                } else if self.skip_comment_or_pi()? {
                    continue;
                } else if self.peek() == Some(b'<') {
                    let child = self.parse_element(depth + 1)?;
                    node.children.push(child);
                } else if self.i >= self.b.len() {
                    return err(format!("unexpected end in the content of <{}>: no closing tag", node.name));
                } else {
                    let start = self.i;
                    while self.i < self.b.len() && self.b[self.i] != b'<' {
                        self.i += 1;
                    }
                    text.push_str(&unescape(&self.s[start..self.i])?);
                }
            }
            // no character data: no text, not the empty text
            if !text.is_empty() {
                node.raw_text = Some(text.clone());
                node.text = Some(text);
            }
            Ok(node)
        }
        /// The name at the cursor; empty when no name starts there.
        fn read_name(&mut self) -> String {
            let start = self.i;
            while self.i < self.b.len() {
                let c = self.b[self.i];
                // bytes of a multi-byte character belong to the name
                if c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-' | b':' | b'.') || c >= 0x80 {
                    self.i += 1;
                } else {
                    break;
                }
            }
            self.s[start..self.i].to_string()
        }
    }
    /// Replace the five predefined entities and numeric character references
    /// (1j). A numeric reference takes decimal or hexadecimal digits only and
    /// must name a character XML 1.0 allows. Every other `&` is an error. The
    /// text a reference gives is not read again.
    fn unescape(s: &str) -> Result<String, Error> {
        if !s.contains('&') {
            return Ok(s.to_string());
        }
        let mut out = String::with_capacity(s.len());
        let mut rest = s;
        while let Some(at) = rest.find('&') {
            out.push_str(&rest[..at]);
            rest = &rest[at..];
            let named = [("&quot;", '"'), ("&lt;", '<'), ("&gt;", '>'), ("&apos;", '\''), ("&amp;", '&')];
            if let Some((name, ch)) = named.iter().find(|(name, _)| rest.starts_with(name)) {
                out.push(*ch);
                rest = &rest[name.len()..];
            } else if rest.starts_with("&#") {
                let bad = |what: &str| Error { msg: format!("character reference {}", what) };
                let end = rest.find(';').ok_or_else(|| bad("has no `;`"))?;
                let body = &rest[2..end];
                let (digits, radix) = match body.strip_prefix('x') {
                    Some(hex) => (hex, 16),
                    None => (body, 10),
                };
                // digits only: `from_str_radix` alone would take a sign
                let all_digits = !digits.is_empty() && digits.bytes().all(|c| if radix == 16 { c.is_ascii_hexdigit() } else { c.is_ascii_digit() });
                if !all_digits {
                    return Err(bad(&format!("`{}` is not decimal or hexadecimal digits", &rest[..=end])));
                }
                // more digits than fit is a number beyond every character
                let cp = u32::from_str_radix(digits, radix).unwrap_or(u32::MAX);
                let allowed = matches!(cp, 0x9 | 0xA | 0xD | 0x20..=0xD7FF | 0xE000..=0xFFFD | 0x10000..=0x10FFFF);
                match char::from_u32(cp).filter(|_| allowed) {
                    Some(ch) => out.push(ch),
                    None => return Err(bad(&format!("`{}` names no character XML 1.0 allows", &rest[..=end]))),
                }
                rest = &rest[end + 1..];
            } else {
                let shown: String = rest.chars().take(12).collect();
                return err(format!("`&` that begins no predefined entity or character reference: `{}`", shown));
            }
        }
        out.push_str(rest);
        Ok(out)
    }

    /// 1d: a character XML 1.0 cannot hold, in a string that is to be written.
    pub(crate) fn writable(s: &str) -> Result<(), Error> {
        match s.chars().find(|c| matches!(*c as u32, 0..=0x8 | 0xB | 0xC | 0xE..=0x1F | 0xFFFE | 0xFFFF)) {
            Some(c) => err(format!("U+{:04X} cannot be written in XML 1.0", c as u32)),
            None => Ok(()),
        }
    }
}

// ---------------------------------------------------------------------------
// JSON value (minimal) + GeoJSON codec
// ---------------------------------------------------------------------------

pub mod json {
    use super::*;

    #[derive(Debug, Clone, PartialEq)]
    pub enum Json {
        Null,
        Bool(bool),
        Int(i64),
        Num(f64),
        Str(String),
        Arr(Vec<Json>),
        Obj(Vec<(String, Json)>),
        /// JSON text written as it is; never produced by the parser
        Raw(String),
    }

    impl Json {
        #[cfg(any(feature = "geojson", feature = "json"))]
        pub fn get<'a>(&'a self, key: &str) -> Option<&'a Json> {
            if let Json::Obj(m) = self {
                m.iter().find(|(k, _)| k == key).map(|(_, v)| v)
            } else {
                None
            }
        }
    }

    /// The deepest nesting of arrays and objects a document may have; the
    /// outermost array or object is level 1. A document nested deeper fails
    /// to parse (`malformed-wire` on the `json` and `geojson` wires), so the
    /// parser's recursion is bounded whatever the input.
    pub const MAX_DEPTH: usize = 64;

    /// Parse one JSON document: one value, then only whitespace.
    pub fn parse(input: &str) -> Result<Json, Error> {
        let mut p = JsonParser { b: input.as_bytes(), i: 0, raws: None, depth: 0 };
        p.document()
    }

    /// Parse, and also return the text of every number as written, in
    /// document order.
    #[cfg(any(feature = "geojson", feature = "json"))]
    pub fn parse_raw(input: &str) -> Result<(Json, Vec<String>), Error> {
        let mut p = JsonParser { b: input.as_bytes(), i: 0, raws: Some(Vec::new()), depth: 0 };
        let v = p.document()?;
        Ok((v, p.raws.unwrap_or_default()))
    }

    /// The text of each number of a document as written, by the address of
    /// its value in the parsed tree (`raws` from `parse_raw`), and the values
    /// a field has read.
    #[cfg(any(feature = "geojson", feature = "json"))]
    pub struct NumTexts {
        texts: HashMap<*const Json, String>,
        read: std::cell::RefCell<HashSet<*const Json>>,
    }

    #[cfg(any(feature = "geojson", feature = "json"))]
    impl NumTexts {
        #[cfg(any(feature = "geojson", feature = "json"))]
        fn get(&self, j: &Json) -> Option<&String> {
            self.texts.get(&(j as *const Json))
        }
        /// A field reads this value.
        #[cfg(any(feature = "geojson", feature = "json"))]
        pub fn mark(&self, j: &Json) {
            self.read.borrow_mut().insert(j as *const Json);
        }
        /// Is there a number outside the double range that no field read?
        /// (ruling 27 of 0.15: `malformed-wire`)
        #[cfg(feature = "json")]
        pub fn unread_out_of_range(&self, root: &Json) -> bool {
            let read = self.read.borrow();
            fn walk(j: &Json, read: &HashSet<*const Json>) -> bool {
                match j {
                    Json::Num(x) => !x.is_finite() && !read.contains(&(j as *const Json)),
                    Json::Arr(a) => a.iter().any(|v| walk(v, read)),
                    Json::Obj(m) => m.iter().any(|(_, v)| walk(v, read)),
                    _ => false,
                }
            }
            walk(root, &read)
        }
    }

    #[cfg(any(feature = "geojson", feature = "json"))]
    pub fn number_texts(root: &Json, raws: &[String]) -> NumTexts {
        fn walk(j: &Json, raws: &[String], at: &mut usize, out: &mut HashMap<*const Json, String>) {
            match j {
                Json::Int(_) | Json::Num(_) => {
                    if let Some(t) = raws.get(*at) {
                        out.insert(j as *const Json, t.clone());
                    }
                    *at += 1;
                }
                Json::Arr(a) => a.iter().for_each(|v| walk(v, raws, at, out)),
                Json::Obj(m) => m.iter().for_each(|(_, v)| walk(v, raws, at, out)),
                _ => {}
            }
        }
        let mut out = HashMap::new();
        walk(root, raws, &mut 0, &mut out);
        NumTexts { texts: out, read: std::cell::RefCell::new(HashSet::new()) }
    }

    /// The text of a number as written, else as the value prints.
    #[cfg(any(feature = "geojson", feature = "json"))]
    pub fn number_text(j: &Json, texts: &NumTexts) -> Option<String> {
        match j {
            Json::Int(n) => Some(texts.get(j).cloned().unwrap_or_else(|| n.to_string())),
            Json::Num(x) => Some(texts.get(j).cloned().unwrap_or_else(|| fmt_f64(*x))),
            _ => None,
        }
    }

    /// `scale` and `iscale` decode on `json` and `geojson` (engine-spec
    /// v0.15): the member must be a number; `iscale` reads its digits as
    /// written. None for another transform.
    #[cfg(any(feature = "geojson", feature = "json"))]
    pub(crate) fn decode_scale(t: &Transform, j: &Json, texts: &NumTexts) -> Option<Result<Value, Error>> {
        let not_number = || err(format!("JSON value `{}` is not a number", serialize(j)));
        Some(match t {
            Transform::TextScale(_) => match j {
                Json::Int(_) | Json::Num(_) => t.decode(&number_text(j, texts)?),
                _ => not_number(),
            },
            Transform::TextIscale(_) => match number_text(j, texts) {
                Some(text) => t.decode(&text),
                None => not_number(),
            },
            _ => return None,
        })
    }

    /// How many numbers a value holds, in document order.
    #[cfg(feature = "geojson")]
    pub fn count_numbers(j: &Json) -> usize {
        match j {
            Json::Int(_) | Json::Num(_) => 1,
            Json::Arr(a) => a.iter().map(count_numbers).sum(),
            Json::Obj(m) => m.iter().map(|(_, v)| count_numbers(v)).sum(),
            _ => 0,
        }
    }

    /// Serialize with every number as it was written: `raws` from
    /// `parse_raw`, `idx` the index of the value's first number.
    #[cfg(feature = "geojson")]
    pub fn serialize_raw(j: &Json, raws: &[String], idx: &mut usize) -> String {
        match j {
            Json::Int(_) | Json::Num(_) => {
                *idx += 1;
                raws.get(*idx - 1).cloned().unwrap_or_else(|| serialize(j))
            }
            Json::Arr(a) => {
                let parts: Vec<String> = a.iter().map(|v| serialize_raw(v, raws, idx)).collect();
                format!("[{}]", parts.join(","))
            }
            Json::Obj(m) => {
                let parts: Vec<String> =
                    m.iter().map(|(k, v)| format!("\"{}\":{}", escape(k), serialize_raw(v, raws, idx))).collect();
                format!("{{{}}}", parts.join(","))
            }
            other => serialize(other),
        }
    }

    struct JsonParser<'a> {
        b: &'a [u8],
        i: usize,
        raws: Option<Vec<String>>,
        /// how many arrays and objects are open
        depth: usize,
    }
    impl<'a> JsonParser<'a> {
        fn document(&mut self) -> Result<Json, Error> {
            let v = self.value()?;
            self.ws();
            if self.i < self.b.len() {
                return err(format!("json: content after the value at byte {}", self.i));
            }
            Ok(v)
        }
        /// One more array or object is open: refused beyond `MAX_DEPTH`.
        fn open(&mut self) -> Result<(), Error> {
            self.depth += 1;
            if self.depth > MAX_DEPTH {
                return err(format!("json: nesting deeper than {} levels", MAX_DEPTH));
            }
            Ok(())
        }
        fn rest(&self) -> &'a [u8] {
            self.b.get(self.i..).unwrap_or(&[])
        }
        fn ws(&mut self) {
            // JSON whitespace (RFC 8259): space, tab, line feed, carriage return
            while self.i < self.b.len() && matches!(self.b[self.i], b' ' | b'\t' | b'\n' | b'\r') {
                self.i += 1;
            }
        }
        fn value(&mut self) -> Result<Json, Error> {
            self.ws();
            if self.i >= self.b.len() {
                return err("json: unexpected end");
            }
            match self.b[self.i] {
                b'{' => self.object(),
                b'[' => self.array(),
                b'"' => Ok(Json::Str(self.string()?)),
                b't' | b'f' => self.boolean(),
                b'n' => {
                    self.expect("null")?;
                    Ok(Json::Null)
                }
                _ => self.number(),
            }
        }
        fn expect(&mut self, s: &str) -> Result<(), Error> {
            if self.rest().starts_with(s.as_bytes()) {
                self.i += s.len();
                Ok(())
            } else {
                err(format!("json: expected `{}`", s))
            }
        }
        fn boolean(&mut self) -> Result<Json, Error> {
            if self.rest().starts_with(b"true") {
                self.i += 4;
                Ok(Json::Bool(true))
            } else {
                self.expect("false")?;
                Ok(Json::Bool(false))
            }
        }
        fn object(&mut self) -> Result<Json, Error> {
            self.open()?;
            self.i += 1; // {
            let mut m = Vec::new();
            self.ws();
            if self.i < self.b.len() && self.b[self.i] == b'}' {
                self.i += 1;
                self.depth -= 1;
                return Ok(Json::Obj(m));
            }
            loop {
                self.ws();
                let k = self.string()?;
                self.ws();
                if self.i >= self.b.len() || self.b[self.i] != b':' {
                    return err("json: expected ':'");
                }
                self.i += 1;
                let v = self.value()?;
                m.push((k, v));
                self.ws();
                match self.b.get(self.i) {
                    Some(b',') => {
                        self.i += 1;
                    }
                    Some(b'}') => {
                        self.i += 1;
                        break;
                    }
                    _ => return err("json: expected ',' or '}'"),
                }
            }
            self.depth -= 1;
            Ok(Json::Obj(m))
        }
        fn array(&mut self) -> Result<Json, Error> {
            self.open()?;
            self.i += 1; // [
            let mut a = Vec::new();
            self.ws();
            if self.i < self.b.len() && self.b[self.i] == b']' {
                self.i += 1;
                self.depth -= 1;
                return Ok(Json::Arr(a));
            }
            loop {
                let v = self.value()?;
                a.push(v);
                self.ws();
                match self.b.get(self.i) {
                    Some(b',') => {
                        self.i += 1;
                    }
                    Some(b']') => {
                        self.i += 1;
                        break;
                    }
                    _ => return err("json: expected ',' or ']'"),
                }
            }
            self.depth -= 1;
            Ok(Json::Arr(a))
        }
        fn hex4(&mut self) -> Result<u32, Error> {
            let bad = || Error { msg: "json: bad \\u".into() };
            let hex = self.rest().get(..4).ok_or_else(bad)?;
            // four hex digits: `from_str_radix` alone would take a sign
            if !hex.iter().all(|c| c.is_ascii_hexdigit()) {
                return Err(bad());
            }
            let hex = std::str::from_utf8(hex).map_err(|_| bad())?;
            let cp = u32::from_str_radix(hex, 16).map_err(|_| bad())?;
            self.i += 4;
            Ok(cp)
        }
        fn string(&mut self) -> Result<String, Error> {
            if self.i >= self.b.len() || self.b[self.i] != b'"' {
                return err("json: expected string");
            }
            self.i += 1;
            // bytes, so UTF-8 in the input passes through unchanged
            let mut s: Vec<u8> = Vec::new();
            let push = |s: &mut Vec<u8>, ch: char| {
                let mut buf = [0u8; 4];
                s.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
            };
            while self.i < self.b.len() {
                let c = self.b[self.i];
                self.i += 1;
                match c {
                    b'"' => {
                        return String::from_utf8(s).map_err(|_| Error { msg: "json: invalid utf-8 in string".into() })
                    }
                    b'\\' => {
                        if self.i >= self.b.len() {
                            break;
                        }
                        let e = self.b[self.i];
                        self.i += 1;
                        match e {
                            b'"' | b'\\' | b'/' => s.push(e),
                            b'n' => s.push(b'\n'),
                            b't' => s.push(b'\t'),
                            b'r' => s.push(b'\r'),
                            b'b' => s.push(0x08),
                            b'f' => s.push(0x0c),
                            b'u' => {
                                let mut cp = self.hex4()?;
                                let lone = || Error { msg: "json: a \\u escape is half of a surrogate pair without its other half".into() };
                                // a surrogate pair is one character; half of one is refused
                                if (0xD800..0xDC00).contains(&cp) {
                                    if !self.rest().starts_with(b"\\u") {
                                        return Err(lone());
                                    }
                                    self.i += 2;
                                    let lo = self.hex4()?;
                                    if !(0xDC00..0xE000).contains(&lo) {
                                        return Err(lone());
                                    }
                                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                                }
                                push(&mut s, char::from_u32(cp).ok_or_else(lone)?);
                            }
                            _ => return err(format!("json: bad escape at byte {}", self.i - 1)),
                        }
                    }
                    c if c < 0x20 => return err(format!("json: control character in a string at byte {}", self.i - 1)),
                    _ => s.push(c),
                }
            }
            err("json: unterminated string")
        }
        /// `-`? then `0` or digits with no leading zero, then an optional
        /// fraction and an optional exponent, each with at least one digit.
        fn number(&mut self) -> Result<Json, Error> {
            let start = self.i;
            let mut is_float = false;
            let bad = |at: usize| Error { msg: format!("json: bad value at byte {}", at) };
            let digits = |p: &mut Self| {
                let from = p.i;
                while p.i < p.b.len() && p.b[p.i].is_ascii_digit() {
                    p.i += 1;
                }
                p.i - from
            };
            if self.b.get(self.i) == Some(&b'-') {
                self.i += 1;
            }
            let int_start = self.i;
            let n = digits(self);
            if n == 0 || (n > 1 && self.b[int_start] == b'0') {
                return Err(bad(start));
            }
            if self.b.get(self.i) == Some(&b'.') {
                is_float = true;
                self.i += 1;
                if digits(self) == 0 {
                    return Err(bad(start));
                }
            }
            if matches!(self.b.get(self.i), Some(b'e') | Some(b'E')) {
                is_float = true;
                self.i += 1;
                if matches!(self.b.get(self.i), Some(b'+') | Some(b'-')) {
                    self.i += 1;
                }
                if digits(self) == 0 {
                    return Err(bad(start));
                }
            }
            // ASCII digits, signs, `.` and `e` only
            let tok = std::str::from_utf8(&self.b[start..self.i]).map_err(|_| bad(start))?;
            if let Some(raws) = &mut self.raws {
                raws.push(tok.to_string());
            }
            // `-0`: negative zero (ruling 2b of 0.11)
            if tok.starts_with('-') && tok.bytes().take_while(|b| *b != b'e' && *b != b'E').all(|b| matches!(b, b'-' | b'0' | b'.')) {
                return Ok(Json::Num(-0.0));
            }
            if is_float {
                // a fraction or exponent whose exact value is an integer
                // within i64 keeps every digit (ruling 2d of 0.11)
                if let Some(n) = exact_integer(tok) {
                    return Ok(Json::Int(n));
                }
                tok.parse::<f64>().map(Json::Num).map_err(|_| Error {
                    msg: format!("json: bad number `{}`", tok),
                })
            } else {
                // `-0` is the double -0: parsed as an integer it would lose its sign
                if tok == "-0" {
                    return Ok(Json::Num(-0.0));
                }
                // an integer too large for i64 is still a number
                match tok.parse::<i64>() {
                    Ok(n) => Ok(Json::Int(n)),
                    Err(_) => tok.parse::<f64>().map(Json::Num).map_err(|_| Error {
                        msg: format!("json: bad number `{}`", tok),
                    }),
                }
            }
        }
    }

    /// The exact value of JSON number text, when it is an integer within a
    /// signed 64-bit integer: `1.0`, `1e3`, `9.223372036854775807e18`.
    pub fn exact_integer(tok: &str) -> Option<i64> {
        let (neg, t) = match tok.strip_prefix('-') {
            Some(t) => (true, t),
            None => (false, tok),
        };
        let (mant, exp) = match t.find(['e', 'E']) {
            Some(i) => (&t[..i], &t[i + 1..]),
            None => (t, "0"),
        };
        let (int, frac) = mant.split_once('.').unwrap_or((mant, ""));
        let exp_digits = exp.trim_start_matches(['+', '-']);
        // an exponent of more digits than this is far beyond i64 either way
        let e: i64 = if exp_digits.trim_start_matches('0').len() > 6 {
            if exp.starts_with('-') { -10_000_000 } else { 10_000_000 }
        } else {
            let v: i64 = exp_digits.parse().ok()?;
            if exp.starts_with('-') { -v } else { v }
        };
        let digits: String = format!("{}{}", int, frac);
        let digits = digits.trim_start_matches('0');
        if digits.is_empty() {
            return Some(0);
        }
        let mut scale = e - frac.len() as i64;
        let trimmed = digits.trim_end_matches('0');
        scale += (digits.len() - trimmed.len()) as i64;
        if scale < 0 || trimmed.len() as i64 + scale > 19 {
            return None;
        }
        let mut v: i128 = trimmed.parse().ok()?;
        for _ in 0..scale {
            v *= 10;
        }
        let v = if neg { -v } else { v };
        i64::try_from(v).ok()
    }

    #[cfg(any(feature = "geojson", feature = "json"))]
    pub fn serialize(j: &Json) -> String {
        let mut s = String::new();
        write(j, &mut s);
        s
    }
    #[cfg(any(feature = "geojson", feature = "json"))]
    fn write(j: &Json, out: &mut String) {
        match j {
            Json::Null => out.push_str("null"),
            Json::Raw(text) => out.push_str(text),
            Json::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            Json::Int(n) => out.push_str(&n.to_string()),
            Json::Num(x) => out.push_str(&fmt_f64(*x)),
            Json::Str(s) => {
                out.push('"');
                out.push_str(&escape(s));
                out.push('"');
            }
            Json::Arr(a) => {
                out.push('[');
                for (i, v) in a.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    write(v, out);
                }
                out.push(']');
            }
            Json::Obj(m) => {
                out.push('{');
                for (i, (k, v)) in m.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    out.push('"');
                    out.push_str(&escape(k));
                    out.push_str("\":");
                    write(v, out);
                }
                out.push('}');
            }
        }
    }
    #[cfg(any(feature = "geojson", feature = "json"))]
    fn escape(s: &str) -> String {
        let mut o = String::new();
        for c in s.chars() {
            match c {
                '"' => o.push_str("\\\""),
                '\\' => o.push_str("\\\\"),
                '\n' => o.push_str("\\n"),
                '\t' => o.push_str("\\t"),
                '\r' => o.push_str("\\r"),
                '\u{08}' => o.push_str("\\b"),
                '\u{0c}' => o.push_str("\\f"),
                c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
                _ => o.push(c),
            }
        }
        o
    }
}

/// The text a `when` compares a JSON scalar with: a string as-is, a number or
/// boolean in canonical form. None for null, arrays and objects.
#[cfg(any(feature = "geojson", feature = "json"))]
fn json_when_text(j: &json::Json) -> Option<String> {
    use json::Json;
    match j {
        Json::Str(s) => Some(s.clone()),
        Json::Int(n) => Some(n.to_string()),
        Json::Num(x) => Some(fmt_f64(*x)),
        Json::Bool(b) => Some(b.to_string()),
        _ => None,
    }
}

/// The JSON value a `when` writes (ruling 11 of 0.5): canonical number text as a
/// number, `true` / `false` as a boolean, anything else, or a value written
/// with a leading `=`, as a string.
#[cfg(any(feature = "geojson", feature = "json"))]
fn json_when_value(w: &WhenDef) -> json::Json {
    use json::Json;
    if !w.forced {
        match w.text.as_str() {
            "true" => return Json::Bool(true),
            "false" => return Json::Bool(false),
            _ => {}
        }
        if let Ok(n) = w.text.parse::<i64>() {
            if n.to_string() == w.text {
                return Json::Int(n);
            }
        }
        if w.text.starts_with(|c: char| c.is_ascii_digit() || c == '-') {
            if let Ok(x) = w.text.parse::<f64>() {
                if x.is_finite() && fmt_f64(x) == w.text {
                    return Json::Num(x);
                }
            }
        }
    }
    Json::Str(w.text.clone())
}

/// Does a `when` hold for the member found at its locator?
#[cfg(any(feature = "geojson", feature = "json"))]
fn json_when_holds(member: Option<&json::Json>, w: &WhenDef) -> bool {
    match member {
        None | Some(json::Json::Null) => false,
        Some(_) if w.present => true,
        Some(j) => json_when_text(j).map_or(false, |t| w.holds_text(&t)),
    }
}

#[cfg(feature = "geojson")]
pub mod geojson {
    use super::json::Json;
    use super::*;

    /// The member a `when` locator names: `properties.<name>` or a top-level member.
    fn when_member<'a>(root: &'a Json, locator: &str) -> Option<&'a Json> {
        match locator.strip_prefix("properties.") {
            Some(name) => root.get("properties").and_then(|pp| pp.get(name)),
            None => root.get(locator),
        }
    }

    /// An item value of a group: geojson value types, json locators.
    fn item_dec(t: &Transform, j: &Json, texts: &json::NumTexts) -> Result<Value, Error> {
        if let Some(r) = json::decode_scale(t, j, texts) {
            return r;
        }
        match j {
            Json::Obj(_) | Json::Arr(_) => err("the value is not a scalar"),
            _ => t.decode(&json_scalar_string(j)),
        }
    }

    // locator forms: "id", "geometry.lon|lat|alt", "properties.<name>"
    pub fn decode(p: &Pack, bytes: &str) -> Result<Entity, Error> {
        let _scope = limit::scope();
        let (root, raws) = json::parse_raw(bytes).map_err(|e| Error { msg: format!("malformed-wire: {}", e.msg) })?;
        let texts = json::number_texts(&root, &raws);
        let sel = p.select_decode(None, |w| json_when_holds(when_member(&root, &w.locator), w))?;
        let coords = root
            .get("geometry")
            .and_then(|g| g.get("coordinates"))
            .and_then(|c| if let Json::Arr(a) = c { Some(a) } else { None });
        let mut d = Decoded::new();
        let mapped_props: Vec<&str> = sel.mapped().into_iter().filter_map(|l| l.strip_prefix("properties.")).collect();
        for f in &sel.fields {
            let member: Option<&Json> = if f.locator == "id" {
                root.get("id")
            } else if let Some(slot) = f.locator.strip_prefix("geometry.") {
                let idx = match slot {
                    "lon" => 0,
                    "lat" => 1,
                    "alt" => 2,
                    o => return err(format!("bad geojson geometry slot `{}`", o)),
                };
                coords.and_then(|a| a.get(idx))
            } else if let Some(name) = f.locator.strip_prefix("properties.") {
                root.get("properties").and_then(|pp| pp.get(name))
            } else {
                return err(format!("bad geojson locator `{}`", f.locator));
            };
            // a sentinel: the line yields no value (engine-spec v0.9)
            if member.map_or(false, |j| json_absent(f, j)) {
                continue;
            }
            // `null` on a field that names the option yields no value (engine-spec v0.56)
            if f.null && matches!(member, Some(Json::Null)) {
                continue;
            }
            if let Some(j) = member {
                if let Some(r) = json::decode_scale(&f.transform, j, &texts) {
                    d.put(p, f, r);
                    continue;
                }
            }
            if let Some(r) = member.map(json_scalar_string) {
                d.put(p, f, f.transform.decode(&r));
            }
        }
        // groups: a `properties.<name>` or top-level member whose value is an array
        // an unmapped number outside the double range stays residue with its
        // text as written (ruling 27 of 0.15 limits malformed-wire to `json`)
        jsonwire::decode_groups(p, &sel, &root, item_dec, &texts, &mut d)?;
        // residue: unmapped properties (ruling 13 of 0.6). A number keeps its
        // text as written; an array or object is kept as it was; `null` is
        // dropped; of two members with one name the last value is used at the
        // first position.
        if let Json::Obj(members) = &root {
            // the index, among the document's numbers, of the first number in `properties`
            let mut idx = 0;
            let mut props: Option<&Vec<(String, Json)>> = None;
            for (k, v) in members {
                if k == "properties" {
                    if let Json::Obj(m) = v {
                        props = Some(m);
                    }
                    break;
                }
                idx += json::count_numbers(v);
            }
            // (member name, locator, value)
            let mut kept: Vec<(&str, String, Option<String>)> = Vec::new();
            // where each name is in `kept`, so many members cost n log n, not n * n
            let mut kept_at: BTreeMap<&str, usize> = BTreeMap::new();
            for (k, v) in props.into_iter().flatten() {
                let mut at = idx;
                idx += json::count_numbers(v);
                if mapped_props.contains(&k.as_str()) {
                    continue;
                }
                let scalar = format!("properties.{}", k);
                let (locator, value) = match v {
                    Json::Null => (scalar, None),
                    Json::Int(_) | Json::Num(_) => (scalar, Some(json::serialize_raw(v, &raws, &mut at))),
                    Json::Arr(_) | Json::Obj(_) => {
                        (format!("properties#json.{}", k), Some(json::serialize_raw(v, &raws, &mut at)))
                    }
                    other => (scalar, Some(json_scalar_string(other))),
                };
                match kept_at.get(k.as_str()) {
                    Some(at) => kept[*at] = (k, locator, value),
                    None => {
                        kept_at.insert(k, kept.len());
                        kept.push((k, locator, value));
                    }
                }
            }
            for (_, locator, value) in kept {
                if let Some(value) = value {
                    d.ent.residue.push((p.format.clone(), locator, value));
                }
            }
        }
        d.finish(p, &sel)
    }

    pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
        let sel = p.select_encode(ent)?;
        let mut lon: Option<Json> = None;
        let mut lat: Option<Json> = None;
        let mut alt: Option<Json> = None;
        let mut props: Vec<(String, Json)> = Vec::new();
        // mapped top-level members (`id`, top-level `when` members)
        let mut top: Vec<(String, Json)> = Vec::new();
        // a field keeps a value an earlier line wrote; a `when` replaces it
        fn set(list: &mut Vec<(String, Json)>, name: &str, v: Json, replace: bool) {
            match list.iter().position(|(k, _)| k == name) {
                Some(i) if replace => list[i].1 = v,
                Some(_) => {}
                None => list.push((name.to_string(), v)),
            }
        }
        // fields and `when` values in line order (ruling 10 of 0.5)
        let mut lines: Vec<(usize, &str, Json, bool)> = Vec::new();
        for f in &sel.fields {
            let v = match sel.value_of(ent, f) {
                Some(v) => v,
                None => continue,
            };
            let jv = p
                .to_wire(f, v)
                .and_then(|w| value_to_json(&f.transform, &w))
                .map_err(|e| transform_encode_err(p, f, e))?;
            lines.push((f.line, &f.locator, jv, false));
        }
        // an absent key whose field has `absent` writes its first sentinel
        // where no line with a value writes (engine-spec v0.9, rulings 10 and 16)
        for (f, sn) in sentinel_lines(&sel, ent, |_| false) {
            lines.push((f.line, &f.locator, sentinel_json(sn), false));
        }
        // `null` (engine-spec v0.56) where no line writes a value or a sentinel
        let written: Vec<&str> = lines.iter().map(|l| l.1).collect();
        for f in null_lines(&sel, ent, &written) {
            lines.push((f.line, &f.locator, Json::Null, false));
        }
        for w in sel.fixed() {
            lines.push((w.line, &w.locator, json_when_value(w), true));
        }
        // a list that is present: an array at the group's member
        for g in &sel.groups {
            if let Some(items) = ent.lists.get(&g.list) {
                lines.push((g.line, &g.locator, jsonwire::list_json(p, g, items, value_to_json)?, false));
            }
        }
        // a place several lines name is written at the position of the first
        // of them, whichever line's value or sentinel is written (ruling 23 of 0.9)
        let firsts = first_lines(sel.fields.iter().map(|f| (f.line, f.locator.as_str())).chain(lines.iter().map(|l| (l.0, l.1))));
        lines.sort_by_key(|l| (firsts[l.1], l.0));
        for (_, locator, jv, is_when) in lines {
            if let Some(slot) = locator.strip_prefix("geometry.") {
                let target = match slot {
                    "lon" => &mut lon,
                    "lat" => &mut lat,
                    "alt" => &mut alt,
                    o => return err(format!("bad geojson geometry slot `{}`", o)),
                };
                if target.is_none() {
                    *target = Some(jv);
                }
            } else if let Some(name) = locator.strip_prefix("properties.") {
                set(&mut props, name, jv, is_when);
            } else {
                set(&mut top, locator, jv, is_when);
            }
        }
        // residue belonging to this format
        for (fmt, loc, raw) in &ent.residue {
            if fmt == &p.format {
                // a scalar comes back as a string, an array or object as it was
                let (name, value) = match (loc.strip_prefix("properties."), loc.strip_prefix("properties#json.")) {
                    (Some(name), _) => (name, Json::Str(raw.clone())),
                    (_, Some(name)) => (name, Json::Raw(raw.clone())),
                    _ => continue,
                };
                if !props.iter().any(|(k, _)| k == name) {
                    props.push((name.to_string(), value));
                }
            }
        }
        // assemble canonical Feature
        let mut obj: Vec<(String, Json)> = Vec::new();
        obj.push(("type".into(), Json::Str("Feature".into())));
        // ruling 5 of 0.1.1: without both lon and lat the geometry is null
        if let (Some(lon), Some(lat)) = (lon, lat) {
            let mut arr = vec![lon, lat];
            if let Some(a) = alt {
                arr.push(a);
            }
            obj.push((
                "geometry".into(),
                Json::Obj(vec![
                    ("type".into(), Json::Str("Point".into())),
                    ("coordinates".into(), Json::Arr(arr)),
                ]),
            ));
        } else {
            obj.push(("geometry".into(), Json::Null));
        }
        obj.push(("properties".into(), Json::Obj(props)));
        obj.extend(top);
        Ok(json::serialize(&Json::Obj(obj)))
    }

    fn value_to_json(t: &Transform, v: &Value) -> Result<Json, Error> {
        let s = t.encode(v)?;
        Ok(match t.json_kind() {
            JsonKind::StringK => Json::Str(s),
            JsonKind::IntK => Json::Int(s.parse::<i64>().map_err(|_| Error {
                msg: format!("geojson int encode `{}`", s),
            })?),
            JsonKind::NumK => Json::Num(s.parse::<f64>().map_err(|_| Error {
                msg: format!("geojson num encode `{}`", s),
            })?),
            // the exact digits, never through a double (ruling 7 of 0.15)
            JsonKind::ExactK => Json::Raw(s),
        })
    }

    fn json_scalar_string(j: &Json) -> String {
        match j {
            Json::Str(s) => s.clone(),
            Json::Int(n) => n.to_string(),
            Json::Num(x) => fmt_f64(*x),
            Json::Bool(b) => b.to_string(),
            Json::Null => String::new(),
            _ => String::new(),
        }
    }
}

// ---------------------------------------------------------------------------
// json wire (engine-spec v0.5): any JSON object, members addressed by path.
// ---------------------------------------------------------------------------

#[cfg(any(feature = "json", feature = "geojson"))]
pub mod jsonwire {
    use super::json::Json;
    use super::*;

    /// The member at a dot-path; None when a step is missing or not an object.
    fn lookup<'a>(root: &'a Json, path: &str) -> Option<&'a Json> {
        let mut cur = root;
        for name in path.split('.') {
            cur = cur.get(name)?;
        }
        Some(cur)
    }

    #[cfg(feature = "json")]
    fn decode_value(t: &Transform, j: &Json, texts: &json::NumTexts) -> Result<Value, Error> {
        if let Some(r) = json::decode_scale(t, j, texts) {
            return r;
        }
        match (t, j) {
            (Transform::StringT, Json::Str(s)) => Ok(Value::Str(s.clone())),
            (Transform::Float, Json::Int(n)) => Ok(Value::F64(*n as f64)),
            (Transform::Float, Json::Num(x)) => finite(*x),
            (Transform::Int, Json::Int(n)) => Ok(Value::I64(*n)),
            // an integer within i64 was read as `Int`; negative zero is 0 (ruling 2d of 0.11)
            (Transform::Int, Json::Num(x)) if *x == 0.0 => Ok(Value::I64(0)),
            (Transform::Iso8601Ms | Transform::Iso8601Short | Transform::Iso8601Si, Json::Str(s)) => iso8601_to_ms(s).map(Value::I64),
            (Transform::Bool, Json::Bool(b)) => Ok(Value::I64(*b as i64)),
            _ => err(format!("JSON value `{}` has the wrong type for the transform", json::serialize(j))),
        }
    }

    #[cfg(feature = "json")]
    fn encode_value(t: &Transform, v: &Value) -> Result<Json, Error> {
        match (t, v) {
            (Transform::StringT, Value::Str(s)) => Ok(Json::Str(s.clone())),
            (Transform::Float, Value::F64(x)) if x.is_finite() => Ok(Json::Num(*x)),
            (Transform::Int, Value::I64(n)) => Ok(Json::Int(*n)),
            (Transform::Iso8601Ms, Value::I64(ms)) => Ok(Json::Str(ms_to_iso8601_checked(*ms)?)),
            (Transform::Iso8601Short, Value::I64(ms)) => Ok(Json::Str(ms_to_iso8601_short(*ms)?)),
            (Transform::Iso8601Si, Value::I64(ms)) => Ok(Json::Str(ms_to_iso8601_si(*ms)?)),
            (Transform::Bool, Value::I64(1)) => Ok(Json::Bool(true)),
            (Transform::Bool, Value::I64(0)) => Ok(Json::Bool(false)),
            (Transform::Bool, other) => err(format!("bool encodes 1 or 0, got {}", other.as_display())),
            (Transform::TextScale(sc), Value::F64(x)) => Ok(Json::Num(text_unscale(sc, *x)?)),
            // the exact digits, never through a double (ruling 7 of 0.15)
            (Transform::TextIscale(_), Value::I64(_)) => Ok(Json::Raw(t.encode(v)?)),
            _ => err(format!("transform/value mismatch: {:?} with {:?}", t, v)),
        }
    }

    /// How a wire turns a JSON value into a model value, and back.
    pub(crate) type Dec = fn(&Transform, &Json, &json::NumTexts) -> Result<Value, Error>;
    pub(crate) type Enc = fn(&Transform, &Value) -> Result<Json, Error>;

    /// Decode the fields and groups of one scope: the message object, or one
    /// array element of a group.
    fn decode_scope(
        p: &Pack,
        sel: &Sel,
        obj: &Json,
        item: bool,
        dec: Dec,
        texts: &json::NumTexts,
        d: &mut Decoded,
    ) -> Result<(), Error> {
        for f in &sel.fields {
            // `.`: the element itself, when it is a scalar
            let found = if item && f.locator == "." {
                match obj {
                    Json::Obj(_) | Json::Arr(_) => {
                        d.put(p, f, err("the item is not a scalar"));
                        continue;
                    }
                    scalar => Some(scalar),
                }
            } else {
                lookup(obj, &f.locator)
            };
            match found {
                // `null` is no value, before any sentinel check (ruling 5 of 0.9)
                None | Some(Json::Null) => {}
                // a sentinel: the line yields no value (engine-spec v0.9)
                Some(j) if json_absent(f, j) => texts.mark(j),
                Some(j) => {
                    texts.mark(j);
                    d.put(p, f, dec(&f.transform, j, texts))
                }
            }
        }
        decode_groups(p, sel, obj, dec, texts, d)
    }

    /// The groups of one scope: the member at the group's path is an array,
    /// each element one item. `null` and a missing member: the list is absent.
    pub(crate) fn decode_groups(
        p: &Pack,
        sel: &Sel,
        obj: &Json,
        dec: Dec,
        texts: &json::NumTexts,
        d: &mut Decoded,
    ) -> Result<(), Error> {
        for g in &sel.groups {
            let elements = match lookup(obj, &g.locator) {
                None | Some(Json::Null) => continue,
                Some(Json::Arr(a)) => a,
                Some(_) => {
                    return err(format!(
                        "malformed-wire: format `{}`: member `{}` of list `{}` is not an array",
                        p.format, g.locator, g.list
                    ))
                }
            };
            let body = g.body();
            d.replacing(&g.list);
            let mut items = Vec::new();
            for e in elements {
                limit::take(&p.format, &g.list, 1)?;
                let mut di = Decoded::new();
                decode_scope(p, &body, e, true, dec, texts, &mut di)?;
                items.push(di);
            }
            d.put_list(&g.list, items);
        }
        Ok(())
    }

    #[cfg(feature = "json")]
    pub fn decode(p: &Pack, bytes: &str) -> Result<Entity, Error> {
        let _scope = limit::scope();
        let (root, raws) = json::parse_raw(bytes).map_err(|e| Error { msg: format!("malformed-wire: {}", e.msg) })?;
        let texts = json::number_texts(&root, &raws);
        if !matches!(root, Json::Obj(_)) {
            return err(format!("malformed-wire: format `{}`: the message is not a JSON object", p.format));
        }
        // ruling 22 of 0.5: the same member name twice in one object
        fn twice(j: &Json) -> Option<&str> {
            match j {
                Json::Obj(m) => {
                    // a set, so an object of many members costs n log n, not n * n
                    let mut seen: std::collections::BTreeSet<&str> = std::collections::BTreeSet::new();
                    for (k, v) in m.iter() {
                        if !seen.insert(k.as_str()) {
                            return Some(k);
                        }
                        if let Some(name) = twice(v) {
                            return Some(name);
                        }
                    }
                    None
                }
                Json::Arr(a) => a.iter().find_map(twice),
                _ => None,
            }
        }
        if let Some(name) = twice(&root) {
            return err(format!("malformed-wire: format `{}`: member `{}` appears twice in one object", p.format, name));
        }
        let sel = p.select_decode(None, |w| json_when_holds(lookup(&root, &w.locator), w))?;
        let mut d = Decoded::new();
        decode_scope(p, &sel, &root, false, decode_value, &texts, &mut d)?;
        if texts.unread_out_of_range(&root) {
            return err(format!("malformed-wire: format `{}`: a number no field maps is outside the double range", p.format));
        }
        // residue: every scalar member, at any depth, that no line maps
        let mapped: Vec<&str> = sel.mapped();
        fn walk(obj: &Json, prefix: &str, mapped: &[&str], format: &str, out: &mut Vec<(String, String, String)>) -> Result<(), Error> {
            if let Json::Obj(members) = obj {
                for (k, v) in members {
                    // a member name with `.` has no path in 0.5: not carried
                    if k.contains('.') || k.is_empty() {
                        continue;
                    }
                    let path = if prefix.is_empty() { k.clone() } else { format!("{}.{}", prefix, k) };
                    match v {
                        Json::Obj(_) => walk(v, &path, mapped, format, out)?,
                        Json::Arr(_) | Json::Null => {}
                        scalar => {
                            if !mapped.contains(&path.as_str()) {
                                // a residue number whose nearest double is infinite has no canonical text (2d)
                                if matches!(scalar, Json::Num(x) if !x.is_finite()) {
                                    return err(format!(
                                        "malformed-wire: format `{}`: the number at `{}` is beyond the range of a double",
                                        format, path
                                    ));
                                }
                                out.push((format.to_string(), path, json::serialize(scalar)));
                            }
                        }
                    }
                }
            }
            Ok(())
        }
        walk(&root, "", &mapped, &p.format, &mut d.ent.residue)?;
        d.finish(p, &sel)
    }

    /// The object that holds the last name of `path`, creating the nested
    /// objects on the way at the end of their parent. None if a step is taken
    /// by a scalar.
    fn parent_of<'a>(obj: &'a mut Vec<(String, Json)>, path: &[&str]) -> Option<&'a mut Vec<(String, Json)>> {
        let mut cur = obj;
        for name in &path[..path.len() - 1] {
            let tmp = cur;
            let idx = match tmp.iter().position(|(k, _)| k == name) {
                Some(i) => i,
                None => {
                    tmp.push((name.to_string(), Json::Obj(Vec::new())));
                    tmp.len() - 1
                }
            };
            cur = match &mut tmp[idx].1 {
                Json::Obj(m) => m,
                _ => return None,
            };
        }
        Some(cur)
    }

    /// Drop nested objects that ended with no members.
    fn prune(members: &mut Vec<(String, Json)>) {
        for (_, v) in members.iter_mut() {
            if let Json::Obj(m) = v {
                prune(m);
            }
        }
        members.retain(|(_, v)| !matches!(v, Json::Obj(m) if m.is_empty()));
    }

    /// The array a present list is written as: one element per item.
    pub(crate) fn list_json(p: &Pack, g: &GroupDef, items: &[Entity], enc: Enc) -> Result<Json, Error> {
        let body = g.body();
        let mut out = Vec::new();
        for item in items {
            // a `.` line: the element is the scalar itself
            let scalar = body.fields.iter().filter(|f| f.locator == ".").find_map(|f| body.value_of(item, f).map(|v| (f, v)));
            out.push(match scalar {
                Some((f, v)) => {
                    p.to_wire(f, v).and_then(|w| enc(&f.transform, &w)).map_err(|e| transform_encode_err(p, f, e))?
                }
                None => {
                    // an item with no members written is `{}`
                    let mut members = build(p, &body, item, enc)?;
                    prune(&mut members);
                    // a scalar (`.`) item with no value is `null` (ruling 11 of 0.7),
                    // or the sentinel of its field (ruling 5 of 0.9)
                    if members.is_empty() && g.scalar().is_some() {
                        // a `.` line suppressed by `with` writes no sentinel (ruling 4 of 0.18)
                        match body.fields.iter().filter(|f| f.locator == "." && live(item, f)).find_map(|f| f.sentinel()) {
                            Some(s) => sentinel_json(s),
                            None => Json::Null,
                        }
                    } else {
                        Json::Obj(members)
                    }
                }
            });
        }
        Ok(Json::Arr(out))
    }

    /// The members one scope writes, before residue: the message object, or
    /// one object item of a group.
    fn build(p: &Pack, sel: &Sel, ent: &Entity, enc: Enc) -> Result<Vec<(String, Json)>, Error> {
        // every line in force, in line order: (line, path, value to write if any)
        let mut lines: Vec<(usize, &str, Option<Json>, bool)> = Vec::new();
        for f in sel.fields.iter().filter(|f| f.locator != ".") {
            let jv = match sel.value_of(ent, f) {
                None => None,
                Some(v) => Some(
                    p.to_wire(f, v)
                        .and_then(|w| enc(&f.transform, &w))
                        .map_err(|e| transform_encode_err(p, f, e))?,
                ),
            };
            lines.push((f.line, &f.locator, jv, false));
        }
        // an absent key whose field has `absent` writes its first sentinel
        // where no line with a value writes (engine-spec v0.9)
        for (f, sn) in sentinel_lines(sel, ent, |f| f.locator == ".") {
            if let Some(l) = lines.iter_mut().find(|l| l.0 == f.line) {
                l.2 = Some(sentinel_json(sn));
            }
        }
        // `null` (engine-spec v0.56): an absent key writes `null` where no
        // line on the member writes a value or a sentinel (ruling 1)
        for f in null_lines(sel, ent, &lines.iter().filter(|l| l.2.is_some()).map(|l| l.1).collect::<Vec<_>>()) {
            if let Some(l) = lines.iter_mut().find(|l| l.0 == f.line) {
                l.2 = Some(Json::Null);
            }
        }
        // a `present` line writes nothing, but its nested objects take its position
        for w in sel.whens.iter().filter(|w| w.present) {
            lines.push((w.line, &w.locator, None, true));
        }
        for w in sel.fixed() {
            lines.push((w.line, &w.locator, Some(json_when_value(w)), true));
        }
        // a group line addresses its locator; a present list writes an array there
        for g in &sel.groups {
            let jv = match ent.lists.get(&g.list) {
                Some(items) => Some(list_json(p, g, items, enc)?),
                None => None,
            };
            lines.push((g.line, &g.locator, jv, false));
        }
        // a place several lines name is written at the position of the first
        // of them, whichever line's value or sentinel is written (ruling 23 of 0.9)
        // a `when <locator> present` line names no position
        let firsts = first_lines(lines.iter().filter(|l| !(l.3 && l.2.is_none())).map(|l| (l.0, l.1)));
        lines.sort_by_key(|l| (firsts.get(l.1).copied().unwrap_or(l.0).min(l.0), l.0));
        let mut top: Vec<(String, Json)> = Vec::new();
        for (_, path, value, is_when) in lines {
            let names: Vec<&str> = path.split('.').collect();
            // a nested object takes the position of the first line that addresses into it
            let parent = parent_of(&mut top, &names)
                .ok_or(Error {
                    msg: format!("transform-encode: format `{}`: path `{}` runs through a scalar member", p.format, path),
                })?;
            if let Some(v) = value {
                let leaf = names[names.len() - 1];
                // a field keeps the value an earlier line wrote; a `when` replaces it
                match parent.iter().position(|(k, _)| k == leaf) {
                    Some(i) if is_when => parent[i].1 = v,
                    Some(_) => {}
                    None => parent.push((leaf.to_string(), v)),
                }
            }
        }
        Ok(top)
    }

    #[cfg(feature = "json")]
    pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
        let sel = p.select_encode(ent)?;
        let mut top = build(p, &sel, ent, encode_value)?;
        // residue of this format, after the mapped members of each object
        for (fmt, path, text) in &ent.residue {
            if fmt != &p.format {
                continue;
            }
            let names: Vec<&str> = path.split('.').collect();
            let value = match json::parse(text) {
                Ok(v) => v,
                Err(_) => continue,
            };
            if let Some(parent) = parent_of(&mut top, &names) {
                let leaf = names[names.len() - 1];
                if !parent.iter().any(|(k, _)| k == leaf) {
                    parent.push((leaf.to_string(), value));
                }
            }
        }
        prune(&mut top);
        Ok(json::serialize(&Json::Obj(top)))
    }
}

// ---------------------------------------------------------------------------
// bits codec: fixed-size binary words, fields are bit ranges. I/O as hex text.
// ---------------------------------------------------------------------------

pub mod bits {
    use super::*;

    // locator: "<word>:<pos>:<len>". The field is `len` bits from message bit
    // `word * word_bytes * 8 + pos`; it may run past its word (engine-spec v0.5).
    pub(crate) fn parse_locator(loc: &str) -> Result<(usize, u32, u32), Error> {
        let p: Vec<&str> = loc.split(':').collect();
        if p.len() != 3 {
            return err(format!("bits locator must be word:pos:len, got `{}`", loc));
        }
        // unsigned decimal integers (ruling 2c of 0.11): no sign
        let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
        let word = Some(p[0]).filter(|s| digits(s)).and_then(|s| s.parse::<usize>().ok()).ok_or(Error { msg: format!("bad word in `{}`", loc) })?;
        let pos = Some(p[1]).filter(|s| digits(s)).and_then(|s| s.parse::<u32>().ok()).ok_or(Error { msg: format!("bad pos in `{}`", loc) })?;
        let len = Some(p[2]).filter(|s| digits(s)).and_then(|s| s.parse::<u32>().ok()).ok_or(Error { msg: format!("bad len in `{}`", loc) })?;
        if len == 0 {
            return err(format!("bits len must be at least 1 in `{}`", loc));
        }
        Ok((word, pos, len))
    }

    /// A group locator `<word>:<pos>`: where the first item starts.
    pub(crate) fn parse_group_locator(loc: &str) -> Result<(usize, u32), Error> {
        let bad = || Error { msg: format!("bits group locator must be word:pos, got `{}`", loc) };
        let (w, p) = loc.split_once(':').ok_or_else(bad)?;
        let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
        if !digits(w) || !digits(p) {
            return Err(bad());
        }
        Ok((w.parse::<usize>().map_err(|_| bad())?, p.parse::<u32>().map_err(|_| bad())?))
    }

    /// (first bit of the first item, bits per item) of a group, from the
    /// first bit of its scope.
    #[cfg(feature = "bits")]
    fn group_span(p: &Pack, g: &GroupDef) -> Result<(u64, u64), Error> {
        let (word, pos) = parse_group_locator(&g.locator)?;
        Ok((word as u64 * p.word_bytes as u64 * 8 + pos as u64, g.item_bits.unwrap_or(1)))
    }

    /// (first message bit, bit length) of a locator.
    #[cfg(feature = "bits")]
    pub(crate) fn span(p: &Pack, loc: &str) -> Result<(u64, u32), Error> {
        let (word, pos, len) = parse_locator(loc)?;
        Ok((word as u64 * p.word_bytes as u64 * 8 + pos as u64, len))
    }

    /// Read `len` (1..=64) bits from message bit `start`. None when the range
    /// runs past the input. lsb: bit i is bit `i mod 8` of byte `i div 8`, first
    /// bit least significant. msb: bit i is bit `7 - (i mod 8)`, first bit most
    /// significant. msb-lsb: bit i as with msb, first bit least significant
    /// (engine-spec v0.22).
    #[cfg(feature = "bits")]
    pub(crate) fn get_bits(msg: &[u8], start: u64, len: u32, order: BitOrder) -> Option<u64> {
        match start.checked_add(len as u64) {
            Some(end) if end <= msg.len() as u64 * 8 => {}
            _ => return None,
        }
        let mut v: u64 = 0;
        for k in 0..len as u64 {
            let bit = start + k;
            let byte = msg[(bit / 8) as usize];
            let on = match order {
                BitOrder::Lsb => byte & (1 << (bit % 8)) != 0,
                BitOrder::Msb | BitOrder::MsbLsb => byte & (0x80 >> (bit % 8)) != 0,
            };
            if on {
                v |= match order {
                    BitOrder::Msb => 1u64 << (len as u64 - 1 - k),
                    BitOrder::Lsb | BitOrder::MsbLsb => 1u64 << k,
                };
            }
        }
        Some(v)
    }

    #[cfg(feature = "bits")]
    pub(crate) fn set_bits(msg: &mut [u8], start: u64, len: u32, raw: u64, order: BitOrder) {
        for k in 0..len as u64 {
            let bit = start + k;
            let idx = (bit / 8) as usize;
            if idx >= msg.len() {
                continue;
            }
            let on = match order {
                BitOrder::Msb => raw & (1u64 << (len as u64 - 1 - k)) != 0,
                BitOrder::Lsb | BitOrder::MsbLsb => raw & (1u64 << k) != 0,
            };
            let mask = match order {
                BitOrder::Lsb => 1u8 << (bit % 8),
                BitOrder::Msb | BitOrder::MsbLsb => 0x80u8 >> (bit % 8),
            };
            if on {
                msg[idx] |= mask;
            } else {
                msg[idx] &= !mask;
            }
        }
    }

    /// Message length in bytes: as many whole words as the furthest mapped,
    /// `when` or `const` bit reaches, over the lines in force. `all`: count
    /// `optional` fields too (encode writes them; decode does not need them).
    #[cfg(feature = "bits")]
    fn message_bytes(p: &Pack, sel: &Sel, all: bool) -> Result<usize, Error> {
        let end = message_end(p, sel, all)?;
        let word_bits = p.word_bytes as u64 * 8;
        let words = ((end + word_bits - 1) / word_bits).max(1);
        Ok(words as usize * p.word_bytes)
    }

    /// The furthest bit the lines in force reach, not rounded to a word.
    #[cfg(feature = "bits")]
    fn message_end(p: &Pack, sel: &Sel, all: bool) -> Result<u64, Error> {
        let mut end: u64 = 0;
        let locators = sel
            .fields
            .iter()
            .filter(|f| all || !f.optional)
            .map(|f| &f.locator)
            .chain(sel.fixed().map(|w| &w.locator));
        for loc in locators {
            let (start, len) = span(p, loc)?;
            end = end.max(start + len as u64);
        }
        Ok(end)
    }

    /// The low `len` bits of `raw` with their bytes in reverse order (`swap`).
    #[cfg(feature = "bits")]
    fn swap_bytes(raw: u64, len: u32) -> u64 {
        raw.swap_bytes() >> (64 - len)
    }

    /// The characters of a list of codes; a code the set does not define is an error.
    #[cfg(feature = "bits")]
    pub(crate) fn chars_text(set: CharSet, codes: &[u32]) -> Result<String, Error> {
        let mut text = String::with_capacity(codes.len());
        for c in codes {
            match set.char_of(*c) {
                Some(ch) => text.push(ch),
                None => return err(format!("code {} is not in the character set {:?}", c, set)),
            }
        }
        Ok(text)
    }

    /// The value of a field whose `len` bits start at message bit `start`,
    /// through its transform. The caller has checked the bits are in the input.
    #[cfg(feature = "bits")]
    pub(crate) fn read_field(p: &Pack, f: &FieldDef, raw: &[u8], start: u64, len: u32) -> Result<Value, Error> {
        if f.transform == Transform::Sixbit {
            return armor::read_sixbit(p, f, raw, start, len);
        }
        if f.transform == Transform::Ascii {
            // bytes first to last, each byte's bits in the pack's bit order
            let mut bytes: Vec<u8> =
                (0..len as u64 / 8).map(|k| get_bits(raw, start + k * 8, 8, p.order).unwrap_or(0) as u8).collect();
            if f.swap {
                bytes.reverse();
            }
            while bytes.last() == Some(&0) {
                bytes.pop();
            }
            while f.trim && bytes.last() == Some(&0x20) {
                bytes.pop();
            }
            match bytes.iter().find(|b| !(0x20..=0x7e).contains(*b)) {
                Some(b) => err(format!("byte 0x{:02x} is not printable ASCII", b)),
                None => Ok(Value::Str(bytes.iter().map(|b| *b as char).collect())),
            }
        } else if f.transform == Transform::Utf8 {
            // engine-spec v0.55: bytes as `ascii` takes them, read as UTF-8
            let mut bytes: Vec<u8> =
                (0..len as u64 / 8).map(|k| get_bits(raw, start + k * 8, 8, p.order).unwrap_or(0) as u8).collect();
            if f.swap {
                bytes.reverse();
            }
            while bytes.last() == Some(&0) {
                bytes.pop();
            }
            while f.trim && bytes.last() == Some(&0x20) {
                bytes.pop();
            }
            if bytes.contains(&0) {
                return err("a NUL byte inside utf8 text".to_string());
            }
            match String::from_utf8(bytes) {
                Ok(s) => Ok(Value::Str(s)),
                Err(e) => err(format!("not valid UTF-8: {}", e)),
            }
        } else if f.transform == Transform::Hex {
            // digit k: the 4-bit field at bit 4k, as `uint` reads it (engine-spec v0.22)
            let text: String = (0..len as u64 / 4)
                .map(|k| {
                    let d = get_bits(raw, start + k * 4, 4, p.order).unwrap_or(0) as u32;
                    char::from_digit(d, 16).unwrap_or('0')
                })
                .collect();
            Ok(Value::Str(text))
        } else if let Transform::Chars(set) = f.transform {
            // character i: the w bits from bit i × w of the field, as `uint` reads them (engine-spec v0.15)
            let w = set.width();
            let codes: Vec<u32> =
                (0..(len / w) as u64).map(|i| get_bits(raw, start + i * w as u64, w, p.order).unwrap_or(0) as u32).collect();
            // `stop <code>` (engine-spec v0.22): the text is the characters before
            // the first terminator, compared before the set's check (ruling 9)
            if let Some(stop) = f.stop {
                if let Some(at) = codes.iter().position(|c| *c == stop) {
                    return chars_text(set, &codes[..at]).map(Value::Str);
                }
            }
            let mut text: Vec<char> = chars_text(set, &codes)?.chars().collect();
            match set {
                CharSet::Ascii7 | CharSet::Ascii8 => {
                    // NUL is padding: a NUL followed by a character that is not NUL fails
                    if let Some(i) = text.iter().position(|c| *c == '\0') {
                        if text[i..].iter().any(|c| *c != '\0') {
                            return err("a NUL is followed by a character that is not NUL");
                        }
                        text.truncate(i);
                    }
                }
                CharSet::Icao6 => {
                    while text.last() == Some(&' ') {
                        text.pop();
                    }
                }
                CharSet::Ais6 => {
                    while matches!(text.last(), Some('@') | Some(' ')) {
                        text.pop();
                    }
                }
            }
            Ok(Value::Str(text.into_iter().collect()))
        } else {
            let mut rawv = get_bits(raw, start, len, p.order).unwrap_or(0);
            if f.swap {
                rawv = swap_bytes(rawv, len);
            }
            f.transform.decode_bits(rawv, len)
        }
    }

    /// Write the wire value `v` of a field into its `len` bits at message bit `start`.
    #[cfg(feature = "bits")]
    pub(crate) fn write_field(p: &Pack, f: &FieldDef, v: &Value, start: u64, len: u32, msg: &mut [u8]) -> Result<(), Error> {
        if f.transform == Transform::Sixbit {
            return armor::write_sixbit(p, f, v, start, len, msg);
        }
        if f.transform == Transform::Ascii {
            let fail = |m: String| transform_encode_err(p, f, Error { msg: m });
            let text = match v {
                Value::Str(s) => s.as_bytes(),
                other => return Err(fail(format!("ascii encodes text, got {:?}", other))),
            };
            let room = (len / 8) as usize;
            if text.len() > room {
                return Err(fail(format!("text is {} bytes, the field holds {}", text.len(), room)));
            }
            // ruling 19 of 0.5
            if let Some(b) = text.iter().find(|b| !(0x20..=0x7e).contains(*b)) {
                return Err(fail(format!("byte 0x{:02x} is not printable ASCII", b)));
            }
            let mut bytes: Vec<u8> = (0..room).map(|k| text.get(k).copied().unwrap_or(0)).collect();
            if f.swap {
                bytes.reverse();
            }
            for (k, b) in bytes.iter().enumerate() {
                set_bits(msg, start + k as u64 * 8, 8, *b as u64, p.order);
            }
        } else if f.transform == Transform::Utf8 {
            // engine-spec v0.55: the text's UTF-8 bytes, NUL-padded
            let fail = |m: String| transform_encode_err(p, f, Error { msg: m });
            let text = match v {
                Value::Str(s) => s.as_bytes(),
                other => return Err(fail(format!("utf8 encodes text, got {:?}", other))),
            };
            let room = (len / 8) as usize;
            if text.contains(&0) {
                return Err(fail("the text holds U+0000".to_string()));
            }
            if text.len() > room {
                return Err(fail(format!("text is {} bytes, the field holds {}", text.len(), room)));
            }
            let mut bytes: Vec<u8> = (0..room).map(|k| text.get(k).copied().unwrap_or(0)).collect();
            if f.swap {
                bytes.reverse();
            }
            for (k, b) in bytes.iter().enumerate() {
                set_bits(msg, start + k as u64 * 8, 8, *b as u64, p.order);
            }
        } else if let Transform::Chars(set) = f.transform {
            let fail = |m: String| transform_encode_err(p, f, Error { msg: m });
            let text = match v {
                Value::Str(s) => s,
                other => return Err(fail(format!("chars encodes text, got {:?}", other))),
            };
            let w = set.width();
            let room = (len / w) as usize;
            let n = text.chars().count();
            // `stop` (engine-spec v0.22): the terminator needs a character of its own
            let need = n + f.stop.is_some() as usize;
            if need > room {
                return Err(fail(match f.stop {
                    Some(_) => format!("text is {} characters and its terminator, the field holds {}", n, room),
                    None => format!("text is {} characters, the field holds {}", n, room),
                }));
            }
            let mut codes = Vec::with_capacity(room);
            for ch in text.chars() {
                // with `stop`, NUL is a character with code 0 (rulings 6 and 21 of 0.22)
                let code = match (ch, set, f.stop) {
                    ('\0', CharSet::Ascii7 | CharSet::Ascii8, Some(_)) => Some(0),
                    _ => set.code_of(ch),
                };
                match code {
                    Some(c) if Some(c) == f.stop => {
                        return Err(fail(format!("character {:?} is the terminator, code {}", ch, c)))
                    }
                    Some(c) => codes.push(c),
                    None => return Err(fail(format!("character {:?} is not in the character set {:?}", ch, set))),
                }
            }
            if let Some(stop) = f.stop {
                codes.push(stop);
            }
            codes.resize(room, set.pad());
            for (i, c) in codes.iter().enumerate() {
                set_bits(msg, start + i as u64 * w as u64, w, *c as u64, p.order);
            }
        } else if f.transform == Transform::Hex {
            let fail = |m: String| transform_encode_err(p, f, Error { msg: m });
            let text = match v {
                Value::Str(s) => s,
                other => return Err(fail(format!("hex encodes text, got {:?}", other))),
            };
            let digits = (len / 4) as usize;
            // either case is read (engine-spec v0.22)
            let ds: Option<Vec<u32>> = text.chars().map(|c| c.to_digit(16)).collect();
            match ds {
                Some(ds) if ds.len() == digits => {
                    for (k, d) in ds.iter().enumerate() {
                        set_bits(msg, start + k as u64 * 4, 4, *d as u64, p.order);
                    }
                }
                _ => return Err(fail(format!("`{}` is not {} hex digits", text, digits))),
            }
        } else {
            let mut rawv = f.transform.encode_bits(v, len).map_err(|e| transform_encode_err(p, f, e))?;
            if f.swap {
                rawv = swap_bytes(rawv, len);
            }
            set_bits(msg, start, len, rawv, p.order);
        }
        Ok(())
    }

    /// Does the field's `len` bits at `start` hold one of its sentinels? The
    /// bits read as `uint` reads them, after `swap` (engine-spec v0.9). The
    /// caller has checked the bits are in the input.
    #[cfg(feature = "bits")]
    pub(crate) fn is_sentinel(p: &Pack, f: &FieldDef, raw: &[u8], start: u64, len: u32) -> bool {
        if f.absent.is_empty() || len > 64 {
            return false;
        }
        let mut v = get_bits(raw, start, len, p.order).unwrap_or(0);
        if f.swap {
            v = swap_bytes(v, len);
        }
        f.absent_num(v)
    }

    /// Write the first sentinel of a field into its `len` bits at `start`:
    /// the low `len` bits, then `swap`. False when the field has none.
    #[cfg(feature = "bits")]
    pub(crate) fn write_sentinel(p: &Pack, f: &FieldDef, start: u64, len: u32, msg: &mut [u8]) -> bool {
        match f.sentinel() {
            Some(Sentinel::Num(n)) if len <= 64 => {
                let mask = if len >= 64 { u64::MAX } else { (1u64 << len) - 1 };
                let mut v = n & mask;
                if f.swap {
                    v = swap_bytes(v, len);
                }
                set_bits(msg, start, len, v, p.order);
                true
            }
            _ => false,
        }
    }

    /// Does a gate block hold on `raw`, its locator from bit `base`? A gate
    /// any of whose bits lies beyond `raw` does not, in either form
    /// (engine-spec v0.17).
    #[cfg(feature = "bits")]
    fn gate_holds(p: &Pack, g: &GateDef, raw: &[u8], total: u64, base: u64) -> bool {
        match span(p, &g.locator) {
            // `total`: the bits of the input, which six-bit armor does not
            // round to a byte (engine-spec v0.14)
            Ok((off, len)) if base + off + len as u64 > total => false,
            Ok((off, len)) => match get_bits(raw, base + off, len, p.order) {
                Some(v) => g.values.contains(&v) != g.negate,
                None => false,
            },
            Err(_) => false,
        }
    }

    /// Which gate blocks of a scope hold on `raw`: a nested block only when
    /// the block enclosing it holds. A parent comes before its children in
    /// the table.
    #[cfg(feature = "bits")]
    fn held_on(p: &Pack, gates: &[GateDef], raw: &[u8], total: u64, base: u64) -> Vec<bool> {
        let mut held = vec![false; gates.len()];
        for (i, g) in gates.iter().enumerate() {
            held[i] = g.parent.map_or(true, |q| held[q]) && gate_holds(p, g, raw, total, base);
        }
        held
    }

    /// The lines of a scope outside any gate block and those of the blocks
    /// that hold.
    #[cfg(feature = "bits")]
    fn only_held<'a>(sel: &Sel<'a>, held: &[bool]) -> Sel<'a> {
        let ok = |g: Option<usize>| g.map_or(true, |i| held[i]);
        Sel {
            kind: sel.kind,
            fields: sel.fields.iter().copied().filter(|f| ok(f.gate)).collect(),
            whens: sel.whens.clone(),
            consts: sel.consts.iter().copied().filter(|c| ok(c.gate)).collect(),
            defaults: sel.defaults.iter().copied().filter(|d| ok(d.gate)).collect(),
            groups: sel.groups.clone(),
            root: sel.root,
            gates: sel.gates,
            elements: sel.elements.clone(),
        }
    }

    /// The gate blocks encode chooses for one scope (engine-spec v0.17, steps
    /// 1 to 4): which hold, and the gate value step 3 gave each block.
    #[cfg(feature = "bits")]
    struct GatePlan {
        held: Vec<bool>,
        values: Vec<Option<u64>>,
    }

    /// Ruling 3 of 0.20: a `when` with a list or a range leaves the bits of a
    /// field line with a present key that covers exactly its bits, when the
    /// value written there matches it.
    #[cfg(feature = "bits")]
    fn keeps_field(p: &Pack, sel: &Sel, ent: &Entity, w: &WhenDef, msg: &[u8], base: u64) -> Result<bool, Error> {
        if !w.several() {
            return Ok(false);
        }
        let (off, len) = span(p, &w.locator)?;
        for f in sel.fields.iter().filter(|f| has_key(ent, f)) {
            if span(p, &f.locator)? == (off, len) {
                return Ok(get_bits(msg, base + off, len, p.order).map_or(false, |v| w.holds_num(v)));
            }
        }
        Ok(false)
    }

    #[cfg(feature = "bits")]
    fn plan_gates(p: &Pack, sel: &Sel, ent: &Entity) -> Result<GatePlan, Error> {
        let gates = sel.gates;
        if gates.is_empty() {
            return Ok(GatePlan { held: Vec::new(), values: Vec::new() });
        }
        // step 1: a block is open when one of its fields, or a nested open
        // block, maps a key the entity holds
        let mut open = vec![false; gates.len()];
        for f in &sel.fields {
            if f.gate.is_some() && has_key(ent, f) {
                let mut at = f.gate;
                while let Some(i) = at {
                    open[i] = true;
                    at = gates[i].parent;
                }
            }
        }
        // the bits of the scope, from its first bit; bits not written read as 0
        let counts = sel.groups.iter().filter_map(|g| match &g.count {
            Some(Count::Locator(l)) => Some((l, g)),
            _ => None,
        });
        let mut end = 0u64;
        let locators = sel
            .fields
            .iter()
            .map(|f| &f.locator)
            .chain(sel.fixed().map(|w| &w.locator))
            .chain(gates.iter().map(|g| &g.locator))
            .chain(counts.clone().map(|(l, _)| l));
        for loc in locators {
            let (off, len) = span(p, loc)?;
            end = end.max(off + len as u64);
        }
        let mut work = vec![0u8; ((end + 7) / 8) as usize];
        let mut written = vec![false; end as usize];
        let mark = |written: &mut Vec<bool>, off: u64, len: u32| {
            for b in &mut written[off as usize..(off + len as u64) as usize] {
                *b = true;
            }
        };
        let low = |n: u64, len: u32| if len >= 64 { n } else { n & ((1u64 << len) - 1) };
        // step 2: the 0.5 encode of the lines outside any block. A present
        // key, a `const`, a `when` and a count make their bits written; the
        // bits of a default or a sentinel are kept for step 4 (where no gate
        // value replaces them) but are not written. Sentinels first, then
        // later lines first: the earlier line's value stays.
        let outside = || sel.fields.iter().rev().filter(|f| f.gate.is_none());
        for f in outside().filter(|f| live(ent, f) && sel.value_of(ent, f).is_none()) {
            let (off, len) = span(p, &f.locator)?;
            write_sentinel(p, f, off, len, &mut work);
        }
        for f in outside() {
            if let Some(v) = sel.value_of(ent, f) {
                let (off, len) = span(p, &f.locator)?;
                // a value that does not encode fails in step 5
                if let Ok(w) = p.to_wire(f, v) {
                    let _ = write_field(p, f, &w, off, len, &mut work);
                }
                if has_key(ent, f) {
                    mark(&mut written, off, len);
                }
            }
        }
        for w in sel.consts.iter().filter(|c| c.gate.is_none()).chain(sel.whens.iter().filter(|w| !w.present)) {
            let (off, len) = span(p, &w.locator)?;
            if !keeps_field(p, sel, ent, w, &work, 0)? {
                set_bits(&mut work, off, len, w.num, p.order);
            }
            mark(&mut written, off, len);
        }
        for (l, g) in counts {
            let (off, len) = span(p, l)?;
            let n = ent.lists.get(&g.list).map_or(0, |items| items.len() as u64);
            set_bits(&mut work, off, len, low(n, len), p.order);
            mark(&mut written, off, len);
        }
        // step 3: in line order, outer blocks first, each open block none of
        // whose gate bits is written gets its gate value
        let mut values: Vec<Option<u64>> = vec![None; gates.len()];
        for (i, g) in gates.iter().enumerate() {
            if !open[i] {
                continue;
            }
            let (off, len) = span(p, &g.locator)?;
            if written[off as usize..(off + len as u64) as usize].iter().any(|b| *b) {
                continue;
            }
            let fits = |v: u64| len >= 64 || v >> len == 0;
            let v = if g.negate {
                // the smallest value not listed; none when the list names every value
                (0..=g.values.len() as u64).find(|v| fits(*v) && !g.values.contains(v))
            } else {
                g.values.first().copied()
            };
            if let Some(v) = v {
                set_bits(&mut work, off, len, v, p.order);
                mark(&mut written, off, len);
                values[i] = Some(v);
            }
        }
        // step 4: each block evaluated on the bits of step 3 together with
        // those of an outside default or sentinel no gate value replaced
        let held = held_on(p, gates, &work, work.len() as u64 * 8, 0);
        Ok(GatePlan { held, values })
    }

    /// The furthest bit of a scope's held gate locators (the length paragraph of 0.17).
    #[cfg(feature = "bits")]
    fn held_gates_end(p: &Pack, sel: &Sel, held: &[bool]) -> Result<u64, Error> {
        let mut end = 0u64;
        for (g, h) in sel.gates.iter().zip(held) {
            if *h {
                let (off, len) = span(p, &g.locator)?;
                end = end.max(off + len as u64);
            }
        }
        Ok(end)
    }

    #[cfg(feature = "bits")]
    fn short(p: &Pack, what: impl AsRef<str>) -> Error {
        Error { msg: format!("malformed-wire: format `{}`: {}", p.format, what.as_ref()) }
    }

    /// Decode the fields and groups of one scope: the message (`base` 0), or
    /// one item, whose first bit is `base`. `reach` is the furthest bit the
    /// message must hold; `total` the bits of the input.
    #[cfg(feature = "bits")]
    fn decode_scope(
        p: &Pack,
        sel: &Sel,
        raw: &[u8],
        total: u64,
        base: u64,
        d: &mut Decoded,
        reach: &mut u64,
    ) -> Result<u64, Error> {
        // where the items of this scope's groups end
        let mut groups_end = 0u64;
        for f in &sel.fields {
            let (off, len) = span(p, &f.locator)?;
            let start = base + off;
            if start + len as u64 > total {
                // an `optional` field beyond the input is absent
                if f.optional {
                    continue;
                }
                return Err(short(p, format!("the input ends before `{}` at `{}`", f.model_key, f.locator)));
            }
            if !f.optional {
                *reach = (*reach).max(start + len as u64);
            }
            // a sentinel: the line yields no value (engine-spec v0.9)
            if is_sentinel(p, f, raw, start, len) {
                continue;
            }
            d.put(p, f, read_field(p, f, raw, start, len));
        }
        // a group is always present, with `count` items
        for g in &sel.groups {
            let n = match &g.count {
                Some(Count::Fixed(n)) => *n,
                Some(Count::Locator(l)) => {
                    let (off, len) = span(p, l)?;
                    *reach = (*reach).max(base + off + len as u64);
                    get_bits(raw, base + off, len, p.order)
                        .filter(|_| base + off + len as u64 <= total)
                        .ok_or_else(|| short(p, format!("the input ends before the count of list `{}`", g.list)))?
                }
                None => 0,
            };
            // the count against what the limit still allows, before any item is read (7d)
            d.replacing(&g.list);
            limit::take(&p.format, &g.list, n)?;
            let (off, item_bits) = group_span(p, g)?;
            let start = base + off;
            let end = n.checked_mul(item_bits).and_then(|b| b.checked_add(start)).filter(|e| *e <= total).ok_or_else(|| {
                short(p, format!("list `{}` has {} items of {} bits, more than the input holds", g.list, n, item_bits))
            })?;
            *reach = (*reach).max(end);
            let body = g.body();
            let mut items = Vec::new();
            // an item is `item <bits>` long, or ends where a nested group
            // counted by a locator ends, when that is further (ruling 4 of 0.7)
            let mut at = start;
            for _ in 0..n {
                if at + item_bits > total {
                    return Err(short(p, format!("the input ends inside an item of list `{}`", g.list)));
                }
                let mut di = Decoded::new();
                // the gate blocks of the item, evaluated per item (ruling 2 of 0.17)
                let item = only_held(&body, &held_on(p, &g.gates, raw, total, at));
                let nested_end = decode_scope(p, &item, raw, total, at, &mut di, reach)?;
                at = (at + item_bits).max(nested_end);
                items.push(di);
            }
            *reach = (*reach).max(at);
            groups_end = groups_end.max(at);
            d.put_list(&g.list, items);
        }
        Ok(groups_end)
    }

    #[cfg(feature = "bits")]
    pub fn decode(p: &Pack, hex: &str) -> Result<Entity, Error> {
        let _scope = limit::scope();
        // the message and its length in bits: hex, or six-bit armor (engine-spec v0.14)
        let sixbit = p.armor == armor::Armor::Sixbit;
        let (raw, total) = if sixbit {
            armor::read(p, hex)?
        } else {
            let raw = from_hex(hex)?;
            let total = raw.len() as u64 * 8;
            (raw, total)
        };
        if let Some(body) = &p.seq {
            return super::seq::decode(p, body, &raw, total);
        }
        // a `when` whose bits lie beyond the input does not hold
        let sel = p.select_decode(None, |w| match span(p, &w.locator) {
            Ok((start, len)) => start + len as u64 <= total && get_bits(&raw, start, len, p.order).map_or(false, |v| w.holds_num(v)),
            Err(_) => false,
        })?;
        // the lines of the gate blocks that hold (engine-spec v0.17)
        let sel = only_held(&sel, &held_on(p, sel.gates, &raw, total, 0));
        if sixbit {
            // every bit of the lines in force, not whole words (engine-spec v0.14)
            let need = message_end(p, &sel, false)?;
            if total < need {
                return Err(short(p, format!("input is {} bits, need {}", total, need)));
            }
            let mut d = Decoded::new();
            decode_scope(p, &sel, &raw, total, 0, &mut d, &mut 0)?;
            return d.finish(p, &sel);
        }
        let words = |need: usize| {
            format!("input is {} bytes, need {} ({} words of {})", raw.len(), need, need / p.word_bytes, p.word_bytes)
        };
        let need = message_bytes(p, &sel, false)?;
        if raw.len() < need {
            return Err(short(p, words(need)));
        }
        let mut d = Decoded::new();
        let mut reach = 0u64;
        decode_scope(p, &sel, &raw, total, 0, &mut d, &mut reach)?;
        // whole words up to the furthest bit, the items of every group included
        let word_bits = p.word_bytes as u64 * 8;
        let need = ((reach + word_bits - 1) / word_bits) as usize * p.word_bytes;
        if raw.len() < need {
            return Err(short(p, words(need)));
        }
        d.finish(p, &sel)
    }

    /// The bits one item takes on encode: `item <bits>`, or up to the end of a
    /// nested group counted by a locator, when that is further.
    #[cfg(feature = "bits")]
    fn item_len(p: &Pack, g: &GroupDef, item: &Entity) -> Result<u64, Error> {
        let item_bits = g.item_bits.unwrap_or(1);
        Ok(item_bits.max(group_reach(p, &g.body(), item, 0)?))
    }

    /// The furthest bit the groups of a scope write: each count locator, and
    /// the items of each list the entity has.
    #[cfg(feature = "bits")]
    pub(crate) fn group_reach(p: &Pack, sel: &Sel, ent: &Entity, base: u64) -> Result<u64, Error> {
        let mut end = 0u64;
        for g in &sel.groups {
            if let Some(Count::Locator(l)) = &g.count {
                let (off, len) = span(p, l)?;
                end = end.max(base + off + len as u64);
            }
            if let Some(items) = ent.lists.get(&g.list) {
                let (off, _) = group_span(p, g)?;
                let mut at = base + off;
                for item in items {
                    at += item_len(p, g, item)?;
                }
                end = end.max(at);
            }
        }
        Ok(end)
    }

    /// Write the lines of one scope: the message (`base` 0), or one item,
    /// whose first bit is `base`.
    /// A choice of gate blocks step 6 checks on the final output: the
    /// scope's gate table, its first bit, and the blocks held on encode.
    #[cfg(feature = "bits")]
    type GateCheck<'p> = (&'p [GateDef], u64, Vec<bool>);

    #[cfg(feature = "bits")]
    fn write_scope<'p>(
        p: &Pack,
        all: &Sel<'p>,
        ent: &Entity,
        base: u64,
        msg: &mut [u8],
        checks: &mut Vec<GateCheck<'p>>,
    ) -> Result<(), Error> {
        // the gate blocks that hold (engine-spec v0.17): the lines written are
        // those outside any block and those of the held blocks
        let plan = plan_gates(p, all, ent)?;
        let sel = &only_held(all, &plan.held);
        // an absent key whose field has `absent` writes its first sentinel,
        // first: a line with a value wins over it whatever their order (ruling
        // 16 of 0.9); of two sentinels the earlier line's stays
        for f in sel.fields.iter().rev().filter(|f| live(ent, f) && sel.value_of(ent, f).is_none()) {
            let (off, len) = span(p, &f.locator)?;
            write_sentinel(p, f, base + off, len, msg);
        }
        // later lines first: where two fields cover the same bits the earlier
        // line's value is the one left on the wire (ruling 5 of 0.5)
        for f in sel.fields.iter().rev() {
            let v = match sel.value_of(ent, f) {
                Some(v) => p.to_wire(f, v).map_err(|e| transform_encode_err(p, f, e))?,
                None => continue,
            };
            let (off, len) = span(p, &f.locator)?;
            let start = base + off;
            write_field(p, f, &v, start, len, msg)?;
        }
        // the gate value of each held block: over the bits of a default or a
        // sentinel, under those of a line with a present key (step 5 of 0.17)
        if plan.values.iter().any(|v| v.is_some()) {
            let mut present: Vec<(u64, u64)> = Vec::new();
            for f in sel.fields.iter().filter(|f| has_key(ent, f)) {
                let (off, len) = span(p, &f.locator)?;
                present.push((off, off + len as u64));
            }
            for (i, g) in all.gates.iter().enumerate() {
                let v = match plan.values[i] {
                    Some(v) if plan.held[i] => v,
                    _ => continue,
                };
                let (off, len) = span(p, &g.locator)?;
                for k in 0..len {
                    let at = off + k as u64;
                    if present.iter().any(|(a, b)| *a <= at && at < *b) {
                        continue;
                    }
                    // bit k of the field: the k-th from the low end (lsb) or the high end (msb)
                    let bit = if p.order == BitOrder::Msb { (v >> (len - 1 - k)) & 1 } else { (v >> k) & 1 };
                    set_bits(msg, base + at, 1, bit, p.order);
                }
            }
        }
        // the items of each list the entity has, back to back
        let mut counts: Vec<(&String, u64, &GroupDef)> = Vec::new();
        for g in &sel.groups {
            let fail = |m: String| Error { msg: format!("transform-encode: format `{}`: list `{}`: {}", p.format, g.list, m) };
            let items = match (ent.lists.get(&g.list), &g.count) {
                (Some(items), _) => items,
                // an absent list under a fixed count (ruling 5 of 0.7)
                (None, Some(Count::Fixed(want))) => {
                    return Err(fail(format!("the list is absent, the group holds exactly {} items", want)));
                }
                // an absent list under a count locator writes a count of 0 (ruling 14 of 0.7)
                (None, Some(Count::Locator(l))) => {
                    counts.push((l, 0, g));
                    continue;
                }
                (None, None) => continue,
            };
            let n = items.len() as u64;
            let (off, _) = group_span(p, g)?;
            let body = g.body();
            let mut at = base + off;
            for item in items {
                write_scope(p, &body, item, at, msg, checks)?;
                at += item_len(p, g, item)?;
            }
            match &g.count {
                Some(Count::Fixed(want)) if *want != n => {
                    return Err(fail(format!("{} items, the group holds exactly {}", n, want)));
                }
                Some(Count::Locator(l)) => counts.push((l, n, g)),
                _ => {}
            }
        }
        // over the same bits: fields, then `const`, then `when`, then counts (ruling 15 of 0.7)
        for w in sel.consts.iter().chain(sel.whens.iter().filter(|w| !w.present)) {
            let (off, len) = span(p, &w.locator)?;
            if !keeps_field(p, sel, ent, w, msg, base)? {
                set_bits(msg, base + off, len, w.num, p.order);
            }
        }
        for (l, n, g) in counts {
            let (coff, len) = span(p, l)?;
            if len < 64 && n >> len != 0 {
                return Err(Error {
                    msg: format!(
                        "transform-encode: format `{}`: list `{}`: {} items do not fit the {}-bit count",
                        p.format, g.list, n, len
                    ),
                });
            }
            set_bits(msg, base + coff, len, n, p.order);
        }
        // step 6 of 0.17: every key the entity holds is written by a line in
        // force, and the output decodes to the same choice of blocks
        if !all.gates.is_empty() {
            let fail = |m: String| Error { msg: format!("transform-encode: format `{}`: {}", p.format, m) };
            // a line suppressed by `with` does not count as mapped (ruling 1 of 0.18)
            for f in all.fields.iter().filter(|f| f.gate.is_some() && has_key(ent, f)) {
                if !sel.fields.iter().any(|h| h.model_key == f.model_key && live(ent, h)) {
                    return Err(fail(format!(
                        "`{}` is mapped only by lines of gate blocks that do not hold",
                        f.model_key
                    )));
                }
            }
            // the choice is checked once the whole output is written (ruling 9 of 0.17)
            checks.push((all.gates, base, plan.held));
        }
        Ok(())
    }

    /// Step 6 of 0.17 on the final output: every scope and item decodes to
    /// the blocks encode chose.
    #[cfg(feature = "bits")]
    fn check_gates(p: &Pack, msg: &[u8], total: u64, checks: &[GateCheck]) -> Result<(), Error> {
        for (gates, base, held) in checks {
            let out = held_on(p, gates, msg, total, *base);
            if let Some(i) = (0..out.len()).find(|i| out[*i] != held[*i]) {
                let g = &gates[i];
                return err(format!(
                    "transform-encode: format `{}`: the gate block of line {} (`{}`) {} on the output and {} on encode",
                    p.format,
                    g.line,
                    g.locator,
                    if out[i] { "holds" } else { "does not hold" },
                    if held[i] { "held" } else { "did not hold" }
                ));
            }
        }
        Ok(())
    }

    #[cfg(feature = "bits")]
    pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
        let sixbit = p.armor == armor::Armor::Sixbit;
        if let Some(body) = &p.seq {
            // six-bit armor: the cursor after the last line, not rounded (engine-spec v0.14)
            let (b, cursor) = super::seq::encode_bits(p, body, ent)?;
            return Ok(if sixbit { armor::write(&b, cursor) } else { to_hex(&b) });
        }
        let sel = p.select_encode(ent)?;
        // whole words up to the furthest bit: the lines in force, extended by the items
        let word_bits = p.word_bytes as u64 * 8;
        let items = ((group_reach(p, &sel, ent, 0)? + word_bits - 1) / word_bits) as usize * p.word_bytes;
        // the lines in force and the gate locators of the held blocks (engine-spec v0.17)
        let held = plan_gates(p, &sel, ent)?.held;
        let gates_end = held_gates_end(p, &sel, &held)?;
        let gates = ((gates_end + word_bits - 1) / word_bits) as usize * p.word_bytes;
        let lines = message_bytes(p, &only_held(&sel, &held), true)?;
        let mut msg: Vec<u8> = vec![0u8; lines.max(items).max(gates)];
        let mut checks = Vec::new();
        write_scope(p, &sel, ent, 0, &mut msg, &mut checks)?;
        if sixbit {
            // L: the lines outside any block, the held blocks' lines and their
            // gate locators (engine-spec v0.14, v0.17); the output decodes
            // from L bits rounded up to a character
            let len = armor::fixed_len(p, &only_held(&sel, &held), ent)?.max(gates_end);
            let bits = (len + 5) / 6 * 6;
            let mut out = msg.clone();
            out.resize(((bits + 7) / 8) as usize, 0);
            check_gates(p, &out, bits, &checks)?;
            return Ok(armor::write(&msg, len));
        }
        check_gates(p, &msg, msg.len() as u64 * 8, &checks)?;
        Ok(to_hex(&msg))
    }

    /// Hex text to bytes: whitespace ignored, an even number of hex digits.
    /// Anything else is `malformed-wire`.
    #[cfg(any(feature = "bits", feature = "protobuf", feature = "tlv"))]
    pub fn from_hex(s: &str) -> Result<Vec<u8>, Error> {
        let nibble = |c: u8| match c {
            b'0'..=b'9' => Some(c - b'0'),
            b'a'..=b'f' => Some(c - b'a' + 10),
            b'A'..=b'F' => Some(c - b'A' + 10),
            _ => None,
        };
        let mut out = Vec::with_capacity(s.len() / 2);
        // the high digit of the byte being read
        let mut high: Option<u8> = None;
        for (at, c) in s.bytes().enumerate() {
            // whitespace in hex text: space, tab, line feed, carriage return only
            if matches!(c, b' ' | b'\t' | b'\n' | b'\r') {
                continue;
            }
            // every character a hex digit: `from_str_radix` would take a sign
            let n = match nibble(c) {
                Some(n) => n,
                None => return err(format!("malformed-wire: hex input holds a character that is not a hex digit (byte {})", at)),
            };
            match high.take() {
                Some(h) => out.push(h << 4 | n),
                None => high = Some(n),
            }
        }
        if high.is_some() {
            return err("malformed-wire: hex input has an odd number of digits");
        }
        Ok(out)
    }

    #[cfg(any(feature = "bits", feature = "protobuf", feature = "tlv"))]
    pub fn to_hex(b: &[u8]) -> String {
        let mut s = String::with_capacity(b.len() * 2);
        for byte in b {
            s.push_str(&format!("{:02x}", byte));
        }
        s
    }
}

pub mod armor;
pub mod seq;
pub mod text;
pub mod tlv;
pub mod uper;

// ---------------------------------------------------------------------------
// protobuf codec: fields by number, dot-path for nested messages. I/O as hex.
// ---------------------------------------------------------------------------

pub mod protobuf {
    use super::*;
    #[cfg(feature = "protobuf")]
    use std::collections::BTreeMap;

    #[derive(Clone, Debug, PartialEq)]
    #[cfg(feature = "protobuf")]
    pub enum WireVal {
        Varint(u64),
        Fixed64(u64),
        LenDelim(Vec<u8>),
        Fixed32(u32),
    }
    #[cfg(feature = "protobuf")]
    impl WireVal {
        #[cfg(feature = "protobuf")]
        fn wire_type(&self) -> u8 {
            match self {
                WireVal::Varint(_) => 0,
                WireVal::Fixed64(_) => 1,
                WireVal::LenDelim(_) => 2,
                WireVal::Fixed32(_) => 5,
            }
        }
        #[cfg(feature = "protobuf")]
        fn write(&self, out: &mut Vec<u8>) {
            match self {
                WireVal::Varint(u) => put_varint(*u, out),
                WireVal::Fixed64(u) => out.extend_from_slice(&u.to_le_bytes()),
                WireVal::LenDelim(b) => {
                    put_varint(b.len() as u64, out);
                    out.extend_from_slice(b);
                }
                WireVal::Fixed32(u) => out.extend_from_slice(&u.to_le_bytes()),
            }
        }
    }

    #[cfg(feature = "protobuf")]
    fn put_varint(mut v: u64, out: &mut Vec<u8>) {
        loop {
            let b = (v & 0x7f) as u8;
            v >>= 7;
            if v != 0 {
                out.push(b | 0x80);
            } else {
                out.push(b);
                break;
            }
        }
    }
    /// The largest protobuf field number; the smallest is 1.
    #[cfg(feature = "protobuf")]
    const MAX_FIELD: u64 = (1 << 29) - 1;

    #[cfg(feature = "protobuf")]
    fn get_varint(b: &[u8], i: &mut usize) -> Result<u64, Error> {
        let mut v: u64 = 0;
        let mut shift = 0;
        loop {
            if *i >= b.len() {
                return err("malformed-wire: protobuf: truncated varint");
            }
            let byte = b[*i];
            *i += 1;
            // the tenth byte holds bit 63 only
            if shift == 63 && byte > 1 {
                return err("malformed-wire: protobuf: a ten-byte varint holds bits above bit 63");
            }
            v |= ((byte & 0x7f) as u64) << shift;
            if byte & 0x80 == 0 {
                return Ok(v);
            }
            shift += 7;
            if shift >= 64 {
                return err("malformed-wire: protobuf: varint longer than ten bytes");
            }
        }
    }

    /// parse one message into (field number, value) pairs, in wire order.
    #[cfg(feature = "protobuf")]
    fn parse_msg(b: &[u8]) -> Result<Vec<(u32, WireVal)>, Error> {
        let mut out = Vec::new();
        let mut i = 0;
        while i < b.len() {
            let tag = get_varint(b, &mut i)?;
            // a field number is at most 2^29 - 1; a larger one must not wrap onto a mapped field
            if tag >> 3 == 0 || tag >> 3 > MAX_FIELD {
                return err(format!("malformed-wire: protobuf: field number {} is out of range", tag >> 3));
            }
            let field = (tag >> 3) as u32;
            let wt = (tag & 7) as u8;
            // `i <= b.len()` here, so `left` cannot underflow
            let left = b.len() - i;
            let v = match wt {
                0 => WireVal::Varint(get_varint(b, &mut i)?),
                1 => {
                    if left < 8 {
                        return err("malformed-wire: protobuf: truncated fixed64");
                    }
                    let mut a = [0u8; 8];
                    a.copy_from_slice(&b[i..i + 8]);
                    i += 8;
                    WireVal::Fixed64(u64::from_le_bytes(a))
                }
                2 => {
                    // compared as u64 against the bytes left: no addition to overflow
                    let len = get_varint(b, &mut i)?;
                    if len > (b.len() - i) as u64 {
                        return err(format!(
                            "malformed-wire: protobuf: a length-delimited field states {} bytes, {} are left",
                            len,
                            b.len() - i
                        ));
                    }
                    let len = len as usize;
                    let s = b[i..i + len].to_vec();
                    i += len;
                    WireVal::LenDelim(s)
                }
                5 => {
                    if left < 4 {
                        return err("malformed-wire: protobuf: truncated fixed32");
                    }
                    let mut a = [0u8; 4];
                    a.copy_from_slice(&b[i..i + 4]);
                    i += 4;
                    WireVal::Fixed32(u32::from_le_bytes(a))
                }
                other => return err(format!("malformed-wire: protobuf: wire type {} unsupported", other)),
            };
            out.push((field, v));
        }
        Ok(out)
    }

    pub(crate) fn parse_path(locator: &str) -> Result<Vec<u32>, Error> {
        locator
            .split('.')
            .map(|s| {
                Some(s)
                    .filter(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()))
                    .and_then(|s| s.parse::<u32>().ok())
                    .ok_or(Error { msg: format!("bad protobuf path `{}`", locator) })
            })
            .collect()
    }

    /// One message and the submessages the pack's paths walk into, each
    /// parsed once: the cost of a decode is the size of the input, not the
    /// size of the input times the number of lines in the pack.
    #[cfg(feature = "protobuf")]
    struct Parsed {
        root: Vec<(u32, WireVal)>,
        /// the submessage at each path walked so far (last occurrence of each step)
        subs: BTreeMap<Vec<u32>, Vec<(u32, WireVal)>>,
    }
    #[cfg(feature = "protobuf")]
    impl Parsed {
        #[cfg(feature = "protobuf")]
        fn new(b: &[u8]) -> Result<Parsed, Error> {
            Ok(Parsed { root: parse_msg(b)?, subs: BTreeMap::new() })
        }
        /// The fields of the submessage at `prefix` (the message itself for
        /// an empty prefix); None when a step does not occur. A step that is
        /// not a submessage is `malformed-wire` (ruling 13 of 0.7).
        #[cfg(feature = "protobuf")]
        fn fields_at(&mut self, prefix: &[u32]) -> Result<Option<&[(u32, WireVal)]>, Error> {
            for k in 0..prefix.len() {
                if self.subs.contains_key(&prefix[..=k]) {
                    continue;
                }
                let holder = if k == 0 { &self.root } else { &self.subs[&prefix[..k]] };
                let parsed = match holder.iter().rev().find(|(f, _)| *f == prefix[k]).map(|(_, v)| v) {
                    None => return Ok(None),
                    Some(WireVal::LenDelim(sub)) => parse_msg(sub)?,
                    Some(_) => {
                        return err(format!("malformed-wire: protobuf: path field {} is not a submessage", prefix[k]))
                    }
                };
                self.subs.insert(prefix[..=k].to_vec(), parsed);
            }
            Ok(Some(if prefix.is_empty() { &self.root } else { &self.subs[prefix] }))
        }
        /// The leaf field value at a dot-path (last occurrence wins per field).
        #[cfg(feature = "protobuf")]
        fn resolve(&mut self, path: &[u32]) -> Result<Option<WireVal>, Error> {
            let (last, before) = match path.split_last() {
                Some(split) => split,
                None => return Ok(None),
            };
            Ok(self.fields_at(before)?.and_then(|fields| fields.iter().rev().find(|(f, _)| f == last).map(|(_, v)| v.clone())))
        }
    }

    /// Does a leaf value hold one of the field's sentinels? A value whose wire
    /// type is not the one the transform fixes holds none: it is
    /// `transform-decode` (ruling 15 of 0.9).
    #[cfg(feature = "protobuf")]
    fn is_sentinel(f: &FieldDef, v: &WireVal) -> bool {
        if f.absent.is_empty() {
            return false;
        }
        match (&f.transform, v) {
            (Transform::Pvarint | Transform::Psint, WireVal::Varint(u)) | (Transform::Pdouble, WireVal::Fixed64(u)) => {
                f.absent_num(*u)
            }
            (Transform::Pfloat, WireVal::Fixed32(u)) => f.absent_num(*u as u64),
            (Transform::Pstring, WireVal::LenDelim(b)) => std::str::from_utf8(b).map_or(false, |t| f.absent_text(t)),
            _ => false,
        }
    }

    /// Is a leaf value the proto3 default of its wire type (engine-spec
    /// v0.56): varint 0, +0.0 (all bits zero), the empty text?
    #[cfg(feature = "protobuf")]
    fn is_proto3_default(v: &WireVal) -> bool {
        match v {
            WireVal::Varint(0) | WireVal::Fixed64(0) | WireVal::Fixed32(0) => true,
            WireVal::LenDelim(b) => b.is_empty(),
            _ => false,
        }
    }

    /// The leaf value a sentinel is written as: no zig-zag on `psint`.
    #[cfg(feature = "protobuf")]
    fn sentinel_wire(f: &FieldDef, s: &Sentinel) -> Result<WireVal, Error> {
        match (&f.transform, s) {
            (Transform::Pvarint | Transform::Psint, Sentinel::Num(n)) => Ok(WireVal::Varint(*n)),
            (Transform::Pdouble, Sentinel::Num(n)) => Ok(WireVal::Fixed64(*n)),
            (Transform::Pfloat, Sentinel::Num(n)) => Ok(WireVal::Fixed32(*n as u32)),
            (Transform::Pstring, Sentinel::Text(t, _)) => Ok(WireVal::LenDelim(t.clone().into_bytes())),
            _ => err(format!("transform-encode: protobuf: `{}` has no sentinel its transform writes", f.model_key)),
        }
    }

    pub(crate) fn numeric(t: &Transform) -> bool {
        matches!(t, Transform::Pvarint | Transform::Psint | Transform::Pdouble | Transform::Pfloat)
    }

    /// The values of a packed repeated field: one length-delimited occurrence
    /// holding the values back to back.
    #[cfg(feature = "protobuf")]
    fn unpack(t: &Transform, b: &[u8]) -> Result<Vec<WireVal>, Error> {
        let mut out = Vec::new();
        match t {
            Transform::Pdouble => {
                if b.len() % 8 != 0 {
                    return err("malformed-wire: protobuf: a packed fixed64 field is not a multiple of 8 bytes");
                }
                for c in b.chunks(8) {
                    let mut a = [0u8; 8];
                    a.copy_from_slice(c);
                    out.push(WireVal::Fixed64(u64::from_le_bytes(a)));
                }
            }
            Transform::Pfloat => {
                if b.len() % 4 != 0 {
                    return err("malformed-wire: protobuf: a packed fixed32 field is not a multiple of 4 bytes");
                }
                for c in b.chunks(4) {
                    let mut a = [0u8; 4];
                    a.copy_from_slice(c);
                    out.push(WireVal::Fixed32(u32::from_le_bytes(a)));
                }
            }
            _ => {
                let mut i = 0;
                while i < b.len() {
                    let v = get_varint(b, &mut i).map_err(|e| Error { msg: format!("{} in a packed field", e.msg) })?;
                    out.push(WireVal::Varint(v));
                }
            }
        }
        Ok(out)
    }

    /// Decode the fields and groups of one scope: the message, or one item
    /// read as a submessage.
    #[cfg(feature = "protobuf")]
    fn decode_scope(p: &Pack, sel: &Sel, msg: &mut Parsed, d: &mut Decoded) -> Result<(), Error> {
        for f in sel.fields.iter().filter(|f| f.locator != ".") {
            let path = parse_path(&f.locator)?;
            if let Some(wv) = msg.resolve(&path)? {
                // a sentinel: the line yields no value (engine-spec v0.9)
                if !is_sentinel(f, &wv) {
                    d.put(p, f, f.transform.decode_pb(&wv));
                }
            }
        }
        for g in &sel.groups {
            let path = parse_path(&g.locator)?;
            let (last, before) = path.split_last().ok_or(Error { msg: "empty protobuf path".into() })?;
            // the message that holds the items: the last occurrence of each step
            let holder = match msg.fields_at(before)? {
                Some(fields) => fields,
                None => continue,
            };
            let body = g.body();
            // a `.` line with a numeric transform: an occurrence may be packed
            let packed = g.scalar().map(|f| &f.transform).filter(|t| numeric(t));
            let mut occurrences: Vec<WireVal> = Vec::new();
            for (field, v) in holder {
                if field != last {
                    continue;
                }
                match (v, packed) {
                    (WireVal::LenDelim(bytes), Some(t)) => occurrences.extend(unpack(t, bytes)?),
                    _ => occurrences.push(v.clone()),
                }
            }
            // the list is present when at least one item occurs
            if occurrences.is_empty() {
                continue;
            }
            let into = body.fields.iter().any(|f| f.locator != ".") || !body.groups.is_empty();
            d.replacing(&g.list);
            let mut items = Vec::new();
            for v in &occurrences {
                limit::take(&p.format, &g.list, 1)?;
                let mut di = Decoded::new();
                // `.`: the occurrence itself as a scalar
                for f in body.fields.iter().filter(|f| f.locator == ".") {
                    if !is_sentinel(f, v) {
                        di.put(p, f, f.transform.decode_pb(v));
                    }
                }
                match v {
                    WireVal::LenDelim(sub) if into => decode_scope(p, &body, &mut Parsed::new(sub)?, &mut di)?,
                    _ if into && g.scalar().is_none() => {
                        return err(format!(
                            "malformed-wire: format `{}`: an item of list `{}` is not a submessage",
                            p.format, g.list
                        ))
                    }
                    _ => {}
                }
                items.push(di);
            }
            d.put_list(&g.list, items);
        }
        Ok(())
    }

    #[cfg(feature = "protobuf")]
    pub fn decode(p: &Pack, hex: &str) -> Result<Entity, Error> {
        let _scope = limit::scope();
        let raw = super::bits::from_hex(hex)?;
        // a malformed message is an error, not a kind mismatch, and is one
        // whether or not a line of the pack reads it
        let msg = std::cell::RefCell::new(Parsed::new(&raw)?);
        let sel = p.select_decode(None, |w| {
            let found = parse_path(&w.locator).and_then(|path| msg.borrow_mut().resolve(&path));
            match found {
                Ok(Some(v)) => w.present || matches!(v, WireVal::Varint(x) if w.holds_num(x)),
                _ => false,
            }
        })?;
        let mut d = Decoded::new();
        decode_scope(p, &sel, &mut msg.into_inner(), &mut d)?;
        d.finish(p, &sel)
    }

    // build tree: a node is a leaf value, a submessage of ascending field
    // nodes, or the occurrences of a repeated field
    #[cfg(feature = "protobuf")]
    enum Node {
        Leaf(WireVal),
        Msg(BTreeMap<u32, Node>),
        Many(Vec<Node>),
    }
    #[cfg(feature = "protobuf")]
    fn insert(tree: &mut BTreeMap<u32, Node>, path: &[u32], v: WireVal) -> Result<(), Error> {
        insert_node(tree, path, Node::Leaf(v))
    }
    #[cfg(feature = "protobuf")]
    fn insert_node(tree: &mut BTreeMap<u32, Node>, path: &[u32], node: Node) -> Result<(), Error> {
        if path.len() == 1 {
            tree.insert(path[0], node);
            return Ok(());
        }
        let child = tree.entry(path[0]).or_insert_with(|| Node::Msg(BTreeMap::new()));
        match child {
            Node::Msg(m) => insert_node(m, &path[1..], node),
            _ => err(format!("transform-encode: protobuf: field {} is both a leaf and a submessage", path[0])),
        }
    }
    #[cfg(feature = "protobuf")]
    fn write_node(field: u32, node: &Node, out: &mut Vec<u8>) {
        match node {
            Node::Leaf(wv) => {
                put_varint(((field as u64) << 3) | wv.wire_type() as u64, out);
                wv.write(out);
            }
            Node::Msg(sub) => {
                let bytes = serialize(sub);
                put_varint(((field as u64) << 3) | 2, out);
                put_varint(bytes.len() as u64, out);
                out.extend_from_slice(&bytes);
            }
            Node::Many(nodes) => {
                for n in nodes {
                    write_node(field, n, out);
                }
            }
        }
    }
    #[cfg(feature = "protobuf")]
    fn serialize(tree: &BTreeMap<u32, Node>) -> Vec<u8> {
        let mut out = Vec::new();
        for (field, node) in tree {
            write_node(*field, node, &mut out);
        }
        out
    }

    /// The tree one scope writes: the message, or one submessage item.
    #[cfg(feature = "protobuf")]
    fn build(p: &Pack, sel: &Sel, ent: &Entity) -> Result<BTreeMap<u32, Node>, Error> {
        let mut tree: BTreeMap<u32, Node> = BTreeMap::new();
        // an absent key whose field has `absent` writes its first sentinel where
        // no line with a value writes (engine-spec v0.9): later lines first, so
        // of two sentinels on one path the earlier line's stays
        // `implicit` (engine-spec v0.56): a value equal to the proto3 default
        // is not written, but its line still holds the place (ruling 16 of 0.5)
        let mut places: Vec<(Vec<u32>, Option<WireVal>)> = Vec::new();
        fn place(places: &mut Vec<(Vec<u32>, Option<WireVal>)>, f: &FieldDef, path: Vec<u32>, wv: WireVal) {
            let wv = if f.implicit && is_proto3_default(&wv) { None } else { Some(wv) };
            match places.iter_mut().find(|(p, _)| *p == path) {
                Some(e) => e.1 = wv,
                None => places.push((path, wv)),
            }
        }
        for (f, s) in sentinel_lines(sel, ent, |f| f.locator == ".").into_iter().rev() {
            place(&mut places, f, parse_path(&f.locator)?, sentinel_wire(f, s)?);
        }
        // later lines first: of two fields on one path the earlier line's value stays
        for f in sel.fields.iter().rev().filter(|f| f.locator != ".") {
            if let Some(v) = sel.value_of(ent, f) {
                let path = parse_path(&f.locator)?;
                let wv = p
                    .to_wire(f, v)
                    .and_then(|w| f.transform.encode_pb(&w))
                    .map_err(|e| transform_encode_err(p, f, e))?;
                place(&mut places, f, path, wv);
            }
        }
        for (path, wv) in places {
            if let Some(wv) = wv {
                insert(&mut tree, &path, wv)?;
            }
        }
        // one occurrence per item; an absent or empty list writes nothing
        for g in sel.groups.iter().rev() {
            let items = match ent.lists.get(&g.list) {
                Some(items) if !items.is_empty() => items,
                _ => continue,
            };
            let body = g.body();
            let mut nodes: Vec<Node> = Vec::new();
            let mut packed: Vec<u8> = Vec::new();
            for item in items {
                // a `.` line: the occurrence is the scalar itself
                let scalar = body.fields.iter().filter(|f| f.locator == ".").find_map(|f| body.value_of(item, f).map(|v| (f, v)));
                // an item that lacks the value: the sentinel of a `.` line (ruling 5 of 0.9)
                // (not of one suppressed by `with`: ruling 4 of 0.18)
                let sentinel = body.fields.iter().filter(|f| f.locator == "." && live(item, f)).find_map(|f| f.sentinel().map(|s| (*f, s)));
                match (scalar, sentinel) {
                    (Some((f, v)), _) => {
                        let wv = p
                            .to_wire(f, v)
                            .and_then(|w| f.transform.encode_pb(&w))
                            .map_err(|e| transform_encode_err(p, f, e))?;
                        wv.write(&mut packed);
                        nodes.push(Node::Leaf(wv));
                    }
                    (None, Some((f, s))) => {
                        let wv = sentinel_wire(f, s)?;
                        wv.write(&mut packed);
                        nodes.push(Node::Leaf(wv));
                    }
                    // an item with nothing written is an empty length-delimited occurrence
                    (None, None) => nodes.push(Node::Msg(build(p, &body, item)?)),
                }
            }
            // a `.` line with a numeric transform: the packed form
            let node = match g.scalar() {
                // an item with no value is left out; a list whose items all
                // lack the value writes nothing (ruling 11 of 0.7)
                Some(f) if numeric(&f.transform) => {
                    if packed.is_empty() {
                        continue;
                    }
                    Node::Leaf(WireVal::LenDelim(packed))
                }
                _ => Node::Many(nodes),
            };
            insert_node(&mut tree, &parse_path(&g.locator)?, node)?;
        }
        // `when` and `const` values: a varint for an integer, nothing for `present`
        for w in sel.fixed() {
            // ruling 3 of 0.20: a list or a range keeps the varint of the
            // earliest field line on the path whose key is present, when it matches
            let mut num = w.num;
            if w.several() {
                if let Some(f) = sel.fields.iter().find(|f| f.locator == w.locator && has_key(ent, f)) {
                    let v = sel.value_of(ent, f).expect("present");
                    if let Ok(WireVal::Varint(x)) = p.to_wire(f, v).and_then(|v| f.transform.encode_pb(&v)) {
                        if w.holds_num(x) {
                            num = x;
                        }
                    }
                }
            }
            insert(&mut tree, &parse_path(&w.locator)?, WireVal::Varint(num))?;
        }
        Ok(tree)
    }

    #[cfg(feature = "protobuf")]
    pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
        let sel = p.select_encode(ent)?;
        let mut tree = build(p, &sel, ent)?;
        // `present` with no field written under the path: an empty
        // length-delimited field, so the output decodes as the same kind
        for w in &sel.whens {
            if w.present {
                let path = parse_path(&w.locator)?;
                let mut cur = &mut tree;
                for step in &path {
                    let tmp = cur;
                    cur = match tmp.entry(*step).or_insert_with(|| Node::Msg(BTreeMap::new())) {
                        Node::Msg(m) => m,
                        _ => break,
                    };
                }
            }
        }
        Ok(super::bits::to_hex(&serialize(&tree)))
    }
}

// ---------------------------------------------------------------------------
// Helpers: float formatting, ISO8601 <-> epoch ms, pack-file tokenizing
// ---------------------------------------------------------------------------

/// Shortest round-trip decimal for an f64 (Rust's Display already does this).
pub fn fmt_f64(x: f64) -> String {
    if x == x.trunc() && x.abs() < 1e15 {
        // integer-valued float: emit without trailing .0 for canonical stability
        format!("{}", x as i64)
    } else {
        format!("{}", x)
    }
}

/// Split a pack or module line into tokens. `#` starts a comment only at the
/// start of a token; double quotes wrap a value that holds whitespace.
fn tokenize(line: &str) -> Result<Vec<String>, Error> {
    let mut toks = Vec::new();
    let mut cur = String::new();
    let mut in_q = false;
    let mut started = false;
    for c in line.chars() {
        if in_q {
            if c == '"' {
                in_q = false;
            } else {
                cur.push(c);
            }
        } else if c == '"' {
            in_q = true;
            started = true;
        // whitespace between tokens: space, tab, line feed and carriage
        // return; any other character, U+00A0 included, is part of a token
        } else if pack_space(c) {
            if started {
                toks.push(std::mem::take(&mut cur));
                started = false;
            }
        } else if c == '#' && !started {
            break;
        } else {
            cur.push(c);
            started = true;
        }
    }
    if in_q {
        return err("unterminated-quote: a value that begins with `\"` has no closing `\"` on its line");
    }
    if started {
        toks.push(cur);
    }
    Ok(toks)
}

fn req_arg(toks: &[String], i: usize, ln: usize) -> Result<String, Error> {
    toks.get(i)
        .cloned()
        .ok_or(Error { msg: format!("bad-directive: line {}: missing argument", ln) })
}

/// Tokenize one line of a pack or module, the line number in a failure.
fn tokenize_at(line: &str, ln: usize) -> Result<Vec<String>, Error> {
    tokenize(line).map_err(|e| match e.msg.split_once(": ") {
        Some((kind, rest)) => Error { msg: format!("{}: line {}: {}", kind, ln, rest) },
        None => e,
    })
}

/// The directives of a pack, each with the number of arguments it takes:
/// (name, least, most). `usize::MAX`: any number more.
const PACK_DIRECTIVES: &[(&str, usize, usize)] = &[
    ("format", 1, 1),
    ("version", 1, 1),
    ("distribution", 1, 1),
    ("source", 1, 1),
    ("uses", 1, 1),
    ("wire", 1, 1),
    ("root", 1, 1),
    ("field", 3, usize::MAX),
    ("when", 2, 2),
    ("const", 2, 2),
    ("kind", 1, 1),
    ("requires", 1, usize::MAX),
    ("default", 2, 2),
    ("map", 3, 3),
    ("typemap", 2, 2),
    ("group", 2, usize::MAX),
    ("end", 0, 0),
    ("word_bytes", 1, 1),
    ("bit_order", 1, 1),
    ("layout", 1, 1),
    ("also", 1, 3),
    ("pad", 1, 1),
    ("align", 1, 1),
    ("presence", 2, 2),
    ("if", 1, usize::MAX),
    ("opt", 0, 0),
    ("chain", 0, 0),
    ("fx", 0, 0),
    ("length", 1, usize::MAX),
    ("delimiter", 1, 1),
    ("start", 1, 1),
    ("checksum", 1, 2),
    // the tlv wire (engine-spec v0.13): the form of these lines is checked
    // after the file is read, with the other checks of that version
    ("tag", 1, usize::MAX),
    ("key", 1, usize::MAX),
    // six-bit armor (engine-spec v0.14, ruling 13): exactly one argument, a
    // line check; the rest of the line is checked after the file is read, and
    // it may stand before the `wire` line
    ("armor", 1, 1),
    // engine-spec v0.18: `element <path>`; its wire and its path are checked
    // after the file is read
    ("element", 1, 1),
    // ASN.1 unaligned PER (engine-spec v0.19): `encoding <none | uper>`,
    // `ext`, `choice <n> [ext]`, `alt <i>`. Only the number of arguments is
    // a line check (5e of 0.11, as ruling 13 of 0.14 for `armor`); whether a
    // line fits its pack (ruling 9, 18, 21 of 0.19) is checked after the file.
    // None of them is in the list of lines that stand after the `wire` line.
    ("encoding", 1, 1),
    ("ext", 0, 0),
    ("choice", 1, 2),
    ("alt", 1, 1),
    // engine-spec v0.20: a switch on a decoded value (ruling 27: `case` takes
    // one value list, `else` none)
    ("switch", 1, 1),
    ("case", 1, 1),
    ("else", 0, 0),
    // engine-spec v0.21: `count <name> <len> [plus <n>]`; its form is checked
    // with the rest of the sequential layout, after the file is read
    ("count", 2, usize::MAX),
];

/// The lines that stand after the `wire` line (ruling 5b of 0.11).
const AFTER_WIRE: &[&str] = &[
    "root", "field", "when", "const", "group", "end", "word_bytes", "bit_order", "layout", "also", "pad", "align",
    "presence", "if", "opt", "chain", "fx", "length",
];

/// The checks of ruling 5 of 0.11 that each line of a pack owes as it is
/// read, in order: `unterminated-quote`, `unknown-directive`, the number of
/// arguments, `missing-wire`, then the line's own content that the line and
/// the lines before it decide (a repeated header line, the `distribution`
/// and `wire` values, `layout sequential` after a line it must precede, the
/// transform's name and parameters, the form of a locator). The parsers
/// check the rest of each line after this pass.
fn pack_line_checks(text: &str) -> Result<(), Error> {
    let mut wire: Option<Wire> = None;
    let mut seen_header: HashSet<&'static str> = HashSet::new();
    // the first line that must stand after `layout sequential`
    let mut first_after_wire: Option<usize> = None;
    let mut sequential = false;
    for (lineno, raw) in text.lines().enumerate() {
        let ln = lineno + 1;
        let toks = tokenize_at(raw, ln)?;
        if toks.is_empty() {
            continue;
        }
        let d = toks[0].as_str();
        let (name, least, most) = match PACK_DIRECTIVES.iter().find(|(n, _, _)| *n == d) {
            Some(e) => *e,
            None => return err(format!("unknown-directive: line {}: `{}` is not a directive of a pack", ln, d)),
        };
        let n = toks.len() - 1;
        // ruling 5 of 0.11 makes `key` in a pack `unknown-directive` (load
        // vector 445, `key extra string -`); 0.13 adds `key <hex>`, one
        // argument. Read together: only the one-argument form is a directive of a pack.
        if name == "key" && n != 1 {
            return err(format!("unknown-directive: line {}: `key` with {} arguments is a line of a module, not of a pack", ln, n));
        }
        // 5e: `checksum` takes one argument; `checksum sum16 <tag>` (0.13) two
        let most = if name == "checksum" && toks[1] != "sum16" { 1 } else { most };
        if n < least || n > most {
            let takes = match (least, most) {
                (l, m) if l == m => l.to_string(),
                (l, usize::MAX) => format!("at least {}", l),
                (l, m) => format!("{} to {}", l, m),
            };
            return bad(ln, format!("`{}` takes {} arguments, got {}", name, takes, n));
        }
        if AFTER_WIRE.contains(&name) {
            if wire.is_none() {
                return err(format!("missing-wire: line {}: `{}` stands before the `wire` line", ln, name));
            }
            first_after_wire.get_or_insert(ln);
        }
        // the line's own content
        if matches!(name, "format" | "version" | "wire" | "distribution") && !seen_header.insert(name) {
            return bad(ln, format!("a second `{}` line", name));
        }
        match name {
            "wire" => {
                wire = Some(match Wire::from_name(&toks[1]) {
                    // ruling 1c of 0.24: a wire of the specification this build lacks
                    Some(w) if !w.in_build() => {
                        return err(format!("unknown-wire: line {}: this build does not have the `{}` wire", ln, w.name()))
                    }
                    Some(w) => w,
                    None => return err(format!("unknown-wire: line {}: `{}` is not a wire", ln, toks[1])),
                })
            }
            "distribution" => {
                if Distribution::parse(&toks[1]).is_none() {
                    return bad(ln, format!("distribution is `public` or `controlled`, got `{}`", toks[1]));
                }
            }
            "layout" if toks[1] == "sequential" => {
                if let Some(at) = first_after_wire.filter(|at| *at < ln) {
                    return bad(ln, format!("`layout sequential` stands after line {}, which it must precede", at));
                }
                sequential = true;
            }
            "field" => {
                check_locator(wire, sequential, &toks[2], ln)?;
                // ruling 8 of 0.13: on tlv a transform that does not parse is
                // `bad-directive`, checked after the file is read
                let transform = match Transform::parse(&toks[3]) {
                    Err(_) if wire == Some(Wire::Tlv) => Transform::Hex,
                    t => t.map_err(|e| Error { msg: e.msg.replacen(": ", &format!(": line {}: ", ln), 1) })?,
                };
                // the options and the values of an `absent` option are line
                // checks too; a bit length above 64 is checked after the file (4d)
                let mut f = FieldDef {
                    model_key: toks[1].clone(),
                    locator: toks[2].clone(),
                    transform,
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
                    null: false,
                    implicit: false,
                    range: None,
                };
                field_options_at(&mut f, &toks, ln, true, false)?;
                if let Some(w) = wire {
                    let bits_len = match (w, sequential) {
                        (Wire::Bits, true) => toks[2].parse::<u32>().ok(),
                        (Wire::Bits, false) => bits::parse_locator(&toks[2]).ok().map(|(_, _, len)| len),
                        _ => None,
                    };
                    let decided = w != Wire::Bits || bits_len.map_or(false, |len| len <= 64);
                    // text (ruling 16 of 0.10) and tlv (ruling 10 of 0.13):
                    // `absent` does not fit the wire, checked after the file
                    if decided && !matches!(w, Wire::Text | Wire::Tlv) {
                        resolve_absent(w, &mut f, bits_len)?;
                    }
                }
            }
            "when" | "const" => check_locator(wire, sequential, &toks[1], ln)?,
            // 5a: an empty step of an `xml` group locator is a line check too
            "group" if wire == Some(Wire::Xml) && toks[2].split('/').any(|s| s.is_empty()) => {
                return err(format!("bad-locator: line {}: `{}`: an empty step", ln, toks[2]));
            }
            // ruling 44 of 0.21: a `protobuf` group step that is not digits only
            // is `bad-locator` (5a); `rest` and `last` are `bad-directive` after
            // the file (ruling 37)
            "group"
                if wire == Some(Wire::Protobuf)
                    && !matches!(toks[2].as_str(), "rest" | "last")
                    && toks[2].split('.').any(|s| s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit())) =>
            {
                return err(format!("bad-locator: line {}: `{}`: a step is a field number, digits only", ln, toks[2]));
            }
            _ => {}
        }
    }
    Ok(())
}

/// Ruling 5a of 0.11: the form of the locator of a `field`, `when` or
/// `const` line on its wire; `bad-locator` when it does not have it.
fn check_locator(wire: Option<Wire>, sequential: bool, loc: &str, ln: usize) -> Result<(), Error> {
    let bad_loc = |why: &str| err(format!("bad-locator: line {}: `{}`: {}", ln, loc, why));
    let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
    match wire {
        Some(Wire::Xml) => {
            let steps: Vec<&str> = loc.split('/').collect();
            if steps.iter().any(|s| s.is_empty()) {
                return bad_loc("an empty step");
            }
            let last = steps[steps.len() - 1];
            for s in &steps[..steps.len() - 1] {
                if s.starts_with('@') || *s == "#text" {
                    return bad_loc("a step after `@name` or `#text`");
                }
            }
            if last == "@" {
                return bad_loc("an empty attribute name");
            }
            if !(last.starts_with('@') || last == "#text") {
                return bad_loc("the locator does not end in `@name` or `#text`");
            }
        }
        Some(Wire::Json) => {
            if loc != "." && loc.split('.').any(|s| s.is_empty()) {
                return bad_loc("an empty member name");
            }
        }
        Some(Wire::GeoJson) => {
            if loc != "." && loc.split('.').any(|s| s.is_empty()) {
                return bad_loc("an empty member name");
            }
            if let Some(slot) = loc.strip_prefix("geometry.") {
                if !matches!(slot, "lon" | "lat" | "alt") {
                    return bad_loc("`geometry.` is followed by `lon`, `lat` or `alt`");
                }
            }
        }
        Some(Wire::Protobuf) => {
            if loc != "." {
                for step in loc.split('.') {
                    if step.is_empty() {
                        return bad_loc("an empty step");
                    }
                    if !digits(step) {
                        return bad_loc("a step is a field number, digits only");
                    }
                    match step.parse::<u64>() {
                        Ok(n) if (1..=536_870_911).contains(&n) => {}
                        _ => return bad_loc("a field number is 1 to 536870911"),
                    }
                }
            }
        }
        Some(Wire::Bits) if sequential => {
            if !loc.contains(':') {
                if !digits(loc) {
                    return bad_loc("a bit length is digits only");
                }
                if loc.bytes().all(|b| b == b'0') {
                    return bad_loc("a bit length of 0");
                }
            }
        }
        // ruling 9 of 0.19: a UPER locator in a pack that is not a UPER pack
        // (a fixed-layout one included, ruling 19) is `bad-directive`,
        // checked after the file is read, not a 5a form error
        // and `until:<code>` (engine-spec v0.22) outside a sequential layout
        // is `bad-directive` as well, as the UPER locators are
        Some(Wire::Bits) if ["int:", "enum:", "chars:", "octets:", "until:"].iter().any(|p| loc.starts_with(p)) => {}
        Some(Wire::Bits) => {
            if loc.contains(':') {
                let parts: Vec<&str> = loc.split(':').collect();
                if parts.len() != 3 || !parts.iter().all(|p| digits(p)) {
                    return bad_loc("a bits locator is <word>:<pos>:<len>, digits only");
                }
                if parts[2].bytes().all(|b| b == b'0') {
                    return bad_loc("a bit length of 0");
                }
            } else if !digits(loc) {
                // a bit length alone stays `bad-directive`; other text is no locator
                return bad_loc("a bits locator is <word>:<pos>:<len>, digits only");
            }
        }
        // tlv (engine-spec v0.13): a path is checked after the file is read,
        // and its errors are `bad-directive`
        Some(Wire::Text) | Some(Wire::Tlv) | None => {}
    }
    Ok(())
}

// --- civil date <-> days (Howard Hinnant's algorithms) ---
fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}
fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// `YYYY-MM-DDTHH:MM:SS[.fff]` then `Z`, `z`, `+hh:mm` or `-hh:mm`; the `T`
/// may be lowercase (engine-spec v0.6). The instant is converted to UTC.
/// Fraction digits beyond milliseconds are truncated.
pub fn iso8601_to_ms(s: &str) -> Result<i64, Error> {
    // ruling 3 of 0.11: nothing stands before or after
    let bytes = s.as_bytes();
    if bytes.len() < 20 || !s.is_ascii() {
        return err(format!("iso8601 too short: `{}`", s));
    }
    let num = |a: usize, b: usize| -> Result<i64, Error> {
        if !bytes[a..b].iter().all(|c| c.is_ascii_digit()) {
            return err(format!("iso8601 bad field in `{}`", s));
        }
        s[a..b].parse::<i64>().map_err(|_| Error { msg: format!("iso8601 bad field in `{}`", s) })
    };
    if bytes[4] != b'-' || bytes[7] != b'-' || !matches!(bytes[10], b'T' | b't') || bytes[13] != b':' || bytes[16] != b':' {
        return err(format!("iso8601 needs YYYY-MM-DDTHH:MM:SS: `{}`", s));
    }
    let year = num(0, 4)?;
    let mon = num(5, 7)?;
    let day = num(8, 10)?;
    let hh = num(11, 13)?;
    let mm = num(14, 16)?;
    let ss = num(17, 19)?;
    let mut i = 19;
    let mut frac_ms = 0i64;
    if bytes[i] == b'.' {
        i += 1;
        let start = i;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            i += 1;
        }
        if i == start {
            return err(format!("iso8601 fraction has no digits: `{}`", s));
        }
        let mut digits: String = s[start..i].chars().take(3).collect();
        while digits.len() < 3 {
            digits.push('0');
        }
        frac_ms = digits.parse::<i64>().unwrap_or(0);
    }
    // the designator: Z, z, or an offset from UTC
    let rest = &bytes[i..];
    let offset_min = match rest {
        [b'Z'] | [b'z'] => 0,
        [sign @ (b'+' | b'-'), _, _, b':', _, _] => {
            let m = num(i + 1, i + 3)? * 60 + num(i + 4, i + 6)?;
            if *sign == b'-' {
                -m
            } else {
                m
            }
        }
        _ => return err(format!("iso8601 needs `Z` or an offset `+hh:mm`: `{}`", s)),
    };
    // ruling 3b of 0.11: the ranges
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let last_day = match mon {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap => 29,
        2 => 28,
        _ => 0,
    };
    if !(1..=9999).contains(&year) || !(1..=last_day).contains(&day) || hh > 23 || mm > 59 || ss > 59 {
        return err(format!("iso8601 date or time out of range: `{}`", s));
    }
    if rest.len() == 6 && (num(i + 1, i + 3)? > 23 || num(i + 4, i + 6)? > 59) {
        return err(format!("iso8601 offset out of range: `{}`", s));
    }
    let days = days_from_civil(year, mon, day);
    let secs = days * 86400 + hh * 3600 + mm * 60 + ss - offset_min * 60;
    let ms = secs * 1000 + frac_ms;
    // ruling 3d of 0.11: the instant lies in years 0001 to 9999
    if !(MIN_ISO_MS..=MAX_ISO_MS).contains(&ms) {
        return err(format!("iso8601 instant outside years 0001 to 9999: `{}`", s));
    }
    Ok(ms)
}

/// `0001-01-01T00:00:00.000Z` and `9999-12-31T23:59:59.999Z` in epoch ms.
const MIN_ISO_MS: i64 = -62_135_596_800_000;
const MAX_ISO_MS: i64 = 253_402_300_799_999;

/// `ms_to_iso8601` for a transform: an instant outside years 0001 to 9999 is
/// refused (ruling 3f of 0.11).
pub fn ms_to_iso8601_checked(ms: i64) -> Result<String, Error> {
    if !(MIN_ISO_MS..=MAX_ISO_MS).contains(&ms) {
        return err(format!("{} ms is outside years 0001 to 9999", ms));
    }
    Ok(ms_to_iso8601(ms))
}

/// `iso8601_short` (engine-spec v0.18): `YYYY-MM-DDTHH:MM:SSZ` when the
/// milliseconds are 0, else the milliseconds with trailing zeros removed. An
/// instant outside the years 0000 to 9999 is an error (ruling 11).
pub fn ms_to_iso8601_short(ms: i64) -> Result<String, Error> {
    let secs = ms.div_euclid(1000);
    let frac = ms.rem_euclid(1000);
    let (y, m, d) = civil_from_days(secs.div_euclid(86400));
    if !(0..=9999).contains(&y) {
        return err(format!("{} ms is outside the years 0000 to 9999", ms));
    }
    let rem = secs.rem_euclid(86400);
    let mut out = format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", y, m, d, rem / 3600, (rem % 3600) / 60, rem % 60);
    if frac != 0 {
        let digits = format!("{:03}", frac);
        out.push('.');
        out.push_str(digits.trim_end_matches('0'));
    }
    out.push('Z');
    Ok(out)
}

/// `iso8601_si` (engine-spec v0.55): `YYYY-MM-DDTHH:MM:SSZ` when the
/// milliseconds are 0, else three fraction digits; years 0001 to 9999 only
/// (ruling 2 of 0.55).
pub fn ms_to_iso8601_si(ms: i64) -> Result<String, Error> {
    let full = ms_to_iso8601_checked(ms)?;
    Ok(if ms.rem_euclid(1000) == 0 { format!("{}Z", &full[..19]) } else { full })
}

pub fn ms_to_iso8601(ms: i64) -> String {
    let secs = ms.div_euclid(1000);
    let frac = ms.rem_euclid(1000);
    let days = secs.div_euclid(86400);
    let rem = secs.rem_euclid(86400);
    let (y, m, d) = civil_from_days(days);
    let hh = rem / 3600;
    let mm = (rem % 3600) / 60;
    let ss = rem % 60;
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
        y, m, d, hh, mm, ss, frac
    )
}
