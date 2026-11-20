#!/usr/bin/env python3
"""ietf-headers-vectors: write the vectors of the seven IETF header packs.

Packs: ipv4-header, ipv6-header, udp-header, tcp-header, icmp-header,
ntp-header, dns-header.

Python 3 standard library only; imports no engine and reads no pack.def. The
layouts below are this program's own restatement of RFC 791 section 3.1,
RFC 8200 section 3, RFC 768, RFC 9293 section 3.1, RFC 792, RFC 5905 section
7.3 and RFC 1035 section 4.1.1: each header is a list of (field, bits) in wire
order, most significant bit first, multi-octet fields in network (big-endian)
order.

Inputs: headers built here field by field, from values chosen here. No message
is taken from a document. Addresses are from the documentation ranges
(192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24 of RFC 5737 and 2001:db8::/32
of RFC 3849), plus one link-local IPv6 address for a group with its top bit set.
Checksums are computed here by the ones' complement sum the RFCs define
(IPv4 header; UDP and TCP over the pseudo header with no data; ICMP over the
message), so each built header is one a host could send.

Every `expect` is this program's packing of the header; every `model` value is
the field value that was packed. The NTP transmit timestamp's whole seconds
also give `time_ms`: seconds times 1000 less 2208988800000, the milliseconds
from 1900-01-01 to 1970-01-01 (RFC 5905 section 6 counts from 1900). Encode
from GeoJSON rounds (time_ms + 2208988800000) / 1000 half away from zero.
Vectors from GeoJSON to ntp-header go in packs/geojson/vectors as
ntp-header-NN-*.json. Bytes after the fixed header (options, data)
are read over by the packs and not written back: those vectors expect the
fixed header alone.

Usage: python3 -I tools/gen/ietf-headers-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file
differs.
"""
import calendar
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402


def pack(layout, values):
    """layout: [(name, bits)], most significant bit first; values: {name: int}.
    A name absent from values is 0. Signed values are given as two's complement."""
    total = sum(n for _, n in layout)
    assert total % 8 == 0, total
    acc = 0
    for name, n in layout:
        v = values.get(name, 0)
        if v < 0:
            v += 1 << n
        assert 0 <= v < (1 << n), (name, v, n)
        acc = (acc << n) | v
    return acc.to_bytes(total // 8, "big")


def ones_sum(data):
    if len(data) % 2:
        data += b"\0"
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
        s = (s & 0xFFFF) + (s >> 16)
    return s


def checksum(data):
    return (~ones_sum(data)) & 0xFFFF


def ip4(text):
    a = [int(x) for x in text.split(".")]
    return (a[0] << 24) | (a[1] << 16) | (a[2] << 8) | a[3]


def ip6_groups(text):
    """The eight 16-bit groups of an IPv6 address in text form (one `::` at most)."""
    if "::" in text:
        head, tail = text.split("::")
        h = [int(x, 16) for x in head.split(":")] if head else []
        t = [int(x, 16) for x in tail.split(":")] if tail else []
        g = h + [0] * (8 - len(h) - len(t)) + t
    else:
        g = [int(x, 16) for x in text.split(":")]
    assert len(g) == 8
    return g


def model_of(prefix_values, kind=None):
    m = {}
    if kind:
        m["@kind"] = kind
    for k, v in prefix_values.items():
        m["inet." + k] = v if isinstance(v, str) else str(v)
    return m


def vec(pack_name, name, inp, expect=None, error=None, model=None, to=None, ref=""):
    v = {"name": name, "from": pack_name, "to": to or pack_name, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = ref
    return v


SRC = "built by tools/gen/ietf-headers-vectors.py from values chosen there; "

# ---------------------------------------------------------------------------
# IPv4, RFC 791 section 3.1: 20 octets before options.
IPV4 = [("ipv4_version", 4), ("ipv4_ihl", 4), ("ipv4_tos", 8), ("ipv4_total_length", 16),
        ("ipv4_identification", 16), ("ipv4_flag_reserved", 1), ("ipv4_dont_fragment", 1),
        ("ipv4_more_fragments", 1), ("ipv4_fragment_offset", 13), ("ipv4_ttl", 8),
        ("ip_protocol", 8), ("ipv4_header_checksum", 16), ("ipv4_src_addr", 32),
        ("ipv4_dst_addr", 32)]


def ipv4_header(values, options=b""):
    v = dict(values)
    v["ipv4_header_checksum"] = 0
    raw = pack(IPV4, v) + options
    v["ipv4_header_checksum"] = checksum(raw)
    return pack(IPV4, v) + options, v


def ipv4_vectors():
    out = []
    P = "ipv4-header"
    base = {"ipv4_version": 4, "ipv4_ihl": 5, "ipv4_tos": 0, "ipv4_total_length": 28,
            "ipv4_identification": 0x1C46, "ipv4_dont_fragment": 1, "ipv4_ttl": 64,
            "ip_protocol": 17, "ipv4_src_addr": ip4("192.0.2.1"), "ipv4_dst_addr": ip4("198.51.100.7")}
    h, v = ipv4_header(base)
    out.append(vec(P, "udp-datagram-header-roundtrip", h.hex(), h.hex(), model=model_of(v, "ipv4"),
                   ref=SRC + "a 28-octet UDP datagram from 192.0.2.1 to 198.51.100.7, don't fragment, TTL 64, "
                       "header checksum computed over the 20 octets"))
    frag = {"ipv4_version": 4, "ipv4_ihl": 5, "ipv4_tos": 0xB8, "ipv4_total_length": 1500,
            "ipv4_identification": 0xFFFF, "ipv4_flag_reserved": 0, "ipv4_more_fragments": 1,
            "ipv4_fragment_offset": 8191, "ipv4_ttl": 255, "ip_protocol": 6,
            "ipv4_src_addr": ip4("203.0.113.255"), "ipv4_dst_addr": ip4("255.255.255.255")}
    h2, v2 = ipv4_header(frag)
    out.append(vec(P, "fragment-edge-values-roundtrip", h2.hex(), h2.hex(), model=model_of(v2, "ipv4"),
                   ref=SRC + "a fragment with more fragments set, the largest fragment offset (8191), TTL 255, "
                       "identification 65535 and the broadcast destination 255.255.255.255 (top bit set)"))
    opt = bytes([0x94, 0x04, 0x00, 0x00])        # a 4-octet option: type 148, length 4, value 0
    o = dict(base, ipv4_ihl=6, ipv4_total_length=32)
    h3, v3 = ipv4_header(o, opt)
    data = bytes(range(8))
    out.append(vec(P, "options-and-data-are-not-written", (h3 + data).hex(), h3[:20].hex(),
                   model=model_of(v3, "ipv4"),
                   ref=SRC + "a header of IHL 6 with one 4-octet option, followed by 8 octets of data; "
                       "the pack maps the first 20 octets, so the option and data are read over and not written"))
    h6 = bytearray(h)
    h6[0] = 0x65
    out.append(vec(P, "version-6-is-no-kind", bytes(h6).hex(), error="no-kind",
                   ref=SRC + "the first datagram with its version nibble set to 6"))
    out.append(vec(P, "nineteen-octets-is-malformed", h[:19].hex(), error="malformed-wire",
                   ref=SRC + "the first datagram's header cut to 19 octets"))
    # No ipv4 -> ipv6 vector: the device profile (embedded/) refuses that plan at
    # compile time (target-unreachable) instead of at run time (no-kind).
    return out


# ---------------------------------------------------------------------------
# IPv6, RFC 8200 section 3: 40 octets.
IPV6 = ([("ipv6_version", 4), ("ipv6_traffic_class", 8), ("ipv6_flow_label", 20),
         ("ipv6_payload_length", 16), ("ip_protocol", 8), ("ipv6_hop_limit", 8)]
        + [("ipv6_src_g%d" % i, 16) for i in range(8)] + [("ipv6_dst_g%d" % i, 16) for i in range(8)])


def ipv6_values(src, dst, **kw):
    v = {"ipv6_version": 6}
    v.update(kw)
    for i, g in enumerate(ip6_groups(src)):
        v["ipv6_src_g%d" % i] = g
    for i, g in enumerate(ip6_groups(dst)):
        v["ipv6_dst_g%d" % i] = g
    return v


def ipv6_vectors():
    out = []
    P = "ipv6-header"
    v = ipv6_values("2001:db8::1", "2001:db8:0:1::53", ipv6_traffic_class=0, ipv6_flow_label=0x12345,
                    ipv6_payload_length=20, ip_protocol=6, ipv6_hop_limit=64)
    h = pack(IPV6, v)
    out.append(vec(P, "tcp-segment-header-roundtrip", h.hex(), h.hex(), model=model_of(v, "ipv6"),
                   ref=SRC + "a header for a 20-octet TCP segment from 2001:db8::1 to 2001:db8:0:1::53, "
                       "flow label 0x12345, hop limit 64"))
    v2 = ipv6_values("fe80::a00:27ff:fe4e:66a1", "ff02::1", ipv6_traffic_class=0xFF, ipv6_flow_label=0xFFFFF,
                     ipv6_payload_length=65535, ip_protocol=58, ipv6_hop_limit=255)
    h2 = pack(IPV6, v2)
    out.append(vec(P, "link-local-edge-values-roundtrip", h2.hex(), h2.hex(), model=model_of(v2, "ipv6"),
                   ref=SRC + "a link-local source (first group 0xfe80, top bit set) to the all-nodes group "
                       "ff02::1, the largest traffic class, flow label, payload length and hop limit, ICMPv6 next header"))
    h3 = h + bytes(20)
    out.append(vec(P, "payload-is-not-written", h3.hex(), h.hex(), model=model_of(v, "ipv6"),
                   ref=SRC + "the first header followed by its 20 octets of payload (zeros); the payload is read over"))
    h4 = bytearray(h)
    h4[0] = (4 << 4) | (h4[0] & 0x0F)
    out.append(vec(P, "version-4-is-no-kind", bytes(h4).hex(), error="no-kind",
                   ref=SRC + "the first header with its version nibble set to 4"))
    out.append(vec(P, "thirty-nine-octets-is-malformed", h[:39].hex(), error="malformed-wire",
                   ref=SRC + "the first header cut to 39 octets"))
    return out


# ---------------------------------------------------------------------------
# UDP, RFC 768: 8 octets. TCP, RFC 9293 section 3.1: 20 octets before options.
UDP = [("src_port", 16), ("dst_port", 16), ("udp_length", 16), ("udp_checksum", 16)]
TCP = [("src_port", 16), ("dst_port", 16), ("tcp_seq", 32), ("tcp_ack", 32), ("tcp_data_offset", 4),
       ("tcp_reserved", 4), ("tcp_cwr", 1), ("tcp_ece", 1), ("tcp_urg", 1), ("tcp_ack_flag", 1),
       ("tcp_psh", 1), ("tcp_rst", 1), ("tcp_syn", 1), ("tcp_fin", 1), ("tcp_window", 16),
       ("tcp_checksum", 16), ("tcp_urgent_pointer", 16)]


def pseudo4(src, dst, proto, length):
    return ip4(src).to_bytes(4, "big") + ip4(dst).to_bytes(4, "big") + bytes([0, proto]) + length.to_bytes(2, "big")


def udp_vectors():
    out = []
    P = "udp-header"
    v = {"src_port": 53000, "dst_port": 53, "udp_length": 8}
    v["udp_checksum"] = checksum(pseudo4("192.0.2.1", "198.51.100.7", 17, 8) + pack(UDP, v)) or 0xFFFF
    h = pack(UDP, v)
    out.append(vec(P, "header-roundtrip", h.hex(), h.hex(), model=model_of(v),
                   ref=SRC + "a UDP header with no data from port 53000 to port 53, checksum over the IPv4 "
                       "pseudo header of 192.0.2.1 to 198.51.100.7"))
    z = {"src_port": 0, "dst_port": 65535, "udp_length": 65535, "udp_checksum": 0}
    hz = pack(UDP, z)
    out.append(vec(P, "no-source-port-no-checksum-roundtrip", (hz + b"\x01\x02").hex(), hz.hex(),
                   model=model_of(z),
                   ref=SRC + "source port 0 (not used), checksum 0 (none computed), destination port and length "
                       "65535, followed by two octets of data that are read over"))
    t = {"src_port": 53000, "dst_port": 53}
    out.append(vec(P, "ports-to-tcp", h.hex(), pack(TCP, t).hex(), to="tcp-header",
                   ref=SRC + "the first header converted to tcp-header: the two ports carry, every other TCP "
                       "field is not in the entity and is written as zero bits"))
    out.append(vec(P, "seven-octets-is-malformed", h[:7].hex(), error="malformed-wire",
                   ref=SRC + "the first header cut to 7 octets"))
    return out


def tcp_vectors():
    out = []
    P = "tcp-header"
    syn = {"src_port": 49152, "dst_port": 443, "tcp_seq": 0x9C1F3A27, "tcp_ack": 0, "tcp_data_offset": 5,
           "tcp_syn": 1, "tcp_window": 64240}
    syn["tcp_checksum"] = checksum(pseudo4("192.0.2.1", "203.0.113.10", 6, 20) + pack(TCP, syn))
    h = pack(TCP, syn)
    full = dict(syn)
    for k in ("tcp_cwr", "tcp_ece", "tcp_urg", "tcp_ack_flag", "tcp_psh", "tcp_rst", "tcp_fin"):
        full[k] = 0
    full["tcp_reserved"] = 0
    full["tcp_urgent_pointer"] = 0
    out.append(vec(P, "syn-roundtrip", h.hex(), h.hex(), model=model_of(full),
                   ref=SRC + "a SYN from port 49152 to port 443, window 64240, checksum over the IPv4 pseudo "
                       "header of 192.0.2.1 to 203.0.113.10"))
    e = {"src_port": 65535, "dst_port": 1, "tcp_seq": 0xFFFFFFFF, "tcp_ack": 0x80000000, "tcp_data_offset": 15,
         "tcp_reserved": 15, "tcp_cwr": 1, "tcp_ece": 1, "tcp_urg": 1, "tcp_ack_flag": 1, "tcp_psh": 1,
         "tcp_rst": 1, "tcp_syn": 1, "tcp_fin": 1, "tcp_window": 65535, "tcp_checksum": 0xABCD,
         "tcp_urgent_pointer": 65535}
    he = pack(TCP, e)
    out.append(vec(P, "every-bit-edge-roundtrip", he.hex(), he.hex(), model=model_of(e),
                   ref=SRC + "every control bit and the reserved bits set, data offset 15, the largest sequence "
                       "number, window and urgent pointer; the checksum is a chosen value, not computed"))
    o = dict(syn, tcp_data_offset=6)
    o["tcp_checksum"] = 0
    mss = bytes([2, 4, 0x05, 0xB4])            # maximum segment size option, 1460
    o["tcp_checksum"] = checksum(pseudo4("192.0.2.1", "203.0.113.10", 6, 24) + pack(TCP, o) + mss)
    ho = pack(TCP, o)
    out.append(vec(P, "options-are-not-written", (ho + mss).hex(), ho.hex(),
                   model={"inet.tcp_data_offset": "6", "inet.tcp_syn": "1"},
                   ref=SRC + "the SYN with data offset 6 and a maximum segment size option of 1460; the option "
                       "is read over and not written"))
    out.append(vec(P, "ports-to-udp", h.hex(), pack(UDP, {"src_port": 49152, "dst_port": 443}).hex(), to="udp-header",
                   ref=SRC + "the SYN converted to udp-header: the two ports carry, length and checksum are "
                       "not in the entity and are written as zero"))
    out.append(vec(P, "nineteen-octets-is-malformed", h[:19].hex(), error="malformed-wire",
                   ref=SRC + "the SYN cut to 19 octets"))
    return out


# ---------------------------------------------------------------------------
# ICMP, RFC 792: type, code, checksum, then 32 bits that depend on the type.
ICMP_HEAD = [("icmp_type", 8), ("icmp_code", 8), ("icmp_checksum", 16)]
ICMP_REST = {
    "ids": [("icmp_identifier", 16), ("icmp_sequence", 16)],
    "unused": [("icmp_unused", 32)],
    "gateway": [("icmp_gateway_addr", 32)],
    "pointer": [("icmp_pointer", 8), ("icmp_unused", 24)],
    "timestamp": [("icmp_identifier", 16), ("icmp_sequence", 16), ("icmp_originate_ms", 32),
                  ("icmp_receive_ms", 32), ("icmp_transmit_ms", 32)],
    "rest": [("icmp_rest", 32)],
}


def icmp(shape, values, data=b""):
    layout = ICMP_HEAD + ICMP_REST[shape]
    v = dict(values)
    v["icmp_checksum"] = 0
    v["icmp_checksum"] = checksum(pack(layout, v) + data)
    return pack(layout, v), v


def icmp_vectors():
    out = []
    P = "icmp-header"
    # an original IPv4 header and 64 bits of its data, as error messages carry
    orig, _ = ipv4_header({"ipv4_version": 4, "ipv4_ihl": 5, "ipv4_total_length": 36, "ipv4_ttl": 1,
                           "ip_protocol": 17, "ipv4_src_addr": ip4("192.0.2.1"),
                           "ipv4_dst_addr": ip4("198.51.100.7")})
    orig += bytes([0xCF, 0x08, 0x82, 0x9B, 0x00, 0x10, 0x00, 0x00])
    cases = [
        ("echo", "echo-roundtrip", "ids", {"icmp_type": 8, "icmp_code": 0, "icmp_identifier": 0x4D2,
                                           "icmp_sequence": 1}, b"",
         "an echo request with identifier 1234 and sequence 1 and no data"),
        ("echo-reply", "echo-reply-roundtrip", "ids", {"icmp_type": 0, "icmp_code": 0, "icmp_identifier": 0x4D2,
                                                       "icmp_sequence": 65535}, b"",
         "an echo reply with identifier 1234 and the largest sequence number"),
        ("destination-unreachable", "port-unreachable-roundtrip", "unused",
         {"icmp_type": 3, "icmp_code": 3, "icmp_unused": 0}, orig,
         "a port unreachable (code 3) carrying an original IPv4 header and 64 bits of its data, "
         "which the pack reads over; the checksum covers them"),
        ("source-quench", "source-quench-roundtrip", "unused", {"icmp_type": 4, "icmp_code": 0, "icmp_unused": 0},
         b"", "a source quench with no original datagram"),
        ("redirect", "redirect-roundtrip", "gateway", {"icmp_type": 5, "icmp_code": 1,
                                                       "icmp_gateway_addr": ip4("192.0.2.254")}, b"",
         "a redirect for the host (code 1) to gateway 192.0.2.254"),
        ("time-exceeded", "time-exceeded-roundtrip", "unused", {"icmp_type": 11, "icmp_code": 0, "icmp_unused": 0},
         orig, "a time to live exceeded in transit (code 0) carrying the original header and data"),
        ("parameter-problem", "parameter-problem-roundtrip", "pointer",
         {"icmp_type": 12, "icmp_code": 0, "icmp_pointer": 8, "icmp_unused": 0}, b"",
         "a parameter problem pointing at octet 8 of the original header"),
        ("timestamp", "timestamp-roundtrip", "timestamp",
         {"icmp_type": 13, "icmp_code": 0, "icmp_identifier": 7, "icmp_sequence": 2,
          "icmp_originate_ms": 45296789, "icmp_receive_ms": 0, "icmp_transmit_ms": 0}, b"",
         "a timestamp request sent at 12:34:56.789 UT (45296789 ms after midnight)"),
        ("timestamp-reply", "timestamp-reply-roundtrip", "timestamp",
         {"icmp_type": 14, "icmp_code": 0, "icmp_identifier": 7, "icmp_sequence": 2,
          "icmp_originate_ms": 45296789, "icmp_receive_ms": 45296801, "icmp_transmit_ms": 86399999}, b"",
         "its reply, received 12 ms later and sent at the last millisecond of the day (86399999)"),
        ("information-request", "information-request-roundtrip", "ids",
         {"icmp_type": 15, "icmp_code": 0, "icmp_identifier": 9, "icmp_sequence": 0}, b"",
         "an information request"),
        ("information-reply", "information-reply-roundtrip", "ids",
         {"icmp_type": 16, "icmp_code": 0, "icmp_identifier": 9, "icmp_sequence": 0}, b"",
         "an information reply"),
        ("other", "unknown-type-is-other-roundtrip", "rest",
         {"icmp_type": 42, "icmp_code": 0, "icmp_rest": 0x12345678}, b"",
         "type 42, which RFC 792 does not define: the kind with no `when` takes it"),
    ]
    for kind, name, shape, values, data, why in cases:
        h, v = icmp(shape, values, data)
        out.append(vec(P, name, (h + data).hex(), h.hex(), model=model_of(v, kind), ref=SRC + why))
    ts, _ = icmp("timestamp", cases[7][3])
    out.append(vec(P, "timestamp-cut-short-is-malformed", ts[:8].hex(), error="malformed-wire",
                   ref=SRC + "the timestamp request cut to 8 octets: its kind maps 20"))
    return out


# ---------------------------------------------------------------------------
# NTP, RFC 5905 section 7.3: the 48-octet basic header.
NTP = [("ntp_leap", 2), ("ntp_version", 3), ("ntp_mode", 3), ("ntp_stratum", 8), ("ntp_poll", 8),
       ("ntp_precision", 8), ("root_delay_raw", 32), ("root_disp_raw", 32), ("refid", 32),
       ("ntp_ref_ts_sec", 32), ("ntp_ref_ts_frac", 32), ("ntp_org_ts_sec", 32), ("ntp_org_ts_frac", 32),
       ("ntp_rec_ts_sec", 32), ("ntp_rec_ts_frac", 32), ("ntp_xmt_ts_sec", 32), ("ntp_xmt_ts_frac", 32)]

TS_FIELDS = ["ntp_ref_ts_sec", "ntp_ref_ts_frac", "ntp_org_ts_sec", "ntp_org_ts_frac",
             "ntp_rec_ts_sec", "ntp_rec_ts_frac", "ntp_xmt_ts_sec", "ntp_xmt_ts_frac"]


def plain(x):
    """Shortest decimal text that reads back to the double, no exponent."""
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    r = repr(x)
    assert "e" not in r, r
    return r


def ntp_model(v, kind):
    m = {"@kind": kind}
    for k in ("ntp_leap", "ntp_version", "ntp_mode", "ntp_stratum", "ntp_poll", "ntp_precision") + tuple(TS_FIELDS):
        m["inet." + k] = str(v.get(k, 0))
    m["time_ms"] = str(v.get("ntp_xmt_ts_sec", 0) * 1000 - NTP_UNIX_MS)
    m["inet.ntp_root_delay"] = plain(v.get("root_delay_raw", 0) / 65536)
    m["inet.ntp_root_dispersion"] = plain(v.get("root_disp_raw", 0) / 65536)
    refid = v.get("refid", 0)
    if kind == "secondary":
        m["inet.ntp_ref_id"] = str(refid)
    else:
        text = refid.to_bytes(4, "big").rstrip(b"\0").decode("ascii")
        m["inet.ntp_kiss_code" if kind == "kiss-code" else "inet.ntp_ref_clock"] = text
    return m


def ascii4(s):
    return int.from_bytes(s.encode("ascii").ljust(4, b"\0"), "big")


# 2026-11-19 00:00:00 UTC in NTP era 0 seconds: Unix seconds + 2208988800 (the
# seconds from 1900-01-01 to 1970-01-01).
NTP_DAY = calendar.timegm((2026, 11, 19, 0, 0, 0)) + 2208988800
NTP_UNIX_MS = 2208988800000     # 70 years and 17 leap days, in ms


def round_half_away(num, den):
    """num / den rounded to the nearest integer, halves away from zero."""
    q, r = divmod(abs(num), den)
    if 2 * r >= den:
        q += 1
    return q if num >= 0 else -q


def geojson_time(ms):
    return json.dumps({"type": "Feature", "geometry": None, "properties": {"time_ms": ms}},
                      separators=(",", ":"))


def ntp_vectors():
    out = []
    P = "ntp-header"
    client = {"ntp_leap": 0, "ntp_version": 4, "ntp_mode": 3, "ntp_stratum": 0, "ntp_poll": 6,
              "ntp_precision": -20, "ntp_xmt_ts_sec": NTP_DAY + 3600, "ntp_xmt_ts_frac": 0x80000000}
    h = pack(NTP, client)
    out.append(vec(P, "client-request-roundtrip", h.hex(), h.hex(), model=ntp_model(client, "kiss-code"),
                   ref=SRC + "a version 4 client request, stratum 0 with a zero reference ID (the empty kiss "
                       "code), poll 2^6 s, precision 2^-20 s, transmit timestamp 2026-11-19 01:00:00.5 UTC"))
    server = {"ntp_leap": 0, "ntp_version": 4, "ntp_mode": 4, "ntp_stratum": 1, "ntp_poll": 6,
              "ntp_precision": -23, "root_delay_raw": 0, "root_disp_raw": 1000, "refid": ascii4("GPS"),
              "ntp_ref_ts_sec": NTP_DAY + 3599, "ntp_ref_ts_frac": 0xC0000000,
              "ntp_org_ts_sec": NTP_DAY + 3600, "ntp_org_ts_frac": 0x80000000,
              "ntp_rec_ts_sec": NTP_DAY + 3600, "ntp_rec_ts_frac": 0x80418937,
              "ntp_xmt_ts_sec": NTP_DAY + 3600, "ntp_xmt_ts_frac": 0x8041CA2B}
    hs = pack(NTP, server)
    out.append(vec(P, "primary-server-reply-roundtrip", hs.hex(), hs.hex(), model=ntp_model(server, "primary"),
                   ref=SRC + "the reply of a stratum 1 server whose reference clock is named GPS, root "
                       "dispersion 1000/65536 s, the origin timestamp copied from the request"))
    sec = {"ntp_leap": 3, "ntp_version": 4, "ntp_mode": 4, "ntp_stratum": 2, "ntp_poll": -128,
           "ntp_precision": 127, "root_delay_raw": 0xFFFFFFFF, "root_disp_raw": 0x00010000,
           "refid": ip4("192.0.2.123"), "ntp_ref_ts_sec": 0xFFFFFFFF, "ntp_ref_ts_frac": 0xFFFFFFFF,
           "ntp_xmt_ts_sec": NTP_DAY, "ntp_xmt_ts_frac": 1}
    hc = pack(NTP, sec)
    out.append(vec(P, "secondary-edge-values-roundtrip", hc.hex(), hc.hex(), model=ntp_model(sec, "secondary"),
                   ref=SRC + "a stratum 2 server reply whose reference ID is the IPv4 address 192.0.2.123, leap "
                       "indicator 3, the smallest poll (-128) and largest precision (127), the largest root "
                       "delay (65535.9999847412109375 s), root dispersion 1 s, the last instant of NTP era 0 "
                       "as reference timestamp"))
    kiss = {"ntp_leap": 3, "ntp_version": 4, "ntp_mode": 4, "ntp_stratum": 0, "ntp_poll": 10,
            "refid": ascii4("RATE"), "ntp_org_ts_sec": NTP_DAY + 3600, "ntp_org_ts_frac": 0x80000000}
    hk = pack(NTP, kiss)
    out.append(vec(P, "kiss-of-death-roundtrip", hk.hex(), hk.hex(), model=ntp_model(kiss, "kiss-code"),
                   ref=SRC + "a stratum 0 reply carrying the kiss code RATE"))
    ext = hs + bytes([0x00, 0x00, 0x00, 0x2A]) + bytes(16)
    out.append(vec(P, "key-id-and-digest-are-not-written", ext.hex(), hs.hex(), model=ntp_model(server, "primary"),
                   ref=SRC + "the primary server reply followed by a key identifier (42) and a 16-octet digest "
                       "of zeros; the pack maps the 48-octet header only"))
    bad = dict(kiss, refid=0x52410154)        # 'R' 'A' 0x01 'T'
    out.append(vec(P, "kiss-code-with-a-control-octet-is-transform-decode", pack(NTP, bad).hex(),
                   error="transform-decode",
                   ref=SRC + "the kiss reply with octet 0x01 in its reference ID, which `ascii` does not read"))
    out.append(vec(P, "forty-seven-octets-is-malformed", hs[:47].hex(), error="malformed-wire",
                   ref=SRC + "the primary server reply cut to 47 octets"))
    t = (NTP_DAY + 3600) * 1000 - NTP_UNIX_MS
    out.append(vec(P, "transmit-seconds-to-geojson-time", hs.hex(), geojson_time(t),
                   model=ntp_model(server, "primary"), to="geojson",
                   ref=SRC + "the primary server reply to GeoJSON: GeoJSON maps time_ms only; the transmit "
                       "seconds times 1000 less 2208988800000 give 2026-11-19 01:00:00 UTC, and the fraction "
                       "(about 0.501 s) is not added"))
    return out


def ntp_from_geojson():
    """Vectors from GeoJSON to ntp-header. The entity has no kind, so encode takes
    the first kind whose requires hold: secondary, which has none and no `when`;
    every field but the transmit seconds is absent and written zero."""
    out = []
    P = "ntp-header"
    base = (NTP_DAY + 3600) * 1000 - NTP_UNIX_MS
    for name, ms, what in (
            ("time-half-second-rounds-up", base + 500, "500 ms past the second, a half, rounds away from zero"),
            ("time-below-half-second-rounds-down", base + 499, "499 ms past the second rounds down"),
            ("time-last-second-of-era-0", (1 << 32) * 1000 - 1000 - NTP_UNIX_MS,
             "2036-02-07 06:28:15 UTC, the last whole second of era 0, gives seconds 0xFFFFFFFF"),
            ("time-ntp-epoch", -NTP_UNIX_MS, "1900-01-01 00:00:00 UTC gives seconds 0")):
        sec = round_half_away(ms + NTP_UNIX_MS, 1000)
        h = pack(NTP, {"ntp_xmt_ts_sec": sec})
        out.append(vec("geojson", name, geojson_time(ms), h.hex(), to=P,
                       ref=SRC + "a GeoJSON Feature with time_ms %d only: %s; transmit seconds %d, every other "
                           "octet zero (kind secondary)" % (ms, what, sec)))
    for name, ms, what in (
            ("time-after-era-0-is-transform-encode", (1 << 32) * 1000 - NTP_UNIX_MS,
             "2036-02-07 06:28:16 UTC needs seconds 2^32, which does not fit 32 bits"),
            ("time-before-1900-is-transform-encode", -NTP_UNIX_MS - 1000,
             "one second before 1900-01-01 needs seconds -1, which is not unsigned")):
        out.append(vec("geojson", name, geojson_time(ms), error="transform-encode", to=P,
                       ref=SRC + "a GeoJSON Feature with time_ms %d: %s" % (ms, what)))
    return out


# ---------------------------------------------------------------------------
# DNS message header, RFC 1035 section 4.1.1: 12 octets.
DNS = [("dns_id", 16), ("dns_qr", 1), ("dns_opcode", 4), ("dns_aa", 1), ("dns_tc", 1), ("dns_rd", 1),
       ("dns_ra", 1), ("dns_z", 3), ("dns_rcode", 4), ("dns_qdcount", 16), ("dns_ancount", 16),
       ("dns_nscount", 16), ("dns_arcount", 16)]
DNS_KEYS = [k for k, _ in DNS]


def dns_model(v):
    return {"inet." + k: str(v.get(k, 0)) for k in DNS_KEYS}


def dns_vectors():
    out = []
    P = "dns-header"
    q = {"dns_id": 0x1A2B, "dns_rd": 1, "dns_qdcount": 1}
    hq = pack(DNS, q)
    # the question: name example.com (RFC 2606), type A, class IN, read over by the pack
    question = b"\x07example\x03com\x00" + b"\x00\x01\x00\x01"
    out.append(vec(P, "query-roundtrip", (hq + question).hex(), hq.hex(), model=dns_model(q),
                   ref=SRC + "a standard query with recursion desired and one question (example.com, type A, "
                       "class IN), which the pack reads over"))
    r = {"dns_id": 0x1A2B, "dns_qr": 1, "dns_opcode": 0, "dns_aa": 1, "dns_rd": 1, "dns_ra": 1,
         "dns_rcode": 3, "dns_qdcount": 1, "dns_nscount": 1}
    hr = pack(DNS, r)
    out.append(vec(P, "name-error-response-roundtrip", hr.hex(), hr.hex(), model=dns_model(r),
                   ref=SRC + "an authoritative response with response code 3 (name error), one question and one "
                       "authority record"))
    e = {"dns_id": 0xFFFF, "dns_qr": 1, "dns_opcode": 15, "dns_aa": 1, "dns_tc": 1, "dns_rd": 1, "dns_ra": 1,
         "dns_z": 7, "dns_rcode": 15, "dns_qdcount": 65535, "dns_ancount": 65535, "dns_nscount": 65535,
         "dns_arcount": 65535}
    he = pack(DNS, e)
    out.append(vec(P, "every-bit-edge-roundtrip", he.hex(), he.hex(), model=dns_model(e),
                   ref=SRC + "every field at its largest value, the Z bits set"))
    out.append(vec(P, "eleven-octets-is-malformed", hq[:11].hex(), error="malformed-wire",
                   ref=SRC + "the query header cut to 11 octets"))
    return out


PACKS = {
    "ipv4-header": ipv4_vectors,
    "ipv6-header": ipv6_vectors,
    "udp-header": udp_vectors,
    "tcp-header": tcp_vectors,
    "icmp-header": icmp_vectors,
    "ntp-header": ntp_vectors,
    "dns-header": dns_vectors,
}

# Vectors whose input is another format: (pack holding them, file prefix, builder).
CROSS = [("geojson", "ntp-header", ntp_from_geojson)]


def build_files(out):
    written = {}
    for pack_name, fn in PACKS.items():
        vecs = fn()
        assert len({v["name"] for v in vecs}) == len(vecs)
        d = "packs/%s/vectors" % pack_name
        keep = set()
        for i, v in enumerate(vecs, 1):
            name = "%02d-%s.json" % (i, v["name"])
            out.write(d + "/" + name, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
            keep.add(name)
        for old in out.listdir(d):
            if old.endswith(".json") and old not in keep:
                out.remove(d + "/" + old)
        written[pack_name] = len(vecs)
    for holder, prefix, fn in CROSS:
        vecs = fn()
        assert len({v["name"] for v in vecs}) == len(vecs)
        d = "packs/%s/vectors" % holder
        keep = set()
        for i, v in enumerate(vecs, 1):
            name = "%s-%02d-%s.json" % (prefix, i, v["name"])
            out.write(d + "/" + name, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
            keep.add(name)
        for old in out.listdir(d):
            if old.startswith(prefix + "-") and old.endswith(".json") and old not in keep:
                out.remove(d + "/" + old)
        written[holder + "/" + prefix] = len(vecs)
    return written


def main(argv=None):
    return genio.vector_main("ietf-headers-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
