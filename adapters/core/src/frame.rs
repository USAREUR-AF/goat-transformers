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
    Whole,
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
    /// whole                         the whole datagram, file or document (also: datagram, file, document)
    /// ```
    ///
    /// then, after commas, `max=<bytes>` and `hex`.
    pub fn parse(s: &str) -> Result<Framing, AdapterError> {
        let mut parts = s.split(',');
        let head = parts.next().unwrap_or("");
        let f: Vec<&str> = head.split(':').collect();
        let spec = match f.as_slice() {
            ["newline"] => FrameSpec::Newline,
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
            _ => return Err(bad(s, "expected newline, len:<N>:<be|le>, fixed:<N>, start:<byte>:len:<N>:<be|le>[:total] or whole")),
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
        match self.spec {
            FrameSpec::Newline => Box::new(Newline::new(self.max)),
            FrameSpec::Length { n, big } => Box::new(LengthPrefix::new(n, big, self.max)),
            FrameSpec::Fixed { n } => Box::new(Fixed::new(n)),
            FrameSpec::Start { start, n, big, total } => Box::new(StartLength::new(start, n, big, total, self.max)),
            FrameSpec::Whole => Box::new(Whole::new(self.max)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
        for bad in ["", "lines", "len:3:be", "len:2", "len:2:xe", "fixed:0", "start:300:len:1", "newline,loud", "start:1:len:2"] {
            assert_eq!(Framing::parse(bad).unwrap_err().kind, "bad-frame", "{}", bad);
        }
    }
}
