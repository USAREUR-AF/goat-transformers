//! Framing: how one message is delimited on a stream.
//!
//! Framing is stated, never guessed from content. A framer is given the
//! bytes as they arrive and returns whole messages; the same framer wraps an
//! outgoing message. Every framer has a maximum message size, so its buffer
//! is bounded.

use crate::AdapterError;

/// The default maximum size of one message: 16 MiB.
pub const DEFAULT_MAX: usize = 16 * 1024 * 1024;

pub trait Framer: Send {
    /// Give the framer bytes as they arrived.
    fn push(&mut self, bytes: &[u8]);
    /// The next whole message, or `None` when more bytes are needed. An
    /// error with `fatal` set means the stream can no longer be framed.
    fn next(&mut self) -> Result<Option<Vec<u8>>, AdapterError>;
    /// The unit has ended (end of stream, end of file, end of datagram).
    /// Returns the last message if the framing allows one to end here; bytes
    /// that are part of an incomplete message are an error. The framer is
    /// empty afterwards and can be used for the next unit.
    fn finish(&mut self) -> Result<Option<Vec<u8>>, AdapterError>;
    /// Append one outgoing message, framed, to `out`.
    fn wrap(&self, msg: &[u8], out: &mut Vec<u8>) -> Result<(), AdapterError>;
}

/// A read buffer that hands bytes out from the front.
#[derive(Default)]
struct Buf {
    data: Vec<u8>,
    pos: usize,
}
impl Buf {
    fn push(&mut self, b: &[u8]) {
        if self.pos > 0 && self.pos >= self.data.len() / 2 {
            self.data.drain(..self.pos);
            self.pos = 0;
        }
        self.data.extend_from_slice(b);
    }
    fn avail(&self) -> &[u8] {
        &self.data[self.pos..]
    }
    fn take(&mut self, n: usize) -> Vec<u8> {
        let v = self.data[self.pos..self.pos + n].to_vec();
        self.pos += n;
        v
    }
    fn skip(&mut self, n: usize) {
        self.pos += n;
    }
    fn clear(&mut self) -> usize {
        let n = self.data.len() - self.pos;
        self.data.clear();
        self.pos = 0;
        n
    }
}

fn oversize(len: usize, max: usize) -> AdapterError {
    AdapterError::fatal("frame-oversize", format!("a message of {} bytes or more exceeds the maximum of {}", len, max))
}
fn truncated(n: usize) -> AdapterError {
    AdapterError::new("frame-truncated", format!("the input ended with {} bytes of an incomplete message", n))
}

fn read_len(b: &[u8], big: bool) -> u64 {
    let mut v = 0u64;
    if big {
        for x in b {
            v = (v << 8) | *x as u64;
        }
    } else {
        for x in b.iter().rev() {
            v = (v << 8) | *x as u64;
        }
    }
    v
}
fn write_len(len: usize, n: usize, big: bool, out: &mut Vec<u8>) -> Result<(), AdapterError> {
    if n < 8 && (len as u64) >> (8 * n) != 0 {
        return Err(AdapterError::new("frame-mismatch", format!("a message of {} bytes does not fit a length of {} bytes", len, n)));
    }
    let be = (len as u64).to_be_bytes();
    if big {
        out.extend_from_slice(&be[8 - n..]);
    } else {
        out.extend(be[8 - n..].iter().rev());
    }
    Ok(())
}

/// One message per line. A line ends at LF; a CR before it is removed; an
/// empty line is not a message. A last line with no LF is a message.
pub struct Newline {
    buf: Buf,
    max: usize,
}
impl Newline {
    pub fn new(max: usize) -> Newline {
        Newline { buf: Buf::default(), max }
    }
}
fn strip_cr(mut v: Vec<u8>) -> Vec<u8> {
    if v.last() == Some(&b'\r') {
        v.pop();
    }
    v
}
impl Framer for Newline {
    fn push(&mut self, bytes: &[u8]) {
        self.buf.push(bytes)
    }
    fn next(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        loop {
            match self.buf.avail().iter().position(|b| *b == b'\n') {
                Some(i) => {
                    let line = strip_cr(self.buf.take(i));
                    self.buf.skip(1);
                    if line.len() > self.max {
                        return Err(oversize(line.len(), self.max));
                    }
                    if !line.is_empty() {
                        return Ok(Some(line));
                    }
                }
                None if self.buf.avail().len() > self.max => return Err(oversize(self.buf.avail().len(), self.max)),
                None => return Ok(None),
            }
        }
    }
    fn finish(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        let n = self.buf.avail().len();
        let line = strip_cr(self.buf.take(n));
        self.buf.clear();
        Ok(if line.is_empty() { None } else { Some(line) })
    }
    fn wrap(&self, msg: &[u8], out: &mut Vec<u8>) -> Result<(), AdapterError> {
        if msg.contains(&b'\n') {
            return Err(AdapterError::new("frame-mismatch", "the message contains a line feed and cannot be one line"));
        }
        out.extend_from_slice(msg);
        out.push(b'\n');
        Ok(())
    }
}

/// A length of `n` bytes (1, 2, 4 or 8), then that many bytes of message.
/// The length counts the message only.
pub struct LengthPrefix {
    buf: Buf,
    n: usize,
    big: bool,
    max: usize,
}
impl LengthPrefix {
    pub fn new(n: usize, big: bool, max: usize) -> LengthPrefix {
        LengthPrefix { buf: Buf::default(), n, big, max }
    }
}
impl Framer for LengthPrefix {
    fn push(&mut self, bytes: &[u8]) {
        self.buf.push(bytes)
    }
    fn next(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        let a = self.buf.avail();
        if a.len() < self.n {
            return Ok(None);
        }
        let len = read_len(&a[..self.n], self.big);
        if len > self.max as u64 {
            return Err(oversize(len as usize, self.max));
        }
        let len = len as usize;
        if a.len() < self.n + len {
            return Ok(None);
        }
        self.buf.skip(self.n);
        Ok(Some(self.buf.take(len)))
    }
    fn finish(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        match self.buf.clear() {
            0 => Ok(None),
            n => Err(truncated(n)),
        }
    }
    fn wrap(&self, msg: &[u8], out: &mut Vec<u8>) -> Result<(), AdapterError> {
        write_len(msg.len(), self.n, self.big, out)?;
        out.extend_from_slice(msg);
        Ok(())
    }
}

/// Every message is exactly `n` bytes.
pub struct Fixed {
    buf: Buf,
    n: usize,
}
impl Fixed {
    pub fn new(n: usize) -> Fixed {
        Fixed { buf: Buf::default(), n }
    }
}
impl Framer for Fixed {
    fn push(&mut self, bytes: &[u8]) {
        self.buf.push(bytes)
    }
    fn next(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        Ok(if self.buf.avail().len() >= self.n { Some(self.buf.take(self.n)) } else { None })
    }
    fn finish(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        match self.buf.clear() {
            0 => Ok(None),
            n => Err(truncated(n)),
        }
    }
    fn wrap(&self, msg: &[u8], out: &mut Vec<u8>) -> Result<(), AdapterError> {
        if msg.len() != self.n {
            return Err(AdapterError::new("frame-mismatch", format!("a message of {} bytes is not the fixed size {}", msg.len(), self.n)));
        }
        out.extend_from_slice(msg);
        Ok(())
    }
}

/// A start byte, a length of `n` bytes, then the message.
///
/// With `total` unset the length counts the bytes after it, and the message
/// is those bytes. With `total` set the length counts the whole frame from
/// the start byte, and the message is the whole frame: this is the shape of
/// a format whose own first bytes are a type and a length (an ASTERIX data
/// block is `start:0x3e:len:2:be:total` for category 062).
///
/// Bytes before a start byte are skipped and reported as `frame-desync`;
/// the framer then continues at the next start byte.
pub struct StartLength {
    buf: Buf,
    start: u8,
    n: usize,
    big: bool,
    total: bool,
    max: usize,
}
impl StartLength {
    pub fn new(start: u8, n: usize, big: bool, total: bool, max: usize) -> StartLength {
        StartLength { buf: Buf::default(), start, n, big, total, max }
    }
}
impl Framer for StartLength {
    fn push(&mut self, bytes: &[u8]) {
        self.buf.push(bytes)
    }
    fn next(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        let a = self.buf.avail();
        if a.is_empty() {
            return Ok(None);
        }
        if a[0] != self.start {
            let skip = a.iter().position(|b| *b == self.start).unwrap_or(a.len());
            self.buf.skip(skip);
            return Err(AdapterError::new("frame-desync", format!("skipped {} bytes that do not begin with the start byte 0x{:02x}", skip, self.start)));
        }
        let head = 1 + self.n;
        if a.len() < head {
            return Ok(None);
        }
        let len = read_len(&a[1..head], self.big);
        if len > self.max as u64 {
            self.buf.skip(1);
            return Err(AdapterError::new("frame-desync", format!("a length of {} exceeds the maximum of {}; skipped the start byte", len, self.max)));
        }
        let len = len as usize;
        if self.total {
            if len < head {
                self.buf.skip(1);
                return Err(AdapterError::new("frame-desync", format!("a whole-frame length of {} is shorter than its own header; skipped the start byte", len)));
            }
            if a.len() < len {
                return Ok(None);
            }
            Ok(Some(self.buf.take(len)))
        } else {
            if a.len() < head + len {
                return Ok(None);
            }
            self.buf.skip(head);
            Ok(Some(self.buf.take(len)))
        }
    }
    fn finish(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        match self.buf.clear() {
            0 => Ok(None),
            n => Err(truncated(n)),
        }
    }
    fn wrap(&self, msg: &[u8], out: &mut Vec<u8>) -> Result<(), AdapterError> {
        if self.total {
            let head = 1 + self.n;
            let ok = msg.len() >= head && msg[0] == self.start && read_len(&msg[1..head], self.big) == msg.len() as u64;
            if !ok {
                return Err(AdapterError::new("frame-mismatch", "the message does not begin with the start byte and its own whole length"));
            }
            out.extend_from_slice(msg);
        } else {
            out.push(self.start);
            write_len(msg.len(), self.n, self.big, out)?;
            out.extend_from_slice(msg);
        }
        Ok(())
    }
}

/// A length field of `n` bytes at offset `at` of each frame, with no start
/// byte: a stream of blocks whose header states their length after other
/// header octets (`at:<K>:len:<N>:<be|le>:<whole|rest>`). With `whole` the
/// length counts the whole frame, with `rest` the bytes after the length
/// field. The message is the whole frame, header included.
pub struct LengthAt {
    buf: Buf,
    at: usize,
    n: usize,
    big: bool,
    whole: bool,
    max: usize,
}
impl LengthAt {
    pub fn new(at: usize, n: usize, big: bool, whole: bool, max: usize) -> LengthAt {
        LengthAt { buf: Buf::default(), at, n, big, whole, max }
    }
    /// The size of the frame whose first `at + n` bytes are `head`; `None`
    /// when the length is shorter than the length field's own end.
    fn size(&self, head: &[u8]) -> Option<u64> {
        let len = read_len(&head[self.at..self.at + self.n], self.big);
        let end = (self.at + self.n) as u64;
        if self.whole {
            (len >= end).then_some(len)
        } else {
            len.checked_add(end)
        }
    }
}
impl Framer for LengthAt {
    fn push(&mut self, bytes: &[u8]) {
        self.buf.push(bytes)
    }
    fn next(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        let a = self.buf.avail();
        let head = self.at + self.n;
        if a.len() < head {
            return Ok(None);
        }
        let size = match self.size(&a[..head]) {
            Some(n) => n,
            None => {
                self.buf.skip(1);
                return Err(AdapterError::new("frame-desync", format!("a whole-frame length shorter than the {} bytes up to the end of its length field; skipped one byte", head)));
            }
        };
        if size > self.max as u64 {
            self.buf.skip(1);
            return Err(AdapterError::new("frame-desync", format!("a frame of {} bytes exceeds the maximum of {}; skipped one byte", size, self.max)));
        }
        let size = size as usize;
        if a.len() < size {
            return Ok(None);
        }
        Ok(Some(self.buf.take(size)))
    }
    fn finish(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        match self.buf.clear() {
            0 => Ok(None),
            n => Err(truncated(n)),
        }
    }
    fn wrap(&self, msg: &[u8], out: &mut Vec<u8>) -> Result<(), AdapterError> {
        let head = self.at + self.n;
        if msg.len() < head || self.size(&msg[..head]) != Some(msg.len() as u64) {
            return Err(AdapterError::new("frame-mismatch", format!("the message's length field ({} bytes at offset {}) does not state its own size", self.n, self.at)));
        }
        out.extend_from_slice(msg);
        Ok(())
    }
}

/// The whole unit is one message: one datagram, one file, one XML or JSON
/// document read to the end of the input.
pub struct Whole {
    buf: Vec<u8>,
    max: usize,
}
impl Whole {
    pub fn new(max: usize) -> Whole {
        Whole { buf: Vec::new(), max }
    }
}
impl Framer for Whole {
    fn push(&mut self, bytes: &[u8]) {
        // keep at most one byte past the maximum: enough to know it was passed
        let room = (self.max + 1).saturating_sub(self.buf.len());
        self.buf.extend_from_slice(&bytes[..bytes.len().min(room)]);
    }
    fn next(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        if self.buf.len() > self.max {
            return Err(oversize(self.buf.len(), self.max));
        }
        Ok(None)
    }
    fn finish(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        let v = std::mem::take(&mut self.buf);
        if v.len() > self.max {
            return Err(oversize(v.len(), self.max));
        }
        Ok(if v.is_empty() { None } else { Some(v) })
    }
    fn wrap(&self, msg: &[u8], out: &mut Vec<u8>) -> Result<(), AdapterError> {
        out.extend_from_slice(msg);
        Ok(())
    }
}

/// MAVLink 2 frames (https://mavlink.io/en/guide/serialization.html).
///
/// A frame is STX 0xFD, LEN, INCOMPAT, COMPAT, SEQ, SYSID, COMPID, MSGID (3
/// bytes, little-endian), LEN payload bytes, a 2-byte checksum and, when
/// INCOMPAT bit 0 is set, a 13-byte signature. A sender trims trailing zero
/// bytes from the payload; a receiver reads the missing bytes as zero. This
/// framer does that: a payload shorter than its message's full length is
/// zero-filled and LEN is rewritten, so a pack written for the full length
/// decodes it. The checksum and signature are carried unchanged (they are not
/// mapped). Bytes before an STX are skipped, as a MAVLink receiver does; a
/// MAVLink 1 frame (STX 0xFE) and a frame whose id is not in `lengths` pass
/// through unchanged.
pub struct Mavlink2 {
    buf: Buf,
    lengths: std::sync::Arc<std::collections::BTreeMap<u32, usize>>,
}
impl Mavlink2 {
    pub fn new(lengths: std::sync::Arc<std::collections::BTreeMap<u32, usize>>) -> Mavlink2 {
        Mavlink2 { buf: Buf::default(), lengths }
    }
}
const MAV2_STX: u8 = 0xFD;
const MAV1_STX: u8 = 0xFE;
impl Framer for Mavlink2 {
    fn push(&mut self, bytes: &[u8]) {
        self.buf.push(bytes);
    }
    fn next(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        // skip to the next start byte
        let a = self.buf.avail();
        let skip = a.iter().position(|&b| b == MAV2_STX || b == MAV1_STX).unwrap_or(a.len());
        if skip > 0 {
            self.buf.skip(skip);
        }
        let a = self.buf.avail();
        if a.len() < 2 {
            return Ok(None);
        }
        if a[0] == MAV1_STX {
            let total = 6 + a[1] as usize + 2;
            if a.len() < total {
                return Ok(None);
            }
            return Ok(Some(self.buf.take(total)));
        }
        if a.len() < 10 {
            return Ok(None);
        }
        let len = a[1] as usize;
        let sig = if a[2] & 0x01 != 0 { 13 } else { 0 };
        let total = 10 + len + 2 + sig;
        if a.len() < total {
            return Ok(None);
        }
        let frame = self.buf.take(total);
        let id = frame[7] as u32 | (frame[8] as u32) << 8 | (frame[9] as u32) << 16;
        match self.lengths.get(&id) {
            Some(&full) if full > len && full <= 255 => {
                let mut out = Vec::with_capacity(10 + full + 2 + sig);
                out.extend_from_slice(&frame[..10]);
                out[1] = full as u8;
                out.extend_from_slice(&frame[10..10 + len]);
                out.resize(10 + full, 0);
                out.extend_from_slice(&frame[10 + len..]);
                Ok(Some(out))
            }
            _ => Ok(Some(frame)),
        }
    }
    fn finish(&mut self) -> Result<Option<Vec<u8>>, AdapterError> {
        let r = self.next();
        let left = self.buf.clear();
        match r {
            Ok(Some(m)) if left == 0 => Ok(Some(m)),
            Ok(Some(_)) | Ok(None) if left > 0 => Err(truncated(left)),
            other => other,
        }
    }
    fn wrap(&self, msg: &[u8], out: &mut Vec<u8>) -> Result<(), AdapterError> {
        out.extend_from_slice(msg);
        Ok(())
    }
}

/// The full payload length of every MAVLink 2 message a pack defines: from
/// each kind's `when 0:56:24 <id>` (the message id) and `when 0:8:8 <len>`
/// (the payload length) lines of `pack.def` text.
pub fn mavlink2_lengths(pack_def: &str, into: &mut std::collections::BTreeMap<u32, usize>) {
    let (mut id, mut len): (Option<u32>, Option<usize>) = (None, None);
    let mut flush = |id: &mut Option<u32>, len: &mut Option<usize>| {
        if let (Some(i), Some(l)) = (id.take(), len.take()) {
            into.insert(i, l);
        }
    };
    for line in pack_def.lines() {
        let f: Vec<&str> = line.split_whitespace().collect();
        match f.as_slice() {
            ["kind", ..] => {
                flush(&mut id, &mut len);
            }
            ["when", "0:56:24", v] => id = v.parse().ok(),
            ["when", "0:8:8", v] => len = v.parse().ok(),
            _ => {}
        }
    }
    flush(&mut id, &mut len);
}

/// Frame one complete unit (a datagram, a publication): every message in it,
/// and the first error if the unit did not frame cleanly. The framer is
/// empty afterwards, so the next unit starts clean.
pub fn frame_unit(framer: &mut dyn Framer, bytes: &[u8]) -> (Vec<Vec<u8>>, Option<AdapterError>) {
    let mut out = Vec::new();
    let mut first: Option<AdapterError> = None;
    framer.push(bytes);
    loop {
        match framer.next() {
            Ok(Some(m)) => out.push(m),
            Ok(None) => break,
            Err(e) => {
                let fatal = e.fatal;
                // fatal for this unit only: the source itself can go on
                first.get_or_insert(AdapterError::new(&e.kind, e.msg));
                if fatal {
                    let _ = framer.finish();
                    return (out, first);
                }
            }
        }
    }
    match framer.finish() {
        Ok(Some(m)) => out.push(m),
        Ok(None) => {}
        Err(e) => {
            first.get_or_insert(AdapterError::new(&e.kind, e.msg));
        }
    }
    (out, first)
}

/// A framing as stated on a command line.
#[derive(Debug, Clone, PartialEq)]
pub enum FrameSpec {
    Newline,
    Length { n: usize, big: bool },
    Fixed { n: usize },
    Start { start: u8, n: usize, big: bool, total: bool },
    /// A length field at an offset of the frame: `whole` when it counts the
    /// whole frame, else the bytes after it.
    LengthAt { at: usize, n: usize, big: bool, whole: bool },
    Whole,
    /// MAVLink 2 frames, each payload zero-filled to its message's full
    /// length. `lengths` maps a message id to that length; the caller fills it
    /// from the loaded packs (`mavlink2_lengths`).
    Mavlink2 { lengths: std::sync::Arc<std::collections::BTreeMap<u32, usize>> },
}

/// A framing and its options.
#[derive(Debug, Clone, PartialEq)]
pub struct Framing {
    pub spec: FrameSpec,
    /// The maximum size of one message.
    pub max: usize,
    /// A binary message is carried as hexadecimal text inside the frame.
    pub hex: bool,
}

fn bad(s: &str, why: &str) -> AdapterError {
    AdapterError::fatal("bad-frame", format!("`{}`: {}", s, why))
}
fn num(s: &str, whole: &str) -> Result<usize, AdapterError> {
    let r = match s.strip_prefix("0x") {
        Some(h) => usize::from_str_radix(h, 16),
        None => s.parse(),
    };
    r.map_err(|_| bad(whole, &format!("`{}` is not a number", s)))
}
fn endian(s: &str, whole: &str) -> Result<bool, AdapterError> {
    match s {
        "be" => Ok(true),
        "le" => Ok(false),
        _ => Err(bad(whole, "byte order is `be` or `le`")),
    }
}
fn len_bytes(s: &str, whole: &str) -> Result<usize, AdapterError> {
    match num(s, whole)? {
        n @ (1 | 2 | 4 | 8) => Ok(n),
        _ => Err(bad(whole, "a length is 1, 2, 4 or 8 bytes")),
    }
}

impl Framing {
    pub fn whole() -> Framing {
        Framing { spec: FrameSpec::Whole, max: DEFAULT_MAX, hex: false }
    }
    pub fn of(spec: FrameSpec) -> Framing {
        Framing { spec, max: DEFAULT_MAX, hex: false }
    }

    /// Read a framing:
    ///
    /// ```text
    /// newline                       one message per line
    /// len:<N>:<be|le>               a length of N bytes, then the message
    /// fixed:<N>                     every message is N bytes
    /// start:<byte>:len:<N>:<be|le>  a start byte, a length, then the message
    /// start:<byte>:len:<N>:<be|le>:total   the length counts the whole frame, which is the message
    /// at:<K>:len:<N>:<be|le>:whole  a length of N bytes at offset K counts the whole frame, which is the message
    /// at:<K>:len:<N>:<be|le>:rest   a length of N bytes at offset K counts the bytes after it; the frame is the message
    /// whole                         the whole datagram, file or document (also: datagram, file, document)
    /// mavlink2                      MAVLink 2 frames; a payload trimmed of trailing zeros is zero-filled
    /// ```
    ///
    /// then, after commas, `max=<bytes>` and `hex`.
    pub fn parse(s: &str) -> Result<Framing, AdapterError> {
        let mut parts = s.split(',');
        let head = parts.next().unwrap_or("");
        let f: Vec<&str> = head.split(':').collect();
        let spec = match f.as_slice() {
            ["newline"] => FrameSpec::Newline,
            ["mavlink2"] => FrameSpec::Mavlink2 { lengths: Default::default() },
            ["whole"] | ["datagram"] | ["file"] | ["document"] => FrameSpec::Whole,
            ["len", n, e] => FrameSpec::Length { n: len_bytes(n, s)?, big: endian(e, s)? },
            ["len", n] if *n == "1" => FrameSpec::Length { n: 1, big: true },
            ["fixed", n] => match num(n, s)? {
                0 => return Err(bad(s, "a fixed size is at least 1")),
                n => FrameSpec::Fixed { n },
            },
            ["start", b, "len", n, rest @ ..] => {
                let start = num(b, s)?;
                if start > 255 {
                    return Err(bad(s, "the start byte is 0 to 255"));
                }
                let n = len_bytes(n, s)?;
                let (big, total) = match rest {
                    [e] => (endian(e, s)?, false),
                    [e, "total"] => (endian(e, s)?, true),
                    [] if n == 1 => (true, false),
                    _ => return Err(bad(s, "expected start:<byte>:len:<N>:<be|le>[:total]")),
                };
                FrameSpec::Start { start: start as u8, n, big, total }
            }
            ["at", k, "len", n, e, w] => FrameSpec::LengthAt {
                at: num(k, s)?,
                n: len_bytes(n, s)?,
                big: endian(e, s)?,
                whole: match *w {
                    "whole" => true,
                    "rest" => false,
                    _ => return Err(bad(s, "the length counts the `whole` frame or the `rest` after it")),
                },
            },
            ["at", ..] => return Err(bad(s, "expected at:<offset>:len:<N>:<be|le>:<whole|rest>")),
            _ => return Err(bad(s, "expected newline, len:<N>:<be|le>, fixed:<N>, start:<byte>:len:<N>:<be|le>[:total], at:<offset>:len:<N>:<be|le>:<whole|rest>, mavlink2 or whole")),
        };
        let mut fr = Framing::of(spec);
        for opt in parts {
            match opt.split_once('=') {
                None if opt == "hex" => fr.hex = true,
                Some(("max", v)) => fr.max = num(v, s)?,
                _ => return Err(bad(s, &format!("unknown option `{}` (options are max=<bytes> and hex)", opt))),
            }
        }
        Ok(fr)
    }

    /// A new framer with an empty buffer. One per stream.
    pub fn build(&self) -> Box<dyn Framer> {
        match &self.spec {
            FrameSpec::Newline => Box::new(Newline::new(self.max)),
            FrameSpec::Length { n, big } => Box::new(LengthPrefix::new(*n, *big, self.max)),
            FrameSpec::Fixed { n } => Box::new(Fixed::new(*n)),
            FrameSpec::Start { start, n, big, total } => Box::new(StartLength::new(*start, *n, *big, *total, self.max)),
            FrameSpec::LengthAt { at, n, big, whole } => Box::new(LengthAt::new(*at, *n, *big, *whole, self.max)),
            FrameSpec::Whole => Box::new(Whole::new(self.max)),
            FrameSpec::Mavlink2 { lengths } => Box::new(Mavlink2::new(lengths.clone())),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn gpi_lengths() -> std::sync::Arc<std::collections::BTreeMap<u32, usize>> {
        let mut m = std::collections::BTreeMap::new();
        mavlink2_lengths("kind heartbeat\nwhen 0:56:24 0\nwhen 0:8:8 9\nkind global_position_int\nwhen      0:56:24 33\nwhen      0:8:8 28\n", &mut m);
        std::sync::Arc::new(m)
    }
    fn frame(id: u32, payload: &[u8]) -> Vec<u8> {
        let mut f = vec![0xFD, payload.len() as u8, 0, 0, 7, 1, 1, id as u8, (id >> 8) as u8, (id >> 16) as u8];
        f.extend_from_slice(payload);
        f.extend_from_slice(&[0xAB, 0xCD]);
        f
    }

    #[test]
    fn mavlink2_lengths_from_a_pack() {
        let m = gpi_lengths();
        assert_eq!(m.get(&0), Some(&9));
        assert_eq!(m.get(&33), Some(&28));
        assert_eq!(m.len(), 2);
    }

    #[test]
    fn mavlink2_zero_fills_a_trimmed_payload() {
        let fr = Framing { spec: FrameSpec::Mavlink2 { lengths: gpi_lengths() }, max: DEFAULT_MAX, hex: false };
        let mut f = fr.build();
        let trimmed: Vec<u8> = (1..=27).collect(); // GLOBAL_POSITION_INT with hdg's high byte trimmed
        let (msgs, err) = frame_unit(f.as_mut(), &frame(33, &trimmed));
        assert!(err.is_none());
        assert_eq!(msgs.len(), 1);
        let m = &msgs[0];
        assert_eq!(m[1], 28, "LEN is the full length");
        assert_eq!(&m[10..37], &trimmed[..]);
        assert_eq!(m[37], 0, "the trimmed byte reads zero");
        assert_eq!(&m[38..], &[0xAB, 0xCD], "checksum carried");
    }

    #[test]
    fn mavlink2_full_unknown_v1_and_several_in_one_datagram() {
        let fr = Framing::parse("mavlink2").unwrap();
        let fr = Framing { spec: FrameSpec::Mavlink2 { lengths: gpi_lengths() }, ..fr };
        let full: Vec<u8> = vec![5; 28];
        let mut unit = frame(33, &full);
        unit.extend(frame(999, &[1, 2, 3])); // an id no pack names: unchanged
        unit.extend([0xFE, 2, 0, 1, 1, 0, 9, 9, 0xAA, 0xBB]); // MAVLink 1: unchanged
        unit.extend([0x00, 0x11]); // noise before the next STX is skipped
        unit.extend(frame(0, &[1, 2])); // heartbeat trimmed to 2 bytes
        let mut f = fr.build();
        let (msgs, err) = frame_unit(f.as_mut(), &unit);
        assert!(err.is_none(), "{:?}", err.map(|e| e.kind));
        assert_eq!(msgs.len(), 4);
        assert_eq!(msgs[0], frame(33, &full));
        assert_eq!(msgs[1], frame(999, &[1, 2, 3]));
        assert_eq!(msgs[2][0], 0xFE);
        assert_eq!(msgs[3][1], 9);
        assert_eq!(&msgs[3][10..19], &[1, 2, 0, 0, 0, 0, 0, 0, 0]);
    }

    #[test]
    fn mavlink2_an_incomplete_frame_is_truncated() {
        let fr = Framing { spec: FrameSpec::Mavlink2 { lengths: gpi_lengths() }, max: DEFAULT_MAX, hex: false };
        let mut f = fr.build();
        let mut fr_bytes = frame(33, &[1; 28]);
        fr_bytes.truncate(20);
        let (msgs, err) = frame_unit(f.as_mut(), &fr_bytes);
        assert!(msgs.is_empty());
        assert_eq!(err.unwrap().kind, "frame-truncated");
    }

    fn drain(f: &mut dyn Framer) -> Vec<Vec<u8>> {
        let mut v = Vec::new();
        while let Some(m) = f.next().unwrap() {
            v.push(m);
        }
        v
    }
    /// Wrap the messages, feed the bytes back one at a time, expect the messages.
    fn roundtrip(spec: &str, msgs: &[&[u8]]) {
        let fr = Framing::parse(spec).unwrap();
        let mut wire = Vec::new();
        for m in msgs {
            fr.build().wrap(m, &mut wire).unwrap();
        }
        let mut f = fr.build();
        let mut got = Vec::new();
        for b in &wire {
            f.push(&[*b]);
            got.extend(drain(f.as_mut()));
        }
        got.extend(f.finish().unwrap());
        assert_eq!(got, msgs.iter().map(|m| m.to_vec()).collect::<Vec<_>>(), "{}", spec);
    }

    #[test]
    fn every_stream_framer_round_trips_byte_by_byte() {
        let msgs: [&[u8]; 3] = [b"alpha", b"b", b"gamma gamma"];
        for spec in ["newline", "len:1", "len:2:be", "len:2:le", "len:4:be", "len:4:le", "len:8:be", "len:8:le", "start:0xaa:len:2:be", "start:170:len:1"] {
            roundtrip(spec, &msgs);
        }
        roundtrip("fixed:3", &[b"abc", b"def"]);
    }

    #[test]
    fn newline_removes_cr_skips_empty_lines_and_takes_an_unterminated_last_line() {
        let mut f = Newline::new(100);
        f.push(b"one\r\n\n\r\ntwo\nthree");
        assert_eq!(drain(&mut f), vec![b"one".to_vec(), b"two".to_vec()]);
        assert_eq!(f.finish().unwrap(), Some(b"three".to_vec()));
        assert_eq!(f.finish().unwrap(), None);
    }

    #[test]
    fn newline_refuses_a_message_with_a_line_feed_and_a_line_past_the_maximum() {
        let f = Newline::new(4);
        assert_eq!(f.wrap(b"a\nb", &mut Vec::new()).unwrap_err().kind, "frame-mismatch");
        let mut f = Newline::new(4);
        f.push(b"12345");
        let e = f.next().unwrap_err();
        assert_eq!((e.kind.as_str(), e.fatal), ("frame-oversize", true));
    }

    #[test]
    fn length_prefix_byte_orders() {
        let mut out = Vec::new();
        LengthPrefix::new(2, true, 100).wrap(b"abc", &mut out).unwrap();
        assert_eq!(out, [0, 3, b'a', b'b', b'c']);
        out.clear();
        LengthPrefix::new(4, false, 100).wrap(b"abc", &mut out).unwrap();
        assert_eq!(out, [3, 0, 0, 0, b'a', b'b', b'c']);
    }

    #[test]
    fn length_prefix_refuses_oversize_truncation_and_a_length_that_does_not_fit() {
        let mut f = LengthPrefix::new(2, true, 10);
        f.push(&[0, 11]);
        let e = f.next().unwrap_err();
        assert_eq!((e.kind.as_str(), e.fatal), ("frame-oversize", true));
        let mut f = LengthPrefix::new(2, true, 10);
        f.push(&[0, 4, 1, 2]);
        assert_eq!(f.next().unwrap(), None);
        assert_eq!(f.finish().unwrap_err().kind, "frame-truncated");
        let e = LengthPrefix::new(1, true, 1000).wrap(&[0u8; 256], &mut Vec::new()).unwrap_err();
        assert_eq!(e.kind, "frame-mismatch");
    }

    #[test]
    fn length_prefix_carries_an_empty_message() {
        let mut f = LengthPrefix::new(1, true, 10);
        f.push(&[0, 1, 7]);
        assert_eq!(drain(&mut f), vec![vec![], vec![7]]);
    }

    #[test]
    fn fixed_refuses_another_size_and_a_short_tail() {
        assert_eq!(Fixed::new(3).wrap(b"ab", &mut Vec::new()).unwrap_err().kind, "frame-mismatch");
        let mut f = Fixed::new(3);
        f.push(b"abcde");
        assert_eq!(drain(&mut f), vec![b"abc".to_vec()]);
        assert_eq!(f.finish().unwrap_err().kind, "frame-truncated");
    }

    #[test]
    fn start_length_reports_skipped_bytes_and_continues() {
        let mut f = StartLength::new(0xaa, 1, true, false, 100);
        f.push(&[1, 2, 3, 0xaa, 2, 9, 8, 0xaa, 1, 7]);
        let e = f.next().unwrap_err();
        assert_eq!((e.kind.as_str(), e.fatal), ("frame-desync", false));
        assert!(e.msg.contains("skipped 3 bytes"), "{}", e.msg);
        assert_eq!(drain(&mut f), vec![vec![9, 8], vec![7]]);
        assert_eq!(f.finish().unwrap(), None);
    }

    #[test]
    fn start_length_total_yields_the_whole_frame() {
        // two ASTERIX-shaped blocks: category byte, 2-byte whole length, body
        let a = [0x3e, 0, 5, 1, 2];
        let b = [0x3e, 0, 4, 9];
        let mut f = StartLength::new(0x3e, 2, true, true, 100);
        f.push(&a);
        f.push(&b);
        assert_eq!(drain(&mut f), vec![a.to_vec(), b.to_vec()]);
        let mut out = Vec::new();
        f.wrap(&a, &mut out).unwrap();
        assert_eq!(out, a);
        assert_eq!(f.wrap(&[0x3e, 0, 9, 1], &mut out).unwrap_err().kind, "frame-mismatch");
        // a whole length shorter than the header cannot be a frame
        f.push(&[0x3e, 0, 1]);
        assert_eq!(f.next().unwrap_err().kind, "frame-desync");
    }

    #[test]
    fn whole_is_one_message_per_unit_and_is_bounded() {
        let mut f = Whole::new(8);
        f.push(b"<a>");
        f.push(b"</a>");
        assert_eq!(f.next().unwrap(), None);
        assert_eq!(f.finish().unwrap(), Some(b"<a></a>".to_vec()));
        assert_eq!(f.finish().unwrap(), None);
        f.push(b"123456789abcdef");
        assert_eq!(f.next().unwrap_err().kind, "frame-oversize");
        assert_eq!(f.finish().unwrap_err().kind, "frame-oversize");
        let mut out = Vec::new();
        f.wrap(b"x", &mut out).unwrap();
        assert_eq!(out, b"x");
    }

    #[test]
    fn frame_unit_frames_a_datagram() {
        let mut w = Framing::whole().build();
        assert_eq!(frame_unit(w.as_mut(), b"one"), (vec![b"one".to_vec()], None));
        let mut n = Framing::parse("newline").unwrap().build();
        assert_eq!(frame_unit(n.as_mut(), b"a\nb\n").0.len(), 2);
        // a datagram with a cut message: what framed is kept, the cut is an error, the next datagram is clean
        let mut l = Framing::parse("len:1").unwrap().build();
        let (msgs, e) = frame_unit(l.as_mut(), &[1, 7, 5, 1]);
        assert_eq!(msgs, vec![vec![7]]);
        assert_eq!(e.unwrap().kind, "frame-truncated");
        assert_eq!(frame_unit(l.as_mut(), &[1, 8]), (vec![vec![8]], None));
    }

    #[test]
    fn parse_reads_every_form_and_refuses_the_rest() {
        assert_eq!(Framing::parse("len:4:be").unwrap().spec, FrameSpec::Length { n: 4, big: true });
        assert_eq!(Framing::parse("len:2:le").unwrap().spec, FrameSpec::Length { n: 2, big: false });
        assert_eq!(Framing::parse("fixed:25").unwrap().spec, FrameSpec::Fixed { n: 25 });
        assert_eq!(
            Framing::parse("start:0x3e:len:2:be:total").unwrap().spec,
            FrameSpec::Start { start: 0x3e, n: 2, big: true, total: true }
        );
        for w in ["whole", "datagram", "file", "document"] {
            assert_eq!(Framing::parse(w).unwrap().spec, FrameSpec::Whole);
        }
        let f = Framing::parse("newline,hex,max=1024").unwrap();
        assert_eq!((f.spec, f.hex, f.max), (FrameSpec::Newline, true, 1024));
        for bad in ["", "lines", "len:3:be", "len:2", "len:2:xe", "fixed:0", "start:300:len:1", "newline,loud", "start:1:len:2",
                    "at:2:len:2:be", "at:2:len:3:be:whole", "at:x:len:2:be:whole", "at:2:len:2:be:total"] {
            assert_eq!(Framing::parse(bad).unwrap_err().kind, "bad-frame", "{}", bad);
        }
        assert_eq!(
            Framing::parse("at:2:len:2:be:whole").unwrap().spec,
            FrameSpec::LengthAt { at: 2, n: 2, big: true, whole: true }
        );
        assert_eq!(
            Framing::parse("at:0x1:len:1:le:rest").unwrap().spec,
            FrameSpec::LengthAt { at: 1, n: 1, big: false, whole: false }
        );
    }

    // Invented blocks: a type octet, a flags octet, a 2-byte big-endian length
    // of the whole block, then the rest.
    fn block(kind: u8, body: &[u8]) -> Vec<u8> {
        let len = (4 + body.len()) as u16;
        let mut b = vec![kind, 0x10];
        b.extend_from_slice(&len.to_be_bytes());
        b.extend_from_slice(body);
        b
    }

    #[test]
    fn a_length_at_offset_2_cuts_a_stream_of_blocks_however_it_arrives() {
        let blocks = [block(0x01, &[0xaa, 0xbb, 0xcc]), block(0x02, &[]), block(0x07, &[1, 2, 3, 4, 5, 6, 7, 8, 9])];
        let stream: Vec<u8> = blocks.concat();
        // one byte at a time, then in two halves: the same three blocks
        for chunk in [1, stream.len() / 2 + 1, stream.len()] {
            let mut f = Framing::parse("at:2:len:2:be:whole").unwrap().build();
            let mut got = Vec::new();
            for c in stream.chunks(chunk) {
                f.push(c);
                while let Some(m) = f.next().unwrap() {
                    got.push(m);
                }
            }
            assert_eq!(got, blocks.to_vec(), "chunks of {}", chunk);
            assert_eq!(f.finish().unwrap(), None);
        }
        // wrap writes a block as it is, and only one whose length is its size
        let f = Framing::parse("at:2:len:2:be:whole").unwrap().build();
        let mut out = Vec::new();
        f.wrap(&blocks[0], &mut out).unwrap();
        assert_eq!(out, blocks[0]);
        let mut wrong = blocks[0].clone();
        wrong[3] += 1;
        assert_eq!(f.wrap(&wrong, &mut out).unwrap_err().kind, "frame-mismatch");
    }

    #[test]
    fn a_length_at_an_offset_counting_the_rest_and_the_errors() {
        // a length of one byte at offset 1 counting the rest: 3 bytes after
        // it make a frame of 5
        let mut f = Framing::parse("at:1:len:1:be:rest").unwrap().build();
        f.push(&[0x09, 0x03, 0xa1, 0xa2, 0xa3, 0x09, 0x00]);
        assert_eq!(f.next().unwrap(), Some(vec![0x09, 0x03, 0xa1, 0xa2, 0xa3]));
        assert_eq!(f.next().unwrap(), Some(vec![0x09, 0x00]));
        assert_eq!(f.next().unwrap(), None);
        // a whole-frame length shorter than its own field is skipped a byte at a time
        let mut f = Framing::parse("at:2:len:2:be:whole").unwrap().build();
        f.push(&[0x01, 0x10, 0x00, 0x03]);
        assert_eq!(f.next().unwrap_err().kind, "frame-desync");
        // a frame above max is skipped too
        let mut f = Framing::parse("at:2:len:2:be:whole,max=16").unwrap().build();
        f.push(&[0x01, 0x10, 0x00, 0x20]);
        assert_eq!(f.next().unwrap_err().kind, "frame-desync");
        // a block cut short at the end is frame-truncated
        let mut f = Framing::parse("at:2:len:2:be:whole").unwrap().build();
        f.push(&block(0x01, &[1, 2, 3])[..5]);
        assert_eq!(f.next().unwrap(), None);
        assert_eq!(f.finish().unwrap_err().kind, "frame-truncated");
    }
}
