#!/usr/bin/env python3
"""Write packs/pcep/pack.def and model/pcep.def: a PCEP message (RFC 5440): the common header,
then each object with its common object header and, for the object classes RFC 5440 defines,
its body; the route objects' subobjects as RFC 3209 section 4.3.3 states them.

The TLV block (RFC 5440 section 7.1) and the subobject block repeat in several object bodies;
this script writes each repetition from one statement. The vectors are not written here:
tools/gen/ietf-more-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/pcep-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SHA = {"rfc5440": "2b7b7c9d2980aecd8c46637ce5f562d320eb4bb9718f3428d5a582ea2c700ae2",
       "rfc3209": "a2ebe64e44c276aa217589950f81c146d4f05a4016ac4a15b0fec7242e304159"}


def F(key, bits, tr="uint"):
    return "field  pcep.%s  %d  %s" % (key, bits, tr)


def octets(lst):
    return ["group  pcep.%s  rest" % lst, "  field  pcep.octet  8  uint", "end"]


def tlvs():
    """Optional TLVs to the end of the object body (RFC 5440 section 7.1): type, length of the
    value, the value as octets, padding to a multiple of 4 octets."""
    return (["group  pcep.tlvs  rest", "  " + F("tlv_type", 16), "  length  16  bytes"] +
            ["    " + x for x in octets("tlv_value")] + ["  end", "  align  32", "end"])


def subobjects(lst):
    """Route subobjects to the end of the object body (RFC 3209 section 4.3.3): the L bit, the
    type, the length (of the whole subobject), the content by type."""
    body = ["group  pcep.%s  rest" % lst, "  " + F("sub_l", 1), "  " + F("sub_type", 7),
            "  length  8  bytes  plus  2", "    switch  pcep.sub_type",
            "      case  1", "        " + F("sub_ipv4", 32), "        " + F("sub_prefix_length", 8),
            "        " + F("sub_flags", 8),
            "      case  2", "        " + F("sub_ipv6_high", 64), "        " + F("sub_ipv6_low", 64),
            "        " + F("sub_prefix_length", 8), "        " + F("sub_flags", 8),
            "      case  32", "        " + F("sub_asn", 16),
            "      else"] + ["        " + x for x in octets("sub_value")] + ["    end", "  end", "end"]
    return body


BODIES = [
    ("1", "OPEN", [F("open_version", 3), F("open_flags", 5), F("keepalive", 8), F("deadtimer", 8), F("sid", 8)] + tlvs()),
    ("2", "RP", [F("rp_flags", 26), F("rp_o", 1), F("rp_b", 1), F("rp_r", 1), F("rp_priority", 3),
                 F("request_id", 32)] + tlvs()),
    ("3", "NO-PATH", [F("nature_of_issue", 8), F("no_path_c", 1), F("no_path_flags", 15), "pad  8"] + tlvs()),
    ("4", "END-POINTS", ["switch  pcep.object_type", "  case  1", "    " + F("source_ipv4", 32),
                         "    " + F("destination_ipv4", 32), "  case  2", "    " + F("source_ipv6_high", 64),
                         "    " + F("source_ipv6_low", 64), "    " + F("destination_ipv6_high", 64),
                         "    " + F("destination_ipv6_low", 64), "  else"] +
     ["    " + x for x in octets("body_octets")] + ["end"]),
    ("5", "BANDWIDTH", [F("bandwidth", 32, "f32")]),
    ("6", "METRIC", ["pad  16", F("metric_flags", 6), F("metric_c", 1), F("metric_b", 1), F("metric_type", 8),
                     F("metric_value", 32, "f32")]),
    ("7", "ERO", subobjects("ero")),
    ("8", "RRO", subobjects("rro")),
    ("9", "LSPA", [F("exclude_any", 32), F("include_any", 32), F("include_all", 32), F("setup_priority", 8),
                   F("holding_priority", 8), F("lspa_flags", 7), F("lspa_l", 1), "pad  8"] + tlvs()),
    ("10", "IRO", subobjects("iro")),
    ("11", "SVEC", ["pad  8", F("svec_flags", 21), F("svec_s", 1), F("svec_n", 1), F("svec_l", 1),
                    "group  pcep.svec_request_ids  rest", "  " + F("svec_request_id", 32), "end"]),
    ("12", "NOTIFICATION", ["pad  8", F("notification_flags", 8), F("notification_type", 8),
                            F("notification_value", 8)] + tlvs()),
    ("13", "PCEP-ERROR", ["pad  8", F("error_flags", 8), F("error_type", 8), F("error_value", 8)] + tlvs()),
    ("14", "LOAD-BALANCING", ["pad  16", F("lb_flags", 8), F("max_lsp", 8), F("min_bandwidth", 32, "f32")]),
    ("15", "CLOSE", ["pad  16", F("close_flags", 8), F("close_reason", 8)] + tlvs()),
]


def pack_text():
    L = ["# PCEP message (RFC 5440): the common header and every object, with the bodies of the object",
         "# classes 1 to 15. Public. Written by tools/gen/pcep-pack.py; do not edit by hand. Wire bits,",
         "# layout sequential, msb; I/O is hex text. pack.md states what is mapped.",
         "format        pcep", "version       0.1.0", "distribution  public",
         'source        "IETF RFC 5440, Path Computation Element (PCE) Communication Protocol (PCEP), March 2009, https://www.rfc-editor.org/rfc/rfc5440.txt (sha256 %s); layout restated"' % SHA["rfc5440"],
         'source        "IETF RFC 3209, RSVP-TE, December 2001, section 4.3.3, the subobjects of the route objects, https://www.rfc-editor.org/rfc/rfc3209.txt (sha256 %s); layout restated"' % SHA["rfc3209"],
         "uses          pcep", "wire          bits", "layout        sequential", "bit_order     msb", "",
         "kind    message", "when    3  1", F("message_flags", 5), F("message_type", 8), "length  16  whole",
         "group  pcep.objects  rest", "  " + F("object_class", 8), "  " + F("object_type", 4),
         "  " + F("object_reserved", 2), "  " + F("object_p", 1), "  " + F("object_i", 1),
         "  length  16  bytes  plus  4", "    switch  pcep.object_class"]
    for cls, name, lines in BODIES:
        L.append("      case  %-3s                   # %s" % (cls, name))
        L += ["        " + x for x in lines]
    L.append("      else")
    L += ["        " + x for x in octets("body_octets")]
    L += ["    end", "  end", "end"]
    return "\n".join(L) + "\n"


KEYS = [
    ("key", "message_flags", "int", "-", "flags of the common header, 5 bits, none defined"),
    ("key", "message_type", "int", "-", "message type: 1 Open, 2 Keepalive, 3 PCReq, 4 PCRep, 5 PCNtf, 6 PCErr, 7 Close"),
    ("list", "objects", None, None, "the objects of the message, in order"),
    ("key", "object_class", "int", "-", "object class: 1 OPEN, 2 RP, 3 NO-PATH, 4 END-POINTS, 5 BANDWIDTH, 6 METRIC, 7 ERO, 8 RRO, 9 LSPA, 10 IRO, 11 SVEC, 12 NOTIFICATION, 13 PCEP-ERROR, 14 LOAD-BALANCING, 15 CLOSE"),
    ("key", "object_type", "int", "-", "object type within the class"),
    ("key", "object_reserved", "int", "-", "the two reserved bits of the object header"),
    ("key", "object_p", "int", "-", "P flag: the object must be taken into account by the PCE"),
    ("key", "object_i", "int", "-", "I flag: the PCE ignored the optional object"),
    ("list", "body_octets", None, None, "body of an object of a class or type the pack does not lay out, as its octets"),
    ("key", "octet", "int", "-", "one octet"),
    ("list", "tlvs", None, None, "optional TLVs of an object, in order"),
    ("key", "tlv_type", "int", "-", "TLV type"),
    ("list", "tlv_value", None, None, "value of a TLV, as its octets (without the padding)"),
    ("key", "open_version", "int", "-", "OPEN: PCEP version, 1"),
    ("key", "open_flags", "int", "-", "OPEN: flags, none defined"),
    ("key", "keepalive", "int", "s", "OPEN: the largest gap in seconds between two messages the sender will leave"),
    ("key", "deadtimer", "int", "s", "OPEN: seconds after which the peer declares the session dead without a message"),
    ("key", "sid", "int", "-", "OPEN: PCEP session ID"),
    ("key", "rp_flags", "int", "-", "RP: the 26 high flag bits"),
    ("key", "rp_o", "int", "-", "RP: O flag, 1 when the path may be loose"),
    ("key", "rp_b", "int", "-", "RP: B flag, 1 for a bidirectional TE LSP"),
    ("key", "rp_r", "int", "-", "RP: R flag, 1 for a reoptimization"),
    ("key", "rp_priority", "int", "-", "RP: request priority, 1 lowest to 7 highest, 0 unspecified"),
    ("key", "request_id", "int", "-", "RP: request ID number"),
    ("key", "nature_of_issue", "int", "-", "NO-PATH: nature of issue, 0 no path satisfies the constraints, 1 PCE chain broken"),
    ("key", "no_path_c", "int", "-", "NO-PATH: C flag, 1 when the unsatisfied constraints follow"),
    ("key", "no_path_flags", "int", "-", "NO-PATH: the other flag bits"),
    ("key", "source_ipv4", "int", "-", "END-POINTS: source IPv4 address, as an unsigned 32-bit integer"),
    ("key", "destination_ipv4", "int", "-", "END-POINTS: destination IPv4 address"),
    ("key", "source_ipv6_high", "int", "-", "END-POINTS: first 64 bits of the source IPv6 address"),
    ("key", "source_ipv6_low", "int", "-", "END-POINTS: last 64 bits of the source IPv6 address"),
    ("key", "destination_ipv6_high", "int", "-", "END-POINTS: first 64 bits of the destination IPv6 address"),
    ("key", "destination_ipv6_low", "int", "-", "END-POINTS: last 64 bits of the destination IPv6 address"),
    ("key", "bandwidth", "float", "-", "BANDWIDTH: bandwidth in bytes per second, an IEEE single"),
    ("key", "metric_flags", "int", "-", "METRIC: the six high flag bits"),
    ("key", "metric_c", "int", "-", "METRIC: C flag, 1 when the PCE is asked to compute the metric"),
    ("key", "metric_b", "int", "-", "METRIC: B flag, 1 when the value is a bound"),
    ("key", "metric_type", "int", "-", "METRIC: type, 1 IGP, 2 TE, 3 hop counts"),
    ("key", "metric_value", "float", "-", "METRIC: value, an IEEE single"),
    ("list", "ero", None, None, "ERO: subobjects, in order"),
    ("list", "rro", None, None, "RRO: subobjects, in order"),
    ("list", "iro", None, None, "IRO: subobjects, in order"),
    ("key", "sub_l", "int", "-", "subobject: L bit, 1 for a loose hop (ERO, IRO); 0 in an RRO"),
    ("key", "sub_type", "int", "-", "subobject type: 1 IPv4 prefix, 2 IPv6 prefix, 32 AS number"),
    ("key", "sub_ipv4", "int", "-", "subobject: IPv4 address, as an unsigned 32-bit integer"),
    ("key", "sub_ipv6_high", "int", "-", "subobject: first 64 bits of the IPv6 address"),
    ("key", "sub_ipv6_low", "int", "-", "subobject: last 64 bits of the IPv6 address"),
    ("key", "sub_prefix_length", "int", "-", "subobject: prefix length in bits"),
    ("key", "sub_flags", "int", "-", "subobject: the octet after the prefix length, padding in an ERO and IRO, flags in an RRO"),
    ("key", "sub_asn", "int", "-", "subobject: 2-octet AS number"),
    ("list", "sub_value", None, None, "subobject of another type, its content as octets"),
    ("key", "exclude_any", "int", "-", "LSPA: attribute filter, exclude any"),
    ("key", "include_any", "int", "-", "LSPA: attribute filter, include any"),
    ("key", "include_all", "int", "-", "LSPA: attribute filter, include all"),
    ("key", "setup_priority", "int", "-", "LSPA: setup priority, 0 highest to 7"),
    ("key", "holding_priority", "int", "-", "LSPA: holding priority, 0 highest to 7"),
    ("key", "lspa_flags", "int", "-", "LSPA: the seven high flag bits"),
    ("key", "lspa_l", "int", "-", "LSPA: L flag, 1 when local protection is desired"),
    ("key", "svec_flags", "int", "-", "SVEC: the 21 high flag bits"),
    ("key", "svec_s", "int", "-", "SVEC: S flag, SRLG-diverse"),
    ("key", "svec_n", "int", "-", "SVEC: N flag, node-diverse"),
    ("key", "svec_l", "int", "-", "SVEC: L flag, link-diverse"),
    ("list", "svec_request_ids", None, None, "SVEC: the request IDs it synchronizes, in order"),
    ("key", "svec_request_id", "int", "-", "SVEC: one request ID number"),
    ("key", "notification_flags", "int", "-", "NOTIFICATION: flags"),
    ("key", "notification_type", "int", "-", "NOTIFICATION: notification type"),
    ("key", "notification_value", "int", "-", "NOTIFICATION: notification value"),
    ("key", "error_flags", "int", "-", "PCEP-ERROR: flags"),
    ("key", "error_type", "int", "-", "PCEP-ERROR: error type"),
    ("key", "error_value", "int", "-", "PCEP-ERROR: error value"),
    ("key", "lb_flags", "int", "-", "LOAD-BALANCING: flags"),
    ("key", "max_lsp", "int", "-", "LOAD-BALANCING: the most TE LSPs the bandwidth may be split over"),
    ("key", "min_bandwidth", "float", "-", "LOAD-BALANCING: the least bandwidth of each TE LSP, bytes per second, an IEEE single"),
    ("key", "close_flags", "int", "-", "CLOSE: flags"),
    ("key", "close_reason", "int", "-", "CLOSE: reason, 1 no explanation, 2 DeadTimer expired, 3 malformed message, 4 too many unknown requests or replies, 5 too many unrecognized messages"),
]


def module_text():
    L = ["# The pcep module: the fields of PCEP messages and objects (RFC 5440) and of the route",
         "# subobjects (RFC 3209 section 4.3.3). Written by tools/gen/pcep-pack.py; do not edit by hand.",
         "module        pcep", "version       0.1.0", "distribution  public",
         'source        "IETF RFC 5440 (PCEP) and RFC 3209 section 4.3.3 (route subobjects); restated by goat-transformers"']
    w = max(len(k[1]) for k in KEYS)
    for kind, name, vt, unit, meaning in KEYS:
        if kind == "list":
            L.append('list  %-*s  "%s"' % (w, name, meaning))
        else:
            L.append('key   %-*s  %-5s  %-2s  "%s"' % (w, name, vt, unit, meaning))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/pcep/pack.def", pack_text())
    out.write("model/pcep.def", module_text())
    return {"pcep": 2}


def main(argv=None):
    return genio.vector_main("pcep-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
