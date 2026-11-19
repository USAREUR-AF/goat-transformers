//! The sources and sinks.
//!
//! None of them holds a queue. A source keeps only the messages of the one
//! read it has just made (a read is at most 64 KiB), and a framer keeps at
//! most one message of its stated maximum size.

use goat_adapters_core::frame::{frame_unit, Framer, Framing};
use goat_adapters_core::{AdapterError, Message, Meta, Recv, Sink, Source};
use std::collections::VecDeque;
use std::fs::File;
use std::io::{ErrorKind, Read, Write};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, TcpListener, TcpStream, ToSocketAddrs, UdpSocket};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// How long a waiting source waits before it reports `Idle`.
const POLL: Duration = Duration::from_millis(200);
/// One read.
const CHUNK: usize = 64 * 1024;
/// The most connections a listener holds at once.
pub const MAX_CONNECTIONS: usize = 64;
/// How long a write to one TCP listener client may take before the client is dropped.
const CLIENT_WRITE_TIMEOUT: Duration = Duration::from_secs(5);

fn waiting(e: &std::io::Error) -> bool {
    matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut)
}
fn listen_host(host: &str) -> &str {
    if host.is_empty() {
        "0.0.0.0"
    } else {
        host
    }
}

// ---------------------------------------------------------------------------
// A byte stream read to its end: stdin, a file, a TCP connection, a serial port
// ---------------------------------------------------------------------------

pub struct ReadSource<R: Read + Send> {
    r: R,
    framer: Box<dyn Framer>,
    buf: Vec<u8>,
    eof: bool,
    name: String,
    origin: Option<String>,
}

impl<R: Read + Send> ReadSource<R> {
    pub fn new(r: R, framing: &Framing, name: &str, origin: Option<String>) -> ReadSource<R> {
        ReadSource { r, framer: framing.build(), buf: vec![0u8; CHUNK], eof: false, name: name.to_string(), origin }
    }
}
impl ReadSource<std::io::Stdin> {
    pub fn stdin(framing: &Framing) -> Self {
        ReadSource::new(std::io::stdin(), framing, "stdin:", None)
    }
}
impl ReadSource<File> {
    pub fn file(path: &str, framing: &Framing) -> Result<Self, AdapterError> {
        let f = File::open(path).map_err(|e| AdapterError::io(&format!("cannot open {}", path), e))?;
        Ok(ReadSource::new(f, framing, &format!("file:{}", path), Some(path.to_string())))
    }
    /// A serial port, opened as a device file. The line settings (speed,
    /// parity, raw mode) are set outside, for example with `stty`.
    pub fn serial(path: &str, framing: &Framing) -> Result<Self, AdapterError> {
        let f = File::open(path).map_err(|e| AdapterError::io(&format!("cannot open {}", path), e))?;
        Ok(ReadSource::new(f, framing, &format!("serial:{}", path), Some(path.to_string())))
    }
}
impl ReadSource<TcpStream> {
    pub fn tcp(host: &str, port: u16, framing: &Framing) -> Result<Self, AdapterError> {
        let name = format!("tcp://{}:{}", host, port);
        let s = TcpStream::connect((host, port)).map_err(|e| AdapterError::io(&format!("cannot connect to {}", name), e))?;
        s.set_read_timeout(Some(POLL)).map_err(|e| AdapterError::io("set_read_timeout", e))?;
        Ok(ReadSource::new(s, framing, &name, Some(name.clone())))
    }
}

impl<R: Read + Send> Source for ReadSource<R> {
    fn recv(&mut self) -> Result<Recv, AdapterError> {
        loop {
            if let Some(m) = self.framer.next()? {
                return Ok(Recv::Message(Message::now(m, self.origin.clone())));
            }
            if self.eof {
                return Ok(match self.framer.finish()? {
                    Some(m) => Recv::Message(Message::now(m, self.origin.clone())),
                    None => Recv::End,
                });
            }
            match self.r.read(&mut self.buf) {
                Ok(0) => self.eof = true,
                Ok(n) => self.framer.push(&self.buf[..n]),
                Err(e) if waiting(&e) => return Ok(Recv::Idle),
                Err(e) if e.kind() == ErrorKind::Interrupted => {}
                Err(e) => return Err(AdapterError::io(&format!("read from {}", self.name), e)),
            }
        }
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

// ---------------------------------------------------------------------------
// A directory: its files in byte order of name, each framed on its own
// ---------------------------------------------------------------------------

pub struct DirSource {
    name: String,
    files: VecDeque<PathBuf>,
    framing: Framing,
    current: Option<ReadSource<File>>,
}

impl DirSource {
    /// The regular files of `path` whose names do not begin with `.`, read
    /// once, in byte order of name. With `whole` framing one file is one
    /// message; with any other framing each file is framed on its own.
    pub fn open(path: &str, framing: &Framing) -> Result<DirSource, AdapterError> {
        let rd = std::fs::read_dir(path).map_err(|e| AdapterError::io(&format!("cannot read directory {}", path), e))?;
        let mut files: Vec<PathBuf> = rd
            .flatten()
            .map(|e| e.path())
            .filter(|p| p.is_file() && !p.file_name().and_then(|n| n.to_str()).map_or(true, |n| n.starts_with('.')))
            .collect();
        files.sort_by(|a, b| a.file_name().cmp(&b.file_name()));
        Ok(DirSource { name: format!("dir:{}", path), files: files.into(), framing: framing.clone(), current: None })
    }
}

impl Source for DirSource {
    fn recv(&mut self) -> Result<Recv, AdapterError> {
        loop {
            if let Some(cur) = &mut self.current {
                match cur.recv() {
                    Ok(Recv::End) => self.current = None,
                    Ok(other) => return Ok(other),
                    Err(e) => {
                        // this file is done for; the next file is its own unit
                        let file = cur.origin.clone().unwrap_or_default();
                        self.current = None;
                        return Err(AdapterError::new(&e.kind, format!("{} (in {})", e.msg, file)));
                    }
                }
            }
            let Some(path) = self.files.pop_front() else { return Ok(Recv::End) };
            let shown = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
            match File::open(&path) {
                Ok(f) => self.current = Some(ReadSource::new(f, &self.framing, &self.name, Some(shown))),
                Err(e) => return Err(AdapterError::new("io", format!("cannot open {}: {}", shown, e))),
            }
        }
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

// ---------------------------------------------------------------------------
// TCP listener as a source: every connection is its own framed stream
// ---------------------------------------------------------------------------

pub struct TcpListenSource {
    name: String,
    listener: TcpListener,
    framing: Framing,
    conns: Vec<(TcpStream, Box<dyn Framer>, String)>,
    ready: VecDeque<Message>,
    errors: VecDeque<AdapterError>,
    buf: Vec<u8>,
}

impl TcpListenSource {
    pub fn bind(host: &str, port: u16, framing: &Framing) -> Result<TcpListenSource, AdapterError> {
        let name = format!("tcp-listen://{}:{}", host, port);
        let listener = TcpListener::bind((listen_host(host), port)).map_err(|e| AdapterError::io(&format!("cannot listen on {}", name), e))?;
        listener.set_nonblocking(true).map_err(|e| AdapterError::io("set_nonblocking", e))?;
        Ok(TcpListenSource { name, listener, framing: framing.clone(), conns: Vec::new(), ready: VecDeque::new(), errors: VecDeque::new(), buf: vec![0u8; CHUNK] })
    }
    pub fn local_addr(&self) -> Option<SocketAddr> {
        self.listener.local_addr().ok()
    }

    fn accept(&mut self) {
        loop {
            match self.listener.accept() {
                Ok((s, peer)) => {
                    if self.conns.len() >= MAX_CONNECTIONS {
                        self.errors.push_back(AdapterError::new("connection-refused", format!("{}: already serving {} connections", peer, MAX_CONNECTIONS)));
                    } else if let Err(e) = s.set_nonblocking(true) {
                        self.errors.push_back(AdapterError::new("io", format!("{}: {}", peer, e)));
                    } else {
                        self.conns.push((s, self.framing.build(), peer.to_string()));
                    }
                }
                Err(e) if waiting(&e) => return,
                Err(e) if e.kind() == ErrorKind::Interrupted => {}
                Err(e) => {
                    self.errors.push_back(AdapterError::new("io", format!("accept: {}", e)));
                    return;
                }
            }
        }
    }

    /// One read from every connection. A connection whose stream cannot be
    /// framed, or that ends inside a message, is closed and reported.
    fn read_all(&mut self) {
        let mut i = 0;
        while i < self.conns.len() {
            let (stream, framer, peer) = &mut self.conns[i];
            let mut close = false;
            let fail = |e: AdapterError| AdapterError::new(&e.kind, format!("{} (connection {} closed)", e.msg, peer));
            match stream.read(&mut self.buf) {
                Ok(0) => {
                    close = true;
                    match framer.finish() {
                        Ok(Some(m)) => self.ready.push_back(Message::now(m, Some(peer.clone()))),
                        Ok(None) => {}
                        Err(e) => self.errors.push_back(fail(e)),
                    }
                }
                Ok(n) => {
                    framer.push(&self.buf[..n]);
                    loop {
                        match framer.next() {
                            Ok(Some(m)) => self.ready.push_back(Message::now(m, Some(peer.clone()))),
                            Ok(None) => break,
                            Err(e) if e.fatal => {
                                close = true;
                                self.errors.push_back(fail(e));
                                break;
                            }
                            Err(e) => self.errors.push_back(AdapterError::new(&e.kind, format!("{} (connection {})", e.msg, peer))),
                        }
                    }
                }
                Err(e) if waiting(&e) || e.kind() == ErrorKind::Interrupted => {}
                Err(e) => {
                    close = true;
                    self.errors.push_back(fail(AdapterError::new("io", e.to_string())));
                }
            }
            if close {
                self.conns.swap_remove(i);
            } else {
                i += 1;
            }
        }
    }
}

impl Source for TcpListenSource {
    fn recv(&mut self) -> Result<Recv, AdapterError> {
        if self.ready.is_empty() && self.errors.is_empty() {
            self.accept();
            self.read_all();
        }
        if let Some(m) = self.ready.pop_front() {
            return Ok(Recv::Message(m));
        }
        if let Some(e) = self.errors.pop_front() {
            return Err(e);
        }
        std::thread::sleep(Duration::from_millis(10));
        Ok(Recv::Idle)
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

// ---------------------------------------------------------------------------
// UDP
// ---------------------------------------------------------------------------

pub struct UdpSource {
    name: String,
    sock: UdpSocket,
    framer: Box<dyn Framer>,
    ready: VecDeque<Message>,
    pending: Option<AdapterError>,
    buf: Vec<u8>,
}

impl UdpSource {
    /// `host` empty: every local address. `host` a multicast group: join it,
    /// on the interface `iface` (an IPv4 address, or an IPv6 interface
    /// index) or on the one the system chooses. Otherwise: that local
    /// address. Each datagram is one unit for the framer.
    pub fn bind(host: &str, port: u16, iface: Option<&str>, framing: &Framing) -> Result<UdpSource, AdapterError> {
        let name = format!("udp://{}:{}", host, port);
        let io = |what: &str, e| AdapterError::io(&format!("{} {}", what, name), e);
        let sock = match host.parse::<IpAddr>() {
            Ok(IpAddr::V4(group)) if group.is_multicast() => {
                let via = match iface {
                    Some(a) => a.parse::<Ipv4Addr>().map_err(|_| AdapterError::fatal("bad-uri", format!("iface `{}` is not an IPv4 address", a)))?,
                    None => Ipv4Addr::UNSPECIFIED,
                };
                let s = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, port)).map_err(|e| io("cannot bind", e))?;
                s.join_multicast_v4(&group, &via).map_err(|e| io("cannot join", e))?;
                s
            }
            Ok(IpAddr::V6(group)) if group.is_multicast() => {
                let via = match iface {
                    Some(a) => a.parse::<u32>().map_err(|_| AdapterError::fatal("bad-uri", format!("iface `{}` is not an IPv6 interface index", a)))?,
                    None => 0,
                };
                let s = UdpSocket::bind((Ipv6Addr::UNSPECIFIED, port)).map_err(|e| io("cannot bind", e))?;
                s.join_multicast_v6(&group, via).map_err(|e| io("cannot join", e))?;
                s
            }
            _ if iface.is_some() => return Err(AdapterError::fatal("bad-uri", format!("{}: iface is for a multicast group", name))),
            _ => UdpSocket::bind((listen_host(host), port)).map_err(|e| io("cannot bind", e))?,
        };
        sock.set_read_timeout(Some(POLL)).map_err(|e| io("set_read_timeout", e))?;
        Ok(UdpSource { name, sock, framer: framing.build(), ready: VecDeque::new(), pending: None, buf: vec![0u8; CHUNK] })
    }
    pub fn local_addr(&self) -> Option<SocketAddr> {
        self.sock.local_addr().ok()
    }
}

impl Source for UdpSource {
    fn recv(&mut self) -> Result<Recv, AdapterError> {
        loop {
            if let Some(m) = self.ready.pop_front() {
                return Ok(Recv::Message(m));
            }
            if let Some(e) = self.pending.take() {
                return Err(e);
            }
            match self.sock.recv_from(&mut self.buf) {
                Ok((n, peer)) => {
                    let (msgs, err) = frame_unit(self.framer.as_mut(), &self.buf[..n]);
                    let peer = peer.to_string();
                    self.ready.extend(msgs.into_iter().map(|m| Message::now(m, Some(peer.clone()))));
                    self.pending = err.map(|e| AdapterError::new(&e.kind, format!("{} (datagram from {})", e.msg, peer)));
                }
                Err(e) if waiting(&e) => return Ok(Recv::Idle),
                Err(e) if e.kind() == ErrorKind::Interrupted => {}
                Err(e) => return Err(AdapterError::io(&format!("receive on {}", self.name), e)),
            }
        }
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

/// One message is one datagram.
pub struct UdpSink {
    name: String,
    sock: UdpSocket,
    to: SocketAddr,
    framer: Box<dyn Framer>,
    out: Vec<u8>,
}

impl UdpSink {
    /// Send to `host:port`. `iface` is the local address the socket binds,
    /// which is how the outgoing interface of a multicast group is chosen
    /// with the standard library; `ttl` is the multicast time to live.
    pub fn open(host: &str, port: u16, iface: Option<&str>, ttl: Option<u32>, framing: &Framing) -> Result<UdpSink, AdapterError> {
        let name = format!("udp://{}:{}", host, port);
        let io = |what: &str, e| AdapterError::io(&format!("{} {}", what, name), e);
        if host.is_empty() {
            return Err(AdapterError::fatal("bad-uri", format!("{}: an output needs a destination host", name)));
        }
        let to = (host, port).to_socket_addrs().map_err(|e| io("cannot resolve", e))?.next().ok_or_else(|| AdapterError::fatal("io", format!("{}: no address", name)))?;
        let local: SocketAddr = match iface {
            Some(a) => SocketAddr::new(a.parse().map_err(|_| AdapterError::fatal("bad-uri", format!("iface `{}` is not an address", a)))?, 0),
            None if to.is_ipv4() => SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), 0),
            None => SocketAddr::new(IpAddr::V6(Ipv6Addr::UNSPECIFIED), 0),
        };
        let sock = UdpSocket::bind(local).map_err(|e| io("cannot bind for", e))?;
        if let Some(t) = ttl {
            sock.set_multicast_ttl_v4(t).map_err(|e| io("cannot set ttl for", e))?;
        }
        Ok(UdpSink { name, sock, to, framer: framing.build(), out: Vec::new() })
    }
}

impl Sink for UdpSink {
    fn send(&mut self, bytes: &[u8], _meta: &Meta) -> Result<(), AdapterError> {
        self.out.clear();
        self.framer.wrap(bytes, &mut self.out)?;
        if self.out.len() > 65507 {
            return Err(AdapterError::new("datagram-oversize", format!("a message of {} bytes does not fit one UDP datagram", self.out.len())));
        }
        match self.sock.send_to(&self.out, self.to) {
            Ok(n) if n == self.out.len() => Ok(()),
            Ok(n) => Err(AdapterError::new("io", format!("sent {} of {} bytes", n, self.out.len()))),
            Err(e) => Err(AdapterError::new("io", e.to_string())),
        }
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

// ---------------------------------------------------------------------------
// A byte stream written in order: stdout, a file, a TCP connection, a serial port
// ---------------------------------------------------------------------------

pub struct WriteSink<W: Write + Send> {
    w: W,
    framer: Box<dyn Framer>,
    out: Vec<u8>,
    name: String,
}

impl<W: Write + Send> WriteSink<W> {
    pub fn new(w: W, framing: &Framing, name: &str) -> WriteSink<W> {
        WriteSink { w, framer: framing.build(), out: Vec::new(), name: name.to_string() }
    }
}
impl WriteSink<std::io::Stdout> {
    pub fn stdout(framing: &Framing) -> Self {
        WriteSink::new(std::io::stdout(), framing, "stdout:")
    }
}
impl WriteSink<File> {
    /// Create the file, or empty it; with `append`, add to it.
    pub fn file(path: &str, append: bool, framing: &Framing) -> Result<Self, AdapterError> {
        let mut o = std::fs::OpenOptions::new();
        o.create(true);
        if append {
            o.append(true);
        } else {
            o.write(true).truncate(true);
        }
        let f = o.open(path).map_err(|e| AdapterError::io(&format!("cannot open {} for writing", path), e))?;
        Ok(WriteSink::new(f, framing, &format!("file:{}", path)))
    }
    /// A serial port, opened as a device file; line settings are set outside.
    pub fn serial(path: &str, framing: &Framing) -> Result<Self, AdapterError> {
        let f = std::fs::OpenOptions::new().write(true).open(path).map_err(|e| AdapterError::io(&format!("cannot open {} for writing", path), e))?;
        Ok(WriteSink::new(f, framing, &format!("serial:{}", path)))
    }
}
impl WriteSink<TcpStream> {
    pub fn tcp(host: &str, port: u16, framing: &Framing) -> Result<Self, AdapterError> {
        let name = format!("tcp://{}:{}", host, port);
        let s = TcpStream::connect((host, port)).map_err(|e| AdapterError::io(&format!("cannot connect to {}", name), e))?;
        let _ = s.set_nodelay(true);
        Ok(WriteSink::new(s, framing, &name))
    }
}

impl<W: Write + Send> Sink for WriteSink<W> {
    fn send(&mut self, bytes: &[u8], _meta: &Meta) -> Result<(), AdapterError> {
        self.out.clear();
        self.framer.wrap(bytes, &mut self.out)?;
        // a stream that takes part of a message cannot be framed again
        self.w.write_all(&self.out).and_then(|_| self.w.flush()).map_err(|e| AdapterError::io(&format!("write to {}", self.name), e))
    }
    fn flush(&mut self) -> Result<(), AdapterError> {
        self.w.flush().map_err(|e| AdapterError::io(&format!("flush {}", self.name), e))
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

// ---------------------------------------------------------------------------
// A directory: one file per message
// ---------------------------------------------------------------------------

pub struct DirSink {
    name: String,
    dir: PathBuf,
    prefix: String,
    ext: String,
    by_origin: bool,
    framer: Box<dyn Framer>,
    last_origin: (String, u64),
}

impl DirSink {
    /// One file per message, written under a temporary name and renamed, so
    /// a reader of the directory never sees part of a file. The name is
    /// `<prefix><seq, six digits>.<ext>`, or with `by_origin`
    /// `<prefix><stem of the input's name>.<ext>` (then `-2`, `-3` for
    /// further messages of the same input). An existing file is never
    /// replaced.
    pub fn open(path: &str, prefix: &str, ext: &str, by_origin: bool, framing: &Framing) -> Result<DirSink, AdapterError> {
        let bad = |s: &str| s.contains('/') || s.contains('\\') || s.contains("..");
        if bad(prefix) || bad(ext) || ext.is_empty() {
            return Err(AdapterError::fatal("bad-uri", "prefix and ext are parts of a file name"));
        }
        std::fs::create_dir_all(path).map_err(|e| AdapterError::io(&format!("cannot create directory {}", path), e))?;
        Ok(DirSink {
            name: format!("dir:{}", path),
            dir: PathBuf::from(path),
            prefix: prefix.to_string(),
            ext: ext.to_string(),
            by_origin,
            framer: framing.build(),
            last_origin: (String::new(), 0),
        })
    }
}

impl Sink for DirSink {
    fn send(&mut self, bytes: &[u8], meta: &Meta) -> Result<(), AdapterError> {
        let stem = if self.by_origin {
            let origin = meta.origin.ok_or_else(|| AdapterError::new("no-origin", "name=origin needs an input that names its messages (file:, dir:)"))?;
            let stem = Path::new(origin).file_stem().and_then(|s| s.to_str()).filter(|s| !s.is_empty() && !s.starts_with('.'));
            let stem = stem.ok_or_else(|| AdapterError::new("no-origin", format!("`{}` gives no file name", origin)))?;
            if self.last_origin.0 == origin {
                self.last_origin.1 += 1;
                format!("{}-{}", stem, self.last_origin.1)
            } else {
                self.last_origin = (origin.to_string(), 1);
                stem.to_string()
            }
        } else {
            format!("{:06}", meta.seq)
        };
        let file = format!("{}{}.{}", self.prefix, stem, self.ext);
        let path = self.dir.join(&file);
        if path.exists() {
            return Err(AdapterError::new("exists", format!("{} exists and is not replaced", file)));
        }
        let mut out = Vec::new();
        self.framer.wrap(bytes, &mut out)?;
        let tmp = self.dir.join(format!(".{}.part", file));
        std::fs::write(&tmp, &out).and_then(|_| std::fs::rename(&tmp, &path)).map_err(|e| {
            let _ = std::fs::remove_file(&tmp);
            AdapterError::new("io", format!("cannot write {}: {}", file, e))
        })
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

// ---------------------------------------------------------------------------
// TCP listener as a sink: every connected client gets every message
// ---------------------------------------------------------------------------

pub struct TcpListenSink {
    name: String,
    listener: TcpListener,
    clients: Vec<(TcpStream, String)>,
    framer: Box<dyn Framer>,
    out: Vec<u8>,
}

impl TcpListenSink {
    pub fn bind(host: &str, port: u16, framing: &Framing) -> Result<TcpListenSink, AdapterError> {
        let name = format!("tcp-listen://{}:{}", host, port);
        let listener = TcpListener::bind((listen_host(host), port)).map_err(|e| AdapterError::io(&format!("cannot listen on {}", name), e))?;
        listener.set_nonblocking(true).map_err(|e| AdapterError::io("set_nonblocking", e))?;
        Ok(TcpListenSink { name, listener, clients: Vec::new(), framer: framing.build(), out: Vec::new() })
    }
    pub fn local_addr(&self) -> Option<SocketAddr> {
        self.listener.local_addr().ok()
    }
    fn accept(&mut self) {
        loop {
            match self.listener.accept() {
                Ok((s, peer)) => {
                    let ready = s.set_nonblocking(false).is_ok() && s.set_write_timeout(Some(CLIENT_WRITE_TIMEOUT)).is_ok();
                    if ready && self.clients.len() < MAX_CONNECTIONS {
                        let _ = s.set_nodelay(true);
                        self.clients.push((s, peer.to_string()));
                    }
                }
                Err(e) if e.kind() == ErrorKind::Interrupted => {}
                Err(_) => return,
            }
        }
    }
}

impl Sink for TcpListenSink {
    /// A message sent while no client is connected is not kept: the send
    /// fails with `no-client`. A client that does not take a message within
    /// the write timeout is dropped, and the send fails with
    /// `client-dropped` although the other clients received the message.
    fn send(&mut self, bytes: &[u8], _meta: &Meta) -> Result<(), AdapterError> {
        self.accept();
        if self.clients.is_empty() {
            return Err(AdapterError::new("no-client", "no client is connected; the message was not delivered"));
        }
        self.out.clear();
        self.framer.wrap(bytes, &mut self.out)?;
        let mut dropped = Vec::new();
        let out = &self.out;
        self.clients.retain_mut(|(s, peer)| match s.write_all(out) {
            Ok(()) => true,
            Err(e) => {
                dropped.push(format!("{} ({})", peer, e));
                false
            }
        });
        if dropped.is_empty() {
            Ok(())
        } else {
            Err(AdapterError::new("client-dropped", format!("closed {}", dropped.join(", "))))
        }
    }
    fn describe(&self) -> String {
        self.name.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};

    /// A new empty directory under the system temporary directory.
    pub(crate) fn temp_dir(tag: &str) -> PathBuf {
        static N: AtomicU32 = AtomicU32::new(0);
        let d = std::env::temp_dir().join(format!("goat-adapters-{}-{}-{}", tag, std::process::id(), N.fetch_add(1, Ordering::Relaxed)));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }
    fn fr(s: &str) -> Framing {
        Framing::parse(s).unwrap()
    }
    fn meta(seq: u64, origin: Option<&str>) -> Meta<'_> {
        Meta { seq, origin }
    }
    /// Messages until the source ends, or until `want` have arrived.
    fn collect(src: &mut dyn Source, want: usize) -> (Vec<Message>, Vec<AdapterError>) {
        let (mut msgs, mut errs) = (Vec::new(), Vec::new());
        let until = std::time::Instant::now() + Duration::from_secs(10);
        while msgs.len() + errs.len() < want && std::time::Instant::now() < until {
            match src.recv() {
                Ok(Recv::Message(m)) => msgs.push(m),
                Ok(Recv::Idle) => {}
                Ok(Recv::End) => break,
                Err(e) => errs.push(e),
            }
        }
        (msgs, errs)
    }
    fn bodies(msgs: &[Message]) -> Vec<&[u8]> {
        msgs.iter().map(|m| m.bytes.as_slice()).collect()
    }

    #[test]
    fn read_source_frames_a_stream_and_stamps_each_message() {
        let data: &[u8] = b"one\ntwo\nthree";
        let mut s = ReadSource::new(data, &fr("newline"), "test:", Some("t".into()));
        let (msgs, errs) = collect(&mut s, usize::MAX);
        assert!(errs.is_empty());
        assert_eq!(bodies(&msgs), [&b"one"[..], b"two", b"three"]);
        assert!(msgs.iter().all(|m| m.received_ms.unwrap() > 1_600_000_000_000 && m.origin.as_deref() == Some("t")));
    }

    #[test]
    fn read_source_reports_a_stream_that_ends_inside_a_message() {
        let data: &[u8] = &[0, 2, b'h', b'i', 0, 9, b'x'];
        let mut s = ReadSource::new(data, &fr("len:2:be"), "test:", None);
        let (msgs, errs) = collect(&mut s, 2);
        assert_eq!(bodies(&msgs), [b"hi"]);
        assert_eq!(errs[0].kind, "frame-truncated");
    }

    #[test]
    fn file_sink_and_file_source_round_trip_and_append() {
        let d = temp_dir("file");
        let p = d.join("m.bin");
        let p = p.to_str().unwrap();
        let mut w = WriteSink::file(p, false, &fr("len:4:le")).unwrap();
        w.send(b"alpha", &meta(1, None)).unwrap();
        w.send(&[0, 255, 10], &meta(2, None)).unwrap();
        w.flush().unwrap();
        drop(w);
        let mut w = WriteSink::file(p, true, &fr("len:4:le")).unwrap();
        w.send(b"tail", &meta(3, None)).unwrap();
        drop(w);
        let mut s = ReadSource::file(p, &fr("len:4:le")).unwrap();
        let (msgs, errs) = collect(&mut s, usize::MAX);
        assert!(errs.is_empty());
        assert_eq!(bodies(&msgs), [&b"alpha"[..], &[0, 255, 10], b"tail"]);
        assert_eq!(msgs[0].origin.as_deref(), Some(p));
        // without append the file is emptied
        drop(WriteSink::file(p, false, &fr("newline")).unwrap());
        assert_eq!(std::fs::read(p).unwrap().len(), 0);
        assert_eq!(ReadSource::file(d.join("absent").to_str().unwrap(), &fr("newline")).err().unwrap().kind, "io");
        std::fs::remove_dir_all(d).unwrap();
    }

    #[test]
    fn dir_source_reads_one_message_per_file_in_name_order() {
        let d = temp_dir("dirsrc");
        std::fs::write(d.join("b.xml"), "<b/>").unwrap();
        std::fs::write(d.join("a.xml"), "<a/>\n").unwrap();
        std::fs::write(d.join(".hidden"), "no").unwrap();
        std::fs::write(d.join("empty"), "").unwrap();
        std::fs::create_dir(d.join("sub")).unwrap();
        let mut s = DirSource::open(d.to_str().unwrap(), &Framing::whole()).unwrap();
        let (msgs, errs) = collect(&mut s, usize::MAX);
        assert!(errs.is_empty());
        assert_eq!(bodies(&msgs), [&b"<a/>\n"[..], b"<b/>"]);
        assert_eq!(msgs[0].origin.as_deref(), Some("a.xml"));
        std::fs::remove_dir_all(d).unwrap();
    }

    #[test]
    fn dir_source_frames_within_each_file_and_goes_on_after_a_bad_file() {
        let d = temp_dir("dirframed");
        std::fs::write(d.join("1.bin"), [1, b'a', 1, b'b']).unwrap();
        std::fs::write(d.join("2.bin"), [1, b'c', 5, b'x']).unwrap();
        std::fs::write(d.join("3.bin"), [1, b'd']).unwrap();
        let mut s = DirSource::open(d.to_str().unwrap(), &fr("len:1")).unwrap();
        let (msgs, errs) = collect(&mut s, usize::MAX);
        assert_eq!(bodies(&msgs), [b"a", b"b", b"c", b"d"]);
        assert_eq!(errs.len(), 1);
        assert_eq!(errs[0].kind, "frame-truncated");
        assert!(errs[0].msg.contains("2.bin") && !errs[0].fatal, "{}", errs[0].msg);
        std::fs::remove_dir_all(d).unwrap();
    }

    #[test]
    fn dir_sink_names_by_sequence_or_by_origin_and_never_replaces() {
        let d = temp_dir("dirsink");
        let p = d.to_str().unwrap();
        let mut s = DirSink::open(p, "trk-", "json", false, &Framing::whole()).unwrap();
        s.send(b"{}", &meta(1, None)).unwrap();
        s.send(b"[]", &meta(2, None)).unwrap();
        assert_eq!(std::fs::read(d.join("trk-000001.json")).unwrap(), b"{}");
        assert_eq!(std::fs::read(d.join("trk-000002.json")).unwrap(), b"[]");
        assert_eq!(s.send(b"x", &meta(2, None)).unwrap_err().kind, "exists");
        assert_eq!(std::fs::read(d.join("trk-000002.json")).unwrap(), b"[]");

        let mut s = DirSink::open(p, "", "geojson", true, &fr("newline")).unwrap();
        s.send(b"1", &meta(1, Some("in/a.xml"))).unwrap();
        s.send(b"2", &meta(2, Some("in/a.xml"))).unwrap();
        s.send(b"3", &meta(3, Some("b.xml"))).unwrap();
        assert_eq!(std::fs::read(d.join("a.geojson")).unwrap(), b"1\n");
        assert_eq!(std::fs::read(d.join("a-2.geojson")).unwrap(), b"2\n");
        assert_eq!(std::fs::read(d.join("b.geojson")).unwrap(), b"3\n");
        assert_eq!(s.send(b"4", &meta(4, None)).unwrap_err().kind, "no-origin");
        // nothing temporary is left behind
        assert!(std::fs::read_dir(&d).unwrap().flatten().all(|e| !e.file_name().to_string_lossy().ends_with(".part")));
        assert_eq!(DirSink::open(p, "../x", "json", false, &Framing::whole()).err().unwrap().kind, "bad-uri");
        std::fs::remove_dir_all(d).unwrap();
    }

    #[test]
    fn tcp_client_sink_to_tcp_listener_source_over_loopback() {
        let mut src = TcpListenSource::bind("127.0.0.1", 0, &fr("len:2:be")).unwrap();
        let port = src.local_addr().unwrap().port();
        let mut a = WriteSink::tcp("127.0.0.1", port, &fr("len:2:be")).unwrap();
        let mut b = WriteSink::tcp("127.0.0.1", port, &fr("len:2:be")).unwrap();
        a.send(b"from a", &meta(1, None)).unwrap();
        b.send(b"from b", &meta(1, None)).unwrap();
        a.send(b"again a", &meta(2, None)).unwrap();
        let (msgs, errs) = collect(&mut src, 3);
        assert!(errs.is_empty(), "{:?}", errs);
        let mut got: Vec<&[u8]> = bodies(&msgs);
        got.sort();
        assert_eq!(got, [&b"again a"[..], b"from a", b"from b"]);
        assert!(msgs[0].origin.as_deref().unwrap().starts_with("127.0.0.1:"));
    }

    #[test]
    fn tcp_listener_source_closes_and_reports_a_connection_that_ends_inside_a_message() {
        let mut src = TcpListenSource::bind("127.0.0.1", 0, &fr("len:2:be")).unwrap();
        let port = src.local_addr().unwrap().port();
        let mut c = TcpStream::connect(("127.0.0.1", port)).unwrap();
        c.write_all(&[0, 1, b'k', 0, 9, b'x']).unwrap();
        drop(c);
        let (msgs, errs) = collect(&mut src, 2);
        assert_eq!(bodies(&msgs), [b"k"]);
        assert_eq!(errs[0].kind, "frame-truncated");
        assert!(!errs[0].fatal);
        // the listener still serves
        let mut ok = WriteSink::tcp("127.0.0.1", port, &fr("len:2:be")).unwrap();
        ok.send(b"next", &meta(1, None)).unwrap();
        assert_eq!(bodies(&collect(&mut src, 1).0), [b"next"]);
    }

    #[test]
    fn tcp_client_source_reads_until_the_peer_closes() {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        let t = std::thread::spawn(move || {
            let (mut s, _) = l.accept().unwrap();
            s.write_all(b"a\n").unwrap();
            std::thread::sleep(Duration::from_millis(300)); // longer than one poll: the source reports Idle
            s.write_all(b"b\n").unwrap();
        });
        let mut src = ReadSource::tcp("127.0.0.1", port, &fr("newline")).unwrap();
        let (msgs, errs) = collect(&mut src, usize::MAX);
        t.join().unwrap();
        assert!(errs.is_empty());
        assert_eq!(bodies(&msgs), [b"a", b"b"]);
        assert_eq!(ReadSource::tcp("127.0.0.1", 1, &fr("newline")).err().unwrap().kind, "io");
    }

    #[test]
    fn tcp_listener_sink_sends_to_every_client_and_fails_loudly_with_none() {
        let mut sink = TcpListenSink::bind("127.0.0.1", 0, &fr("newline")).unwrap();
        let port = sink.local_addr().unwrap().port();
        assert_eq!(sink.send(b"lost", &meta(1, None)).unwrap_err().kind, "no-client");
        let mut c1 = ReadSource::tcp("127.0.0.1", port, &fr("newline")).unwrap();
        let mut c2 = ReadSource::tcp("127.0.0.1", port, &fr("newline")).unwrap();
        std::thread::sleep(Duration::from_millis(50));
        sink.send(b"hello", &meta(2, None)).unwrap();
        assert_eq!(bodies(&collect(&mut c1, 1).0), [b"hello"]);
        assert_eq!(bodies(&collect(&mut c2, 1).0), [b"hello"]);
        // a client that went away is dropped and the send says so
        drop(c1);
        let mut kinds = Vec::new();
        for i in 0..50 {
            if let Err(e) = sink.send(b"more", &meta(3 + i, None)) {
                kinds.push(e.kind);
                break;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        assert_eq!(kinds, ["client-dropped"]);
        sink.send(b"last", &meta(99, None)).unwrap();
    }

    #[test]
    fn udp_unicast_one_datagram_is_one_message() {
        let mut src = UdpSource::bind("127.0.0.1", 0, None, &Framing::whole()).unwrap();
        let port = src.local_addr().unwrap().port();
        let mut sink = UdpSink::open("127.0.0.1", port, None, None, &Framing::whole()).unwrap();
        sink.send(b"<event/>", &meta(1, None)).unwrap();
        sink.send(&[0, 1, 2, 255], &meta(2, None)).unwrap();
        let (msgs, errs) = collect(&mut src, 2);
        assert!(errs.is_empty());
        assert_eq!(bodies(&msgs), [&b"<event/>"[..], &[0, 1, 2, 255]]);
        assert!(msgs[0].origin.as_deref().unwrap().starts_with("127.0.0.1:"));
        assert_eq!(sink.send(&vec![0u8; 70_000], &meta(3, None)).unwrap_err().kind, "datagram-oversize");
        assert!(matches!(src.recv(), Ok(Recv::Idle)));
    }

    #[test]
    fn udp_datagram_with_stated_framing_carries_several_messages_and_reports_a_cut_one() {
        let mut src = UdpSource::bind("127.0.0.1", 0, None, &fr("len:1")).unwrap();
        let to = src.local_addr().unwrap();
        let s = UdpSocket::bind("127.0.0.1:0").unwrap();
        s.send_to(&[1, b'a', 1, b'b'], to).unwrap();
        s.send_to(&[1, b'c', 4, b'x'], to).unwrap();
        s.send_to(&[1, b'd'], to).unwrap();
        let (msgs, errs) = collect(&mut src, 5);
        assert_eq!(bodies(&msgs), [b"a", b"b", b"c", b"d"]);
        assert_eq!(errs.len(), 1);
        assert_eq!((errs[0].kind.as_str(), errs[0].fatal), ("frame-truncated", false));
    }

    #[test]
    fn udp_multicast_join_and_receive() {
        // 239.255.0.0/16 is the administratively scoped local range. A time
        // to live of 0 keeps the datagram on this host. The loopback
        // interface is tried first, then the interface the system chooses:
        // which of the two carries multicast differs between systems.
        let group = "239.255.77.41";
        assert_eq!(UdpSource::bind("127.0.0.1", 0, Some("127.0.0.1"), &Framing::whole()).err().unwrap().kind, "bad-uri");
        let mut why = Vec::new();
        for iface in [Some("127.0.0.1"), None] {
            let mut src = match UdpSource::bind(group, 0, iface, &Framing::whole()) {
                Ok(s) => s,
                Err(e) => {
                    why.push(format!("join via {:?}: {}", iface, e));
                    continue;
                }
            };
            let port = src.local_addr().unwrap().port();
            let mut sink = UdpSink::open(group, port, iface, Some(0), &Framing::whole()).unwrap();
            if let Err(e) = sink.send(b"to the group", &meta(1, None)) {
                why.push(format!("send via {:?}: {}", iface, e));
                continue;
            }
            let (msgs, _) = collect(&mut src, 1);
            if msgs.is_empty() {
                why.push(format!("via {:?}: nothing came back", iface));
                continue;
            }
            assert_eq!(bodies(&msgs), [b"to the group"]);
            return;
        }
        // a host with no multicast-capable interface cannot run this
        eprintln!("skipped: no interface carried multicast: {}", why.join("; "));
    }

    #[cfg(unix)]
    #[test]
    fn serial_port_is_a_device_file_read_and_written_in_order() {
        // a named pipe stands in for the device: both are opened by path and
        // read as a stream of bytes
        let d = temp_dir("serial");
        let p = d.join("ttyTEST");
        let p = p.to_str().unwrap().to_string();
        let made = std::process::Command::new("mkfifo").arg(&p).status().map(|s| s.success()).unwrap_or(false);
        if !made {
            eprintln!("skipped: mkfifo is not available");
            return;
        }
        let wp = p.clone();
        let t = std::thread::spawn(move || {
            let mut w = WriteSink::serial(&wp, &fr("start:0x7e:len:1")).unwrap();
            w.send(b"ping", &meta(1, None)).unwrap();
            w.send(b"pong", &meta(2, None)).unwrap();
        });
        let mut s = ReadSource::serial(&p, &fr("start:0x7e:len:1")).unwrap();
        let (msgs, errs) = collect(&mut s, usize::MAX);
        t.join().unwrap();
        assert!(errs.is_empty());
        assert_eq!(bodies(&msgs), [b"ping", b"pong"]);
        std::fs::remove_dir_all(d).unwrap();
    }
}
