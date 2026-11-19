//! Endpoint URIs: `scheme:rest[?key=value&...]`.

use crate::io;
use goat_adapters_core::frame::Framing;
use goat_adapters_core::{AdapterError, Sink, Source};

#[derive(Debug, Clone, PartialEq)]
pub struct Uri {
    pub raw: String,
    pub scheme: String,
    /// What follows `scheme:` (and `//` when present), before `?`.
    pub body: String,
    pub query: Vec<(String, String)>,
}

fn bad(raw: &str, why: impl AsRef<str>) -> AdapterError {
    AdapterError::fatal("bad-uri", format!("`{}`: {}", raw, why.as_ref()))
}

impl Uri {
    pub fn parse(raw: &str) -> Result<Uri, AdapterError> {
        let (scheme, rest) = raw.split_once(':').ok_or_else(|| bad(raw, "expected <scheme>:<rest>"))?;
        if scheme.is_empty() || !scheme.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-') {
            return Err(bad(raw, "expected <scheme>:<rest>"));
        }
        let rest = rest.strip_prefix("//").unwrap_or(rest);
        let (body, q) = rest.split_once('?').unwrap_or((rest, ""));
        let mut query = Vec::new();
        for pair in q.split('&').filter(|p| !p.is_empty()) {
            let (k, v) = pair.split_once('=').ok_or_else(|| bad(raw, format!("`{}` is not key=value", pair)))?;
            query.push((k.to_string(), v.to_string()));
        }
        Ok(Uri { raw: raw.to_string(), scheme: scheme.to_string(), body: body.to_string(), query })
    }

    pub fn q(&self, key: &str) -> Option<&str> {
        self.query.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
    }

    /// Refuse a query key this endpoint does not have.
    pub fn allow(&self, keys: &[&str]) -> Result<(), AdapterError> {
        match self.query.iter().find(|(k, _)| !keys.contains(&k.as_str())) {
            Some((k, _)) if keys.is_empty() => Err(bad(&self.raw, format!("`{}`: this endpoint takes no options", k))),
            Some((k, _)) => Err(bad(&self.raw, format!("unknown option `{}` (options: {})", k, keys.join(", ")))),
            None => Ok(()),
        }
    }

    /// `host:port`, `:port` or `[v6]:port`. The host may be empty.
    pub fn host_port(&self) -> Result<(String, u16), AdapterError> {
        let (host, port) = self.body.rsplit_once(':').ok_or_else(|| bad(&self.raw, "expected <host>:<port>"))?;
        let port: u16 = port.parse().map_err(|_| bad(&self.raw, format!("`{}` is not a port", port)))?;
        let host = host.strip_prefix('[').and_then(|h| h.strip_suffix(']')).unwrap_or(host);
        Ok((host.to_string(), port))
    }

    pub fn path(&self) -> Result<&str, AdapterError> {
        if self.body.is_empty() {
            return Err(bad(&self.raw, "expected a path"));
        }
        Ok(&self.body)
    }

    pub fn err(&self, why: impl AsRef<str>) -> AdapterError {
        bad(&self.raw, why)
    }
}

/// A transport an adapter crate adds to the command line.
pub trait Scheme {
    /// The scheme name, such as `mqtt`.
    fn name(&self) -> &'static str;
    /// One line for `--help`.
    fn help(&self) -> &'static str;
    fn source(&self, uri: &Uri, frame: Option<&Framing>) -> Result<Box<dyn Source>, AdapterError>;
    fn sink(&self, uri: &Uri, frame: Option<&Framing>) -> Result<Box<dyn Sink>, AdapterError>;
}

/// A stream has no message boundaries of its own, so its framing is stated.
fn stated<'a>(uri: &Uri, frame: Option<&'a Framing>, flag: &str) -> Result<&'a Framing, AdapterError> {
    frame.ok_or_else(|| {
        uri.err(format!(
            "a {} endpoint is a stream of bytes: state how one message is delimited with {} (newline, len:<N>:<be|le>, fixed:<N>, start:<byte>:len:<N>:<be|le>, whole)",
            uri.scheme, flag
        ))
    })
}

/// Open the endpoint messages arrive on.
pub fn open_source(raw: &str, frame: Option<&Framing>, extra: &[&dyn Scheme]) -> Result<Box<dyn Source>, AdapterError> {
    let uri = Uri::parse(raw)?;
    if let Some(s) = extra.iter().find(|s| s.name() == uri.scheme) {
        return s.source(&uri, frame);
    }
    let whole = Framing::whole();
    Ok(match uri.scheme.as_str() {
        "stdin" => {
            uri.allow(&[])?;
            Box::new(io::ReadSource::stdin(stated(&uri, frame, "--in-frame")?))
        }
        "file" => {
            uri.allow(&[])?;
            Box::new(io::ReadSource::file(uri.path()?, stated(&uri, frame, "--in-frame")?)?)
        }
        "serial" => {
            uri.allow(&[])?;
            Box::new(io::ReadSource::serial(uri.path()?, stated(&uri, frame, "--in-frame")?)?)
        }
        "dir" => {
            uri.allow(&[])?;
            Box::new(io::DirSource::open(uri.path()?, frame.unwrap_or(&whole))?)
        }
        "tcp" => {
            uri.allow(&[])?;
            let (host, port) = uri.host_port()?;
            Box::new(io::ReadSource::tcp(&host, port, stated(&uri, frame, "--in-frame")?)?)
        }
        "tcp-listen" => {
            uri.allow(&[])?;
            let (host, port) = uri.host_port()?;
            Box::new(io::TcpListenSource::bind(&host, port, stated(&uri, frame, "--in-frame")?)?)
        }
        "udp" => {
            uri.allow(&["iface"])?;
            let (host, port) = uri.host_port()?;
            Box::new(io::UdpSource::bind(&host, port, uri.q("iface"), frame.unwrap_or(&whole))?)
        }
        other => return Err(uri.err(format!("no input adapter for scheme `{}`", other))),
    })
}

/// Open an endpoint converted messages leave on.
pub fn open_sink(raw: &str, frame: Option<&Framing>, extra: &[&dyn Scheme]) -> Result<Box<dyn Sink>, AdapterError> {
    let uri = Uri::parse(raw)?;
    if let Some(s) = extra.iter().find(|s| s.name() == uri.scheme) {
        return s.sink(&uri, frame);
    }
    let whole = Framing::whole();
    Ok(match uri.scheme.as_str() {
        "stdout" => {
            uri.allow(&[])?;
            Box::new(io::WriteSink::stdout(stated(&uri, frame, "--out-frame")?))
        }
        "file" => {
            uri.allow(&["append"])?;
            let append = flag(&uri, "append")?;
            Box::new(io::WriteSink::file(uri.path()?, append, stated(&uri, frame, "--out-frame")?)?)
        }
        "serial" => {
            uri.allow(&[])?;
            Box::new(io::WriteSink::serial(uri.path()?, stated(&uri, frame, "--out-frame")?)?)
        }
        "dir" => {
            uri.allow(&["ext", "prefix", "name"])?;
            let by_origin = match uri.q("name") {
                None | Some("seq") => false,
                Some("origin") => true,
                Some(v) => return Err(uri.err(format!("name is `seq` or `origin`, not `{}`", v))),
            };
            Box::new(io::DirSink::open(
                uri.path()?,
                uri.q("prefix").unwrap_or(""),
                uri.q("ext").unwrap_or("msg"),
                by_origin,
                frame.unwrap_or(&whole),
            )?)
        }
        "tcp" => {
            uri.allow(&[])?;
            let (host, port) = uri.host_port()?;
            Box::new(io::WriteSink::tcp(&host, port, stated(&uri, frame, "--out-frame")?)?)
        }
        "tcp-listen" => {
            uri.allow(&[])?;
            let (host, port) = uri.host_port()?;
            Box::new(io::TcpListenSink::bind(&host, port, stated(&uri, frame, "--out-frame")?)?)
        }
        "udp" => {
            uri.allow(&["iface", "ttl"])?;
            let (host, port) = uri.host_port()?;
            let ttl = match uri.q("ttl") {
                None => None,
                Some(t) => Some(t.parse::<u32>().map_err(|_| uri.err("ttl is a number"))?),
            };
            Box::new(io::UdpSink::open(&host, port, uri.q("iface"), ttl, frame.unwrap_or(&whole))?)
        }
        other => return Err(uri.err(format!("no output adapter for scheme `{}`", other))),
    })
}

fn flag(uri: &Uri, key: &str) -> Result<bool, AdapterError> {
    match uri.q(key) {
        None | Some("0") => Ok(false),
        Some("1") => Ok(true),
        Some(v) => Err(uri.err(format!("{} is 0 or 1, not `{}`", key, v))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_reads_scheme_body_and_query() {
        let u = Uri::parse("udp://239.2.3.1:6969?iface=192.0.2.7").unwrap();
        assert_eq!((u.scheme.as_str(), u.body.as_str(), u.q("iface")), ("udp", "239.2.3.1:6969", Some("192.0.2.7")));
        assert_eq!(u.host_port().unwrap(), ("239.2.3.1".to_string(), 6969));
        assert_eq!(Uri::parse("tcp-listen://:9000").unwrap().host_port().unwrap(), (String::new(), 9000));
        assert_eq!(Uri::parse("tcp://[::1]:9000").unwrap().host_port().unwrap(), ("::1".to_string(), 9000));
        assert_eq!(Uri::parse("serial:/dev/ttyUSB0").unwrap().path().unwrap(), "/dev/ttyUSB0");
        assert_eq!(Uri::parse("file:out/a.json").unwrap().path().unwrap(), "out/a.json");
        assert_eq!(Uri::parse("stdin:").unwrap().body, "");
    }

    #[test]
    fn parse_refuses_what_is_not_a_uri() {
        for raw in ["", "nocolon", ":x", "UDP://:1", "udp://:1?iface"] {
            assert_eq!(Uri::parse(raw).unwrap_err().kind, "bad-uri", "{}", raw);
        }
        assert_eq!(Uri::parse("udp://host").unwrap().host_port().unwrap_err().kind, "bad-uri");
        assert_eq!(Uri::parse("udp://:99999").unwrap().host_port().unwrap_err().kind, "bad-uri");
    }

    #[test]
    fn a_stream_endpoint_needs_its_framing_stated_and_unknown_options_are_refused() {
        let e = open_source("stdin:", None, &[]).err().unwrap();
        assert!(e.msg.contains("--in-frame"), "{}", e.msg);
        let e = open_sink("stdout:", None, &[]).err().unwrap();
        assert!(e.msg.contains("--out-frame"), "{}", e.msg);
        assert!(open_source("udp://127.0.0.1:0?speed=9", None, &[]).err().unwrap().msg.contains("unknown option `speed`"));
        assert!(open_source("carrier-pigeon://x:1", None, &[]).err().unwrap().msg.contains("no input adapter"));
        assert!(open_sink("stdin:", None, &[]).err().unwrap().msg.contains("no output adapter"));
    }
}
