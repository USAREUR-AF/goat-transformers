//! goat-adapters-core: what a transport adapter is.
//!
//! The engine converts one message, given as text, to one message, given as
//! text. Everything about where a message comes from, how one message is
//! told from the next on a stream, and where the result goes is here and in
//! the adapter crates, never in the engine.
//!
//! - [`Source`] yields framed messages, one at a time.
//! - [`Sink`] accepts one converted message.
//! - [`frame::Framer`] states how one message is delimited on a stream.
//! - [`pipeline::Pipeline`] wires source -> engine -> sinks and counts.
//!
//! Standard library only.

pub mod frame;
pub mod pipeline;

/// The engine, so that an adapter crate names one dependency.
pub use goat_transformers as engine;

use std::fmt;

/// A failure of an adapter or a framer. `kind` is a short stable name that
/// the pipeline counts by, in the style of the engine's named errors.
#[derive(Debug, Clone, PartialEq)]
pub struct AdapterError {
    pub kind: String,
    pub msg: String,
    /// The source or sink cannot continue after this error.
    pub fatal: bool,
}

impl AdapterError {
    pub fn new(kind: &str, msg: impl Into<String>) -> AdapterError {
        AdapterError { kind: kind.to_string(), msg: msg.into(), fatal: false }
    }
    pub fn fatal(kind: &str, msg: impl Into<String>) -> AdapterError {
        AdapterError { kind: kind.to_string(), msg: msg.into(), fatal: true }
    }
    pub fn io(what: &str, e: std::io::Error) -> AdapterError {
        AdapterError::fatal("io", format!("{}: {}", what, e))
    }
}

impl fmt::Display for AdapterError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.kind, self.msg)
    }
}
impl std::error::Error for AdapterError {}

/// One framed message from a source.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Message {
    /// The bytes of exactly one message, without its framing.
    pub bytes: Vec<u8>,
    /// When the adapter received it, epoch milliseconds UTC.
    pub received_ms: Option<i64>,
    /// Where it came from, for reports and for output naming: a peer
    /// address, a file name, a topic.
    pub origin: Option<String>,
    /// Model keys only this adapter knows, as text (the engine's context).
    pub context: Vec<(String, String)>,
}

impl Message {
    /// A message received now.
    pub fn now(bytes: Vec<u8>, origin: Option<String>) -> Message {
        Message { bytes, received_ms: Some(now_ms()), origin, context: Vec::new() }
    }
}

/// The current time, epoch milliseconds UTC.
pub fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

/// What one call to [`Source::recv`] produced.
#[derive(Debug)]
pub enum Recv {
    Message(Message),
    /// Nothing arrived within the source's own short timeout. The pipeline
    /// calls again; this is how a waiting source lets the pipeline stop.
    Idle,
    /// The source has ended (end of file, peer closed).
    End,
}

/// Where messages arrive. A source holds no queue of its own beyond the
/// messages of the one read it has just made.
pub trait Source: Send {
    fn recv(&mut self) -> Result<Recv, AdapterError>;
    /// A short name for reports, such as `udp://:4242`.
    fn describe(&self) -> String;
}

/// What a sink is told about the message it is given.
#[derive(Debug, Clone, Copy)]
pub struct Meta<'a> {
    /// The count of this message at the source, from 1.
    pub seq: u64,
    pub origin: Option<&'a str>,
}

/// Where converted messages leave. `send` is given one message without
/// framing and returns when the transport has taken it; a sink that cannot
/// deliver returns an error and the pipeline counts it.
pub trait Sink: Send {
    fn send(&mut self, bytes: &[u8], meta: &Meta) -> Result<(), AdapterError>;
    fn flush(&mut self) -> Result<(), AdapterError> {
        Ok(())
    }
    fn describe(&self) -> String;
}
