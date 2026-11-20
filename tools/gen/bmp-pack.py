#!/usr/bin/env python3
"""Write packs/bgp-bmp/pack.def and model/bmp.def: the BGP Monitoring Protocol (RFC 7854, with
the Adj-RIB-Out of RFC 8671 and the Loc-RIB of RFC 9069).

A BMP message repeats a few blocks in many places: the per-peer header in five message types,
a BGP message (RFC 4271 section 4) in four, TLV lists in four, and in a BGP UPDATE a prefix of
0 to 16 octets chosen by its length and the path attributes. This script writes those
repetitions from one statement of each, read from RFC 7854 sections 4.1 to 4.10, RFC 8671
sections 4 to 6, RFC 9069 sections 4 and 5 and RFC 4271 section 4. The prefix and attribute
blocks follow the statement tools/gen/mrt-pack.py makes of the same RFC 4271 layouts. The
vectors are not written here: tools/gen/routing-vectors.py derives them with an encoder of its
own.

Usage: python3 -I tools/gen/bmp-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

RFC_SHA = {"rfc7854": "43b9dddf7a0b4bef3f5f94fc50e89d8e9ebec7cd9077568a41cfb8a89785b0db",
           "rfc8671": "380320e72475eea11916fbab63c877ddb67018a6fb7ab3f3fe4070972e476dcd",
           "rfc9069": "35c4a9f467718f0cdf843912b4f18f10007e0bf3001b43f37b8eb9484c56547c",
           "rfc4271": "98b851146abcd56ecbb398dd1a818bcde2dcac6fde3d901c423d988f86eaab76"}

# stat types of RFC 7854 section 4.8 and RFC 8671 section 6: (types, layout)
STATS = [("0,1,2,3,4,5,6,11,12,13", "counter"), ("7,8,14,15", "gauge"), ("9,10,16,17", "afi_safi")]


class W:
    def __init__(self):
        self.lines = []
        self.ind = 0

    def __call__(self, text):
        self.lines.append("  " * self.ind + text)

    def block(self, head):
        self(head)
        self.ind += 1

    def end(self):
        self.ind -= 1
        self("end")

    def endswitch(self):
        self.ind -= 1
        self("end")

    def case(self, head):
        self(head)
        self.ind += 1

    def endcase(self):
        self.ind -= 1


def octets(w, lst, key="octet"):
    """Bytes the pack does not interpret, as a list of octets to the end of the extent."""
    w.block("group  bmp.%s  rest" % lst)
    w("field  bmp.%s  8  uint" % key)
    w.end()


def prefix(w):
    """A prefix of `prefix_length` bits in the fewest whole octets (RFC 4271 section 4.3)."""
    w("field  bmp.prefix_length  8  uint")
    w.block("switch  bmp.prefix_length")
    for n in range(0, 17):
        lo, hi = (0, 0) if n == 0 else (8 * n - 7, 8 * n)
        w.case("case  %s" % ",".join(str(v) for v in range(lo, hi + 1)))
        for i in range(1, n + 1):
            w("field  bmp.prefix_octet_%d  8  uint" % i)
        w.endcase()
    w.endswitch()


def attributes(w, asn_bits):
    """BGP path attributes to the end of the extent (RFC 4271 section 4.3): ORIGIN, AS_PATH,
    NEXT_HOP, MULTI_EXIT_DISC and LOCAL_PREF are read; any other value is kept as octets."""
    w.block("group  bmp.attributes  rest")
    for f in ("optional", "transitive", "partial", "extended_length"):
        w("field  bmp.attr_%s  1  uint" % f)
    w("field  bmp.attr_flags_low  4  uint")
    w("field  bmp.attr_type  8  uint")
    w.block("switch  bmp.attr_extended_length")
    for case, bits in (("case  1", 16), ("else", 8)):
        w.case(case)
        w.block("length  %d  bytes" % bits)
        w.block("switch  bmp.attr_type")
        w.case("case  1")
        w("field  bmp.origin  8  uint")
        w.endcase()
        w.case("case  2")
        w.block("group  bmp.as_path_segments  rest")
        w("field  bmp.segment_type  8  uint")
        w("count  asns  8")
        w.block("group  bmp.segment_asns  count  @asns")
        w("field  bmp.asn  %d  uint" % asn_bits)
        w.end()
        w.end()
        w.endcase()
        for code, key in ((3, "next_hop"), (4, "multi_exit_disc"), (5, "local_pref")):
            w.case("case  %d" % code)
            w("field  bmp.%s  32  uint" % key)
            w.endcase()
        w.case("else")
        octets(w, "attr_value")
        w.endcase()
        w.endswitch()
        w.end()
        w.endcase()
    w.endswitch()
    w.end()


def bgp_message(w, p, types, asn_bits=32):
    """A BGP message (RFC 4271 section 4.1): the marker of 16 octets all ones, the length (which
    counts the marker, itself and the type), the type, and the body of the types in `types`;
    any other type keeps its body as octets. `p` prefixes the keys, so that two messages in one
    scope (the OPENs of a Peer Up) keep apart."""
    for _ in range(4):
        w("const  32  4294967295")
    w.block("length  16  bytes  plus  18")
    w("field  bmp.%sbgp_type  8  uint" % p)
    w.block("switch  bmp.%sbgp_type" % p)
    if "open" in types:
        w.case("case  1")
        w("field  bmp.%sopen_version  8  uint" % p)
        w("field  bmp.%sopen_my_as  16  uint" % p)
        w("field  bmp.%sopen_hold_time  16  uint" % p)
        w("field  bmp.%sopen_bgp_identifier  32  uint" % p)
        w.block("length  8  bytes")
        octets(w, "%sopen_parameters" % p)
        w.end()
        w.endcase()
    if "update" in types:
        w.case("case  2")
        w.block("length  16  bytes")
        w.block("group  bmp.withdrawn_routes  rest")
        prefix(w)
        w.end()
        w.end()
        w.block("length  16  bytes")
        attributes(w, asn_bits)
        w.end()
        w.block("group  bmp.nlri  rest")
        prefix(w)
        w.end()
        w.endcase()
    if "notification" in types:
        w.case("case  3")
        w("field  bmp.%serror_code  8  uint" % p)
        w("field  bmp.%serror_subcode  8  uint" % p)
        octets(w, "%snotification_data" % p)
        w.endcase()
    if "keepalive" in types:
        w("case  4")
    w.case("else")
    octets(w, "%sbgp_body" % p)
    w.endcase()
    w.endswitch()
    w.end()


def per_peer(w):
    """The per-peer header (RFC 7854 section 4.2; O flag RFC 8671 section 4; peer type 3 and its
    F flag RFC 9069 section 4.1)."""
    w("field  bmp.peer_type  8  uint")
    for f in ("v", "l", "a", "o"):
        w("field  bmp.peer_flag_%s  1  uint" % f)
    w("field  bmp.peer_flags_low  4  uint")
    w("field  bmp.peer_distinguisher  64  uint")
    address(w, "peer")
    w("field  bmp.peer_as  32  uint")
    w("field  bmp.peer_bgp_id  32  uint")
    w("field  bmp.timestamp_sec  32  uint")
    w("field  bmp.timestamp_usec  32  uint")


def address(w, who):
    """An address field of 16 octets: IPv6 when the V flag is 1, else IPv4 in the last 4 octets."""
    w.block("switch  bmp.peer_flag_v")
    w.case("case  1")
    w("field  bmp.%s_ipv6_high  64  uint" % who)
    w("field  bmp.%s_ipv6_low  64  uint" % who)
    w.endcase()
    w.case("else")
    w("pad  96")
    w("field  bmp.%s_ipv4  32  uint" % who)
    w.endcase()
    w.endswitch()


def info_tlvs(w, lst, special=None):
    """Information TLVs to the end of the message (RFC 7854 sections 4.4 and 4.5): type, length,
    value; a value is kept as octets unless `special` lays out its type."""
    w.block("group  bmp.%s  rest" % lst)
    w("field  bmp.info_type  16  uint")
    w.block("length  16  bytes")
    if special:
        w.block("switch  bmp.info_type")
        special(w)
        w.case("else")
        octets(w, "info_value")
        w.endcase()
        w.endswitch()
    else:
        octets(w, "info_value")
    w.end()
    w.end()


def termination_reason(w):
    w.case("case  1")
    w("field  bmp.termination_reason  16  uint")
    w.endcase()


def mirror_special(w):
    w.case("case  0")
    bgp_message(w, "", ("open", "update", "notification", "keepalive"))
    w.endcase()
    w.case("case  1")
    w("field  bmp.mirror_code  16  uint")
    w.endcase()


def pack_text():
    w = W()
    for line in ["# BGP Monitoring Protocol (RFC 7854; Adj-RIB-Out, RFC 8671; Loc-RIB, RFC 9069): one BMP",
                 "# message, the common header and the message of its type. Public. Written by",
                 "# tools/gen/bmp-pack.py from one statement of each layout; do not edit by hand. I/O is",
                 "# hex text. pack.md states what is mapped and what is not.",
                 "format        bgp-bmp", "version       0.1.0", "distribution  public",
                 'source        "IETF RFC 7854, BGP Monitoring Protocol (BMP), https://www.rfc-editor.org/rfc/rfc7854.txt (sha256 %s); layout restated"' % RFC_SHA["rfc7854"],
                 'source        "IETF RFC 8671, Support for Adj-RIB-Out in BMP, https://www.rfc-editor.org/rfc/rfc8671.txt (sha256 %s)"' % RFC_SHA["rfc8671"],
                 'source        "IETF RFC 9069, Support for Local RIB in BMP, https://www.rfc-editor.org/rfc/rfc9069.txt (sha256 %s)"' % RFC_SHA["rfc9069"],
                 'source        "IETF RFC 4271, A Border Gateway Protocol 4 (BGP-4), section 4, the BGP messages BMP carries (sha256 %s)"' % RFC_SHA["rfc4271"],
                 "uses          bmp", "wire          bits", "layout        sequential", "bit_order     msb", "",
                 "kind    message", "when    8  3", "length  32  whole", "field   bmp.msg_type  8  uint"]:
        w(line)
    w.block("switch  bmp.msg_type")
    w.case("case  0                       # Route Monitoring")
    per_peer(w)
    w.block("switch  bmp.peer_flag_a")
    w.case("case  1                     # the legacy 2-octet AS_PATH")
    bgp_message(w, "", ("update",), 16)
    w.endcase()
    w.case("else")
    bgp_message(w, "", ("update",), 32)
    w.endcase()
    w.endswitch()
    w.endcase()
    w.case("case  1                       # Statistics Report")
    per_peer(w)
    w.block("group  bmp.stats  count  32")
    w("field  bmp.stat_type  16  uint")
    w.block("length  16  bytes")
    w.block("switch  bmp.stat_type")
    for types, layout in STATS:
        w.case("case  %s" % types)
        if layout == "counter":
            w("field  bmp.stat_counter  32  uint")
        elif layout == "gauge":
            w("field  bmp.stat_gauge  64  uint")
        else:
            w("field  bmp.stat_afi  16  uint")
            w("field  bmp.stat_safi  8  uint")
            w("field  bmp.stat_gauge  64  uint")
        w.endcase()
    w.case("else")
    octets(w, "stat_value")
    w.endcase()
    w.endswitch()
    w.end()
    w.end()
    w.endcase()
    w.case("case  2                       # Peer Down Notification")
    per_peer(w)
    w("field  bmp.down_reason  8  uint")
    w.block("switch  bmp.down_reason")
    w.case("case  1,3")
    bgp_message(w, "", ("notification",))
    w.endcase()
    w.case("case  2")
    w("field  bmp.fsm_event  16  uint")
    w.endcase()
    w.case("case  6")
    info_tlvs(w, "down_tlvs")
    w.endcase()
    w("case  4,5")
    w.case("else")
    octets(w, "down_data")
    w.endcase()
    w.endswitch()
    w.endcase()
    w.case("case  3                       # Peer Up Notification")
    per_peer(w)
    address(w, "local")
    w("field  bmp.local_port  16  uint")
    w("field  bmp.remote_port  16  uint")
    bgp_message(w, "sent_", ("open",))
    bgp_message(w, "received_", ("open",))
    info_tlvs(w, "up_tlvs")
    w.endcase()
    w.case("case  4                       # Initiation")
    info_tlvs(w, "init_tlvs")
    w.endcase()
    w.case("case  5                       # Termination")
    info_tlvs(w, "term_tlvs", termination_reason)
    w.endcase()
    w.case("case  6                       # Route Mirroring")
    per_peer(w)
    w.block("group  bmp.mirror_tlvs  rest")
    w("field  bmp.mirror_type  16  uint")
    w.block("length  16  bytes")
    w.block("switch  bmp.mirror_type")
    mirror_special(w)
    w.case("else")
    octets(w, "info_value")
    w.endcase()
    w.endswitch()
    w.end()
    w.end()
    w.endcase()
    w.case("else")
    octets(w, "body")
    w.endcase()
    w.endswitch()
    return "\n".join(w.lines) + "\n"


KEYS = [
    ("key", "msg_type", "int", "-", "message type: 0 Route Monitoring, 1 Statistics Report, 2 Peer Down, 3 Peer Up, 4 Initiation, 5 Termination, 6 Route Mirroring"),
    ("list", "body", None, None, "body of a message of another type, as its octets"),
    ("key", "octet", "int", "-", "one octet of a value the pack does not lay out"),
    ("key", "peer_type", "int", "-", "peer type: 0 global instance, 1 route distinguisher instance, 2 local instance, 3 Loc-RIB instance (RFC 9069)"),
    ("key", "peer_flag_v", "int", "-", "for peer types 0-2 the V flag, 1 when the peer address is IPv6; for the Loc-RIB peer type the F flag, 1 when the Loc-RIB is filtered"),
    ("key", "peer_flag_l", "int", "-", "L flag: 1 post-policy, 0 pre-policy"),
    ("key", "peer_flag_a", "int", "-", "A flag: 1 when the BGP message uses the legacy 2-octet AS_PATH"),
    ("key", "peer_flag_o", "int", "-", "O flag (RFC 8671): 1 Adj-RIB-Out, 0 Adj-RIB-In"),
    ("key", "peer_flags_low", "int", "-", "the four low bits of the peer flags, reserved"),
    ("key", "peer_distinguisher", "int", "-", "peer distinguisher, 64 bits (as uint reads 64 bits: negative when the top bit is set); zero for a global instance peer"),
    ("key", "peer_ipv4", "int", "-", "IPv4 address of the peer, as an unsigned 32-bit integer"),
    ("key", "peer_ipv6_high", "int", "-", "first 64 bits of the peer's IPv6 address"),
    ("key", "peer_ipv6_low", "int", "-", "last 64 bits of the peer's IPv6 address"),
    ("key", "peer_as", "int", "-", "AS number of the peer"),
    ("key", "peer_bgp_id", "int", "-", "BGP identifier of the peer"),
    ("key", "timestamp_sec", "int", "s", "when the routes were received: seconds since 1970-01-01 UTC; 0 when not known"),
    ("key", "timestamp_usec", "int", "us", "microseconds after timestamp_sec"),
    ("key", "bgp_type", "int", "-", "BGP message type: 1 OPEN, 2 UPDATE, 3 NOTIFICATION, 4 KEEPALIVE"),
    ("list", "bgp_body", None, None, "body of a BGP message of a type the place does not lay out, as its octets"),
    ("list", "withdrawn_routes", None, None, "UPDATE: withdrawn IPv4 prefixes, in order"),
    ("list", "nlri", None, None, "UPDATE: announced IPv4 prefixes, in order"),
    ("key", "prefix_length", "int", "bit", "length of a prefix in bits"),
] + [("key", "prefix_octet_%d" % i, "int", "-", "octet %d of a prefix; a prefix has as many octets as its length needs" % i)
     for i in range(1, 17)] + [
    ("list", "attributes", None, None, "UPDATE: BGP path attributes, in order"),
    ("key", "attr_optional", "int", "-", "optional flag of a path attribute"),
    ("key", "attr_transitive", "int", "-", "transitive flag of a path attribute"),
    ("key", "attr_partial", "int", "-", "partial flag of a path attribute"),
    ("key", "attr_extended_length", "int", "-", "extended-length flag: 1 when the attribute's length takes two octets"),
    ("key", "attr_flags_low", "int", "-", "the four low bits of the attribute flags, unused"),
    ("key", "attr_type", "int", "-", "attribute type code: 1 ORIGIN, 2 AS_PATH, 3 NEXT_HOP, 4 MULTI_EXIT_DISC, 5 LOCAL_PREF, ..."),
    ("key", "origin", "int", "-", "ORIGIN: 0 IGP, 1 EGP, 2 INCOMPLETE"),
    ("list", "as_path_segments", None, None, "segments of the AS_PATH attribute, in order"),
    ("key", "segment_type", "int", "-", "AS_PATH segment type: 1 AS_SET, 2 AS_SEQUENCE"),
    ("list", "segment_asns", None, None, "AS numbers of an AS_PATH segment, in order"),
    ("key", "asn", "int", "-", "one AS number of an AS_PATH segment, of 2 or 4 octets by the A flag"),
    ("key", "next_hop", "int", "-", "NEXT_HOP: an IPv4 address as an unsigned 32-bit integer"),
    ("key", "multi_exit_disc", "int", "-", "MULTI_EXIT_DISC metric"),
    ("key", "local_pref", "int", "-", "LOCAL_PREF"),
    ("list", "attr_value", None, None, "value of an attribute the pack does not read, as its octets"),
    ("key", "error_code", "int", "-", "NOTIFICATION: error code"),
    ("key", "error_subcode", "int", "-", "NOTIFICATION: error subcode"),
    ("list", "notification_data", None, None, "NOTIFICATION: data, as its octets"),
    ("list", "stats", None, None, "Statistics Report: the statistics, in order"),
    ("key", "stat_type", "int", "-", "stat type (RFC 7854 section 4.8, RFC 8671 section 6)"),
    ("key", "stat_counter", "int", "-", "a 32-bit counter (stat types 0-6 and 11-13)"),
    ("key", "stat_gauge", "int", "-", "a 64-bit gauge (stat types 7, 8, 14 and 15, and with an AFI and SAFI 9, 10, 16 and 17)"),
    ("key", "stat_afi", "int", "-", "address family identifier of a per-AFI/SAFI gauge"),
    ("key", "stat_safi", "int", "-", "subsequent address family identifier of a per-AFI/SAFI gauge"),
    ("list", "stat_value", None, None, "value of a stat type the pack does not lay out, as its octets"),
    ("key", "down_reason", "int", "-", "Peer Down reason: 1 local close with a NOTIFICATION, 2 local close with an FSM event, 3 remote close with a NOTIFICATION, 4 remote close without one, 5 peer no longer monitored, 6 Loc-RIB instance closed (RFC 9069)"),
    ("key", "fsm_event", "int", "-", "Peer Down reason 2: the code of the BGP finite-state-machine event; 0 when none applies"),
    ("list", "down_tlvs", None, None, "Peer Down reason 6: information TLVs (RFC 9069), in order"),
    ("list", "down_data", None, None, "Peer Down data of another reason, as its octets"),
    ("key", "local_ipv4", "int", "-", "Peer Up: local IPv4 address of the session, as an unsigned 32-bit integer"),
    ("key", "local_ipv6_high", "int", "-", "Peer Up: first 64 bits of the local IPv6 address"),
    ("key", "local_ipv6_low", "int", "-", "Peer Up: last 64 bits of the local IPv6 address"),
    ("key", "local_port", "int", "-", "Peer Up: local TCP port of the session"),
    ("key", "remote_port", "int", "-", "Peer Up: remote TCP port of the session"),
]
for p, who in (("sent_", "the OPEN the monitored router sent"), ("received_", "the OPEN the monitored router received")):
    KEYS += [
        ("key", p + "bgp_type", "int", "-", "Peer Up, %s: BGP message type, 1 for an OPEN" % who),
        ("list", p + "bgp_body", None, None, "Peer Up, %s: body of a message other than an OPEN, as its octets" % who),
        ("key", p + "open_version", "int", "-", "Peer Up, %s: BGP version" % who),
        ("key", p + "open_my_as", "int", "-", "Peer Up, %s: the sender's 2-octet AS number" % who),
        ("key", p + "open_hold_time", "int", "s", "Peer Up, %s: proposed hold time" % who),
        ("key", p + "open_bgp_identifier", "int", "-", "Peer Up, %s: BGP identifier of the sender" % who),
        ("list", p + "open_parameters", None, None, "Peer Up, %s: optional parameters, as their octets" % who),
    ]
KEYS += [
    ("key", "open_version", "int", "-", "Route Mirroring, a mirrored OPEN: BGP version"),
    ("key", "open_my_as", "int", "-", "Route Mirroring, a mirrored OPEN: the sender's 2-octet AS number"),
    ("key", "open_hold_time", "int", "s", "Route Mirroring, a mirrored OPEN: proposed hold time"),
    ("key", "open_bgp_identifier", "int", "-", "Route Mirroring, a mirrored OPEN: BGP identifier of the sender"),
    ("list", "open_parameters", None, None, "Route Mirroring, a mirrored OPEN: optional parameters, as their octets"),
]
KEYS += [
    ("list", "up_tlvs", None, None, "Peer Up: information TLVs, in order"),
    ("list", "init_tlvs", None, None, "Initiation: information TLVs, in order"),
    ("list", "term_tlvs", None, None, "Termination: information TLVs, in order"),
    ("key", "info_type", "int", "-", "information TLV type: 0 string; Initiation 1 sysDescr, 2 sysName; Termination 1 reason; Peer Up 3 VRF or table name (RFC 9069), 4 admin label (RFC 8671)"),
    ("list", "info_value", None, None, "value of an information or route mirroring TLV, as its octets (a string is its UTF-8 octets)"),
    ("key", "termination_reason", "int", "-", "Termination reason: 0 administratively closed, 1 unspecified, 2 out of resources, 3 redundant connection, 4 permanently administratively closed"),
    ("list", "mirror_tlvs", None, None, "Route Mirroring: the TLVs, in order"),
    ("key", "mirror_type", "int", "-", "route mirroring TLV type: 0 a BGP message, 1 information"),
    ("key", "mirror_code", "int", "-", "route mirroring information code: 0 errored PDU, 1 messages lost"),
]


def module_text():
    L = ["# The bmp module: the fields of BGP Monitoring Protocol messages (RFC 7854, RFC 8671, RFC 9069)",
         "# and of the BGP messages they carry (RFC 4271 section 4), as the messages hold them. Written by",
         "# tools/gen/bmp-pack.py; do not edit by hand. Addresses are unsigned integers (IPv6 in two",
         "# halves); AS numbers and identifiers are integers.",
         "module        bmp", "version       0.1.0", "distribution  public",
         'source        "IETF RFC 7854, RFC 8671 and RFC 9069 (BMP), RFC 4271 section 4 (BGP messages); restated by goat-transformers"']
    w = max(len(k[1]) for k in KEYS)
    for kind, name, vt, unit, meaning in KEYS:
        if kind == "list":
            L.append('list  %-*s  "%s"' % (w, name, meaning))
        else:
            L.append('key   %-*s  %-4s  %-3s  "%s"' % (w, name, vt, unit, meaning))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/bgp-bmp/pack.def", pack_text())
    out.write("model/bmp.def", module_text())
    return {"bgp-bmp": 2}


def main(argv=None):
    return genio.vector_main("bmp-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
