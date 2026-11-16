//! goat-transformers reference engine (std-only).
//!
//! Data-driven any-to-any tactical message transformation. A `Pack` describes a
//! format as data (see `spec/engine-spec.md`); the engine interprets packs. No
//! message definition is compiled in. This is the reference implementation that
//! the other language engines are checked against via the shared vectors.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;

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
}

impl Scale {
    fn parse(args: &str) -> Option<Scale> {
        let parts: Vec<&str> = args.split(':').collect();
        if parts.is_empty() || parts.len() > 2 {
            return None;
        }
        let offset = match parts.get(1) {
            Some(s) => s.parse::<f64>().ok()?,
            None => 0.0,
        };
        let int = |s: &str| -> Option<f64> {
            if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            s.parse::<f64>().ok().filter(|x| *x != 0.0)
        };
        let (num, den) = match parts[0].split_once('/') {
            Some((n, d)) => (int(n)?, Some(int(d)?)),
            None => (parts[0].parse::<f64>().ok().filter(|x| *x != 0.0 && x.is_finite())?, None),
        };
        Some(Scale { num, den, offset })
    }
    /// `v * factor` (or `v * num / den`), then `+ offset`
    fn decode(&self, v: f64) -> f64 {
        match self.den {
            Some(den) => v * self.num / den + self.offset,
            None => v * self.num + self.offset,
        }
    }
    /// `(x - offset) / factor` (or `(x - offset) * den / num`), rounded half away from zero
    fn encode(&self, x: f64) -> f64 {
        match self.den {
            Some(den) => ((x - self.offset) * den / self.num).round(),
            None => ((x - self.offset) / self.num).round(),
        }
    }
}

impl Transform {
    fn parse(name: &str) -> Result<Transform, Error> {
        if let Some(args) = name.strip_prefix("linscale:") {
            let mut it = args.split(':');
            let maxpos = it.next().and_then(|s| s.parse::<f64>().ok());
            let range = it.next().and_then(|s| s.parse::<f64>().ok());
            return match (maxpos, range, it.next()) {
                (Some(m), Some(r), None) => Ok(Transform::Linscale(m, r)),
                _ => err(format!("linscale needs <maxpos>:<range>, got `{}`", name)),
            };
        }
        for (prefix, signed) in [("uscale:", false), ("sscale:", true)] {
            if let Some(args) = name.strip_prefix(prefix) {
                return match Scale::parse(args) {
                    Some(sc) => Ok(if signed { Transform::Sscale(sc) } else { Transform::Uscale(sc) }),
                    None => err(format!("bad-directive: {}<factor>[:<offset>] expected, got `{}`", prefix, name)),
                };
            }
        }
        match name {
            "bool" => Ok(Transform::Bool),
            "f32" => Ok(Transform::F32),
            "f64" => Ok(Transform::F64),
            "ascii" => Ok(Transform::Ascii),
            "string" => Ok(Transform::StringT),
            "float" => Ok(Transform::Float),
            "int" => Ok(Transform::Int),
            "iso8601_ms" => Ok(Transform::Iso8601Ms),
            "uint" => Ok(Transform::Uint),
            "twos" => Ok(Transform::Twos),
            "pstring" => Ok(Transform::Pstring),
            "pvarint" => Ok(Transform::Pvarint),
            "psint" => Ok(Transform::Psint),
            "pdouble" => Ok(Transform::Pdouble),
            "pfloat" => Ok(Transform::Pfloat),
            other => err(format!("unknown transform `{}`", other)),
        }
    }

    /// The shared-model type this transform yields (spec/shared-model.md).
    pub fn value_type(&self) -> KeyType {
        match self {
            Transform::StringT | Transform::Pstring | Transform::Ascii => KeyType::Str,
            Transform::Float
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
            | Transform::Uint
            | Transform::Twos
            | Transform::Pvarint
            | Transform::Psint => KeyType::Int,
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
        )
    }

    fn is_protobuf(&self) -> bool {
        matches!(
            self,
            Transform::Pstring | Transform::Pvarint | Transform::Psint | Transform::Pdouble | Transform::Pfloat
        )
    }

    /// bits wire: raw unsigned field value + bit length -> model value
    /// (every bits transform but `ascii`, which the codec reads byte by byte)
    fn decode_bits(&self, raw: u64, len: u32) -> Result<Value, Error> {
        let signed = |raw: u64, len: u32| -> i64 {
            let sign_bit = 1u64 << (len - 1);
            if len < 64 && raw & sign_bit != 0 {
                (raw as i64) - (1i64 << len)
            } else {
                raw as i64
            }
        };
        match self {
            Transform::Uint => Ok(Value::I64(raw as i64)),
            Transform::Twos => Ok(Value::I64(signed(raw, len))),
            Transform::Linscale(maxpos, range) => {
                Ok(Value::F64(signed(raw, len) as f64 / maxpos * range))
            }
            Transform::Uscale(sc) => Ok(Value::F64(sc.decode(raw as f64))),
            Transform::Sscale(sc) => Ok(Value::F64(sc.decode(signed(raw, len) as f64))),
            Transform::F32 => finite(f32::from_bits(raw as u32) as f64),
            Transform::F64 => finite(f64::from_bits(raw)),
            _ => err(format!("transform {:?} is not valid on a bits wire", self)),
        }
    }

    /// bits wire: model value -> raw unsigned field value masked to bit length
    fn encode_bits(&self, v: &Value, len: u32) -> Result<u64, Error> {
        let mask = if len >= 64 { u64::MAX } else { (1u64 << len) - 1 };
        // 2^len and 2^(len-1) are exact in f64 for every len in 1..=64
        let two = |n: u32| (2.0f64).powi(n as i32);
        match (self, v) {
            (Transform::Uint, Value::I64(n)) => Ok((*n as u64) & mask),
            (Transform::Twos, Value::I64(n)) => Ok((*n as u64) & mask),
            (Transform::Linscale(maxpos, range), Value::F64(x)) => {
                let raw = (x / range * maxpos).round() as i64;
                Ok((raw as u64) & mask)
            }
            (Transform::Uscale(sc), Value::F64(x)) => {
                let r = sc.encode(*x);
                if !(r >= 0.0 && r < two(len)) {
                    return err(format!("{} is outside the {}-bit unsigned range of the field", x, len));
                }
                Ok(r as u64)
            }
            (Transform::Sscale(sc), Value::F64(x)) => {
                let r = sc.encode(*x);
                if !(r >= -two(len - 1) && r < two(len - 1)) {
                    return err(format!("{} is outside the {}-bit signed range of the field", x, len));
                }
                Ok((r as i64 as u64) & mask)
            }
            (Transform::F32, Value::F64(x)) => Ok(single(*x)?.to_bits() as u64),
            (Transform::F64, Value::F64(x)) => Ok(finite(*x)?.as_f64().to_bits()),
            _ => err(format!("transform/value mismatch on bits: {:?} with {:?}", self, v)),
        }
    }
    /// wire string -> model value
    fn decode(&self, raw: &str) -> Result<Value, Error> {
        match self {
            Transform::StringT => Ok(Value::Str(raw.to_string())),
            Transform::Float => raw
                .trim()
                .parse::<f64>()
                .ok()
                .filter(|x| x.is_finite())
                .map(Value::F64)
                .ok_or(Error { msg: format!("float decode failed: `{}`", raw) }),
            Transform::Int => raw
                .trim()
                .parse::<i64>()
                .map(Value::I64)
                .map_err(|_| Error { msg: format!("int decode failed: `{}`", raw) }),
            Transform::Iso8601Ms => iso8601_to_ms(raw).map(Value::I64),
            t if t.is_bits() => err(format!("transform {:?} is only valid on a bits wire", self)),
            t if t.is_protobuf() => {
                err(format!("transform {:?} is only valid on a protobuf wire", self))
            }
            _ => err(format!("transform {:?} not valid on a text wire", self)),
        }
    }
    /// model value -> wire string
    fn encode(&self, v: &Value) -> Result<String, Error> {
        match (self, v) {
            (Transform::StringT, Value::Str(s)) => Ok(s.clone()),
            (Transform::Float, Value::F64(x)) => Ok(fmt_f64(*x)),
            (Transform::Int, Value::I64(n)) => Ok(n.to_string()),
            (Transform::Iso8601Ms, Value::I64(ms)) => Ok(ms_to_iso8601(*ms)),
            _ => err(format!("transform/value mismatch: {:?} with {:?}", self, v)),
        }
    }
    /// protobuf wire: a leaf field's wire value -> model value
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
    fn json_kind(&self) -> JsonKind {
        match self {
            Transform::StringT | Transform::Iso8601Ms | Transform::Pstring | Transform::Ascii => {
                JsonKind::StringK
            }
            Transform::Float
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
            | Transform::Psint => JsonKind::IntK,
        }
    }
}

/// A float read from the wire: not-a-number and infinity are refused
/// (ruling 23 of 0.5, extended in 0.6).
fn finite(x: f64) -> Result<Value, Error> {
    if x.is_finite() {
        Ok(Value::F64(x))
    } else {
        err(format!("{} is not a finite number", x))
    }
}

/// A model float narrowed to a single: outside single range is refused.
fn single(x: f64) -> Result<f32, Error> {
    let y = x as f32;
    if y.is_finite() {
        Ok(y)
    } else {
        err(format!("{} is outside the range of a single", x))
    }
}

enum JsonKind {
    StringK,
    NumK,
    IntK,
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
            return Scale::parse(a).filter(|_| !a.contains(':')).map(DeriveFn::Scale);
        }
        if let Some(a) = name.strip_prefix("offset:") {
            return match read_as(KeyType::Float, a) {
                Some(Value::F64(x)) => Some(DeriveFn::Offset(x, a.parse::<i64>().ok())),
                _ => None,
            };
        }
        if let Some(a) = name.strip_prefix("join:") {
            return Some(DeriveFn::Join(a.to_string()));
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
            let toks = tokenize(raw)?;
            if toks.is_empty() {
                continue;
            }
            let ln = lineno + 1;
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
                    derives.push(DeriveDef { target: toks[1].clone(), func, args: toks[3..].to_vec(), line: ln });
                }
                other => return err(format!("unknown-directive: line {}: `{}` in a model module", ln, other)),
            }
        }
        let name = name.ok_or(Error { msg: "bad-directive: model module missing `module`".into() })?;
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
        Ok(Module { name, version: version.unwrap_or_else(|| "0".into()), distribution, sources, keys, lists, derives, uses })
    }
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
}

impl GroupDef {
    /// The lines in force for one item.
    fn body(&self) -> Sel<'_> {
        Sel {
            kind: None,
            fields: self.fields.iter().collect(),
            whens: Vec::new(),
            consts: self.consts.iter().collect(),
            defaults: self.defaults.iter().collect(),
            groups: self.groups.iter().collect(),
            root: "",
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

/// One message layout of a format.
#[derive(Clone, Debug)]
pub struct KindDef {
    pub name: String,
    pub whens: Vec<WhenDef>,
    /// (model key, line)
    pub requires: Vec<(String, usize)>,
    pub fields: Vec<FieldDef>,
    /// `const` lines of this kind (same shape as a `when`; never `present`)
    pub consts: Vec<WhenDef>,
    pub defaults: Vec<DefaultDef>,
    /// xml only: the root element of this kind, when it has its own
    pub root: Option<String>,
    /// `group` blocks of this kind
    pub groups: Vec<GroupDef>,
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
}

impl<'a> Sel<'a> {
    /// The value encode uses for a field: the entity's, else the `default`.
    fn value_of(&self, ent: &'a Entity, f: &FieldDef) -> Option<&'a Value> {
        ent.fields.get(&f.model_key).or_else(|| {
            self.defaults.iter().find(|d| d.model_key == f.model_key).and_then(|d| d.value.as_ref())
        })
    }
    /// The values written over any field: every `when` that is not `present`, and every `const`.
    fn fixed(&self) -> impl Iterator<Item = &'a WhenDef> + '_ {
        self.whens.iter().copied().filter(|w| !w.present).chain(self.consts.iter().copied())
    }
    /// The locators a decode treats as mapped: every field, every `when` that
    /// is not `present` (ruling 27 of 0.5) and every `const`.
    fn mapped(&self) -> Vec<&'a str> {
        self.fields
            .iter()
            .map(|f| f.locator.as_str())
            .chain(self.fixed().map(|w| w.locator.as_str()))
            .chain(self.groups.iter().map(|g| g.locator.as_str()))
            .collect()
    }
}

#[derive(Clone, Debug)]
pub struct Pack {
    pub format: String,
    pub version: String,
    pub wire: Wire,
    pub root: String,       // xml only
    pub word_bytes: usize,  // bits only
    /// bits only: most-significant-bit-first order (`bit_order msb`)
    pub msb: bool,
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
}

fn bad<T>(ln: usize, m: impl AsRef<str>) -> Result<T, Error> {
    err(format!("bad-directive: line {}: {}", ln, m.as_ref()))
}

impl Pack {
    pub fn parse(text: &str) -> Result<Pack, Error> {
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
        let mut bit_order: Option<(bool, usize)> = None;
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
        let mut maps: Vec<(String, Vec<(String, String)>)> = Vec::new();
        // table name -> its place in `maps`
        let mut map_index: HashMap<String, usize> = HashMap::new();
        // `root` lines inside a kind, to check against the wire once it is known
        let mut kind_root_line: Option<usize> = None;
        let mut to_cot = BTreeMap::new();
        let mut from_cot = BTreeMap::new();
        for (lineno, raw) in text.lines().enumerate() {
            let toks = tokenize(raw)?;
            if toks.is_empty() {
                continue;
            }
            let ln = lineno + 1;
            match toks[0].as_str() {
                // ruling 18 of 0.7: only these five directives inside a group
                // (ruling 24 of 0.8: the header directives among the rest)
                d if !open.is_empty() && !matches!(d, "field" | "const" | "default" | "group" | "end") => {
                    return bad(ln, format!("`{}` is not allowed inside a group", d));
                }
                "format" => format = Some(req_arg(&toks, 1, ln)?),
                "version" => version = Some(req_arg(&toks, 1, ln)?),
                "wire" => {
                    wire = Some(match req_arg(&toks, 1, ln)?.as_str() {
                        "xml" => Wire::Xml,
                        "geojson" => Wire::GeoJson,
                        "bits" => Wire::Bits,
                        "protobuf" => Wire::Protobuf,
                        "json" => Wire::Json,
                        o => return err(format!("line {}: unknown wire `{}`", ln, o)),
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
                    let d = DefaultDef { model_key: toks[1].clone(), text: toks[2].clone(), line: ln, value: None };
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
                    word_bytes = req_arg(&toks, 1, ln)?
                        .parse::<usize>()
                        .map_err(|_| Error { msg: format!("line {}: word_bytes needs a number", ln) })?
                }
                "bit_order" => {
                    if toks.len() != 2 {
                        return bad(ln, "bit_order needs `lsb` or `msb`");
                    }
                    bit_order = Some(match toks[1].as_str() {
                        "lsb" => (false, ln),
                        "msb" => (true, ln),
                        o => return bad(ln, format!("bit_order is `lsb` or `msb`, got `{}`", o)),
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
                    for key in &toks[1..] {
                        k.requires.push((key.clone(), ln));
                    }
                }
                "field" => {
                    if toks.len() < 4 {
                        return err(format!(
                            "line {}: field needs <model-key> <locator> <transform> [options]",
                            ln
                        ));
                    }
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
                    };
                    // options after the transform, in any order (engine-spec v0.6)
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
                                i += 1;
                                continue;
                            }
                            "swap" => &mut f.swap,
                            "trim" => &mut f.trim,
                            "optional" => &mut f.optional,
                            o => return bad(ln, format!("unknown field option `{}`", o)),
                        };
                        if *flag {
                            return bad(ln, format!("field option `{}` given twice", toks[i]));
                        }
                        *flag = true;
                        i += 1;
                    }
                    match (open.last_mut(), kinds.last_mut()) {
                        (Some(g), _) => g.fields.push(f),
                        (None, Some(k)) => k.fields.push(f),
                        (None, None) => fields.push(f),
                    }
                }
                "typemap" => {
                    if toks.len() != 3 {
                        return err(format!("line {}: typemap needs <native> <cot>", ln));
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
                "pad" | "align" | "presence" | "if" | "opt" | "chain" | "fx" | "length" | "also" => {
                    return bad(ln, format!("`{}` is a line of a `layout sequential` pack", toks[0]));
                }
                other => return err(format!("line {}: unknown directive `{}`", ln, other)),
            }
        }
        if let Some(g) = open.first() {
            return bad(g.line, format!("group `{}` has no `end`", g.list));
        }
        let wire = wire.ok_or(Error { msg: "pack missing `wire`".into() })?;
        // xml: a pack-level root, unless every kind has its own (engine-spec v0.6)
        if wire == Wire::Xml && root.is_empty() && (kinds.is_empty() || kinds.iter().any(|k| k.root.is_none())) {
            return err("xml pack missing `root`");
        }
        if let Some(ln) = kind_root_line {
            if wire != Wire::Xml {
                return bad(ln, "`root` inside a kind is valid only on the xml wire");
            }
        }
        if wire == Wire::Bits && word_bytes == 0 {
            return err("bits pack missing `word_bytes`");
        }
        if let Some((_, ln)) = bit_order {
            if wire != Wire::Bits {
                return bad(ln, "`bit_order` is valid only on a bits wire");
            }
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
        for f in fields.iter().chain(kinds.iter().flat_map(|k| k.fields.iter())) {
            check_field_for_wire(wire, f, false)?;
            via_ok(f)?;
        }
        for w in whens.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.whens.iter_mut())) {
            resolve_when(wire, w, false)?;
        }
        let no_present = |c: &WhenDef| -> Result<(), Error> {
            if c.present {
                return bad(c.line, "a `const` value cannot be `present`; write `=present` for the text");
            }
            Ok(())
        };
        for c in consts.iter_mut().chain(kinds.iter_mut().flat_map(|k| k.consts.iter_mut())) {
            resolve_when(wire, c, false)?;
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
                    check_group_for_wire(wire, g)?;
                    if wire == Wire::Bits {
                        check_item_bounds(word_bytes, g)?;
                    }
                    for f in &g.fields {
                        check_field_for_wire(wire, f, true)?;
                        via_ok(f)?;
                    }
                    for c in g.consts.iter_mut() {
                        resolve_when(wire, c, true)?;
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
            let common = lines(&fields, &whens, &consts);
            let common_fields = lines(&fields, &[], &[]);
            if kinds.is_empty() {
                check_scope(wire, word_bytes, &common, &common_fields, &groups.iter().collect::<Vec<_>>())?;
            }
            for k in &kinds {
                let mut ls = common.clone();
                ls.extend(lines(&k.fields, &k.whens, &k.consts));
                let mut fs = common_fields.clone();
                fs.extend(lines(&k.fields, &[], &[]));
                let gs: Vec<&GroupDef> = groups.iter().chain(k.groups.iter()).collect();
                check_scope(wire, word_bytes, &ls, &fs, &gs)?;
            }
            let mut every: Vec<&GroupDef> = Vec::new();
            for g in groups.iter().chain(kinds.iter().flat_map(|k| k.groups.iter())) {
                g.walk(&mut every);
            }
            for g in every {
                check_scope(
                    wire,
                    word_bytes,
                    &lines(&g.fields, &[], &g.consts),
                    &lines(&g.fields, &[], &[]),
                    &g.groups.iter().collect::<Vec<_>>(),
                )?;
            }
        }
        let format = format.ok_or(Error { msg: "pack missing `format`".into() })?;
        let distribution = distribution.ok_or(Error {
            msg: format!("missing-distribution: pack `{}` has no `distribution`", format),
        })?;
        if sources.is_empty() {
            return err(format!("missing-source: pack `{}` has no `source`", format));
        }
        Ok(Pack {
            format,
            version: version.unwrap_or_else(|| "0".into()),
            wire,
            root,
            word_bytes,
            msb: bit_order.map(|(m, _)| m).unwrap_or(false),
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
        })
    }

    /// The lines in force when `kind` is selected (None: a pack without kinds).
    fn sel<'a>(&'a self, kind: Option<&'a KindDef>) -> Sel<'a> {
        let mut fields: Vec<&FieldDef> = self.fields.iter().collect();
        let mut whens: Vec<&WhenDef> = self.whens.iter().collect();
        let mut consts: Vec<&WhenDef> = self.consts.iter().collect();
        let mut defaults: Vec<&DefaultDef> = Vec::new();
        let mut groups: Vec<&GroupDef> = self.groups.iter().collect();
        let mut root = self.root.as_str();
        if let Some(k) = kind {
            groups.extend(k.groups.iter());
            fields.extend(k.fields.iter());
            whens.extend(k.whens.iter());
            consts.extend(k.consts.iter());
            defaults.extend(k.defaults.iter());
            if let Some(r) = &k.root {
                root = r;
            }
        }
        defaults.extend(self.defaults.iter());
        Sel { kind, fields, whens, consts, defaults, groups, root }
    }

    /// Decode-side kind selection: `holds` says whether a `when` matches the
    /// wire. `root` is the document's root element (xml): a kind is considered
    /// only when its root, or the pack's, has that name.
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
            .find(|k| {
                // a key that is present, or a list that has at least one item
                k.requires
                    .iter()
                    .all(|(key, _)| ent.fields.contains_key(key) || ent.lists.get(key).map_or(false, |l| !l.is_empty()))
            })
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
    fn to_wire(&self, f: &FieldDef, v: &Value) -> Result<Value, Error> {
        // the typemap, then the table (ruling 6 of 0.6)
        let mapped = match v {
            Value::Str(cot) if f.model_key == "type" => self.typemap_from_cot.get(cot).map(|n| Value::Str(n.clone())),
            _ => None,
        };
        let v = mapped.as_ref().unwrap_or(v);
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
        let mut out: Vec<(usize, &str)> =
            self.kinds.iter().flat_map(|k| k.requires.iter().map(|(key, line)| (*line, key.as_str()))).collect();
        if let Some(body) = &self.seq {
            body.visit(&mut |v| {
                if let seq::Visit::Requires(line, key) = v {
                    out.push((line, key));
                }
            });
        }
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

fn transform_encode_err(p: &Pack, f: &FieldDef, e: Error) -> Error {
    Error {
        msg: format!("transform-encode: format `{}`: `{}` at `{}`: {}", p.format, f.model_key, f.locator, e.msg),
    }
}

/// Read table or pack text as a value of the given type. None when it is not one.
fn read_as(ty: KeyType, text: &str) -> Option<Value> {
    let plain = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit() || matches!(b, b'-' | b'+' | b'.' | b'e' | b'E'));
    match ty {
        KeyType::Str => Some(Value::Str(text.to_string())),
        KeyType::Int => text.parse::<i64>().ok().map(Value::I64),
        KeyType::Float => text.parse::<f64>().ok().filter(|x| x.is_finite() && plain(text)).map(Value::F64),
    }
}

/// Table text in the canonical form a value of that type is compared in.
fn canon_text(ty: KeyType, text: &str) -> String {
    match ty {
        KeyType::Str => text.to_string(),
        _ => read_as(ty, text).map(|v| v.as_display()).unwrap_or_else(|| text.to_string()),
    }
}

/// The fields of one decode. A key takes the value of the earliest line whose
/// locator is present and whose transform succeeds (engine-spec v0.6); a key
/// with a failed line and no value fails the decode (ruling 9 of 0.1.1). A line
/// whose transform succeeds and whose table refuses the value fails the decode
/// whatever the other lines of the key do (ruling 4 of 0.6).
struct Decoded {
    ent: Entity,
    /// (key, message): a transform failed; an error unless the key gets a value
    soft: Vec<(String, String)>,
    /// a table refused a value, or an item failed
    hard: Vec<String>,
    hard_keys: Vec<String>,
}
impl Decoded {
    fn new() -> Decoded {
        Decoded { ent: Entity::default(), soft: Vec::new(), hard: Vec::new(), hard_keys: Vec::new() }
    }
    fn has(&self, f: &FieldDef) -> bool {
        self.ent.fields.contains_key(&f.model_key)
    }
    /// One line whose locator is present: the transform's result, through the table.
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
    fn close(self) -> (Entity, Vec<String>) {
        let ent = self.ent;
        let mut failed: Vec<String> =
            self.soft.into_iter().filter(|(k, _)| !ent.fields.contains_key(k)).map(|(_, m)| m).collect();
        failed.extend(self.hard);
        (ent, failed)
    }
    /// Take the decoded items of a list: a failed item field fails the decode.
    fn put_list(&mut self, list: &str, items: Vec<Decoded>) {
        let mut out = Vec::new();
        for (i, item) in items.into_iter().enumerate() {
            let (ent, failed) = item.close();
            self.hard.extend(failed.into_iter().map(|m| format!("{}[{}]: {}", list, i, m)));
            out.push(ent);
        }
        self.ent.lists.insert(list.to_string(), out);
    }
    fn finish(self, p: &Pack, sel: &Sel) -> Result<Entity, Error> {
        let (mut ent, failed) = self.close();
        if !failed.is_empty() {
            return err(format!("transform-decode: format `{}`: {}", p.format, failed.join("; ")));
        }
        ent.kind = sel.kind.map(|k| (p.format.clone(), k.name.clone()));
        Ok(ent)
    }
}

/// Load checks a `field` line owes its wire (engine-spec v0.5).
fn check_field_for_wire(wire: Wire, f: &FieldDef, in_group: bool) -> Result<(), Error> {
    let t = &f.transform;
    if (f.swap || f.trim || f.optional) && wire != Wire::Bits {
        return bad(f.line, "`swap`, `trim` and `optional` are valid only on a bits wire");
    }
    if f.trim && *t != Transform::Ascii {
        return bad(f.line, "`trim` is valid only with `ascii`");
    }
    if *t == Transform::Bool && wire != Wire::Json {
        return bad(f.line, "`bool` is valid only on the json wire");
    }
    // inside a group `.` is the item itself (json, geojson, protobuf)
    let item_itself = in_group && f.locator == ".";
    match wire {
        Wire::Json => {
            if !matches!(
                t,
                Transform::StringT | Transform::Float | Transform::Int | Transform::Iso8601Ms | Transform::Bool
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
            let ok = match t {
                Transform::F32 => len == 32,
                Transform::F64 => len == 64,
                Transform::Ascii => len % 8 == 0 && (8..=2040).contains(&len),
                _ => (1..=64).contains(&len),
            };
            if !ok {
                return bad(f.line, format!("bit length {} is not allowed for the transform of `{}`", len, f.model_key));
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
    for (line, loc) in g.fields.iter().map(|f| (f.line, &f.locator)).chain(g.consts.iter().map(|c| (c.line, &c.locator))) {
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
        if g.item_bits.is_some() {
            return bad(g.line, "`item` is valid only on a bits wire");
        }
    }
    let ok = match wire {
        Wire::Xml => names('/') && !g.locator.contains('@') && !g.locator.contains('#'),
        Wire::Json => names('.'),
        Wire::GeoJson => {
            names('.') && !g.locator.starts_with("geometry.") && (!g.locator.contains('.') || g.locator.starts_with("properties."))
        }
        Wire::Protobuf => {
            // ruling 13 of 0.7: a body mixing `.` with paths
            if g.scalar().is_some() && (g.fields.iter().any(|f| f.locator != ".") || !g.consts.is_empty() || !g.groups.is_empty())
            {
                return bad(g.line, format!("the body of group `{}` mixes `.` with paths", g.list));
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
        Wire::Bits => None,
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

/// Validate one `when` line against the wire and work out its value.
fn resolve_when(wire: Wire, w: &mut WhenDef, in_group: bool) -> Result<(), Error> {
    let number = |w: &WhenDef| -> Result<u64, Error> {
        if w.value.is_empty() || !w.value.bytes().all(|b| b.is_ascii_digit()) {
            return bad(w.line, format!("`when` value `{}` is not an unsigned decimal integer", w.value));
        }
        w.value
            .parse::<u64>()
            .or_else(|_| bad(w.line, format!("`when` value `{}` is too large", w.value)))
    };
    match wire {
        Wire::Bits => {
            let (_, _, len) = bits::parse_locator(&w.locator)
                .map_err(|e| Error { msg: format!("bad-directive: line {}: {}", w.line, e.msg) })?;
            if !(1..=64).contains(&len) {
                return bad(w.line, format!("bit length {} is not allowed on a `when`", len));
            }
            w.num = number(w)?;
            if len < 64 && w.num >> len != 0 {
                return bad(w.line, format!("`when` value {} does not fit {} bits", w.num, len));
            }
        }
        Wire::Protobuf => {
            protobuf::parse_path(&w.locator)
                .map_err(|e| Error { msg: format!("bad-directive: line {}: {}", w.line, e.msg) })?;
            if w.value == "present" {
                w.present = true;
            } else {
                w.num = number(w)?;
            }
        }
        Wire::Xml | Wire::GeoJson | Wire::Json => {
            let ok = match wire {
                Wire::Xml => {
                    let last = w.locator.rsplit('/').next().unwrap_or("");
                    (last.starts_with('@') && last.len() > 1) || (last == "#text" && (in_group || w.locator.contains('/')))
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
            } else {
                w.forced = w.value.starts_with('=');
                w.text = w.value.strip_prefix('=').unwrap_or(&w.value).to_string();
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
}

impl Default for Engine {
    fn default() -> Engine {
        Engine {
            packs: BTreeMap::new(),
            modules: BTreeMap::new(),
            key_index: HashMap::new(),
            list_index: HashMap::new(),
            max_distribution: Distribution::Controlled,
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
        // record each key's declared type, and read each default as it
        let set_field = |f: &mut FieldDef| f.key_type = self.key_def(&f.model_key).map(|d| d.ty);
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
            .ok_or(Error { msg: format!("no pack loaded for format `{}`", format) })
    }

    pub fn decode(&self, format: &str, bytes: &str) -> Result<Entity, Error> {
        let p = self.pack(format)?;
        match p.wire {
            Wire::Xml => xml::decode(p, bytes),
            Wire::GeoJson => geojson::decode(p, bytes),
            Wire::Bits => bits::decode(p, bytes),
            Wire::Protobuf => protobuf::decode(p, bytes),
            Wire::Json => jsonwire::decode(p, bytes),
        }
    }
    pub fn encode(&self, format: &str, ent: &Entity) -> Result<String, Error> {
        let p = self.pack(format)?;
        match p.wire {
            Wire::Xml => xml::encode(p, ent),
            Wire::GeoJson => geojson::encode(p, ent),
            Wire::Bits => bits::encode(p, ent),
            Wire::Protobuf => protobuf::encode(p, ent),
            Wire::Json => jsonwire::encode(p, ent),
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
        let mut ent = self.decode(from, bytes)?;
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

pub mod xml {
    use super::*;

    #[derive(Debug, Default, Clone)]
    pub struct Node {
        pub name: String,
        pub attrs: Vec<(String, String)>,
        pub children: Vec<Node>,
        pub text: Option<String>,
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
                Some(v) => w.present || v == w.text,
            },
            Some((node, Loc::Text)) => w.present || node.text.as_deref().unwrap_or("") == w.text,
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
    fn decode_scope(p: &Pack, sel: &Sel, node: &Node, item: bool, d: &mut Decoded) {
        for f in &sel.fields {
            if f.locator == "#text" && !item {
                continue;
            }
            if let Some((n, loc)) = resolve(node, &f.locator) {
                let raw = match loc {
                    Loc::Attr(a) => n.attr(&a).map(|s| s.to_string()),
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
            let decoded = found
                .into_iter()
                .map(|n| {
                    let mut di = Decoded::new();
                    decode_scope(p, &body, n, true, &mut di);
                    di
                })
                .collect();
            d.put_list(&g.list, decoded);
        }
    }

    pub fn decode(p: &Pack, bytes: &str) -> Result<Entity, Error> {
        let root = parse(bytes)?;
        if p.kinds.is_empty() && root.name != p.root {
            return err(format!("missing-root: format `{}`: expected root <{}>, found <{}>", p.format, p.root, root.name));
        }
        // a kind is considered only when the document's root is its root
        let sel = p.select_decode(Some(&root.name), |w| when_holds(&root, w))?;
        let mut d = Decoded::new();
        decode_scope(p, &sel, &root, false, &mut d);
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
        lines.sort_by_key(|l| l.0);
        for (_, line) in &lines {
            match line {
                Line::Value(locator, raw, is_when) => place(node, locator, raw, *is_when)?,
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
    fn escape_attr(s: &str) -> String {
        s.replace('&', "&amp;").replace('<', "&lt;").replace('"', "&quot;")
    }
    fn escape_text(s: &str) -> String {
        s.replace('&', "&amp;").replace('<', "&lt;")
    }

    // --- minimal parser ---
    pub fn parse(input: &str) -> Result<Node, Error> {
        let mut p = XmlParser { b: input.as_bytes(), i: 0 };
        p.skip_prolog();
        p.parse_element()
    }
    struct XmlParser<'a> {
        b: &'a [u8],
        i: usize,
    }
    impl<'a> XmlParser<'a> {
        fn ws(&mut self) {
            while self.i < self.b.len() && (self.b[self.i] as char).is_ascii_whitespace() {
                self.i += 1;
            }
        }
        fn skip_prolog(&mut self) {
            loop {
                self.ws();
                if self.starts_with("<?") {
                    while self.i < self.b.len() && !self.starts_with("?>") {
                        self.i += 1;
                    }
                    self.i += 2;
                } else if self.starts_with("<!") {
                    while self.i < self.b.len() && self.b[self.i] != b'>' {
                        self.i += 1;
                    }
                    self.i += 1;
                } else {
                    break;
                }
            }
        }
        fn starts_with(&self, s: &str) -> bool {
            self.b[self.i..].starts_with(s.as_bytes())
        }
        fn parse_element(&mut self) -> Result<Node, Error> {
            self.ws();
            if self.i >= self.b.len() || self.b[self.i] != b'<' {
                return err("expected '<'");
            }
            self.i += 1;
            let name = self.read_name();
            let mut node = Node { name, ..Default::default() };
            loop {
                self.ws();
                if self.i >= self.b.len() {
                    return err("unexpected end in tag");
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
                    return err("bad attribute name");
                }
                self.ws();
                if self.i >= self.b.len() || self.b[self.i] != b'=' {
                    return err("expected '=' in attribute");
                }
                self.i += 1;
                self.ws();
                let q = self.b[self.i];
                if q != b'"' && q != b'\'' {
                    return err("expected quote");
                }
                self.i += 1;
                let start = self.i;
                while self.i < self.b.len() && self.b[self.i] != q {
                    self.i += 1;
                }
                let val = unescape(&String::from_utf8_lossy(&self.b[start..self.i]));
                self.i += 1;
                node.attrs.push((an, val));
            }
            // content
            let mut text = String::new();
            loop {
                if self.starts_with("</") {
                    self.i += 2;
                    let _ = self.read_name();
                    self.ws();
                    if self.i < self.b.len() && self.b[self.i] == b'>' {
                        self.i += 1;
                    }
                    break;
                } else if self.i < self.b.len() && self.b[self.i] == b'<' {
                    let child = self.parse_element()?;
                    node.children.push(child);
                } else if self.i >= self.b.len() {
                    return err("unexpected end in content");
                } else {
                    let start = self.i;
                    while self.i < self.b.len() && self.b[self.i] != b'<' {
                        self.i += 1;
                    }
                    text.push_str(&String::from_utf8_lossy(&self.b[start..self.i]));
                }
            }
            let t = unescape(text.trim());
            if !t.is_empty() {
                node.text = Some(t);
            }
            Ok(node)
        }
        fn read_name(&mut self) -> String {
            self.ws();
            let start = self.i;
            while self.i < self.b.len() {
                let c = self.b[self.i] as char;
                if c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == ':' || c == '.' {
                    self.i += 1;
                } else {
                    break;
                }
            }
            String::from_utf8_lossy(&self.b[start..self.i]).to_string()
        }
    }
    fn unescape(s: &str) -> String {
        s.replace("&quot;", "\"")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&apos;", "'")
            .replace("&amp;", "&")
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
        pub fn get<'a>(&'a self, key: &str) -> Option<&'a Json> {
            if let Json::Obj(m) = self {
                m.iter().find(|(k, _)| k == key).map(|(_, v)| v)
            } else {
                None
            }
        }
    }

    pub fn parse(input: &str) -> Result<Json, Error> {
        let mut p = JsonParser { b: input.as_bytes(), i: 0, raws: None };
        p.ws();
        let v = p.value()?;
        p.ws();
        Ok(v)
    }

    /// Parse, and also return the text of every number as written, in
    /// document order.
    pub fn parse_raw(input: &str) -> Result<(Json, Vec<String>), Error> {
        let mut p = JsonParser { b: input.as_bytes(), i: 0, raws: Some(Vec::new()) };
        p.ws();
        let v = p.value()?;
        p.ws();
        Ok((v, p.raws.unwrap_or_default()))
    }

    /// How many numbers a value holds, in document order.
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
    }
    impl<'a> JsonParser<'a> {
        fn ws(&mut self) {
            while self.i < self.b.len() && (self.b[self.i] as char).is_ascii_whitespace() {
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
            if self.b[self.i..].starts_with(s.as_bytes()) {
                self.i += s.len();
                Ok(())
            } else {
                err(format!("json: expected `{}`", s))
            }
        }
        fn boolean(&mut self) -> Result<Json, Error> {
            if self.b[self.i..].starts_with(b"true") {
                self.i += 4;
                Ok(Json::Bool(true))
            } else {
                self.expect("false")?;
                Ok(Json::Bool(false))
            }
        }
        fn object(&mut self) -> Result<Json, Error> {
            self.i += 1; // {
            let mut m = Vec::new();
            self.ws();
            if self.i < self.b.len() && self.b[self.i] == b'}' {
                self.i += 1;
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
            Ok(Json::Obj(m))
        }
        fn array(&mut self) -> Result<Json, Error> {
            self.i += 1; // [
            let mut a = Vec::new();
            self.ws();
            if self.i < self.b.len() && self.b[self.i] == b']' {
                self.i += 1;
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
            Ok(Json::Arr(a))
        }
        fn hex4(&mut self) -> Result<u32, Error> {
            let bad = || Error { msg: "json: bad \\u".into() };
            let hex = self.b.get(self.i..self.i + 4).ok_or_else(bad)?;
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
                            b'n' => s.push(b'\n'),
                            b't' => s.push(b'\t'),
                            b'r' => s.push(b'\r'),
                            b'b' => s.push(0x08),
                            b'f' => s.push(0x0c),
                            b'u' => {
                                let mut cp = self.hex4()?;
                                // a surrogate pair is one character
                                if (0xD800..0xDC00).contains(&cp) && self.b[self.i..].starts_with(b"\\u") {
                                    let save = self.i;
                                    self.i += 2;
                                    let lo = self.hex4()?;
                                    if (0xDC00..0xE000).contains(&lo) {
                                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                                    } else {
                                        self.i = save;
                                    }
                                }
                                push(&mut s, char::from_u32(cp).unwrap_or('\u{FFFD}'));
                            }
                            _ => s.push(e),
                        }
                    }
                    _ => s.push(c),
                }
            }
            err("json: unterminated string")
        }
        fn number(&mut self) -> Result<Json, Error> {
            let start = self.i;
            let mut is_float = false;
            if self.b.get(self.i) == Some(&b'-') {
                self.i += 1;
            }
            while self.i < self.b.len() {
                match self.b[self.i] {
                    b'0'..=b'9' => self.i += 1,
                    b'.' | b'e' | b'E' | b'+' | b'-' => {
                        is_float = true;
                        self.i += 1;
                    }
                    _ => break,
                }
            }
            let tok = std::str::from_utf8(&self.b[start..self.i]).unwrap();
            if let Some(raws) = &mut self.raws {
                raws.push(tok.to_string());
            }
            if is_float {
                tok.parse::<f64>().map(Json::Num).map_err(|_| Error {
                    msg: format!("json: bad number `{}`", tok),
                })
            } else {
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

    pub fn serialize(j: &Json) -> String {
        let mut s = String::new();
        write(j, &mut s);
        s
    }
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
fn json_when_holds(member: Option<&json::Json>, w: &WhenDef) -> bool {
    match member {
        None | Some(json::Json::Null) => false,
        Some(_) if w.present => true,
        Some(j) => json_when_text(j).as_deref() == Some(w.text.as_str()),
    }
}

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
    fn item_dec(t: &Transform, j: &Json) -> Result<Value, Error> {
        match j {
            Json::Obj(_) | Json::Arr(_) => err("the value is not a scalar"),
            _ => t.decode(&json_scalar_string(j)),
        }
    }

    // locator forms: "id", "geometry.lon|lat|alt", "properties.<name>"
    pub fn decode(p: &Pack, bytes: &str) -> Result<Entity, Error> {
        let (root, raws) = json::parse_raw(bytes)?;
        let sel = p.select_decode(None, |w| json_when_holds(when_member(&root, &w.locator), w))?;
        let coords = root
            .get("geometry")
            .and_then(|g| g.get("coordinates"))
            .and_then(|c| if let Json::Arr(a) = c { Some(a) } else { None });
        let mut d = Decoded::new();
        let mapped_props: Vec<&str> = sel.mapped().into_iter().filter_map(|l| l.strip_prefix("properties.")).collect();
        for f in &sel.fields {
            let raw: Option<String> = if f.locator == "id" {
                root.get("id").map(json_scalar_string)
            } else if let Some(slot) = f.locator.strip_prefix("geometry.") {
                let idx = match slot {
                    "lon" => 0,
                    "lat" => 1,
                    "alt" => 2,
                    o => return err(format!("bad geojson geometry slot `{}`", o)),
                };
                coords.and_then(|a| a.get(idx)).map(json_scalar_string)
            } else if let Some(name) = f.locator.strip_prefix("properties.") {
                root.get("properties").and_then(|pp| pp.get(name)).map(json_scalar_string)
            } else {
                return err(format!("bad geojson locator `{}`", f.locator));
            };
            if let Some(r) = raw {
                d.put(p, f, f.transform.decode(&r));
            }
        }
        // groups: a `properties.<name>` or top-level member whose value is an array
        jsonwire::decode_groups(p, &sel, &root, item_dec, &mut d)?;
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
                match kept.iter_mut().find(|(name, _, _)| name == k) {
                    Some(entry) => *entry = (k, locator, value),
                    None => kept.push((k, locator, value)),
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
        for w in sel.fixed() {
            lines.push((w.line, &w.locator, json_when_value(w), true));
        }
        // a list that is present: an array at the group's member
        for g in &sel.groups {
            if let Some(items) = ent.lists.get(&g.list) {
                lines.push((g.line, &g.locator, jsonwire::list_json(p, g, items, value_to_json)?, false));
            }
        }
        lines.sort_by_key(|l| l.0);
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

    fn decode_value(t: &Transform, j: &Json) -> Result<Value, Error> {
        match (t, j) {
            (Transform::StringT, Json::Str(s)) => Ok(Value::Str(s.clone())),
            (Transform::Float, Json::Int(n)) => Ok(Value::F64(*n as f64)),
            (Transform::Float, Json::Num(x)) => Ok(Value::F64(*x)),
            (Transform::Int, Json::Int(n)) => Ok(Value::I64(*n)),
            (Transform::Int, Json::Num(x)) if x.fract() == 0.0 && x.abs() < 9.0e18 => Ok(Value::I64(*x as i64)),
            (Transform::Iso8601Ms, Json::Str(s)) => iso8601_to_ms(s).map(Value::I64),
            (Transform::Bool, Json::Bool(b)) => Ok(Value::I64(*b as i64)),
            _ => err(format!("JSON value `{}` has the wrong type for the transform", json::serialize(j))),
        }
    }

    fn encode_value(t: &Transform, v: &Value) -> Result<Json, Error> {
        match (t, v) {
            (Transform::StringT, Value::Str(s)) => Ok(Json::Str(s.clone())),
            (Transform::Float, Value::F64(x)) if x.is_finite() => Ok(Json::Num(*x)),
            (Transform::Int, Value::I64(n)) => Ok(Json::Int(*n)),
            (Transform::Iso8601Ms, Value::I64(ms)) => Ok(Json::Str(ms_to_iso8601(*ms))),
            (Transform::Bool, Value::I64(1)) => Ok(Json::Bool(true)),
            (Transform::Bool, Value::I64(0)) => Ok(Json::Bool(false)),
            (Transform::Bool, other) => err(format!("bool encodes 1 or 0, got {}", other.as_display())),
            _ => err(format!("transform/value mismatch: {:?} with {:?}", t, v)),
        }
    }

    /// How a wire turns a JSON value into a model value, and back.
    pub(crate) type Dec = fn(&Transform, &Json) -> Result<Value, Error>;
    pub(crate) type Enc = fn(&Transform, &Value) -> Result<Json, Error>;

    /// Decode the fields and groups of one scope: the message object, or one
    /// array element of a group.
    fn decode_scope(p: &Pack, sel: &Sel, obj: &Json, item: bool, dec: Dec, d: &mut Decoded) -> Result<(), Error> {
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
                None | Some(Json::Null) => {}
                Some(j) => d.put(p, f, dec(&f.transform, j)),
            }
        }
        decode_groups(p, sel, obj, dec, d)
    }

    /// The groups of one scope: the member at the group's path is an array,
    /// each element one item. `null` and a missing member: the list is absent.
    pub(crate) fn decode_groups(p: &Pack, sel: &Sel, obj: &Json, dec: Dec, d: &mut Decoded) -> Result<(), Error> {
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
            let mut items = Vec::new();
            for e in elements {
                let mut di = Decoded::new();
                decode_scope(p, &body, e, true, dec, &mut di)?;
                items.push(di);
            }
            d.put_list(&g.list, items);
        }
        Ok(())
    }

    pub fn decode(p: &Pack, bytes: &str) -> Result<Entity, Error> {
        let root = json::parse(bytes).map_err(|e| Error { msg: format!("malformed-wire: {}", e.msg) })?;
        if !matches!(root, Json::Obj(_)) {
            return err(format!("malformed-wire: format `{}`: the message is not a JSON object", p.format));
        }
        // ruling 22 of 0.5: the same member name twice in one object
        fn twice(j: &Json) -> Option<&str> {
            match j {
                Json::Obj(m) => {
                    for (i, (k, v)) in m.iter().enumerate() {
                        if m[..i].iter().any(|(other, _)| other == k) {
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
        decode_scope(p, &sel, &root, false, decode_value, &mut d)?;
        // residue: every scalar member, at any depth, that no line maps
        let mapped: Vec<&str> = sel.mapped();
        fn walk(obj: &Json, prefix: &str, mapped: &[&str], format: &str, out: &mut Vec<(String, String, String)>) {
            if let Json::Obj(members) = obj {
                for (k, v) in members {
                    // a member name with `.` has no path in 0.5: not carried
                    if k.contains('.') || k.is_empty() {
                        continue;
                    }
                    let path = if prefix.is_empty() { k.clone() } else { format!("{}.{}", prefix, k) };
                    match v {
                        Json::Obj(_) => walk(v, &path, mapped, format, out),
                        Json::Arr(_) | Json::Null => {}
                        scalar => {
                            if !mapped.contains(&path.as_str()) {
                                out.push((format.to_string(), path, json::serialize(scalar)));
                            }
                        }
                    }
                }
            }
        }
        walk(&root, "", &mapped, &p.format, &mut d.ent.residue);
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
                    // a scalar (`.`) item with no value is `null` (ruling 11 of 0.7)
                    if members.is_empty() && g.scalar().is_some() {
                        Json::Null
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
        lines.sort_by_key(|l| l.0);
        let mut top: Vec<(String, Json)> = Vec::new();
        for (_, path, value, is_when) in lines {
            let names: Vec<&str> = path.split('.').collect();
            // a nested object takes the position of the first line that addresses into it
            let parent = parent_of(&mut top, &names)
                .ok_or(Error { msg: format!("format `{}`: path `{}` runs through a scalar member", p.format, path) })?;
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
        let word = p[0].parse::<usize>().map_err(|_| Error { msg: format!("bad word in `{}`", loc) })?;
        let pos = p[1].parse::<u32>().map_err(|_| Error { msg: format!("bad pos in `{}`", loc) })?;
        let len = p[2].parse::<u32>().map_err(|_| Error { msg: format!("bad len in `{}`", loc) })?;
        if len == 0 {
            return err(format!("bits len must be at least 1 in `{}`", loc));
        }
        Ok((word, pos, len))
    }

    /// A group locator `<word>:<pos>`: where the first item starts.
    pub(crate) fn parse_group_locator(loc: &str) -> Result<(usize, u32), Error> {
        let bad = || Error { msg: format!("bits group locator must be word:pos, got `{}`", loc) };
        let (w, p) = loc.split_once(':').ok_or_else(bad)?;
        Ok((w.parse::<usize>().map_err(|_| bad())?, p.parse::<u32>().map_err(|_| bad())?))
    }

    /// (first bit of the first item, bits per item) of a group, from the
    /// first bit of its scope.
    fn group_span(p: &Pack, g: &GroupDef) -> Result<(u64, u64), Error> {
        let (word, pos) = parse_group_locator(&g.locator)?;
        Ok((word as u64 * p.word_bytes as u64 * 8 + pos as u64, g.item_bits.unwrap_or(1)))
    }

    /// (first message bit, bit length) of a locator.
    fn span(p: &Pack, loc: &str) -> Result<(u64, u32), Error> {
        let (word, pos, len) = parse_locator(loc)?;
        Ok((word as u64 * p.word_bytes as u64 * 8 + pos as u64, len))
    }

    /// Read `len` (1..=64) bits from message bit `start`. None when the range
    /// runs past the input. lsb: bit i is bit `i mod 8` of byte `i div 8`, first
    /// bit least significant. msb: bit i is bit `7 - (i mod 8)`, first bit most
    /// significant.
    pub(crate) fn get_bits(msg: &[u8], start: u64, len: u32, msb: bool) -> Option<u64> {
        if start + len as u64 > msg.len() as u64 * 8 {
            return None;
        }
        let mut v: u64 = 0;
        for k in 0..len as u64 {
            let bit = start + k;
            let byte = msg[(bit / 8) as usize];
            if msb {
                if byte & (0x80 >> (bit % 8)) != 0 {
                    v |= 1u64 << (len as u64 - 1 - k);
                }
            } else if byte & (1 << (bit % 8)) != 0 {
                v |= 1u64 << k;
            }
        }
        Some(v)
    }

    pub(crate) fn set_bits(msg: &mut [u8], start: u64, len: u32, raw: u64, msb: bool) {
        for k in 0..len as u64 {
            let bit = start + k;
            let idx = (bit / 8) as usize;
            if idx >= msg.len() {
                continue;
            }
            let (on, mask) = if msb {
                (raw & (1u64 << (len as u64 - 1 - k)) != 0, 0x80u8 >> (bit % 8))
            } else {
                (raw & (1u64 << k) != 0, 1u8 << (bit % 8))
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
    fn message_bytes(p: &Pack, sel: &Sel, all: bool) -> Result<usize, Error> {
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
        let word_bits = p.word_bytes as u64 * 8;
        let words = ((end + word_bits - 1) / word_bits).max(1);
        Ok(words as usize * p.word_bytes)
    }

    /// The low `len` bits of `raw` with their bytes in reverse order (`swap`).
    fn swap_bytes(raw: u64, len: u32) -> u64 {
        raw.swap_bytes() >> (64 - len)
    }

    /// The value of a field whose `len` bits start at message bit `start`,
    /// through its transform. The caller has checked the bits are in the input.
    pub(crate) fn read_field(p: &Pack, f: &FieldDef, raw: &[u8], start: u64, len: u32) -> Result<Value, Error> {
        if f.transform == Transform::Ascii {
            // bytes first to last, each byte's bits in the pack's bit order
            let mut bytes: Vec<u8> =
                (0..len as u64 / 8).map(|k| get_bits(raw, start + k * 8, 8, p.msb).unwrap_or(0) as u8).collect();
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
        } else {
            let mut rawv = get_bits(raw, start, len, p.msb).unwrap_or(0);
            if f.swap {
                rawv = swap_bytes(rawv, len);
            }
            f.transform.decode_bits(rawv, len)
        }
    }

    /// Write the wire value `v` of a field into its `len` bits at message bit `start`.
    pub(crate) fn write_field(p: &Pack, f: &FieldDef, v: &Value, start: u64, len: u32, msg: &mut [u8]) -> Result<(), Error> {
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
                set_bits(msg, start + k as u64 * 8, 8, *b as u64, p.msb);
            }
        } else {
            let mut rawv = f.transform.encode_bits(v, len).map_err(|e| transform_encode_err(p, f, e))?;
            if f.swap {
                rawv = swap_bytes(rawv, len);
            }
            set_bits(msg, start, len, rawv, p.msb);
        }
        Ok(())
    }

    fn short(p: &Pack, what: impl AsRef<str>) -> Error {
        Error { msg: format!("malformed-wire: format `{}`: {}", p.format, what.as_ref()) }
    }

    /// Decode the fields and groups of one scope: the message (`base` 0), or
    /// one item, whose first bit is `base`. `reach` is the furthest bit the
    /// message must hold.
    fn decode_scope(p: &Pack, sel: &Sel, raw: &[u8], base: u64, d: &mut Decoded, reach: &mut u64) -> Result<u64, Error> {
        let total = raw.len() as u64 * 8;
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
            d.put(p, f, read_field(p, f, raw, start, len));
        }
        // a group is always present, with `count` items
        for g in &sel.groups {
            let n = match &g.count {
                Some(Count::Fixed(n)) => *n,
                Some(Count::Locator(l)) => {
                    let (off, len) = span(p, l)?;
                    *reach = (*reach).max(base + off + len as u64);
                    get_bits(raw, base + off, len, p.msb)
                        .ok_or_else(|| short(p, format!("the input ends before the count of list `{}`", g.list)))?
                }
                None => 0,
            };
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
                let nested_end = decode_scope(p, &body, raw, at, &mut di, reach)?;
                at = (at + item_bits).max(nested_end);
                items.push(di);
            }
            *reach = (*reach).max(at);
            groups_end = groups_end.max(at);
            d.put_list(&g.list, items);
        }
        Ok(groups_end)
    }

    pub fn decode(p: &Pack, hex: &str) -> Result<Entity, Error> {
        let raw = from_hex(hex.trim()).map_err(|e| Error { msg: format!("malformed-wire: {}", e.msg) })?;
        if let Some(body) = &p.seq {
            return super::seq::decode(p, body, &raw);
        }
        // a `when` whose bits lie beyond the input does not hold
        let sel = p.select_decode(None, |w| match span(p, &w.locator) {
            Ok((start, len)) => get_bits(&raw, start, len, p.msb) == Some(w.num),
            Err(_) => false,
        })?;
        let words = |need: usize| {
            format!("input is {} bytes, need {} ({} words of {})", raw.len(), need, need / p.word_bytes, p.word_bytes)
        };
        let need = message_bytes(p, &sel, false)?;
        if raw.len() < need {
            return Err(short(p, words(need)));
        }
        let mut d = Decoded::new();
        let mut reach = 0u64;
        decode_scope(p, &sel, &raw, 0, &mut d, &mut reach)?;
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
    fn item_len(p: &Pack, g: &GroupDef, item: &Entity) -> Result<u64, Error> {
        let item_bits = g.item_bits.unwrap_or(1);
        Ok(item_bits.max(group_reach(p, &g.body(), item, 0)?))
    }

    /// The furthest bit the groups of a scope write: each count locator, and
    /// the items of each list the entity has.
    fn group_reach(p: &Pack, sel: &Sel, ent: &Entity, base: u64) -> Result<u64, Error> {
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
    fn write_scope(p: &Pack, sel: &Sel, ent: &Entity, base: u64, msg: &mut [u8]) -> Result<(), Error> {
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
                write_scope(p, &body, item, at, msg)?;
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
            set_bits(msg, base + off, len, w.num, p.msb);
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
            set_bits(msg, base + coff, len, n, p.msb);
        }
        Ok(())
    }

    pub fn encode(p: &Pack, ent: &Entity) -> Result<String, Error> {
        if let Some(body) = &p.seq {
            return super::seq::encode(p, body, ent).map(|b| to_hex(&b));
        }
        let sel = p.select_encode(ent)?;
        // whole words up to the furthest bit: the lines in force, extended by the items
        let word_bits = p.word_bytes as u64 * 8;
        let items = ((group_reach(p, &sel, ent, 0)? + word_bits - 1) / word_bits) as usize * p.word_bytes;
        let mut msg: Vec<u8> = vec![0u8; message_bytes(p, &sel, true)?.max(items)];
        write_scope(p, &sel, ent, 0, &mut msg)?;
        Ok(to_hex(&msg))
    }

    pub fn from_hex(s: &str) -> Result<Vec<u8>, Error> {
        let s: String = s.chars().filter(|c| !c.is_whitespace()).collect();
        if s.len() % 2 != 0 || !s.is_ascii() {
            return err("hex input has odd length");
        }
        (0..s.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|_| Error { msg: "bad hex".into() }))
            .collect()
    }

    pub fn to_hex(b: &[u8]) -> String {
        let mut s = String::with_capacity(b.len() * 2);
        for byte in b {
            s.push_str(&format!("{:02x}", byte));
        }
        s
    }
}

pub mod seq;

// ---------------------------------------------------------------------------
// protobuf codec: fields by number, dot-path for nested messages. I/O as hex.
// ---------------------------------------------------------------------------

pub mod protobuf {
    use super::*;
    use std::collections::BTreeMap;

    #[derive(Clone, Debug, PartialEq)]
    pub enum WireVal {
        Varint(u64),
        Fixed64(u64),
        LenDelim(Vec<u8>),
        Fixed32(u32),
    }
    impl WireVal {
        fn wire_type(&self) -> u8 {
            match self {
                WireVal::Varint(_) => 0,
                WireVal::Fixed64(_) => 1,
                WireVal::LenDelim(_) => 2,
                WireVal::Fixed32(_) => 5,
            }
        }
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
    fn get_varint(b: &[u8], i: &mut usize) -> Result<u64, Error> {
        let mut v: u64 = 0;
        let mut shift = 0;
        loop {
            if *i >= b.len() {
                return err("protobuf: truncated varint");
            }
            let byte = b[*i];
            *i += 1;
            v |= ((byte & 0x7f) as u64) << shift;
            if byte & 0x80 == 0 {
                return Ok(v);
            }
            shift += 7;
            if shift >= 64 {
                return err("protobuf: varint too long");
            }
        }
    }

    /// parse one message into (field number, value) pairs, in wire order.
    fn parse_msg(b: &[u8]) -> Result<Vec<(u32, WireVal)>, Error> {
        let mut out = Vec::new();
        let mut i = 0;
        while i < b.len() {
            let tag = get_varint(b, &mut i)?;
            let field = (tag >> 3) as u32;
            let wt = (tag & 7) as u8;
            let v = match wt {
                0 => WireVal::Varint(get_varint(b, &mut i)?),
                1 => {
                    if i + 8 > b.len() {
                        return err("protobuf: truncated fixed64");
                    }
                    let mut a = [0u8; 8];
                    a.copy_from_slice(&b[i..i + 8]);
                    i += 8;
                    WireVal::Fixed64(u64::from_le_bytes(a))
                }
                2 => {
                    let len = get_varint(b, &mut i)? as usize;
                    if i + len > b.len() {
                        return err("protobuf: truncated length-delimited");
                    }
                    let s = b[i..i + len].to_vec();
                    i += len;
                    WireVal::LenDelim(s)
                }
                5 => {
                    if i + 4 > b.len() {
                        return err("protobuf: truncated fixed32");
                    }
                    let mut a = [0u8; 4];
                    a.copy_from_slice(&b[i..i + 4]);
                    i += 4;
                    WireVal::Fixed32(u32::from_le_bytes(a))
                }
                other => return err(format!("protobuf: wire type {} unsupported", other)),
            };
            out.push((field, v));
        }
        Ok(out)
    }

    pub(crate) fn parse_path(locator: &str) -> Result<Vec<u32>, Error> {
        locator
            .split('.')
            .map(|s| s.parse::<u32>().map_err(|_| Error { msg: format!("bad protobuf path `{}`", locator) }))
            .collect()
    }

    /// resolve a dot-path to the leaf field value (last occurrence wins per field).
    fn resolve(b: &[u8], path: &[u32]) -> Result<Option<WireVal>, Error> {
        let fields = parse_msg(b)?;
        let want = path[0];
        let last = fields.iter().rev().find(|(f, _)| *f == want).map(|(_, v)| v);
        match (last, path.len()) {
            (None, _) => Ok(None),
            (Some(v), 1) => Ok(Some(v.clone())),
            (Some(WireVal::LenDelim(sub)), _) => resolve(sub, &path[1..]),
            // ruling 13 of 0.7
            (Some(_), _) => err(format!("malformed-wire: protobuf: path field {} is not a submessage", want)),
        }
    }

    fn numeric(t: &Transform) -> bool {
        matches!(t, Transform::Pvarint | Transform::Psint | Transform::Pdouble | Transform::Pfloat)
    }

    /// The values of a packed repeated field: one length-delimited occurrence
    /// holding the values back to back.
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
                    let v = get_varint(b, &mut i)
                        .map_err(|e| Error { msg: format!("malformed-wire: {} in a packed field", e.msg) })?;
                    out.push(WireVal::Varint(v));
                }
            }
        }
        Ok(out)
    }

    /// Decode the fields and groups of one scope: the message, or one item
    /// read as a submessage.
    fn decode_scope(p: &Pack, sel: &Sel, b: &[u8], d: &mut Decoded) -> Result<(), Error> {
        for f in sel.fields.iter().filter(|f| f.locator != ".") {
            let path = parse_path(&f.locator)?;
            if let Some(wv) = resolve(b, &path)? {
                d.put(p, f, f.transform.decode_pb(&wv));
            }
        }
        for g in &sel.groups {
            let path = parse_path(&g.locator)?;
            let (last, before) = path.split_last().ok_or(Error { msg: "empty protobuf path".into() })?;
            // the message that holds the items: the last occurrence of each step
            let mut holder: Vec<u8> = b.to_vec();
            let mut found = true;
            for step in before {
                match resolve(&holder, &[*step])? {
                    Some(WireVal::LenDelim(sub)) => holder = sub,
                    Some(_) => return err(format!("malformed-wire: protobuf: path field {} is not a submessage", step)),
                    None => {
                        found = false;
                        break;
                    }
                }
            }
            if !found {
                continue;
            }
            let body = g.body();
            // a `.` line with a numeric transform: an occurrence may be packed
            let packed = g.scalar().map(|f| &f.transform).filter(|t| numeric(t));
            let mut occurrences: Vec<WireVal> = Vec::new();
            for (field, v) in parse_msg(&holder)? {
                if field != *last {
                    continue;
                }
                match (&v, packed) {
                    (WireVal::LenDelim(bytes), Some(t)) => occurrences.extend(unpack(t, bytes)?),
                    _ => occurrences.push(v),
                }
            }
            // the list is present when at least one item occurs
            if occurrences.is_empty() {
                continue;
            }
            let into = body.fields.iter().any(|f| f.locator != ".") || !body.groups.is_empty();
            let mut items = Vec::new();
            for v in &occurrences {
                let mut di = Decoded::new();
                // `.`: the occurrence itself as a scalar
                for f in body.fields.iter().filter(|f| f.locator == ".") {
                    di.put(p, f, f.transform.decode_pb(v));
                }
                match v {
                    WireVal::LenDelim(sub) if into => decode_scope(p, &body, sub, &mut di)?,
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

    pub fn decode(p: &Pack, hex: &str) -> Result<Entity, Error> {
        let raw = super::bits::from_hex(hex.trim())?;
        if !p.kinds.is_empty() {
            parse_msg(&raw)?; // a malformed message is an error, not a kind mismatch
        }
        let sel = p.select_decode(None, |w| {
            let found = parse_path(&w.locator).and_then(|path| resolve(&raw, &path));
            match found {
                Ok(Some(v)) => w.present || v == WireVal::Varint(w.num),
                _ => false,
            }
        })?;
        let mut d = Decoded::new();
        decode_scope(p, &sel, &raw, &mut d)?;
        d.finish(p, &sel)
    }

    // build tree: a node is a leaf value, a submessage of ascending field
    // nodes, or the occurrences of a repeated field
    enum Node {
        Leaf(WireVal),
        Msg(BTreeMap<u32, Node>),
        Many(Vec<Node>),
    }
    fn insert(tree: &mut BTreeMap<u32, Node>, path: &[u32], v: WireVal) -> Result<(), Error> {
        insert_node(tree, path, Node::Leaf(v))
    }
    fn insert_node(tree: &mut BTreeMap<u32, Node>, path: &[u32], node: Node) -> Result<(), Error> {
        if path.len() == 1 {
            tree.insert(path[0], node);
            return Ok(());
        }
        let child = tree.entry(path[0]).or_insert_with(|| Node::Msg(BTreeMap::new()));
        match child {
            Node::Msg(m) => insert_node(m, &path[1..], node),
            _ => err(format!("protobuf: field {} is both a leaf and a submessage", path[0])),
        }
    }
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
    fn serialize(tree: &BTreeMap<u32, Node>) -> Vec<u8> {
        let mut out = Vec::new();
        for (field, node) in tree {
            write_node(*field, node, &mut out);
        }
        out
    }

    /// The tree one scope writes: the message, or one submessage item.
    fn build(p: &Pack, sel: &Sel, ent: &Entity) -> Result<BTreeMap<u32, Node>, Error> {
        let mut tree: BTreeMap<u32, Node> = BTreeMap::new();
        // later lines first: of two fields on one path the earlier line's value stays
        for f in sel.fields.iter().rev().filter(|f| f.locator != ".") {
            if let Some(v) = sel.value_of(ent, f) {
                let path = parse_path(&f.locator)?;
                let wv = p
                    .to_wire(f, v)
                    .and_then(|w| f.transform.encode_pb(&w))
                    .map_err(|e| transform_encode_err(p, f, e))?;
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
                match scalar {
                    Some((f, v)) => {
                        let wv = p
                            .to_wire(f, v)
                            .and_then(|w| f.transform.encode_pb(&w))
                            .map_err(|e| transform_encode_err(p, f, e))?;
                        wv.write(&mut packed);
                        nodes.push(Node::Leaf(wv));
                    }
                    // an item with nothing written is an empty length-delimited occurrence
                    None => nodes.push(Node::Msg(build(p, &body, item)?)),
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
            insert(&mut tree, &parse_path(&w.locator)?, WireVal::Varint(w.num))?;
        }
        Ok(tree)
    }

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
        } else if c.is_whitespace() {
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
        return err("unterminated quote in pack line");
    }
    if started {
        toks.push(cur);
    }
    Ok(toks)
}

fn req_arg(toks: &[String], i: usize, ln: usize) -> Result<String, Error> {
    toks.get(i)
        .cloned()
        .ok_or(Error { msg: format!("line {}: missing argument", ln) })
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
    let s = s.trim();
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
    let days = days_from_civil(year, mon, day);
    let secs = days * 86400 + hh * 3600 + mm * 60 + ss - offset_min * 60;
    Ok(secs * 1000 + frac_ms)
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
