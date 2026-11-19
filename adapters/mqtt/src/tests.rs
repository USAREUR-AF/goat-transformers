use super::*;
use goat_adapters_core::pipeline::{Formats, Outcome, Output, Pipeline};
use std::net::TcpListener;
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};

// A broker for the tests: enough of MQTT 3.1.1 to route QoS 0 publications.
// It reads packets with this crate's `split_packet`, so the packet bytes are
// also pinned below against the specification's own layouts.
#[derive(Default)]
struct Broker {
    subs: Mutex<Vec<(String, TcpStream)>>,
    pings: AtomicU32,
    /// Stop answering after the subscription is acknowledged.
    mute: AtomicBool,
}

fn matches(filter: &str, topic: &str) -> bool {
    let (mut f, mut t) = (filter.split('/'), topic.split('/'));
    loop {
        match (f.next(), t.next()) {
            (Some("#"), _) => return true,
            (Some("+"), Some(_)) => {}
            (Some(a), Some(b)) if a == b => {}
            (None, None) => return true,
            _ => return false,
        }
    }
}

fn serve(b: Arc<Broker>, mut s: TcpStream) {
    let mut buf = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        while let Ok(Some((first, body, end))) = split_packet(&buf, 1 << 20) {
            let p: Vec<u8> = buf[body..end].to_vec();
            buf.drain(..end);
            if b.mute.load(Ordering::Relaxed) && first & 0xf0 != CONNECT && first != SUBSCRIBE {
                continue;
            }
            match first & 0xf0 {
                CONNECT => {
                    // the client identifier follows the ten bytes of the variable header
                    let n = u16::from_be_bytes([p[10], p[11]]) as usize;
                    let refused = &p[12..12 + n] == b"refused";
                    s.write_all(&[CONNACK, 2, 0, if refused { 5 } else { 0 }]).unwrap();
                }
                0x80 => {
                    let n = u16::from_be_bytes([p[2], p[3]]) as usize;
                    let filter = String::from_utf8(p[4..4 + n].to_vec()).unwrap();
                    b.subs.lock().unwrap().push((filter, s.try_clone().unwrap()));
                    s.write_all(&[SUBACK, 3, p[0], p[1], 0]).unwrap();
                }
                PUBLISH => {
                    let (topic, _) = split_publish(first, &p).unwrap();
                    let whole = packet(PUBLISH, &p).unwrap();
                    for (filter, to) in b.subs.lock().unwrap().iter_mut() {
                        if matches(filter, topic) {
                            let _ = to.write_all(&whole);
                        }
                    }
                }
                PINGREQ => {
                    b.pings.fetch_add(1, Ordering::Relaxed);
                    s.write_all(&[PINGRESP, 0]).unwrap();
                }
                _ => return,
            }
        }
        match s.read(&mut chunk) {
            Ok(0) | Err(_) => return,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
        }
    }
}

fn broker() -> (Arc<Broker>, u16) {
    let l = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = l.local_addr().unwrap().port();
    let b = Arc::new(Broker::default());
    let shared = b.clone();
    std::thread::spawn(move || {
        for s in l.incoming().flatten() {
            let b = shared.clone();
            std::thread::spawn(move || serve(b, s));
        }
    });
    (b, port)
}

fn target(port: u16, rest: &str) -> Target {
    Target::parse(&Uri::parse(&format!("mqtt://127.0.0.1:{}/{}", port, rest)).unwrap()).unwrap()
}
fn collect(src: &mut dyn Source, want: usize) -> Vec<Message> {
    let mut out = Vec::new();
    let until = Instant::now() + Duration::from_secs(10);
    while out.len() < want && Instant::now() < until {
        if let Recv::Message(m) = src.recv().unwrap() {
            out.push(m);
        }
    }
    out
}
const META: Meta = Meta { seq: 1, origin: None };

#[test]
fn packets_have_the_layout_of_the_specification() {
    // section 3.1: CONNECT, protocol name MQTT, level 4, clean session, keep-alive 60, client "c"
    assert_eq!(connect_packet("c", None, None, 60).unwrap(), [0x10, 13, 0, 4, b'M', b'Q', b'T', b'T', 4, 0x02, 0, 60, 0, 1, b'c']);
    // user name and password set bits 7 and 6 of the connect flags and follow the client identifier
    assert_eq!(
        connect_packet("c", Some("u"), Some("pw"), 0).unwrap(),
        [0x10, 20, 0, 4, b'M', b'Q', b'T', b'T', 4, 0xc2, 0, 0, 0, 1, b'c', 0, 1, b'u', 0, 2, b'p', b'w']
    );
    // section 3.8: SUBSCRIBE has the fixed flags 0010, a packet identifier, a filter and a requested QoS
    assert_eq!(subscribe_packet(1, "a/b").unwrap(), [0x82, 8, 0, 1, 0, 3, b'a', b'/', b'b', 0]);
    // section 3.3: PUBLISH at QoS 0 has no packet identifier
    assert_eq!(publish_packet("a/b", b"hi").unwrap(), [0x30, 7, 0, 3, b'a', b'/', b'b', b'h', b'i']);
    // section 2.2.3: the remaining lengths the specification gives as examples
    assert_eq!(packet(0x30, &[0; 64]).unwrap()[..2], [0x30, 0x40]);
    assert_eq!(packet(0x30, &[0; 321]).unwrap()[..3], [0x30, 0xc1, 0x02]);
    assert_eq!(packet(0x30, &[0; 16_384]).unwrap()[..4], [0x30, 0x80, 0x80, 0x01]);
}

#[test]
fn split_packet_waits_for_a_whole_packet_and_refuses_what_cannot_be_one() {
    let p = publish_packet("t", &[7; 300]).unwrap();
    for cut in [0, 1, 2, 3, p.len() - 1] {
        assert_eq!(split_packet(&p[..cut], 1000).unwrap(), None, "cut at {}", cut);
    }
    let (first, body, end) = split_packet(&p, 1000).unwrap().unwrap();
    assert_eq!((first, end), (0x30, p.len()));
    assert_eq!(split_publish(first, &p[body..end]).unwrap(), ("t", &[7u8; 300][..]));
    assert_eq!(split_packet(&p, 100).unwrap_err().kind, "frame-oversize");
    assert_eq!(split_packet(&[0x30, 0x80, 0x80, 0x80, 0x80, 0x01], 1 << 30).unwrap_err().kind, "mqtt-protocol");
    assert_eq!(split_publish(0x32, &[0, 1, b't', 0, 9]).unwrap_err().kind, "mqtt-protocol");
    assert_eq!(split_publish(0x30, &[0, 9, b't']).unwrap_err().kind, "mqtt-protocol");
}

#[test]
fn a_uri_states_broker_topic_and_options() {
    let t = Target::parse(&Uri::parse("mqtt://broker.example:8883/tracks/+/cot?client=pipe-1&user=feed&password-env=MQTT_PW&keepalive=20").unwrap()).unwrap();
    assert_eq!((t.host.as_str(), t.port, t.topic.as_str()), ("broker.example", 8883, "tracks/+/cot"));
    assert_eq!((t.client.as_str(), t.user.as_deref(), t.password_env.as_deref(), t.keepalive), ("pipe-1", Some("feed"), Some("MQTT_PW"), 20));
    let t = Target::parse(&Uri::parse("mqtt://broker.example/all/#").unwrap()).unwrap();
    assert_eq!((t.port, t.topic.as_str(), t.keepalive), (1883, "all/#", 60));
    assert!(t.client.len() <= 23, "{}", t.client);
    for bad in ["mqtt://broker.example", "mqtt://broker.example/", "mqtt:///t", "mqtt://h:x/t", "mqtt://h/t?password=secret", "mqtt://h/t?keepalive=0"] {
        assert_eq!(Target::parse(&Uri::parse(bad).unwrap()).unwrap_err().kind, "bad-uri", "{}", bad);
    }
}

#[test]
fn publications_reach_a_subscriber_one_message_each_with_the_topic_as_origin() {
    let (_b, port) = broker();
    let mut src = MqttSource::open(&target(port, "tracks/+/cot"), &Framing::whole()).unwrap();
    let mut a = MqttSink::open(&target(port, "tracks/a/cot"), &Framing::whole()).unwrap();
    let mut other = MqttSink::open(&target(port, "status/a"), &Framing::whole()).unwrap();
    a.send(b"<event/>", &META).unwrap();
    other.send(b"not for the subscriber", &META).unwrap();
    a.send(&[0, 255, 13, 10], &META).unwrap();
    a.send(&vec![b'x'; 70_000], &META).unwrap(); // larger than one read and than a two-byte remaining length
    let got = collect(&mut src, 3);
    assert_eq!(got.len(), 3);
    assert_eq!(got[0].bytes, b"<event/>");
    assert_eq!(got[1].bytes, [0, 255, 13, 10]);
    assert_eq!(got[2].bytes.len(), 70_000);
    assert!(got.iter().all(|m| m.origin.as_deref() == Some("tracks/a/cot") && m.received_ms.is_some()));
    assert!(matches!(src.recv(), Ok(Recv::Idle)));
    assert_eq!(MqttSink::open(&target(port, "tracks/#"), &Framing::whole()).err().unwrap().kind, "bad-uri");
}

#[test]
fn a_stated_framing_applies_inside_each_publication() {
    let (_b, port) = broker();
    let mut src = MqttSource::open(&target(port, "batch"), &Framing::parse("newline").unwrap()).unwrap();
    let mut sink = MqttSink::open(&target(port, "batch"), &Framing::whole()).unwrap();
    sink.send(b"one\ntwo\n", &META).unwrap();
    sink.send(b"three", &META).unwrap();
    let got: Vec<Vec<u8>> = collect(&mut src, 3).into_iter().map(|m| m.bytes).collect();
    assert_eq!(got, [&b"one"[..], b"two", b"three"]);
}

#[test]
fn a_refused_connection_and_a_missing_broker_are_errors() {
    let (_b, port) = broker();
    let e = MqttSink::open(&target(port, "t?client=refused"), &Framing::whole()).err().unwrap();
    assert_eq!(e.kind, "mqtt-refused");
    assert!(e.msg.contains("return code 5"), "{}", e.msg);
    assert_eq!(MqttSource::open(&target(1, "t"), &Framing::whole()).err().unwrap().kind, "io");
    let e = MqttSink::open(&target(port, "t?password-env=GOAT_ADAPTERS_TEST_UNSET_VARIABLE"), &Framing::whole()).err().unwrap();
    assert!(e.msg.contains("is not set"), "{}", e.msg);
}

#[test]
fn an_idle_subscription_pings_and_a_silent_broker_is_a_timeout() {
    let (b, port) = broker();
    let mut src = MqttSource::open(&target(port, "quiet?keepalive=1"), &Framing::whole()).unwrap();
    let until = Instant::now() + Duration::from_millis(1300);
    while Instant::now() < until {
        assert!(matches!(src.recv(), Ok(Recv::Idle)));
    }
    assert!(b.pings.load(Ordering::Relaxed) >= 2, "{} pings", b.pings.load(Ordering::Relaxed));
    b.mute.store(true, Ordering::Relaxed);
    let until = Instant::now() + Duration::from_secs(10);
    let e = loop {
        match src.recv() {
            Ok(_) => assert!(Instant::now() < until, "no timeout"),
            Err(e) => break e,
        }
    };
    assert_eq!((e.kind.as_str(), e.fatal), ("mqtt-timeout", true));
}

#[test]
fn cot_xml_on_one_topic_leaves_as_geojson_on_another() {
    let packs = concat!(env!("CARGO_MANIFEST_DIR"), "/../../packs");
    let only = ["cot-xml".to_string(), "geojson".to_string()];
    let f = Formats::load(&Path::new(packs).join("../model"), Path::new(packs), Some(&only), None).unwrap();
    let (_b, port) = broker();
    let mut out = MqttSource::open(&target(port, "geo/#"), &Framing::whole()).unwrap();
    let source = MqttSource::open(&target(port, "cot/#"), &Framing::whole()).unwrap();
    let sink = MqttSink::open(&target(port, "geo/tracks"), &Framing::whole()).unwrap();
    let mut p = Pipeline::new(&f, "cot-xml", Box::new(source), vec![Output { to: "geojson".into(), hex: false, sink: Box::new(sink) }]);
    p.check().unwrap();
    let stop = AtomicBool::new(false);
    let stats = p.stats.clone();
    let got = std::thread::scope(|s| {
        let run = s.spawn(|| p.run(&stop));
        let mut feed = MqttSink::open(&target(port, "cot/unit-1"), &Framing::whole()).unwrap();
        feed.send(br#"<event version="2.0" uid="J-01334" type="a-f-G-U-C" time="2021-02-27T20:00:00.000Z" how="m-g"><point lat="30.0090027" lon="-85.9578182" hae="-42.6" ce="45.3" le="99.5"/><detail><contact callsign="GATOR"/></detail></event>"#, &META).unwrap();
        feed.send(b"<event", &META).unwrap();
        let got = collect(&mut out, 1);
        // the second publication must have been counted before the run is stopped
        let until = Instant::now() + Duration::from_secs(10);
        while stats.received.load(Ordering::Relaxed) < 2 && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(20));
        }
        stop.store(true, Ordering::Relaxed);
        assert_eq!(run.join().unwrap(), Outcome::Interrupted);
        got
    });
    assert_eq!(
        String::from_utf8(got[0].bytes.clone()).unwrap(),
        r#"{"type":"Feature","geometry":{"type":"Point","coordinates":[-85.9578182,30.0090027,-42.6]},"properties":{"type":"a-f-G-U-C","time_ms":1614456000000,"how":"m-g","ce":45.3,"le":99.5,"callsign":"GATOR"},"id":"J-01334"}"#
    );
    assert_eq!(got[0].origin.as_deref(), Some("geo/tracks"));
    assert_eq!(p.stats.received.load(Ordering::Relaxed), 2);
    assert_eq!(p.stats.converted.load(Ordering::Relaxed), 1);
    assert_eq!(p.stats.failed_total(), 1);
    assert!(matches!(out.recv(), Ok(Recv::Idle)), "the message that did not convert was not published");
}
