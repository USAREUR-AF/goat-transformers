//! goat-adapters-zenoh: Zenoh as a source and a sink.
//!
//! Status: Written, not built. This file has not been compiled; see
//! README.md in this directory for why, and for what to check first.
//!
//! - As a source: a subscriber on one key expression. One sample is one
//!   unit for the framer; the default framing is `whole` (one sample, one
//!   message). A message's origin is the key the sample was published on.
//! - As a sink: one `put` per message on one key.
//!
//! URI: `zenoh:<key expression>[?config=<file>&mode=<peer|client>&connect=<endpoint>]`

use goat_adapters_core::frame::{frame_unit, Framer, Framing};
use goat_adapters_core::{AdapterError, Message, Meta, Recv, Sink, Source};
use goat_adapters_std::uri::{Scheme, Uri};
use std::collections::VecDeque;
use std::time::Duration;
use zenoh::Wait;

const POLL: Duration = Duration::from_millis(200);

fn zerr(what: &str, e: impl std::fmt::Display) -> AdapterError {
    AdapterError::fatal("zenoh", format!("{}: {}", what, e))
}

/// What a `zenoh:` URI states.
#[derive(Debug, Clone, PartialEq)]
pub struct Target {
    pub key: String,
    /// A Zenoh configuration file. Without one, the default configuration.
    pub config: Option<String>,
    pub mode: Option<String>,
    /// An endpoint to connect to, such as `tcp/192.0.2.1:7447`.
    pub connect: Option<String>,
}

impl Target {
    pub fn parse(uri: &Uri) -> Result<Target, AdapterError> {
        uri.allow(&["config", "mode", "connect"])?;
        if uri.body.is_empty() {
            return Err(uri.err("expected zenoh:<key expression>"));
        }
        if let Some(m) = uri.q("mode") {
            if m != "peer" && m != "client" {
                return Err(uri.err("mode is `peer` or `client`"));
            }
        }
        Ok(Target {
            key: uri.body.clone(),
            config: uri.q("config").map(|s| s.to_string()),
            mode: uri.q("mode").map(|s| s.to_string()),
            connect: uri.q("connect").map(|s| s.to_string()),
        })
    }

    fn open(&self) -> Result<zenoh::Session, AdapterError> {
        let mut config = match &self.config {
            Some(path) => zenoh::Config::from_file(path).map_err(|e| zerr(&format!("cannot read {}", path), e))?,
            None => zenoh::Config::default(),
        };
        if let Some(mode) = &self.mode {
            config.insert_json5("mode", &format!("\"{}\"", mode)).map_err(|e| zerr("mode", e))?;
        }
        if let Some(endpoint) = &self.connect {
            config.insert_json5("connect/endpoints", &format!("[\"{}\"]", endpoint)).map_err(|e| zerr("connect", e))?;
        }
        zenoh::open(config).wait().map_err(|e| zerr("cannot open a session", e))
    }
}

pub struct ZenohSource {
    name: String,
    // the subscriber is declared on the session and ends with it
    _session: zenoh::Session,
    subscriber: zenoh::pubsub::Subscriber<zenoh::handlers::FifoChannelHandler<zenoh::sample::Sample>>,
    framer: Box<dyn Framer>,
    ready: VecDeque<Message>,
    pending: Option<AdapterError>,
}

impl ZenohSource {
    pub fn open(t: &Target, framing: &Framing) -> Result<ZenohSource, AdapterError> {
        let session = t.open()?;
        // The subscriber's channel is Zenoh's default FIFO, which has a fixed
        // capacity: a pipeline slower than the publishers makes the session
        // apply the publishers' congestion control, it does not grow a queue here.
        let subscriber = session.declare_subscriber(&t.key).wait().map_err(|e| zerr(&format!("cannot subscribe to {}", t.key), e))?;
        Ok(ZenohSource { name: format!("zenoh:{}", t.key), _session: session, subscriber, framer: framing.build(), ready: VecDeque::new(), pending: None })
    }
}

impl Source for ZenohSource {
    fn recv(&mut self) -> Result<Recv, AdapterError> {
        loop {
            if let Some(m) = self.ready.pop_front() {
                return Ok(Recv::Message(m));
            }
            if let Some(e) = self.pending.take() {
                return Err(e);
            }
            match self.subscriber.recv_timeout(POLL) {
                Ok(Some(sample)) => {
                    let key = sample.key_expr().as_str().to_string();
                    let payload = sample.payload().to_bytes();
                    let (msgs, err) = frame_unit(self.framer.as_mut(), &payload);
                    self.ready.extend(msgs.into_iter().map(|m| Message::now(m, Some(key.clone()))));
                    self.pending = err.map(|e| AdapterError::new(&e.kind, format!("{} (sample on {})", e.msg, key)));
                }
                Ok(None) => return Ok(Recv::Idle),
                Err(e) => return Err(zerr("the subscriber closed", e)),
            }
        }
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

pub struct ZenohSink {
    name: String,
    session: zenoh::Session,
    key: String,
    framer: Box<dyn Framer>,
    out: Vec<u8>,
}

impl ZenohSink {
    pub fn open(t: &Target, framing: &Framing) -> Result<ZenohSink, AdapterError> {
        if t.key.contains('*') {
            return Err(AdapterError::fatal("bad-uri", format!("`{}`: a key to publish on has no wildcard", t.key)));
        }
        Ok(ZenohSink { name: format!("zenoh:{}", t.key), session: t.open()?, key: t.key.clone(), framer: framing.build(), out: Vec::new() })
    }
}

impl Sink for ZenohSink {
    fn send(&mut self, bytes: &[u8], _meta: &Meta) -> Result<(), AdapterError> {
        self.out.clear();
        self.framer.wrap(bytes, &mut self.out)?;
        self.session.put(&self.key, self.out.as_slice()).wait().map_err(|e| AdapterError::new("zenoh", format!("put on {}: {}", self.key, e)))
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

/// The `zenoh:` scheme for the command line.
pub struct Zenoh;

impl Scheme for Zenoh {
    fn name(&self) -> &'static str {
        "zenoh"
    }
    fn help(&self) -> &'static str {
        "zenoh:<key expression>[?config=<file>&mode=<peer|client>&connect=<endpoint>]\n  As --in the key expression may hold wildcards. One sample is one message unless a framing is stated."
    }
    fn source(&self, uri: &Uri, frame: Option<&Framing>) -> Result<Box<dyn Source>, AdapterError> {
        Ok(Box::new(ZenohSource::open(&Target::parse(uri)?, frame.unwrap_or(&Framing::whole()))?))
    }
    fn sink(&self, uri: &Uri, frame: Option<&Framing>) -> Result<Box<dyn Sink>, AdapterError> {
        Ok(Box::new(ZenohSink::open(&Target::parse(uri)?, frame.unwrap_or(&Framing::whole()))?))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_uri_states_the_key_and_the_session_options() {
        let t = Target::parse(&Uri::parse("zenoh:tracks/**?mode=client&connect=tcp/192.0.2.1:7447").unwrap()).unwrap();
        assert_eq!((t.key.as_str(), t.mode.as_deref(), t.connect.as_deref()), ("tracks/**", Some("client"), Some("tcp/192.0.2.1:7447")));
        assert_eq!(Target::parse(&Uri::parse("zenoh:").unwrap()).unwrap_err().kind, "bad-uri");
        assert_eq!(Target::parse(&Uri::parse("zenoh:a?mode=router").unwrap()).unwrap_err().kind, "bad-uri");
    }

    /// Two sessions in this process, in peer mode with multicast scouting:
    /// what one puts, the other receives.
    #[test]
    fn a_put_reaches_a_subscriber() {
        let key = "goat-adapters-test/a";
        let mut src = ZenohSource::open(&Target::parse(&Uri::parse(&format!("zenoh:{}", key)).unwrap()).unwrap(), &Framing::whole()).unwrap();
        let mut sink = ZenohSink::open(&Target::parse(&Uri::parse(&format!("zenoh:{}", key)).unwrap()).unwrap(), &Framing::whole()).unwrap();
        let until = std::time::Instant::now() + Duration::from_secs(20);
        loop {
            sink.send(b"hello", &Meta { seq: 1, origin: None }).unwrap();
            match src.recv().unwrap() {
                Recv::Message(m) => {
                    assert_eq!(m.bytes, b"hello");
                    assert_eq!(m.origin.as_deref(), Some(key));
                    break;
                }
                _ => assert!(std::time::Instant::now() < until, "nothing arrived"),
            }
        }
    }
}
