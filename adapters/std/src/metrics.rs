//! `--metrics <addr>`: the pipeline's counters for Prometheus, as text
//! exposition format 0.0.4 on `GET /metrics`. Standard library only: one
//! thread accepts one connection at a time, reads the request line and
//! answers; any other path is 404. Nothing here can slow the pipeline: it
//! reads the counters and never takes a lock the pipeline holds for longer
//! than a copy.
//!
//! The series (every counter only rises; `format` is a pack's format name):
//!
//!   goat_xf_pipe_messages_in_total{format}     messages from the source
//!   goat_xf_pipe_messages_out_total{format}    messages converted and delivered,
//!                                              by target format (two outputs of
//!                                              one format add two)
//!   goat_xf_pipe_errors_total{stage,format,kind}
//!                                              failures: stage `decode` (the
//!                                              input's format), `encode` and
//!                                              `deliver` (the target's format),
//!                                              `source` (the input's format);
//!                                              kind is the engine's error name
//!   goat_xf_pipe_uptime_seconds                seconds since the pipeline started

use goat_adapters_core::pipeline::Stats;
use std::fmt::Write as _;
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

/// `:9464` listens on every address; `127.0.0.1:9464` on one.
pub fn bind_addr(addr: &str) -> String {
    match addr.strip_prefix(':') {
        Some(port) => format!("0.0.0.0:{}", port),
        None => addr.to_string(),
    }
}

fn label(v: &str) -> String {
    v.replace('\\', "\\\\").replace('"', "\\\"").replace('\n', "\\n")
}

/// The exposition text for these counters; `from` is the input format.
pub fn render(stats: &Stats, from: &str) -> String {
    let mut s = String::new();
    s.push_str("# HELP goat_xf_pipe_messages_in_total Messages received from the source.\n");
    s.push_str("# TYPE goat_xf_pipe_messages_in_total counter\n");
    let _ = writeln!(s, "goat_xf_pipe_messages_in_total{{format=\"{}\"}} {}", label(from), stats.received.load(Ordering::Relaxed));
    s.push_str("# HELP goat_xf_pipe_messages_out_total Messages converted and delivered, by target format.\n");
    s.push_str("# TYPE goat_xf_pipe_messages_out_total counter\n");
    for (format, n) in stats.delivered_by() {
        let _ = writeln!(s, "goat_xf_pipe_messages_out_total{{format=\"{}\"}} {}", label(&format), n);
    }
    s.push_str("# HELP goat_xf_pipe_errors_total Failures by stage (decode, encode, deliver, source), format and error name.\n");
    s.push_str("# TYPE goat_xf_pipe_errors_total counter\n");
    for ((stage, format, kind), n) in stats.failed_by() {
        let _ = writeln!(s, "goat_xf_pipe_errors_total{{stage=\"{}\",format=\"{}\",kind=\"{}\"}} {}", label(&stage), label(&format), label(&kind), n);
    }
    s.push_str("# HELP goat_xf_pipe_uptime_seconds Seconds since the pipeline started.\n");
    s.push_str("# TYPE goat_xf_pipe_uptime_seconds gauge\n");
    let _ = writeln!(s, "goat_xf_pipe_uptime_seconds {:.3}", stats.uptime_secs());
    s
}

fn answer(mut conn: TcpStream, stats: &Stats, from: &str) {
    let _ = conn.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = conn.set_write_timeout(Some(Duration::from_secs(2)));
    let mut first = String::new();
    {
        let mut reader = BufReader::new(&conn);
        if reader.read_line(&mut first).is_err() {
            return;
        }
        // the headers are read and dropped, up to the blank line
        let mut line = String::new();
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) if line == "\r\n" || line == "\n" => break,
                Ok(_) => {}
            }
        }
    }
    let mut parts = first.split_whitespace();
    let (method, path) = (parts.next().unwrap_or(""), parts.next().unwrap_or(""));
    let path = path.split('?').next().unwrap_or("");
    let (status, ctype, body) = if (method == "GET" || method == "HEAD") && path == "/metrics" {
        ("200 OK", "text/plain; version=0.0.4; charset=utf-8", render(stats, from))
    } else {
        ("404 Not Found", "text/plain; charset=utf-8", "not found: the counters are at /metrics\n".to_string())
    };
    let head = format!("HTTP/1.1 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", status, ctype, body.len());
    let _ = conn.write_all(head.as_bytes());
    if method != "HEAD" {
        let _ = conn.write_all(body.as_bytes());
    }
}

/// Listen on `addr` and answer from a thread of its own until the process
/// ends. A port that cannot be bound is an error here, before the pipeline
/// starts. Returns the address bound (useful with port 0).
pub fn serve(addr: &str, stats: Arc<Stats>, from: String) -> Result<std::net::SocketAddr, String> {
    let listener = TcpListener::bind(bind_addr(addr)).map_err(|e| format!("cannot listen on {}: {}", addr, e))?;
    let bound = listener.local_addr().map_err(|e| format!("cannot listen on {}: {}", addr, e))?;
    std::thread::Builder::new()
        .name("metrics".to_string())
        .spawn(move || {
            for conn in listener.incoming().flatten() {
                answer(conn, &stats, &from);
            }
        })
        .map_err(|e| format!("cannot start the metrics thread: {}", e))?;
    Ok(bound)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    fn get(addr: std::net::SocketAddr, path: &str) -> String {
        let mut c = TcpStream::connect(addr).unwrap();
        write!(c, "GET {} HTTP/1.1\r\nHost: x\r\n\r\n", path).unwrap();
        let mut out = String::new();
        c.read_to_string(&mut out).unwrap();
        out
    }

    #[test]
    fn the_text_names_every_series() {
        let s = Stats::default();
        s.received.store(4, Ordering::Relaxed);
        s.delivered("geojson");
        s.delivered("geojson");
        s.fail_at("decode", "cot-xml", "malformed-wire");
        s.fail_at("deliver", "geojson", "io");
        let t = render(&s, "cot-xml");
        assert!(t.contains("goat_xf_pipe_messages_in_total{format=\"cot-xml\"} 4\n"), "{}", t);
        assert!(t.contains("goat_xf_pipe_messages_out_total{format=\"geojson\"} 2\n"), "{}", t);
        assert!(t.contains("goat_xf_pipe_errors_total{stage=\"decode\",format=\"cot-xml\",kind=\"malformed-wire\"} 1\n"), "{}", t);
        assert!(t.contains("goat_xf_pipe_errors_total{stage=\"deliver\",format=\"geojson\",kind=\"io\"} 1\n"), "{}", t);
        assert!(t.contains("# TYPE goat_xf_pipe_uptime_seconds gauge\n"));
        assert_eq!(label("a\"b\\c"), "a\\\"b\\\\c");
    }

    #[test]
    fn the_server_answers_metrics_and_nothing_else() {
        let s = Arc::new(Stats::default());
        s.received.store(7, Ordering::Relaxed);
        let addr = serve("127.0.0.1:0", s.clone(), "nmea0183".to_string()).unwrap();
        let ok = get(addr, "/metrics");
        assert!(ok.starts_with("HTTP/1.1 200 OK\r\n"), "{}", ok);
        assert!(ok.contains("Content-Type: text/plain; version=0.0.4"));
        assert!(ok.contains("goat_xf_pipe_messages_in_total{format=\"nmea0183\"} 7\n"));
        assert!(get(addr, "/").starts_with("HTTP/1.1 404 Not Found\r\n"));
        // the counters are read at each request
        s.received.store(8, Ordering::Relaxed);
        assert!(get(addr, "/metrics?x=1").contains("{format=\"nmea0183\"} 8\n"));
    }

    #[test]
    fn a_colon_and_a_port_is_every_address() {
        assert_eq!(bind_addr(":9464"), "0.0.0.0:9464");
        assert_eq!(bind_addr("127.0.0.1:9464"), "127.0.0.1:9464");
        assert!(serve("256.0.0.1:1", Arc::new(Stats::default()), "x".to_string()).is_err());
    }
}
