//! gt-core: the goat-transformers device engine.
//!
//! Runs packs compiled ahead of time by `tools/gen/packc.py` to the binary
//! form of `embedded/FORMAT.md`. No standard library, no allocator, no
//! dependency, no `unsafe`. The caller provides every buffer; no input makes
//! the engine panic.
//!
//! This is a second execution form of the Rust reference engine
//! (`engines/rust`), written with that engine's source open, not an
//! independently written engine. Its results are checked byte for byte
//! against the reference (`embedded/gt-proof`).
//!
//! ```ignore
//! static PLAN: [u8; 812] = [/* written by packc.py */];
//!
//! let plan = gt_core::Plan::parse(&PLAN)?;
//! let mut scratch = gt_core::Scratch::<32>::new();
//! let mut out = [0u8; 64];
//! let n = gt_core::convert(&plan, message, &mut out, &mut scratch, &[])?;
//! ```
#![no_std]
#![forbid(unsafe_code)]

#[cfg(feature = "alloc")]
extern crate alloc;

mod engine;
pub mod num;
mod plan;

pub use engine::{Got, Scope, Scratch, Session, TextRef, MAX_ARGS, MAX_DEPTH, MAX_PRESENCE, MAX_WHOLES, ROOT};
pub use plan::{Carry, Plan, FORMAT_VERSION};

/// A model key of a compiled plan: its index in the plan's key table. The
/// compiler writes the ids of the context keys into the generated source.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct KeyId(pub u16);

/// A value the caller supplies for a context key.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Value<'a> {
    Int(i64),
    Float(f64),
    /// text, as bytes
    Str(&'a [u8]),
}

/// Why a conversion failed. The first six are the named error kinds of
/// `spec/engine-spec.md`; the last three belong to the device profile.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Error {
    /// `no-kind`: the message, or the values, select no kind the plan holds
    NoKind,
    /// `malformed-wire`: the input is shorter than its layout, or states a
    /// length or a presence the pack does not describe
    MalformedWire,
    /// `transform-decode`: a field's bits are not a value of its transform
    TransformDecode,
    /// `transform-encode`: a value does not fit its field, table or group
    TransformEncode,
    /// `undeclared-key`: a context key the plan was not compiled with
    UndeclaredKey,
    /// `key-type-mismatch`: a context value of another type than its key
    KeyTypeMismatch,
    /// the output buffer is shorter than the message
    OutputFull,
    /// the message holds more values or list items than the scratch
    ScratchFull,
    /// the blob is not a plan this engine reads, or names a function the
    /// engine was built without
    BadPlan,
}

impl Error {
    /// The error kind as the specification names it.
    pub const fn name(self) -> &'static str {
        match self {
            Error::NoKind => "no-kind",
            Error::MalformedWire => "malformed-wire",
            Error::TransformDecode => "transform-decode",
            Error::TransformEncode => "transform-encode",
            Error::UndeclaredKey => "undeclared-key",
            Error::KeyTypeMismatch => "key-type-mismatch",
            Error::OutputFull => "output-full",
            Error::ScratchFull => "scratch-full",
            Error::BadPlan => "bad-plan",
        }
    }
}

/// Convert one message: decode `input` as the plan's source format, set the
/// context keys the message lacks, apply the plan's derivations, and write
/// the target format into `out`. Returns the number of bytes written.
///
/// An empty `context` is "no context": a same-format plan then returns the
/// canonical form of the input without deriving. Use `convert_with` to pass
/// an empty context that counts as given (ruling 10 of engine-spec 0.6).
pub fn convert<'a, const N: usize>(
    plan: &'a Plan<'a>,
    input: &'a [u8],
    out: &mut [u8],
    scratch: &mut Scratch<N>,
    context: &'a [(KeyId, Value<'a>)],
) -> Result<usize, Error> {
    convert_with(plan, input, out, scratch, if context.is_empty() { None } else { Some(context) })
}

/// `convert` with the context optional, as the reference engine takes it.
pub fn convert_with<'a, const N: usize>(
    plan: &'a Plan<'a>,
    input: &'a [u8],
    out: &mut [u8],
    scratch: &mut Scratch<N>,
    context: Option<&'a [(KeyId, Value<'a>)]>,
) -> Result<usize, Error> {
    let mut s = Session::new(plan, scratch);
    s.decode(input)?;
    // engine-spec 0.6, "Order inside convert": with `from == to` and no
    // context the middle steps are skipped
    if !plan.is_same_format() || context.is_some() {
        s.fill(context.unwrap_or(&[]))?;
        s.complete()?;
    }
    s.encode(out)
}

/// `convert` into a new `Vec`, growing it until the message fits.
#[cfg(feature = "alloc")]
pub fn convert_to_vec<'a, const N: usize>(
    plan: &'a Plan<'a>,
    input: &'a [u8],
    scratch: &mut Scratch<N>,
    context: &'a [(KeyId, Value<'a>)],
) -> Result<alloc::vec::Vec<u8>, Error> {
    let mut out = alloc::vec![0u8; 64];
    loop {
        match convert(plan, input, &mut out, scratch, context) {
            Ok(n) => {
                out.truncate(n);
                return Ok(out);
            }
            Err(Error::OutputFull) if out.len() < (1 << 24) => {
                let grown = out.len() * 4;
                out.resize(grown, 0);
            }
            Err(e) => return Err(e),
        }
    }
}
