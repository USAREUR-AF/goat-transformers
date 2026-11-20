#!/usr/bin/env python3
"""ietf-headers-2-vectors: write the vectors of the second set of IETF header packs.

Packs: rtp-header, rtcp-header, arp-ipv4-ethernet, gre-header, vxlan-header,
mpls-label-entry, igmpv2, sctp-common-header, bfd-control.

Python 3 standard library only; imports no engine and reads no pack.def. The
layouts below are this program's own restatement of RFC 3550 sections 5.1,
6.4.1 and 6.4.2, RFC 826 (with the IPv4 type of RFC 894), RFC 2784 with RFC
2890, RFC 7348 section 5, RFC 3032 section 2.1, RFC 2236 section 2, RFC 9260
section 3.1 and RFC 5880 section 4.1: each header is a list of (field, bits) in
wire order, most significant bit first, multi-octet fields in network
(big-endian) order.

Inputs: headers built here field by field, from values chosen here. No message
is taken from a document. Addresses are from the documentation ranges
(192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24 of RFC 5737; the multicast
block 233.252.0.0/24 of RFC 5771; Ethernet addresses 00-00-5E-00-53-00 to
00-00-5E-00-53-FF of RFC 7042). The IGMP checksum is computed here by the ones'
complement sum RFC 2236 defines; the GRE, SCTP and other checksums are values
chosen here and say nothing of the content (the packs carry them, they do not
compute or check them).

Every `expect` is this program's packing of the header; every `model` value is
the field value that was packed. Bytes after the fixed part (CSRC list, report
blocks, payload, chunks, authentication, further stack entries) are read over
and not written back: those vectors expect the fixed part alone.

Usage: python3 -I tools/gen/ietf-headers-2-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file
differs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402


def pack(layout, values):
    """layout: [(name, bits)], most significant bit first; values: {name: int}.
    A name absent from values is 0."""
    total = sum(n for _, n in layout)
    assert total % 8 == 0, total
    acc = 0
    for name, n in layout:
        v = values.get(name, 0)
        assert 0 <= v < (1 << n), (name, v, n)
        acc = (acc << n) | v
    return acc.to_bytes(total // 8, "big")


def checksum(data):
    """Ones' complement of the ones' complement sum of 16-bit words."""
    if len(data) % 2:
        data += b"\0"
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF


def ip4(text):
    a = [int(x) for x in text.split(".")]
    return (a[0] << 24) | (a[1] << 16) | (a[2] << 8) | a[3]


def mac(text):
    return int(text.replace("-", ""), 16)


def model_of(values, keys, kind=None):
    m = {}
    if kind:
        m["@kind"] = kind
    for k in keys:
        m["inet." + k] = str(values.get(k, 0))
    return m


def vec(pack_name, name, inp, expect=None, model=None, ref="", error=None, to=None):
    v = {"name": name, "from": pack_name, "to": to or pack_name, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = ref
    return v


SRC = "built by tools/gen/ietf-headers-2-vectors.py from values chosen there; "


# ---------------------------------------------------------------------------
# RTP fixed header, RFC 3550 section 5.1: 12 octets.
RTP = [("rtp_version", 2), ("rtp_padding", 1), ("rtp_extension", 1), ("rtp_csrc_count", 4),
       ("rtp_marker", 1), ("rtp_payload_type", 7), ("rtp_sequence", 16), ("rtp_timestamp", 32),
       ("rtp_ssrc", 32)]
RTP_KEYS = [k for k, _ in RTP]


def rtp_vectors():
    out = []
    P = "rtp-header"
    a = {"rtp_version": 2, "rtp_marker": 1, "rtp_payload_type": 96, "rtp_sequence": 4660,
         "rtp_timestamp": 160000, "rtp_ssrc": 0x5EED1234}
    h = pack(RTP, a)
    out.append(vec(P, "dynamic-payload-roundtrip", h.hex(), h.hex(), model_of(a, RTP_KEYS),
                   SRC + "version 2, marker set, dynamic payload type 96, sequence 4660, timestamp 160000, "
                         "no CSRC"))
    e = {"rtp_version": 3, "rtp_padding": 1, "rtp_extension": 1, "rtp_csrc_count": 15, "rtp_marker": 1,
         "rtp_payload_type": 127, "rtp_sequence": 65535, "rtp_timestamp": 0xFFFFFFFF,
         "rtp_ssrc": 0xFFFFFFFF}
    he = pack(RTP, e)
    out.append(vec(P, "every-field-at-its-largest-roundtrip", he.hex(), he.hex(), model_of(e, RTP_KEYS),
                   SRC + "every field at its largest value, version 3 included: the pack does not check "
                         "the version"))
    c = dict(a, rtp_csrc_count=2, rtp_marker=0, rtp_payload_type=0)
    hc = pack(RTP, c)
    tail = (0x11111111).to_bytes(4, "big") + (0x22222222).to_bytes(4, "big") + bytes(160)
    out.append(vec(P, "csrc-list-and-payload-are-not-written", (hc + tail).hex(), hc.hex(),
                   model_of(c, RTP_KEYS),
                   SRC + "payload type 0 with two CSRC identifiers and 160 payload octets of zeros; the "
                         "count is kept, the identifiers and payload are read over"))
    out.append(vec(P, "eleven-octets-is-malformed", h[:11].hex(), error="malformed-wire",
                   ref=SRC + "the first vector's header cut to 11 octets"))
    return out


# ---------------------------------------------------------------------------
# RTCP SR and RR, RFC 3550 sections 6.4.1 and 6.4.2.
RTCP_HEAD = [("rtcp_version", 2), ("rtcp_padding", 1), ("rtcp_report_count", 5), ("pt", 8),
             ("rtcp_length", 16), ("rtcp_ssrc", 32)]
RTCP_SENDER = [("rtcp_ntp_ts_sec", 32), ("rtcp_ntp_ts_frac", 32), ("rtcp_rtp_timestamp", 32),
               ("rtcp_packet_count", 32), ("rtcp_octet_count", 32)]
RTCP_HEAD_KEYS = [k for k, _ in RTCP_HEAD if k != "pt"]
RTCP_SR_KEYS = RTCP_HEAD_KEYS + [k for k, _ in RTCP_SENDER]
REPORT_BLOCK = [("ssrc", 32), ("fraction_lost", 8), ("cumulative_lost", 24), ("ext_highest_seq", 32),
                ("jitter", 32), ("lsr", 32), ("dlsr", 32)]


def rtcp_vectors():
    out = []
    P = "rtcp-header"
    sr = {"rtcp_version": 2, "pt": 200, "rtcp_length": 6, "rtcp_ssrc": 0x5EED1234,
          "rtcp_ntp_ts_sec": 4004557200, "rtcp_ntp_ts_frac": 0x40000000, "rtcp_rtp_timestamp": 160000,
          "rtcp_packet_count": 1000, "rtcp_octet_count": 160000}
    h = pack(RTCP_HEAD + RTCP_SENDER, sr)
    out.append(vec(P, "sender-report-roundtrip", h.hex(), h.hex(), model_of(sr, RTCP_SR_KEYS, "sender-report"),
                   SRC + "a sender report with no report block (length 6: seven words less one), sent at "
                         "NTP time 4004557200.25 s, after 1000 packets and 160000 payload octets"))
    sr1 = dict(sr, rtcp_report_count=1, rtcp_length=12)
    h1 = pack(RTCP_HEAD + RTCP_SENDER, sr1)
    blk = pack(REPORT_BLOCK, {"ssrc": 0x0BADCAFE, "fraction_lost": 25, "cumulative_lost": 3,
                              "ext_highest_seq": 70000, "jitter": 12, "lsr": 0x1C7D4000, "dlsr": 0x8000})
    out.append(vec(P, "report-block-is-not-written", (h1 + blk).hex(), h1.hex(),
                   model_of(sr1, RTCP_SR_KEYS, "sender-report"),
                   SRC + "the sender report with one report block (count 1, length 12); the 24-octet block "
                         "is read over and not written"))
    rr = {"rtcp_version": 2, "pt": 201, "rtcp_length": 1, "rtcp_ssrc": 0x0BADCAFE}
    hr = pack(RTCP_HEAD, rr)
    out.append(vec(P, "receiver-report-roundtrip", hr.hex(), hr.hex(),
                   model_of(rr, RTCP_HEAD_KEYS, "receiver-report"),
                   SRC + "an empty receiver report: count 0, length 1, the header alone"))
    e = {"rtcp_version": 3, "rtcp_padding": 1, "rtcp_report_count": 31, "pt": 201, "rtcp_length": 65535,
         "rtcp_ssrc": 0xFFFFFFFF}
    he = pack(RTCP_HEAD, e)
    out.append(vec(P, "receiver-report-largest-values-roundtrip", he.hex(), he.hex(),
                   model_of(e, RTCP_HEAD_KEYS, "receiver-report"),
                   SRC + "a receiver report header with every field at its largest value, version 3 "
                         "included"))
    sdes = pack(RTCP_HEAD, dict(rr, pt=202))
    out.append(vec(P, "source-description-is-no-kind", sdes.hex(), error="no-kind",
                   ref=SRC + "the receiver report header with packet type 202 (source description), which "
                             "the pack does not map"))
    out.append(vec(P, "sender-report-of-27-octets-is-malformed", h[:27].hex(), error="malformed-wire",
                   ref=SRC + "the first sender report cut to 27 octets"))
    return out


# ---------------------------------------------------------------------------
# ARP, RFC 826, for IPv4 over Ethernet: 28 octets.
ARP = [("hrd", 16), ("pro", 16), ("hln", 8), ("pln", 8), ("op", 16),
       ("arp_sender_hw_addr", 48), ("arp_sender_ip_addr", 32),
       ("arp_target_hw_addr", 48), ("arp_target_ip_addr", 32)]
ARP_KEYS = ["arp_sender_hw_addr", "arp_sender_ip_addr", "arp_target_hw_addr", "arp_target_ip_addr"]
ARP_BASE = {"hrd": 1, "pro": 0x0800, "hln": 6, "pln": 4}


def arp_vectors():
    out = []
    P = "arp-ipv4-ethernet"
    q = dict(ARP_BASE, op=1, arp_sender_hw_addr=mac("00-00-5E-00-53-01"), arp_sender_ip_addr=ip4("192.0.2.1"),
             arp_target_ip_addr=ip4("192.0.2.2"))
    h = pack(ARP, q)
    out.append(vec(P, "request-roundtrip", h.hex(), h.hex(), model_of(q, ARP_KEYS, "request"),
                   SRC + "a request from 00-00-5E-00-53-01 at 192.0.2.1 for 192.0.2.2, target hardware "
                         "address 0"))
    r = dict(ARP_BASE, op=2, arp_sender_hw_addr=mac("00-00-5E-00-53-02"), arp_sender_ip_addr=ip4("192.0.2.2"),
             arp_target_hw_addr=mac("00-00-5E-00-53-01"), arp_target_ip_addr=ip4("192.0.2.1"))
    hr = pack(ARP, r)
    out.append(vec(P, "reply-roundtrip", hr.hex(), hr.hex(), model_of(r, ARP_KEYS, "reply"),
                   SRC + "the reply to that request from 00-00-5E-00-53-02"))
    e = dict(ARP_BASE, op=2, arp_sender_hw_addr=(1 << 48) - 1, arp_sender_ip_addr=0xFFFFFFFF,
             arp_target_hw_addr=(1 << 48) - 1, arp_target_ip_addr=0xFFFFFFFF)
    he = pack(ARP, e)
    out.append(vec(P, "all-ones-addresses-roundtrip", he.hex(), he.hex(), model_of(e, ARP_KEYS, "reply"),
                   SRC + "a reply whose four addresses are all ones (the 48-bit integer 281474976710655)"))
    out.append(vec(P, "ethernet-padding-is-not-written", (h + bytes(18)).hex(), h.hex(),
                   model_of(q, ARP_KEYS, "request"),
                   SRC + "the request followed by 18 zero octets, the padding that brings an Ethernet frame "
                         "to its least size"))
    out.append(vec(P, "opcode-3-is-no-kind", pack(ARP, dict(q, op=3)).hex(), error="no-kind",
                   ref=SRC + "the request with opcode 3, which RFC 826 does not define"))
    out.append(vec(P, "hardware-type-6-is-no-kind", pack(ARP, dict(q, hrd=6)).hex(), error="no-kind",
                   ref=SRC + "the request with hardware type 6, not Ethernet"))
    out.append(vec(P, "twenty-seven-octets-is-malformed", h[:27].hex(), error="malformed-wire",
                   ref=SRC + "the request cut to 27 octets"))
    return out


# ---------------------------------------------------------------------------
# GRE, RFC 2784 and RFC 2890: four octets, then the optional words.
GRE_HEAD = [("c", 1), ("gre_bit1", 1), ("k", 1), ("s", 1), ("gre_reserved0", 9), ("gre_version", 3),
            ("gre_protocol_type", 16)]


def gre(v):
    b = pack(GRE_HEAD, {"c": 1 if "gre_checksum" in v else 0, "gre_bit1": v.get("gre_bit1", 0),
                        "k": 1 if "gre_key" in v else 0, "s": 1 if "gre_sequence" in v else 0,
                        "gre_reserved0": v.get("gre_reserved0", 0), "gre_version": v.get("gre_version", 0),
                        "gre_protocol_type": v["gre_protocol_type"]})
    if "gre_checksum" in v:
        b += pack([("a", 16), ("b", 16)], {"a": v["gre_checksum"], "b": v.get("gre_reserved1", 0)})
    if "gre_key" in v:
        b += v["gre_key"].to_bytes(4, "big")
    if "gre_sequence" in v:
        b += v["gre_sequence"].to_bytes(4, "big")
    return b


def gre_model(v):
    keys = ["gre_bit1", "gre_reserved0", "gre_version", "gre_protocol_type"]
    if "gre_checksum" in v:
        keys += ["gre_checksum", "gre_reserved1"]
    if "gre_key" in v:
        keys.append("gre_key")
    if "gre_sequence" in v:
        keys.append("gre_sequence")
    return model_of(v, keys)


def gre_vectors():
    out = []
    P = "gre-header"
    base = {"gre_protocol_type": 0x0800}
    h = gre(base)
    out.append(vec(P, "base-header-roundtrip", h.hex(), h.hex(), gre_model(base),
                   SRC + "the four-octet header, no optional word, carrying IPv4 (EtherType 0x0800)"))
    k = {"gre_protocol_type": 0x86DD, "gre_key": 0x0000BEEF}
    hk = gre(k)
    out.append(vec(P, "key-only-roundtrip", hk.hex(), hk.hex(), gre_model(k),
                   SRC + "K set, key 48879, carrying IPv6 (EtherType 0x86DD): 8 octets"))
    s = {"gre_protocol_type": 0x0800, "gre_sequence": 0xFFFFFFFF}
    hs = gre(s)
    out.append(vec(P, "sequence-only-roundtrip", hs.hex(), hs.hex(), gre_model(s),
                   SRC + "S set, the largest sequence number: 8 octets"))
    a = {"gre_protocol_type": 0x6558, "gre_checksum": 0x1234, "gre_reserved1": 0, "gre_key": 7,
         "gre_sequence": 42}
    ha = gre(a)
    out.append(vec(P, "checksum-key-and-sequence-roundtrip", ha.hex(), ha.hex(), gre_model(a),
                   SRC + "C, K and S set, carrying an Ethernet frame (EtherType 0x6558): checksum 0x1234 "
                         "(a chosen value), key 7, sequence 42, 16 octets in the order checksum word, key, "
                         "sequence"))
    z = {"gre_protocol_type": 0x0800, "gre_checksum": 0, "gre_reserved1": 0}
    hz = gre(z)
    out.append(vec(P, "checksum-of-zero-keeps-the-c-bit", hz.hex(), hz.hex(), gre_model(z),
                   SRC + "C set with checksum 0 and reserved1 0: the keys are present, so the bit is "
                         "written 1"))
    e = {"gre_protocol_type": 0xFFFF, "gre_reserved0": 511, "gre_version": 7}
    he = gre(e)
    out.append(vec(P, "reserved-and-version-largest-roundtrip", he.hex(), he.hex(), gre_model(e),
                   SRC + "reserved0 bits all set and version 7: the pack does not check them"))
    r = dict(base, gre_bit1=1)
    hr = gre(r)
    out.append(vec(P, "bit-1-is-carried", hr.hex(), hr.hex(), gre_model(r),
                   SRC + "the base header with bit 1 set (routing present in RFC 1701; RFC 2784 reserves "
                         "it): a plain field, so it comes back; no routing field is read"))
    out.append(vec(P, "payload-is-not-written", (ha + bytes(20)).hex(), ha.hex(), gre_model(a),
                   SRC + "the C, K and S header followed by 20 payload octets of zeros"))
    out.append(vec(P, "key-bit-without-the-key-is-malformed", hk[:6].hex(), error="malformed-wire",
                   ref=SRC + "the K header cut to 6 octets: the key does not fit"))
    out.append(vec(P, "three-octets-is-malformed", h[:3].hex(), error="malformed-wire",
                   ref=SRC + "the base header cut to 3 octets"))
    return out


# ---------------------------------------------------------------------------
# VXLAN, RFC 7348 section 5: 8 octets.
VXLAN = [("r1", 4), ("vxlan_i_flag", 1), ("r2", 3), ("vxlan_reserved1", 24), ("vxlan_vni", 24),
         ("vxlan_reserved2", 8)]
VXLAN_KEYS = ["vxlan_i_flag", "vxlan_reserved1", "vxlan_vni", "vxlan_reserved2"]


def vxlan_vectors():
    out = []
    P = "vxlan-header"
    a = {"vxlan_i_flag": 1, "vxlan_vni": 0x123456}
    h = pack(VXLAN, a)
    out.append(vec(P, "valid-vni-roundtrip", h.hex(), h.hex(), model_of(a, VXLAN_KEYS),
                   SRC + "I flag set, VNI 1193046"))
    e = {"vxlan_i_flag": 1, "vxlan_vni": 0xFFFFFF}
    he = pack(VXLAN, e)
    out.append(vec(P, "largest-vni-roundtrip", he.hex(), he.hex(), model_of(e, VXLAN_KEYS),
                   SRC + "I flag set, the largest VNI 16777215"))
    z = {"vxlan_i_flag": 0, "vxlan_vni": 0}
    hz = pack(VXLAN, z)
    out.append(vec(P, "i-flag-clear-roundtrip", hz.hex(), hz.hex(), model_of(z, VXLAN_KEYS),
                   SRC + "all eight octets zero: I flag clear, the pack does not check it"))
    rs = dict(a, r1=15, r2=7)
    out.append(vec(P, "reserved-flag-bits-are-not-written", pack(VXLAN, rs).hex(), h.hex(),
                   model_of(a, VXLAN_KEYS),
                   SRC + "the first header with the seven reserved flag bits set: they are ignored on decode "
                         "and written 0"))
    rw = dict(a, vxlan_reserved1=0xFFFFFF, vxlan_reserved2=0xFF)
    hw = pack(VXLAN, rw)
    out.append(vec(P, "reserved-words-are-carried", hw.hex(), hw.hex(), model_of(rw, VXLAN_KEYS),
                   SRC + "the first header with the 24 and 8 reserved bits after the flags and the VNI set: "
                         "fields, so they come back"))
    out.append(vec(P, "inner-frame-is-not-written", (h + bytes(14)).hex(), h.hex(), model_of(a, VXLAN_KEYS),
                   SRC + "the first header followed by 14 zero octets standing for the inner Ethernet header"))
    out.append(vec(P, "seven-octets-is-malformed", h[:7].hex(), error="malformed-wire",
                   ref=SRC + "the first header cut to 7 octets"))
    return out


# ---------------------------------------------------------------------------
# MPLS label stack entry, RFC 3032 section 2.1: 4 octets.
MPLS = [("mpls_label", 20), ("mpls_tc", 3), ("mpls_bottom_of_stack", 1), ("mpls_ttl", 8)]
MPLS_KEYS = [k for k, _ in MPLS]


def mpls_vectors():
    out = []
    P = "mpls-label-entry"
    a = {"mpls_label": 16, "mpls_tc": 5, "mpls_bottom_of_stack": 1, "mpls_ttl": 64}
    h = pack(MPLS, a)
    out.append(vec(P, "bottom-entry-roundtrip", h.hex(), h.hex(), model_of(a, MPLS_KEYS),
                   SRC + "label 16 (the first one not reserved), traffic class 5, bottom of stack, TTL 64"))
    e = {"mpls_label": (1 << 20) - 1, "mpls_tc": 7, "mpls_bottom_of_stack": 1, "mpls_ttl": 255}
    he = pack(MPLS, e)
    out.append(vec(P, "largest-values-roundtrip", he.hex(), he.hex(), model_of(e, MPLS_KEYS),
                   SRC + "every field at its largest value, label 1048575"))
    n = {"mpls_label": 0, "mpls_tc": 0, "mpls_bottom_of_stack": 1, "mpls_ttl": 1}
    hn = pack(MPLS, n)
    out.append(vec(P, "ipv4-explicit-null-roundtrip", hn.hex(), hn.hex(), model_of(n, MPLS_KEYS),
                   SRC + "the reserved label 0 (IPv4 explicit null) at the bottom of the stack, TTL 1"))
    top = {"mpls_label": 1000, "mpls_tc": 0, "mpls_bottom_of_stack": 0, "mpls_ttl": 255}
    ht = pack(MPLS, top)
    out.append(vec(P, "second-entry-is-not-written", (ht + h).hex(), ht.hex(), model_of(top, MPLS_KEYS),
                   SRC + "a stack of two entries, label 1000 above the first vector's entry: the pack maps "
                         "the top entry only"))
    out.append(vec(P, "three-octets-is-malformed", h[:3].hex(), error="malformed-wire",
                   ref=SRC + "the first entry cut to 3 octets"))
    return out


# ---------------------------------------------------------------------------
# IGMPv2, RFC 2236 section 2: 8 octets.
IGMP = [("type", 8), ("igmp_max_resp_time", 8), ("igmp_checksum", 16), ("igmp_group_addr", 32)]
IGMP_KEYS = ["igmp_max_resp_time", "igmp_checksum", "igmp_group_addr"]


def igmp(v):
    v = dict(v, igmp_checksum=0)
    v["igmp_checksum"] = checksum(pack(IGMP, v))
    return v, pack(IGMP, v)


def igmp_vectors():
    out = []
    P = "igmpv2"
    rows = [
        ("general-query-roundtrip", "membership-query", {"type": 0x11, "igmp_max_resp_time": 100},
         "a general query: group 0, max response time 100 (10 s)"),
        ("group-specific-query-roundtrip", "membership-query",
         {"type": 0x11, "igmp_max_resp_time": 10, "igmp_group_addr": ip4("233.252.0.1")},
         "a query for group 233.252.0.1, max response time 10 (1 s)"),
        ("v2-report-roundtrip", "v2-membership-report", {"type": 0x16, "igmp_group_addr": ip4("233.252.0.1")},
         "a version 2 report for 233.252.0.1"),
        ("leave-group-roundtrip", "leave-group", {"type": 0x17, "igmp_group_addr": ip4("233.252.0.1")},
         "a leave for 233.252.0.1"),
        ("v1-report-roundtrip", "v1-membership-report", {"type": 0x12, "igmp_group_addr": ip4("233.252.0.2")},
         "a version 1 report for 233.252.0.2"),
    ]
    first = None
    for name, kind, v, what in rows:
        mv, h = igmp(v)
        first = first or h
        out.append(vec(P, name, h.hex(), h.hex(), model_of(mv, IGMP_KEYS, kind),
                       SRC + what + "; checksum 0x%04x computed here" % mv["igmp_checksum"]))
    ov, ho = igmp({"type": 0x30, "igmp_max_resp_time": 5, "igmp_group_addr": ip4("233.252.0.3")})
    om = model_of(ov, IGMP_KEYS, "other")
    om["inet.igmp_type"] = "48"
    out.append(vec(P, "unnamed-type-is-kind-other", ho.hex(), ho.hex(), om,
                   SRC + "type 0x30, which RFC 2236 does not name, read with the version 2 layout; checksum "
                         "0x%04x computed here" % ov["igmp_checksum"]))
    gv, _ = igmp(rows[2][2])
    bad = dict(gv, igmp_checksum=gv["igmp_checksum"] ^ 0xFFFF)
    hb = pack(IGMP, bad)
    out.append(vec(P, "wrong-checksum-is-carried", hb.hex(), hb.hex(),
                   model_of(bad, IGMP_KEYS, "v2-membership-report"),
                   SRC + "the version 2 report with its checksum inverted: the pack carries the checksum "
                         "and does not check it"))
    out.append(vec(P, "seven-octets-is-malformed", first[:7].hex(), error="malformed-wire",
                   ref=SRC + "the general query cut to 7 octets"))
    return out


# ---------------------------------------------------------------------------
# SCTP common header, RFC 9260 section 3.1: 12 octets.
SCTP = [("src_port", 16), ("dst_port", 16), ("sctp_verification_tag", 32), ("sctp_checksum", 32)]
SCTP_KEYS = ["src_port", "dst_port", "sctp_verification_tag", "sctp_checksum"]
UDP = [("src_port", 16), ("dst_port", 16), ("udp_length", 16), ("udp_checksum", 16)]


def sctp_vectors():
    out = []
    P = "sctp-common-header"
    a = {"src_port": 5000, "dst_port": 36412, "sctp_verification_tag": 0x2F6B19A0,
         "sctp_checksum": 0x0A0B0C0D}
    h = pack(SCTP, a)
    out.append(vec(P, "common-header-roundtrip", h.hex(), h.hex(), model_of(a, SCTP_KEYS),
                   SRC + "source port 5000, destination port 36412, a verification tag, checksum 0x0a0b0c0d "
                         "(a chosen value)"))
    z = {"src_port": 5000, "dst_port": 5001}
    hz = pack(SCTP, z)
    out.append(vec(P, "zero-tag-roundtrip", hz.hex(), hz.hex(), model_of(z, SCTP_KEYS),
                   SRC + "verification tag 0, as in a packet carrying an INIT chunk, checksum 0"))
    e = {"src_port": 65535, "dst_port": 65535, "sctp_verification_tag": 0xFFFFFFFF,
         "sctp_checksum": 0xFFFFFFFF}
    he = pack(SCTP, e)
    out.append(vec(P, "largest-values-roundtrip", he.hex(), he.hex(), model_of(e, SCTP_KEYS),
                   SRC + "every field at its largest value"))
    chunk = bytes([0, 3, 0, 20]) + bytes(16)
    out.append(vec(P, "chunks-are-not-written", (h + chunk).hex(), h.hex(), model_of(a, SCTP_KEYS),
                   SRC + "the first header followed by a 20-octet DATA chunk header and payload (type 0, "
                         "flags 3, length 20, the rest zero)"))
    out.append(vec(P, "eleven-octets-is-malformed", h[:11].hex(), error="malformed-wire",
                   ref=SRC + "the first header cut to 11 octets"))
    u = pack(UDP, {"src_port": 5000, "dst_port": 36412})
    out.append(vec(P, "ports-to-udp-header", h.hex(), u.hex(), model_of(a, SCTP_KEYS), to="udp-header",
                   ref=SRC + "the first header to udp-header: the shared keys inet.src_port and inet.dst_port "
                             "carry; UDP length and checksum are absent and written 0"))
    return out


# ---------------------------------------------------------------------------
# BFD control packet, mandatory section, RFC 5880 section 4.1: 24 octets.
BFD = [("bfd_version", 3), ("bfd_diag", 5), ("bfd_state", 2), ("bfd_poll", 1), ("bfd_final", 1),
       ("bfd_cpi", 1), ("bfd_auth_present", 1), ("bfd_demand", 1), ("bfd_multipoint", 1),
       ("bfd_detect_mult", 8), ("bfd_length", 8), ("bfd_my_disc", 32), ("bfd_your_disc", 32),
       ("bfd_desired_min_tx", 32), ("bfd_required_min_rx", 32), ("bfd_required_min_echo_rx", 32)]
BFD_KEYS = [k for k, _ in BFD]


def bfd_vectors():
    out = []
    P = "bfd-control"
    up = {"bfd_version": 1, "bfd_state": 3, "bfd_detect_mult": 3, "bfd_length": 24, "bfd_my_disc": 0x11223344,
          "bfd_your_disc": 0x55667788, "bfd_desired_min_tx": 300000, "bfd_required_min_rx": 300000}
    h = pack(BFD, up)
    out.append(vec(P, "up-session-roundtrip", h.hex(), h.hex(), model_of(up, BFD_KEYS),
                   SRC + "an Up session: detect multiplier 3, intervals of 300000 us (0.3 s), no echo"))
    down = {"bfd_version": 1, "bfd_diag": 1, "bfd_state": 1, "bfd_poll": 1, "bfd_detect_mult": 3,
            "bfd_length": 24, "bfd_my_disc": 1, "bfd_desired_min_tx": 1000000, "bfd_required_min_rx": 1000000,
            "bfd_required_min_echo_rx": 50000}
    hd = pack(BFD, down)
    out.append(vec(P, "down-with-poll-roundtrip", hd.hex(), hd.hex(), model_of(down, BFD_KEYS),
                   SRC + "a Down session after detection time expired (diagnostic 1), poll set, your "
                         "discriminator 0 (not yet known), slow rate of 1 s, echo 50000 us"))
    e = {k: (1 << n) - 1 for k, n in BFD}
    he = pack(BFD, e)
    out.append(vec(P, "largest-values-roundtrip", he.hex(), he.hex(), model_of(e, BFD_KEYS),
                   SRC + "every field at its largest value, the multipoint bit included: the pack does not "
                         "check it"))
    au = dict(up, bfd_auth_present=1, bfd_length=24 + 8)
    ha = pack(BFD, au)
    auth = bytes([1, 8, 1]) + b"pswd" + bytes(1)
    out.append(vec(P, "authentication-section-is-not-written", (ha + auth).hex(), ha.hex(),
                   model_of(au, BFD_KEYS),
                   SRC + "the Up packet with A set and an 8-octet simple password section (type 1, length "
                         "8, key ID 1, a 5-octet password); length 32 is kept, the section is read over"))
    out.append(vec(P, "twenty-three-octets-is-malformed", h[:23].hex(), error="malformed-wire",
                   ref=SRC + "the Up packet cut to 23 octets"))
    return out


PACKS = {
    "rtp-header": rtp_vectors,
    "rtcp-header": rtcp_vectors,
    "arp-ipv4-ethernet": arp_vectors,
    "gre-header": gre_vectors,
    "vxlan-header": vxlan_vectors,
    "mpls-label-entry": mpls_vectors,
    "igmpv2": igmp_vectors,
    "sctp-common-header": sctp_vectors,
    "bfd-control": bfd_vectors,
}


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
    return written


def main(argv=None):
    return genio.vector_main("ietf-headers-2-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
