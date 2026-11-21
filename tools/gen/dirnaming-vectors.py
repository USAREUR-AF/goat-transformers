#!/usr/bin/env python3
"""dirnaming-vectors: write the vectors of nbns-message, nbdgm-message, llmnr-header and slp-message.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of:
- RFC 1002 section 4.1 (a name is labels, each a length octet and that many octets, ended by a
  zero length; the first label is the 16-octet NetBIOS name in first-level encoding, each octet
  as two letters 'A' plus its high and low half; two high bits 11 make a 14-bit pointer, allowed
  only in Name Service packets), 4.2.1 (the header: 16-bit transaction ID; the R bit and the
  4-bit opcode; flags AA, TC, RD, RA, two zero bits, B; 4-bit rcode; four 16-bit counts; the
  question name, type, class; a record's name, type, class, 32-bit TTL, 16-bit RDLENGTH and data;
  NB data: G, 2-bit owner node type, 13 zero bits, IPv4 address, repeated) and 4.2.18 (NBSTAT
  data: an 8-bit name count, entries of a 16-octet name and 16 flag bits G, ONT, DRG, CNF, ACT,
  PRM, 9 zero bits, then the statistics: 6-octet unit ID, two octets, then 16-bit fields with two
  32-bit ones as listed there) and 4.4 (the datagram header: message type, flags with SNT, F and
  M in the low four bits, datagram ID, source IPv4 address and port; by type the length and
  offset with the two names and the user data, an error code, or the destination name);
- RFC 4795 section 2.1.1 (the LLMNR header: the DNS header with C in the AA place, T in the RD
  place and four zero bits);
- RFC 1035 section 4.1.1 (the DNS header, for the conversions);
- RFC 2608 sections 4.3, 8, 8.1, 8.2, 8.4 and 9.2 (SLPv2: version, function, 24-bit length of
  the whole message, flags O F R and 13 zero bits, 24-bit next extension offset, XID, language tag
  with its 16-bit length; SrvRqst five 16-bit-length strings; SrvRply error code, entry count and
  URL entries, each a reserved octet, lifetime, URL with its length, an 8-bit count of
  authentication blocks, each a descriptor, a 16-bit length of the whole block, a timestamp, the
  SPI string and the authenticator; SrvAck an error code). Every integer is big-endian.

Inputs: packets built here field by field from values chosen here; no packet is taken from a
document or a capture. Addresses are from RFC 5737; names and scopes are invented or under
example.com.

`expect` of a round trip is this program's packing of the decoded values, which for these packets
is the input; of a conversion, the target header packed here from the shared values. `model`
holds values that were packed.

Usage: python3 -I tools/gen/dirnaming-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/dirnaming-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_NS = "RFC 1002 sections 4.1 and 4.2"
R_DG = "RFC 1002 sections 4.1 and 4.4"
R_LL = "RFC 4795 section 2.1.1"
R_SLP = "RFC 2608 section 8"


def vec(pack, name, inp, model=None, error=None, ref="", to=None, expect=None, note=""):
    v = {"name": name, "from": pack, "to": to or pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = (expect if expect is not None else inp).hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def v4(s):
    return int(ipaddress.IPv4Address(s))


def bits(fields):
    acc, n = 0, 0
    for v, w in fields:
        assert 0 <= v < (1 << w), (v, w)
        acc, n = (acc << w) | v, n + w
    assert n % 8 == 0
    return acc.to_bytes(n // 8, "big")


# ---------------------------------------------------------------- NetBIOS names

def nb16(name, suffix):
    return name.upper().encode("ascii").ljust(15, b" ") + bytes([suffix])


def first_level(raw16):
    return "".join(chr(65 + (b >> 4)) + chr(65 + (b & 15)) for b in raw16)


def nbname(name, suffix, scope=()):
    enc = first_level(nb16(name, suffix)).encode("ascii")
    out = bytes([32]) + enc
    for lab in scope:
        out += bytes([len(lab)]) + lab.encode("ascii")
    return out + b"\x00"


def pointer(off):
    return u16(0xC000 | off)


def nbns_header(trn, r, opcode, aa=0, tc=0, rd=0, ra=0, b=0, rcode=0, counts=(0, 0, 0, 0)):
    return u16(trn) + bits([(r, 1), (opcode, 4), (aa, 1), (tc, 1), (rd, 1), (ra, 1), (0, 2), (b, 1), (rcode, 4)]) + u16(*counts)


def rr(owner, typ, ttl, rdata, cls=1):
    return owner + u16(typ, cls) + u32(ttl) + u16(len(rdata)) + rdata


def nb_entry(g, ont, addr):
    return bits([(g, 1), (ont, 2), (0, 13)]) + u32(v4(addr))


def nbns_vectors():
    P = "nbns-message"
    out = []
    q = nbname("WORKGROUP", 0x1D)
    a = nbns_header(0x8A01, 0, 0, rd=1, b=1, counts=(1, 0, 0, 0)) + q + u16(0x20, 1)
    out.append(("01-name-query-broadcast-roundtrip.json", vec(P, "name-query-broadcast-roundtrip", a,
                {"inet.dns_id": str(0x8A01), "inet.dns_qr": "0", "nbns.opcode": "0", "inet.dns_rd": "1", "nbns.broadcast": "1",
                 "nbns.questions.#": "1", "nbns.questions[0].nbns.question_name_len1": "32",
                 "nbns.questions[0].nbns.question_name_label1": first_level(nb16("WORKGROUP", 0x1D)),
                 "nbns.questions[0].nbns.question_type": "32", "nbns.questions[0].nbns.question_class": "1"},
                ref=R_NS, note="a broadcast name query (section 4.2.12) for WORKGROUP with suffix 0x1D")))
    b = nbns_header(0x8A01, 1, 0, aa=1, rd=1, counts=(0, 1, 0, 0)) + rr(nbname("FILESRV", 0x20), 0x20, 300000,
                                                                       nb_entry(0, 2, "192.0.2.10") + nb_entry(0, 2, "198.51.100.10"))
    out.append(("02-positive-query-response-roundtrip.json", vec(P, "positive-query-response-roundtrip", b,
                {"inet.dns_qr": "1", "inet.dns_aa": "1", "nbns.answers[0].nbns.rr_type": "32", "nbns.answers[0].nbns.ttl": "300000",
                 "nbns.answers[0].nbns.nb_entries.#": "2", "nbns.answers[0].nbns.nb_entries[0].nbns.nb_ont": "2",
                 "nbns.answers[0].nbns.nb_entries[1].nbns.nb_address": str(v4("198.51.100.10"))},
                ref=R_NS, note="a positive name query response (4.2.13) with two addresses of an M node")))
    c = (nbns_header(0x0102, 0, 5, rd=1, b=1, counts=(1, 0, 0, 1)) + nbname("HOST7", 0x00) + u16(0x20, 1) +
         rr(pointer(12), 0x20, 0, nb_entry(0, 0, "192.0.2.7")))
    out.append(("03-registration-with-pointer-roundtrip.json", vec(P, "registration-with-pointer-roundtrip", c,
                {"nbns.opcode": "5", "nbns.additional[0].nbns.rr_name_t1": "3", "nbns.additional[0].nbns.rr_name_pointer": "12",
                 "nbns.additional[0].nbns.nb_entries[0].nbns.nb_address": str(v4("192.0.2.7"))},
                ref=R_NS, note="a name registration request (4.2.2) whose additional record names the question by a pointer to offset 12")))
    stats = (bytes.fromhex("02005e0053a1") + bytes([0, 0]) + u16(3, 60, 0, 0, 1, 0) + u32(1200, 3400) + u16(0, 0, 32, 64, 64, 0, 16, 16, 1450))
    names = (nb16("FILESRV", 0x00) + bits([(0, 1), (0, 2), (0, 1), (0, 1), (1, 1), (1, 1), (0, 9)]) +
             nb16("WORKGROUP", 0x00) + bits([(1, 1), (0, 2), (0, 1), (0, 1), (1, 1), (0, 1), (0, 9)]))
    d = nbns_header(0x0007, 1, 0, aa=1, counts=(0, 1, 0, 0)) + rr(nbname("*", 0x00), 0x21, 0, bytes([2]) + names + stats)
    out.append(("04-node-status-response-roundtrip.json", vec(P, "node-status-response-roundtrip", d,
                {"nbns.answers[0].nbns.rr_type": "33", "nbns.answers[0].nbns.node_names.#": "2",
                 "nbns.answers[0].nbns.node_names[0].nbns.node_name": nb16("FILESRV", 0).hex(),
                 "nbns.answers[0].nbns.node_names[0].nbns.node_permanent": "1", "nbns.answers[0].nbns.node_names[1].nbns.node_group": "1",
                 "nbns.answers[0].nbns.unit_id": "02005e0053a1", "nbns.answers[0].nbns.good_sends": "1200",
                 "nbns.answers[0].nbns.session_data_packet_size": "1450"},
                ref=R_NS + ".18", note="a node status response with two names and the 46-octet statistics")))
    e = (nbns_header(0x0009, 1, 0, rd=1, ra=1, counts=(0, 0, 1, 1)) +
         rr(nbname("PRINTSRV", 0x20), 2, 0, nbname("NBNS2", 0x20)) + rr(nbname("NBNS2", 0x20), 1, 0, u32(v4("203.0.113.53"))))
    out.append(("05-redirect-response-roundtrip.json", vec(P, "redirect-response-roundtrip", e,
                {"nbns.authority[0].nbns.rr_type": "2", "nbns.authority[0].nbns.ns_name_len1": "32",
                 "nbns.additional[0].nbns.rr_type": "1", "nbns.additional[0].nbns.a_address": str(v4("203.0.113.53"))},
                ref=R_NS + ".15", note="a redirect name query response: an NS record and the name server's A record")))
    f = nbns_header(0x0102, 1, 7, aa=1, counts=(0, 1, 0, 0)) + rr(nbname("HOST7", 0x00), 0x0A, 2, u16(0x2910))
    out.append(("06-wack-response-roundtrip.json", vec(P, "wack-response-roundtrip", f,
                {"nbns.opcode": "7", "nbns.answers[0].nbns.rr_type": "10", "nbns.answers[0].nbns.rdata.#": "2"},
                ref=R_NS + ".16", note="a WACK: a NULL record whose two data octets repeat the request's opcode and flags")))
    g = nbns_header(0x0003, 0, 0, counts=(1, 0, 0, 0)) + nbname("LAB", 0x20, ("corp", "example", "com")) + u16(0x20, 1)
    out.append(("07-name-with-scope-roundtrip.json", vec(P, "name-with-scope-roundtrip", g,
                {"nbns.questions[0].nbns.question_name_label2": "corp", "nbns.questions[0].nbns.question_name_label3": "example",
                 "nbns.questions[0].nbns.question_name_label4": "com", "nbns.questions[0].nbns.question_name_len5": "0"},
                ref=R_NS + ".1", note="a unicast query whose name has a three-label scope")))
    h = nbns_header(0x8A01, 1, 0, aa=1, tc=1, rd=1, ra=1, counts=(0, 0, 0, 0))
    out.append(("08-to-dns-header.json", vec(P, "to-dns-header", h, to="dns-header",
                expect=u16(0x8A01) + bits([(1, 1), (0, 4), (1, 1), (1, 1), (1, 1), (1, 1), (0, 3), (0, 4)]) + u16(0, 0, 0, 0),
                ref=R_NS + " and RFC 1035 section 4.1.1", note="the transaction ID and the R, AA, TC, RD and RA bits carry over; the NetBIOS opcode, B and rcode do not")))
    out.append(("09-cut-record-is-malformed.json", vec(P, "cut-record-is-malformed", b[:-3], error="malformed-wire",
                ref=R_NS, note="the RDLENGTH states 12 octets and 9 follow")))
    out.append(("10-reserved-label-tag-is-no-kind.json", vec(P, "reserved-label-tag-is-no-kind",
                nbns_header(1, 0, 0, counts=(1, 0, 0, 0)) + b"\x60" + bytes(4), error="no-kind",
                ref=R_NS + ".1", note="a name whose first octet has the reserved high bits 01")))
    return P, out


# ---------------------------------------------------------------- NetBIOS datagrams

def dgm_header(typ, dgm_id, src, port, snt=0, first=1, more=0):
    return bytes([typ]) + bits([(0, 4), (snt, 2), (first, 1), (more, 1)]) + u16(dgm_id) + u32(v4(src)) + u16(port)


def nbdgm_vectors():
    P = "nbdgm-message"
    out = []
    src, dst, data = nbname("CLIENT1", 0x00), nbname("FILESRV", 0x20), b"\xffSMB%"
    a = dgm_header(0x10, 0x4321, "192.0.2.21", 138) + u16(len(src) + len(dst) + len(data), 0) + src + dst + data
    out.append(("01-direct-unique-roundtrip.json", vec(P, "direct-unique-roundtrip", a,
                {"nbdgm.msg_type": "16", "nbdgm.first": "1", "nbdgm.dgm_id": str(0x4321), "nbdgm.source_ip": str(v4("192.0.2.21")),
                 "nbdgm.source_port": "138", "nbdgm.dgm_length": str(len(src) + len(dst) + len(data)),
                 "nbdgm.source_name_label1": first_level(nb16("CLIENT1", 0)), "nbdgm.user_data.#": str(len(data))},
                ref=R_DG, note="a direct unique datagram with five octets of user data")))
    src2, dst2 = nbname("CLIENT1", 0x00, ("example", "com")), nbname("WORKGROUP", 0x1E, ("example", "com"))
    b = dgm_header(0x12, 0x4322, "192.0.2.21", 138, snt=1, first=0, more=1) + u16(200, 64) + src2 + dst2 + bytes(range(8))
    out.append(("02-broadcast-fragment-roundtrip.json", vec(P, "broadcast-fragment-roundtrip", b,
                {"nbdgm.msg_type": "18", "nbdgm.source_node_type": "1", "nbdgm.first": "0", "nbdgm.more": "1", "nbdgm.packet_offset": "64",
                 "nbdgm.destination_name_label2": "example"},
                ref=R_DG, note="a broadcast datagram fragment from a P node, not the first, more to follow, names with a scope")))
    c = dgm_header(0x13, 0x4321, "198.51.100.1", 138, snt=3) + bytes([0x82])
    out.append(("03-error-packet-roundtrip.json", vec(P, "error-packet-roundtrip", c,
                {"nbdgm.msg_type": "19", "nbdgm.source_node_type": "3", "nbdgm.error_code": str(0x82)},
                ref=R_DG, note="an error packet from an NBDD: destination name not present")))
    d = dgm_header(0x14, 0x0005, "192.0.2.21", 138) + nbname("FILESRV", 0x20)
    out.append(("04-query-request-roundtrip.json", vec(P, "query-request-roundtrip", d, {"nbdgm.msg_type": "20"},
                ref=R_DG, note="a datagram query request")))
    out.append(("05-pointer-in-datagram-name-is-no-kind.json", vec(P, "pointer-in-datagram-name-is-no-kind",
                dgm_header(0x14, 6, "192.0.2.21", 138) + pointer(12), error="no-kind",
                ref=R_DG, note="section 4.1: pointers are not allowed in datagram packets")))
    out.append(("06-unknown-type-is-no-kind.json", vec(P, "unknown-type-is-no-kind", dgm_header(0x17, 6, "192.0.2.21", 138),
                error="no-kind", ref=R_DG, note="message type 0x17 is not defined")))
    out.append(("07-cut-header-is-malformed.json", vec(P, "cut-header-is-malformed", a[:9], error="malformed-wire",
                ref=R_DG, note="the header stops inside the source address")))
    return P, out


# ---------------------------------------------------------------- LLMNR

def llmnr(i, qr, op, c, tc, t, z, rcode, counts):
    return u16(i) + bits([(qr, 1), (op, 4), (c, 1), (tc, 1), (t, 1), (z, 4), (rcode, 4)]) + u16(*counts)


def dnsh(i, qr, op, aa, tc, rd, ra, z, rcode, counts):
    return u16(i) + bits([(qr, 1), (op, 4), (aa, 1), (tc, 1), (rd, 1), (ra, 1), (z, 3), (rcode, 4)]) + u16(*counts)


def llmnr_vectors():
    P = "llmnr-header"
    out = []
    a = llmnr(0x1234, 0, 0, 0, 0, 0, 0, 0, (1, 0, 0, 0))
    out.append(("01-query-roundtrip.json", vec(P, "query-roundtrip", a,
                {"inet.dns_id": str(0x1234), "inet.dns_qr": "0", "llmnr.conflict": "0", "llmnr.tentative": "0", "inet.dns_qdcount": "1"},
                ref=R_LL, note="a query with one question")))
    b = llmnr(0x1234, 1, 0, 1, 0, 1, 0, 0, (1, 1, 0, 0))
    out.append(("02-response-conflict-tentative-roundtrip.json", vec(P, "response-conflict-tentative-roundtrip", b,
                {"inet.dns_qr": "1", "llmnr.conflict": "1", "llmnr.tentative": "1", "inet.dns_ancount": "1"},
                ref=R_LL, note="a response with C and T set")))
    c = llmnr(0xFFFF, 1, 15, 1, 1, 1, 15, 15, (0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF))
    out.append(("03-every-bit-edge-roundtrip.json", vec(P, "every-bit-edge-roundtrip", c, {"llmnr.z": "15", "inet.dns_rcode": "15"},
                ref=R_LL, note="every bit set, the reserved Z bits included")))
    d = llmnr(0x0042, 1, 0, 1, 1, 1, 0, 0, (1, 2, 0, 1))
    out.append(("04-to-dns-header.json", vec(P, "to-dns-header", d, to="dns-header", expect=dnsh(0x0042, 1, 0, 0, 1, 0, 0, 0, 0, (1, 2, 0, 1)),
                ref=R_LL + " and RFC 1035 section 4.1.1", note="ID, QR, opcode, TC, rcode and the counts carry over; C and T do not, so AA and RD are 0")))
    out.append(("05-eleven-octets-is-malformed.json", vec(P, "eleven-octets-is-malformed", a[:11], error="malformed-wire",
                ref=R_LL, note="the header without its last octet")))
    e = dnsh(0x0042, 1, 0, 1, 1, 1, 1, 0, 0, (1, 1, 0, 0))
    cross = ("dns-header", "to-llmnr-header-flags-not-shared.json",
             vec("dns-header", "to-llmnr-header-flags-not-shared", e, to=P, expect=llmnr(0x0042, 1, 0, 0, 1, 0, 0, 0, (1, 1, 0, 0)),
                 ref="RFC 1035 section 4.1.1 and " + R_LL, note="AA, RD and RA have no LLMNR meaning and are dropped; C, T and Z are written 0"))
    return P, out, cross


# ---------------------------------------------------------------- SLPv2

def lstr(s):
    return u16(len(s)) + s


def slp(fn, xid, body, lang=b"en", o=0, f=0, r=0, ext=0):
    rest = bits([(o, 1), (f, 1), (r, 1), (0, 13)]) + ext.to_bytes(3, "big") + u16(xid) + lstr(lang) + body
    total = 2 + 3 + len(rest)
    return bytes([2, fn]) + total.to_bytes(3, "big") + rest


def url_entry(lifetime, url, auths=()):
    return bytes([0]) + u16(lifetime) + lstr(url) + bytes([len(auths)]) + b"".join(auths)


def auth_block(bsd, ts, spi, data):
    body = u32(ts) + lstr(spi) + data
    return u16(bsd, 4 + len(body)) + body


def slp_vectors():
    P = "slp-message"
    out = []
    a = slp(1, 0x0101, lstr(b"192.0.2.9") + lstr(b"service:printer") + lstr(b"DEFAULT") + lstr(b"(location=floor2)") + lstr(b""), r=1)
    out.append(("01-service-request-roundtrip.json", vec(P, "service-request-roundtrip", a,
                {"slp.function_id": "1", "slp.request_mcast": "1", "slp.xid": str(0x0101), "slp.language_tag.#": "2",
                 "slp.service_type.#": "15", "slp.spi.#": "0"},
                ref=R_SLP + ".1", note="a multicast SrvRqst with a previous responder, type, scope and predicate, no SPI")))
    auth = auth_block(2, 0x7F000000, b"key1", bytes(range(20)))
    b = slp(2, 0x0101, u16(0, 2) + url_entry(10800, b"service:printer:lpr://192.0.2.31/queue") +
            url_entry(600, b"service:printer:ipp://192.0.2.32/ipp", (auth,)))
    out.append(("02-service-reply-with-auth-roundtrip.json", vec(P, "service-reply-with-auth-roundtrip", b,
                {"slp.function_id": "2", "slp.error_code": "0", "slp.url_entries.#": "2", "slp.url_entries[0].slp.url_lifetime": "10800",
                 "slp.url_entries[1].slp.url_auths.#": "1", "slp.url_entries[1].slp.url_auths[0].slp.auth_bsd": "2",
                 "slp.url_entries[1].slp.url_auths[0].slp.auth_timestamp": str(0x7F000000),
                 "slp.url_entries[1].slp.url_auths[0].slp.auth_data.#": "20"},
                ref=R_SLP + ".2, 4.3 and 9.2", note="a SrvRply with two URL entries, the second with one authentication block")))
    c = slp(5, 0x0202, u16(0), lang=b"en-GB")
    out.append(("03-service-ack-roundtrip.json", vec(P, "service-ack-roundtrip", c, {"slp.function_id": "5", "slp.error_code": "0"},
                ref=R_SLP + ".4", note="a SrvAck with no error")))
    d = slp(8, 0, u16(0) + u32(0x5F000000) + lstr(b"service:directory-agent://192.0.2.1") + lstr(b"DEFAULT") + lstr(b"") + lstr(b"") + bytes([0]))
    out.append(("04-da-advert-as-octets-roundtrip.json", vec(P, "da-advert-as-octets-roundtrip", d, {"slp.function_id": "8"},
                ref=R_SLP, note="an unsolicited DAAdvert (XID 0), its body kept as octets")))
    out.append(("05-version-1-is-no-kind.json", vec(P, "version-1-is-no-kind", bytes([1]) + c[1:], error="no-kind",
                ref=R_SLP, note="the first octet is not version 2")))
    out.append(("06-shorter-than-length-is-malformed.json", vec(P, "shorter-than-length-is-malformed", c[:-1], error="malformed-wire",
                ref=R_SLP, note="the length states one octet more than the input holds")))
    return P, out


def build(out):
    counts = {}
    lp, lv, cross = llmnr_vectors()
    for pack, vs in (nbns_vectors(), nbdgm_vectors(), (lp, lv), slp_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    out.write("packs/%s/vectors/%s" % (cross[0], cross[1]), json.dumps(cross[2], indent=2) + "\n")
    counts[cross[0]] = 1
    return counts


def main(argv=None):
    return genio.vector_main("dirnaming-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
