#!/usr/bin/env python3
"""Write the IPPM test packet packs and model/ippm.def: OWAMP-Test (RFC 4656 section 4.1.2),
the TWAMP-Test reflector packet (RFC 5357 section 4.2.1) and STAMP (RFC 8762 sections 4.2 and
4.3, with the session identifier and the TLVs of RFC 8972), each in the unauthenticated and the
authenticated layout.

The eight layouts share their parts (a timestamp of 64 bits, an error estimate of 16, MBZ runs,
a 16-octet HMAC, the STAMP TLVs); this script writes each layout from one statement of the parts,
so that the packs cannot drift apart. The vectors are not written here:
tools/gen/ietf-more-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/ippm-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SHA = {"rfc4656": "768f1b2b193736c26c0271e2f9ea3e5cd0d05946a6ef5ea29c28378a4d4adbcf",
       "rfc5357": "473849a8af63f863caad7c5b65e922e278190b16bf6c2ff877972738f476669a",
       "rfc8762": "2362c7a7458fe18cab2f10159f08d881bb3792bf3ac3c7a680025a34e073719a",
       "rfc8972": "8839ae063380394360bf58fe0a972684740cfcb89fbf76470181da633cb282a8"}
SRC = {"rfc4656": "IETF RFC 4656, A One-way Active Measurement Protocol (OWAMP), September 2006, section 4.1.2",
       "rfc5357": "IETF RFC 5357, A Two-Way Active Measurement Protocol (TWAMP), October 2008, section 4.2.1",
       "rfc8762": "IETF RFC 8762, Simple Two-Way Active Measurement Protocol (STAMP), March 2020, sections 4.2 and 4.3",
       "rfc8972": "IETF RFC 8972, STAMP Optional Extensions, January 2021, sections 3 and 4"}


def F(key, bits):
    return "field  ippm.%s  %d  uint" % (key, bits)


def ts(p):
    return [F(p + "ts_sec", 32), F(p + "ts_frac", 32)]


def err(p):
    return [F(p + "err_s", 1), F(p + "err_z", 1), F(p + "err_scale", 6), F(p + "err_multiplier", 8)]


def pad(octets):
    return ["pad  %d" % (8 * octets)]


HMAC = [F("hmac_high", 64), F("hmac_low", 64)]
PADDING = ["group  ippm.padding  rest", "  field  ippm.octet  8  uint", "end"]


def octets(lst, ind):
    return [ind + "group  ippm.%s  rest" % lst, ind + "  field  ippm.octet  8  uint", ind + "end"]


def tlvs():
    """STAMP TLVs to the end of the packet (RFC 8972 section 4): flags U, M, I and five reserved
    bits, type, length (of the value), the value by type."""
    L = ["group  ippm.tlvs  rest", "  " + F("tlv_flag_u", 1), "  " + F("tlv_flag_m", 1),
         "  " + F("tlv_flag_i", 1), "  " + F("tlv_flags_low", 5), "  " + F("tlv_type", 8),
         "  length  16  bytes", "    switch  ippm.tlv_type"]
    cases = [
        ("3", [F("sync_src_in", 8), F("timestamp_in", 8), F("sync_src_out", 8), F("timestamp_out", 8)]),
        ("4", [F("cos_dscp1", 6), F("cos_dscp2", 6), F("cos_ecn", 2), F("cos_rp", 2), F("cos_reserved", 16)]),
        ("5", [F("dm_sender_tx", 32), F("dm_reflector_rx", 32), F("dm_reflector_tx", 32)]),
        ("6", [F("ar_id", 4), F("ar_reserved_high", 4), F("ar_return_code", 8), F("ar_reserved", 16)]),
        ("7", [F("fu_sequence", 32), F("fu_ts_sec", 32), F("fu_ts_frac", 32), F("fu_ts_mode", 8),
               F("fu_reserved", 24)]),
    ]
    for v, lines in cases:
        L.append("      case  %s" % v)
        L += ["        " + x for x in lines]
    L.append("      else")
    L += octets("tlv_value", "        ")
    L += ["    end", "  end", "end"]
    return L


SEQ = [F("sequence", 32)]
LAYOUTS = {
    "owamp-test": ("OWAMP-Test packet, unauthenticated mode (also the TWAMP-Test packet of a Session-Sender)",
                   ["rfc4656"], SEQ + ts("") + err("") + PADDING),
    "owamp-test-auth": ("OWAMP-Test packet, authenticated and encrypted modes (also the TWAMP-Test packet of a Session-Sender)",
                        ["rfc4656"], SEQ + pad(12) + ts("") + err("") + pad(6) + HMAC + PADDING),
    "twamp-reflector": ("TWAMP-Test packet of a Session-Reflector, unauthenticated mode", ["rfc5357"],
                        SEQ + ts("") + err("") + pad(2) + ts("rcv_") + [F("sender_sequence", 32)] + ts("sender_") +
                        err("sender_") + pad(2) + [F("sender_ttl", 8)] + PADDING),
    "twamp-reflector-auth": ("TWAMP-Test packet of a Session-Reflector, authenticated and encrypted modes", ["rfc5357"],
                             SEQ + pad(12) + ts("") + err("") + pad(6) + ts("rcv_") + pad(8) +
                             [F("sender_sequence", 32)] + pad(12) + ts("sender_") + err("sender_") + pad(6) +
                             [F("sender_ttl", 8)] + pad(15) + HMAC + PADDING),
    "stamp-sender": ("STAMP Session-Sender test packet, unauthenticated mode, with the SSID and TLVs of RFC 8972",
                     ["rfc8762", "rfc8972"], SEQ + ts("") + err("") + [F("ssid", 16)] + pad(28) + tlvs()),
    "stamp-reflector": ("STAMP Session-Reflector test packet, unauthenticated mode, with the SSID and TLVs of RFC 8972",
                        ["rfc8762", "rfc8972"],
                        SEQ + ts("") + err("") + [F("ssid", 16)] + ts("rcv_") + [F("sender_sequence", 32)] +
                        ts("sender_") + err("sender_") + pad(2) + [F("sender_ttl", 8)] + pad(3) + tlvs()),
    "stamp-sender-auth": ("STAMP Session-Sender test packet, authenticated mode, with the SSID and TLVs of RFC 8972",
                          ["rfc8762", "rfc8972"],
                          SEQ + pad(12) + ts("") + err("") + [F("ssid", 16)] + pad(68) + HMAC + tlvs()),
    "stamp-reflector-auth": ("STAMP Session-Reflector test packet, authenticated mode, with the SSID and TLVs of RFC 8972",
                             ["rfc8762", "rfc8972"],
                             SEQ + pad(12) + ts("") + err("") + [F("ssid", 16)] + pad(4) + ts("rcv_") + pad(8) +
                             [F("sender_sequence", 32)] + pad(12) + ts("sender_") + err("sender_") + pad(6) +
                             [F("sender_ttl", 8)] + pad(15) + HMAC + tlvs()),
}


def pack_text(name):
    what, rfcs, lines = LAYOUTS[name]
    out = ["# %s. Public. Written by tools/gen/ippm-pack.py; do not edit by hand." % what,
           "# Wire bits, layout sequential, msb; I/O is hex text. pack.md states what is mapped.",
           "format        %s" % name, "version       0.1.0", "distribution  public"]
    for r in rfcs:
        out.append('source        "%s, https://www.rfc-editor.org/rfc/%s.txt (sha256 %s); layout restated"'
                   % (SRC[r], r, SHA[r]))
    out += ["uses          ippm", "wire          bits", "layout        sequential", "bit_order     msb", ""]
    return "\n".join(out + lines) + "\n"


def tsk(p, who):
    return [("key", p + "ts_sec", "int", "s", "%s: the integer part, seconds since 1900-01-01 00:00 UTC (NTP format; with Z = 1 the PTP format, seconds since 1970)" % who),
            ("key", p + "ts_frac", "int", "-", "%s: the fractional part in units of 2^-32 s (NTP format; with Z = 1 nanoseconds)" % who)]


def errk(p, who):
    return [("key", p + "err_s", "int", "-", "%s error estimate, S: 1 when the clock is synchronized to UTC by an external source" % who),
            ("key", p + "err_z", "int", "-", "%s error estimate, Z: the timestamp format, 0 NTP, 1 PTP (RFC 8762); 0 in OWAMP and TWAMP" % who),
            ("key", p + "err_scale", "int", "-", "%s error estimate, scale: the error is multiplier × 2^(-32) × 2^scale seconds" % who),
            ("key", p + "err_multiplier", "int", "-", "%s error estimate, multiplier; 0 is not valid" % who)]


KEYS = ([("key", "sequence", "int", "-", "sequence number of the packet in its session, from 0"),
         ("key", "octet", "int", "-", "one octet of a run the pack does not lay out")]
        + tsk("", "Timestamp, when the packet was sent") + errk("", "the sender's")
        + tsk("rcv_", "Receive Timestamp, when the reflector received the packet")
        + [("key", "sender_sequence", "int", "-", "the sequence number of the packet the reflector received")]
        + tsk("sender_", "Session-Sender Timestamp, copied from the packet the reflector received")
        + errk("sender_", "the session-sender's, copied")
        + [("key", "sender_ttl", "int", "-", "TTL or hop limit of the packet the reflector received (255 when it cannot be read)"),
           ("key", "ssid", "int", "-", "STAMP session identifier (RFC 8972); 0 when not used"),
           ("key", "hmac_high", "int", "-", "first 8 octets of the HMAC (as uint reads 64 bits: negative when the top bit is set)"),
           ("key", "hmac_low", "int", "-", "last 8 octets of the HMAC"),
           ("list", "padding", None, None, "packet padding after the fields, as its octets"),
           ("list", "tlvs", None, None, "STAMP TLVs (RFC 8972), in order"),
           ("key", "tlv_flag_u", "int", "-", "TLV flag U: set by the reflector when it did not recognize the TLV"),
           ("key", "tlv_flag_m", "int", "-", "TLV flag M: set by the reflector when the TLV was malformed"),
           ("key", "tlv_flag_i", "int", "-", "TLV flag I: set by the reflector when the integrity check of the TLVs failed"),
           ("key", "tlv_flags_low", "int", "-", "the five reserved bits of the TLV flags"),
           ("key", "tlv_type", "int", "-", "TLV type: 1 extra padding, 2 location, 3 timestamp information, 4 class of service, 5 direct measurement, 6 access report, 7 follow-up telemetry, 8 HMAC"),
           ("list", "tlv_value", None, None, "value of a TLV the pack does not lay out (extra padding, location, HMAC, others), as its octets"),
           ("key", "sync_src_in", "int", "-", "timestamp information: synchronization source of the receive timestamp"),
           ("key", "timestamp_in", "int", "-", "timestamp information: timestamping method of the receive timestamp"),
           ("key", "sync_src_out", "int", "-", "timestamp information: synchronization source of the transmit timestamp"),
           ("key", "timestamp_out", "int", "-", "timestamp information: timestamping method of the transmit timestamp"),
           ("key", "cos_dscp1", "int", "-", "class of service: the DSCP the sender asks the reflector to use"),
           ("key", "cos_dscp2", "int", "-", "class of service: the DSCP of the packet as the reflector received it"),
           ("key", "cos_ecn", "int", "-", "class of service: the ECN of the packet as the reflector received it"),
           ("key", "cos_rp", "int", "-", "class of service: reverse path, 0 when the reflector used DSCP1"),
           ("key", "cos_reserved", "int", "-", "class of service: reserved, 0"),
           ("key", "dm_sender_tx", "int", "-", "direct measurement: the sender's count of transmitted test packets"),
           ("key", "dm_reflector_rx", "int", "-", "direct measurement: the reflector's count of received test packets"),
           ("key", "dm_reflector_tx", "int", "-", "direct measurement: the reflector's count of transmitted test packets"),
           ("key", "ar_id", "int", "-", "access report: identifier of the access network"),
           ("key", "ar_reserved_high", "int", "-", "access report: the four reserved bits after the identifier, 0"),
           ("key", "ar_return_code", "int", "-", "access report: return code"),
           ("key", "ar_reserved", "int", "-", "access report: reserved, 0"),
           ("key", "fu_sequence", "int", "-", "follow-up telemetry: sequence number of the earlier packet it reports on"),
           ("key", "fu_ts_sec", "int", "s", "follow-up telemetry: integer part of that packet's departure time"),
           ("key", "fu_ts_frac", "int", "-", "follow-up telemetry: fractional part of that packet's departure time"),
           ("key", "fu_ts_mode", "int", "-", "follow-up telemetry: timestamping method of the follow-up timestamp"),
           ("key", "fu_reserved", "int", "-", "follow-up telemetry: reserved, 0")])


def module_text():
    L = ["# The ippm module: the fields of the OWAMP, TWAMP and STAMP test packets (RFC 4656, RFC 5357,",
         "# RFC 8762, RFC 8972). Written by tools/gen/ippm-pack.py; do not edit by hand.",
         "module        ippm", "version       0.1.0", "distribution  public",
         'source        "IETF RFC 4656, RFC 5357, RFC 8762 and RFC 8972 (IPPM test packets); restated by goat-transformers"']
    w = max(len(k[1]) for k in KEYS)
    for kind, name, vt, unit, meaning in KEYS:
        if kind == "list":
            L.append('list  %-*s  "%s"' % (w, name, meaning))
        else:
            L.append('key   %-*s  %-4s  %-2s  "%s"' % (w, name, vt, unit, meaning))
    return "\n".join(L) + "\n"


def build(out):
    for name in LAYOUTS:
        out.write("packs/%s/pack.def" % name, pack_text(name))
    out.write("model/ippm.def", module_text())
    return {"ippm": len(LAYOUTS) + 1}


def main(argv=None):
    return genio.vector_main("ippm-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
