#!/usr/bin/env python3
"""Write the TPKT/X.224 pack (RFC 1006, and the TPDU layouts of RFC 905, the ISO 8073 transport protocol)
and the RDP connection negotiation pack ([MS-RDPBCGR] 2.2.1.1 and 2.2.1.2: the X.224 Connection Request
with its routing token or cookie and RDP_NEG_REQ, the Connection Confirm with RDP_NEG_RSP or
RDP_NEG_FAILURE), with their modules.

TPKT and X.224 are big-endian; the RDP negotiation structures are little-endian (`swap`). The X.224
length indicator counts the TPDU header after itself, a `length 8 bytes` block; in RDP it also counts
the routing token or cookie and the negotiation structures.
The vectors are not written here: tools/gen/rdp-neg-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/rdp-neg-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "tpkt": ('source        "IETF RFC 1006, ISO Transport Service on top of the TCP, May 1987, section 6 (TPKT), '
             'https://www.rfc-editor.org/rfc/rfc1006.txt; IETF RFC 905, ISO Transport Protocol Specification ISO DP 8073, April 1984, '
             'sections 13.2-13.7 and 13.12 (the TPDU structure), https://www.rfc-editor.org/rfc/rfc905.txt; layout restated"'),
    "rdp": ('source        "Microsoft, [MS-RDPBCGR]: Remote Desktop Protocol: Basic Connectivity and Graphics Remoting, release of 2026-03-09, '
            'sections 2.2.1.1, 2.2.1.1.1, 2.2.1.1.2, 2.2.1.2, 2.2.1.2.1 and 2.2.1.2.2, '
            'https://winprotocoldocs-bhdugrdyduf5h2e4.b02.azurefd.net/MS-RDPBCGR/%5bMS-RDPBCGR%5d.pdf (sha256 '
            '77fae7d35a5cc4f3d0f4ab86ed752182ec675369655259cb999b7c41290d2d7d), Microsoft Open Specifications copyright permission; '
            'with RFC 1006 and RFC 905 for TPKT and X.224; layout restated"'),
}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def sw(key, cases, other=None):
    L = ["switch  %s" % key]
    for vals, lines in cases:
        L.append("  case  %s" % vals)
        L += ind(2, lines)
    if other is not None:
        L.append("  else")
        L += ind(2, other)
    L.append("end")
    return L


def F(mod, k, b, tr="uint", swap=False):
    return "field  %s.%s  %d  %s%s" % (mod, k, b, tr, "  swap" if swap else "")


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


def module(name, header, src, keys, strings=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC[src]]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in strings else "int", k[2]))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- TPKT / X.224

T = "tpkt"


def tpdu_header(mod, var_cr, var_cc):
    """The TPDU after the length indicator: code and credit, then the fixed part by code."""
    refs = [F(mod, "dst_ref", 16), F(mod, "src_ref", 16)]
    return [F(mod, "tpdu_code", 4), F(mod, "credit", 4)] + sw("%s.tpdu_code" % mod, [
        ("14", refs + [F(mod, "class", 4), F(mod, "options", 4)] + var_cr),
        ("13", refs + [F(mod, "class", 4), F(mod, "options", 4)] + var_cc),
        ("15", [F(mod, "eot", 1), F(mod, "tpdu_nr", 7)]),
        ("8", refs + [F(mod, "reason", 8)] + octets(mod, "variable_part")),
        ("7", [F(mod, "dst_ref", 16), F(mod, "reject_cause", 8)] + octets(mod, "variable_part"))],
        octets(mod, "variable_part"))


def tpkt_head(mod):
    return ["kind  tpkt", "when  8  3", F(mod, "reserved", 8), "length  16  whole", "length  8  bytes"]


def tpkt_pack():
    L = head("tpkt-x224", ["TPKT (RFC 1006) and the X.224 transport TPDU inside it (RFC 905, ISO 8073): the length indicator, the TPDU",
                           "code, the fixed part of CR, CC, DT, DR and ER, the variable part and the user data. Written by",
                           "tools/gen/rdp-neg-pack.py; do not edit by hand."], "tpkt", [T])
    L += tpkt_head(T) + ind(1, tpdu_header(T, octets(T, "variable_part"), octets(T, "variable_part"))) + ["end"] + octets(T, "user_data")
    return "\n".join(L) + "\n"


TPKT_KEYS = [
    ("key", "reserved", "TPKT: the reserved octet, 0"),
    ("key", "tpdu_code", "TPDU code, the high four bits: 14 CR connection request, 13 CC connection confirm, 15 DT data, 8 DR disconnect request, 7 ER error (other codes as octets)"),
    ("key", "credit", "CR, CC: credit (CDT); other TPDUs: the low four bits of the code octet"),
    ("key", "dst_ref", "destination reference"), ("key", "src_ref", "source reference"),
    ("key", "class", "CR, CC: protocol class (0 for TP0)"), ("key", "options", "CR, CC: options (extended formats, explicit flow control)"),
    ("key", "eot", "DT: end of TSDU mark"), ("key", "tpdu_nr", "DT: TPDU send sequence number (0 in class 0)"),
    ("key", "reason", "DR: disconnect reason"), ("key", "reject_cause", "ER: reject cause"),
    ("list", "variable_part", "the TPDU's variable part (parameters), as octets"),
    ("list", "user_data", "the user data after the TPDU header (for RDP, the MCS PDUs), as octets"), ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- RDP negotiation

R = "rdpneg"


def correlation():
    return [F(R, "correlation_type", 8), F(R, "correlation_flags", 8), F(R, "correlation_length", 16, swap=True),
            F(R, "correlation_id", 128, "hex"), F(R, "correlation_reserved", 128, "hex")]


def neg_req_body():
    """RDP_NEG_REQ after its type octet, and the correlation info when the flag 0x08 is set."""
    with_corr = ",".join(str(v) for v in range(256) if v & 0x08)
    return ([F(R, "neg_flags", 8), F(R, "neg_length", 16, swap=True), F(R, "requested_protocols", 32, swap=True)] +
            sw("rdpneg.neg_flags", [(with_corr, correlation())], []))


def rdp_pack():
    cr = ([F(R, "first_octet", 8)] + sw("rdpneg.first_octet", [
        ("67", ["field  rdpneg.token_line  until:13  chars:ascii8", "const  8  10", F(R, "neg_type", 8)] +
         sw("rdpneg.neg_type", [("1", neg_req_body())], [])),
        ("1", neg_req_body())], []))
    cc = [F(R, "neg_type", 8)] + sw("rdpneg.neg_type", [
        ("2", [F(R, "neg_flags", 8), F(R, "neg_length", 16, swap=True), F(R, "selected_protocol", 32, swap=True)]),
        ("3", [F(R, "neg_flags", 8), F(R, "neg_length", 16, swap=True), F(R, "failure_code", 32, swap=True)])], [])
    L = head("rdp-x224-negotiation", ["RDP connection negotiation ([MS-RDPBCGR] 2.2.1.1 and 2.2.1.2): TPKT and the X.224 Connection Request",
                                      "with its routing token or cookie line and RDP_NEG_REQ (and correlation info), or the Connection Confirm",
                                      "with RDP_NEG_RSP or RDP_NEG_FAILURE; DT TPDUs carry the user data. Written by tools/gen/rdp-neg-pack.py."],
             "rdp", [T, R])
    L += tpkt_head(T) + ind(1, tpdu_header(T, cr, cc)) + ["end"] + octets(T, "user_data")
    return "\n".join(L) + "\n"


RDP_KEYS = [
    ("key", "first_octet", "Connection Request: the first octet after the class: 67 ('C') begins the routing token or cookie line, 1 begins RDP_NEG_REQ"),
    ("key", "token_line", "Connection Request: the routing token or cookie line after its first character 'C' (for a cookie, 'ookie: mstshash=' and the identifier), without the CR LF"),
    ("key", "neg_type", "negotiation structure type: 1 RDP_NEG_REQ, 2 RDP_NEG_RSP, 3 RDP_NEG_FAILURE"),
    ("key", "neg_flags", "negotiation flags (request: 1 restricted admin required, 2 redirected authentication required, 8 correlation info present; response: 1 extended client data supported, 2 dynvc graphics pipeline, 8 restricted admin supported, 0x10 redirected authentication supported)"),
    ("key", "neg_length", "negotiation structure length, 8"),
    ("key", "requested_protocols", "RDP_NEG_REQ: requested protocols (0 standard RDP security, 1 TLS, 2 CredSSP, 4 RDSTLS, 8 CredSSP with early user authorization, 0x10 RDS AAD auth)"),
    ("key", "selected_protocol", "RDP_NEG_RSP: the selected protocol"),
    ("key", "failure_code", "RDP_NEG_FAILURE: failure code (1 SSL required by server, 2 SSL not allowed, 3 SSL certificate not on server, 4 inconsistent flags, 5 hybrid required, 6 SSL with user auth required, 7 Entra auth required)"),
    ("key", "correlation_type", "correlation info: type, 6"), ("key", "correlation_flags", "correlation info: flags, 0"),
    ("key", "correlation_length", "correlation info: length, 36"), ("key", "correlation_id", "correlation info: the 16-octet correlation ID, as hexadecimal digits"),
    ("key", "correlation_reserved", "correlation info: the 16 reserved octets, as hexadecimal digits"),
]


def build(out):
    out.write("packs/tpkt-x224/pack.def", tpkt_pack())
    out.write("packs/rdp-x224-negotiation/pack.def", rdp_pack())
    out.write("model/tpkt.def", module("tpkt", ["# The tpkt module: TPKT and X.224 TPDU fields (RFC 1006, RFC 905). Written by tools/gen/rdp-neg-pack.py."], "tpkt", TPKT_KEYS))
    out.write("model/rdpneg.def", module("rdpneg", ["# The rdpneg module: the RDP connection negotiation structures ([MS-RDPBCGR] 2.2.1). Written by tools/gen/rdp-neg-pack.py."],
                                         "rdp", RDP_KEYS, ["token_line", "correlation_id", "correlation_reserved"]))
    return {"rdp-neg": 4}


def main(argv=None):
    return genio.vector_main("rdp-neg-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
