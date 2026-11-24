#!/usr/bin/env python3
"""Write the media transport packs and their modules: the MPEG-2 transport stream packet, the SRT
packet, the RIST main profile tunnel packet, the WebRTC data channel establishment protocol, the
RTP packet with its header extension, and the RTP header extension elements of RFC 8285.

Lengths counted in 4-octet units (RTP header extensions, SRT handshake extensions) cannot drive a
`length` block, so their contents are stated as hex fields whose size a `switch` on the length
chooses; this script writes those switches and the other repeated blocks from one statement each.
The vectors are not written here: tools/gen/media-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/media-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "ffmpeg": 'source        "FFmpeg n7.1 (commit b08d7969c550a804a59511c7b83f2dd8cc0499b8), libavformat/mpegts.c (sha256 da1f2f17590ccb7e497060073005cf9746039684e876dd0444be22e21aa7f0a6) and mpegts.h, LGPL-2.1-or-later, https://github.com/FFmpeg/FFmpeg; the transport stream packet header and PCR as the demuxer reads them; layout restated, no code copied"',
    "gst": 'source        "GStreamer 1.26.9 (commit f313fae193089408e278c0dd3450145e5a12307b), subprojects/gst-plugins-bad/gst/mpegtsdemux/mpegtspacketizer.c (sha256 7a85ecd4526f982ad37c6ad30ed471cc3566b475268d8a3752b09d9ba3a3a2d5), LGPL-2.0-or-later, https://github.com/GStreamer/gstreamer; the adaptation field flags, PCR, OPCR, splice countdown, private data and extension as the packetizer reads them; layout restated, no code copied"',
    "srt": 'source        "IETF Internet-Draft draft-sharabayko-srt-01, The SRT Protocol, September 2021, https://www.ietf.org/archive/id/draft-sharabayko-srt-01.txt (sha256 5a8dd79821c44c33b8292b5753213715b1b4293338f74684a01a8ccc57933e3b), IETF Trust (BCP 78); layout restated"',
    "rist": 'source        "Video Services Forum, VSF TR-06-2:2024, Reliable Internet Stream Transport (RIST) Protocol Specification, Main Profile, 2024-06-12, https://static.vsf.tv/download/technical_recommendations/VSF_TR-06-2_2024_06_12.pdf (sha256 ebfc6b470ade396e4be0f83b869f4a13e604b2c05f8934aac00211a4cd82fdab), CC BY-ND 4.0; layout restated, the document not modified"',
    "gre": 'source        "IETF RFC 2784 and RFC 2890 (GRE, key and sequence number); the GRE header fields on the inet keys of gre-header"',
    "dcep": 'source        "IETF RFC 8832, WebRTC Data Channel Establishment Protocol, January 2021, https://www.rfc-editor.org/rfc/rfc8832.txt (sha256 64f9addf6ff135f37c5ff8ec5b9b905ad882d6288400af144425cac3df507df5), IETF Trust (BCP 78); layout restated"',
    "rtp": 'source        "IETF RFC 3550, RTP, July 2003, section 5.1 and 5.3.1, https://www.rfc-editor.org/rfc/rfc3550.txt (sha256 4c210e9434b5b4c029e8536ad8991f3709bc3cbfa0999e951bcb4c2143c539e8); layout restated"',
    "8285": 'source        "IETF RFC 8285, A General Mechanism for RTP Header Extensions, October 2017, https://www.rfc-editor.org/rfc/rfc8285.txt (sha256 e6fc1f0e6638560b6052f08d548b02b0418bb4f7b1f362a5ec340293e673d60a); layout restated"',
}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def head(name, comment, sources, uses):
    L = ["# %s" % c for c in comment] + ["format        %s" % name, "version       0.1.0", "distribution  public"]
    L += [SRC[s] for s in sources]
    L += ["uses          %s" % u for u in uses]
    return L + ["wire          bits", "layout        sequential", "bit_order     msb", ""]


def flag_block(mod, flag, body):
    """A block read when a one-bit flag is 1; an absent flag (an empty adaptation field) reads nothing."""
    return ["switch  %s.%s" % (mod, flag), "  case  1"] + ind(2, body) + ["  else", "end"]


def units_hex(mod, lenkey, contentkey, maxn, bytes_each=4, minus=0):
    """A content whose size is a count of `bytes_each`-octet units (less `minus` octets), as hex."""
    L = ["switch  %s.%s" % (mod, lenkey)]
    for n in range(0, maxn + 1):
        size = n * bytes_each - minus
        if size <= 0:
            L.append("  case  %d" % n)
            continue
        L.append("  case  %d" % n)
        L.append("    " + F(mod, contentkey, size * 8, "hex"))
    L.append("end")
    return L


# ---------------------------------------------------------------- MPEG-2 TS

def mpegts_pack():
    m = "mpegts"
    pcr = lambda p: [F(m, p + "base", 33), F(m, p + "reserved", 6), F(m, p + "extension", 9)]
    af = ([F(m, "discontinuity", 1), F(m, "random_access", 1), F(m, "es_priority", 1), F(m, "pcr_flag", 1),
           F(m, "opcr_flag", 1), F(m, "splicing_point_flag", 1), F(m, "private_data_flag", 1),
           F(m, "extension_flag", 1)] +
          flag_block(m, "pcr_flag", pcr("pcr_")) + flag_block(m, "opcr_flag", pcr("opcr_")) +
          flag_block(m, "splicing_point_flag", [F(m, "splice_countdown", 8, "twos")]) +
          flag_block(m, "private_data_flag", ["length  8  bytes"] + ind(1, octets(m, "private_data")) + ["end"]) +
          flag_block(m, "extension_flag", ["length  8  bytes"] + ind(1, octets(m, "af_extension")) + ["end"]) +
          octets(m, "stuffing"))
    L = head("mpegts-packet", ["MPEG-2 transport stream packet: the 4-octet header, the adaptation field and the payload of one",
                               "188-octet packet. Public. Restated from FFmpeg and GStreamer (LGPL), no code copied. Written by",
                               "tools/gen/media-pack.py; do not edit by hand. pack.md states what is mapped."],
             ["ffmpeg", "gst"], [m])
    L += ["kind    packet", "when    8  71", F(m, "transport_error", 1), F(m, "payload_unit_start", 1),
          F(m, "transport_priority", 1), F(m, "pid", 13), F(m, "scrambling", 2), F(m, "adaptation_field_control", 2),
          F(m, "continuity_counter", 4), "switch  mpegts.adaptation_field_control", "  case  2,3",
          "    length  8  bytes"] + ind(3, af) + ["    end", "  else", "end",
          "switch  mpegts.adaptation_field_control", "  case  1,3"] + ind(2, octets(m, "payload")) + ["  else", "end"]
    return "\n".join(L) + "\n"


MPEGTS_KEYS = [
    ("key", "transport_error", "transport error indicator: 1 when the packet has an uncorrectable error"),
    ("key", "payload_unit_start", "payload unit start indicator: 1 when a PES packet or a PSI section starts in this packet"),
    ("key", "transport_priority", "transport priority"),
    ("key", "pid", "packet identifier, 13 bits: 0 PAT, 1 CAT, 0x1FFF null packets, others by the PMT"),
    ("key", "scrambling", "transport scrambling control: 0 not scrambled"),
    ("key", "adaptation_field_control", "1 payload only, 2 adaptation field only, 3 adaptation field then payload"),
    ("key", "continuity_counter", "continuity counter, 4 bits, per PID"),
    ("key", "discontinuity", "adaptation field: discontinuity indicator"),
    ("key", "random_access", "adaptation field: random access indicator"),
    ("key", "es_priority", "adaptation field: elementary stream priority indicator"),
    ("key", "pcr_flag", "adaptation field: 1 when a PCR follows"),
    ("key", "opcr_flag", "adaptation field: 1 when an original PCR follows"),
    ("key", "splicing_point_flag", "adaptation field: 1 when a splice countdown follows"),
    ("key", "private_data_flag", "adaptation field: 1 when transport private data follows"),
    ("key", "extension_flag", "adaptation field: 1 when an adaptation field extension follows"),
    ("key", "pcr_base", "program clock reference base, 33 bits, in 90 kHz units"),
    ("key", "pcr_reserved", "the six reserved bits between the PCR base and extension"),
    ("key", "pcr_extension", "program clock reference extension, 9 bits, in 27 MHz units (0-299)"),
    ("key", "opcr_base", "original PCR base, 90 kHz units"),
    ("key", "opcr_reserved", "the six reserved bits of the original PCR"),
    ("key", "opcr_extension", "original PCR extension, 27 MHz units"),
    ("key", "splice_countdown", "splice countdown, read as signed"),
    ("list", "private_data", "transport private data, as octets"),
    ("list", "af_extension", "the adaptation field extension after its length (flags and fields), as octets"),
    ("list", "stuffing", "stuffing octets at the end of the adaptation field (0xFF)"),
    ("list", "payload", "the payload: a part of a PES packet or of PSI sections, as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- SRT

def srt_pack():
    s = "srt"
    hs = ([F(s, "hs_version", 32), F(s, "encryption", 16), F(s, "extension_field", 16), F(s, "hs_reserved", 1),
           F(s, "initial_seq", 31), F(s, "mtu", 32), F(s, "flow_window", 32), F(s, "handshake_type", 32),
           F(s, "srt_socket_id", 32), F(s, "syn_cookie", 32), F(s, "peer_ip", 128, "hex"),
           "group  srt.extensions  rest", "  " + F(s, "ext_type", 16), "  switch  srt.ext_type", "    case  1,2",
           "      " + F(s, "ext_length", 16), "      " + F(s, "srt_version", 32), "      " + F(s, "srt_flags", 32),
           "      " + F(s, "receiver_tsbpd_delay", 16), "      " + F(s, "sender_tsbpd_delay", 16), "    else",
           "      " + F(s, "ext_length", 16)] + ind(3, units_hex(s, "ext_length", "ext_content", 63)) + ["  end", "end"])
    words = lambda lst: ["group  srt.%s  rest" % lst, "  " + F(s, "word", 32), "end"]
    L = head("srt-packet", ["SRT packet (draft-sharabayko-srt-01): the data packet and the control packets with the handshake",
                            "and its extensions. Public. Written by tools/gen/media-pack.py; do not edit by hand."],
             ["srt"], [s])
    L += ["kind    data", "when    1  0", "requires  srt.packet_seq  srt.position  srt.in_order  srt.key_flags  srt.retransmitted  srt.message_number  srt.timestamp  srt.dest_socket_id", F(s, "packet_seq", 31), F(s, "position", 2), F(s, "in_order", 1),
          F(s, "key_flags", 2), F(s, "retransmitted", 1), F(s, "message_number", 26), F(s, "timestamp", 32),
          F(s, "dest_socket_id", 32)] + octets(s, "payload")
    L += ["", "kind    control", "when    1  1", "requires  srt.control_type  srt.subtype  srt.type_specific  srt.timestamp  srt.dest_socket_id", F(s, "control_type", 15), F(s, "subtype", 16),
          F(s, "type_specific", 32), F(s, "timestamp", 32), F(s, "dest_socket_id", 32), "switch  srt.control_type",
          "  case  0                       # HANDSHAKE"] + ind(2, hs) + [
          "  case  2,3                     # ACK, NAK: 32-bit words"] + ind(2, words("cif_words")) + [
          "  case  7                       # DROPREQ", "    " + F(s, "first_seq", 32), "    " + F(s, "last_seq", 32),
          "  case  6                       # ACKACK: no CIF", "  else"] + ind(2, octets(s, "cif")) + ["end"]
    return "\n".join(L) + "\n"


SRT_KEYS = [
    ("key", "packet_seq", "data: packet sequence number, 31 bits"),
    ("key", "position", "data: PP, the packet's place in its message: 2 first, 0 middle, 1 last, 3 a single packet"),
    ("key", "in_order", "data: O, 1 when the message must be delivered in order"),
    ("key", "key_flags", "data: KK, 0 not encrypted, 1 even key, 2 odd key"),
    ("key", "retransmitted", "data: R, 1 when the packet is a retransmission"),
    ("key", "message_number", "data: message number, 26 bits"),
    ("key", "timestamp", "microseconds since the socket was created, 32 bits"),
    ("key", "dest_socket_id", "destination socket ID; 0 in a handshake to an unknown peer"),
    ("list", "payload", "data: the payload, as octets"),
    ("key", "control_type", "control: 0 handshake, 1 keep-alive, 2 ACK, 3 NAK, 4 congestion warning, 5 shutdown, 6 ACKACK, 7 drop request, 8 peer error, 0x7FFF user-defined"),
    ("key", "subtype", "control: subtype (user-defined types)"),
    ("key", "type_specific", "control: type-specific information (the ACK number of an ACK and ACKACK, the message number of a drop request, ...)"),
    ("key", "hs_version", "handshake: version, 4 or 5"),
    ("key", "encryption", "handshake: encryption field, 0 none, 2 AES-128, 3 AES-192, 4 AES-256"),
    ("key", "extension_field", "handshake: extension field (the SRT magic 0x4A17 in an induction response; else the flags of the extensions present)"),
    ("key", "hs_reserved", "handshake: the bit before the initial sequence number, 0"),
    ("key", "initial_seq", "handshake: initial packet sequence number"),
    ("key", "mtu", "handshake: maximum transmission unit size, octets"),
    ("key", "flow_window", "handshake: maximum flow window size, packets"),
    ("key", "handshake_type", "handshake: type, 0xFFFFFFFD done, 0xFFFFFFFE agreement, 0xFFFFFFFF conclusion, 0 wavehand, 1 induction"),
    ("key", "srt_socket_id", "handshake: the sender's socket ID"),
    ("key", "syn_cookie", "handshake: SYN cookie"),
    ("key", "peer_ip", "handshake: the peer's IP address, 128 bits as 32 hexadecimal digits (an IPv4 address in the first 32 bits)"),
    ("list", "extensions", "handshake: the extensions, in order"),
    ("key", "ext_type", "handshake extension type: 1 HSREQ, 2 HSRSP, 3 KMREQ, 4 KMRSP, 5 SID, 6 congestion, 7 filter, 8 group"),
    ("key", "ext_length", "handshake extension: length in 4-octet units"),
    ("key", "ext_content", "handshake extension: the content of an extension other than HSREQ and HSRSP, as hexadecimal digits"),
    ("key", "srt_version", "HSREQ, HSRSP: SRT library version"),
    ("key", "srt_flags", "HSREQ, HSRSP: SRT flags (TSBPDSND, TSBPDRCV, CRYPT, TLPKTDROP, PERIODICNAK, REXMITFLG, STREAM, PACKET_FILTER)"),
    ("key", "receiver_tsbpd_delay", "HSREQ, HSRSP: receiver latency, milliseconds"),
    ("key", "sender_tsbpd_delay", "HSREQ, HSRSP: sender latency, milliseconds"),
    ("list", "cif_words", "ACK and NAK: the control information field as 32-bit words (an ACK's last acknowledged sequence number, RTT, RTT variance, buffer, rates; a NAK's loss list)"),
    ("key", "word", "one 32-bit word"),
    ("key", "first_seq", "drop request: first sequence number of the message to drop"),
    ("key", "last_seq", "drop request: last sequence number of the message to drop"),
    ("list", "cif", "the control information field of another control type, as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- RIST main profile

def rist_pack():
    r = "rist"
    reduced = [F(r, "udp_source_port", 16), F(r, "udp_destination_port", 16)] + octets(r, "payload")
    keepalive = ([F(r, "mac_address", 48, "hex")] +
                 [F(r, "cap_" + c, 1) for c in ("x", "r", "b", "a", "p", "e", "l", "n", "d", "t", "v", "j", "f")] +
                 [F(r, "cap_reserved", 3)] + octets(r, "json"))
    L = head("rist-main", ["RIST main profile tunnel packet (VSF TR-06-2:2024): the GRE header with the RIST version, the",
                           "VSF protocol header, reduced overhead data, keep-alive messages and full datagrams. Public.",
                           "Written by tools/gen/media-pack.py; do not edit by hand. pack.md states what is mapped."],
             ["rist", "gre"], ["inet", r])
    L += ["presence  c  1", "field  inet.gre_bit1  1  uint", "presence  ks  2", F(r, "reserved0_high", 5), F(r, "h", 1),
          F(r, "rv", 3), "field  inet.gre_version  3  uint", "field  inet.gre_protocol_type  16  uint", "if  c.1",
          "  field  inet.gre_checksum   16  uint", "  field  inet.gre_reserved1  16  uint", "end", "if  ks.1",
          "  field  inet.gre_key  32  uint", "end", "if  ks.2", "  field  inet.gre_sequence  32  uint", "end",
          "switch  inet.gre_protocol_type", "  case  52448                   # 0xCCE0, the VSF EtherType",
          "    " + F(r, "vsf_protocol_type", 16), "    " + F(r, "vsf_protocol_subtype", 16),
          "    switch  rist.vsf_protocol_subtype", "      case  0                 # reduced overhead"] + ind(4, reduced) + [
          "      case  32768             # keep-alive"] + ind(4, keepalive) + ["      else"] + ind(4, octets(r, "vsf_payload")) + [
          "    end", "  case  34998                   # 0x88B6, reduced overhead, legacy"] + ind(2, reduced) + [
          "  case  34997                   # 0x88B5, keep-alive, legacy"] + ind(2, keepalive) + ["  else"] + ind(2, octets(r, "datagram")) + ["end"]
    return "\n".join(L) + "\n"


RIST_KEYS = [
    ("key", "reserved0_high", "the five high bits of GRE Reserved0 that RIST leaves reserved"),
    ("key", "h", "H: the AES key length of pre-shared key operation, 0 for 128 bits, 1 for 256 bits"),
    ("key", "rv", "RV: the RIST version, 0 TR-06-2:2020, 1 TR-06-2:2021, 2 TR-06-2:2022 and later"),
    ("key", "vsf_protocol_type", "VSF protocol type, 0 for RIST"),
    ("key", "vsf_protocol_subtype", "VSF protocol subtype: 0 reduced overhead data, 0x8000 keep-alive, 0x8001 future nonce announcement"),
    ("key", "udp_source_port", "reduced overhead: the UDP source port of the tunnelled flow"),
    ("key", "udp_destination_port", "reduced overhead: the UDP destination port of the tunnelled flow"),
    ("list", "payload", "reduced overhead: the UDP payload, as octets; ciphertext when a pre-shared key is in use"),
    ("key", "mac_address", "keep-alive: the sender's 48-bit MAC address, 12 hexadecimal digits, its identity in the session"),
    ("key", "cap_x", "keep-alive capability X: more capabilities in the JSON message"),
    ("key", "cap_r", "keep-alive capability R: routing of non-RIST traffic"),
    ("key", "cap_b", "keep-alive capability B: bonding"),
    ("key", "cap_a", "keep-alive capability A: adaptive encoding"),
    ("key", "cap_p", "keep-alive capability P: SMPTE 2022 FEC"),
    ("key", "cap_e", "keep-alive capability E: seamless redundancy switch (SMPTE 2022-7)"),
    ("key", "cap_l", "keep-alive capability L: load sharing"),
    ("key", "cap_n", "keep-alive capability N: NULL packet deletion"),
    ("key", "cap_d", "keep-alive flag D: this is a disconnect message"),
    ("key", "cap_t", "keep-alive flag T: this is a reconnect message"),
    ("key", "cap_v", "keep-alive capability V: reduced overhead mode"),
    ("key", "cap_j", "keep-alive capability J: JSON information"),
    ("key", "cap_f", "keep-alive capability F: on-the-fly pre-shared key passphrase change"),
    ("key", "cap_reserved", "keep-alive: the three reserved capability bits"),
    ("list", "json", "keep-alive: the JSON message payload, as octets"),
    ("list", "vsf_payload", "the payload of another VSF subtype, as octets"),
    ("list", "datagram", "the GRE payload of another protocol type (0x0800: a full IPv4 datagram), as octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- DCEP

def dcep_pack():
    d = "dcep"
    L = head("dcep", ["WebRTC Data Channel Establishment Protocol message (RFC 8832): DATA_CHANNEL_OPEN and",
                      "DATA_CHANNEL_ACK. Public. Written by tools/gen/media-pack.py; do not edit by hand."], ["dcep"], [d])
    L += ["kind    open", "when    8  3  as  dcep.message_type", "requires  dcep.channel_type  dcep.priority  dcep.reliability", F(d, "channel_type", 8), F(d, "priority", 16), F(d, "reliability", 32),
          "count  label_length  16", "count  protocol_length  16", "group  dcep.label  count  @label_length",
          "  " + F(d, "octet", 8), "end", "group  dcep.protocol  count  @protocol_length", "  " + F(d, "octet", 8), "end",
          "", "kind    ack", "when    8  2  as  dcep.message_type"]
    return "\n".join(L) + "\n"


DCEP_KEYS = [
    ("key", "message_type", "message type: 3 DATA_CHANNEL_OPEN, 2 DATA_CHANNEL_ACK"),
    ("key", "channel_type", "channel type: 0x00 reliable, 0x80 reliable unordered, 0x01 / 0x81 partial reliable by retransmissions, 0x02 / 0x82 partial reliable by time"),
    ("key", "priority", "priority of the channel"),
    ("key", "reliability", "reliability parameter: the number of retransmissions or the lifetime in milliseconds, by the channel type"),
    ("list", "label", "the channel's label, as its UTF-8 octets (its length is written from the list)"),
    ("list", "protocol", "the subprotocol, as its UTF-8 octets (its length is written from the list)"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- RTP packet and header extension

def rtp_pack():
    x = "rtpx"
    L = head("rtp-packet", ["RTP packet (RFC 3550): the fixed header on the inet keys of rtp-header, the CSRC list, the header",
                            "extension (profile, length, data) and the payload. Public. Written by tools/gen/media-pack.py."],
             ["rtp"], ["inet", x])
    L += ["field  inet.rtp_version  2  uint", "field  inet.rtp_padding  1  uint", "field  inet.rtp_extension  1  uint",
          "count  csrcs  4", "field  inet.rtp_marker  1  uint", "field  inet.rtp_payload_type  7  uint",
          "field  inet.rtp_sequence  16  uint", "field  inet.rtp_timestamp  32  uint", "field  inet.rtp_ssrc  32  uint",
          "group  inet.rtp_csrcs  count  @csrcs", "  field  inet.rtp_csrc  32  uint", "end",
          "switch  inet.rtp_extension", "  case  1", "    " + F(x, "profile", 16), "    " + F(x, "ext_length", 16)]
    L += ind(2, units_hex(x, "ext_length", "ext_data", 63)) + ["  case  0", "end"] + octets(x, "payload")
    return "\n".join(L) + "\n"


def rtpx_pack():
    x = "rtpx"
    one = (["group  rtpx.elements  rest", "  " + F(x, "id", 4), "  switch  rtpx.id", "    case  0",
            "      " + F(x, "len", 4), "    else", "      " + F(x, "len", 4), "      switch  rtpx.len"] +
           ["        case  %d\n          %s" % (n, F(x, "data", (n + 1) * 8, "hex")) for n in range(16)] +
           ["      end", "  end", "end"])
    two = (["group  rtpx.elements  rest", "  " + F(x, "id", 8), "  switch  rtpx.id", "    case  0", "    else",
            "      length  8  bytes"] + ind(4, octets(x, "element_data")) + ["      end", "  end", "end"])
    L = head("rtp-header-extension", ["RTP header extension (RFC 8285): the profile, the length and the extension elements in the",
                                      "one-byte or the two-byte form. Public. Written by tools/gen/media-pack.py."],
             ["8285"], [x])
    L += [F(x, "profile", 16), F(x, "ext_length", 16), "switch  rtpx.profile", "  case  48862               # 0xBEDE, one-byte form"]
    L += ind(2, "\n".join(one).split("\n"))
    L += ["  case  %s           # 0x1000-0x100F, two-byte form" % ",".join(str(v) for v in range(4096, 4112))]
    L += ind(2, two) + ["  else"] + ind(2, octets(x, "ext_octets")) + ["end"]
    return "\n".join(L) + "\n"


RTPX_KEYS = [
    ("key", "profile", "header extension profile: 0xBEDE (48862) the one-byte form, 0x1000-0x100F the two-byte form (the low four bits are application bits), others profile-specific"),
    ("key", "ext_length", "header extension length in 32-bit words, not counting the profile and length"),
    ("key", "ext_data", "rtp-packet: the header extension data, as hexadecimal digits"),
    ("list", "payload", "rtp-packet: the payload, padding included, as octets"),
    ("list", "elements", "rtp-header-extension: the extension elements and padding octets, in order"),
    ("key", "id", "extension element ID (0 for a padding octet; 15 is reserved in the one-byte form)"),
    ("key", "len", "one-byte form: the element's data length minus one (0 for a padding octet)"),
    ("key", "data", "one-byte form: the element's data, 1 to 16 octets, as hexadecimal digits"),
    ("list", "element_data", "two-byte form: the element's data, 0 to 255 octets"),
    ("list", "ext_octets", "the data of an extension of another profile, as octets"),
    ("key", "octet", "one octet"),
]


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
    out.write("packs/mpegts-packet/pack.def", mpegts_pack())
    out.write("packs/srt-packet/pack.def", srt_pack())
    out.write("packs/rist-main/pack.def", rist_pack())
    out.write("packs/dcep/pack.def", dcep_pack())
    out.write("packs/rtp-packet/pack.def", rtp_pack())
    out.write("packs/rtp-header-extension/pack.def", rtpx_pack())
    out.write("model/mpegts.def", module("mpegts", ["# The mpegts module: the fields of an MPEG-2 transport stream packet. Written by tools/gen/media-pack.py."],
                                         'source        "Restated from FFmpeg libavformat/mpegts.c and GStreamer mpegtspacketizer.c (LGPL); no code copied"', MPEGTS_KEYS))
    out.write("model/srt.def", module("srt", ["# The srt module: the fields of SRT packets (draft-sharabayko-srt-01). Written by tools/gen/media-pack.py."],
                                      'source        "IETF draft-sharabayko-srt-01; restated by goat-transformers"', SRT_KEYS, ["peer_ip", "ext_content"]))
    out.write("model/rist.def", module("rist", ["# The rist module: the RIST main profile fields (VSF TR-06-2:2024). Written by tools/gen/media-pack.py."],
                                       'source        "VSF TR-06-2:2024 (CC BY-ND 4.0); restated by goat-transformers, the document not modified"', RIST_KEYS, ["mac_address"]))
    out.write("model/dcep.def", module("dcep", ["# The dcep module: the fields of DCEP messages (RFC 8832). Written by tools/gen/media-pack.py."],
                                       'source        "IETF RFC 8832; restated by goat-transformers"', DCEP_KEYS))
    out.write("model/rtpx.def", module("rtpx", ["# The rtpx module: RTP header extensions (RFC 3550 section 5.3.1, RFC 8285). Written by tools/gen/media-pack.py."],
                                       'source        "IETF RFC 3550 and RFC 8285; restated by goat-transformers"', RTPX_KEYS, ["ext_data", "data"]))
    return {"media": 11}


def main(argv=None):
    return genio.vector_main("media-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
