#!/usr/bin/env python3
"""gtp-vectors: write the vectors of the gtpu, gtpv2c and pfcp packs.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of 3GPP TS 29.281 clauses 5 and 8 (GTP-U header, extension headers,
IEs), TS 29.274 clauses 5 and 8 (GTPv2-C header, IE format, IMSI, Cause, Recovery, EBI, F-TEID,
Bearer Context) and TS 29.244 clauses 7.2 and 8 (PFCP header, IE format, Cause, Source and
Destination Interface, Precedence, PDR ID, F-SEID, Node ID, Recovery Time Stamp), as their ETSI
editions of Release 19 state them: every multi-octet field big-endian.

Inputs: messages built here field by field from values chosen here; no message is taken from a
document. Addresses are from the documentation ranges of RFC 5737 and RFC 3849; the IMSI uses the
test network code 001 01.

`expect` of every vector is this program's packing of the decoded values, which for these messages
is the input; `model` holds the values that were packed.

Usage: python3 -I tools/gen/gtp-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = ("built by tools/gen/gtp-vectors.py from values chosen there; layout restated from %s; expect "
          "derived there, no engine run")
R_U = "3GPP TS 29.281 clauses 5 and 8"
R_C = "3GPP TS 29.274 clauses 5 and 8"
R_P = "3GPP TS 29.244 clauses 7.2 and 8"


def u8(*v):
    return bytes(v)


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def u64(v):
    return struct.pack(">Q", v)


def v4(t):
    return int(ipaddress.IPv4Address(t))


def v6(t):
    return ipaddress.IPv6Address(t).packed


def vec(pack, name, inp, model=None, error=None, ref=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


# ---------------------------------------------------------------- GTP-U

def gtpu(mtype, teid, rest, e=0, s=0, pn=0):
    flags = (1 << 5) | (1 << 4) | (e << 2) | (s << 1) | pn
    return u8(flags, mtype) + u16(len(rest)) + u32(teid) + rest


def ext(content, nxt):
    assert (len(content) + 2) % 4 == 0
    return u8((len(content) + 2) // 4) + content + u8(nxt)


def gtpu_vectors():
    out = []
    pdu = bytes.fromhex("450000140001000040110000c0000201c0000202")
    m = gtpu(255, 0x1234ABCD, pdu)
    out.append(("01-g-pdu-roundtrip.json", vec("gtpu", "g-pdu-roundtrip", m,
                {"gtpu.version": "1", "gtpu.pt": "1", "gtpu.flag_e": "0", "gtpu.message_type": "255",
                 "gtpu.teid": str(0x1234ABCD), "gtpu.t_pdu.#": "20", "@absent": ["gtpu.sequence"]},
                ref=R_U + "; a G-PDU without optional fields, carrying a 20-octet IPv4 header")))
    psc = bytes([0x00, 0x09])
    m = gtpu(255, 0x1234ABCD, u16(0) + u8(0, 0x85) + ext(psc, 0) + pdu, e=1)
    out.append(("02-g-pdu-pdu-session-container-roundtrip.json", vec("gtpu", "g-pdu-pdu-session-container-roundtrip", m,
                {"gtpu.flag_e": "1", "gtpu.next_type": str(0x85), "gtpu.ext1_length": "1",
                 "gtpu.ext1_content": psc.hex(), "gtpu.ext1_next_type": "0", "gtpu.t_pdu.#": "20"},
                ref=R_U + "; a G-PDU with one extension header, a PDU session container (type 0x85, QFI 9)")))
    m = gtpu(255, 0x0000BEEF, u16(77) + u8(0, 0x85) + ext(psc, 0x40) + ext(u16(2152), 0) + pdu, e=1, s=1)
    out.append(("03-g-pdu-two-extension-headers-roundtrip.json", vec("gtpu", "g-pdu-two-extension-headers-roundtrip", m,
                {"gtpu.flag_s": "1", "gtpu.sequence": "77", "gtpu.ext1_next_type": str(0x40), "gtpu.ext2_length": "1",
                 "gtpu.ext2_content": u16(2152).hex(), "gtpu.ext2_next_type": "0"},
                ref=R_U + "; a G-PDU with a sequence number and two extension headers: a PDU session container, then "
                    "a UDP port")))
    m = gtpu(2, 0, u16(9) + u8(0, 0) + u8(14, 0), s=1)
    out.append(("04-echo-response-roundtrip.json", vec("gtpu", "echo-response-roundtrip", m,
                {"gtpu.message_type": "2", "gtpu.sequence": "9", "gtpu.ies.#": "1", "gtpu.ies[0].gtpu.ie_type": "14",
                 "gtpu.ies[0].gtpu.restart_counter": "0"},
                ref=R_U + "; an echo response with its sequence number and a Recovery IE")))
    m = gtpu(26, 0, u16(3) + u8(0, 0) + u8(16) + u32(0x1234ABCD) + u8(133) + u16(4) + u32(v4("192.0.2.20")), s=1)
    out.append(("05-error-indication-roundtrip.json", vec("gtpu", "error-indication-roundtrip", m,
                {"gtpu.message_type": "26", "gtpu.ies.#": "2", "gtpu.ies[0].gtpu.teid_data_i": str(0x1234ABCD),
                 "gtpu.ies[1].gtpu.ie_type": "133", "gtpu.ies[1].gtpu.ie_value.#": "4"},
                ref=R_U + "; an error indication with TEID Data I and a GTP-U peer address")))
    m = gtpu(254, 0x1234ABCD, b"")
    out.append(("06-end-marker-roundtrip.json", vec("gtpu", "end-marker-roundtrip", m,
                {"gtpu.message_type": "254", "gtpu.ies.#": "0"}, ref=R_U + "; an end marker, the header alone")))
    out.append(("07-truncated-is-malformed.json", vec("gtpu", "truncated-is-malformed", gtpu(255, 1, pdu)[:-3],
                error="malformed-wire", ref=R_U + "; a G-PDU shorter than its length field")))
    m = gtpu(31, 0, u16(5) + u8(0, 0) + u8(141, 2, 0x40, 0x85), s=1)
    out.append(("08-supported-extension-headers-roundtrip.json", vec("gtpu", "supported-extension-headers-roundtrip", m,
                {"gtpu.message_type": "31", "gtpu.ies.#": "1", "gtpu.ies[0].gtpu.ie_type": "141",
                 "gtpu.ies[0].gtpu.ie_value.#": "2", "gtpu.ies[0].gtpu.ie_value[0].gtpu.octet": str(0x40),
                 "gtpu.ies[0].gtpu.ie_value[1].gtpu.octet": str(0x85)},
                ref=R_U + "; a Supported Extension Headers Notification (type 31) with its Extension Header Type List "
                    "IE (141, clause 8.5): a 1-octet length, 2, then the types 0x40 and 0x85")))
    return [("gtpu",) + x for x in out]


# ---------------------------------------------------------------- GTPv2-C

def gtpv2(mtype, ies, teid=None, seq=1, prio=None, p=0):
    t = 1 if teid is not None else 0
    mp = 1 if prio is not None else 0
    flags = (2 << 5) | (p << 4) | (t << 3) | (mp << 2)
    body = (u32(teid) if t else b"") + seq.to_bytes(3, "big") + u8((prio << 4) if mp else 0) + b"".join(ies)
    return u8(flags, mtype) + u16(len(body)) + body


def ie2(t, value, instance=0):
    return u8(t) + u16(len(value)) + u8(instance) + value


def tbcd(digits):
    if len(digits) % 2:
        digits += "f"
    return bytes(int(digits[i + 1], 16) << 4 | int(digits[i], 16) for i in range(0, len(digits), 2))


def fteid(v4addr, iface, teid, v6addr=None):
    flags = (0x80 if v4addr else 0) | (0x40 if v6addr else 0) | iface
    return u8(flags) + u32(teid) + (u32(v4(v4addr)) if v4addr else b"") + (v6(v6addr) if v6addr else b"")


def gtpv2_vectors():
    out = []
    m = gtpv2(1, [ie2(3, u8(7))], seq=0x000101)
    out.append(("01-echo-request-roundtrip.json", vec("gtpv2c", "echo-request-roundtrip", m,
                {"@kind": "message", "gtpv2.flag_t": "0", "gtpv2.message_type": "1", "gtpv2.sequence": str(0x101),
                 "gtpv2.ies.#": "1", "gtpv2.ies[0].gtpv2.restart_counter": "7", "@absent": ["gtpv2.teid"]},
                ref=R_C + "; an echo request (no TEID) with a Recovery IE")))
    imsi = tbcd("001010123456789")
    csr = gtpv2(32, [ie2(1, imsi), ie2(87, fteid("192.0.2.1", 10, 0x0A0B0C0D)),
                     ie2(93, ie2(73, u8(5)) + ie2(87, fteid("192.0.2.2", 0, 0x11223344), instance=0))],
                teid=0, seq=0x000102)
    out.append(("02-create-session-request-roundtrip.json", vec("gtpv2c", "create-session-request-roundtrip", csr,
                {"gtpv2.flag_t": "1", "gtpv2.teid": "0", "gtpv2.message_type": "32", "gtpv2.ies.#": "3",
                 "gtpv2.ies[0].gtpv2.imsi_digits.#": "8", "gtpv2.ies[0].gtpv2.imsi_digits[0].gtpv2.digit_odd": "0",
                 "gtpv2.ies[0].gtpv2.imsi_digits[7].gtpv2.digit_even": "15",
                 "gtpv2.ies[1].gtpv2.fteid_v4": "1", "gtpv2.ies[1].gtpv2.interface_type": "10",
                 "gtpv2.ies[1].gtpv2.teid": str(0x0A0B0C0D), "gtpv2.ies[1].gtpv2.ipv4": str(v4("192.0.2.1")),
                 "gtpv2.ies[2].gtpv2.grouped_ies.#": "2", "gtpv2.ies[2].gtpv2.grouped_ies[0].gtpv2.ebi": "5",
                 "gtpv2.ies[2].gtpv2.grouped_ies[1].gtpv2.interface_type": "0"},
                ref=R_C + "; a Create Session Request with an IMSI (15 digits and the filler), the sender's F-TEID and "
                    "a Bearer Context holding an EBI and an F-TEID")))
    csp = gtpv2(33, [ie2(2, u8(16, 0)), ie2(87, fteid("192.0.2.3", 11, 0x55667788, "2001:db8::3"), instance=1),
                     ie2(93, ie2(2, u8(16, 0)) + ie2(73, u8(5)))], teid=0x0A0B0C0D, seq=0x000102, prio=3)
    out.append(("03-create-session-response-roundtrip.json", vec("gtpv2c", "create-session-response-roundtrip", csp,
                {"gtpv2.flag_mp": "1", "gtpv2.message_priority": "3", "gtpv2.teid": str(0x0A0B0C0D),
                 "gtpv2.ies[0].gtpv2.cause": "16", "gtpv2.ies[0].gtpv2.offending_ie.#": "0",
                 "gtpv2.ies[1].gtpv2.instance": "1", "gtpv2.ies[1].gtpv2.fteid_v6": "1",
                 "gtpv2.ies[1].gtpv2.ipv6": v6("2001:db8::3").hex(),
                 "gtpv2.ies[2].gtpv2.grouped_ies[0].gtpv2.cause": "16"},
                ref=R_C + "; a Create Session Response with message priority 3, Cause 16, an F-TEID with IPv4 and IPv6 "
                    "and a Bearer Context")))
    apn = b"\x08internet"
    dsr = gtpv2(36, [ie2(71, apn), ie2(73, u8(5))], teid=0x55667788, seq=0x000103)
    out.append(("04-unlaid-ie-roundtrip.json", vec("gtpv2c", "unlaid-ie-roundtrip", dsr,
                {"gtpv2.message_type": "36", "gtpv2.ies[0].gtpv2.ie_type": "71",
                 "gtpv2.ies[0].gtpv2.ie_value.#": str(len(apn))},
                ref=R_C + "; a Delete Session Request with an APN IE (type 71), kept as octets, and an EBI")))
    bad = bytearray(gtpv2(1, [ie2(3, u8(7))]))
    bad[0] = (1 << 5)
    out.append(("05-version-1-is-no-kind.json", vec("gtpv2c", "version-1-is-no-kind", bytes(bad), error="no-kind",
                ref=R_C + "; the echo request with version 1 in place of 2")))
    out.append(("06-truncated-is-malformed.json", vec("gtpv2c", "truncated-is-malformed", csr[:-2], error="malformed-wire",
                ref=R_C + "; the Create Session Request without its last 2 octets")))
    return [("gtpv2c",) + x for x in out]


# ---------------------------------------------------------------- PFCP

def pfcp(mtype, ies, seid=None, seq=1, prio=None):
    s = 1 if seid is not None else 0
    mp = 1 if prio is not None else 0
    flags = (1 << 5) | (mp << 1) | s
    body = (u64(seid) if s else b"") + seq.to_bytes(3, "big") + u8((prio << 4) if mp else 0) + b"".join(ies)
    return u8(flags, mtype) + u16(len(body)) + body


def iep(t, value, enterprise=None):
    if enterprise is not None:
        return u16(0x8000 | t, 2 + len(value)) + u16(enterprise) + value
    return u16(t, len(value)) + value


def pfcp_vectors():
    out = []
    rts = 3982469213
    m = pfcp(1, [iep(96, u32(rts))], seq=0x000201)
    out.append(("01-heartbeat-request-roundtrip.json", vec("pfcp", "heartbeat-request-roundtrip", m,
                {"@kind": "message", "pfcp.flag_s": "0", "pfcp.message_type": "1", "pfcp.ies.#": "1",
                 "pfcp.ies[0].pfcp.recovery_time_stamp": str(rts), "@absent": ["pfcp.header_seid"]},
                ref=R_P + "; a heartbeat request with a Recovery Time Stamp")))
    m = pfcp(5, [iep(60, u8(0) + u32(v4("192.0.2.30"))), iep(96, u32(rts))], seq=0x000202)
    out.append(("02-association-setup-request-roundtrip.json", vec("pfcp", "association-setup-request-roundtrip", m,
                {"pfcp.message_type": "5", "pfcp.ies[0].pfcp.node_id_type": "0",
                 "pfcp.ies[0].pfcp.ipv4": str(v4("192.0.2.30"))},
                ref=R_P + "; an association setup request with an IPv4 Node ID and a Recovery Time Stamp")))
    fqdn = b"\x03smf\x07example\x03org"
    pdi = iep(2, iep(20, u8(0)))
    create_pdr = iep(1, iep(56, u16(1)) + iep(29, u32(255)) + pdi)
    create_far = iep(3, iep(108, u32(1)) + iep(44, u16(0x0002)))
    m = pfcp(50, [iep(60, u8(2) + fqdn), iep(57, u8(0x02) + u64(0x0102030405060708) + u32(v4("192.0.2.31"))),
                  create_pdr, create_far], seid=0, seq=0x000203)
    out.append(("03-session-establishment-request-roundtrip.json", vec("pfcp", "session-establishment-request-roundtrip", m,
                {"pfcp.flag_s": "1", "pfcp.header_seid": "0", "pfcp.message_type": "50", "pfcp.ies.#": "4",
                 "pfcp.ies[0].pfcp.node_id_type": "2", "pfcp.ies[0].pfcp.node_id_fqdn.#": str(len(fqdn)),
                 "pfcp.ies[1].pfcp.fseid_v4": "1", "pfcp.ies[1].pfcp.seid": str(0x0102030405060708),
                 "pfcp.ies[2].pfcp.grouped_ies.#": "3", "pfcp.ies[2].pfcp.grouped_ies[0].pfcp.rule_id": "1",
                 "pfcp.ies[2].pfcp.grouped_ies[1].pfcp.precedence": "255",
                 "pfcp.ies[2].pfcp.grouped_ies[2].pfcp.ie_value.#": str(len(pdi) - 4),
                 "pfcp.ies[3].pfcp.grouped_ies.#": "2"},
                ref=R_P + "; a session establishment request with an FQDN Node ID, an IPv4 F-SEID, a Create PDR (PDR ID, "
                    "Precedence, and a PDI kept as octets, two levels down) and a Create FAR")))
    m = pfcp(51, [iep(60, u8(1) + v6("2001:db8::30")), iep(19, u8(1)),
                  iep(57, u8(0x01) + u64(0x1112131415161718) + v6("2001:db8::30"))], seid=0x0102030405060708,
             seq=0x000203, prio=2)
    out.append(("04-session-establishment-response-roundtrip.json", vec("pfcp", "session-establishment-response-roundtrip", m,
                {"pfcp.flag_mp": "1", "pfcp.message_priority": "2", "pfcp.header_seid": str(0x0102030405060708),
                 "pfcp.ies[0].pfcp.ipv6": v6("2001:db8::30").hex(), "pfcp.ies[1].pfcp.cause": "1",
                 "pfcp.ies[2].pfcp.fseid_v6": "1"},
                ref=R_P + "; a session establishment response with message priority 2, an IPv6 Node ID, Cause 1 and an "
                    "IPv6 F-SEID")))
    m = pfcp(1, [iep(96, u32(rts)), iep(5, b"\xAA\xBB", enterprise=32473)], seq=0x000204)
    out.append(("05-vendor-ie-roundtrip.json", vec("pfcp", "vendor-ie-roundtrip", m,
                {"pfcp.ies[1].pfcp.ie_vendor": "1", "pfcp.ies[1].pfcp.ie_type": "5",
                 "pfcp.ies[1].pfcp.enterprise_id": "32473", "pfcp.ies[1].pfcp.ie_value.#": "2"},
                ref=R_P + "; a heartbeat request with a vendor-specific IE (enterprise 32473), its value as octets")))
    bad = bytearray(pfcp(1, [iep(96, u32(rts))]))
    bad[0] = (2 << 5)
    out.append(("06-version-2-is-no-kind.json", vec("pfcp", "version-2-is-no-kind", bytes(bad), error="no-kind",
                ref=R_P + "; the heartbeat request with version 2 in place of 1")))
    out.append(("07-truncated-is-malformed.json", vec("pfcp", "truncated-is-malformed", m[:-1], error="malformed-wire",
                ref=R_P + "; the vendor IE message without its last octet")))
    return [("pfcp",) + x for x in out]


def build_files(out):
    written = {}
    for pack, fname, v in gtpu_vectors() + gtpv2_vectors() + pfcp_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("gtp-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
