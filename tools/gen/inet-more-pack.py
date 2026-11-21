#!/usr/bin/env python3
"""Write the Internet control-plane packs and their modules: the whole DNS message (RFC 1035 with
the RR types of RFC 3596, 2782, 6891 and 8659), the DHCPv6 message with its options (RFC 9915), and
the ICMPv6 Neighbor Discovery messages with their options (RFC 4861, RFC 8106).

A DNS name is a run of labels ending at a zero length or at a compression pointer. The run cannot be a
list (it ends on a value inside an item), so each name is nested `switch` blocks, one per label, up to
MAX_LABELS; each label's characters are a field whose size a `switch` on the label length chooses. A
compression pointer is read as its 14-bit offset and not followed. ND options count their length in
8-octet units, so their bodies are chosen by `switch` blocks on that length.
The vectors are not written here: tools/gen/inet-more-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/inet-more-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "dns": ('source        "IETF RFC 1035 sections 3.1, 3.2, 3.3, 3.4, 4.1; RFC 3596 section 2.2 (AAAA); RFC 2782 (SRV); RFC 6891 '
            'section 6 (OPT); RFC 8659 section 4.1 (CAA); https://www.rfc-editor.org/; layouts restated"'),
    "dhcp": ('source        "IETF RFC 9915, Dynamic Host Configuration Protocol for IPv6 (DHCPv6), sections 8, 9, 11 and 21 (it obsoletes '
             'RFC 8415), https://www.rfc-editor.org/rfc/rfc9915.txt; layouts restated"'),
    "nd": ('source        "IETF RFC 4861, Neighbor Discovery for IP version 6, sections 4.1 to 4.6; RFC 8106 section 5 (RDNSS, DNSSL); '
           'https://www.rfc-editor.org/; layouts restated"'),
}
MAX_LABELS = 10


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


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


def text(L):
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- DNS

M = "dnsmsg"


def name(prefix, d=1):
    """The labels of a name from depth d: a 2-bit tag (0 a label, 3 a pointer), then the label."""
    tag, ln = "%s_t%d" % (prefix, d), "%s_len%d" % (prefix, d)
    if d > MAX_LABELS:
        return [F(M, tag, 2)] + sw("%s.%s" % (M, tag), [("0", [F(M, ln, 6)] + sw("%s.%s" % (M, ln), [("0", [])])),
                                                        ("3", [F(M, prefix + "_pointer", 14)])])
    labels = [("0", [])] + [(str(n), [F(M, "%s_label%d" % (prefix, d), 8 * n, "chars:ascii8")]) for n in range(1, 64)]
    rest = sw("%s.%s" % (M, ln), [("0", [])], name(prefix, d + 1))
    return [F(M, tag, 2)] + sw("%s.%s" % (M, tag), [("0", [F(M, ln, 6)] + sw("%s.%s" % (M, ln), labels) + rest),
                                                    ("3", [F(M, prefix + "_pointer", 14)])])


def name_keys(prefix, what):
    keys = []
    for d in range(1, MAX_LABELS + 2):
        keys.append(("key", "%s_t%d" % (prefix, d), "%s, label %d: tag, 0 a label, 3 a compression pointer" % (what, d)))
        keys.append(("key", "%s_len%d" % (prefix, d), "%s, label %d: length in octets (0 ends the name)" % (what, d)))
        if d <= MAX_LABELS:
            keys.append(("key", "%s_label%d" % (prefix, d), "%s, label %d: its characters" % (what, d)))
    keys.append(("key", prefix + "_pointer", "%s: the compression pointer, the offset in the message of the rest of the name (not followed)" % what))
    return keys


def dns_pack():
    rdata = (sw("dnsmsg.type", [
        ("1", [F(M, "a", 32)]),
        ("28", [F(M, "aaaa", 128, "hex")]),
        ("15", [F(M, "preference", 16)]),
        ("6", name("mname") + name("rname") + [F(M, "serial", 32), F(M, "refresh", 32), F(M, "retry", 32), F(M, "expire", 32),
                                               F(M, "minimum", 32)]),
        ("33", [F(M, "priority", 16), F(M, "weight", 16), F(M, "port", 16)])], []) +
        sw("dnsmsg.type", [("2,5,12,15,33", name("target"))], []) +
        sw("dnsmsg.type", [
            ("1,2,5,6,12,15,28,33", []),
            ("16", ["group  dnsmsg.txt  rest", "  count  txtlen  8", "  group  dnsmsg.txt_chars  count  @txtlen",
                    "    " + F(M, "octet", 8), "  end", "end"]),
            ("257", [F(M, "caa_flags", 8), "count  taglen  8", "group  dnsmsg.caa_tag  count  @taglen", "  " + F(M, "octet", 8), "end"] +
             octets(M, "caa_value"))],
           octets(M, "rdata")))
    opt = ([F(M, "udp_payload_size", 16), F(M, "extended_rcode", 8), F(M, "edns_version", 8), F(M, "dnssec_ok", 1), F(M, "edns_z", 15),
            "length  16  bytes", "  group  dnsmsg.edns_options  rest", "    " + F(M, "option_code", 16), "    length  16  bytes"] +
           ind(3, octets(M, "option_data")) + ["    end", "  end", "end"])
    rr = name("owner") + [F(M, "type", 16)] + sw("dnsmsg.type", [("41", opt)],
                                                 [F(M, "class", 16), F(M, "ttl", 32), "length  16  bytes"] + ind(1, rdata) + ["end"])
    L = head("dns-message", ["DNS message (RFC 1035 section 4.1): the header on the inet keys of dns-header, the question section and",
                             "the answer, authority and additional sections with their resource records. Names are label runs; a",
                             "compression pointer is kept as its offset. Written by tools/gen/inet-more-pack.py; do not edit by hand."],
             "dns", ["inet", M])
    L += ["field  inet.dns_id  16  uint", "field  inet.dns_qr  1  uint", "field  inet.dns_opcode  4  uint", "field  inet.dns_aa  1  uint",
          "field  inet.dns_tc  1  uint", "field  inet.dns_rd  1  uint", "field  inet.dns_ra  1  uint", "field  inet.dns_z  3  uint",
          "field  inet.dns_rcode  4  uint", "count  qdcount  16", "count  ancount  16", "count  nscount  16", "count  arcount  16",
          "group  dnsmsg.questions  count  @qdcount"]
    L += ind(1, name("qname") + [F(M, "qtype", 16), F(M, "qclass", 16)]) + ["end"]
    for sec, cnt in (("answers", "ancount"), ("authority", "nscount"), ("additional", "arcount")):
        L += ["group  dnsmsg.%s  count  @%s" % (sec, cnt)] + ind(1, rr) + ["end"]
    return text(L)


DNS_KEYS = ([("list", "questions", "the question section (its count is written from the list)"),
             ("key", "qtype", "question type (1 A, 28 AAAA, 15 MX, 255 ANY ...)"), ("key", "qclass", "question class (1 IN; mDNS sets the top bit for a unicast reply)")] +
            name_keys("qname", "question name") +
            [("list", "answers", "the answer section"), ("list", "authority", "the authority section"), ("list", "additional", "the additional section")] +
            name_keys("owner", "record owner name") +
            [("key", "type", "record type (1 A, 2 NS, 5 CNAME, 6 SOA, 12 PTR, 15 MX, 16 TXT, 28 AAAA, 33 SRV, 41 OPT, 257 CAA ...)"),
             ("key", "class", "record class (1 IN; mDNS uses the top bit as cache flush)"), ("key", "ttl", "time to live, seconds"),
             ("key", "a", "A: the IPv4 address, the 32-bit integer"), ("key", "aaaa", "AAAA: the IPv6 address, as hexadecimal digits"),
             ("key", "preference", "MX: preference")] +
            name_keys("target", "NS, CNAME, PTR, MX or SRV target name") +
            [("list", "txt", "TXT: the character strings"), ("list", "txt_chars", "TXT: one character string, as octets (its length is written from the list)"),
             ("key", "serial", "SOA: serial"), ("key", "refresh", "SOA: refresh, seconds"), ("key", "retry", "SOA: retry, seconds"),
             ("key", "expire", "SOA: expire, seconds"), ("key", "minimum", "SOA: minimum (negative caching TTL), seconds")] +
            name_keys("mname", "SOA primary server name") + name_keys("rname", "SOA responsible mailbox name") +
            [("key", "priority", "SRV: priority"), ("key", "weight", "SRV: weight"), ("key", "port", "SRV: port"),
             ("key", "caa_flags", "CAA: flags (128 issuer critical)"), ("list", "caa_tag", "CAA: the property tag, as octets (its length is written from the list)"),
             ("list", "caa_value", "CAA: the property value, as octets"), ("list", "rdata", "RDATA of another type, as octets"),
             ("key", "udp_payload_size", "OPT (EDNS): the requester's UDP payload size"), ("key", "extended_rcode", "OPT: the upper 8 bits of the extended response code"),
             ("key", "edns_version", "OPT: EDNS version (0)"), ("key", "dnssec_ok", "OPT: DO bit, DNSSEC answers wanted"),
             ("key", "edns_z", "OPT: the 15 Z bits, 0"), ("list", "edns_options", "OPT: the EDNS options"),
             ("key", "option_code", "EDNS option code (10 COOKIE, 12 PADDING, 8 client subnet, 15 extended error ...)"),
             ("list", "option_data", "EDNS option data, as octets"), ("key", "octet", "one octet")])
DNS_STRINGS = [k[1] for k in DNS_KEYS if "_label" in k[1]] + ["aaaa"]


# ---------------------------------------------------------------- DHCPv6

H = "dhcpv6msg"


def status_body():
    return [F(H, "status_code", 16)] + octets(H, "status_message")


def opt_list(lst, codekey, cases, other_list):
    return (["group  %s.%s  rest" % (H, lst), "  " + F(H, codekey, 16), "  length  16  bytes"] +
            ind(2, sw("%s.%s" % (H, codekey), cases, octets(H, other_list))) + ["  end", "end"])


def dhcp_pack():
    addr_opts = opt_list("addr_options", "addr_option_code", [("13", status_body())], "addr_option_data")
    ia_opts = opt_list("ia_options", "ia_option_code", [
        ("5", [F(H, "ia_address", 128, "hex"), F(H, "preferred_lifetime", 32), F(H, "valid_lifetime", 32)] + addr_opts),
        ("26", [F(H, "preferred_lifetime", 32), F(H, "valid_lifetime", 32), F(H, "prefix_length", 8), F(H, "ia_prefix", 128, "hex")] + addr_opts),
        ("13", status_body())], "ia_option_data")
    duid = [F(H, "duid_type", 16)] + sw("dhcpv6msg.duid_type", [
        ("1", [F(H, "hardware_type", 16), F(H, "duid_time", 32)] + octets(H, "link_layer_address")),
        ("2", [F(H, "enterprise_number", 32)] + octets(H, "duid_identifier")),
        ("3", [F(H, "hardware_type", 16)] + octets(H, "link_layer_address")),
        ("4", [F(H, "duid_uuid", 128, "hex")])], octets(H, "duid_identifier"))
    options = opt_list("options", "option_code", [
        ("1,2", duid),
        ("3", [F(H, "iaid", 32), F(H, "t1", 32), F(H, "t2", 32)] + ia_opts),
        ("4", [F(H, "iaid", 32)] + ia_opts),
        ("25", [F(H, "iaid", 32), F(H, "t1", 32), F(H, "t2", 32)] + ia_opts),
        ("6", ["group  dhcpv6msg.requested_options  rest", "  " + F(H, "requested_option", 16), "end"]),
        ("7", [F(H, "preference", 8)]),
        ("8", [F(H, "elapsed_time", 16)]),
        ("13", status_body()),
        ("14", []),
        ("23", ["group  dhcpv6msg.dns_servers  rest", "  " + F(H, "dns_server", 128, "hex"), "end"]),
        ("32,82,83", [F(H, "seconds_value", 32)])], "option_data")
    L = head("dhcpv6-message", ["DHCPv6 message (RFC 9915): the message type, the transaction ID (or, for relay messages, the hop count",
                                "and link and peer addresses), and the options, those of IAs and addresses nested. Written by",
                                "tools/gen/inet-more-pack.py; do not edit by hand."], "dhcp", [H])
    L += [F(H, "msg_type", 8)] + sw("dhcpv6msg.msg_type", [
        ("12,13", [F(H, "hop_count", 8), F(H, "link_address", 128, "hex"), F(H, "peer_address", 128, "hex")])],
        [F(H, "transaction_id", 24)])
    L += options
    return text(L)


DHCP_KEYS = [
    ("key", "msg_type", "message type: 1 SOLICIT, 2 ADVERTISE, 3 REQUEST, 4 CONFIRM, 5 RENEW, 6 REBIND, 7 REPLY, 8 RELEASE, 9 DECLINE, 10 RECONFIGURE, 11 INFORMATION-REQUEST, 12 RELAY-FORW, 13 RELAY-REPL"),
    ("key", "transaction_id", "transaction ID, 24 bits"), ("key", "hop_count", "relay: hop count"),
    ("key", "link_address", "relay: link address, as hexadecimal digits"), ("key", "peer_address", "relay: peer address, as hexadecimal digits"),
    ("list", "options", "the options, in order"),
    ("key", "option_code", "option code (1 client ID, 2 server ID, 3 IA_NA, 4 IA_TA, 6 ORO, 7 preference, 8 elapsed time, 13 status, 14 rapid commit, 23 DNS servers, 25 IA_PD ...)"),
    ("key", "duid_type", "DUID type: 1 link-layer plus time, 2 enterprise number, 3 link-layer, 4 UUID"),
    ("key", "hardware_type", "DUID: hardware type (1 Ethernet)"), ("key", "duid_time", "DUID-LLT: time, seconds since 2000-01-01 UTC, modulo 2^32"),
    ("list", "link_layer_address", "DUID: the link-layer address, as octets"), ("key", "enterprise_number", "DUID-EN: the IANA enterprise number"),
    ("list", "duid_identifier", "DUID-EN identifier, or a DUID of another type, as octets"), ("key", "duid_uuid", "DUID-UUID: the UUID, as hexadecimal digits"),
    ("key", "iaid", "IA: identity association ID"), ("key", "t1", "IA: T1, seconds"), ("key", "t2", "IA: T2, seconds"),
    ("list", "ia_options", "IA: its options"), ("key", "ia_option_code", "IA option code (5 IA address, 26 IA prefix, 13 status)"),
    ("key", "ia_address", "IA address: the IPv6 address, as hexadecimal digits"), ("key", "ia_prefix", "IA prefix: the prefix, as hexadecimal digits"),
    ("key", "prefix_length", "IA prefix: prefix length"), ("key", "preferred_lifetime", "preferred lifetime, seconds"),
    ("key", "valid_lifetime", "valid lifetime, seconds"), ("list", "addr_options", "IA address or prefix: its options"),
    ("key", "addr_option_code", "IA address or prefix option code (13 status)"), ("list", "addr_option_data", "an IA address or prefix option of another code, as octets"),
    ("list", "ia_option_data", "an IA option of another code, as octets"),
    ("key", "status_code", "status code (0 success, 1 unspecified failure, 2 no addresses available, 3 no binding, 4 not on link, 5 use multicast, 6 no prefix available)"),
    ("list", "status_message", "status message, UTF-8 octets"), ("list", "requested_options", "ORO: the requested option codes"),
    ("key", "requested_option", "one requested option code"), ("key", "preference", "server preference, 0-255"),
    ("key", "elapsed_time", "elapsed time, hundredths of a second"), ("list", "dns_servers", "DNS recursive name servers"),
    ("key", "dns_server", "one DNS server address, as hexadecimal digits"),
    ("key", "seconds_value", "information refresh time (32), SOL_MAX_RT (82) or INF_MAX_RT (83), seconds"),
    ("list", "option_data", "an option of another code, as octets"), ("key", "octet", "one octet"),
]
DHCP_STRINGS = ["link_address", "peer_address", "duid_uuid", "ia_address", "ia_prefix", "dns_server"]


# ---------------------------------------------------------------- ICMPv6 ND

N = "icmpnd"
MAX_OPT_UNITS = 32


def units_hex(key, first_bytes):
    """Option bodies by the 8-octet length: the remaining octets as hex."""
    cases = []
    for n in range(1, MAX_OPT_UNITS + 1):
        size = n * 8 - first_bytes
        cases.append((str(n), [F(N, key, size * 8, "hex")] if size > 0 else []))
    return cases


def nd_option():
    lla = sw("icmpnd.option_length", [("1", [F(N, "link_layer_address", 48, "hex")])] +
             [(str(n), [F(N, "link_layer_address", (n * 8 - 2) * 8, "hex")]) for n in range(2, 5)])
    prefix = sw("icmpnd.option_length", [("4", [F(N, "prefix_length", 8), F(N, "on_link", 1), F(N, "autonomous", 1),
                                                F(N, "router_address", 1), F(N, "prefix_reserved1", 5), F(N, "valid_lifetime", 32),
                                                F(N, "preferred_lifetime", 32), F(N, "prefix_reserved2", 32), F(N, "prefix", 128, "hex")])])
    redirected = [F(N, "redirected_reserved", 48)] + sw("icmpnd.option_length", units_hex("redirected_packet", 8))
    mtu = sw("icmpnd.option_length", [("1", [F(N, "mtu_reserved", 16), F(N, "mtu", 32)])])
    rdnss = [F(N, "rdnss_reserved", 16), F(N, "rdnss_lifetime", 32)] + sw("icmpnd.option_length", units_hex("rdnss_addresses", 8))
    dnssl = [F(N, "dnssl_reserved", 16), F(N, "dnssl_lifetime", 32)] + sw("icmpnd.option_length", units_hex("dnssl_names", 8))
    other = sw("icmpnd.option_length", units_hex("option_data", 2))
    return ([F(N, "option_type", 8), F(N, "option_length", 8)] +
            sw("icmpnd.option_type", [("1,2", lla), ("3", prefix), ("4", redirected), ("5", mtu), ("25", rdnss), ("31", dnssl)], other))


def nd_pack():
    L = head("icmpv6-nd", ["ICMPv6 Neighbor Discovery messages (RFC 4861): Router Solicitation and Advertisement, Neighbor",
                           "Solicitation and Advertisement, Redirect, with their options. Type, code, checksum and the RS and RA",
                           "fields are the inet keys of icmpv6-header. Written by tools/gen/inet-more-pack.py; do not edit by hand."],
             "nd", ["inet", N])
    L += ["field  inet.icmpv6_type  8  uint", "field  inet.icmpv6_code  8  uint", "field  inet.icmpv6_checksum  16  uint"]
    L += sw("inet.icmpv6_type", [
        ("133", ["field  inet.icmpv6_reserved  32  uint"]),
        ("134", ["field  inet.icmpv6_ra_cur_hop_limit  8  uint", "field  inet.icmpv6_ra_managed  1  uint",
                 "field  inet.icmpv6_ra_other  1  uint", "field  inet.icmpv6_ra_reserved  6  uint",
                 "field  inet.icmpv6_ra_router_lifetime  16  uint", "field  inet.icmpv6_ra_reachable_time  32  uint",
                 "field  inet.icmpv6_ra_retrans_timer  32  uint"]),
        ("135", [F(N, "ns_reserved", 32), F(N, "target", 128, "hex")]),
        ("136", [F(N, "router", 1), F(N, "solicited", 1), F(N, "override", 1), F(N, "na_reserved", 29), F(N, "target", 128, "hex")]),
        ("137", [F(N, "redirect_reserved", 32), F(N, "target", 128, "hex"), F(N, "destination", 128, "hex")])])
    L += ["group  icmpnd.options  rest"] + ind(1, nd_option()) + ["end"]
    return text(L)


ND_KEYS = [
    ("key", "ns_reserved", "NS: the 32 reserved bits"), ("key", "target", "NS, NA, Redirect: the target address, as hexadecimal digits"),
    ("key", "router", "NA R flag: the sender is a router"), ("key", "solicited", "NA S flag: sent in response to a solicitation"),
    ("key", "override", "NA O flag: override an existing cache entry"), ("key", "na_reserved", "NA: the 29 reserved bits"),
    ("key", "redirect_reserved", "Redirect: the 32 reserved bits"), ("key", "destination", "Redirect: the destination address, as hexadecimal digits"),
    ("list", "options", "the options, in order"),
    ("key", "option_type", "option type: 1 source link-layer address, 2 target link-layer address, 3 prefix information, 4 redirected header, 5 MTU, 25 RDNSS, 31 DNSSL"),
    ("key", "option_length", "option length, in units of 8 octets, the type and length included"),
    ("key", "link_layer_address", "link-layer address option: the address (and any padding), as hexadecimal digits"),
    ("key", "prefix_length", "prefix information: prefix length"), ("key", "on_link", "prefix information L flag: on-link"),
    ("key", "autonomous", "prefix information A flag: usable for autonomous address configuration"),
    ("key", "router_address", "prefix information R flag (RFC 6275): the prefix field holds the router's address"),
    ("key", "prefix_reserved1", "prefix information: the 5 reserved bits"), ("key", "valid_lifetime", "prefix information: valid lifetime, seconds (0xFFFFFFFF infinity)"),
    ("key", "preferred_lifetime", "prefix information: preferred lifetime, seconds"), ("key", "prefix_reserved2", "prefix information: the 32 reserved bits"),
    ("key", "prefix", "prefix information: the prefix, as hexadecimal digits"),
    ("key", "redirected_reserved", "redirected header: the 48 reserved bits"),
    ("key", "redirected_packet", "redirected header: the start of the redirected packet, as hexadecimal digits"),
    ("key", "mtu_reserved", "MTU option: the 16 reserved bits"), ("key", "mtu", "MTU option: the link MTU"),
    ("key", "rdnss_reserved", "RDNSS: the 16 reserved bits"), ("key", "rdnss_lifetime", "RDNSS: lifetime, seconds"),
    ("key", "rdnss_addresses", "RDNSS: the DNS server addresses, 16 octets each, as hexadecimal digits"),
    ("key", "dnssl_reserved", "DNSSL: the 16 reserved bits"), ("key", "dnssl_lifetime", "DNSSL: lifetime, seconds"),
    ("key", "dnssl_names", "DNSSL: the search domain names (DNS name encoding, zero-padded), as hexadecimal digits"),
    ("key", "option_data", "an option of another type: its body, as hexadecimal digits"),
]
ND_STRINGS = ["target", "destination", "link_layer_address", "prefix", "redirected_packet", "rdnss_addresses", "dnssl_names", "option_data"]


def module(name_, header, src, keys, strings=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name_, "version       0.1.0", "distribution  public", SRC[src]]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in strings else "int", k[2]))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/dns-message/pack.def", dns_pack())
    out.write("packs/dhcpv6-message/pack.def", dhcp_pack())
    out.write("packs/icmpv6-nd/pack.def", nd_pack())
    out.write("model/dnsmsg.def", module("dnsmsg", ["# The dnsmsg module: the sections and records of a DNS message. Written by tools/gen/inet-more-pack.py."], "dns", DNS_KEYS, DNS_STRINGS))
    out.write("model/dhcpv6msg.def", module("dhcpv6msg", ["# The dhcpv6msg module: DHCPv6 messages and options (RFC 9915). Written by tools/gen/inet-more-pack.py."], "dhcp", DHCP_KEYS, DHCP_STRINGS))
    out.write("model/icmpnd.def", module("icmpnd", ["# The icmpnd module: ICMPv6 Neighbor Discovery fields and options. Written by tools/gen/inet-more-pack.py."], "nd", ND_KEYS, ND_STRINGS))
    return {"inet-more": 6}


def main(argv=None):
    return genio.vector_main("inet-more-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
