#!/usr/bin/env python3
"""Write the 3GPP mobile-core packs and their modules: the GTP-U header with its extension headers
and IEs (3GPP TS 29.281), the GTPv2-C header and IEs (TS 29.274) and the PFCP header and IEs
(TS 29.244), each from the ETSI edition of Release 19.

The extension header chain, the optional header fields and the IE lists repeat in several places;
this script writes them from one statement each. The vectors are not written here:
tools/gen/gtp-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/gtp-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

DOC = {"29281": ("ETSI TS 129 281 V19.2.0 (2026-01), 3GPP TS 29.281 version 19.2.0 Release 19, General Packet Radio System (GPRS) Tunnelling Protocol User Plane (GTPv1-U)",
                 "https://www.etsi.org/deliver/etsi_ts/129200_129299/129281/19.02.00_60/ts_129281v190200p.pdf",
                 "30ca7128fd87024d60b7d1ca79cf15c6b16c4725de9a2c6fdc780e212e545639"),
       "29274": ("ETSI TS 129 274 V19.6.0 (2026-03), 3GPP TS 29.274 version 19.6.0 Release 19, Evolved General Packet Radio Service (GPRS) Tunnelling Protocol for Control plane (GTPv2-C)",
                 "https://www.etsi.org/deliver/etsi_ts/129200_129299/129274/19.06.00_60/ts_129274v190600p.pdf",
                 "b825a7cb0c266f25b3b1343947f01022e97b0330608c796052bb6ce4973b0380"),
       "29244": ("ETSI TS 129 244 V19.6.0 (2026-08), 3GPP TS 29.244 version 19.6.0 Release 19, Interface between the Control Plane and the User Plane nodes (PFCP)",
                 "https://www.etsi.org/deliver/etsi_ts/129200_129299/129244/19.06.00_60/ts_129244v190600p.pdf",
                 "5f5858f6174563cbe7c6cb8eb49a99fe2bb64b39b4d086e6163f42eea540f9ea")}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def head(name, what, doc, mod, extra_uses=()):
    title, url, sha = DOC[doc]
    L = ["# %s. Public; the source states no licence (pack.md, PROVENANCE.md). Written by" % what,
         "# tools/gen/gtp-pack.py; do not edit by hand. Wire bits, layout sequential, msb; I/O is hex text.",
         "format        %s" % name, "version       0.1.0", "distribution  public",
         'source        "%s, %s (sha256 %s); layout restated"' % (title, url, sha),
         "uses          %s" % mod]
    L += ["uses          %s" % u for u in extra_uses]
    return L + ["wire          bits", "layout        sequential", "bit_order     msb", ""]


# ---------------------------------------------------------------- GTP-U (TS 29.281)

MAX_EXT = 4
MAX_EXT_LEN = 16


def ext_chain(level):
    """Extension header `level` (1 to MAX_EXT), entered when the previous next type is not 0: its
    length in 4-octet units, its content (4 × length − 2 octets, as hex), its next type."""
    g = "gtpu"
    p = "ext%d_" % level
    L = [F(g, p + "length", 8), "switch  gtpu.%slength" % p]
    for n in range(1, MAX_EXT_LEN + 1):
        L.append("  case  %d" % n)
        L.append("    " + F(g, p + "content", (4 * n - 2) * 8, "hex"))
    L.append("end")
    L.append(F(g, p + "next_type", 8))
    L.append("switch  gtpu.%snext_type" % p)
    L.append("  case  0")
    if level < MAX_EXT:
        L.append("  else")
        L += ind(2, ext_chain(level + 1))
    L.append("end")
    return L


def gtpu_optional():
    """The sequence number, N-PDU number and next extension header type, present when E, S or PN
    is 1; the extension headers when the next type is not 0."""
    g = "gtpu"
    return ([F(g, "sequence", 16), F(g, "npdu", 8), F(g, "next_type", 8), "switch  gtpu.next_type", "  case  0",
             "  else"] + ind(2, ext_chain(1)) + ["end"])


GTPU_IES = (["group  gtpu.ies  rest", "  " + F("gtpu", "ie_type", 8), "  switch  gtpu.ie_type",
             "    case  14", "      " + F("gtpu", "restart_counter", 8),
             "    case  16", "      " + F("gtpu", "teid_data_i", 32),
             "    case  141", "      length  8  bytes"] + ind(4, octets("gtpu", "ie_value")) + ["      end",
             "    else", "      length  16  bytes"] + ind(4, octets("gtpu", "ie_value")) + ["      end", "  end", "end"])


def gtpu_pack():
    g = "gtpu"
    L = head("gtpu", "GTP-U message (3GPP TS 29.281): the header, its optional fields and extension headers, and the payload",
             "29281", g)
    L += [F(g, "version", 3), F(g, "pt", 1), F(g, "spare", 1), F(g, "flag_e", 1), F(g, "flag_s", 1), F(g, "flag_pn", 1),
          F(g, "message_type", 8), "length  16  bytes  plus  -4", "  " + F(g, "teid", 32)]
    opt = gtpu_optional()
    body = (["switch  gtpu.flag_e", "  case  1"] + ind(2, opt) + ["  case  0", "    switch  gtpu.flag_s", "      case  1"] +
            ind(4, opt) + ["      case  0", "        switch  gtpu.flag_pn", "          case  1"] + ind(6, opt) +
            ["          case  0", "        end", "    end", "end"])
    payload = (["switch  gtpu.message_type", "  case  255"] + ind(2, octets(g, "t_pdu")) + ["  else"] + ind(2, GTPU_IES) +
               ["end"])
    L += ind(1, body + payload) + ["end"]
    return "\n".join(L) + "\n"


GTPU_KEYS = [
    ("key", "version", "GTP version, 1"),
    ("key", "pt", "protocol type: 1 GTP, 0 GTP' (charging)"),
    ("key", "spare", "spare bit, 0"),
    ("key", "flag_e", "E: 1 when the next extension header type is to be read"),
    ("key", "flag_s", "S: 1 when the sequence number is to be read"),
    ("key", "flag_pn", "PN: 1 when the N-PDU number is to be read"),
    ("key", "message_type", "message type: 1 echo request, 2 echo response, 26 error indication, 31 supported extension headers notification, 253 tunnel status, 254 end marker, 255 G-PDU"),
    ("key", "teid", "tunnel endpoint identifier of the receiving end; 0 in echo and error indication"),
    ("key", "sequence", "sequence number (present when E, S or PN is 1; meaningful when S is 1)"),
    ("key", "npdu", "N-PDU number (present when E, S or PN is 1; meaningful when PN is 1)"),
    ("key", "next_type", "type of the first extension header, 0 for none: 0x40 UDP port, 0x85 PDU session container, 0xC0 PDCP PDU number, ...; the two high bits say who must understand it"),
] + [k for i in range(1, MAX_EXT + 1) for k in (
    ("key", "ext%d_length" % i, "extension header %d: its length in 4-octet units" % i),
    ("key", "ext%d_content" % i, "extension header %d: its content, as hexadecimal digits (its type is the next type before it)" % i),
    ("key", "ext%d_next_type" % i, "extension header %d: the type of the extension header after it, 0 for none" % i))] + [
    ("list", "t_pdu", "G-PDU: the user packet (T-PDU), as octets"),
    ("list", "ies", "the information elements of a signalling message, in order"),
    ("key", "ie_type", "IE type: 14 recovery, 16 tunnel endpoint identifier data I; 128 and above have a length, of 2 octets except 141 extension header type list, whose length is 1 octet (133 GTP-U peer address, 141, 255 private extension)"),
    ("key", "restart_counter", "recovery IE: restart counter"),
    ("key", "teid_data_i", "tunnel endpoint identifier data I IE"),
    ("list", "ie_value", "value of an IE with a length field, as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- GTPv2-C (TS 29.274)

GTPV2_GROUPED = "93,109,195"


def gtpv2_ies(lst, nested):
    """IEs to the end of the extent (TS 29.274 clause 8.2.1): type, length of the value (a `length
    16 bytes plus -1` block, which also holds the spare and instance octet), spare, instance, value."""
    v = "gtpv2"
    L = ["group  gtpv2.%s  rest" % lst, "  " + F(v, "ie_type", 8), "  length  16  bytes  plus  -1",
         "    " + F(v, "ie_spare", 4), "    " + F(v, "instance", 4), "    switch  gtpv2.ie_type"]
    cases = [
        ("1", ["group  gtpv2.imsi_digits  rest", "  " + F(v, "digit_even", 4), "  " + F(v, "digit_odd", 4), "end"]),
        ("2", [F(v, "cause", 8), F(v, "cause_spare", 5), F(v, "cause_pce", 1), F(v, "cause_bce", 1), F(v, "cause_cs", 1)] +
         octets(v, "offending_ie")),
        ("3", [F(v, "restart_counter", 8)]),
        ("73", [F(v, "ebi_spare", 4), F(v, "ebi", 4)] + octets(v, "extra")),
        ("87", [F(v, "fteid_v4", 1), F(v, "fteid_v6", 1), F(v, "interface_type", 6), F(v, "teid", 32),
                "switch  gtpv2.fteid_v4", "  case  1", "    " + F(v, "ipv4", 32), "  case  0", "end",
                "switch  gtpv2.fteid_v6", "  case  1", "    " + F(v, "ipv6", 128, "hex"), "  case  0", "end"] +
         octets(v, "extra")),
    ]
    if nested:
        cases.append((GTPV2_GROUPED, gtpv2_ies("grouped_ies", False)))
    for codes, body in cases:
        L.append("      case  %s" % codes)
        L += ind(4, body)
    L.append("      else")
    L += ind(4, octets(v, "ie_value"))
    L += ["    end", "  end", "end"]
    return L


def gtpv2_pack():
    v = "gtpv2"
    L = head("gtpv2c", "GTPv2-C message (3GPP TS 29.274): the header and the IEs, with the common IEs laid out",
             "29274", v)
    L += ["kind    message", "when    3  2", F(v, "flag_p", 1), F(v, "flag_t", 1), F(v, "flag_mp", 1), F(v, "flags_spare", 2),
          F(v, "message_type", 8), "length  16  bytes", "  switch  gtpv2.flag_t", "    case  1",
          "      " + F(v, "teid", 32), "    case  0", "  end", "  " + F(v, "sequence", 24),
          "  switch  gtpv2.flag_mp", "    case  1", "      " + F(v, "message_priority", 4), "      pad  4",
          "    case  0", "      pad  8", "  end"]
    L += ind(1, gtpv2_ies("ies", True)) + ["end"]
    return "\n".join(L) + "\n"


GTPV2_KEYS = [
    ("key", "flag_p", "P: 1 when another GTP-C message is piggybacked after this one"),
    ("key", "flag_t", "T: 1 when the header holds a TEID (0 for echo and version not supported)"),
    ("key", "flag_mp", "MP: 1 when the header holds a message priority"),
    ("key", "flags_spare", "the two spare bits of the first octet"),
    ("key", "message_type", "message type: 1 echo request, 2 echo response, 32 create session request, 33 create session response, 34 modify bearer request, 35 modify bearer response, 36 delete session request, 37 delete session response, ..."),
    ("key", "teid", "tunnel endpoint identifier (the header's, or an F-TEID's)"),
    ("key", "sequence", "sequence number, 24 bits"),
    ("key", "message_priority", "message priority, 0 highest to 15"),
    ("list", "ies", "the IEs of the message, in order"),
    ("list", "grouped_ies", "the IEs inside a grouped IE (Bearer Context, PDN Connection, SCEF PDN Connection), in order"),
    ("key", "ie_type", "IE type: 1 IMSI, 2 Cause, 3 Recovery, 73 EBI, 87 F-TEID, 93 Bearer Context, ..."),
    ("key", "ie_spare", "the four spare bits before the instance"),
    ("key", "instance", "instance, telling apart IEs of the same type in one message"),
    ("list", "imsi_digits", "IMSI: the digits, two per octet (TBCD); a 15-digit IMSI ends with the filler 15"),
    ("key", "digit_even", "IMSI: the high nibble of an octet, the later digit (15 for the filler)"),
    ("key", "digit_odd", "IMSI: the low nibble of an octet, the earlier digit"),
    ("key", "cause", "Cause: cause value (16 request accepted, 64 context not found, ...)"),
    ("key", "cause_spare", "Cause: the five spare bits"),
    ("key", "cause_pce", "Cause: PCE, the cause comes from the PDN connection"),
    ("key", "cause_bce", "Cause: BCE, the cause comes from a bearer context"),
    ("key", "cause_cs", "Cause: CS, the cause comes from the remote node, not this one"),
    ("list", "offending_ie", "Cause: the type, length and instance of the offending IE, as octets"),
    ("key", "restart_counter", "Recovery: restart counter"),
    ("key", "ebi_spare", "EBI: the four spare bits"),
    ("key", "ebi", "EPS bearer ID, 5 to 15"),
    ("key", "fteid_v4", "F-TEID: 1 when an IPv4 address follows"),
    ("key", "fteid_v6", "F-TEID: 1 when an IPv6 address follows"),
    ("key", "interface_type", "F-TEID: interface type (0 S1-U eNodeB GTP-U, 1 S1-U SGW GTP-U, ..., 10 S11 MME GTP-C, 11 S11/S4 SGW GTP-C, ...)"),
    ("key", "ipv4", "F-TEID: IPv4 address, as an unsigned 32-bit integer"),
    ("key", "ipv6", "F-TEID: IPv6 address, 32 hexadecimal digits"),
    ("list", "extra", "octets after the defined fields of an extendable IE"),
    ("list", "ie_value", "value of an IE the pack does not lay out, as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- PFCP (TS 29.244)

PFCP_GROUPED = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,51,54,58,59"


def pfcp_ies(lst, nested):
    """IEs to the end of the extent (TS 29.244 clause 8.1.1): the vendor bit and the 15-bit type,
    the length of what follows (a `length 16 bytes` block), the enterprise ID of a vendor IE, the value."""
    p = "pfcp"
    L = ["group  pfcp.%s  rest" % lst, "  " + F(p, "ie_vendor", 1), "  " + F(p, "ie_type", 15), "  length  16  bytes",
         "    switch  pfcp.ie_vendor", "      case  1", "        " + F(p, "enterprise_id", 16)]
    L += ind(4, octets(p, "ie_value"))
    L += ["      case  0", "        switch  pfcp.ie_type"]
    cases = [
        ("19", [F(p, "cause", 8)]),
        ("20,42", [F(p, "interface_spare", 4), F(p, "interface_value", 4)] + octets(p, "extra")),
        ("29", [F(p, "precedence", 32)] + octets(p, "extra")),
        ("56", [F(p, "rule_id", 16)] + octets(p, "extra")),
        ("57", [F(p, "fseid_spare", 6), F(p, "fseid_v4", 1), F(p, "fseid_v6", 1), F(p, "seid", 64),
                "switch  pfcp.fseid_v4", "  case  1", "    " + F(p, "ipv4", 32), "  case  0", "end",
                "switch  pfcp.fseid_v6", "  case  1", "    " + F(p, "ipv6", 128, "hex"), "  case  0", "end"] +
         octets(p, "extra")),
        # Node ID is extendable (TS 29.244 Table 8.1.2-1, Figure 8.2.38-1): octets after an IPv4 or
        # IPv6 address are kept; an FQDN runs to the end of the IE, so it can have none.
        ("60", [F(p, "node_id_spare", 4), F(p, "node_id_type", 4), "switch  pfcp.node_id_type", "  case  0",
                "    " + F(p, "ipv4", 32)] + ind(2, octets(p, "extra")) +
               ["  case  1", "    " + F(p, "ipv6", 128, "hex")] + ind(2, octets(p, "extra")) + ["  else"] +
         ind(2, octets(p, "node_id_fqdn")) + ["end"]),
        ("96", [F(p, "recovery_time_stamp", 32)] + octets(p, "extra")),
    ]
    if nested:
        cases.append((PFCP_GROUPED, pfcp_ies("grouped_ies", False)))
    for codes, body in cases:
        L.append("          case  %s" % codes)
        L += ind(6, body)
    L.append("          else")
    L += ind(6, octets(p, "ie_value"))
    L += ["        end", "    end", "  end", "end"]
    return L


def pfcp_pack():
    p = "pfcp"
    L = head("pfcp", "PFCP message (3GPP TS 29.244): the header and the IEs, with common node and session IEs laid out",
             "29244", p)
    L += ["kind    message", "when    3  1", F(p, "flags_spare", 2), F(p, "flag_fo", 1), F(p, "flag_mp", 1), F(p, "flag_s", 1),
          F(p, "message_type", 8), "length  16  bytes", "  switch  pfcp.flag_s", "    case  1",
          "      " + F(p, "header_seid", 64), "    case  0", "  end", "  " + F(p, "sequence", 24),
          "  switch  pfcp.flag_mp", "    case  1", "      " + F(p, "message_priority", 4), "      pad  4",
          "    case  0", "      pad  8", "  end"]
    L += ind(1, pfcp_ies("ies", True)) + ["end"]
    return "\n".join(L) + "\n"


PFCP_KEYS = [
    ("key", "flags_spare", "the two spare bits of the first octet"),
    ("key", "flag_fo", "FO: 1 when another PFCP message follows in the same datagram"),
    ("key", "flag_mp", "MP: 1 when the header holds a message priority"),
    ("key", "flag_s", "S: 1 when the header holds a SEID (session messages)"),
    ("key", "message_type", "message type: 1 heartbeat request, 2 heartbeat response, 5 association setup request, 6 association setup response, ..., 50 session establishment request, 51 session establishment response, 52 session modification request, ..."),
    ("key", "header_seid", "session endpoint identifier of the receiver (as uint reads 64 bits: negative when the top bit is set)"),
    ("key", "sequence", "sequence number, 24 bits"),
    ("key", "message_priority", "message priority, 0 highest to 15"),
    ("list", "ies", "the IEs of the message, in order"),
    ("list", "grouped_ies", "the IEs inside a grouped IE (Create PDR, PDI, Create FAR and the others of types 1 to 18, 51, 54, 58, 59), in order"),
    ("key", "ie_vendor", "1 when the IE is vendor-specific (an enterprise ID follows the length)"),
    ("key", "ie_type", "IE type: 19 Cause, 20 Source Interface, 29 Precedence, 42 Destination Interface, 56 PDR ID, 57 F-SEID, 60 Node ID, 96 Recovery Time Stamp, ..."),
    ("key", "enterprise_id", "IANA enterprise number of a vendor-specific IE"),
    ("key", "cause", "Cause: cause value (1 request accepted, 64 request rejected, ...)"),
    ("key", "interface_spare", "Source and Destination Interface: the four spare bits"),
    ("key", "interface_value", "Source and Destination Interface: 0 access, 1 core, 2 SGi-LAN/N6-LAN, 3 CP function, ..."),
    ("key", "precedence", "Precedence: the precedence of a PDR (lower is higher precedence)"),
    ("key", "rule_id", "PDR ID: the rule identifier"),
    ("key", "fseid_spare", "F-SEID: the six spare bits"),
    ("key", "fseid_v4", "F-SEID: 1 when an IPv4 address follows"),
    ("key", "fseid_v6", "F-SEID: 1 when an IPv6 address follows"),
    ("key", "seid", "F-SEID: session endpoint identifier (as uint reads 64 bits)"),
    ("key", "ipv4", "an IPv4 address (F-SEID, Node ID), as an unsigned 32-bit integer"),
    ("key", "ipv6", "an IPv6 address (F-SEID, Node ID), 32 hexadecimal digits"),
    ("key", "node_id_spare", "Node ID: the four spare bits"),
    ("key", "node_id_type", "Node ID: 0 IPv4 address, 1 IPv6 address, 2 FQDN"),
    ("list", "node_id_fqdn", "Node ID: the FQDN in DNS label form, as octets"),
    ("key", "recovery_time_stamp", "Recovery Time Stamp: when the node last started, seconds since 1900-01-01 00:00 UTC (NTP)"),
    ("list", "extra", "octets after the defined fields of an extendable IE"),
    ("list", "ie_value", "value of an IE the pack does not lay out, as octets"),
    ("key", "octet", "one octet"),
]


def module(name, header, doc_keys, keys, strings=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public",
                  'source        "%s; restated by goat-transformers; no licence stated"' % doc_keys]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in strings else "int", k[2]))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/gtpu/pack.def", gtpu_pack())
    out.write("packs/gtpv2c/pack.def", gtpv2_pack())
    out.write("packs/pfcp/pack.def", pfcp_pack())
    out.write("model/gtpu.def", module("gtpu", ["# The gtpu module: the fields of GTP-U messages (3GPP TS 29.281). Written by tools/gen/gtp-pack.py."],
                                       "ETSI TS 129 281 V19.2.0 (3GPP TS 29.281 Release 19)", GTPU_KEYS,
                                       ["ext%d_content" % i for i in range(1, MAX_EXT + 1)]))
    out.write("model/gtpv2.def", module("gtpv2", ["# The gtpv2 module: the fields of GTPv2-C messages (3GPP TS 29.274). Written by tools/gen/gtp-pack.py."],
                                        "ETSI TS 129 274 V19.6.0 (3GPP TS 29.274 Release 19)", GTPV2_KEYS, ["ipv6"]))
    out.write("model/pfcp.def", module("pfcp", ["# The pfcp module: the fields of PFCP messages (3GPP TS 29.244). Written by tools/gen/gtp-pack.py."],
                                       "ETSI TS 129 244 V19.6.0 (3GPP TS 29.244 Release 19)", PFCP_KEYS, ["ipv6"]))
    return {"gtp": 6}


def main(argv=None):
    return genio.vector_main("gtp-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
