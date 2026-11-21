#!/usr/bin/env python3
"""Write the directory and naming packs and their modules:

- nbns-message: a NetBIOS Name Service packet (RFC 1002 section 4.2): the DNS-shaped header with
  the NetBIOS opcode and flags, the question entries, and the answer, authority and additional
  resource records with the NB, NBSTAT, A, NS and NULL record data. Names are label runs (the
  first label is the 32-character first-level encoding of the NetBIOS name, the others the
  scope); a compression pointer is kept as its offset.
- nbdgm-message: a NetBIOS Datagram Service packet (RFC 1002 section 4.4): the header, then by
  message type the source and destination names and the user data, the error code, or the
  destination name of a query.
- llmnr-header: the 12-octet LLMNR header (RFC 4795 section 2.1.1), the DNS header with the C
  (conflict) and T (tentative) bits and four reserved bits; the rest of the message is the DNS
  message, read by dns-message.
- slp-message: an SLPv2 message (RFC 2608 section 8): the header with its whole-message length
  and language tag, the Service Request strings, the Service Reply URL entries with their
  authentication blocks, the Service Acknowledgement error code; other functions as octets.

The vectors are not written here: tools/gen/dirnaming-vectors.py derives them with an encoder of
its own.

Usage: python3 -I tools/gen/dirnaming-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "nb": ('source        "IETF RFC 1002, Protocol Standard for a NetBIOS Service on a TCP/UDP Transport: Detailed Specifications, '
           'March 1987, sections 4.1, 4.2.1, 4.2.18 and 4.4, https://www.rfc-editor.org/rfc/rfc1002.txt; layouts restated"'),
    "llmnr": ('source        "IETF RFC 4795, Link-Local Multicast Name Resolution (LLMNR), January 2007, section 2.1.1, '
              'https://www.rfc-editor.org/rfc/rfc4795.txt; with RFC 1035 section 4.1.1 for the shared header fields; layout restated"'),
    "slp": ('source        "IETF RFC 2608, Service Location Protocol, Version 2, June 1999, sections 4.3, 8, 8.1, 8.2, 8.4 and 9.2, '
            'https://www.rfc-editor.org/rfc/rfc2608.txt; layouts restated"'),
}
MAX_LABELS = 4


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


def F(k, b, tr="uint"):
    return "field  %s  %d  %s" % (k, b, tr)


def octets(lst, octet):
    return ["group  %s  rest" % lst, "  " + F(octet, 8), "end"]


def head(name, comment, src, uses, wire=("wire          bits", "layout        sequential", "bit_order     msb")):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + list(wire) + [""])


def text(L):
    return "\n".join(L) + "\n"


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC[src]]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], k[0], k[2]))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- names (RFC 1002 section 4.1)

def name(mod, prefix, pointer=True, d=1):
    """The labels of a name from depth d: a 2-bit tag (0 a label, 3 a pointer when allowed), the label."""
    tag, ln = "%s.%s_t%d" % (mod, prefix, d), "%s.%s_len%d" % (mod, prefix, d)
    ptr = [("3", [F("%s.%s_pointer" % (mod, prefix), 14)])] if pointer else []
    if d > MAX_LABELS:
        return [F(tag, 2)] + sw(tag, [("0", [F(ln, 6)] + sw(ln, [("0", [])]))] + ptr)
    labels = [("0", [])] + [(str(n), [F("%s.%s_label%d" % (mod, prefix, d), 8 * n, "chars:ascii8")]) for n in range(1, 64)]
    rest = sw(ln, [("0", [])], name(mod, prefix, pointer, d + 1))
    return [F(tag, 2)] + sw(tag, [("0", [F(ln, 6)] + sw(ln, labels) + rest)] + ptr)


def name_keys(prefix, what, pointer=True):
    keys = []
    for d in range(1, MAX_LABELS + 2):
        keys.append(("int", "%s_t%d" % (prefix, d), "%s, label %d: tag, 0 a label%s" % (what, d, ", 3 a compression pointer" if pointer else "")))
        keys.append(("int", "%s_len%d" % (prefix, d), "%s, label %d: length in octets (0 ends the name)" % (what, d)))
        if d <= MAX_LABELS:
            first = " (the first label is the NetBIOS name in first-level encoding: 32 letters A to P, two per octet of the name)" if d == 1 else " (scope)"
            keys.append(("string", "%s_label%d" % (prefix, d), "%s, label %d: its characters%s" % (what, d, first)))
    if pointer:
        keys.append(("int", prefix + "_pointer", "%s: the compression pointer, the offset in the packet of the rest of the name (not followed)" % what))
    return keys


# ---------------------------------------------------------------- NetBIOS Name Service

N = "nbns"


def nbns_pack():
    nb = ["group  nbns.nb_entries  rest", "  " + F("nbns.nb_group", 1), "  " + F("nbns.nb_ont", 2), "  " + F("nbns.nb_reserved", 13),
          "  " + F("nbns.nb_address", 32), "end"]
    stats = [F("nbns.unit_id", 48, "hex"), F("nbns.jumpers", 8), F("nbns.test_result", 8), F("nbns.version_number", 16),
             F("nbns.period_of_statistics", 16), F("nbns.crcs", 16), F("nbns.alignment_errors", 16), F("nbns.collisions", 16),
             F("nbns.send_aborts", 16), F("nbns.good_sends", 32), F("nbns.good_receives", 32), F("nbns.retransmits", 16),
             F("nbns.no_resource_conditions", 16), F("nbns.free_command_blocks", 16), F("nbns.total_command_blocks", 16),
             F("nbns.max_total_command_blocks", 16), F("nbns.pending_sessions", 16), F("nbns.max_pending_sessions", 16),
             F("nbns.max_total_sessions", 16), F("nbns.session_data_packet_size", 16)]
    nbstat = (["count  num_names  8", "group  nbns.node_names  count  @num_names"] +
              ind(1, [F("nbns.node_name", 128, "hex"), F("nbns.node_group", 1), F("nbns.node_ont", 2), F("nbns.node_deregister", 1),
                      F("nbns.node_conflict", 1), F("nbns.node_active", 1), F("nbns.node_permanent", 1), F("nbns.node_reserved", 9)]) +
              ["end"] + stats)
    rdata = sw("nbns.rr_type", [
        ("32", nb),
        ("33", nbstat),
        ("1", [F("nbns.a_address", 32)]),
        ("2", name(N, "ns_name"))],
        octets("nbns.rdata", "nbns.octet"))
    rr = name(N, "rr_name") + [F("nbns.rr_type", 16), F("nbns.rr_class", 16), F("nbns.ttl", 32), "length  16  bytes"] + ind(1, rdata) + ["end"]
    L = head("nbns-message", ["NetBIOS Name Service packet (RFC 1002 section 4.2): the header, the question entries and the resource",
                              "records. Names are label runs; a compression pointer is kept as its offset. Written by",
                              "tools/gen/dirnaming-pack.py; do not edit by hand."], "nb", ["inet", N])
    L += ["field  inet.dns_id  16  uint", "field  inet.dns_qr  1  uint", F("nbns.opcode", 4), "field  inet.dns_aa  1  uint",
          "field  inet.dns_tc  1  uint", "field  inet.dns_rd  1  uint", "field  inet.dns_ra  1  uint", F("nbns.nm_reserved", 2),
          F("nbns.broadcast", 1), F("nbns.rcode", 4), "count  qdcount  16", "count  ancount  16", "count  nscount  16", "count  arcount  16",
          "group  nbns.questions  count  @qdcount"]
    L += ind(1, name(N, "question_name") + [F("nbns.question_type", 16), F("nbns.question_class", 16)]) + ["end"]
    for sec, cnt in (("answers", "ancount"), ("authority", "nscount"), ("additional", "arcount")):
        L += ["group  nbns.%s  count  @%s" % (sec, cnt)] + ind(1, rr) + ["end"]
    return text(L)


NBNS_KEYS = ([
    ("int", "opcode", "operation: 0 query, 5 registration, 6 release, 7 WACK, 8 refresh"),
    ("int", "nm_reserved", "the two reserved flag bits, 0"),
    ("int", "broadcast", "flag B: the packet was broadcast or multicast"),
    ("int", "rcode", "result code of a response (0 none, 1 format error, 2 server failure, 3 name error, 4 unsupported, 5 refused, 6 active, 7 conflict)"),
    ("list", "questions", "the question entries (their count is written from the list)"),
    ("int", "question_type", "question type: 0x20 NB, 0x21 NBSTAT"), ("int", "question_class", "question class: 1 IN"),
    ("list", "answers", "the answer resource records"), ("list", "authority", "the authority resource records"),
    ("list", "additional", "the additional resource records"),
    ("int", "rr_type", "record type: 1 A, 2 NS, 10 NULL, 0x20 NB, 0x21 NBSTAT"), ("int", "rr_class", "record class: 1 IN"),
    ("int", "ttl", "time to live of the name, in seconds"),
    ("list", "nb_entries", "NB record data: the entries, each flags and an address"),
    ("int", "nb_group", "NB entry: G, 1 a group name, 0 a unique name"),
    ("int", "nb_ont", "NB entry: owner node type, 0 B node, 1 P node, 2 M node"),
    ("int", "nb_reserved", "NB entry: the 13 reserved flag bits, 0"),
    ("int", "nb_address", "NB entry: the owner's IPv4 address, as an unsigned 32-bit integer"),
    ("list", "node_names", "NBSTAT record data: the node name array (its count is written from the list)"),
    ("string", "node_name", "node name entry: the 16-octet NetBIOS name, as hexadecimal digits"),
    ("int", "node_group", "node name entry: G, group name"), ("int", "node_ont", "node name entry: owner node type"),
    ("int", "node_deregister", "node name entry: DRG, being deleted"), ("int", "node_conflict", "node name entry: CNF, in conflict"),
    ("int", "node_active", "node name entry: ACT, active (always 1)"), ("int", "node_permanent", "node name entry: PRM, the permanent node name"),
    ("int", "node_reserved", "node name entry: the 9 reserved flag bits, 0"),
    ("string", "unit_id", "NBSTAT statistics: unique unit ID, 6 octets as hexadecimal digits"),
    ("int", "jumpers", "NBSTAT statistics: jumpers"), ("int", "test_result", "NBSTAT statistics: test result"),
    ("int", "version_number", "NBSTAT statistics: version number"), ("int", "period_of_statistics", "NBSTAT statistics: period of statistics"),
    ("int", "crcs", "NBSTAT statistics: number of CRC errors"), ("int", "alignment_errors", "NBSTAT statistics: number of alignment errors"),
    ("int", "collisions", "NBSTAT statistics: number of collisions"), ("int", "send_aborts", "NBSTAT statistics: number of send aborts"),
    ("int", "good_sends", "NBSTAT statistics: number of good sends"), ("int", "good_receives", "NBSTAT statistics: number of good receives"),
    ("int", "retransmits", "NBSTAT statistics: number of retransmits"),
    ("int", "no_resource_conditions", "NBSTAT statistics: number of no-resource conditions"),
    ("int", "free_command_blocks", "NBSTAT statistics: free command blocks"), ("int", "total_command_blocks", "NBSTAT statistics: total command blocks"),
    ("int", "max_total_command_blocks", "NBSTAT statistics: maximum total command blocks"),
    ("int", "pending_sessions", "NBSTAT statistics: pending sessions"), ("int", "max_pending_sessions", "NBSTAT statistics: maximum pending sessions"),
    ("int", "max_total_sessions", "NBSTAT statistics: maximum total sessions possible"),
    ("int", "session_data_packet_size", "NBSTAT statistics: session data packet size"),
    ("int", "a_address", "A record data: an IPv4 address, as an unsigned 32-bit integer"),
    ("list", "rdata", "record data of another type (NULL, as in the WACK response, included), as octets"), ("int", "octet", "one octet"),
] + name_keys("question_name", "question name") + name_keys("rr_name", "record name") + name_keys("ns_name", "NS record data: the name server's name"))


# ---------------------------------------------------------------- NetBIOS Datagram Service

D = "nbdgm"


def nbdgm_pack():
    L = head("nbdgm-message", ["NetBIOS Datagram Service packet (RFC 1002 section 4.4): the header, then by message type the names and",
                               "user data, the error code, or the destination name of a query. Written by tools/gen/dirnaming-pack.py."],
             "nb", [D])
    L += [F("nbdgm.msg_type", 8), F("nbdgm.reserved", 4), F("nbdgm.source_node_type", 2), F("nbdgm.first", 1), F("nbdgm.more", 1),
          F("nbdgm.dgm_id", 16), F("nbdgm.source_ip", 32), F("nbdgm.source_port", 16)]
    L += sw("nbdgm.msg_type", [
        ("16,17,18", [F("nbdgm.dgm_length", 16), F("nbdgm.packet_offset", 16)] + name(D, "source_name", False) +
         name(D, "destination_name", False) + octets("nbdgm.user_data", "nbdgm.octet")),
        ("19", [F("nbdgm.error_code", 8)]),
        ("20,21,22", name(D, "destination_name", False))])
    return text(L)


NBDGM_KEYS = ([
    ("int", "msg_type", "message type: 0x10 direct unique, 0x11 direct group, 0x12 broadcast, 0x13 error, 0x14 query request, 0x15 positive and 0x16 negative query response"),
    ("int", "reserved", "the four reserved flag bits, 0"),
    ("int", "source_node_type", "SNT: 0 B node, 1 P node, 2 M node, 3 NBDD"),
    ("int", "first", "F: the first (and possibly only) fragment"), ("int", "more", "M: more fragments follow"),
    ("int", "dgm_id", "datagram ID"), ("int", "source_ip", "source IPv4 address, as an unsigned 32-bit integer"),
    ("int", "source_port", "source UDP port"), ("int", "dgm_length", "datagram length, as sent (not computed)"),
    ("int", "packet_offset", "packet offset of this fragment, as sent"),
    ("int", "error_code", "error packet: 0x82 destination name not present, 0x83 invalid source name format, 0x84 invalid destination name format"),
    ("list", "user_data", "the user data, as octets"), ("int", "octet", "one octet"),
] + name_keys("source_name", "source name", False) + name_keys("destination_name", "destination name", False))


# ---------------------------------------------------------------- LLMNR header

def llmnr_pack():
    L = head("llmnr-header", ["LLMNR header (RFC 4795 section 2.1.1): the 12-octet DNS header with the conflict and tentative bits.",
                              "Written by tools/gen/dirnaming-pack.py; do not edit by hand."], "llmnr", ["inet", "llmnr"],
             ("wire          bits", "word_bytes    1", "bit_order     msb"))
    rows = [("inet.dns_id", 0, 16), ("inet.dns_qr", 16, 1), ("inet.dns_opcode", 17, 4), ("llmnr.conflict", 21, 1), ("inet.dns_tc", 22, 1),
            ("llmnr.tentative", 23, 1), ("llmnr.z", 24, 4), ("inet.dns_rcode", 28, 4), ("inet.dns_qdcount", 32, 16),
            ("inet.dns_ancount", 48, 16), ("inet.dns_nscount", 64, 16), ("inet.dns_arcount", 80, 16)]
    L += ["field  %-20s  0:%d:%d  uint" % r for r in rows]
    return text(L)


LLMNR_KEYS = [
    ("int", "conflict", "flag C: in a query, several responses were received; in a response, the name is not unique"),
    ("int", "tentative", "flag T: the responder is authoritative but has not yet verified that the name is unique"),
    ("int", "z", "the four reserved bits, 0"),
]


# ---------------------------------------------------------------- SLPv2

S = "slp"


def lstr(lst):
    return ["length  16  bytes"] + ind(1, octets("slp." + lst, "slp.octet")) + ["end"]


def slp_pack():
    auth = (["count  url_auth_count  8", "group  slp.url_auths  count  @url_auth_count"] +
            ind(1, [F("slp.auth_bsd", 16), "length  16  bytes  plus  4"] +
                ind(1, [F("slp.auth_timestamp", 32)] + lstr("auth_spi") + octets("slp.auth_data", "slp.octet")) + ["end"]) + ["end"])
    entry = [F("slp.url_reserved", 8), F("slp.url_lifetime", 16)] + lstr("url") + auth
    L = head("slp-message", ["SLPv2 message (RFC 2608 section 8): the header with the whole-message length and the language tag, then",
                             "the Service Request strings, the Service Reply URL entries or the acknowledgement's error code; other",
                             "functions as octets. Written by tools/gen/dirnaming-pack.py; do not edit by hand."], "slp", [S])
    L += ["kind  slpv2", "when  8  2", F("slp.function_id", 8), "length  24  whole", F("slp.overflow", 1), F("slp.fresh", 1),
          F("slp.request_mcast", 1), F("slp.reserved", 13), F("slp.next_extension_offset", 24), F("slp.xid", 16)] + lstr("language_tag")
    L += sw("slp.function_id", [
        ("1", lstr("pr_list") + lstr("service_type") + lstr("scope_list") + lstr("predicate") + lstr("spi")),
        ("2", [F("slp.error_code", 16), "count  url_count  16", "group  slp.url_entries  count  @url_count"] + ind(1, entry) + ["end"]),
        ("5", [F("slp.error_code", 16)])],
        octets("slp.body", "slp.octet"))
    return text(L)


SLP_KEYS = [
    ("int", "function_id", "function: 1 SrvRqst, 2 SrvRply, 3 SrvReg, 4 SrvDeReg, 5 SrvAck, 6 AttrRqst, 7 AttrRply, 8 DAAdvert, 9 SrvTypeRqst, 10 SrvTypeRply, 11 SAAdvert"),
    ("int", "overflow", "flag O: the message did not fit in a datagram"), ("int", "fresh", "flag F: a new registration"),
    ("int", "request_mcast", "flag R: the request was multicast or broadcast"), ("int", "reserved", "the 13 reserved bits, 0"),
    ("int", "next_extension_offset", "offset from the message start of the first extension, 0 when none (the extensions are not read)"),
    ("int", "xid", "transaction ID, copied into the reply"),
    ("list", "language_tag", "the language tag, as octets"),
    ("list", "pr_list", "SrvRqst: the previous responder list, as octets"), ("list", "service_type", "SrvRqst: the service type, as octets"),
    ("list", "scope_list", "SrvRqst: the scope list, as octets"), ("list", "predicate", "SrvRqst: the predicate (an LDAPv3 search filter), as octets"),
    ("list", "spi", "SrvRqst: the SLP SPI string, as octets"),
    ("int", "error_code", "SrvRply, SrvAck: the error code (0 none)"),
    ("list", "url_entries", "SrvRply: the URL entries (their count is written from the list)"),
    ("int", "url_reserved", "URL entry: the reserved octet"), ("int", "url_lifetime", "URL entry: lifetime in seconds"),
    ("list", "url", "URL entry: the URL, as octets"),
    ("list", "url_auths", "URL entry: the URL authentication blocks (their count is written from the list)"),
    ("int", "auth_bsd", "authentication block: block structure descriptor"),
    ("int", "auth_timestamp", "authentication block: expiry, seconds since 1970-01-01T00:00Z (wrapping in 2106)"),
    ("list", "auth_spi", "authentication block: the SLP SPI string, as octets"),
    ("list", "auth_data", "authentication block: the structured authentication block, as octets"),
    ("list", "body", "the body of another function, as octets"), ("int", "octet", "one octet"),
]


def build(out):
    out.write("packs/nbns-message/pack.def", nbns_pack())
    out.write("packs/nbdgm-message/pack.def", nbdgm_pack())
    out.write("packs/llmnr-header/pack.def", llmnr_pack())
    out.write("packs/slp-message/pack.def", slp_pack())
    for m, h, src, keys in (("nbns", "NetBIOS Name Service fields (RFC 1002 section 4.2)", "nb", NBNS_KEYS),
                            ("nbdgm", "NetBIOS Datagram Service fields (RFC 1002 section 4.4)", "nb", NBDGM_KEYS),
                            ("llmnr", "the LLMNR header bits that differ from DNS (RFC 4795)", "llmnr", LLMNR_KEYS),
                            ("slp", "SLPv2 fields (RFC 2608)", "slp", SLP_KEYS)):
        out.write("model/%s.def" % m, module(m, ["# The %s module: %s. Written by tools/gen/dirnaming-pack.py." % (m, h)], src, keys))
    return {"dirnaming": 8}


def main(argv=None):
    return genio.vector_main("dirnaming-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
