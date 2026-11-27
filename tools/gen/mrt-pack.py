#!/usr/bin/env python3
"""Write packs/mrt/pack.def and model/mrt.def: BGP MRT records (RFC 6396, add-path RFC 8050).

The pack repeats one layout in many kinds (a kind per MRT type and subtype) and one block in
many places (a prefix of 0 to 16 octets chosen by its length, the BGP path attributes); this
script writes those repetitions from one statement of each, read from RFC 6396 sections 2, 3,
4.3 and 4.4, RFC 8050 sections 3 and 4, and RFC 4271 section 4 (the BGP message carried in a
BGP4MP_MESSAGE). The vectors are not written here: tools/gen/logs-vectors.py derives them with
an encoder of its own.

Usage: python3 -I tools/gen/mrt-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCES = [
    'source  "IETF RFC 6396, Multi-Threaded Routing Toolkit (MRT) Routing Information Export Format, https://www.rfc-editor.org/rfc/rfc6396.txt (sha256 %s)"',
    'source  "IETF RFC 8050, MRT Routing Information Export Format with BGP Additional Path Extensions, https://www.rfc-editor.org/rfc/rfc8050.txt (sha256 %s)"',
    'source  "IETF RFC 4271, A Border Gateway Protocol 4 (BGP-4), section 4, the BGP message a BGP4MP_MESSAGE carries"',
]


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


def octets(w, lst, key):
    """Bytes the pack does not interpret, as a list of octets to the end of the extent."""
    w.block("group  mrt.%s  rest" % lst)
    w("field  mrt.%s  8  uint" % key)
    w.end()


def prefix(w):
    """A prefix of `prefix_length` bits written in the fewest whole octets (RFC 4271 4.3)."""
    w("field  mrt.prefix_length  8  uint")
    w.block("switch mrt.prefix_length")
    for n in range(0, 17):
        lo, hi = (0, 0) if n == 0 else (8 * n - 7, 8 * n)
        w.block("case %s" % ",".join(str(v) for v in range(lo, hi + 1)))
        for i in range(1, n + 1):
            w("field  mrt.prefix_octet_%d  8  uint" % i)
        w.ind -= 1
    w.end()


def attributes(w, asn_bits):
    """BGP path attributes to the end of the extent (RFC 4271 4.3): flags, type code, a length of
    one octet or, with the extended-length flag, two; the value. ORIGIN, AS_PATH, NEXT_HOP,
    MULTI_EXIT_DISC and LOCAL_PREF are read; any other value is kept as octets."""
    w.block("group  mrt.attributes  rest")
    for f in ("optional", "transitive", "partial", "extended_length"):
        w("field  mrt.attr_%s  1  uint" % f)
    w("field  mrt.attr_flags_low  4  uint")
    w("field  mrt.attr_type  8  uint")
    w.block("switch mrt.attr_extended_length")
    for case, bits in (("case 1", 16), ("else", 8)):
        w.block(case)
        w.block("length %d bytes" % bits)
        w.block("switch mrt.attr_type")
        w.block("case 1")
        w("field  mrt.origin  8  uint")
        w.ind -= 1
        w.block("case 2")
        w.block("group  mrt.as_path_segments  rest")
        w("field  mrt.segment_type  8  uint")
        w("count  asns  8")
        w.block("group  mrt.segment_asns  count @asns")
        w("field  mrt.asn  %d  uint" % asn_bits)
        w.end()
        w.end()
        w.ind -= 1
        for code, key in ((3, "next_hop"), (4, "multi_exit_disc"), (5, "local_pref")):
            w.block("case %d" % code)
            w("field  mrt.%s  32  uint" % key)
            w.ind -= 1
        w.block("else")
        octets(w, "attr_value", "attr_octet")
        w.ind -= 1
        w.end()
        w.end()
        w.ind -= 1
    w.end()
    w.end()


TD2 = [(1, "peer-index-table", None, None), (2, "rib-ipv4-unicast", False, "IPv4"), (3, "rib-ipv4-multicast", False, "IPv4"),
       (4, "rib-ipv6-unicast", False, "IPv6"), (5, "rib-ipv6-multicast", False, "IPv6"),
       (8, "rib-ipv4-unicast-addpath", True, "IPv4"), (9, "rib-ipv4-multicast-addpath", True, "IPv4"),
       (10, "rib-ipv6-unicast-addpath", True, "IPv6"), (11, "rib-ipv6-multicast-addpath", True, "IPv6")]
# subtype, name, AS of 4 octets, a BGP message (else a state change), add-path
BGP4MP = [(0, "state-change", False, False, False), (5, "state-change-as4", True, False, False),
          (1, "message", False, True, False), (4, "message-as4", True, True, False),
          (6, "message-local", False, True, False), (7, "message-as4-local", True, True, False),
          (8, "message-addpath", False, True, True), (9, "message-as4-addpath", True, True, True),
          (10, "message-local-addpath", False, True, True), (11, "message-as4-local-addpath", True, True, True)]


def pack_text(sha):
    w = W()
    for line in ["# BGP MRT records (RFC 6396, with the add-path subtypes of RFC 8050): one record, the",
                 "# common header and the message, for TABLE_DUMP_V2 (13), BGP4MP (16) and BGP4MP_ET (17).",
                 "# Public. Written by tools/gen/mrt-pack.py from one statement of each layout; do not edit",
                 "# by hand. I/O is hex text. pack.md states what is mapped, what is not, and the time.",
                 "format     mrt", "version    0.1.0", "distribution public"]:
        w(line)
    w(SOURCES[0] % sha["rfc6396"])
    w(SOURCES[1] % sha["rfc8050"])
    w(SOURCES[2])
    for line in ["uses       mrt", "wire       bits", "layout     sequential", "bit_order  msb",
                 "field  time_ms  32  uiscale:1000      # Timestamp: seconds since 1970-01-01 UTC"]:
        w(line)
    for sub, name, addpath, _ in TD2:
        w("")
        w("kind    table-dump-v2-%s" % name)
        w("when    16  13  as  mrt.type")
        w("when    16  %d  as  mrt.subtype" % sub)
        w.block("length 32 bytes")
        if sub == 1:
            w("field  mrt.collector_bgp_id  32  uint")
            w.block("length 16 bytes")
            octets(w, "view_name", "view_name_octet")
            w.end()
            w.block("group  mrt.peers  count 16")
            w("field  mrt.peer_type  8  uint")
            w("field  mrt.peer_bgp_id  32  uint")
            w.block("switch mrt.peer_type")
            for v, ip6, as4 in ((0, False, False), (1, True, False), (2, False, True), (3, True, True)):
                w.block("case %d" % v)
                if ip6:
                    w("field  mrt.peer_ipv6_high  64  uint")
                    w("field  mrt.peer_ipv6_low  64  uint")
                else:
                    w("field  mrt.peer_ipv4  32  uint")
                w("field  mrt.peer_as  %d  uint" % (32 if as4 else 16))
                w.ind -= 1
            w.end()
            w.end()
        else:
            w("field  mrt.sequence_number  32  uint")
            prefix(w)
            w.block("group  mrt.rib_entries  count 16")
            w("field  mrt.peer_index  16  uint")
            w("field  mrt.originated_time  32  uint")
            if addpath:
                w("field  mrt.path_identifier  32  uint")
            w.block("length 16 bytes")
            attributes(w, 32)
            w.end()
            w.end()
        w.end()
    for et in (False, True):
        for sub, name, as4, message, addpath in BGP4MP:
            w("")
            w("kind    bgp4mp-%s%s" % ("et-" if et else "", name))
            w("when    16  %d  as  mrt.type" % (17 if et else 16))
            w("when    16  %d  as  mrt.subtype" % sub)
            w.block("length 32 bytes")
            if et:
                w("field  mrt.microseconds  32  uint")
            w("field  mrt.peer_as  %d  uint" % (32 if as4 else 16))
            w("field  mrt.local_as  %d  uint" % (32 if as4 else 16))
            w("field  mrt.interface_index  16  uint")
            w("field  mrt.address_family  16  uint")
            w.block("switch mrt.address_family")
            w.block("case 1")
            w("field  mrt.peer_ipv4  32  uint")
            w("field  mrt.local_ipv4  32  uint")
            w.ind -= 1
            w.block("case 2")
            for k in ("peer_ipv6_high", "peer_ipv6_low", "local_ipv6_high", "local_ipv6_low"):
                w("field  mrt.%s  64  uint" % k)
            w.ind -= 1
            w.end()
            if not message:
                w("field  mrt.old_state  16  uint")
                w("field  mrt.new_state  16  uint")
            else:
                w("field  mrt.bgp_marker_high  64  uint")
                w("field  mrt.bgp_marker_low  64  uint")
                w.block("length 16 bytes plus 18                 # the BGP length counts its marker, itself and the type")
                w("field  mrt.bgp_type  8  uint")
                w.block("switch mrt.bgp_type")
                w.block("case 1                                  # OPEN")
                w("field  mrt.open_version  8  uint")
                w("field  mrt.open_my_as  16  uint")
                w("field  mrt.open_hold_time  16  uint")
                w("field  mrt.open_bgp_identifier  32  uint")
                w.block("length 8 bytes")
                octets(w, "open_parameters", "open_parameter_octet")
                w.end()
                w.ind -= 1
                w.block("case 2                                  # UPDATE")
                w.block("length 16 bytes")
                w.block("group  mrt.withdrawn_routes  rest")
                if addpath:
                    w("field  mrt.path_identifier  32  uint")
                prefix(w)
                w.end()
                w.end()
                w.block("length 16 bytes")
                attributes(w, 32 if as4 else 16)
                w.end()
                w.block("group  mrt.nlri  rest")
                if addpath:
                    w("field  mrt.path_identifier  32  uint")
                prefix(w)
                w.end()
                w.ind -= 1
                w.block("case 3                                  # NOTIFICATION")
                w("field  mrt.error_code  8  uint")
                w("field  mrt.error_subcode  8  uint")
                octets(w, "notification_data", "notification_octet")
                w.ind -= 1
                w("case 4                                    # KEEPALIVE: no body")
                w.block("else")
                octets(w, "bgp_body", "bgp_body_octet")
                w.ind -= 1
                w.end()
                w.end()
            w.end()
    return "\n".join(w.lines) + "\n"


KEYS = [
    # the record header's type and subtype choose the kind; bound by `when ... as` (engine-spec
    # 0.30), they cross to another format and choose the kind on encode from one
    ("key", "type", "int", "-", "MRT type: 13 TABLE_DUMP_V2, 16 BGP4MP, 17 BGP4MP_ET"),
    ("key", "subtype", "int", "-", "MRT subtype within the type (RFC 6396 4.3 and 4.4, RFC 8050)"),
    ("key", "collector_bgp_id", "int", "-", "BGP identifier of the collector that wrote the table (PEER_INDEX_TABLE)"),
    ("list", "view_name", None, None, "name of the view, as its octets (PEER_INDEX_TABLE); an empty list when the view has no name"),
    ("key", "view_name_octet", "int", "-", "one octet of the view name"),
    ("list", "peers", None, None, "peers of the PEER_INDEX_TABLE, in order; a RIB entry names a peer by its index here"),
    ("key", "peer_type", "int", "-", "peer type: bit 0 set for an IPv6 address, bit 1 set for a 4-octet AS number"),
    ("key", "peer_bgp_id", "int", "-", "BGP identifier of the peer"),
    ("key", "peer_ipv4", "int", "-", "IPv4 address of the peer, as an unsigned 32-bit integer"),
    ("key", "peer_ipv6_high", "int", "-", "first 64 bits of the peer's IPv6 address (as uint reads 64 bits: negative when the top bit is set)"),
    ("key", "peer_ipv6_low", "int", "-", "last 64 bits of the peer's IPv6 address"),
    ("key", "peer_as", "int", "-", "AS number of the peer, of 2 or 4 octets by the subtype or peer type"),
    ("key", "sequence_number", "int", "-", "sequence number of the RIB record in its table dump"),
    ("key", "prefix_length", "int", "bit", "length of a prefix in bits"),
] + [("key", "prefix_octet_%d" % i, "int", "-", "octet %d of a prefix; a prefix has as many octets as its length needs" % i)
     for i in range(1, 17)] + [
    ("list", "rib_entries", None, None, "RIB entries of the prefix, one per peer that has a route to it"),
    ("key", "peer_index", "int", "-", "index of the entry's peer in the PEER_INDEX_TABLE"),
    ("key", "originated_time", "int", "s", "time the route was received, seconds since 1970-01-01 UTC"),
    ("key", "path_identifier", "int", "-", "path identifier of an additional path (RFC 7911, RFC 8050)"),
    ("list", "attributes", None, None, "BGP path attributes, in order"),
    ("key", "attr_optional", "int", "-", "optional flag of a path attribute (1 optional, 0 well-known)"),
    ("key", "attr_transitive", "int", "-", "transitive flag of a path attribute"),
    ("key", "attr_partial", "int", "-", "partial flag of a path attribute"),
    ("key", "attr_extended_length", "int", "-", "extended-length flag: 1 when the attribute's length takes two octets"),
    ("key", "attr_flags_low", "int", "-", "the four low bits of the attribute flags, unused"),
    ("key", "attr_type", "int", "-", "attribute type code: 1 ORIGIN, 2 AS_PATH, 3 NEXT_HOP, 4 MULTI_EXIT_DISC, 5 LOCAL_PREF, ..."),
    ("key", "origin", "int", "-", "ORIGIN: 0 IGP, 1 EGP, 2 INCOMPLETE"),
    ("list", "as_path_segments", None, None, "segments of the AS_PATH attribute, in order"),
    ("key", "segment_type", "int", "-", "AS_PATH segment type: 1 AS_SET, 2 AS_SEQUENCE"),
    ("list", "segment_asns", None, None, "AS numbers of an AS_PATH segment, in order"),
    ("key", "asn", "int", "-", "one AS number of an AS_PATH segment, of 2 or 4 octets by the subtype"),
    ("key", "next_hop", "int", "-", "NEXT_HOP: an IPv4 address as an unsigned 32-bit integer"),
    ("key", "multi_exit_disc", "int", "-", "MULTI_EXIT_DISC metric"),
    ("key", "local_pref", "int", "-", "LOCAL_PREF"),
    ("list", "attr_value", None, None, "value of an attribute the pack does not read, as its octets"),
    ("key", "attr_octet", "int", "-", "one octet of an attribute value"),
    ("key", "microseconds", "int", "us", "microseconds after the header's seconds (BGP4MP_ET); time_ms holds the whole seconds only"),
    ("key", "local_as", "int", "-", "AS number of the collector's side of the session"),
    ("key", "interface_index", "int", "-", "interface index of the session on the collector"),
    ("key", "address_family", "int", "-", "address family of the two addresses: 1 IPv4, 2 IPv6"),
    ("key", "local_ipv4", "int", "-", "IPv4 address of the collector's side, as an unsigned 32-bit integer"),
    ("key", "local_ipv6_high", "int", "-", "first 64 bits of the collector's IPv6 address"),
    ("key", "local_ipv6_low", "int", "-", "last 64 bits of the collector's IPv6 address"),
    ("key", "old_state", "int", "-", "BGP finite-state-machine state before the change: 1 Idle to 6 Established"),
    ("key", "new_state", "int", "-", "BGP finite-state-machine state after the change"),
    ("key", "bgp_marker_high", "int", "-", "first 64 bits of the BGP marker (all ones: -1 as uint reads 64 bits)"),
    ("key", "bgp_marker_low", "int", "-", "last 64 bits of the BGP marker"),
    ("key", "bgp_type", "int", "-", "BGP message type: 1 OPEN, 2 UPDATE, 3 NOTIFICATION, 4 KEEPALIVE"),
    ("key", "open_version", "int", "-", "OPEN: BGP version"),
    ("key", "open_my_as", "int", "-", "OPEN: the sender's AS number (2 octets; AS_TRANS 23456 for a 4-octet AS)"),
    ("key", "open_hold_time", "int", "s", "OPEN: proposed hold time"),
    ("key", "open_bgp_identifier", "int", "-", "OPEN: BGP identifier of the sender"),
    ("list", "open_parameters", None, None, "OPEN: optional parameters, as their octets"),
    ("key", "open_parameter_octet", "int", "-", "one octet of the OPEN optional parameters"),
    ("list", "withdrawn_routes", None, None, "UPDATE: withdrawn IPv4 prefixes, in order"),
    ("list", "nlri", None, None, "UPDATE: announced IPv4 prefixes (network layer reachability information), in order"),
    ("key", "error_code", "int", "-", "NOTIFICATION: error code"),
    ("key", "error_subcode", "int", "-", "NOTIFICATION: error subcode"),
    ("list", "notification_data", None, None, "NOTIFICATION: data, as its octets"),
    ("key", "notification_octet", "int", "-", "one octet of the NOTIFICATION data"),
    ("list", "bgp_body", None, None, "body of a BGP message of another type, as its octets"),
    ("key", "bgp_body_octet", "int", "-", "one octet of that body"),
]


def module_text():
    L = ["# The mrt module: the fields of BGP MRT records (RFC 6396, RFC 8050) as the records hold them.",
         "# Written by tools/gen/mrt-pack.py; do not edit by hand. Addresses are unsigned integers",
         "# (IPv6 in two halves); AS numbers and identifiers are integers.",
         "module        mrt", "version       0.1.0", "distribution  public",
         'source        "IETF RFC 6396 and RFC 8050 (MRT), RFC 4271 section 4 (BGP messages); restated by goat-transformers"']
    w = max(len(k[1]) for k in KEYS)
    for kind, name, vt, unit, meaning in KEYS:
        if kind == "list":
            L.append('list  %-*s  "%s"' % (w, name, meaning))
        else:
            L.append('key   %-*s  %-4s  %-3s  "%s"' % (w, name, vt, unit, meaning))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/mrt/pack.def", pack_text(RFC_SHA))
    out.write("model/mrt.def", module_text())
    return {"mrt": 2}


RFC_SHA = {"rfc6396": "415c96368320e94eaed7dd17d024a83c516beb0ac98653ec80ddcc1921d22ef7",
           "rfc8050": "aa3ea773846495e292749a13a5306dfbc6da8e37d80ddbf92fddc827a71b5821"}


def main(argv=None):
    return genio.vector_main("mrt-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
