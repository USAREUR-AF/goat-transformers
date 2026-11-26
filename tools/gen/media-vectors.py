#!/usr/bin/env python3
"""media-vectors: write the vectors of the media transport packs.

Packs: mpegts-packet, srt-packet, rist-main, dcep, rtp-packet, rtp-header-extension.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of the MPEG-2 transport stream packet as FFmpeg's mpegts.c and
GStreamer's mpegtspacketizer.c read it, draft-sharabayko-srt-01 section 3, VSF TR-06-2:2024
sections 5.1 to 5.6 with RFC 2784 and RFC 2890, RFC 8832 section 5, RFC 3550 sections 5.1 and
5.3.1, and RFC 8285 section 4: every multi-octet field big-endian.

Inputs: packets built here field by field from values chosen here; no packet is taken from a
document or a capture. Addresses are from the documentation ranges of RFC 5737 and RFC 3849.

`expect` of every vector is this program's packing of the decoded values, which for these packets
is the input; `model` holds the values that were packed.

Usage: python3 -I tools/gen/media-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/media-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_TS = "FFmpeg libavformat/mpegts.c and GStreamer mpegtspacketizer.c (the transport stream packet and adaptation field)"
R_SRT = "draft-sharabayko-srt-01 section 3"
R_RIST = "VSF TR-06-2:2024 sections 5.1 to 5.6, RFC 2784 and RFC 2890"
R_DCEP = "RFC 8832 section 5"
R_RTP = "RFC 3550 sections 5.1 and 5.3.1"
R_8285 = "RFC 8285 section 4"


def u8(*v):
    return bytes(v)


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def bits(fields):
    """[(value, width)] packed most significant bit first into whole octets."""
    acc, n = 0, 0
    for v, w in fields:
        assert 0 <= v < (1 << w), (v, w)
        acc, n = (acc << w) | v, n + w
    assert n % 8 == 0, n
    return acc.to_bytes(n // 8, "big")


def vec(pack, name, inp, model=None, error=None, ref=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


# ---------------------------------------------------------------- MPEG-TS

def ts(pid, cc, afc, af=b"", payload=b"", pusi=0, tei=0, prio=0, tsc=0):
    head = bits([(0x47, 8), (tei, 1), (pusi, 1), (prio, 1), (pid, 13), (tsc, 2), (afc, 2), (cc, 4)])
    body = (u8(len(af)) + af if afc in (2, 3) else b"") + (payload if afc in (1, 3) else b"")
    pkt = head + body
    assert len(pkt) == 188, len(pkt)
    return pkt


def pcr(base, ext, reserved=0x3F):
    return bits([(base, 33), (reserved, 6), (ext, 9)])


def mpegts_vectors():
    out = []
    p = "mpegts-packet"
    pay = bytes(range(184))
    m = ts(0x100, 5, 1, payload=pay, pusi=1)
    out.append((p, "01-payload-only-roundtrip.json", vec(p, "payload-only-roundtrip", m,
                {"@kind": "packet", "mpegts.payload_unit_start": "1", "mpegts.pid": "256",
                 "mpegts.adaptation_field_control": "1", "mpegts.continuity_counter": "5", "mpegts.payload.#": "184",
                 "@absent": ["mpegts.pcr_flag"]}, ref=R_TS + "; a packet with payload only, starting a payload unit")))
    af = u8(0x50) + pcr(0x123456789, 150)
    m = ts(0x101, 6, 3, af=af, payload=bytes(176))
    out.append((p, "02-pcr-roundtrip.json", vec(p, "pcr-roundtrip", m,
                {"mpegts.random_access": "1", "mpegts.pcr_flag": "1", "mpegts.pcr_base": str(0x123456789),
                 "mpegts.pcr_reserved": "63", "mpegts.pcr_extension": "150", "mpegts.stuffing.#": "0",
                 "mpegts.payload.#": "176"},
                ref=R_TS + "; an adaptation field with the random access indicator and a PCR, then payload")))
    af = u8(0x00) + b"\xff" * 182
    m = ts(0x1FFF, 0, 2, af=af)
    out.append((p, "03-stuffing-only-roundtrip.json", vec(p, "stuffing-only-roundtrip", m,
                {"mpegts.pid": "8191", "mpegts.adaptation_field_control": "2", "mpegts.pcr_flag": "0",
                 "mpegts.stuffing.#": "182", "mpegts.stuffing[0].mpegts.octet": "255", "@absent": ["mpegts.payload"]},
                ref=R_TS + "; an adaptation field of 183 octets, no flag set, all stuffing, and no payload")))
    af = (u8(0x0F) + pcr(0x000000100, 7) + u8(0xFD) + u8(3) + b"abc" + u8(2, 0x80, 0x00) + b"\xff" * 4)
    m = ts(0x102, 7, 3, af=af, payload=bytes(188 - 4 - 1 - len(af)))
    out.append((p, "04-opcr-splice-private-extension-roundtrip.json", vec(p, "opcr-splice-private-extension-roundtrip", m,
                {"mpegts.opcr_flag": "1", "mpegts.opcr_base": "256", "mpegts.opcr_extension": "7",
                 "mpegts.splice_countdown": "-3", "mpegts.private_data.#": "3", "mpegts.af_extension.#": "2",
                 "mpegts.stuffing.#": "4", "@absent": ["mpegts.pcr_base"]},
                ref=R_TS + "; an adaptation field with an OPCR, a splice countdown of -3, three octets of private data, "
                    "a two-octet extension and stuffing")))
    # 05 (an adaptation field of length 0, then payload) was dropped: its expectation wrote the empty
    # field back with length 0, where ruling 7 of engine-spec 0.8 writes every line of a length block on
    # encode (here the flags octet); an engine found the error, so rule 16 of the brief drops the vector
    bad = bytearray(ts(0x100, 5, 1, payload=pay))
    bad[0] = 0x48
    out.append((p, "06-no-sync-byte-is-no-kind.json", vec(p, "no-sync-byte-is-no-kind", bytes(bad), error="no-kind",
                ref=R_TS + "; a packet whose first octet is not 0x47")))
    m = ts(0x101, 6, 3, af=u8(0x50) + pcr(1, 1), payload=bytes(176))
    out.append((p, "07-truncated-adaptation-field-is-malformed.json", vec(p, "truncated-adaptation-field-is-malformed", m[:8],
                error="malformed-wire", ref=R_TS + "; the PCR packet cut inside its adaptation field")))
    return out


# ---------------------------------------------------------------- SRT

def srt_data(seq, pp, o, kk, r, msgno, tsv, sock, payload):
    return bits([(0, 1), (seq, 31), (pp, 2), (o, 1), (kk, 2), (r, 1), (msgno, 26)]) + u32(tsv, sock) + payload


def srt_ctrl(ctype, sub, spec, tsv, sock, cif=b""):
    return bits([(1, 1), (ctype, 15), (sub, 16)]) + u32(spec, tsv, sock) + cif


def handshake(version, enc, extf, iseq, mtu, win, htype, sockid, cookie, ip, exts=b""):
    return (u32(version) + u16(enc, extf) + u32(iseq, mtu, win, htype, sockid, cookie) +
            ipaddress.IPv4Address(ip).packed + bytes(12) + exts)


def srt_vectors():
    out = []
    p = "srt-packet"
    m = srt_data(1000, 3, 0, 0, 0, 77, 123456, 0x2A3B4C5D, b"payload!")
    out.append((p, "01-data-roundtrip.json", vec(p, "data-roundtrip", m,
                {"@kind": "data", "srt.packet_seq": "1000", "srt.position": "3", "srt.message_number": "77",
                 "srt.timestamp": "123456", "srt.dest_socket_id": str(0x2A3B4C5D), "srt.payload.#": "8"},
                ref=R_SRT + "; a data packet holding a whole message")))
    ind_ = srt_ctrl(0, 0, 0, 100, 0, handshake(4, 0, 2, 5000, 1500, 8192, 1, 0x11111111, 0, "192.0.2.10"))
    out.append((p, "02-handshake-induction-roundtrip.json", vec(p, "handshake-induction-roundtrip", ind_,
                {"@kind": "control", "srt.control_type": "0", "srt.hs_version": "4", "srt.handshake_type": "1",
                 "srt.initial_seq": "5000", "srt.mtu": "1500",
                 "srt.peer_ip": (ipaddress.IPv4Address("192.0.2.10").packed + bytes(12)).hex(), "srt.extensions.#": "0"},
                ref=R_SRT + "; an induction handshake (version 4) without extensions")))
    hsreq = u16(1, 3) + u32(0x010500, 0xBF) + u16(120, 120)
    sid = u16(5, 2) + b"#!::r=ab"
    con = srt_ctrl(0, 0, 0, 200, 0x11111111, handshake(5, 0, 0x0005, 5000, 1500, 8192, 0xFFFFFFFF, 0x22222222,
                                                        0x99887766, "198.51.100.20", hsreq + sid))
    out.append((p, "03-handshake-conclusion-extensions-roundtrip.json", vec(p, "handshake-conclusion-extensions-roundtrip", con,
                {"srt.hs_version": "5", "srt.extension_field": "5", "srt.handshake_type": str(0xFFFFFFFF),
                 "srt.extensions.#": "2", "srt.extensions[0].srt.srt_version": str(0x010500),
                 "srt.extensions[0].srt.srt_flags": str(0xBF), "srt.extensions[0].srt.receiver_tsbpd_delay": "120",
                 "srt.extensions[1].srt.ext_type": "5", "srt.extensions[1].srt.ext_length": "2",
                 "srt.extensions[1].srt.ext_content": b"#!::r=ab".hex()},
                ref=R_SRT + "; a conclusion handshake (version 5) with an HSREQ and a stream ID extension")))
    ack = srt_ctrl(2, 0, 9, 300, 0x22222222, u32(1001, 25000, 5000, 8000, 1000, 50000, 120000))
    out.append((p, "04-ack-roundtrip.json", vec(p, "ack-roundtrip", ack,
                {"srt.control_type": "2", "srt.type_specific": "9", "srt.cif_words.#": "7",
                 "srt.cif_words[0].srt.word": "1001"}, ref=R_SRT + "; a full ACK of seven words")))
    nak = srt_ctrl(3, 0, 0, 310, 0x22222222, u32(0x80000010, 0x00000014))
    out.append((p, "05-nak-roundtrip.json", vec(p, "nak-roundtrip", nak,
                {"srt.control_type": "3", "srt.cif_words.#": "2", "srt.cif_words[0].srt.word": str(0x80000010)},
                ref=R_SRT + "; a NAK reporting the loss of a range of sequence numbers")))
    out.append((p, "06-ackack-roundtrip.json", vec(p, "ackack-roundtrip", srt_ctrl(6, 0, 9, 320, 0x11111111),
                {"srt.control_type": "6", "srt.type_specific": "9"}, ref=R_SRT + "; an ACKACK")))
    out.append((p, "07-drop-request-roundtrip.json", vec(p, "drop-request-roundtrip",
                srt_ctrl(7, 0, 77, 330, 0x22222222, u32(990, 995)),
                {"srt.control_type": "7", "srt.first_seq": "990", "srt.last_seq": "995"},
                ref=R_SRT + "; a message drop request")))
    out.append((p, "08-keepalive-roundtrip.json", vec(p, "keepalive-roundtrip", srt_ctrl(1, 0, 0, 340, 0x22222222),
                {"srt.control_type": "1", "srt.cif.#": "0"}, ref=R_SRT + "; a keep-alive")))
    big = srt_ctrl(0, 0, 0, 350, 0x11111111, handshake(5, 0, 0, 0x80000001, 1500, 8192, 1, 0x11111111, 0,
                                                       "192.0.2.10"))
    out.append((p, "10-handshake-initial-seq-top-bit-roundtrip.json",
                vec(p, "handshake-initial-seq-top-bit-roundtrip", big,
                {"srt.initial_seq": str(0x80000001), "@absent": ["srt.hs_reserved"], "srt.extensions.#": "0"},
                ref=R_SRT + "; a handshake whose initial packet sequence number has its top bit set: one 32-bit "
                    "field (section 3.2.1, figure 5), no reserved bit")))
    out.append((p, "09-truncated-is-malformed.json", vec(p, "truncated-is-malformed", con[:-6], error="malformed-wire",
                ref=R_SRT + "; the conclusion handshake cut inside its stream ID extension")))
    return out


# ---------------------------------------------------------------- RIST

def gre(proto, k=None, s=None, c=None, h=0, rv=2):
    head = bits([(1 if c is not None else 0, 1), (0, 1), (1 if k is not None else 0, 1), (1 if s is not None else 0, 1),
                 (0, 5), (h, 1), (rv, 3), (0, 3), (proto, 16)])
    if c is not None:
        head += u16(c, 0)
    if k is not None:
        head += u32(k)
    if s is not None:
        head += u32(s)
    return head


def rist_vectors():
    out = []
    p = "rist-main"
    rtp = bytes.fromhex("80600001000000640a0b0c0d") + b"media"
    m = gre(0xCCE0, s=41) + u16(0, 0) + u16(5000, 5001) + rtp
    out.append((p, "01-reduced-overhead-roundtrip.json", vec(p, "reduced-overhead-roundtrip", m,
                {"inet.gre_protocol_type": str(0xCCE0), "inet.gre_sequence": "41", "rist.rv": "2",
                 "rist.vsf_protocol_subtype": "0", "rist.udp_source_port": "5000", "rist.udp_destination_port": "5001",
                 "rist.payload.#": str(len(rtp)), "@absent": ["inet.gre_key"]},
                ref=R_RIST + "; a reduced overhead packet with a GRE sequence number, carrying an RTP packet")))
    caps = bits([(0, 1), (1, 1), (0, 1), (0, 1), (0, 1), (0, 1), (0, 1), (1, 1), (0, 1), (0, 1), (1, 1), (1, 1), (1, 1), (0, 3)])
    js = b'{"keepalive":1}'
    m = gre(0xCCE0) + u16(0, 0x8000) + bytes.fromhex("00005e005301") + caps + js
    out.append((p, "02-keep-alive-roundtrip.json", vec(p, "keep-alive-roundtrip", m,
                {"rist.vsf_protocol_subtype": str(0x8000), "rist.mac_address": "00005e005301", "rist.cap_r": "1",
                 "rist.cap_n": "1", "rist.cap_v": "1", "rist.cap_j": "1", "rist.cap_f": "1", "rist.cap_d": "0",
                 "rist.json.#": str(len(js))},
                ref=R_RIST + "; a keep-alive with the capabilities routing, NULL packet deletion, reduced overhead, "
                    "JSON and passphrase change, and a JSON payload")))
    m = gre(0x88B6, rv=0) + u16(6000, 6001) + rtp
    out.append((p, "03-legacy-reduced-overhead-roundtrip.json", vec(p, "legacy-reduced-overhead-roundtrip", m,
                {"inet.gre_protocol_type": str(0x88B6), "rist.rv": "0", "rist.udp_source_port": "6000"},
                ref=R_RIST + "; a reduced overhead packet in the legacy encapsulation (EtherType 0x88B6)")))
    ip = bytes.fromhex("4500001c0001000040110000c0000201c0000202") + bytes(8)
    m = gre(0x0800, k=0x0BADC0DE, s=7, h=1) + ip
    out.append((p, "04-full-datagram-psk-roundtrip.json", vec(p, "full-datagram-psk-roundtrip", m,
                {"rist.h": "1", "inet.gre_key": str(0x0BADC0DE), "inet.gre_sequence": "7", "rist.datagram.#": str(len(ip))},
                ref=R_RIST + "; a full datagram packet with a key (the nonce) and a sequence number, the 256-bit key "
                    "flag set; the datagram kept as octets")))
    m = gre(0x88B5, rv=0) + bytes.fromhex("00005e005302") + bits([(0, 13), (0, 3)])
    out.append((p, "05-legacy-keep-alive-roundtrip.json", vec(p, "legacy-keep-alive-roundtrip", m,
                {"inet.gre_protocol_type": str(0x88B5), "rist.mac_address": "00005e005302", "rist.json.#": "0"},
                ref=R_RIST + "; a keep-alive in the legacy encapsulation (EtherType 0x88B5), no capability, no JSON")))
    out.append((p, "06-truncated-is-malformed.json", vec(p, "truncated-is-malformed", gre(0xCCE0, s=41)[:6],
                error="malformed-wire", ref=R_RIST + "; a GRE header cut inside its sequence number")))
    return out


# ---------------------------------------------------------------- DCEP

def dcep_open(ctype, prio, rel, label, proto):
    return u8(3, ctype) + u16(prio) + u32(rel) + u16(len(label), len(proto)) + label + proto


def dcep_vectors():
    out = []
    p = "dcep"
    m = dcep_open(0x00, 256, 0, b"chat", b"")
    out.append((p, "01-open-reliable-roundtrip.json", vec(p, "open-reliable-roundtrip", m,
                {"@kind": "open", "dcep.channel_type": "0", "dcep.priority": "256", "dcep.label.#": "4",
                 "dcep.label[0].dcep.octet": "99", "dcep.protocol.#": "0"},
                ref=R_DCEP + "; DATA_CHANNEL_OPEN for a reliable channel labelled chat, no subprotocol")))
    m = dcep_open(0x82, 512, 150, b"", b"video")
    out.append((p, "02-open-timed-unordered-roundtrip.json", vec(p, "open-timed-unordered-roundtrip", m,
                {"dcep.channel_type": str(0x82), "dcep.reliability": "150", "dcep.label.#": "0", "dcep.protocol.#": "5"},
                ref=R_DCEP + "; DATA_CHANNEL_OPEN for a partially reliable, unordered channel with a lifetime of 150 ms")))
    out.append((p, "03-ack-roundtrip.json", vec(p, "ack-roundtrip", u8(2), {"@kind": "ack"}, ref=R_DCEP + "; DATA_CHANNEL_ACK")))
    out.append((p, "04-unknown-type-is-no-kind.json", vec(p, "unknown-type-is-no-kind", u8(4), error="no-kind",
                ref=R_DCEP + "; a message of type 4, which RFC 8832 does not define")))
    out.append((p, "05-truncated-is-malformed.json", vec(p, "truncated-is-malformed", dcep_open(0, 256, 0, b"chat", b"")[:-1],
                error="malformed-wire", ref=R_DCEP + "; the first open message without the last octet of its label")))
    return out


# ---------------------------------------------------------------- RTP

def rtp(pt, seq, tsv, ssrc, csrcs=(), ext=None, payload=b"", marker=0, padding=0):
    head = bits([(2, 2), (padding, 1), (1 if ext else 0, 1), (len(csrcs), 4), (marker, 1), (pt, 7)]) + u16(seq) + u32(tsv, ssrc)
    head += b"".join(u32(c) for c in csrcs)
    if ext:
        profile, data = ext
        head += u16(profile, len(data) // 4) + data
    return head + payload


def rtp_vectors():
    out = []
    p = "rtp-packet"
    m = rtp(96, 1000, 90000, 0x0A0B0C0D, csrcs=(0x11111111, 0x22222222), payload=b"frame", marker=1)
    out.append((p, "01-csrcs-roundtrip.json", vec(p, "csrcs-roundtrip", m,
                {"inet.rtp_version": "2", "inet.rtp_marker": "1", "inet.rtp_payload_type": "96",
                 "inet.rtp_sequence": "1000", "inet.rtp_csrcs.#": "2",
                 "inet.rtp_csrcs[1].inet.rtp_csrc": str(0x22222222), "rtpx.payload.#": "5",
                 "@absent": ["rtpx.profile"]},
                ref=R_RTP + "; an RTP packet with two CSRCs and a marker, no extension")))
    extdata = bytes.fromhex("10aa21bbcc0033d1d2d3d400")
    m = rtp(111, 7, 48000, 0x01020304, ext=(0xBEDE, extdata), payload=b"opus" + bytes([0, 0, 0, 4]), padding=1)
    out.append((p, "02-extension-padding-roundtrip.json", vec(p, "extension-padding-roundtrip", m,
                {"inet.rtp_extension": "1", "inet.rtp_padding": "1", "rtpx.profile": str(0xBEDE), "rtpx.ext_length": "3",
                 "rtpx.ext_data": extdata.hex(), "rtpx.payload.#": "8"},
                ref=R_RTP + "; an RTP packet with a header extension of three words and padding (kept in the payload)")))
    out.append((p, "03-truncated-is-malformed.json", vec(p, "truncated-is-malformed",
                rtp(96, 1, 2, 3, csrcs=(1, 2))[:18], error="malformed-wire",
                ref=R_RTP + "; a header announcing two CSRCs that ends inside the second")))
    p = "rtp-header-extension"
    one = u16(0xBEDE, 3) + extdata
    out.append((p, "01-one-byte-form-roundtrip.json", vec(p, "one-byte-form-roundtrip", one,
                {"rtpx.profile": str(0xBEDE), "rtpx.ext_length": "3", "rtpx.elements.#": "5",
                 "rtpx.elements[0].rtpx.id": "1", "rtpx.elements[0].rtpx.len": "0", "rtpx.elements[0].rtpx.data": "aa",
                 "rtpx.elements[1].rtpx.data": "bbcc", "rtpx.elements[2].rtpx.id": "0",
                 "rtpx.elements[3].rtpx.id": "3", "rtpx.elements[3].rtpx.data": "d1d2d3d4", "rtpx.elements[4].rtpx.id": "0"},
                ref=R_8285 + "; the one-byte form: elements of 1, 2 and 4 octets with padding octets between and after")))
    two = u16(0x1002, 2) + u8(1, 3) + b"xyz" + u8(2, 0) + u8(0)
    out.append((p, "02-two-byte-form-roundtrip.json", vec(p, "two-byte-form-roundtrip", two,
                {"rtpx.profile": str(0x1002), "rtpx.elements.#": "3", "rtpx.elements[0].rtpx.element_data.#": "3",
                 "rtpx.elements[1].rtpx.element_data.#": "0", "rtpx.elements[2].rtpx.id": "0"},
                ref=R_8285 + "; the two-byte form with application bits 2: an element of 3 octets, an empty element, a "
                    "padding octet")))
    other = u16(0x0001, 1) + b"\x01\x02\x03\x04"
    out.append((p, "03-other-profile-roundtrip.json", vec(p, "other-profile-roundtrip", other,
                {"rtpx.profile": "1", "rtpx.ext_octets.#": "4"}, ref=R_8285 + "; an extension of another profile, kept as octets")))
    return out


def build_files(out):
    written = {}
    for pack, fname, v in mpegts_vectors() + srt_vectors() + rist_vectors() + dcep_vectors() + rtp_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("media-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
