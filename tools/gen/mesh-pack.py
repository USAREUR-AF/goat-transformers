#!/usr/bin/env python3
"""Write the low-power mesh packs and their modules: the 6LoWPAN frame (RFC 4944 dispatch, mesh,
broadcast and fragmentation headers; RFC 6282 IPHC and NHC; the RFC 7400 GHC dispatches) and the
RPL control message (RFC 6550) in ICMPv6.

6LoWPAN headers are told apart by bit patterns of different widths at the start of an octet, and
they stack in a fixed order (mesh, broadcast, fragment, then the IPv6 header). The pack reads the
pattern bit group by bit group with nested `switch` blocks, and writes one stage per position in
the stack; each stage has its own selector keys, so a frame sets each key at most once. Every
branch reads to the end of its octet before any octet list, so an encode writes the same bits back.
The vectors are not written here: tools/gen/mesh-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/mesh-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SHA = {
    "4944": "2a1d639aa85e37d860f4c1e535865cdcc3dfc9f48518a2fcc922b3b18ce78c63",
    "6282": "a3b46845b7223dff27bb78c1c094caa1a6ffdc1f87ec17b8ff905c4aedc4a7f2",
    "7400": "d7e583fb7f5aa839e4c8fc32343b09fec43df95e4659868c52232bc3b63b9be9",
    "6550": "2c09f5945d6dbba4b69203a826121150c0cff1748d10f22c5a75060e53f5cb82",
}
SRC = {
    "4944": 'source        "IETF RFC 4944, Transmission of IPv6 Packets over IEEE 802.15.4 Networks, September 2007, sections 5.1 to 5.3 and 11.1, https://www.rfc-editor.org/rfc/rfc4944.txt (sha256 %s); layout restated"' % SHA["4944"],
    "6282": 'source        "IETF RFC 6282, Compression Format for IPv6 Datagrams over IEEE 802.15.4-Based Networks, September 2011, sections 3 and 4, https://www.rfc-editor.org/rfc/rfc6282.txt (sha256 %s); layout restated"' % SHA["6282"],
    "7400": 'source        "IETF RFC 7400, 6LoWPAN-GHC: Generic Header Compression for IPv6 over Low-Power Wireless Personal Area Networks, November 2014, section 3, https://www.rfc-editor.org/rfc/rfc7400.txt (sha256 %s); the NHC bytes only; layout restated"' % SHA["7400"],
    "6550": 'source        "IETF RFC 6550, RPL: IPv6 Routing Protocol for Low-Power and Lossy Networks, March 2012, sections 6.1 to 6.7, https://www.rfc-editor.org/rfc/rfc6550.txt (sha256 %s); layout restated"' % SHA["6550"],
}
L6 = "lowpan"
R = "rpl"


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def sw(key, cases, other=None):
    """switch on key: cases is [(values, lines)]; other the else lines (None: no else)."""
    L = ["switch  %s" % key]
    for vals, lines in cases:
        L.append("  case  %s" % vals)
        L += ind(2, lines)
    if other is not None:
        L.append("  else")
        L += ind(2, other)
    L.append("end")
    return L


def head(name, comment, sources, uses):
    L = ["# %s" % c for c in comment] + ["format        %s" % name, "version       0.1.0", "distribution  public"]
    L += [SRC[s] for s in sources]
    L += ["uses          %s" % u for u in uses]
    return L + ["wire          bits", "layout        sequential", "bit_order     msb", ""]


def text(L):
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 6LoWPAN

def l(k, b, tr="uint"):
    return F(L6, k, b, tr)


def addr(key, size):
    return [l(key, size, "hex")] if size else []


def udp_ports(prefix):
    return sw("%s.%s_p" % (L6, prefix), [
        ("0", [l("udp_src_port", 16), l("udp_dst_port", 16)]),
        ("1", [l("udp_src_port", 16), l("udp_dst_port_low8", 8)]),
        ("2", [l("udp_src_port_low8", 8), l("udp_dst_port", 16)]),
        ("3", [l("udp_src_port_low4", 4), l("udp_dst_port_low4", 4)])])


def udp(prefix, payload_list):
    return ([l(prefix + "_c", 1), l(prefix + "_p", 2)] + udp_ports(prefix) +
            sw("%s.%s_c" % (L6, prefix), [("0", [l("udp_checksum", 16)])], []) + octets(L6, payload_list))


def nhc():
    """The next header after an IPHC header whose NH bit is 1 (RFC 6282 section 4, RFC 7400 section 3)."""
    ext = ([l("ext_eid", 3), l("ext_nh", 1)] +
           sw("%s.ext_eid" % L6, [("7", octets(L6, "inner_packet"))],
              sw("%s.ext_nh" % L6, [("0", [l("ext_next_header", 8)])], []) +
              ["length  8  bytes"] + ind(1, octets(L6, "ext_header")) + ["end"] + octets(L6, "after_ext")))
    ghc = sw("%s.nhc_d" % L6, [
        ("0", udp("ghc_udp", "ghc_payload")),
        ("1", [l("nhc_e", 3)] + sw("%s.nhc_e" % L6, [("7", octets(L6, "ghc_payload"))],
                                     octets(L6, "nhc_octets")))])
    return ([l("nhc_a", 4)] + sw("%s.nhc_a" % L6, [
        ("15", [l("nhc_b", 1)] + sw("%s.nhc_b" % L6, [("0", udp("udp", "udp_payload"))],
                                     [l("nhc_low", 3)] + octets(L6, "nhc_octets"))),
        ("14", ext),
        ("13", [l("nhc_d", 1)] + ghc),
        ("11", [l("nhc_f", 1)] + sw("%s.nhc_f" % L6, [("0", [l("ghc_ext_eid", 2), l("ghc_ext_nh", 1)] + octets(L6, "ghc_payload"))],
                                     [l("nhc_low", 3)] + octets(L6, "nhc_octets")))],
        [l("nhc_rest", 4)] + octets(L6, "nhc_octets")))


def iphc():
    """The IPHC header after its 011 pattern (RFC 6282 section 3)."""
    stateless = [("0", addr("src_inline", 128)), ("1", addr("src_inline", 64)), ("2", addr("src_inline", 16)), ("3", [])]
    stateful = [("0", []), ("1", addr("src_inline", 64)), ("2", addr("src_inline", 16)), ("3", [])]
    dst_ul = [("0", addr("dst_inline", 128)), ("1", addr("dst_inline", 64)), ("2", addr("dst_inline", 16)), ("3", [])]
    dst_uc = [("0", []), ("1", addr("dst_inline", 64)), ("2", addr("dst_inline", 16)), ("3", [])]
    dst_ml = [("0", addr("dst_inline", 128)), ("1", addr("dst_inline", 48)), ("2", addr("dst_inline", 32)), ("3", addr("dst_inline", 8))]
    dst_mc = [("0", addr("dst_inline", 48)), ("1,2,3", [])]
    L = [l("tf", 2), l("nh", 1), l("hlim", 2), l("cid", 1), l("sac", 1), l("sam", 2), l("m", 1), l("dac", 1), l("dam", 2)]
    L += sw("lowpan.cid", [("1", [l("sci", 4), l("dci", 4)])], [])
    L += sw("lowpan.tf", [("0", [l("ecn", 2), l("dscp", 6), l("tf_pad", 4), l("flow_label", 20)]),
                          ("1", [l("ecn", 2), l("tf_pad", 2), l("flow_label", 20)]),
                          ("2", [l("ecn", 2), l("dscp", 6)]), ("3", [])])
    L += sw("lowpan.nh", [("0", [l("next_header", 8)])], [])
    L += sw("lowpan.hlim", [("0", [l("hop_limit", 8)])], [])
    L += sw("lowpan.sac", [("0", sw("lowpan.sam", stateless)), ("1", sw("lowpan.sam", stateful))])
    L += sw("lowpan.m", [("0", sw("lowpan.dac", [("0", sw("lowpan.dam", dst_ul)), ("1", sw("lowpan.dam", dst_uc))])),
                         ("1", sw("lowpan.dac", [("0", sw("lowpan.dam", dst_ml)), ("1", sw("lowpan.dam", dst_mc))]))])
    L += sw("lowpan.nh", [("0", octets(L6, "ipv6_payload")), ("1", nhc())])
    return L


def stage(n, allow):
    """One position of the header stack. allow: the headers this position may hold."""
    a, b, c, d = ("s%d_a" % n, "s%d_b" % n, "s%d_c" % n, "s%d_d" % n)
    nxt = {"mesh": 1, "bc0": 2, "frag1": 3}
    # 01 ...: IPHC (011), or a 6-bit dispatch (IPv6, BC0, HC1, ESC, reserved)
    lowcases = [("1", octets(L6, "ipv6_packet"))]
    if "bc0" in allow:
        lowcases.append(("16", [l("bc0_sequence", 8)] + stage(nxt["bc0"], ["frag1", "fragn"])))
    c01 = [l(b, 1)] + sw("lowpan.%s" % b, [("1", iphc()),
                                            ("0", [l(c, 5)] + sw("lowpan.%s" % c, lowcases, octets(L6, "frame_octets")))])
    cases = [("0", [l("nalp_bits", 6)] + octets(L6, "frame_octets")), ("1", c01)]
    if "mesh" in allow:
        mesh = ([l("mesh_v", 1), l("mesh_f", 1), l("hops_left", 4)] +
                sw("lowpan.hops_left", [("15", [l("deep_hops_left", 8)])], []) +
                sw("lowpan.mesh_v", [("0", [l("originator", 64, "hex")]), ("1", [l("originator", 16, "hex")])]) +
                sw("lowpan.mesh_f", [("0", [l("final", 64, "hex")]), ("1", [l("final", 16, "hex")])]) +
                stage(nxt["mesh"], ["bc0", "frag1", "fragn"]))
        cases.append(("2", mesh))
    else:
        cases.append(("2", [l("dispatch_bits", 6)] + octets(L6, "frame_octets")))
    fr = []
    if "frag1" in allow:
        fr.append(("0", [l("datagram_size", 11), l("datagram_tag", 16)] + stage(nxt["frag1"], [])))
    if "fragn" in allow:
        fr.append(("4", [l("datagram_size", 11), l("datagram_tag", 16), l("datagram_offset", 8)] +
                   octets(L6, "fragment_octets")))
    c11 = ([l(d, 3)] + sw("lowpan.%s" % d, fr, [l("dispatch_low3", 3)] + octets(L6, "frame_octets")) if fr
           else [l("dispatch_bits", 6)] + octets(L6, "frame_octets"))
    cases.append(("3", c11))
    return [l(a, 2)] + sw("lowpan.%s" % a, cases)


def lowpan_pack():
    L = head("lowpan-frame", ["6LoWPAN frame (RFC 4944, RFC 6282, RFC 7400): the dispatch, the mesh, broadcast and fragmentation",
                              "headers, the IPHC header and the NHC header after it. The message is the MAC payload of an IEEE",
                              "802.15.4 frame. Public. Written by tools/gen/mesh-pack.py; do not edit by hand."],
             ["4944", "6282", "7400"], [L6])
    return text(L + stage(0, ["mesh", "bc0", "frag1", "fragn"]))


LOWPAN_KEYS = [
    ("key", "s0_a", "the first 2 bits of the first header: 0 not a LoWPAN frame, 1 IPv6 or IPHC or a dispatch, 2 mesh, 3 fragment or other"),
    ("key", "s0_b", "after 01: 1 for IPHC (011), 0 for a 6-bit dispatch"),
    ("key", "s0_c", "after 010: the rest of the dispatch (1 IPv6, 2 HC1, 16 BC0, 31 ESC)"),
    ("key", "s0_d", "after 11: the next 3 bits (0 FRAG1, 4 FRAGN)"),
    ("key", "s1_a", "as s0_a, for the header after a mesh header"),
    ("key", "s1_b", "as s0_b, after a mesh header"),
    ("key", "s1_c", "as s0_c, after a mesh header"),
    ("key", "s1_d", "as s0_d, after a mesh header"),
    ("key", "s2_a", "as s0_a, for the header after a broadcast header"),
    ("key", "s2_b", "as s0_b, after a broadcast header"),
    ("key", "s2_c", "as s0_c, after a broadcast header"),
    ("key", "s2_d", "as s0_d, after a broadcast header"),
    ("key", "s3_a", "as s0_a, for the header after a first fragment header"),
    ("key", "s3_b", "as s0_b, after a first fragment header"),
    ("key", "s3_c", "as s0_c, after a first fragment header"),
    ("key", "s3_d", "as s0_d, after a first fragment header"),
    ("key", "nalp_bits", "not a LoWPAN frame: the 6 bits after 00"),
    ("key", "dispatch_bits", "a pattern not allowed at its place: the 6 bits after its first 2"),
    ("key", "dispatch_low3", "a pattern 11 then 3 bits other than a fragment header allowed here: the last 3 bits of the octet"),
    ("list", "frame_octets", "the rest of a frame whose header is not laid out here (LOWPAN_HC1, ESC, page switch, reserved patterns), as octets"),
    ("list", "ipv6_packet", "dispatch 0x41: the uncompressed IPv6 packet, as octets"),
    ("key", "mesh_v", "mesh header V: 0 the originator is a 64-bit address, 1 a 16-bit short address"),
    ("key", "mesh_f", "mesh header F: 0 the final destination is a 64-bit address, 1 a 16-bit short address"),
    ("key", "hops_left", "mesh header: hops left, 0 to 14; 15 means a deep hops left octet follows"),
    ("key", "deep_hops_left", "mesh header: the 8-bit deep hops left"),
    ("key", "originator", "mesh header: the originator's link-layer address, as hexadecimal digits"),
    ("key", "final", "mesh header: the final destination's link-layer address, as hexadecimal digits"),
    ("key", "bc0_sequence", "LOWPAN_BC0: the broadcast sequence number"),
    ("key", "datagram_size", "fragment header: the size of the whole IP packet before fragmentation, octets"),
    ("key", "datagram_tag", "fragment header: the tag shared by the fragments of one packet"),
    ("key", "datagram_offset", "FRAGN: the offset of the fragment in 8-octet units"),
    ("list", "fragment_octets", "FRAGN: the fragment's octets"),
    ("key", "tf", "IPHC TF: 0 ECN, DSCP and flow label inline; 1 ECN and flow label; 2 ECN and DSCP; 3 all elided"),
    ("key", "nh", "IPHC NH: 0 the next header inline, 1 compressed by NHC"),
    ("key", "hlim", "IPHC HLIM: 0 the hop limit inline; 1, 2, 3 the hop limit 1, 64, 255"),
    ("key", "cid", "IPHC CID: 1 a context identifier octet follows"),
    ("key", "sac", "IPHC SAC: 0 stateless, 1 context-based source address compression"),
    ("key", "sam", "IPHC SAM: source address mode (the inline size by SAC)"),
    ("key", "m", "IPHC M: the destination is a multicast address"),
    ("key", "dac", "IPHC DAC: 0 stateless, 1 context-based destination address compression"),
    ("key", "dam", "IPHC DAM: destination address mode (the inline size by M and DAC)"),
    ("key", "sci", "IPHC source context identifier"),
    ("key", "dci", "IPHC destination context identifier"),
    ("key", "ecn", "IPHC inline ECN bits"),
    ("key", "dscp", "IPHC inline DSCP"),
    ("key", "tf_pad", "IPHC: the pad bits of the inline traffic class and flow label, 0"),
    ("key", "flow_label", "IPHC inline flow label"),
    ("key", "next_header", "IPHC inline next header"),
    ("key", "hop_limit", "IPHC inline hop limit"),
    ("key", "src_inline", "IPHC: the source address bits carried inline (128, 64 or 16), as hexadecimal digits"),
    ("key", "dst_inline", "IPHC: the destination address bits carried inline (128, 64, 48, 32, 16 or 8), as hexadecimal digits"),
    ("list", "ipv6_payload", "IPHC with an inline next header: the IPv6 payload, as octets"),
    ("key", "nhc_a", "the first 4 bits of the NHC octet: 15 UDP, 14 extension header, 13 GHC UDP or ICMPv6, 11 GHC extension header"),
    ("key", "nhc_b", "after 1111: 0 for UDP (11110)"),
    ("key", "nhc_d", "after 1101: 0 for GHC UDP (11010), 1 for 11011"),
    ("key", "nhc_e", "after 11011: the last 3 bits (7 for GHC ICMPv6)"),
    ("key", "nhc_f", "after 1011: 0 for GHC extension header (10110)"),
    ("key", "nhc_low", "an NHC pattern not laid out: the last 3 bits of its octet"),
    ("key", "nhc_rest", "an NHC pattern not laid out: the last 4 bits of its octet"),
    ("list", "nhc_octets", "the rest of a packet whose NHC pattern is not laid out, as octets"),
    ("key", "udp_c", "UDP NHC C: 1 the checksum is elided"),
    ("key", "udp_p", "UDP NHC P: 0 both ports inline, 1 the destination's low 8 bits, 2 the source's low 8 bits, 3 the low 4 bits of both"),
    ("key", "ghc_udp_c", "GHC UDP NHC C: 1 the checksum is elided"),
    ("key", "ghc_udp_p", "GHC UDP NHC P, as for UDP"),
    ("key", "udp_src_port", "UDP source port, inline"),
    ("key", "udp_dst_port", "UDP destination port, inline"),
    ("key", "udp_src_port_low8", "UDP source port: the low 8 bits (the high 8 are 0xF0)"),
    ("key", "udp_dst_port_low8", "UDP destination port: the low 8 bits (the high 8 are 0xF0)"),
    ("key", "udp_src_port_low4", "UDP source port: the low 4 bits (the high 12 are 0xF0B)"),
    ("key", "udp_dst_port_low4", "UDP destination port: the low 4 bits (the high 12 are 0xF0B)"),
    ("key", "udp_checksum", "UDP checksum, inline"),
    ("list", "udp_payload", "the UDP payload, as octets"),
    ("list", "ghc_payload", "a payload or header compressed by GHC (RFC 7400 bytecodes), as octets"),
    ("key", "ghc_ext_eid", "GHC extension header NHC: the extension header ID (2 bits)"),
    ("key", "ghc_ext_nh", "GHC extension header NHC: the NH bit"),
    ("key", "ext_eid", "extension header NHC: 0 hop-by-hop, 1 routing, 2 fragment, 3 destination options, 4 mobility, 7 IPv6 header"),
    ("key", "ext_nh", "extension header NHC NH: 0 the next header inline, 1 compressed by NHC"),
    ("key", "ext_next_header", "extension header: the inline next header"),
    ("list", "ext_header", "extension header: its octets after the length (the length counts octets, RFC 6282 section 4.2)"),
    ("list", "after_ext", "what follows the extension header (an NHC header or the payload), as octets"),
    ("list", "inner_packet", "extension header NHC with EID 7: the encapsulated IPHC-compressed IPv6 packet, as octets"),
    ("key", "octet", "one octet"),
]
LOWPAN_STRINGS = ["originator", "final", "src_inline", "dst_inline"]


# ---------------------------------------------------------------- RPL

def r(k, b, tr="uint"):
    return F(R, k, b, tr)


def rpl_options():
    opts = sw("rpl.option_type", [
        ("2", octets(R, "metric_container")),
        ("3", [r("prefix_length", 8), r("route_reserved_a", 3), r("route_preference", 2), r("route_reserved_b", 3),
               r("route_lifetime", 32)] + octets(R, "prefix_octets")),
        ("4", [r("config_flags", 4), r("authentication", 1), r("path_control_size", 3), r("dio_interval_doublings", 8),
               r("dio_interval_min", 8), r("dio_redundancy", 8), r("max_rank_increase", 16), r("min_hop_rank_increase", 16),
               r("objective_code_point", 16), r("config_reserved", 8), r("default_lifetime", 8), r("lifetime_unit", 16)]),
        ("5", [r("target_flags", 8), r("prefix_length", 8)] + octets(R, "prefix_octets")),
        ("6", [r("external", 1), r("transit_flags", 7), r("path_control", 8), r("path_sequence", 8), r("path_lifetime", 8)] +
              octets(R, "parent_address")),
        ("7", [r("solicited_instance", 8), r("solicited_v", 1), r("solicited_i", 1), r("solicited_d", 1),
               r("solicited_flags", 5), r("solicited_dodagid", 128, "hex"), r("solicited_version", 8)]),
        ("8", [r("prefix_length", 8), r("on_link", 1), r("autonomous", 1), r("router_address", 1), r("prefix_reserved1", 5),
               r("valid_lifetime", 32), r("preferred_lifetime", 32), r("prefix_reserved2", 32), r("prefix", 128, "hex")]),
        ("9", [r("descriptor", 32)])],
        octets(R, "option_octets"))
    item = [r("option_type", 8)] + sw("rpl.option_type", [("0", [])], ["length  8  bytes"] + ind(1, opts) + ["end"])
    return ["group  rpl.options  rest"] + ind(1, item) + ["end"]


def rpl_pack():
    dodagid = [r("dodagid", 128, "hex")]
    L = head("rpl-control", ["RPL control message (RFC 6550 section 6): ICMPv6 type 155, the base object by code (DIS, DIO,",
                             "DAO, DAO-ACK, consistency check) and the options. The ICMPv6 type, code and checksum are the inet",
                             "keys of icmpv6-header. Public. Written by tools/gen/mesh-pack.py; do not edit by hand."],
             ["6550"], ["inet", R])
    opts = rpl_options()
    by_code = sw("inet.icmpv6_code", [
        ("0", [r("dis_flags", 8), r("dis_reserved", 8)] + opts),
        ("1", [r("instance_id", 8), r("version", 8), r("rank", 16), r("grounded", 1), r("dio_zero", 1), r("mop", 3),
               r("preference", 3), r("dtsn", 8), r("dio_flags", 8), r("dio_reserved", 8)] + dodagid + opts),
        ("2", [r("instance_id", 8), r("dao_k", 1), r("dao_d", 1), r("dao_flags", 6), r("dao_reserved", 8),
               r("dao_sequence", 8)] + sw("rpl.dao_d", [("1", dodagid)], []) + opts),
        ("3", [r("instance_id", 8), r("dao_d", 1), r("ack_reserved", 7), r("dao_sequence", 8), r("status", 8)] +
              sw("rpl.dao_d", [("1", dodagid)], []) + opts),
        ("138", [r("instance_id", 8), r("cc_response", 1), r("cc_flags", 7), r("cc_nonce", 16)] + dodagid +
                [r("destination_counter", 32)] + opts)],
        octets(R, "secured_octets"))
    L += ["field  inet.icmpv6_type  8  uint", "field  inet.icmpv6_code  8  uint", "field  inet.icmpv6_checksum  16  uint"]
    L += sw("inet.icmpv6_type", [("155", by_code)])
    return text(L)


RPL_KEYS = [
    ("key", "dis_flags", "DIS: the flags octet, 0"),
    ("key", "dis_reserved", "DIS: the reserved octet, 0"),
    ("key", "instance_id", "RPLInstanceID"),
    ("key", "version", "DIO: DODAG version number"),
    ("key", "rank", "DIO: the sender's rank"),
    ("key", "grounded", "DIO G: the DODAG is grounded"),
    ("key", "dio_zero", "DIO: the bit after G, 0"),
    ("key", "mop", "DIO: mode of operation (0 no downward routes, 1 non-storing, 2 storing without multicast, 3 storing with multicast)"),
    ("key", "preference", "DIO: DODAG preference, 0 (least) to 7"),
    ("key", "dtsn", "DIO: destination advertisement trigger sequence number"),
    ("key", "dio_flags", "DIO: the flags octet, 0"),
    ("key", "dio_reserved", "DIO: the reserved octet, 0"),
    ("key", "dodagid", "DODAGID, the IPv6 address of the DODAG root, as hexadecimal digits"),
    ("key", "dao_k", "DAO K: the sender expects a DAO-ACK"),
    ("key", "dao_d", "DAO and DAO-ACK D: the DODAGID is present"),
    ("key", "dao_flags", "DAO: the 6 flag bits after D, 0"),
    ("key", "dao_reserved", "DAO: the reserved octet, 0"),
    ("key", "dao_sequence", "DAO and DAO-ACK: DAO sequence"),
    ("key", "ack_reserved", "DAO-ACK: the 7 reserved bits after D, 0"),
    ("key", "status", "DAO-ACK status: 0 unqualified acceptance, 1-127 acceptance with a condition, 128-255 rejection"),
    ("key", "cc_response", "consistency check R: the message is a response"),
    ("key", "cc_flags", "consistency check: the 7 flag bits after R, 0"),
    ("key", "cc_nonce", "consistency check nonce"),
    ("key", "destination_counter", "consistency check: the destination counter"),
    ("list", "secured_octets", "a code other than 0-3 and 0x8A (the secured forms 0x80-0x83 and others): the message after the checksum, as octets"),
    ("list", "options", "the options, in order"),
    ("key", "option_type", "option type: 0 Pad1, 1 PadN, 2 DAG metric container, 3 route information, 4 DODAG configuration, 5 RPL target, 6 transit information, 7 solicited information, 8 prefix information, 9 target descriptor"),
    ("list", "metric_container", "DAG metric container (RFC 6551): its data, as octets"),
    ("key", "prefix_length", "route information, RPL target, prefix information: the prefix length in bits"),
    ("key", "route_reserved_a", "route information: the 3 reserved bits before the preference, 0"),
    ("key", "route_preference", "route information: route preference"),
    ("key", "route_reserved_b", "route information: the 3 reserved bits after the preference, 0"),
    ("key", "route_lifetime", "route information: route lifetime, seconds (0xFFFFFFFF infinity)"),
    ("list", "prefix_octets", "route information, RPL target: the prefix, as many octets as the option holds"),
    ("key", "config_flags", "DODAG configuration: the 4 flag bits before A, 0"),
    ("key", "authentication", "DODAG configuration A: authentication is enabled"),
    ("key", "path_control_size", "DODAG configuration PCS: the number of bits of path control, less one"),
    ("key", "dio_interval_doublings", "DODAG configuration: DIOIntervalDoublings"),
    ("key", "dio_interval_min", "DODAG configuration: DIOIntervalMin (the interval is 2 to this power, milliseconds)"),
    ("key", "dio_redundancy", "DODAG configuration: DIORedundancyConstant"),
    ("key", "max_rank_increase", "DODAG configuration: MaxRankIncrease"),
    ("key", "min_hop_rank_increase", "DODAG configuration: MinHopRankIncrease"),
    ("key", "objective_code_point", "DODAG configuration: the objective function (OCP)"),
    ("key", "config_reserved", "DODAG configuration: the reserved octet, 0"),
    ("key", "default_lifetime", "DODAG configuration: default route lifetime, in lifetime units"),
    ("key", "lifetime_unit", "DODAG configuration: the lifetime unit, seconds"),
    ("key", "target_flags", "RPL target: the flags octet, 0"),
    ("key", "external", "transit information E: the target is external to the RPL network"),
    ("key", "transit_flags", "transit information: the 7 flag bits after E, 0"),
    ("key", "path_control", "transit information: path control"),
    ("key", "path_sequence", "transit information: path sequence"),
    ("key", "path_lifetime", "transit information: path lifetime, in lifetime units"),
    ("list", "parent_address", "transit information: the parent address (16 octets, or none), as octets"),
    ("key", "solicited_instance", "solicited information: RPLInstanceID"),
    ("key", "solicited_v", "solicited information V: the version number must match"),
    ("key", "solicited_i", "solicited information I: the instance ID must match"),
    ("key", "solicited_d", "solicited information D: the DODAGID must match"),
    ("key", "solicited_flags", "solicited information: the 5 flag bits after D, 0"),
    ("key", "solicited_dodagid", "solicited information: DODAGID, as hexadecimal digits"),
    ("key", "solicited_version", "solicited information: version number"),
    ("key", "on_link", "prefix information L: the prefix is on-link"),
    ("key", "autonomous", "prefix information A: the prefix may be used for address autoconfiguration"),
    ("key", "router_address", "prefix information R: the prefix field holds the sender's whole address"),
    ("key", "prefix_reserved1", "prefix information: the 5 reserved bits after R, 0"),
    ("key", "valid_lifetime", "prefix information: valid lifetime, seconds"),
    ("key", "preferred_lifetime", "prefix information: preferred lifetime, seconds"),
    ("key", "prefix_reserved2", "prefix information: the 32 reserved bits, 0"),
    ("key", "prefix", "prefix information: the prefix (or the router's address), 16 octets, as hexadecimal digits"),
    ("key", "descriptor", "RPL target descriptor: an opaque 32-bit descriptor"),
    ("list", "option_octets", "PadN and options of other types: their data, as octets"),
    ("key", "octet", "one octet"),
]
RPL_STRINGS = ["dodagid", "solicited_dodagid", "prefix"]


def module(name, header, src, keys, strings=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in strings else "int", k[2]))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/lowpan-frame/pack.def", lowpan_pack())
    out.write("packs/rpl-control/pack.def", rpl_pack())
    out.write("model/lowpan.def", module("lowpan", ["# The lowpan module: the fields of 6LoWPAN frames (RFC 4944, RFC 6282, RFC 7400). Written by tools/gen/mesh-pack.py."],
                                         'source        "IETF RFC 4944, RFC 6282 and RFC 7400; restated by goat-transformers"', LOWPAN_KEYS, LOWPAN_STRINGS))
    out.write("model/rpl.def", module("rpl", ["# The rpl module: the fields of RPL control messages (RFC 6550). Written by tools/gen/mesh-pack.py."],
                                      'source        "IETF RFC 6550; restated by goat-transformers"', RPL_KEYS, RPL_STRINGS))
    return {"mesh": 4}


def main(argv=None):
    return genio.vector_main("mesh-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
