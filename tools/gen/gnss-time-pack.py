#!/usr/bin/env python3
"""Write the GNSS correction transport and timing packs and their modules: the NTRIP source-table
record line, the NTP packet with its extension fields (RFC 5905, RFC 7822, the NTS fields of RFC
8915), the NTS-KE record stream (RFC 8915), and the PTP message (IEEE 1588 as linuxptp lays it out).

The NTP packet and NTS-KE are sequential layouts whose type-length records run to the end of the
message; PTP is a header, a body by message type and suffix TLVs to the message length.
The vectors are not written here: tools/gen/gnss-time-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/gnss-time-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "ntrip": ('source        "BKG, Networked Transport of RTCM via Internet Protocol (Ntrip) Version 1.0 (documentation excerpt, not the '
              'official RTCM document), section 6 and Appendix A, https://igs.bkg.bund.de/root_ftp/NTRIP/documentation/NtripDocumentation.pdf '
              '(sha256 d2399f37643acec3bff35b26cfc873613048a5f65bf4ccb66032eae708d44977), no licence stated; record layouts restated"'),
    "ntp": ('source        "IETF RFC 5905 section 7.3, RFC 7822 section 3 and RFC 8915 section 5, https://www.rfc-editor.org/rfc/rfc8915.txt; '
            'layout restated"'),
    "ntske": 'source        "IETF RFC 8915, Network Time Security for the Network Time Protocol, September 2020, section 4, https://www.rfc-editor.org/rfc/rfc8915.txt; layout restated"',
    "ptp": ('source        "linuxptp v4.4 (commit 0188667308e62b6ac61151193320ec052e2fd023), msg.h (sha256 '
            '4fcb3192f77ca15ab848857f21854bf3ac3d3d849ce47b97b071180cbb387c55), ddt.h and tlv.h, GPL-2.0-or-later, '
            'https://github.com/richardcochran/linuxptp; the IEEE 1588 message layouts as linuxptp packs them; restated, no code copied"'),
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


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def bits_head(name, comment, src, uses):
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
            t = k[3] if len(k) > 3 else ("string" if k[1] in strings else "int")
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], t, k[2]))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- NTRIP

STR = ["mountpoint", "identifier", "format", "format_details", "carrier", "nav_system", "network", "country", "latitude",
       "longitude", "nmea", "solution", "generator", "compr_encryp", "authentication", "fee", "bitrate", "misc"]
CAS = ["host", "port", "identifier", "operator", "nmea", "country", "latitude", "longitude", "fallback_host", "fallback_port", "misc"]
NET = ["identifier", "operator", "authentication", "fee", "web_net", "web_str", "web_reg", "misc"]
INTS = {"carrier", "nmea", "solution", "bitrate", "port", "fallback_port"}


def ntrip_pack():
    T = "ntrip"
    L = ["# NTRIP source-table record, one line per message: STR (data stream), CAS (caster), NET (network) or",
         "# ENDSOURCETABLE. Written by tools/gen/gnss-time-pack.py; do not edit by hand.",
         "format        ntrip-sourcetable-line", "version       0.1.0", "distribution  public", SRC["ntrip"],
         "uses          %s" % T, "wire          text", 'delimiter     ";"', ""]
    for kind, fields in (("STR", STR), ("CAS", CAS), ("NET", NET)):
        L += ["kind  %s" % kind.lower(), "when  0  %s" % kind]
        for i, k in enumerate(fields, start=1):
            key = "%s_%s" % (kind.lower(), k) if k in ("identifier", "operator", "authentication", "fee", "nmea",
                                                       "country", "latitude", "longitude", "misc") else k
            L.append("field  %s.%s  %d  %s" % (T, key, i, "int" if k in INTS else "string"))
        L.append("")
    L += ["kind  end", "when  0  ENDSOURCETABLE"]
    return "\n".join(L) + "\n"


NTRIP_DESC = {
    "mountpoint": "STR: the caster mountpoint (up to 100 characters)", "str_identifier": "STR: source identifier, such as the nearest city",
    "format": "STR: data format (RTCM 2.x, RTCM 3, CMR, RAW, RTCA ...)",
    "format_details": "STR: format details, such as RTCM message types with update periods in parentheses",
    "carrier": "STR: carrier phase in the stream: 0 none, 1 L1, 2 L1 and L2", "nav_system": "STR: navigation system(s) (GPS, GPS+GLONASS ...)",
    "network": "STR: network the stream belongs to", "str_country": "STR: three-letter ISO 3166 country code",
    "str_latitude": "STR: approximate latitude, degrees north, as written", "str_longitude": "STR: approximate longitude, degrees east, as written (0-360 in many tables)",
    "str_nmea": "STR: 1 the client must send an NMEA GGA position, 0 it must not", "solution": "STR: 0 single base, 1 network",
    "generator": "STR: hardware or software generating the stream", "compr_encryp": "STR: compression or encryption applied",
    "str_authentication": "STR: access protection: N none, B basic, D digest", "str_fee": "STR: user fee: N no, Y yes",
    "bitrate": "STR: bit rate of the stream, bits per second", "str_misc": "STR: miscellaneous information (the last field)",
    "host": "CAS: caster host name or IP address", "port": "CAS: caster port", "cas_identifier": "CAS: caster identifier",
    "cas_operator": "CAS: institution operating the caster", "cas_nmea": "CAS: 1 the caster can take an NMEA GGA position from a client",
    "cas_country": "CAS: three-letter country code", "cas_latitude": "CAS: latitude, degrees north, as written",
    "cas_longitude": "CAS: longitude, degrees east, as written", "fallback_host": "CAS: fallback caster address (0.0.0.0 none)",
    "fallback_port": "CAS: fallback caster port (0 none)", "cas_misc": "CAS: miscellaneous information",
    "net_identifier": "NET: network identifier", "net_operator": "NET: institution operating the network",
    "net_authentication": "NET: access protection of the network's streams (N, B, D, or a list)",
    "net_fee": "NET: user fee of the network's streams (N, Y, or a list)", "web_net": "NET: web address for network information",
    "web_str": "NET: web address for stream information", "web_reg": "NET: web or mail address for registration",
    "net_misc": "NET: miscellaneous information",
}


def ntrip_keys():
    order = []
    for kind, fields in (("STR", STR), ("CAS", CAS), ("NET", NET)):
        for k in fields:
            key = "%s_%s" % (kind.lower(), k) if k in ("identifier", "operator", "authentication", "fee", "nmea",
                                                       "country", "latitude", "longitude", "misc") else k
            if key not in [o[1] for o in order]:
                order.append(("key", key, NTRIP_DESC[key], "int" if k in INTS else "string"))
    return order


# ---------------------------------------------------------------- NTP with extension fields

def ntp_pack():
    X = "ntpext"
    L = bits_head("ntp-packet", ["NTP packet (RFC 5905 section 7.3) with its extension fields (RFC 7822), the NTS fields of RFC 8915",
                                 "section 5 laid out. The header is on the inet keys of ntp-header. Written by tools/gen/gnss-time-pack.py."],
                  "ntp", ["inet", X])
    L += ["field  inet.ntp_leap  2  uint", "field  inet.ntp_version  3  uint", "field  inet.ntp_mode  3  uint",
          "field  inet.ntp_stratum  8  uint", "field  inet.ntp_poll  8  twos", "field  inet.ntp_precision  8  twos",
          "field  inet.ntp_root_delay  32  uscale:1/65536", "field  inet.ntp_root_dispersion  32  uscale:1/65536"]
    L += sw("inet.ntp_stratum", [("0", ["field  inet.ntp_kiss_code  32  ascii"]), ("1", ["field  inet.ntp_ref_clock  32  ascii"])],
            ["field  inet.ntp_ref_id  32  uint"])
    for t in ("ref", "org", "rec", "xmt"):
        L += ["field  inet.ntp_%s_ts_sec  32  uint" % t, "field  inet.ntp_%s_ts_frac  32  uint" % t]
    body = sw("ntpext.field_type", [
        ("260", octets(X, "unique_identifier")),
        ("516", octets(X, "cookie")),
        ("772", octets(X, "cookie_placeholder")),
        ("1028", [F(X, "nonce_length", 16), F(X, "ciphertext_length", 16)] + octets(X, "authenticator"))],
        octets(X, "value"))
    L += ["group  ntpext.extensions  rest", "  " + F(X, "field_type", 16), "  length  16  bytes  plus  4"] + ind(2, body) + ["  end", "end"]
    return "\n".join(L) + "\n"


NTPEXT_KEYS = [
    ("list", "extensions", "the extension fields after the header, in order"),
    ("key", "field_type", "extension field type (0x0104 unique identifier, 0x0204 NTS cookie, 0x0304 cookie placeholder, 0x0404 NTS authenticator and encrypted fields)"),
    ("list", "unique_identifier", "unique identifier field: its body, as octets"),
    ("list", "cookie", "NTS cookie field: its body, as octets"),
    ("list", "cookie_placeholder", "NTS cookie placeholder field: its body, as octets"),
    ("key", "nonce_length", "NTS authenticator: nonce length, octets, without padding"),
    ("key", "ciphertext_length", "NTS authenticator: ciphertext length, octets, without padding"),
    ("list", "authenticator", "NTS authenticator: nonce, ciphertext and their padding, as octets"),
    ("list", "value", "an extension field of another type: its body, as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- NTS-KE

def ntske_pack():
    K = "ntske"
    L = bits_head("nts-ke-records", ["NTS Key Establishment records (RFC 8915 section 4): a request or response, the records to the end.",
                                     "Written by tools/gen/gnss-time-pack.py; do not edit by hand."], "ntske", [K])
    u16 = lambda lst, key: ["group  ntske.%s  rest" % lst, "  " + F(K, key, 16), "end"]
    body = sw("ntske.record_type", [
        ("0", []),
        ("1", u16("protocols", "protocol_id")),
        ("2", [F(K, "error_code", 16)]),
        ("3", [F(K, "warning_code", 16)]),
        ("4", u16("aead_algorithms", "aead_id")),
        ("5", octets(K, "cookie")),
        ("6", octets(K, "server")),
        ("7", [F(K, "port", 16)])],
        octets(K, "body"))
    L += ["group  ntske.records  rest", "  " + F(K, "critical", 1), "  " + F(K, "record_type", 15), "  length  16  bytes"] + \
         ind(2, body) + ["  end", "end"]
    return "\n".join(L) + "\n"


NTSKE_KEYS = [
    ("list", "records", "the records, in order (the last is End of Message)"),
    ("key", "critical", "C bit: an unrecognized record of this type is an error"),
    ("key", "record_type", "record type: 0 end of message, 1 next protocol negotiation, 2 error, 3 warning, 4 AEAD algorithm negotiation, 5 new cookie for NTPv4, 6 NTPv4 server negotiation, 7 NTPv4 port negotiation"),
    ("list", "protocols", "next protocol negotiation: the protocol IDs (0 NTPv4)"),
    ("key", "protocol_id", "one protocol ID"),
    ("key", "error_code", "error code: 0 unrecognized critical record, 1 bad request, 2 internal server error"),
    ("key", "warning_code", "warning code"),
    ("list", "aead_algorithms", "AEAD algorithm negotiation: the IANA AEAD numeric identifiers (15 AEAD_AES_SIV_CMAC_256)"),
    ("key", "aead_id", "one AEAD algorithm identifier"),
    ("list", "cookie", "new cookie: its body, as octets"),
    ("list", "server", "NTPv4 server negotiation: the server's address or name, as its ASCII octets"),
    ("key", "port", "NTPv4 port negotiation: the UDP port"),
    ("list", "body", "a record of another type: its body, as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- PTP

P = "ptp"


def ts(prefix):
    return [F(P, prefix + "_seconds", 48), F(P, prefix + "_nanoseconds", 32)]


def port(prefix):
    return [F(P, prefix + "_clock_identity", 64, "hex"), F(P, prefix + "_port_number", 16)]


def ptp_pack():
    L = bits_head("ptp-message", ["PTP (IEEE 1588) message as linuxptp lays it out: the common header, the body by message type, and the",
                                  "suffix TLVs to the message length. Written by tools/gen/gnss-time-pack.py; do not edit by hand."],
                  "ptp", [P])
    L += [F(P, "transport_specific", 4), F(P, "message_type", 4), F(P, "minor_version", 4), F(P, "version", 4),
          "length  16  whole", F(P, "domain_number", 8), F(P, "reserved1", 8),
          F(P, "flags0_other", 5), F(P, "unicast", 1), F(P, "two_step", 1), F(P, "alternate_master", 1),
          F(P, "flags1_reserved", 1), F(P, "sync_uncertain", 1), F(P, "frequency_traceable", 1), F(P, "time_traceable", 1),
          F(P, "ptp_timescale", 1), F(P, "utc_offset_valid", 1), F(P, "leap59", 1), F(P, "leap61", 1),
          F(P, "correction", 64, "twos"), F(P, "reserved2", 32)] + port("source") + \
         [F(P, "sequence_id", 16), F(P, "control", 8), F(P, "log_message_interval", 8, "twos")]
    announce = ts("origin") + [F(P, "current_utc_offset", 16, "twos"), F(P, "announce_reserved", 8), F(P, "gm_priority1", 8),
                               F(P, "gm_clock_class", 8), F(P, "gm_clock_accuracy", 8), F(P, "gm_offset_scaled_log_variance", 16),
                               F(P, "gm_priority2", 8), F(P, "gm_identity", 64, "hex"), F(P, "steps_removed", 16), F(P, "time_source", 8)]
    mgmt = port("target") + [F(P, "starting_boundary_hops", 8), F(P, "boundary_hops", 8), F(P, "management_reserved", 4),
                             F(P, "action", 4), F(P, "management_reserved2", 8)]
    L += sw("ptp.message_type", [
        ("0,1", ts("origin")),
        ("2", ts("origin") + port("reserved")),
        ("3", ts("request_receipt") + port("requesting")),
        ("8", ts("precise_origin")),
        ("9", ts("receive") + port("requesting")),
        ("10", ts("response_origin") + port("requesting")),
        ("11", announce),
        ("12", port("target")),
        ("13", mgmt)])
    tlv = sw("ptp.tlv_type", [
        ("1", [F(P, "management_id", 16)] + octets(P, "tlv_data")),
        ("3,16384,32768", [F(P, "organization_id", 24, "hex"), F(P, "organization_subtype", 24, "hex")] + octets(P, "tlv_data")),
        ("8", ["group  ptp.path_trace  rest", "  " + F(P, "path_clock_identity", 64, "hex"), "end"])],
        octets(P, "tlv_data"))
    L += ["group  ptp.tlvs  rest", "  " + F(P, "tlv_type", 16), "  length  16  bytes"] + ind(2, tlv) + ["  end", "end"]
    return "\n".join(L) + "\n"


def ptp_keys():
    K = [
        ("transport_specific", "transportSpecific (majorSdoId), the high nibble of the first octet"),
        ("message_type", "message type: 0 Sync, 1 Delay_Req, 2 Pdelay_Req, 3 Pdelay_Resp, 8 Follow_Up, 9 Delay_Resp, 10 Pdelay_Resp_Follow_Up, 11 Announce, 12 Signaling, 13 Management"),
        ("minor_version", "minorVersionPTP"), ("version", "versionPTP (2)"), ("domain_number", "domain number"),
        ("reserved1", "the reserved octet after the domain"), ("flags0_other", "the other five bits of the first flag octet"),
        ("unicast", "flag: unicast"), ("two_step", "flag: two-step clock"), ("alternate_master", "flag: alternate master"),
        ("flags1_reserved", "the reserved bit of the second flag octet"), ("sync_uncertain", "flag: synchronization uncertain"),
        ("frequency_traceable", "flag: frequency traceable"), ("time_traceable", "flag: time traceable"),
        ("ptp_timescale", "flag: the PTP timescale (TAI) is used"), ("utc_offset_valid", "flag: currentUtcOffset is valid"),
        ("leap59", "flag: the last minute of the day has 59 seconds"), ("leap61", "flag: the last minute of the day has 61 seconds"),
        ("correction", "correction field, nanoseconds times 2^16, signed"), ("reserved2", "the 32 reserved bits after the correction"),
        ("sequence_id", "sequence ID"), ("control", "control field (deprecated)"),
        ("log_message_interval", "log2 of the message interval, seconds, signed"),
        ("current_utc_offset", "Announce: current UTC offset, seconds (TAI - UTC)"), ("announce_reserved", "Announce: reserved octet"),
        ("gm_priority1", "Announce: grandmaster priority 1"), ("gm_clock_class", "Announce: grandmaster clock class"),
        ("gm_clock_accuracy", "Announce: grandmaster clock accuracy code"),
        ("gm_offset_scaled_log_variance", "Announce: grandmaster offset scaled log variance"),
        ("gm_priority2", "Announce: grandmaster priority 2"), ("steps_removed", "Announce: steps removed from the grandmaster"),
        ("time_source", "Announce: time source code (0x20 GNSS, 0x40 PTP, 0x50 NTP, 0xA0 internal oscillator ...)"),
        ("starting_boundary_hops", "Management: starting boundary hops"), ("boundary_hops", "Management: boundary hops"),
        ("management_reserved", "Management: the reserved nibble"), ("action", "Management action: 0 GET, 1 SET, 2 RESPONSE, 3 COMMAND, 4 ACKNOWLEDGE"),
        ("management_reserved2", "Management: the reserved octet"),
        ("tlv_type", "TLV type (1 management, 2 management error, 3 organization extension, 8 path trace, 0x4000/0x8000 organization extensions ...)"),
        ("management_id", "management TLV: the management ID"), ("organization_id", "organization extension: the organization ID (OUI), as hex"),
        ("organization_subtype", "organization extension: the subtype, as hex"), ("path_clock_identity", "path trace: one clock identity, as hex"),
        ("octet", "one octet"),
    ]
    out = []
    for k, d in K[:23]:
        out.append(("key", k, d))
    for pre, what in (("source", "source port identity"), ("origin", "origin timestamp"), ("reserved", "Pdelay_Req reserved port identity"),
                      ("request_receipt", "request receipt timestamp"), ("requesting", "requesting port identity"),
                      ("precise_origin", "precise origin timestamp"), ("receive", "receive timestamp"),
                      ("response_origin", "response origin timestamp"), ("target", "target port identity")):
        if "timestamp" in what:
            out += [("key", pre + "_seconds", what + ": seconds (48 bits), in the PTP timescale unless the flag says otherwise"),
                    ("key", pre + "_nanoseconds", what + ": nanoseconds")]
        else:
            out += [("key", pre + "_clock_identity", what + ": clock identity, as hex"), ("key", pre + "_port_number", what + ": port number")]
    out += [("key", "gm_identity", "Announce: grandmaster clock identity, as hex")]
    for k, d in K[23:]:
        out.append(("key", k, d))
    out += [("list", "tlvs", "the suffix TLVs, in order"), ("list", "tlv_data", "the rest of a TLV's value, as octets"),
            ("list", "path_trace", "path trace TLV: the clock identities")]
    return out


PTP_STRINGS = ["source_clock_identity", "reserved_clock_identity", "requesting_clock_identity", "target_clock_identity",
               "gm_identity", "organization_id", "organization_subtype", "path_clock_identity"]


def build(out):
    out.write("packs/ntrip-sourcetable-line/pack.def", ntrip_pack())
    out.write("packs/ntp-packet/pack.def", ntp_pack())
    out.write("packs/nts-ke-records/pack.def", ntske_pack())
    out.write("packs/ptp-message/pack.def", ptp_pack())
    out.write("model/ntrip.def", module("ntrip", ["# The ntrip module: NTRIP source-table record fields. Written by tools/gen/gnss-time-pack.py."], "ntrip", ntrip_keys()))
    out.write("model/ntpext.def", module("ntpext", ["# The ntpext module: NTP extension fields (RFC 7822, RFC 8915). Written by tools/gen/gnss-time-pack.py."], "ntp", NTPEXT_KEYS))
    out.write("model/ntske.def", module("ntske", ["# The ntske module: NTS Key Establishment records (RFC 8915). Written by tools/gen/gnss-time-pack.py."], "ntske", NTSKE_KEYS))
    out.write("model/ptp.def", module("ptp", ["# The ptp module: PTP (IEEE 1588) message fields as linuxptp lays them out. Written by tools/gen/gnss-time-pack.py."], "ptp", ptp_keys(), PTP_STRINGS))
    return {"gnss-time": 8}


def main(argv=None):
    return genio.vector_main("gnss-time-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
