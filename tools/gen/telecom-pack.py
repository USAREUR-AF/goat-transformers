#!/usr/bin/env python3
"""Write the signalling transport packs and their modules: a Diameter base protocol message
(RFC 6733) and an SCTP packet with its chunks (RFC 9260).

Both formats are a header and a list of type-length-value items padded to 4 octets (Diameter AVPs,
SCTP chunks, and inside them SCTP parameters and error causes); this script writes each list from
one statement of its item. The vectors are not written here: tools/gen/telecom-vectors.py derives
them with an encoder of its own.

Usage: python3 -I tools/gen/telecom-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SHA = {"rfc6733": "b0117adedd43f9f44e444f64cd7360709c351aa27ea288d9c664c2800da8fa26",
       "rfc9260": "04bdd3255e9e5ddf1e401e9d5d726ec2750e5269cb52485db3f7f4fe77500354"}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


# ---------------------------------------------------------------- Diameter (RFC 6733)

U32 = [85, 258, 259, 261, 262, 265, 266, 267, 268, 270, 271, 272, 273, 274, 276, 277, 278, 285, 291, 295, 298,
       299, 480, 483, 485, 27]
U64 = [287]
TIME = [55]
GROUPED = [260, 279, 284, 297]
ADDRESS = [257]


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def avp_list(lst, nested):
    """AVPs to the end of the extent (RFC 6733 section 4.1): code, the flags V, M, P and five
    reserved bits, the length (a `length 24 bytes plus 8` block: it counts the 8-octet header), the
    vendor ID when V is 1, the data by code for base AVPs (vendor 0), then padding to 4 octets."""
    d = "diameter"
    L = ["group  %s.%s  rest" % (d, lst), "  " + F(d, "avp_code", 32), "  " + F(d, "avp_flag_v", 1),
         "  " + F(d, "avp_flag_m", 1), "  " + F(d, "avp_flag_p", 1), "  " + F(d, "avp_flags_low", 5),
         "  length  24  bytes  plus  8", "    switch  diameter.avp_flag_v", "      case  1",
         "        " + F(d, "vendor_id", 32)]
    L += ind(4, octets(d, "avp_data"))
    L += ["      case  0", "        switch  diameter.avp_code"]
    cases = [(U32, [F(d, "unsigned32", 32)]), (U64, [F(d, "unsigned64", 64)]), (TIME, [F(d, "time", 32)]),
             (ADDRESS, [F(d, "address_family", 16), "switch  diameter.address_family", "  case  1",
                        "    " + F(d, "address_ipv4", 32), "  case  2", "    " + F(d, "address_ipv6", 128, "hex"),
                        "  else"] + ind(2, octets(d, "avp_data")) + ["end"])]
    if nested:
        cases.append((GROUPED, avp_list("grouped_avps", False)))
    for codes, body in cases:
        L.append("          case  %s" % ",".join(str(c) for c in codes))
        L += ind(6, body)
    L.append("          else")
    L += ind(6, octets(d, "avp_data"))
    L += ["        end", "    end", "  end", "  align  32", "end"]
    return L


def diameter_pack():
    d = "diameter"
    L = ["# Diameter base protocol message (RFC 6733): the header and the AVPs, with the data of the base",
         "# protocol's AVPs laid out and one level of Grouped AVPs. Public. Written by tools/gen/telecom-pack.py;",
         "# do not edit by hand. Wire bits, layout sequential, msb; I/O is hex text. pack.md states what is mapped.",
         "format        diameter", "version       0.1.0", "distribution  public",
         'source        "IETF RFC 6733, Diameter Base Protocol, October 2012, https://www.rfc-editor.org/rfc/rfc6733.txt (sha256 %s); layout restated"' % SHA["rfc6733"],
         "uses          diameter", "wire          bits", "layout        sequential", "bit_order     msb", "",
         "kind    message", "when    8  1", "length  24  whole", F(d, "flag_r", 1), F(d, "flag_p", 1), F(d, "flag_e", 1),
         F(d, "flag_t", 1), F(d, "flags_low", 4), F(d, "command_code", 24), F(d, "application_id", 32),
         F(d, "hop_by_hop_id", 32), F(d, "end_to_end_id", 32)]
    L += avp_list("avps", True)
    return "\n".join(L) + "\n"


DIAMETER_KEYS = [
    ("key", "flag_r", "1 for a request, 0 for an answer"),
    ("key", "flag_p", "1 when the message may be proxied, relayed or redirected"),
    ("key", "flag_e", "1 when the answer is a protocol error"),
    ("key", "flag_t", "1 when the request may be a retransmission"),
    ("key", "flags_low", "the four reserved command flag bits"),
    ("key", "command_code", "command code: 257 Capabilities-Exchange, 258 Re-Auth, 271 Accounting, 274 Abort-Session, 275 Session-Termination, 280 Device-Watchdog, 282 Disconnect-Peer"),
    ("key", "application_id", "application the message belongs to: 0 for the base protocol"),
    ("key", "hop_by_hop_id", "hop-by-hop identifier, matching an answer to its request on one connection"),
    ("key", "end_to_end_id", "end-to-end identifier, for detecting duplicate requests"),
    ("list", "avps", "the AVPs of the message, in order"),
    ("list", "grouped_avps", "the AVPs inside a Grouped AVP (Vendor-Specific-Application-Id, Failed-AVP, Proxy-Info, Experimental-Result), in order"),
    ("key", "avp_code", "AVP code (with vendor ID 0, the codes of RFC 6733 section 4.5)"),
    ("key", "avp_flag_v", "V flag: 1 when a vendor ID follows"),
    ("key", "avp_flag_m", "M flag: 1 when the receiver must understand the AVP"),
    ("key", "avp_flag_p", "P flag: reserved for end-to-end security, 0"),
    ("key", "avp_flags_low", "the five reserved AVP flag bits"),
    ("key", "vendor_id", "IANA enterprise number of the AVP's vendor"),
    ("key", "unsigned32", "an Unsigned32 or Enumerated AVP's value"),
    ("key", "unsigned64", "an Unsigned64 AVP's value (as uint reads 64 bits: negative when the top bit is set)"),
    ("key", "time", "a Time AVP's value: seconds since 1900-01-01 00:00 UTC, the NTP form"),
    ("key", "address_family", "an Address AVP's address family (IANA): 1 IPv4, 2 IPv6"),
    ("key", "address_ipv4", "an Address AVP's IPv4 address, as an unsigned 32-bit integer"),
    ("key", "address_ipv6", "an Address AVP's IPv6 address, 32 hexadecimal digits"),
    ("list", "avp_data", "the data of an AVP the pack does not lay out (strings, identities, vendor AVPs), as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- SCTP (RFC 9260)

def tlv_list(lst, typekey, special):
    """Parameters or error causes (RFC 9260 sections 3.2.1 and 3.3.10): type, length (a `length 16
    bytes plus 4` block, the length counts the 4-octet header), value, padding to 4 octets."""
    s = "sctp"
    L = ["group  %s.%s  rest" % (s, lst), "  " + F(s, typekey, 16), "  length  16  bytes  plus  4"]
    if not special:
        return L + ind(2, octets(s, "value")) + ["  end", "  align  32", "end"]
    L.append("    switch  sctp.%s" % typekey)
    for codes, body in special:
        L.append("      case  %s" % codes)
        L += ind(4, body)
    L.append("      else")
    L += ind(4, octets(s, "value"))
    L += ["    end", "  end", "  align  32", "end"]
    return L


PARAMS = [("5", [F("sctp", "ipv4_address", 32)]), ("6", [F("sctp", "ipv6_address", 128, "hex")]),
          ("9", [F("sctp", "cookie_increment", 32)]),
          ("12", ["group  sctp.address_types  rest", "  " + F("sctp", "address_type", 16), "end"])]
CAUSES = [("1", [F("sctp", "stream_id", 16), "pad  16"]), ("3", [F("sctp", "staleness", 32)]),
          ("9", [F("sctp", "tsn", 32)])]


def sctp_pack():
    s = "sctp"
    L = ["# SCTP packet (RFC 9260): the common header and the chunks, with the bodies of the chunks of",
         "# section 3.3, their parameters and error causes. Public. Written by tools/gen/telecom-pack.py; do",
         "# not edit by hand. Wire bits, layout sequential, msb; I/O is hex text. pack.md states what is mapped.",
         "format        sctp-packet", "version       0.1.0", "distribution  public",
         'source        "IETF RFC 9260, Stream Control Transmission Protocol, June 2022, https://www.rfc-editor.org/rfc/rfc9260.txt (sha256 %s); layout restated"' % SHA["rfc9260"],
         "uses          inet", "uses          sctp", "wire          bits", "layout        sequential", "bit_order     msb", "",
         "field  inet.src_port               16  uint", "field  inet.dst_port               16  uint",
         "field  inet.sctp_verification_tag  32  uint", "field  inet.sctp_checksum          32  uint",
         "group  sctp.chunks  rest", "  " + F(s, "chunk_type", 8), "  " + F(s, "chunk_flags", 8),
         "  length  16  bytes  plus  4", "    switch  sctp.chunk_type"]
    init = [F(s, "initiate_tag", 32), F(s, "a_rwnd", 32), F(s, "outbound_streams", 16), F(s, "inbound_streams", 16),
            F(s, "initial_tsn", 32)] + tlv_list("parameters", "param_type", PARAMS + [("7,8", octets(s, "value"))])
    chunks = [
        ("0", "DATA", [F(s, "tsn", 32), F(s, "stream_id", 16), F(s, "stream_seq", 16), F(s, "ppid", 32)] +
         octets(s, "user_data")),
        ("1,2", "INIT, INIT ACK", init),
        ("3", "SACK", [F(s, "cum_tsn_ack", 32), F(s, "a_rwnd", 32), "count  gaps  16", "count  dups  16",
                       "group  sctp.gap_blocks  count  @gaps", "  " + F(s, "gap_start", 16), "  " + F(s, "gap_end", 16),
                       "end", "group  sctp.duplicate_tsns  count  @dups", "  " + F(s, "duplicate_tsn", 32), "end"]),
        ("4,5", "HEARTBEAT, HEARTBEAT ACK", tlv_list("parameters", "param_type", [])),
        ("6,9", "ABORT, ERROR", tlv_list("causes", "cause_code", CAUSES)),
        ("7", "SHUTDOWN", [F(s, "cum_tsn_ack", 32)]),
        ("10", "COOKIE ECHO", octets(s, "cookie")),
        ("8,11,14", "SHUTDOWN ACK, COOKIE ACK, SHUTDOWN COMPLETE", []),
    ]
    for codes, name, body in chunks:
        L.append("      case  %-10s              # %s" % (codes, name))
        L += ind(4, body)
    L.append("      else")
    L += ind(4, octets(s, "value"))
    L += ["    end", "  end", "  align  32", "end"]
    return "\n".join(L) + "\n"


SCTP_KEYS = [
    ("list", "chunks", "the chunks of the packet, in order"),
    ("key", "chunk_type", "chunk type: 0 DATA, 1 INIT, 2 INIT ACK, 3 SACK, 4 HEARTBEAT, 5 HEARTBEAT ACK, 6 ABORT, 7 SHUTDOWN, 8 SHUTDOWN ACK, 9 ERROR, 10 COOKIE ECHO, 11 COOKIE ACK, 14 SHUTDOWN COMPLETE"),
    ("key", "chunk_flags", "chunk flags as one octet: for DATA the bits I, U, B, E (the low four); for ABORT and SHUTDOWN COMPLETE the T bit (the lowest)"),
    ("key", "tsn", "transmission sequence number (DATA; the No User Data cause)"),
    ("key", "stream_id", "stream identifier (DATA; the Invalid Stream Identifier cause)"),
    ("key", "stream_seq", "DATA: stream sequence number"),
    ("key", "ppid", "DATA: payload protocol identifier"),
    ("list", "user_data", "DATA: the user data, as octets"),
    ("key", "initiate_tag", "INIT, INIT ACK: the tag the peer is to put in the packets it sends"),
    ("key", "a_rwnd", "advertised receiver window credit, octets"),
    ("key", "outbound_streams", "INIT, INIT ACK: outbound streams"),
    ("key", "inbound_streams", "INIT, INIT ACK: the most inbound streams"),
    ("key", "initial_tsn", "INIT, INIT ACK: the first TSN the sender will use"),
    ("list", "parameters", "the parameters of an INIT, INIT ACK, HEARTBEAT or HEARTBEAT ACK, in order"),
    ("key", "param_type", "parameter type: 1 heartbeat info, 5 IPv4 address, 6 IPv6 address, 7 state cookie, 8 unrecognized parameter, 9 cookie preservative, 11 host name, 12 supported address types"),
    ("key", "ipv4_address", "IPv4 address parameter, as an unsigned 32-bit integer"),
    ("key", "ipv6_address", "IPv6 address parameter, 32 hexadecimal digits"),
    ("key", "cookie_increment", "cookie preservative: suggested lifespan increment, milliseconds"),
    ("list", "address_types", "supported address types parameter: the types"),
    ("key", "address_type", "one supported address type: 5 IPv4, 6 IPv6"),
    ("key", "cum_tsn_ack", "SACK, SHUTDOWN: cumulative TSN acknowledgement"),
    ("list", "gap_blocks", "SACK: gap acknowledgement blocks, in order"),
    ("key", "gap_start", "SACK: start of a gap block, as an offset from the cumulative TSN"),
    ("key", "gap_end", "SACK: end of a gap block, as an offset from the cumulative TSN"),
    ("list", "duplicate_tsns", "SACK: the duplicate TSNs reported"),
    ("key", "duplicate_tsn", "SACK: one duplicate TSN"),
    ("list", "causes", "the error causes of an ABORT or ERROR, in order"),
    ("key", "cause_code", "error cause code (section 3.3.10: 1 invalid stream identifier to 13 protocol violation)"),
    ("key", "staleness", "stale cookie cause: measure of staleness, microseconds"),
    ("list", "cookie", "COOKIE ECHO: the cookie, as octets"),
    ("list", "value", "the value of a chunk, parameter or cause the pack does not lay out, as octets"),
    ("key", "octet", "one octet"),
]


def module(name, header, src, keys, typed):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            t = typed.get(k[1], "int")
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], t, k[2]))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/diameter/pack.def", diameter_pack())
    out.write("packs/sctp-packet/pack.def", sctp_pack())
    out.write("model/diameter.def", module(
        "diameter", ["# The diameter module: the fields of a Diameter base protocol message and its AVPs (RFC 6733).",
                     "# Written by tools/gen/telecom-pack.py; do not edit by hand."],
        'source        "IETF RFC 6733, Diameter Base Protocol; restated by goat-transformers"', DIAMETER_KEYS,
        {"address_ipv6": "string"}))
    out.write("model/sctp.def", module(
        "sctp", ["# The sctp module: the chunks of an SCTP packet, their parameters and error causes (RFC 9260).",
                 "# The common header is in the inet module. Written by tools/gen/telecom-pack.py; do not edit by hand."],
        'source        "IETF RFC 9260, Stream Control Transmission Protocol; restated by goat-transformers"', SCTP_KEYS,
        {"ipv6_address": "string"}))
    return {"telecom": 4}


def main(argv=None):
    return genio.vector_main("telecom-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
