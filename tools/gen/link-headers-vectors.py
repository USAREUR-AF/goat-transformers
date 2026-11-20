#!/usr/bin/env python3
"""link-headers-vectors: write the vectors of the link, tunnel, IPsec, QUIC and
capture-file header packs.

Packs: ethernet-ii, ppp-frame, l2tpv3-ip, l2tpv3-udp, esp-header, ah-header,
quic-invariant, pcap-file-header, pcap-record-be, pcap-record-le,
pcapng-section-header, pcapng-epb-be, pcapng-epb-le.

Python 3 standard library only; imports no engine and reads no pack.def. The
layouts below are this program's own restatement of RFC 894, RFC 7042 section 3
and RFC 7348 section 5 (Ethernet II and the C-tag), RFC 1661 and RFC 1662
(PPP), RFC 3931 (L2TPv3), RFC 4303 and RFC 4302 (ESP, AH), RFC 8999 (QUIC
invariants) and the Internet-Drafts draft-ietf-opsawg-pcap-09 and
draft-ietf-opsawg-pcapng-06: each header is a list of (field, bits) in wire
order, most significant bit first; a little-endian capture file's fields are
packed big-endian and their octets reversed, field by field.

Inputs: headers built here from values chosen here; no example of a document is
used. MAC addresses are from 00-00-5E-00-53-00/24 (RFC 7042 section 2.1.2).
Checksums, ICVs and payloads are octets chosen here.

Usage: python3 -I tools/gen/link-headers-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file
differs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402


def pack(layout, values):
    total = sum(n for _, n in layout)
    assert total % 8 == 0, total
    acc = 0
    for name, n in layout:
        v = values.get(name, 0) if isinstance(name, str) else name[1]
        if v < 0:
            v += 1 << n
        assert 0 <= v < (1 << n), (name, v, n)
        acc = (acc << n) | v
    return acc.to_bytes(total // 8, "big")


def le(n, width_bits):
    if n < 0:
        n += 1 << width_bits
    return n.to_bytes(width_bits // 8, "little")


def be(n, width_bits):
    if n < 0:
        n += 1 << width_bits
    return n.to_bytes(width_bits // 8, "big")


def mac(text):
    return int(text.replace("-", ""), 16)


def model_of(values, keys, kind=None, mod="inet"):
    m = {"@kind": kind} if kind else {}
    for k in keys:
        m["%s.%s" % (mod, k)] = str(values.get(k, 0))
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


SRC = "built by tools/gen/link-headers-vectors.py from values chosen there; "
C = lambda v: ("const", v)  # noqa: E731


# ---- Ethernet II -----------------------------------------------------------
def ethernet_vectors():
    out = []
    P = "ethernet-ii"
    d, s = mac("00-00-5E-00-53-01"), mac("00-00-5E-00-53-02")
    u = {"eth_dst_addr": d, "eth_src_addr": s, "eth_type": 0x0800}
    h = pack([("eth_dst_addr", 48), ("eth_src_addr", 48), ("eth_type", 16)], u)
    keys = ["eth_dst_addr", "eth_src_addr", "eth_type"]
    out.append(vec(P, "untagged-ipv4-payload-not-written", (h + bytes(46)).hex(), h.hex(), model_of(u, keys, "untagged"),
                   SRC + "an untagged frame carrying IPv4 (EtherType 0x0800) between two documentation MAC "
                         "addresses, followed by 46 payload octets, read over"))
    t = dict(u, vlan_tag_info=0xA064, eth_type=0x86DD)
    ht = pack([("eth_dst_addr", 48), ("eth_src_addr", 48), (C(0x8100), 16), ("vlan_tag_info", 16), ("eth_type", 16)], t)
    out.append(vec(P, "c-tagged-ipv6", ht.hex(), ht.hex(),
                   model_of(t, ["eth_dst_addr", "eth_src_addr", "vlan_tag_info", "eth_type"],
                            "c-tagged"),
                   SRC + "a frame with a C-tag (EtherType 0x8100), tag information 0xa064, carrying IPv6 (0x86DD)"))
    e = dict(t, eth_dst_addr=(1 << 48) - 1, vlan_tag_info=0xFFFF, eth_type=0xFFFF)
    he = pack([("eth_dst_addr", 48), ("eth_src_addr", 48), (C(0x8100), 16), ("vlan_tag_info", 16), ("eth_type", 16)], e)
    out.append(vec(P, "c-tagged-largest-values", he.hex(), he.hex(),
                   model_of(e, ["eth_dst_addr", "eth_src_addr", "vlan_tag_info", "eth_type"],
                            "c-tagged"),
                   SRC + "the broadcast destination, tag information 0xffff and EtherType 0xffff (the pack checks "
                         "neither)"))
    l8023 = dict(u, eth_type=46)
    hl = pack([("eth_dst_addr", 48), ("eth_src_addr", 48), ("eth_type", 16)], l8023)
    out.append(vec(P, "ieee-802-3-length-is-carried", hl.hex(), hl.hex(), model_of(l8023, keys, "untagged"),
                   SRC + "a value of 46, below 0x0600: an IEEE 802.3 length, not an EtherType; carried as the key"))
    out.append(vec(P, "c-tag-cut-short-is-malformed", ht[:16].hex(), error="malformed-wire",
                   ref=SRC + "the C-tagged frame cut to 16 octets, inside its inner EtherType"))
    out.append(vec(P, "thirteen-octets-is-malformed", h[:13].hex(), error="malformed-wire",
                   ref=SRC + "the untagged header cut to 13 octets"))
    return out


# ---- PPP -------------------------------------------------------------------
def ppp_vectors():
    out = []
    P = "ppp-frame"
    rows = [
        ("hdlc-ipv4-information-not-written", "hdlc-protocol-16", bytes([0xFF, 0x03, 0x00, 0x21]), 0x0021,
         bytes(20) + bytes([0x12, 0x34]),
         "address 0xff, control 0x03, protocol 0x0021 (IPv4), then 20 information octets and a 2-octet FCS, read over"),
        ("hdlc-lcp", "hdlc-protocol-16", bytes([0xFF, 0x03, 0xC0, 0x21]), 0xC021, b"",
         "an LCP frame (protocol 0xc021) with address and control fields"),
        ("hdlc-compressed-protocol", "hdlc-protocol-8", bytes([0xFF, 0x03, 0x21]), 0x21, b"",
         "address and control, then the 1-octet protocol 0x21 (protocol field compression)"),
        ("acfc-ipv6", "protocol-16", bytes([0x00, 0x57]), 0x0057, b"",
         "address and control field compression: the frame starts with protocol 0x0057 (IPv6)"),
        ("acfc-compressed-protocol", "protocol-8", bytes([0x21]), 0x21, bytes(4),
         "both compressions: the 1-octet protocol 0x21, then 4 octets read over"),
    ]
    for name, kind, h, proto, tail, what in rows:
        out.append(vec(P, name, (h + tail).hex(), h.hex(), {"@kind": kind, "inet.ppp_protocol": str(proto)},
                       SRC + what))
    out.append(vec(P, "hdlc-protocol-cut-short-is-malformed", "ff0300", error="malformed-wire",
                   ref=SRC + "address, control and one even protocol octet: the second octet is missing"))
    return out


# ---- L2TPv3 ----------------------------------------------------------------
CTRL = [(C(1), 1), ("l2tp_length_bit", 1), (C(0), 2), ("l2tp_sequence_bit", 1), (C(0), 7), ("l2tp_version", 4),
        ("l2tp_length", 16), ("l2tp_control_connection_id", 32), ("l2tp_ns", 16), ("l2tp_nr", 16)]
CTRL_KEYS = ["l2tp_length_bit", "l2tp_sequence_bit", "l2tp_version", "l2tp_length", "l2tp_control_connection_id",
             "l2tp_ns", "l2tp_nr"]


def l2tp_ip_vectors():
    out = []
    P = "l2tpv3-ip"
    c = {"l2tp_length_bit": 1, "l2tp_sequence_bit": 1, "l2tp_version": 3, "l2tp_length": 20,
         "l2tp_control_connection_id": 0x0000ABCD, "l2tp_ns": 1, "l2tp_nr": 2}
    h = bytes(4) + pack(CTRL, c)
    avp = bytes([0x80, 0x08, 0, 0, 0, 0, 0, 1])
    out.append(vec(P, "control-message-avps-not-written", (h + avp).hex(), h.hex(), model_of(c, CTRL_KEYS, "control"),
                   SRC + "session ID 0, then a control header (L and S set, version 3, length 20, connection 0xabcd, "
                         "Ns 1, Nr 2) and an 8-octet AVP, read over"))
    dv = {"l2tp_session_id": 0x12345678}
    hd = be(0x12345678, 32)
    out.append(vec(P, "data-session-cookie-not-written", (hd + bytes(8) + bytes(14)).hex(), hd.hex(),
                   model_of(dv, ["l2tp_session_id"], "data"),
                   SRC + "a data message for session 0x12345678 with an 8-octet cookie and payload: the cookie's "
                         "length is configured, not on the wire, so only the session ID is read"))
    he = bytes(4) + pack(CTRL, dict(c, l2tp_version=15, l2tp_length=0xFFFF, l2tp_control_connection_id=0xFFFFFFFF,
                                    l2tp_ns=0xFFFF, l2tp_nr=0xFFFF))
    out.append(vec(P, "control-largest-values", he.hex(), he.hex(),
                   model_of(dict(c, l2tp_version=15, l2tp_length=0xFFFF, l2tp_control_connection_id=0xFFFFFFFF,
                                 l2tp_ns=0xFFFF, l2tp_nr=0xFFFF), CTRL_KEYS, "control"),
                   SRC + "a control header with every field at its largest value"))
    out.append(vec(P, "control-cut-short-is-malformed", h[:14].hex(), error="malformed-wire",
                   ref=SRC + "the control message cut to 14 octets"))
    return out


def l2tp_udp_vectors():
    out = []
    P = "l2tpv3-udp"
    c = {"l2tp_length_bit": 1, "l2tp_sequence_bit": 1, "l2tp_version": 3, "l2tp_length": 12,
         "l2tp_control_connection_id": 7, "l2tp_ns": 0, "l2tp_nr": 0}
    h = pack(CTRL, c)
    out.append(vec(P, "control-message", h.hex(), h.hex(), model_of(c, CTRL_KEYS, "control"),
                   SRC + "a control header over UDP: T, L and S set, version 3, length 12 (a zero-length body), "
                         "connection 7"))
    dv = {"l2tp_version": 3, "l2tp_session_id": 0xCAFE0001}
    hd = pack([(C(0), 1), (C(0), 11), ("l2tp_version", 4), ("l2tp_reserved", 16), ("l2tp_session_id", 32)], dv)
    out.append(vec(P, "data-session-payload-not-written", (hd + bytes(10)).hex(), hd.hex(),
                   model_of(dv, ["l2tp_version", "l2tp_reserved", "l2tp_session_id"], "data"),
                   SRC + "a data message over UDP: T 0, version 3, session 0xcafe0001, 10 octets read over"))
    out.append(vec(P, "data-cut-short-is-malformed", hd[:6].hex(), error="malformed-wire",
                   ref=SRC + "the data header cut to 6 octets"))
    return out


# ---- ESP and AH ------------------------------------------------------------
def esp_vectors():
    out = []
    P = "esp-header"
    v = {"ipsec_spi": 0x00001001, "ipsec_seq": 1}
    h = be(v["ipsec_spi"], 32) + be(v["ipsec_seq"], 32)
    out.append(vec(P, "first-packet-payload-not-written", (h + bytes(32)).hex(), h.hex(),
                   model_of(v, ["ipsec_spi", "ipsec_seq"]),
                   SRC + "SPI 0x1001 and the first value of the counter, 1 (the first packet of an SA), then 32 octets of encrypted "
                         "payload and ICV, read over"))
    e = {"ipsec_spi": 0xFFFFFFFF, "ipsec_seq": 0xFFFFFFFF}
    he = be(0xFFFFFFFF, 32) * 2
    out.append(vec(P, "largest-values", he.hex(), he.hex(), model_of(e, ["ipsec_spi", "ipsec_seq"]),
                   SRC + "the largest SPI and sequence number"))
    out.append(vec(P, "seven-octets-is-malformed", h[:7].hex(), error="malformed-wire",
                   ref=SRC + "the header cut to 7 octets"))
    out.append(vec(P, "spi-and-sequence-to-ah-header", h.hex(),
                   (bytes(4) + h).hex(), model_of(v, ["ipsec_spi", "ipsec_seq"]), to="ah-header",
                   ref=SRC + "the ESP header to ah-header: the shared keys inet.ipsec_spi and inet.ipsec_seq carry; "
                             "next header, payload length and reserved are absent and written 0"))
    return out


def ah_vectors():
    out = []
    P = "ah-header"
    v = {"ip_protocol": 6, "ah_payload_len": 4, "ipsec_spi": 0x00002002, "ipsec_seq": 42}
    h = pack([("ip_protocol", 8), ("ah_payload_len", 8), ("ah_reserved", 16), ("ipsec_spi", 32), ("ipsec_seq", 32)], v)
    keys = ["ip_protocol", "ah_payload_len", "ah_reserved", "ipsec_spi", "ipsec_seq"]
    out.append(vec(P, "tcp-next-icv-not-written", (h + bytes(12)).hex(), h.hex(), model_of(v, keys),
                   SRC + "AH before TCP (next header 6), payload length 4 (3 fixed words and a 96-bit ICV, minus 2), "
                         "SPI 0x2002, sequence 42; the 12-octet ICV read over"))
    e = {"ip_protocol": 255, "ah_payload_len": 255, "ah_reserved": 0xFFFF, "ipsec_spi": 0xFFFFFFFF,
         "ipsec_seq": 0xFFFFFFFF}
    he = pack([("ip_protocol", 8), ("ah_payload_len", 8), ("ah_reserved", 16), ("ipsec_spi", 32), ("ipsec_seq", 32)], e)
    out.append(vec(P, "largest-values", he.hex(), he.hex(), model_of(e, keys),
                   SRC + "every field at its largest value, the reserved bits included (the pack does not check them)"))
    out.append(vec(P, "eleven-octets-is-malformed", h[:11].hex(), error="malformed-wire",
                   ref=SRC + "the fixed part cut to 11 octets"))
    return out


# ---- QUIC invariants -------------------------------------------------------
def quic_vectors():
    out = []
    P = "quic-invariant"

    def long_hdr(bits7, version, dcid, scid):
        b = bytes([0x80 | bits7]) + be(version, 32) + bytes([len(dcid)]) + bytes(dcid) + bytes([len(scid)]) + bytes(scid)
        m = {"@kind": "long-header", "inet.quic_version_specific": str(bits7), "inet.quic_version": str(version),
             "inet.quic_dcid.#": str(len(dcid)), "inet.quic_scid.#": str(len(scid))}
        for i, x in enumerate(dcid):
            m["inet.quic_dcid[%d].inet.quic_cid_octet" % i] = str(x)
        for i, x in enumerate(scid):
            m["inet.quic_scid[%d].inet.quic_cid_octet" % i] = str(x)
        return b, m

    h, m = long_hdr(0x40, 1, list(range(1, 9)), [0xAA, 0xBB, 0xCC, 0xDD])
    out.append(vec(P, "long-header-version-1-rest-not-written", (h + bytes(20)).hex(), h.hex(), m,
                   SRC + "a long header, version 0x00000001, an 8-octet destination and 4-octet source connection ID; "
                         "the 20 version-specific octets after them read over"))
    hn, mn = long_hdr(0x2A, 0, [], [0x11])
    out.append(vec(P, "version-negotiation-empty-dcid", (hn + be(1, 32)).hex(), hn.hex(), mn,
                   SRC + "version 0 (version negotiation): an empty destination connection ID and a 1-octet source; "
                         "the supported-version list after it read over"))
    hm, mm = long_hdr(0x7F, 0xFFFFFFFF, [0xFF] * 20, [0xFF] * 255)
    out.append(vec(P, "long-header-largest-values", hm.hex(), hm.hex(), mm,
                   SRC + "every first-octet bit set, the largest version, a 20-octet destination and a 255-octet "
                         "source connection ID (the largest an 8-bit length allows)"))
    out.append(vec(P, "short-header-first-octet", (bytes([0x41]) + bytes(16)).hex(), "41",
                   {"@kind": "short-header", "inet.quic_version_specific": "65"},
                   SRC + "a short header (form bit 0): its connection ID length is not on the wire, so only the "
                         "first octet is read"))
    out.append(vec(P, "connection-id-cut-short-is-malformed", h[:10].hex(), error="malformed-wire",
                   ref=SRC + "the first long header cut to 10 octets, inside its destination connection ID"))
    return out


# ---- pcap ------------------------------------------------------------------
PCAP_KEYS = ["pcap_version_major", "pcap_version_minor", "pcap_reserved1", "pcap_reserved2", "pcap_snaplen",
             "pcap_fcs_len", "pcap_r_bit", "pcap_p_bit", "pcap_linktype"]


def pcap_file(v, little, nsec):
    magic = 0xA1B23C4D if nsec else 0xA1B2C3D4
    flags = (v.get("pcap_fcs_len", 0) << 28) | (v.get("pcap_r_bit", 0) << 27) | (v.get("pcap_p_bit", 0) << 26) | \
        v.get("pcap_linktype", 0)
    enc = le if little else be
    return (enc(magic, 32) + enc(v.get("pcap_version_major", 0), 16) + enc(v.get("pcap_version_minor", 0), 16) +
            enc(v.get("pcap_reserved1", 0), 32) + enc(v.get("pcap_reserved2", 0), 32) +
            enc(v.get("pcap_snaplen", 0), 32) + enc(flags, 32))


def pcap_file_vectors():
    out = []
    P = "pcap-file-header"
    base = {"pcap_version_major": 2, "pcap_version_minor": 4, "pcap_snaplen": 262144, "pcap_linktype": 1}
    for name, little, nsec, kind, what in (
            ("little-endian-microseconds-ethernet", True, False, "little-endian-microseconds",
             "a little-endian file (magic octets d4 c3 b2 a1), version 2.4, snap length 262144, link type 1 "
             "(Ethernet)"),
            ("big-endian-microseconds-ethernet", False, False, "big-endian-microseconds",
             "the same header written big-endian (a1 b2 c3 d4)"),
            ("little-endian-nanoseconds", True, True, "little-endian-nanoseconds",
             "a little-endian file with nanosecond timestamps (4d 3c b2 a1)"),
            ("big-endian-nanoseconds", False, True, "big-endian-nanoseconds",
             "a big-endian file with nanosecond timestamps (a1 b2 3c 4d)")):
        h = pcap_file(base, little, nsec)
        out.append(vec(P, name, h.hex(), h.hex(), model_of(base, PCAP_KEYS, kind, "pcap"), SRC + what))
    f = dict(base, pcap_fcs_len=2, pcap_p_bit=1, pcap_reserved1=0xFFFFFFF0, pcap_linktype=0xFFFF)
    hf = pcap_file(f, True, False)
    out.append(vec(P, "little-endian-fcs-and-old-reserved", hf.hex(), hf.hex(),
                   model_of(f, PCAP_KEYS, "little-endian-microseconds", "pcap"),
                   SRC + "a little-endian header with P set and an FCS of 2 words (4 octets), link type 0xffff, and "
                         "reserved1 0xfffffff0 as an older writer's time zone offset: carried, not checked"))
    out.append(vec(P, "pcapng-magic-is-no-kind", (be(0x0A0D0D0A, 32) + bytes(20)).hex(), error="no-kind",
                   ref=SRC + "the first octets of a pcapng file (block type 0a 0d 0d 0a)"))
    out.append(vec(P, "twenty-three-octets-is-malformed", pcap_file(base, True, False)[:23].hex(),
                   error="malformed-wire", ref=SRC + "the little-endian header cut to 23 octets"))
    return out


def pcap_record_vectors(little):
    out = []
    P = "pcap-record-le" if little else "pcap-record-be"
    enc = le if little else be
    v = {"pcap_ts_sec": 1795568400, "pcap_ts_frac": 123456, "pcap_caplen": 60, "pcap_origlen": 60}
    h = enc(v["pcap_ts_sec"], 32) + enc(v["pcap_ts_frac"], 32) + enc(60, 32) + enc(60, 32)
    keys = ["pcap_ts_sec", "pcap_ts_frac", "pcap_caplen", "pcap_origlen"]
    out.append(vec(P, "record-data-not-written", (h + bytes(60)).hex(), h.hex(), model_of(v, keys, None, "pcap"),
                   SRC + "a record at 1795568400 s and 123456 microseconds (or nanoseconds, as the file says), 60 "
                         "octets captured of 60, the 60 data octets read over"))
    t = {"pcap_ts_sec": 1795568400, "pcap_ts_frac": 999999999, "pcap_caplen": 65535, "pcap_origlen": 1514}
    ht = enc(t["pcap_ts_sec"], 32) + enc(t["pcap_ts_frac"], 32) + enc(65535, 32) + enc(1514, 32)
    out.append(vec(P, "truncated-capture-nanoseconds", ht.hex(), ht.hex(), model_of(t, keys, None, "pcap"),
                   SRC + "a record whose fraction 999999999 only a nanosecond file allows, captured length 65535, "
                         "original 1514: the pack carries both lengths as they are"))
    out.append(vec(P, "fifteen-octets-is-malformed", h[:15].hex(), error="malformed-wire",
                   ref=SRC + "the record header cut to 15 octets"))
    return out


def pcapng_shb_vectors():
    out = []
    P = "pcapng-section-header"
    keys = ["pcapng_block_total_length", "pcapng_version_major", "pcapng_version_minor", "pcapng_section_length"]
    for little, kind in ((True, "little-endian"), (False, "big-endian")):
        enc = le if little else be
        v = {"pcapng_block_total_length": 28, "pcapng_version_major": 1, "pcapng_version_minor": 0,
             "pcapng_section_length": -1}
        h = (be(0x0A0D0D0A, 32) + enc(28, 32) + enc(0x1A2B3C4D, 32) + enc(1, 16) + enc(0, 16) + enc(-1, 64))
        out.append(vec(P, kind + "-length-not-stated", (h + enc(28, 32)).hex(), h.hex(),
                       model_of(v, keys, kind, "pcap"),
                       SRC + "a %s section header block, version 1.0, section length -1 (not stated), no option; "
                             "its trailing block total length read over" % kind.replace("-", " ")))
    v2 = {"pcapng_block_total_length": 0xFFFFFFFC, "pcapng_version_major": 0xFFFF, "pcapng_version_minor": 0xFFFF,
          "pcapng_section_length": (1 << 63) - 4}
    h2 = (be(0x0A0D0D0A, 32) + le(0xFFFFFFFC, 32) + le(0x1A2B3C4D, 32) + le(0xFFFF, 16) + le(0xFFFF, 16) +
          le((1 << 63) - 4, 64))
    out.append(vec(P, "little-endian-largest-section", h2.hex(), h2.hex(), model_of(v2, keys, "little-endian", "pcap"),
                   SRC + "the largest values, a section length of 2^63 - 4 (a multiple of 4): the pack checks neither "
                         "the version nor the alignment"))
    bad = be(0x0A0D0D0A, 32) + be(28, 32) + be(0x01020304, 32) + bytes(12)
    out.append(vec(P, "unknown-byte-order-magic-is-no-kind", bad.hex(), error="no-kind",
                   ref=SRC + "a section header block whose byte-order magic is 01 02 03 04"))
    out.append(vec(P, "twenty-three-octets-is-malformed", h[:23].hex(), error="malformed-wire",
                   ref=SRC + "the big-endian block cut to 23 octets"))
    return out


def pcapng_epb_vectors(little):
    out = []
    P = "pcapng-epb-le" if little else "pcapng-epb-be"
    enc = le if little else be
    keys = ["pcapng_block_total_length", "pcapng_interface_id", "pcapng_ts_high", "pcapng_ts_low", "pcap_caplen",
            "pcap_origlen"]
    ts = 1795568400123456
    v = {"pcapng_block_total_length": 96, "pcapng_interface_id": 0, "pcapng_ts_high": ts >> 32,
         "pcapng_ts_low": ts & 0xFFFFFFFF, "pcap_caplen": 60, "pcap_origlen": 60}
    h = enc(6, 32) + b"".join(enc(v[k], 32) for k in keys)
    out.append(vec(P, "packet-data-not-written", (h + bytes(60) + enc(96, 32)).hex(), h.hex(),
                   model_of(v, keys, "enhanced-packet", "pcap"),
                   SRC + "an enhanced packet block on interface 0 at %d microseconds (in the default resolution), "
                         "60 octets of 60; data and the trailing length read over" % ts))
    out.append(vec(P, "other-block-type-is-no-kind", (enc(1, 32) + bytes(24)).hex(), error="no-kind",
                   ref=SRC + "block type 1 (interface description)"))
    out.append(vec(P, "twenty-seven-octets-is-malformed", h[:27].hex(), error="malformed-wire",
                   ref=SRC + "the block cut to 27 octets"))
    return out


PACKS = {
    "ethernet-ii": ethernet_vectors,
    "ppp-frame": ppp_vectors,
    "l2tpv3-ip": l2tp_ip_vectors,
    "l2tpv3-udp": l2tp_udp_vectors,
    "esp-header": esp_vectors,
    "ah-header": ah_vectors,
    "quic-invariant": quic_vectors,
    "pcap-file-header": pcap_file_vectors,
    "pcap-record-le": lambda: pcap_record_vectors(True),
    "pcap-record-be": lambda: pcap_record_vectors(False),
    "pcapng-section-header": pcapng_shb_vectors,
    "pcapng-epb-le": lambda: pcapng_epb_vectors(True),
    "pcapng-epb-be": lambda: pcapng_epb_vectors(False),
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
    return genio.vector_main("link-headers-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
