#!/usr/bin/env python3
"""rdp-neg-vectors: write the vectors of tpkt-x224 and rdp-x224-negotiation.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of RFC 1006 section 6 (TPKT: version 3, a reserved octet, the
16-bit length of the whole packet), RFC 905 sections 13.2-13.7 and 13.12 (the TPDU: a length
indicator counting the header octets after itself, then the code octet and the fixed part;
user data follows the header) and [MS-RDPBCGR] 2.2.1.1-2.2.1.2.2 (the cookie line ended by
CR LF, the 8-octet negotiation structures and the 36-octet correlation info, little-endian).

Inputs: packets built here field by field from values chosen here; no packet is taken from a
document or a capture. The cookie identifier is invented.

`expect` of a round trip is this program's packing of the decoded values. Where a structure
that the RDP pack reads inside the length indicator is missing (a Connection Request with no
variable part, a cookie with no RDP_NEG_REQ, a Connection Confirm with no negotiation data),
the expectation follows ruling 7 of 0.8 of the specification: encode writes every line of a
length block, an absent one as zero bits, so one zero octet is added and both lengths grow by
one. `model` holds values that were packed.

Usage: python3 -I tools/gen/rdp-neg-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/rdp-neg-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_T = "RFC 1006 section 6 and RFC 905 section 13"
R_R = "[MS-RDPBCGR] 2.2.1.1 to 2.2.1.2.2 with RFC 1006 section 6 and RFC 905 section 13"
TP, RD = "tpkt-x224", "rdp-x224-negotiation"


def le16(v):
    return struct.pack("<H", v)


def le32(v):
    return struct.pack("<I", v)


def tpkt(tpdu_header, user=b""):
    """TPKT around one TPDU: the length indicator is the header's length; the TPKT length the whole."""
    body = bytes([len(tpdu_header)]) + tpdu_header + user
    return bytes([3, 0]) + struct.pack(">H", 4 + len(body)) + body


def cr_cc(code, dst, src, cls, opt, var=b"", credit=0):
    return bytes([(code << 4) | credit]) + struct.pack(">HH", dst, src) + bytes([(cls << 4) | opt]) + var


def dt(eot, nr):
    return bytes([0xF0, (eot << 7) | nr])


def neg(typ, flags, value):
    return bytes([typ, flags]) + le16(8) + le32(value)


def correlation(cid):
    assert len(cid) == 16
    return bytes([6, 0]) + le16(36) + cid + bytes(16)


def vec(pack, name, inp, model=None, error=None, ref=R_T, to=None, expect=None, note=""):
    v = {"name": name, "from": pack, "to": to or pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = (expect if expect is not None else inp).hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


COOKIE = b"Cookie: mstshash=exampleuser\r\n"
CID = bytes.fromhex("5a1c33e07b9d4f2a8611c2d4e6f80917")


def tpkt_vectors():
    out = []
    a = tpkt(cr_cc(14, 0, 0x1234, 0, 0, COOKIE))
    out.append(("01-connection-request-roundtrip.json", vec(TP, "connection-request-roundtrip", a,
                {"tpkt.tpdu_code": "14", "tpkt.credit": "0", "tpkt.dst_ref": "0", "tpkt.src_ref": str(0x1234), "tpkt.class": "0"},
                note="a CR of class 0 whose variable part is a cookie line, kept as octets")))
    b = tpkt(cr_cc(13, 0x1234, 0x5678, 0, 0, bytes([0xC0, 1, 0x0B])))
    out.append(("02-connection-confirm-roundtrip.json", vec(TP, "connection-confirm-roundtrip", b,
                {"tpkt.tpdu_code": "13", "tpkt.dst_ref": str(0x1234), "tpkt.src_ref": str(0x5678)},
                note="a CC with one TPDU-size parameter (code 0xC0, length 1, value 11) in its variable part")))
    c = tpkt(dt(1, 0), bytes.fromhex("7f6582"))
    out.append(("03-data-roundtrip.json", vec(TP, "data-roundtrip", c,
                {"tpkt.tpdu_code": "15", "tpkt.eot": "1", "tpkt.tpdu_nr": "0"},
                note="a DT of class 0 with the end mark set and three octets of user data")))
    d = tpkt(bytes([0x80]) + struct.pack(">HH", 0x1234, 0x5678) + bytes([1]) + bytes([0xE0, 2, 0x41, 0x42]))
    out.append(("04-disconnect-request-roundtrip.json", vec(TP, "disconnect-request-roundtrip", d,
                {"tpkt.tpdu_code": "8", "tpkt.reason": "1"},
                note="a DR with reason 1 and an additional-information parameter (code 0xE0) in its variable part")))
    e = tpkt(bytes([0x70]) + struct.pack(">H", 0x1234) + bytes([2]) + bytes([0xC1, 2, 0xF0, 0x80]))
    out.append(("05-error-roundtrip.json", vec(TP, "error-roundtrip", e,
                {"tpkt.tpdu_code": "7", "tpkt.dst_ref": str(0x1234), "tpkt.reject_cause": "2"},
                note="an ER with reject cause 2 and the invalid-TPDU parameter (code 0xC1)")))
    f = tpkt(bytes([0x60, 0x12, 0x34, 0x05]))
    out.append(("06-other-code-as-octets-roundtrip.json", vec(TP, "other-code-as-octets-roundtrip", f,
                {"tpkt.tpdu_code": "6", "tpkt.credit": "0"},
                note="an AK (code 6), not given a fixed part here: the rest of the header is kept as octets")))
    out.append(("07-to-rdp-x224-negotiation-data.json", vec(TP, "to-rdp-x224-negotiation-data", c, to=RD, ref=R_R,
                note="a DT carries over unchanged: the TPDU code, the end mark, the number and the user data")))
    out.append(("08-tpkt-version-2-is-no-kind.json", vec(TP, "tpkt-version-2-is-no-kind", bytes([2]) + c[1:], error="no-kind",
                note="the first octet is not the TPKT version 3")))
    out.append(("09-short-packet-is-malformed.json", vec(TP, "short-packet-is-malformed", c[:-1], error="malformed-wire",
                note="the TPKT length states one octet more than the input holds")))
    return TP, out


def rdp_vectors():
    out = []
    a = tpkt(cr_cc(14, 0, 0, 0, 0, COOKIE + neg(1, 0, 3)))
    out.append(("01-cookie-and-negotiation-request-roundtrip.json", vec(RD, "cookie-and-negotiation-request-roundtrip", a,
                {"tpkt.tpdu_code": "14", "rdpneg.first_octet": "67", "rdpneg.token_line": "ookie: mstshash=exampleuser",
                 "rdpneg.neg_type": "1", "rdpneg.neg_flags": "0", "rdpneg.neg_length": "8", "rdpneg.requested_protocols": "3"},
                ref=R_R, note="a CR with a cookie line and RDP_NEG_REQ asking for TLS and CredSSP")))
    b = tpkt(cr_cc(14, 0, 0, 0, 0, neg(1, 0, 0x0B)))
    out.append(("02-negotiation-request-only-roundtrip.json", vec(RD, "negotiation-request-only-roundtrip", b,
                {"rdpneg.first_octet": "1", "rdpneg.neg_flags": "0", "rdpneg.requested_protocols": str(0x0B)},
                ref=R_R, note="a CR with RDP_NEG_REQ and no cookie; protocols TLS, CredSSP and CredSSP with early authorization")))
    c = tpkt(cr_cc(14, 0, 0, 0, 0, COOKIE + neg(1, 0x08, 3) + correlation(CID)))
    out.append(("03-negotiation-request-with-correlation-roundtrip.json", vec(RD, "negotiation-request-with-correlation-roundtrip", c,
                {"rdpneg.neg_flags": "8", "rdpneg.correlation_type": "6", "rdpneg.correlation_flags": "0",
                 "rdpneg.correlation_length": "36", "rdpneg.correlation_id": CID.hex(), "rdpneg.correlation_reserved": "00" * 16},
                ref=R_R, note="the correlation-info flag 0x08 set, so the 36-octet correlation info follows")))
    d = tpkt(cr_cc(13, 0, 0x1234, 0, 0, neg(2, 0x1F, 2)))
    out.append(("04-negotiation-response-roundtrip.json", vec(RD, "negotiation-response-roundtrip", d,
                {"tpkt.tpdu_code": "13", "rdpneg.neg_type": "2", "rdpneg.neg_flags": str(0x1F), "rdpneg.selected_protocol": "2"},
                ref=R_R, note="a CC with RDP_NEG_RSP selecting CredSSP, every response flag set")))
    e = tpkt(cr_cc(13, 0, 0x1234, 0, 0, neg(3, 0, 5)))
    out.append(("05-negotiation-failure-roundtrip.json", vec(RD, "negotiation-failure-roundtrip", e,
                {"rdpneg.neg_type": "3", "rdpneg.failure_code": "5"},
                ref=R_R, note="a CC with RDP_NEG_FAILURE, failure code 5 (hybrid required by server)")))
    f = tpkt(dt(1, 0), bytes.fromhex("7f65820194"))
    out.append(("06-data-roundtrip.json", vec(RD, "data-roundtrip", f,
                {"tpkt.tpdu_code": "15", "tpkt.eot": "1"}, ref=R_R,
                note="a DT whose user data would be the start of an MCS PDU, kept as octets")))
    g = tpkt(cr_cc(14, 0, 0, 0, 0, COOKIE))
    out.append(("07-cookie-without-request-gains-zero-octet.json", vec(RD, "cookie-without-request-gains-zero-octet", g,
                expect=tpkt(cr_cc(14, 0, 0, 0, 0, COOKIE + b"\x00")), ref=R_R,
                note="the cookie alone: the absent negotiation type is written as one zero octet (ruling 7 of 0.8)")))
    h = tpkt(cr_cc(13, 0, 0x1234, 0, 0))
    out.append(("08-confirm-without-negotiation-gains-zero-octet.json", vec(RD, "confirm-without-negotiation-gains-zero-octet", h,
                expect=tpkt(cr_cc(13, 0, 0x1234, 0, 0, b"\x00")), ref=R_R,
                note="a CC with no negotiation data: the absent negotiation type is written as one zero octet (ruling 7 of 0.8)")))
    out.append(("09-to-tpkt-x224-data.json", vec(RD, "to-tpkt-x224-data", f, to=TP, ref=R_R,
                note="a DT carries over unchanged")))
    cut = tpkt(cr_cc(14, 0, 0, 0, 0, neg(1, 0x08, 3) + correlation(CID)[:32]))
    out.append(("10-cut-correlation-is-malformed.json", vec(RD, "cut-correlation-is-malformed", cut, error="malformed-wire",
                ref=R_R, note="the correlation flag set but the length indicator ends four octets into the reserved field")))
    out.append(("11-tpkt-version-2-is-no-kind.json", vec(RD, "tpkt-version-2-is-no-kind", bytes([2]) + a[1:], error="no-kind",
                ref=R_R, note="the first octet is not the TPKT version 3")))
    return RD, out


def build(out):
    counts = {}
    for pack, vs in (tpkt_vectors(), rdp_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("rdp-neg-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
