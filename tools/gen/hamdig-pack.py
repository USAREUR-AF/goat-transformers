#!/usr/bin/env python3
"""Write the amateur digital voice and data packs and their modules:

- m17-lsf, m17-stream-frame, m17-packet-frame: the M17 Link Setup Frame (DST, SRC, TYPE with its
  fields, META by type: text, GNSS position, extended callsigns, or raw; CRC), the Stream Frame
  contents (LICH chunk and counter, frame number with the end bit, stream data) and the Packet Frame
  contents (chunk, end-of-frame bit, counter), all as Type 1 bits before forward error correction.
  Layouts restated from the M17 Protocol Specification (M17_spec.tex).
- dstar-radio-header: the 41-octet D-STAR radio header (three flag octets, four callsigns and the
  short callsign, checksum). Layout restated from ircDDBGateway (Common/HeaderData.cpp,
  DStarDefines.h).
- dmr-data-header: the 12-octet DMR data header after BPTC decoding (group bit, response bit, data
  packet format, destination and source, the format-dependent octets 8 and 9, CRC). Layout restated
  from MMDVMHost (DMRDataHeader.cpp, DMRDefines.h).

The vectors are not written here: tools/gen/hamdig-vectors.py derives them with an encoder of its
own.

Usage: python3 -I tools/gen/hamdig-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

MS = "9ae2874d8bd44e2d32fae85f7650a23f6bcee5d3"
IG = "f5ab9f7c93c6f28147b84a8f9667f6cc4c027eaa"
SRC = {
    "m17": ('source        "M17 Protocol Specification, https://github.com/M17-Project/M17_spec at commit %s, M17_spec.tex, chapters '
            'Data Link Layer (Link Setup, CRC, Stream Frames, Packet Frames) and Application Layer (LSF TYPE and META) (GNU FDL 1.3 or '
            'later, Copyright 2023-2026 M17 Project); layouts restated, no text copied"' % MS),
    "dstar": ('source        "ircDDBGateway, https://github.com/g4klx/ircDDBGateway at commit %s, Common/HeaderData.cpp and '
              'Common/DStarDefines.h (GPL-2.0, Copyright (C) 2010-2014 Jonathan Naylor G4KLX); layout restated, no code copied; the '
              'JARL D-STAR specification not used"' % IG),
}


def dmr_src(sha):
    return ('source        "MMDVMHost, https://github.com/g4klx/MMDVMHost at commit %s, DMRDataHeader.cpp and DMRDefines.h (GPL-2.0, '
            'Copyright (C) 2012 Ian Wraith, 2015-2025 Jonathan Naylor G4KLX, 2026 Adrian Musceac YO8RZZ); layout restated, no code '
            'copied; ETSI TS 102 361 not used"' % sha)


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


def head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", src] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for t, k, d in keys:
        L.append('list  %-*s  "%s"' % (w, k, d) if t == "list" else 'key   %-*s  %-6s  -  "%s"' % (w, k, t, d))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- M17

def m17_lsf():
    m = "m17."
    gnss = [F(m + "gnss_data_source", 4), F(m + "gnss_station_type", 4), F(m + "gnss_validity", 4), F(m + "gnss_radius", 3),
            F(m + "gnss_bearing", 9), F(m + "gnss_latitude", 24, "sscale:90/8388607"), F(m + "gnss_longitude", 24, "sscale:180/8388607"),
            F(m + "gnss_altitude", 16, "uscale:1/2:-500"), F(m + "gnss_speed", 12, "uscale:1/2"), F(m + "gnss_reserved", 12)]
    meta = sw("m17.encryption_type", [("0", sw("m17.encryption_subtype", [
        ("0", [F(m + "text_control", 8), F(m + "text_block", 104, "hex")]),
        ("1", gnss),
        ("2", [F(m + "extended_callsign_1", 48, "hex"), F(m + "extended_callsign_2", 48, "hex"), F(m + "extended_unused", 16, "hex")])],
        [F(m + "meta", 112, "hex")]))], [F(m + "meta", 112, "hex")])
    L = head("m17-lsf", ["M17 Link Setup Frame (Type 1 bits): DST, SRC, TYPE, META by type, CRC. Written by tools/gen/hamdig-pack.py;",
                         "do not edit by hand."], SRC["m17"], ["m17"])
    L += [F(m + "destination", 48, "hex"), F(m + "source", 48, "hex"), F(m + "type_reserved", 4), F(m + "signed_stream", 1),
          F(m + "channel_access_number", 4), F(m + "encryption_subtype", 2), F(m + "encryption_type", 2), F(m + "data_type", 2),
          F(m + "packet_stream", 1)] + meta + [F(m + "crc", 16, "hex")]
    return "\n".join(L) + "\n"


def m17_stream():
    m = "m17."
    L = head("m17-stream-frame", ["M17 Stream Frame contents (Type 1 bits): LICH chunk and counter, frame number, stream data. Written by",
                                  "tools/gen/hamdig-pack.py; do not edit by hand."], SRC["m17"], ["m17"])
    L += [F(m + "lich_chunk", 40, "hex"), F(m + "lich_counter", 3), F(m + "lich_reserved", 5), F(m + "end_of_stream", 1),
          F(m + "frame_number", 15), F(m + "stream_data", 128, "hex")]
    return "\n".join(L) + "\n"


def m17_packet():
    m = "m17."
    L = head("m17-packet-frame", ["M17 Packet Frame contents (Type 1 bits): 25-octet chunk, end-of-frame bit and counter. Written by",
                                  "tools/gen/hamdig-pack.py; do not edit by hand."], SRC["m17"], ["m17"])
    L += [F(m + "packet_chunk", 200, "hex"), F(m + "end_of_frame", 1), F(m + "packet_counter", 5), F(m + "packet_reserved", 2)]
    return "\n".join(L) + "\n"


M17_KEYS = [
    ("string", "destination", "LSF DST: the encoded destination address, 6 octets as hexadecimal digits (base-40 callsign or special identifier)"),
    ("string", "source", "LSF SRC: the encoded source address, 6 octets as hexadecimal digits"),
    ("int", "type_reserved", "LSF TYPE: the four reserved bits"), ("int", "signed_stream", "LSF TYPE: signed stream (stream mode)"),
    ("int", "channel_access_number", "LSF TYPE: channel access number, 0-15"),
    ("int", "encryption_subtype", "LSF TYPE: encryption subtype (the META type when unencrypted: 0 text, 1 GNSS, 2 extended callsign; the key length otherwise)"),
    ("int", "encryption_type", "LSF TYPE: encryption type (0 none, 1 scrambler, 2 AES, 3 other)"),
    ("int", "data_type", "LSF TYPE: data type (stream mode: 1 data, 2 voice, 3 voice and data)"),
    ("int", "packet_stream", "LSF TYPE: 0 packet mode, 1 stream mode"),
    ("int", "text_control", "META text: control octet (block bitmap and block index)"),
    ("string", "text_block", "META text: the 13 text octets as hexadecimal digits (UTF-8, space padded)"),
    ("int", "gnss_data_source", "META GNSS: data source (0 M17 client, 1 OpenRTX, 15 other)"),
    ("int", "gnss_station_type", "META GNSS: station type (0 fixed, 1 mobile, 2 handheld, 15 other)"),
    ("int", "gnss_validity", "META GNSS: validity bits (8 position, 4 altitude, 2 velocity, 1 radius)"),
    ("int", "gnss_radius", "META GNSS: radius code (an estimate of lateral uncertainty from HDOP)"),
    ("int", "gnss_bearing", "META GNSS: bearing, degrees from north"),
    ("float", "gnss_latitude", "META GNSS: latitude, degrees (+-90 at +-8388607), positive north; the datum is not stated"),
    ("float", "gnss_longitude", "META GNSS: longitude, degrees (+-180 at +-8388607), positive east; the datum is not stated"),
    ("float", "gnss_altitude", "META GNSS: altitude, metres (0.5 m steps from -500 m); the reference is not stated"),
    ("float", "gnss_speed", "META GNSS: speed, km/h"), ("int", "gnss_reserved", "META GNSS: the 12 reserved bits"),
    ("string", "extended_callsign_1", "META extended callsign: the first encoded callsign (originator)"),
    ("string", "extended_callsign_2", "META extended callsign: the second encoded callsign (reflector), or zeros"),
    ("string", "extended_unused", "META extended callsign: the two unused octets"),
    ("string", "meta", "META, encrypted or of a reserved type: the 14 octets as hexadecimal digits"),
    ("string", "crc", "LSF CRC (polynomial 0x5935, initial 0xFFFF), as sent, as hexadecimal digits (not computed)"),
    ("string", "lich_chunk", "stream frame: the 40-bit chunk of the LSF, as hexadecimal digits"),
    ("int", "lich_counter", "stream frame: which LSF chunk (0-5)"), ("int", "lich_reserved", "stream frame: the five reserved LICH bits"),
    ("int", "end_of_stream", "stream frame: the frame number's top bit, set in the last frame"),
    ("int", "frame_number", "stream frame: the frame number, 0 to 0x7FFF"),
    ("string", "stream_data", "stream frame: the 16 octets of stream data (Codec 2 speech or data), as hexadecimal digits"),
    ("string", "packet_chunk", "packet frame: the 25-octet chunk of the packet data, as hexadecimal digits"),
    ("int", "end_of_frame", "packet frame: set in the last frame"),
    ("int", "packet_counter", "packet frame: the frame number (end_of_frame 0) or the number of valid octets, 1-25 (end_of_frame 1)"),
    ("int", "packet_reserved", "packet frame: the two reserved bits"),
]


# ---------------------------------------------------------------- D-STAR

def dstar_pack():
    d = "dstar."
    L = head("dstar-radio-header", ["D-STAR radio header: three flag octets, the repeater, your and my callsigns, checksum. Written by",
                                    "tools/gen/hamdig-pack.py; do not edit by hand."], SRC["dstar"], ["dstar"])
    L += [F(d + "data", 1), F(d + "repeater", 1), F(d + "interrupted", 1), F(d + "control_signal", 1), F(d + "urgent", 1),
          F(d + "repeater_control", 3), F(d + "flag2", 8), F(d + "flag3", 8),
          "field  dstar.rpt2_call  64  chars:ascii8", "field  dstar.rpt1_call  64  chars:ascii8", "field  dstar.your_call  64  chars:ascii8",
          "field  dstar.my_call  64  chars:ascii8", "field  dstar.my_call_suffix  32  chars:ascii8", F(d + "checksum", 16, "hex")]
    return "\n".join(L) + "\n"


DSTAR_KEYS = [
    ("int", "data", "flag 1 bit 7: data (not voice)"), ("int", "repeater", "flag 1 bit 6: via a repeater"),
    ("int", "interrupted", "flag 1 bit 5: communication interrupted"), ("int", "control_signal", "flag 1 bit 4: control signal"),
    ("int", "urgent", "flag 1 bit 3: urgent"),
    ("int", "repeater_control", "flag 1 bits 2-0: 7 repeater control, 6 auto reply, 4 resend requested, 3 ACK, 2 no response, 1 relay unavailable"),
    ("int", "flag2", "flag 2"), ("int", "flag3", "flag 3"),
    ("string", "rpt2_call", "RPT2 callsign, 8 characters"), ("string", "rpt1_call", "RPT1 callsign, 8 characters"),
    ("string", "your_call", "YOUR (UR) callsign, 8 characters"), ("string", "my_call", "MY callsign, 8 characters"),
    ("string", "my_call_suffix", "MY callsign suffix, 4 characters"),
    ("string", "checksum", "the CCITT checksum over the 39 octets before it, as sent (not computed)"),
]


# ---------------------------------------------------------------- DMR

def dmr_pack(src):
    r = "dmr."
    by_dpf = sw("dmr.dpf", [
        ("2", [F(r + "full_message", 1), F(r + "blocks", 7), F(r + "octet9", 8)]),
        ("3", [F(r + "full_message", 1), F(r + "blocks", 7), F(r + "resync", 1), F(r + "send_sequence", 3), F(r + "octet9_low", 4)]),
        ("1", [F(r + "octet8_high", 1), F(r + "blocks", 7), F(r + "octet9", 8)]),
        ("13,14", [F(r + "octet8_high6", 6), F(r + "resync", 1), F(r + "full_message", 1), F(r + "octet9", 8)]),
        ("0", [F(r + "octet8_high6", 6), F(r + "udt_blocks_less_one", 2), F(r + "octet9", 8)])],
        [F(r + "octets8_9", 16, "hex")])
    L = head("dmr-data-header", ["DMR data header (12 octets after BPTC decoding): group and response bits, data packet format, addresses,",
                                 "the format's octets 8 and 9, CRC. Written by tools/gen/hamdig-pack.py; do not edit by hand."], src, ["dmr"])
    L += [F(r + "group", 1), F(r + "response_requested", 1), F(r + "octet0_bits54", 2), F(r + "dpf", 4), F(r + "octet1_high", 4),
          F(r + "octet1_low", 4), F(r + "destination_id", 24), F(r + "source_id", 24)] + by_dpf + [F(r + "crc", 16, "hex")]
    return "\n".join(L) + "\n"


DMR_KEYS = [
    ("int", "group", "octet 0 bit 7: group (not individual) destination"), ("int", "response_requested", "octet 0 bit 6: response requested"),
    ("int", "octet0_bits54", "octet 0 bits 5-4 (in raw and defined short data, added to octet1_low for the block count, as the source does)"),
    ("int", "dpf", "data packet format: 0 UDT, 1 response, 2 unconfirmed data, 3 confirmed data, 13 defined short, 14 raw or status/precoded short, 15 proprietary"),
    ("int", "octet1_high", "octet 1, high nibble"), ("int", "octet1_low", "octet 1, low nibble (raw and defined short: the low block count)"),
    ("int", "destination_id", "destination ID (24 bits; not meaningful for proprietary headers)"),
    ("int", "source_id", "source ID (24 bits; not meaningful for proprietary headers)"),
    ("int", "full_message", "unconfirmed and confirmed: octet 8 bit 7, full message; raw and defined short: octet 8 bit 0"),
    ("int", "blocks", "unconfirmed, confirmed, response: blocks to follow"), ("int", "octet9", "octet 9"),
    ("int", "resync", "confirmed: octet 9 bit 7; raw and defined short: octet 8 bit 1"),
    ("int", "send_sequence", "confirmed: octet 9 bits 6-4, send sequence number"), ("int", "octet9_low", "confirmed: octet 9 bits 3-0"),
    ("int", "octet8_high", "response: octet 8 bit 7"), ("int", "octet8_high6", "raw, defined short, UDT: octet 8 bits 7-2"),
    ("int", "udt_blocks_less_one", "UDT: octet 8 bits 1-0, blocks to follow minus one"),
    ("string", "octets8_9", "proprietary or other formats: octets 8 and 9, as hexadecimal digits"),
    ("string", "crc", "the CCITT CRC (with the data header mask applied), as sent (not computed)"),
]


def build(out, mm_sha):
    out.write("packs/m17-lsf/pack.def", m17_lsf())
    out.write("packs/m17-stream-frame/pack.def", m17_stream())
    out.write("packs/m17-packet-frame/pack.def", m17_packet())
    out.write("packs/dstar-radio-header/pack.def", dstar_pack())
    out.write("packs/dmr-data-header/pack.def", dmr_pack(dmr_src(mm_sha)))
    out.write("model/m17.def", module("m17", ["# The m17 module: M17 LSF, stream and packet frame fields. Written by tools/gen/hamdig-pack.py."], SRC["m17"], M17_KEYS))
    out.write("model/dstar.def", module("dstar", ["# The dstar module: D-STAR radio header fields. Written by tools/gen/hamdig-pack.py."], SRC["dstar"], DSTAR_KEYS))
    out.write("model/dmr.def", module("dmr", ["# The dmr module: DMR data header fields. Written by tools/gen/hamdig-pack.py."], dmr_src(mm_sha), DMR_KEYS))
    return {"hamdig": 8}


MM_SHA = "9589fc39fc34ebf9ded7da72a124f427457ca2ea"


def main(argv=None):
    return genio.vector_main("hamdig-pack.py", __doc__, lambda out: build(out, MM_SHA), argv)


if __name__ == "__main__":
    sys.exit(main())
