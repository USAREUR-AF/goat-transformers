//! goat-adapters-mqtt: MQTT as a source and a sink.
//!
//! MQTT 3.1.1 (OASIS Standard, 29 October 2014), written from that
//! specification with the standard library only. What is implemented is the
//! part a one-way message pipe needs:
//!
//! - CONNECT with a clean session, optional user name and password
//! - SUBSCRIBE to one topic filter at QoS 0 (source)
//! - PUBLISH at QoS 0 (sink), not retained
//! - PINGREQ to keep a subscription's connection alive
//!
//! Not implemented: TLS (the standard library has none), QoS 1 and 2,
//! retained messages, wills, session resumption, MQTT 5, reconnection.
//!
//! One publication is one unit for the framer. The default framing is
//! `whole`: one publication, one message.

use goat_adapters_core::frame::{frame_unit, Framer, Framing};
use goat_adapters_core::{AdapterError, Message, Meta, Recv, Sink, Source};
use goat_adapters_std::uri::{Scheme, Uri};
use std::collections::VecDeque;
use std::io::{ErrorKind, Read, Write};
use std::net::TcpStream;
use std::time::{Duration, Instant};

const POLL: Duration = Duration::from_millis(200);
const HANDSHAKE: Duration = Duration::from_secs(10);
pub const DEFAULT_PORT: u16 = 1883;
pub const DEFAULT_KEEPALIVE: u16 = 60;

const CONNECT: u8 = 0x10;
const CONNACK: u8 = 0x20;
const PUBLISH: u8 = 0x30;
const SUBSCRIBE: u8 = 0x82;
const SUBACK: u8 = 0x90;
const PINGREQ: u8 = 0xc0;
const PINGRESP: u8 = 0xd0;
const DISCONNECT: u8 = 0xe0;

fn proto(msg: impl Into<String>) -> AdapterError {
    AdapterError::fatal("mqtt-protocol", msg)
}

// ---------------------------------------------------------------------------
// Packets (MQTT 3.1.1 section 2 and 3)
// ---------------------------------------------------------------------------

fn put_str(out: &mut Vec<u8>, s: &[u8]) -> Result<(), AdapterError> {
    let n = u16::try_from(s.len()).map_err(|_| AdapterError::new("mqtt-protocol", "a string of more than 65535 bytes"))?;
    out.extend_from_slice(&n.to_be_bytes());
    out.extend_from_slice(s);
    Ok(())
}

/// A packet: the first byte, the remaining length (section 2.2.3), the body.
pub fn packet(first: u8, body: &[u8]) -> Result<Vec<u8>, AdapterError> {
    if body.len() > 268_435_455 {
        return Err(AdapterError::new("mqtt-protocol", "a packet of more than 268,435,455 bytes"));
    }
    let mut out = vec![first];
    let mut n = body.len();
    loop {
        let b = (n % 128) as u8;
        n /= 128;
        out.push(if n > 0 { b | 0x80 } else { b });
        if n == 0 {
            break;
        }
    }
    out.extend_from_slice(body);
    Ok(out)
}

pub fn connect_packet(client: &str, user: Option<&str>, password: Option<&str>, keepalive: u16) -> Result<Vec<u8>, AdapterError> {
    let mut b = Vec::new();
    put_str(&mut b, b"MQTT")?;
    b.push(4); // protocol level: 3.1.1
    let mut flags = 0x02; // clean session
    if user.is_some() {
        flags |= 0x80;
    }
    if password.is_some() {
        flags |= 0x40;
    }
    b.push(flags);
    b.extend_from_slice(&keepalive.to_be_bytes());
    put_str(&mut b, client.as_bytes())?;
    if let Some(u) = user {
        put_str(&mut b, u.as_bytes())?;
    }
    if let Some(p) = password {
        put_str(&mut b, p.as_bytes())?;
    }
    packet(CONNECT, &b)
}

pub fn subscribe_packet(id: u16, filter: &str) -> Result<Vec<u8>, AdapterError> {
    let mut b = id.to_be_bytes().to_vec();
    put_str(&mut b, filter.as_bytes())?;
    b.push(0); // requested QoS 0
    packet(SUBSCRIBE, &b)
}

pub fn publish_packet(topic: &str, payload: &[u8]) -> Result<Vec<u8>, AdapterError> {
    let mut b = Vec::with_capacity(2 + topic.len() + payload.len());
    put_str(&mut b, topic.as_bytes())?;
    b.extend_from_slice(payload);
    packet(PUBLISH, &b)
}

/// The first packet in `buf`, if all of it is there: its first byte, where
/// its body begins, and its whole length.
pub fn split_packet(buf: &[u8], max: usize) -> Result<Option<(u8, usize, usize)>, AdapterError> {
    if buf.len() < 2 {
        return Ok(None);
    }
    let (mut len, mut shift, mut i) = (0usize, 0, 1);
    loop {
        let Some(b) = buf.get(i) else { return Ok(None) };
        len |= ((b & 0x7f) as usize) << shift;
        i += 1;
        if b & 0x80 == 0 {
            break;
        }
        shift += 7;
        if shift > 21 {
            return Err(proto("a remaining length of more than four bytes"));
        }
    }
    if len > max {
        return Err(AdapterError::fatal("frame-oversize", format!("an MQTT packet of {} bytes exceeds the maximum of {}", len, max)));
    }
    Ok(if buf.len() >= i + len { Some((buf[0], i, i + len)) } else { None })
}

/// The topic and payload of a PUBLISH body at QoS 0.
pub fn split_publish(first: u8, body: &[u8]) -> Result<(&str, &[u8]), AdapterError> {
    if first & 0x06 != 0 {
        return Err(proto("a publication above QoS 0 on a QoS 0 subscription"));
    }
    let n = match body {
        [a, b, ..] => u16::from_be_bytes([*a, *b]) as usize,
        _ => return Err(proto("a publication with no topic")),
    };
    let topic = body.get(2..2 + n).ok_or_else(|| proto("a publication cut inside its topic"))?;
    let topic = std::str::from_utf8(topic).map_err(|_| proto("a topic that is not UTF-8"))?;
    Ok((topic, &body[2 + n..]))
}

// ---------------------------------------------------------------------------
// The connection
// ---------------------------------------------------------------------------

/// What `mqtt://host[:port]/topic?options` states.
#[derive(Debug, Clone, PartialEq)]
pub struct Target {
    pub host: String,
    pub port: u16,
    pub topic: String,
    pub client: String,
    pub user: Option<String>,
    /// The name of the environment variable that holds the password. A
    /// password is never written in a URI.
    pub password_env: Option<String>,
    pub keepalive: u16,
}

impl Target {
    pub fn parse(uri: &Uri) -> Result<Target, AdapterError> {
        uri.allow(&["client", "user", "password-env", "keepalive"])?;
        let (authority, topic) = uri.body.split_once('/').ok_or_else(|| uri.err("expected mqtt://<host>[:<port>]/<topic>"))?;
        if topic.is_empty() {
            return Err(uri.err("the topic is empty"));
        }
        let (host, port) = match authority.rsplit_once(':') {
            Some((h, p)) => (h, p.parse::<u16>().map_err(|_| uri.err(format!("`{}` is not a port", p)))?),
            None => (authority, DEFAULT_PORT),
        };
        if host.is_empty() {
            return Err(uri.err("the broker host is empty"));
        }
        let keepalive = match uri.q("keepalive") {
            Some(k) => k.parse::<u16>().ok().filter(|k| *k > 0).ok_or_else(|| uri.err("keepalive is 1 to 65535 seconds"))?,
            None => DEFAULT_KEEPALIVE,
        };
        let client = match uri.q("client") {
            Some(c) => c.to_string(),
            // at most 23 characters, which every broker accepts (section 3.1.3.1)
            None => format!("gxf{:x}{:06x}", std::process::id(), goat_adapters_core::now_ms() & 0xff_ffff),
        };
        Ok(Target {
            host: host.to_string(),
            port,
            topic: topic.to_string(),
            client,
            user: uri.q("user").map(|s| s.to_string()),
            password_env: uri.q("password-env").map(|s| s.to_string()),
            keepalive,
        })
    }
    fn name(&self) -> String {
        format!("mqtt://{}:{}/{}", self.host, self.port, self.topic)
    }
}

struct Conn {
    stream: TcpStream,
    buf: Vec<u8>,
    max: usize,
    name: String,
}

impl Conn {
    /// Connect and complete the CONNECT / CONNACK exchange.
    fn open(t: &Target, keepalive: u16, max: usize) -> Result<Conn, AdapterError> {
        let name = t.name();
        let password = match &t.password_env {
            Some(var) => Some(std::env::var(var).map_err(|_| AdapterError::fatal("bad-uri", format!("the environment variable `{}` is not set", var)))?),
            None => None,
        };
        let stream = TcpStream::connect((t.host.as_str(), t.port)).map_err(|e| AdapterError::io(&format!("cannot connect to {}", name), e))?;
        let _ = stream.set_nodelay(true);
        let mut c = Conn { stream, buf: Vec::new(), max, name };
        c.send(&connect_packet(&t.client, t.user.as_deref(), password.as_deref(), keepalive)?)?;
        match c.expect(CONNACK)?.as_slice() {
            [_, 0] => Ok(c),
            [_, code] => Err(AdapterError::fatal("mqtt-refused", format!("{} refused the connection with return code {}", c.name, code))),
            _ => Err(proto("a CONNACK that is not two bytes")),
        }
    }

    fn send(&mut self, packet: &[u8]) -> Result<(), AdapterError> {
        self.stream.write_all(packet).map_err(|e| AdapterError::io(&format!("write to {}", self.name), e))
    }

    /// The next packet, or `None` when none arrived within `wait`.
    fn read(&mut self, wait: Duration) -> Result<Option<(u8, Vec<u8>)>, AdapterError> {
        self.stream.set_read_timeout(Some(wait)).map_err(|e| AdapterError::io("set_read_timeout", e))?;
        let mut chunk = [0u8; 16 * 1024];
        loop {
            if let Some((first, body, end)) = split_packet(&self.buf, self.max)? {
                let p = self.buf[body..end].to_vec();
                self.buf.drain(..end);
                return Ok(Some((first, p)));
            }
            match self.stream.read(&mut chunk) {
                Ok(0) => return Err(AdapterError::fatal("io", format!("{} closed the connection", self.name))),
                Ok(n) => self.buf.extend_from_slice(&chunk[..n]),
                Err(e) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => return Ok(None),
                Err(e) if e.kind() == ErrorKind::Interrupted => {}
                Err(e) => return Err(AdapterError::io(&format!("read from {}", self.name), e)),
            }
        }
    }

    /// The reply to a request: the next packet must be of this type.
    fn expect(&mut self, want: u8) -> Result<Vec<u8>, AdapterError> {
        match self.read(HANDSHAKE)? {
            Some((first, body)) if first & 0xf0 == want => Ok(body),
            Some((first, _)) => Err(proto(format!("expected packet type {:#04x} from {}, got {:#04x}", want, self.name, first))),
            None => Err(AdapterError::fatal("mqtt-timeout", format!("{} did not answer within {} seconds", self.name, HANDSHAKE.as_secs()))),
        }
    }
}

// ---------------------------------------------------------------------------
// Source and sink
// ---------------------------------------------------------------------------

pub struct MqttSource {
    conn: Conn,
    framer: Box<dyn Framer>,
    ready: VecDeque<Message>,
    pending: Option<AdapterError>,
    keepalive: Duration,
    last_sent: Instant,
    last_heard: Instant,
}

impl MqttSource {
    /// Connect and subscribe to the topic filter at QoS 0.
    pub fn open(t: &Target, framing: &Framing) -> Result<MqttSource, AdapterError> {
        // room for the topic and its length beside the largest message
        let mut conn = Conn::open(t, t.keepalive, framing.max.saturating_add(2 + 65535))?;
        conn.send(&subscribe_packet(1, &t.topic)?)?;
        match conn.expect(SUBACK)?.as_slice() {
            [0, 1, 0] => {}
            [0, 1, code] => return Err(AdapterError::fatal("mqtt-refused", format!("{} refused the subscription with return code {:#04x}", conn.name, code))),
            _ => return Err(proto("a SUBACK that does not answer the subscription")),
        }
        let now = Instant::now();
        Ok(MqttSource {
            conn,
            framer: framing.build(),
            ready: VecDeque::new(),
            pending: None,
            keepalive: Duration::from_secs(t.keepalive as u64),
            last_sent: now,
            last_heard: now,
        })
    }
}

impl Source for MqttSource {
    fn recv(&mut self) -> Result<Recv, AdapterError> {
        loop {
            if let Some(m) = self.ready.pop_front() {
                return Ok(Recv::Message(m));
            }
            if let Some(e) = self.pending.take() {
                return Err(e);
            }
            if self.last_sent.elapsed() >= self.keepalive / 2 {
                self.conn.send(&[PINGREQ, 0])?;
                self.last_sent = Instant::now();
            }
            if self.last_heard.elapsed() >= self.keepalive * 2 {
                return Err(AdapterError::fatal("mqtt-timeout", format!("nothing from {} for {} seconds", self.conn.name, self.last_heard.elapsed().as_secs())));
            }
            let Some((first, body)) = self.conn.read(POLL)? else { return Ok(Recv::Idle) };
            self.last_heard = Instant::now();
            match first & 0xf0 {
                PUBLISH => {
                    let (topic, payload) = split_publish(first, &body)?;
                    let (msgs, err) = frame_unit(self.framer.as_mut(), payload);
                    self.ready.extend(msgs.into_iter().map(|m| Message::now(m, Some(topic.to_string()))));
                    self.pending = err.map(|e| AdapterError::new(&e.kind, format!("{} (publication on {})", e.msg, topic)));
                }
                PINGRESP => {}
                other => return Err(proto(format!("unexpected packet type {:#04x} from {}", other, self.conn.name))),
            }
        }
    }
    fn describe(&self) -> String {
        self.conn.name.clone()
    }
}

/// One message is one publication at QoS 0: the broker does not confirm it.
pub struct MqttSink {
    conn: Conn,
    topic: String,
    framer: Box<dyn Framer>,
    out: Vec<u8>,
}

impl MqttSink {
    pub fn open(t: &Target, framing: &Framing) -> Result<MqttSink, AdapterError> {
        if t.topic.contains('#') || t.topic.contains('+') {
            return Err(AdapterError::fatal("bad-uri", format!("`{}`: a topic to publish on has no wildcard", t.topic)));
        }
        // keep-alive 0: a sink sends only when there is a message, so the
        // broker must not expect a packet within any interval (section 3.1.2.10)
        let conn = Conn::open(t, 0, 1024)?;
        Ok(MqttSink { conn, topic: t.topic.clone(), framer: framing.build(), out: Vec::new() })
    }
}

impl Sink for MqttSink {
    fn send(&mut self, bytes: &[u8], _meta: &Meta) -> Result<(), AdapterError> {
        self.out.clear();
        self.framer.wrap(bytes, &mut self.out)?;
        let p = publish_packet(&self.topic, &self.out)?;
        self.conn.send(&p)
    }
    fn flush(&mut self) -> Result<(), AdapterError> {
        self.conn.stream.flush().map_err(|e| AdapterError::io("flush", e))
    }
    fn describe(&self) -> String {
        self.conn.name.clone()
    }
}

impl Drop for MqttSink {
    fn drop(&mut self) {
        let _ = self.conn.stream.write_all(&[DISCONNECT, 0]);
    }
}
impl Drop for MqttSource {
    fn drop(&mut self) {
        let _ = self.conn.stream.write_all(&[DISCONNECT, 0]);
    }
}

/// The `mqtt://` scheme for the command line.
pub struct Mqtt;

impl Scheme for Mqtt {
    fn name(&self) -> &'static str {
        "mqtt"
    }
    fn help(&self) -> &'static str {
        "mqtt://<host>[:<port>]/<topic>[?client=<id>&user=<name>&password-env=<VARIABLE>&keepalive=<seconds>]\n  MQTT 3.1.1, QoS 0, plain TCP. As --in the topic is a filter (+ and # allowed). One publication is one message unless a framing is stated."
    }
    fn source(&self, uri: &Uri, frame: Option<&Framing>) -> Result<Box<dyn Source>, AdapterError> {
        Ok(Box::new(MqttSource::open(&Target::parse(uri)?, frame.unwrap_or(&Framing::whole()))?))
    }
    fn sink(&self, uri: &Uri, frame: Option<&Framing>) -> Result<Box<dyn Sink>, AdapterError> {
        Ok(Box::new(MqttSink::open(&Target::parse(uri)?, frame.unwrap_or(&Framing::whole()))?))
    }
}

#[cfg(test)]
mod tests;
