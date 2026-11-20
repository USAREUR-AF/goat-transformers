#!/usr/bin/env python3
"""ietf-headers-4-vectors: write the vectors of the fourth set of IETF header packs.

Packs: coap-header, tls-record-header, dtls-record-header, bgp-header,
ospfv2-header, vrrpv3-ipv4, vrrpv3-ipv6, ripv2-header, geneve-header.

Python 3 standard library only; imports no engine and reads no pack.def. The
layouts below are this program's own restatement of RFC 7252 section 3, RFC
8446 sections 4, 5.1 and 6, RFC 9147 section 4, RFC 4271 section 4, RFC 2328
appendix A.3, RFC 9568 section 5, RFC 2453 section 3.6 and RFC 8926 section
3.4: each header is a list of (field, bits) in wire order, most significant
bit first, multi-octet fields in network (big-endian) order.

Inputs: messages built here field by field, from values chosen here. No
message is taken from a document. Addresses are from the documentation ranges
(192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24 of RFC 5737; 2001:db8::/32
of RFC 3849, plus a link-local address); autonomous system numbers from the
documentation range of RFC 5398. The OSPF and VRRP (IPv4) checksums are
computed here by the ones' complement sum the RFCs name; other checksums are
values chosen here (the packs carry them, they do not compute or check them).

Every `expect` is this program's packing of the mapped part; every `model`
value is the field value that was packed; a list is given by `<list>.#` and
its items' values. Octets after the mapped part (CoAP options and payload,
record bodies, BGP optional parameters, routes and data, OSPF neighbors and
LSAs, RIP entries, payloads) are read over and not written back.

Usage: python3 -I tools/gen/ietf-headers-4-vectors.py [--out DIR] [--check]
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


SRC = "built by tools/gen/ietf-headers-4-vectors.py from values chosen there; "


def add_list(m, name, items, keys):
    m["inet.%s.#" % name] = str(len(items))
    for i, it in enumerate(items):
        for k in keys:
            m["inet.%s[%d].inet.%s" % (name, i, k)] = str(it[k])
    return m


def ip6_groups(text):
    if "::" in text:
        h, t = text.split("::")
        h = [int(x, 16) for x in h.split(":")] if h else []
        t = [int(x, 16) for x in t.split(":")] if t else []
        g = h + [0] * (8 - len(h) - len(t)) + t
    else:
        g = [int(x, 16) for x in text.split(":")]
    assert len(g) == 8
    return g


# ---------------------------------------------------------------------------
# CoAP, RFC 7252 section 3.
COAP = [("coap_version", 2), ("coap_type", 2), ("coap_token_length", 4), ("coap_code_class", 3),
        ("coap_code_detail", 5), ("coap_message_id", 16)]
COAP_KEYS = [k for k, _ in COAP]


def coap(v, token):
    v = dict(v, coap_version=v.get("coap_version", 1), coap_token_length=len(token))
    b = pack(COAP, v) + bytes(token)
    m = add_list(model_of(v, COAP_KEYS), "coap_token", [{"coap_token_octet": t} for t in token],
                 ["coap_token_octet"])
    return b, m


def coap_vectors():
    out = []
    P = "coap-header"
    h, m = coap({"coap_type": 0, "coap_code_class": 0, "coap_code_detail": 1, "coap_message_id": 0x7D34},
                [0x71, 0x62, 0x53, 0x44])
    opts = bytes([0xB4]) + b"temp" + bytes([0xFF]) + b"22.5"
    out.append(vec(P, "confirmable-get-options-not-written", (h + opts).hex(), h.hex(), m,
                   SRC + "a confirmable GET (0.01), message ID 0x7d34, a 4-octet token, then a Uri-Path "
                         "option and a payload after the 0xff marker, read over"))
    ha, ma = coap({"coap_type": 2, "coap_code_class": 2, "coap_code_detail": 5, "coap_message_id": 0x7D34},
                  [0x71, 0x62, 0x53, 0x44])
    out.append(vec(P, "piggybacked-content-response-roundtrip", ha.hex(), ha.hex(), ma,
                   SRC + "an acknowledgement carrying the response 2.05 Content with the request's token"))
    he, me = coap({"coap_type": 3, "coap_code_class": 7, "coap_code_detail": 31, "coap_message_id": 0xFFFF},
                  [0xFF] * 8)
    out.append(vec(P, "eight-octet-token-edge-values-roundtrip", he.hex(), he.hex(), me,
                   SRC + "a reset with code 7.31, the largest message ID and an 8-octet token of 0xff "
                         "octets: the largest values (the pack does not check the code class)"))
    hz, mz = coap({"coap_type": 0, "coap_message_id": 1}, [])
    out.append(vec(P, "empty-message-roundtrip", hz.hex(), hz.hex(), mz,
                   SRC + "an empty confirmable message (code 0.00, no token, a CoAP ping): 4 octets"))
    out.append(vec(P, "token-cut-short-is-malformed", h[:6].hex(), error="malformed-wire",
                   ref=SRC + "the GET cut to 6 octets: 2 of its 4 token octets"))
    out.append(vec(P, "three-octets-is-malformed", h[:3].hex(), error="malformed-wire",
                   ref=SRC + "the GET cut to 3 octets"))
    return out


# ---------------------------------------------------------------------------
# TLS record header, RFC 8446 section 5.1.
TLS = [("tls_content_type", 8), ("tls_legacy_version", 16), ("tls_record_length", 16)]
TLS_KEYS = [k for k, _ in TLS]
DTLS_PLAIN = [("tls_content_type", 8), ("tls_legacy_version", 16), ("dtls_epoch", 16), ("dtls_sequence", 48),
              ("tls_record_length", 16)]


def tls_vectors():
    out = []
    P = "tls-record-header"
    hs = {"tls_content_type": 22, "tls_legacy_version": 0x0301, "tls_record_length": 512,
          "tls_handshake_type": 1, "tls_handshake_length": 508}
    h = pack(TLS + [("tls_handshake_type", 8), ("tls_handshake_length", 24)], hs)
    mh = model_of(hs, TLS_KEYS + ["tls_handshake_type", "tls_handshake_length"], "handshake")
    out.append(vec(P, "client-hello-record-body-not-written", (h + bytes(508)).hex(), h.hex(), mh,
                   SRC + "a handshake record of 512 octets, legacy version 0x0301 as for an initial "
                         "ClientHello, whose first message is a client_hello (type 1) of 508 octets; the "
                         "message body (zeros here) is read over"))
    al = {"tls_content_type": 21, "tls_legacy_version": 0x0303, "tls_record_length": 2,
          "tls_alert_level": 2, "tls_alert_description": 40}
    ha = pack(TLS + [("tls_alert_level", 8), ("tls_alert_description", 8)], al)
    out.append(vec(P, "fatal-alert-roundtrip", ha.hex(), ha.hex(),
                   model_of(al, TLS_KEYS + ["tls_alert_level", "tls_alert_description"], "alert"),
                   SRC + "a plaintext alert record: level 2 (fatal), description 40 (handshake_failure)"))
    cc = {"tls_content_type": 20, "tls_legacy_version": 0x0303, "tls_record_length": 1, "tls_ccs_value": 1}
    hc = pack(TLS + [("tls_ccs_value", 8)], cc)
    out.append(vec(P, "change-cipher-spec-roundtrip", hc.hex(), hc.hex(),
                   model_of(cc, TLS_KEYS + ["tls_ccs_value"], "change-cipher-spec"),
                   SRC + "the one-octet change_cipher_spec record TLS 1.3 keeps for middlebox "
                         "compatibility"))
    ad = {"tls_content_type": 23, "tls_legacy_version": 0x0303, "tls_record_length": 32}
    hd = pack(TLS, ad)
    out.append(vec(P, "application-data-body-not-written", (hd + bytes(range(32))).hex(), hd.hex(),
                   model_of(ad, TLS_KEYS, "application-data"),
                   SRC + "an application_data record of 32 octets (a protected record); the 32 octets are "
                         "read over"))
    ot = {"tls_content_type": 24, "tls_legacy_version": 0x0303, "tls_record_length": 0}
    ho = pack(TLS, ot)
    out.append(vec(P, "unnamed-content-type-is-other", ho.hex(), ho.hex(), model_of(ot, TLS_KEYS, "other"),
                   SRC + "content type 24, which RFC 8446 does not define: kind other, the header alone"))
    ed = {"tls_content_type": 255, "tls_legacy_version": 0xFFFF, "tls_record_length": 0xFFFF}
    he = pack(TLS, ed)
    out.append(vec(P, "header-largest-values-roundtrip", he.hex(), he.hex(), model_of(ed, TLS_KEYS, "other"),
                   SRC + "content type 255, legacy version 0xffff and length 65535: the pack checks neither "
                         "the version nor the 2^14 limit"))
    out.append(vec(P, "alert-cut-short-is-malformed", ha[:6].hex(), error="malformed-wire",
                   ref=SRC + "the alert record cut to 6 octets"))
    out.append(vec(P, "four-octets-is-malformed", hd[:4].hex(), error="malformed-wire",
                   ref=SRC + "the application_data header cut to 4 octets"))
    dp = pack(DTLS_PLAIN, {"tls_content_type": 22, "tls_legacy_version": 0x0301, "tls_record_length": 512})
    out.append(vec(P, "client-hello-header-to-dtls", h.hex(), dp.hex(), mh, to="dtls-record-header",
                   ref=SRC + "the client_hello record to dtls-record-header: content type, legacy version and "
                             "length carry (RFC 9147 keeps their meaning); kind plaintext, epoch and sequence "
                             "absent and written 0, the handshake keys not mapped there"))
    return out


# ---------------------------------------------------------------------------
# DTLS 1.3 record headers, RFC 9147 section 4.
def dtls_vectors():
    out = []
    P = "dtls-record-header"
    pv = {"tls_content_type": 22, "tls_legacy_version": 0xFEFD, "dtls_epoch": 0, "dtls_sequence": 5,
          "tls_record_length": 100}
    h = pack(DTLS_PLAIN, pv)
    keys = ["tls_content_type", "tls_legacy_version", "dtls_epoch", "dtls_sequence", "tls_record_length"]
    out.append(vec(P, "plaintext-handshake-body-not-written", (h + bytes(100)).hex(), h.hex(),
                   model_of(pv, keys, "plaintext"),
                   SRC + "a plaintext handshake record, version {254, 253}, epoch 0, sequence 5, 100 octets "
                         "of body read over"))
    ak = {"tls_content_type": 26, "tls_legacy_version": 0xFEFD, "dtls_epoch": 0xFFFF,
          "dtls_sequence": (1 << 48) - 1, "tls_record_length": 0xFFFF}
    hk = pack(DTLS_PLAIN, ak)
    out.append(vec(P, "plaintext-ack-largest-values-roundtrip", hk.hex(), hk.hex(), model_of(ak, keys, "plaintext"),
                   SRC + "a plaintext record of content type 26 (ack) with the largest epoch, 48-bit "
                         "sequence number and length"))
    UH = [("fixed", 3), ("c", 1), ("dtls_seq_16bit", 1), ("dtls_length_present", 1), ("dtls_epoch_low", 2)]
    rows = [
        ("ciphertext-minimal-body-not-written", 0, 0, 3, 0x42, None, 24,
         "a minimal unified header: S 0 and L 0, epoch bits 3, 8-bit sequence 0x42, then 24 octets of "
         "encrypted record (to the end of the datagram), read over"),
        ("ciphertext-8-bit-sequence-with-length-roundtrip", 0, 1, 1, 0xFF, 48, 0,
         "S 0 and L 1: 8-bit sequence 0xff, length 48"),
        ("ciphertext-16-bit-sequence-with-length-roundtrip", 1, 1, 2, 0x1234, 64, 0,
         "S 1 and L 1: 16-bit sequence 0x1234, length 64"),
        ("ciphertext-16-bit-sequence-no-length-roundtrip", 1, 0, 0, 0xFFFF, None, 0,
         "S 1 and L 0: 16-bit sequence 0xffff, no length"),
    ]
    cut = None
    for name, s, l, e, seq, length, extra, what in rows:
        v = {"fixed": 1, "dtls_seq_16bit": s, "dtls_length_present": l, "dtls_epoch_low": e, "dtls_seq_low": seq}
        b = pack(UH, v) + seq.to_bytes(2 if s else 1, "big")
        m = model_of(v, ["dtls_seq_16bit", "dtls_length_present", "dtls_epoch_low", "dtls_seq_low"], "ciphertext")
        if length is not None:
            b += length.to_bytes(2, "big")
            m["inet.tls_record_length"] = str(length)
        if s and l:
            cut = b
        out.append(vec(P, name, (b + bytes(extra)).hex(), b.hex(), m, SRC + what))
    cid = pack(UH, {"fixed": 1, "c": 1, "dtls_seq_16bit": 1, "dtls_length_present": 1, "dtls_epoch_low": 3})
    out.append(vec(P, "connection-id-first-octet-only", (cid + bytes([0xAB, 0xCD, 0, 7, 0, 16])).hex(), cid.hex(),
                   {"@kind": "ciphertext-with-cid", "inet.dtls_cid_present": "1", "inet.dtls_seq_16bit": "1",
                    "inet.dtls_length_present": "1", "inet.dtls_epoch_low": "3"},
                   SRC + "a unified header with C set, followed by a 2-octet connection ID, sequence and "
                         "length: the CID length is not on the wire, so only the first octet is read"))
    out.append(vec(P, "ciphertext-length-cut-short-is-malformed", cut[:4].hex(), error="malformed-wire",
                   ref=SRC + "the S 1, L 1 header cut to 4 octets: the length does not fit"))
    out.append(vec(P, "plaintext-of-12-octets-is-malformed", h[:12].hex(), error="malformed-wire",
                   ref=SRC + "the plaintext handshake header cut to 12 octets"))
    return out


# ---------------------------------------------------------------------------
# BGP-4, RFC 4271 section 4.
BGP_HEAD = [("marker", 128), ("bgp_length", 16), ("type", 8)]
OPEN = [("bgp_version", 8), ("bgp_my_as", 16), ("bgp_hold_time", 16), ("bgp_identifier", 32),
        ("bgp_opt_param_length", 8)]
MARK = (1 << 128) - 1


def bgp(t, body_layout, v):
    return pack(BGP_HEAD + body_layout, dict(v, marker=MARK, type=t))


def bgp_vectors():
    out = []
    P = "bgp-header"
    op = {"bgp_length": 29, "bgp_version": 4, "bgp_my_as": 64496, "bgp_hold_time": 90,
          "bgp_identifier": ip4("192.0.2.1")}
    h = bgp(1, OPEN, op)
    okeys = ["bgp_length"] + [k for k, _ in OPEN]
    out.append(vec(P, "open-roundtrip", h.hex(), h.hex(), model_of(op, okeys, "open"),
                   SRC + "an OPEN from AS 64496, hold time 90 s, identifier 192.0.2.1, no optional "
                         "parameter: 29 octets"))
    op2 = dict(op, bgp_length=37, bgp_opt_param_length=8, bgp_hold_time=0)
    h2 = bgp(1, OPEN, op2)
    params = bytes([2, 6, 1, 4, 0, 1, 0, 1])
    out.append(vec(P, "open-optional-parameters-not-written", (h2 + params).hex(), h2.hex(),
                   model_of(op2, okeys, "open"),
                   SRC + "an OPEN with hold time 0 and an 8-octet optional parameter (a capabilities "
                         "parameter), read over; the length 37 and parameter length 8 are kept"))
    ka = bgp(4, [], {"bgp_length": 19})
    out.append(vec(P, "keepalive-roundtrip", ka.hex(), ka.hex(), {"@kind": "keepalive", "inet.bgp_length": "19"},
                   SRC + "a KEEPALIVE: the 19-octet header alone"))
    nt = {"bgp_length": 21, "bgp_error_code": 6, "bgp_error_subcode": 2}
    hn = bgp(3, [("bgp_error_code", 8), ("bgp_error_subcode", 8)], nt)
    out.append(vec(P, "notification-roundtrip", hn.hex(), hn.hex(),
                   model_of(nt, ["bgp_length", "bgp_error_code", "bgp_error_subcode"], "notification"),
                   SRC + "a NOTIFICATION, error code 6 (Cease) with subcode 2, no data"))
    nd = dict(nt, bgp_length=25)
    hd = bgp(3, [("bgp_error_code", 8), ("bgp_error_subcode", 8)], nd)
    out.append(vec(P, "notification-data-not-written", (hd + b"\x00\x01\x02\x03").hex(), hd.hex(),
                   model_of(nd, ["bgp_length", "bgp_error_code", "bgp_error_subcode"], "notification"),
                   SRC + "the NOTIFICATION with 4 octets of data, read over"))
    up = {"bgp_length": 23, "bgp_withdrawn_routes_length": 0}
    hu = bgp(2, [("bgp_withdrawn_routes_length", 16)], up)
    out.append(vec(P, "update-rest-not-written", (hu + bytes(2)).hex(), hu.hex(),
                   model_of(up, ["bgp_length", "bgp_withdrawn_routes_length"], "update"),
                   SRC + "an UPDATE of 23 octets with no withdrawn route and no path attribute (an "
                         "end-of-RIB marker); the total path attribute length after the first field is read "
                         "over"))
    bad = bytearray(ka)
    bad[15] = 0xFE
    out.append(vec(P, "marker-not-all-ones-is-no-kind", bytes(bad).hex(), error="no-kind",
                   ref=SRC + "the KEEPALIVE with the last marker octet 0xfe"))
    out.append(vec(P, "type-5-is-no-kind", bgp(5, [], {"bgp_length": 19}).hex(), error="no-kind",
                   ref=SRC + "type 5 (ROUTE-REFRESH of a later RFC), which the pack does not map"))
    out.append(vec(P, "eighteen-octets-is-no-kind", ka[:18].hex(), error="no-kind",
                   ref=SRC + "the KEEPALIVE cut to 18 octets: the type octet is beyond the input, so no "
                             "kind's `when` holds (engine-spec 0.5, kinds)"))
    out.append(vec(P, "open-cut-short-is-malformed", h[:28].hex(), error="malformed-wire",
                   ref=SRC + "the first OPEN cut to 28 octets: kind open is selected and its optional "
                             "parameters length does not fit"))
    return out


# ---------------------------------------------------------------------------
# OSPFv2, RFC 2328 appendix A.3.
OSPF_HEAD = [("ospf_version", 8), ("type", 8), ("ospf_packet_length", 16), ("ospf_router_id", 32),
             ("ospf_area_id", 32), ("ospf_checksum", 16), ("ospf_autype", 16), ("ospf_auth_hi", 32),
             ("ospf_auth_lo", 32)]
OSPF_KEYS = [k for k, _ in OSPF_HEAD if k != "type"]
HELLO = [("ospf_network_mask", 32), ("ospf_hello_interval", 16), ("ospf_options", 8), ("ospf_router_priority", 8),
         ("ospf_router_dead_interval", 32), ("ospf_dr", 32), ("ospf_bdr", 32)]
DD = [("ospf_interface_mtu", 16), ("ospf_options", 8), ("ospf_dd_reserved", 5), ("ospf_dd_init", 1),
      ("ospf_dd_more", 1), ("ospf_dd_master", 1), ("ospf_dd_sequence", 32)]


def ospf(t, layout, v, tail=b""):
    """Packet with its checksum: the ones' complement sum over the whole packet with
    the checksum and the 64-bit authentication field taken as zero."""
    v = dict(v, ospf_version=2, type=t)
    v["ospf_packet_length"] = 24 + sum(n for _, n in layout) // 8 + len(tail)
    zero = dict(v, ospf_checksum=0, ospf_auth_hi=0, ospf_auth_lo=0)
    v["ospf_checksum"] = checksum(pack(OSPF_HEAD + layout, zero) + tail)
    return v, pack(OSPF_HEAD + layout, v), tail


def ospf_vectors():
    out = []
    P = "ospfv2-header"
    hv = {"ospf_router_id": ip4("192.0.2.1"), "ospf_network_mask": ip4("255.255.255.0"),
          "ospf_hello_interval": 10, "ospf_options": 0x02, "ospf_router_priority": 1,
          "ospf_router_dead_interval": 40, "ospf_dr": ip4("192.0.2.1")}
    v, h, tail = ospf(1, HELLO, hv, ip4("192.0.2.2").to_bytes(4, "big"))
    out.append(vec(P, "hello-neighbor-not-written", (h + tail).hex(), h.hex(),
                   model_of(v, OSPF_KEYS + [k for k, _ in HELLO], "hello"),
                   SRC + "a Hello in area 0 from 192.0.2.1, mask 255.255.255.0, interval 10 s, E option, "
                         "priority 1, dead interval 40 s, itself designated router, one neighbor "
                         "192.0.2.2 read over; packet length 48 and checksum computed here"))
    pw = int.from_bytes(b"secretpw", "big")
    hv2 = dict(hv, ospf_autype=1, ospf_auth_hi=pw >> 32, ospf_auth_lo=pw & 0xFFFFFFFF, ospf_dr=0,
               ospf_area_id=ip4("0.0.0.1"))
    v2, h2, _ = ospf(1, HELLO, hv2)
    out.append(vec(P, "hello-simple-password-roundtrip", h2.hex(), h2.hex(),
                   model_of(v2, OSPF_KEYS + [k for k, _ in HELLO], "hello"),
                   SRC + "a Hello in area 0.0.0.1 with simple password authentication (type 1, the 8 "
                         "octets 'secretpw' as two 32-bit integers), no designated router yet"))
    dv = {"ospf_router_id": ip4("192.0.2.2"), "ospf_interface_mtu": 1500, "ospf_options": 0x02,
          "ospf_dd_init": 1, "ospf_dd_more": 1, "ospf_dd_master": 1, "ospf_dd_sequence": 0x5EED}
    v3, h3, _ = ospf(2, DD, dv)
    out.append(vec(P, "database-description-roundtrip", h3.hex(), h3.hex(),
                   model_of(v3, OSPF_KEYS + [k for k, _ in DD], "database-description"),
                   SRC + "the first Database Description of an exchange: MTU 1500, I, M and MS set, "
                         "sequence 0x5eed, no LSA header"))
    lsa = bytes(20)
    v4, h4, t4 = ospf(4, [("ospf_lsa_count", 32)], {"ospf_router_id": ip4("192.0.2.1"), "ospf_lsa_count": 1}, lsa)
    out.append(vec(P, "link-state-update-lsas-not-written", (h4 + t4).hex(), h4.hex(),
                   model_of(v4, OSPF_KEYS + ["ospf_lsa_count"], "link-state-update"),
                   SRC + "a Link State Update announcing 1 LSA, 20 octets read over"))
    v5, h5, t5 = ospf(3, [], {"ospf_router_id": ip4("192.0.2.2")}, bytes(12))
    out.append(vec(P, "link-state-request-entries-not-written", (h5 + t5).hex(), h5.hex(),
                   model_of(v5, OSPF_KEYS, "link-state-request"),
                   SRC + "a Link State Request with one 12-octet request entry, read over"))
    v6, h6, _ = ospf(5, [], {"ospf_router_id": ip4("192.0.2.2")})
    out.append(vec(P, "link-state-ack-empty-roundtrip", h6.hex(), h6.hex(), model_of(v6, OSPF_KEYS, "link-state-ack"),
                   SRC + "a Link State Acknowledgment with no LSA header: the 24-octet header"))
    _, h7, _ = ospf(6, [], {})
    out.append(vec(P, "type-6-is-no-kind", h7.hex(), error="no-kind",
                   ref=SRC + "a header with type 6, which RFC 2328 does not define"))
    out.append(vec(P, "hello-cut-short-is-malformed", h[:43].hex(), error="malformed-wire",
                   ref=SRC + "the first Hello cut to 43 octets"))
    return out


# ---------------------------------------------------------------------------
# VRRPv3, RFC 9568 section 5.
VRRP = [("vrrp_version", 4), ("vrrp_type", 4), ("vrrp_vrid", 8), ("vrrp_priority", 8), ("vrrp_addr_count", 8),
        ("vrrp_reserved", 4), ("vrrp_max_adver_int", 12), ("vrrp_checksum", 16)]
VRRP_KEYS = [k for k, _ in VRRP]
G6 = ["vrrp_ipv6_g%d" % i for i in range(8)]


def vrrp4(v, addrs):
    v = dict(v, vrrp_addr_count=len(addrs))
    body = b"".join(a.to_bytes(4, "big") for a in addrs)
    v["vrrp_checksum"] = checksum(pack(VRRP, dict(v, vrrp_checksum=0)) + body)
    b = pack(VRRP, v) + body
    return b, add_list(model_of(v, VRRP_KEYS), "vrrp_ipv4_addrs", [{"vrrp_ipv4_addr": a} for a in addrs],
                       ["vrrp_ipv4_addr"])


def vrrp4_vectors():
    out = []
    P = "vrrpv3-ipv4"
    base = {"vrrp_version": 3, "vrrp_type": 1, "vrrp_vrid": 1, "vrrp_priority": 100, "vrrp_max_adver_int": 100}
    h, m = vrrp4(base, [ip4("192.0.2.254"), ip4("192.0.2.253")])
    out.append(vec(P, "backup-two-addresses-roundtrip", h.hex(), h.hex(), m,
                   SRC + "an advertisement for virtual router 1, priority 100, interval 100 cs (1 s), two "
                         "addresses; checksum computed here"))
    h1, m1 = vrrp4(dict(base, vrrp_vrid=255, vrrp_priority=255, vrrp_max_adver_int=4095), [ip4("198.51.100.1")])
    out.append(vec(P, "owner-largest-values-roundtrip", h1.hex(), h1.hex(), m1,
                   SRC + "the address owner (priority 255) of virtual router 255, the largest interval 4095 cs, "
                         "one address; checksum computed here"))
    h0, m0 = vrrp4(dict(base, vrrp_priority=0), [])
    out.append(vec(P, "no-address-roundtrip", h0.hex(), h0.hex(), m0,
                   SRC + "an advertisement with priority 0 and an address count of 0, which a receiver "
                         "ignores (the pack does not): the 8-octet fixed part"))
    out.append(vec(P, "address-cut-short-is-malformed", h[:14].hex(), error="malformed-wire",
                   ref=SRC + "the two-address advertisement cut to 14 octets"))
    return out


def vrrp6_vectors():
    out = []
    P = "vrrpv3-ipv6"
    v = {"vrrp_version": 3, "vrrp_type": 1, "vrrp_vrid": 7, "vrrp_priority": 100, "vrrp_max_adver_int": 100,
         "vrrp_checksum": 0x4A5B}
    addrs = [ip6_groups("fe80::1"), ip6_groups("2001:db8::1")]
    v["vrrp_addr_count"] = len(addrs)
    b = pack(VRRP, v) + b"".join(g.to_bytes(2, "big") for a in addrs for g in a)
    m = add_list(model_of(v, VRRP_KEYS), "vrrp_ipv6_addrs",
                 [dict(zip(G6, a)) for a in addrs], G6)
    out.append(vec(P, "link-local-and-global-roundtrip", b.hex(), b.hex(), m,
                   SRC + "an advertisement for virtual router 7 with the link-local address fe80::1 first, "
                         "then 2001:db8::1; checksum a chosen value (it covers an IPv6 pseudo header)"))
    out.append(vec(P, "address-cut-short-is-malformed", b[:30].hex(), error="malformed-wire",
                   ref=SRC + "the advertisement cut to 30 octets, inside its second address"))
    return out


# ---------------------------------------------------------------------------
# RIP, RFC 2453 section 3.6.
RIP = [("rip_command", 8), ("rip_version", 8), ("rip_zero", 16)]
RIP_KEYS = [k for k, _ in RIP]


def rip_vectors():
    out = []
    P = "ripv2-header"
    rq = {"rip_command": 1, "rip_version": 2}
    h = pack(RIP, rq)
    entry = pack([("afi", 16), ("tag", 16), ("ip", 32), ("mask", 32), ("nh", 32), ("metric", 32)],
                 {"metric": 16})
    out.append(vec(P, "whole-table-request-entry-not-written", (h + entry).hex(), h.hex(), model_of(rq, RIP_KEYS),
                   SRC + "a version 2 request for the whole table (one entry, family 0, metric 16), the "
                         "entry read over"))
    rs = {"rip_command": 2, "rip_version": 1}
    hr = pack(RIP, rs)
    out.append(vec(P, "version-1-response-roundtrip", hr.hex(), hr.hex(), model_of(rs, RIP_KEYS),
                   SRC + "a version 1 response header"))
    ed = {"rip_command": 255, "rip_version": 255, "rip_zero": 0xFFFF}
    he = pack(RIP, ed)
    out.append(vec(P, "largest-values-roundtrip", he.hex(), he.hex(), model_of(ed, RIP_KEYS),
                   SRC + "every field at its largest value: the pack checks neither the command nor the "
                         "zero field"))
    out.append(vec(P, "three-octets-is-malformed", h[:3].hex(), error="malformed-wire",
                   ref=SRC + "the request header cut to 3 octets"))
    return out


# ---------------------------------------------------------------------------
# Geneve, RFC 8926 section 3.4.
GENEVE = [("geneve_version", 2), ("geneve_opt_len", 6), ("geneve_control", 1), ("geneve_critical", 1),
          ("geneve_reserved1", 6), ("geneve_protocol_type", 16), ("geneve_vni", 24), ("geneve_reserved2", 8)]
GENEVE_KEYS = [k for k, _ in GENEVE]


def geneve(v, words):
    v = dict(v, geneve_opt_len=len(words))
    b = pack(GENEVE, v) + b"".join(w.to_bytes(4, "big") for w in words)
    m = add_list(model_of(v, GENEVE_KEYS), "geneve_option_words", [{"geneve_option_word": w} for w in words],
                 ["geneve_option_word"])
    return b, m


def geneve_vectors():
    out = []
    P = "geneve-header"
    h, m = geneve({"geneve_protocol_type": 0x6558, "geneve_vni": 0x00ABCD}, [])
    out.append(vec(P, "ethernet-payload-not-written", (h + bytes(14)).hex(), h.hex(), m,
                   SRC + "a base header carrying Ethernet (0x6558), VNI 43981, no option, then 14 octets "
                         "standing for the inner Ethernet header, read over"))
    opt = [(0x0102 << 16) | (0x80 << 8) | 1, 0xC0FFEE00]
    ho, mo = geneve({"geneve_critical": 1, "geneve_protocol_type": 0x0800, "geneve_vni": 7}, opt)
    out.append(vec(P, "one-critical-option-as-words-roundtrip", ho.hex(), ho.hex(), mo,
                   SRC + "C set and one option of class 0x0102, type 0x80 (critical) with 4 octets of data: "
                         "option length 2, carried as two raw words"))
    he, me = geneve({"geneve_version": 3, "geneve_control": 1, "geneve_critical": 1, "geneve_reserved1": 63,
                     "geneve_protocol_type": 0xFFFF, "geneve_vni": 0xFFFFFF, "geneve_reserved2": 0xFF},
                    [0xFFFFFFFF] * 63)
    out.append(vec(P, "largest-values-63-words-roundtrip", he.hex(), he.hex(), me,
                   SRC + "every field at its largest value with 63 option words: the 260-octet largest "
                         "header"))
    out.append(vec(P, "option-cut-short-is-malformed", ho[:14].hex(), error="malformed-wire",
                   ref=SRC + "the one-option header cut to 14 octets, inside its second word"))
    out.append(vec(P, "seven-octets-is-malformed", h[:7].hex(), error="malformed-wire",
                   ref=SRC + "the base header cut to 7 octets"))
    return out


PACKS = {
    "coap-header": coap_vectors,
    "tls-record-header": tls_vectors,
    "dtls-record-header": dtls_vectors,
    "bgp-header": bgp_vectors,
    "ospfv2-header": ospf_vectors,
    "vrrpv3-ipv4": vrrp4_vectors,
    "vrrpv3-ipv6": vrrp6_vectors,
    "ripv2-header": rip_vectors,
    "geneve-header": geneve_vectors,
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
    return genio.vector_main("ietf-headers-4-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
