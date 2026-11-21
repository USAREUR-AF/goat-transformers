#!/usr/bin/env python3
"""hamdig-vectors: write the vectors of m17-lsf, m17-stream-frame, m17-packet-frame,
dstar-radio-header and dmr-data-header.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of:
- the M17 specification: LSF = DST (6 octets), SRC (6), TYPE (2: four reserved bits, signed stream,
  four-bit CAN, encryption subtype 2, encryption type 2, data type 2, packet/stream 1), META (14),
  CRC (2); META with no encryption by subtype: text (control octet and 13 octets), GNSS (source 4,
  station 4, validity 4, radius 3, bearing 9, latitude 24 and longitude 24 two's complement, altitude
  16, speed 12, 12 reserved bits), extended callsigns (6 + 6 + 2 unused); the M17 CRC (polynomial
  0x5935, initial 0xFFFF, not reflected) computed over the first 28 octets; stream frame = 40-bit LSF
  chunk, 3-bit counter, 5 reserved bits, 16-bit frame number (top bit: last frame), 16 octets of
  stream data; packet frame = 25 octets, end-of-frame bit, 5-bit counter, 2 reserved bits; the M17
  address encoding (base 40 over the alphabet space, A-Z, 0-9, '-', '/', '.') for the callsigns;
- ircDDBGateway: D-STAR header = flags 1-3, RPT2, RPT1, YOUR, MY (8 characters each), MY suffix (4),
  2 checksum octets; flag 1 bits: data, repeater, interrupted, control, urgent, repeater control (3);
- MMDVMHost: DMR data header = octet 0 (group, response requested, two bits, DPF), octet 1,
  destination and source (24 bits each), octets 8 and 9 by DPF, 2 CRC octets.

Inputs: frames built here field by field from values chosen here; no frame is taken from a document
or a capture. The D-STAR and DMR checks are arbitrary octets (the packs do not compute them).
`expect` of a round trip is the input. `model` holds values that were packed.

Usage: python3 -I tools/gen/hamdig-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/hamdig-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_M = "the M17 Protocol Specification"
R_D = "ircDDBGateway HeaderData.cpp and DStarDefines.h"
R_R = "MMDVMHost DMRDataHeader.cpp and DMRDefines.h"
ALPHABET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/."


def vec(pack, name, inp, model=None, error=None, ref="", note=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


def bits(fields):
    acc, n = 0, 0
    for v, w in fields:
        assert 0 <= v < (1 << w), (v, w)
        acc, n = (acc << w) | v, n + w
    assert n % 8 == 0
    return acc.to_bytes(n // 8, "big")


def m17_addr(call):
    v = 0
    for ch in reversed(call):
        v = v * 40 + ALPHABET.index(ch)
    return v.to_bytes(6, "big")


def m17_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x5935) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return struct.pack(">H", crc)


def m17_type(stream, data_type=0, enc=0, sub=0, can=0, signed=0):
    return bits([(0, 4), (signed, 1), (can, 4), (sub, 2), (enc, 2), (data_type, 2), (stream, 1)])


def lsf(dst, src, typ, meta):
    body = m17_addr(dst) + m17_addr(src) + typ + meta
    assert len(body) == 28
    return body + m17_crc(body)


def m17_vectors():
    out = []
    P = "m17-lsf"
    text = bytes([0x11]) + b"HELLO M17    "
    a = lsf("ALL", "N0CALL", m17_type(1, data_type=2), text)
    out.append((P, "01-stream-voice-text-meta-roundtrip.json", vec(P, "stream-voice-text-meta-roundtrip", a,
                {"m17.destination": m17_addr("ALL").hex(), "m17.source": m17_addr("N0CALL").hex(), "m17.packet_stream": "1",
                 "m17.data_type": "2", "m17.encryption_type": "0", "m17.encryption_subtype": "0", "m17.text_control": str(0x11),
                 "m17.text_block": text[1:].hex(), "m17.crc": a[-2:].hex()},
                ref=R_M, note="a voice stream LSF with a one-block text META; the CRC computed over the first 28 octets")))
    gnss = bits([(1, 4), (2, 4), (0b1110, 4), (0, 3), (90, 9), (4194304, 24), ((-2097152) & 0xFFFFFF, 24), (1100, 16), (100, 12), (0, 12)])
    b = lsf("N0CALL", "AB1CDE", m17_type(1, data_type=3, sub=1, can=5), gnss)
    out.append((P, "02-stream-gnss-meta-roundtrip.json", vec(P, "stream-gnss-meta-roundtrip", b,
                {"m17.channel_access_number": "5", "m17.encryption_subtype": "1", "m17.gnss_data_source": "1", "m17.gnss_station_type": "2",
                 "m17.gnss_validity": str(0b1110), "m17.gnss_bearing": "90", "m17.gnss_altitude": "50", "m17.gnss_speed": "50"},
                ref=R_M, note="a voice and data stream with GNSS META: OpenRTX handheld, bearing 90, altitude 50 m, 50 km/h")))
    ext = m17_addr("W1AW") + m17_addr("M17-XXX") + bytes(2)
    c = lsf("W1AW", "RPT1", m17_type(1, data_type=2, sub=2), ext)
    out.append((P, "03-extended-callsign-meta-roundtrip.json", vec(P, "extended-callsign-meta-roundtrip", c,
                {"m17.encryption_subtype": "2", "m17.extended_callsign_1": m17_addr("W1AW").hex(),
                 "m17.extended_callsign_2": m17_addr("M17-XXX").hex()}, ref=R_M, note="extended callsign META from a repeater")))
    d = lsf("ALL", "N0CALL", m17_type(1, data_type=2, enc=2, sub=0), bytes(range(14)))
    out.append((P, "04-aes-meta-as-hex-roundtrip.json", vec(P, "aes-meta-as-hex-roundtrip", d,
                {"m17.encryption_type": "2", "m17.meta": bytes(range(14)).hex()}, ref=R_M, note="AES-128: the META (nonce) as hex")))
    e = lsf("N0CALL", "AB1CDE", m17_type(0), bytes([0x11]) + b"PKT TEST     ")
    out.append((P, "05-packet-mode-lsf-roundtrip.json", vec(P, "packet-mode-lsf-roundtrip", e, {"m17.packet_stream": "0"},
                ref=R_M, note="a packet mode LSF")))
    out.append((P, "06-cut-lsf-is-malformed.json", vec(P, "cut-lsf-is-malformed", a[:29], error="malformed-wire",
                ref=R_M, note="29 of the 30 octets")))
    P = "m17-stream-frame"
    f = a[5:10] + bits([(1, 3), (0, 5), (0, 1), (42, 15)]) + bytes(range(16))
    out.append((P, "01-stream-frame-roundtrip.json", vec(P, "stream-frame-roundtrip", f,
                {"m17.lich_chunk": a[5:10].hex(), "m17.lich_counter": "1", "m17.end_of_stream": "0", "m17.frame_number": "42",
                 "m17.stream_data": bytes(range(16)).hex()}, ref=R_M, note="frame 42 carrying LSF chunk 1 (octets 5 to 9)")))
    g = a[25:30] + bits([(5, 3), (0, 5), (1, 1), (43, 15)]) + bytes(16)
    out.append((P, "02-last-stream-frame-roundtrip.json", vec(P, "last-stream-frame-roundtrip", g,
                {"m17.lich_counter": "5", "m17.end_of_stream": "1", "m17.frame_number": "43"}, ref=R_M, note="the last frame, chunk 5")))
    out.append((P, "03-cut-stream-frame-is-malformed.json", vec(P, "cut-stream-frame-is-malformed", f[:20], error="malformed-wire", ref=R_M)))
    P = "m17-packet-frame"
    h = bytes(range(25)) + bits([(0, 1), (0, 5), (0, 2)])
    out.append((P, "01-first-packet-frame-roundtrip.json", vec(P, "first-packet-frame-roundtrip", h,
                {"m17.end_of_frame": "0", "m17.packet_counter": "0"}, ref=R_M, note="frame 0 of several")))
    i = b"\x05hi\x00\x12\x34" + bytes(19) + bits([(1, 1), (6, 5), (0, 2)])
    out.append((P, "02-last-packet-frame-roundtrip.json", vec(P, "last-packet-frame-roundtrip", i,
                {"m17.end_of_frame": "1", "m17.packet_counter": "6", "m17.packet_chunk": i[:25].hex()},
                ref=R_M, note="the last frame with 6 valid octets, padded with zeros")))
    out.append((P, "03-cut-packet-frame-is-malformed.json", vec(P, "cut-packet-frame-is-malformed", h[:25], error="malformed-wire", ref=R_M)))
    return out


def call8(s, n=8):
    return s.ljust(n).encode("ascii")


def dstar_vectors():
    P = "dstar-radio-header"
    out = []
    a = bytes([0x40, 0x00, 0x00]) + call8("DB0XYZ G") + call8("DB0XYZ B") + call8("CQCQCQ") + call8("DL1ABC") + call8("ID51", 4) + bytes([0x8A, 0x3F])
    out.append(("01-repeater-header-roundtrip.json", vec(P, "repeater-header-roundtrip", a,
                {"dstar.repeater": "1", "dstar.data": "0", "dstar.rpt2_call": "DB0XYZ G", "dstar.rpt1_call": "DB0XYZ B",
                 "dstar.your_call": "CQCQCQ  ", "dstar.my_call": "DL1ABC  ", "dstar.my_call_suffix": "ID51", "dstar.checksum": "8a3f"},
                ref=R_D, note="a call through a repeater to CQCQCQ, with an arbitrary checksum")))
    b = bytes([0x07, 0x00, 0x00]) + call8("DIRECT") + call8("DIRECT") + call8("DL2DEF") + call8("DL1ABC") + call8("    ", 4) + bytes([0x00, 0x00])
    out.append(("02-direct-repeater-control-roundtrip.json", vec(P, "direct-repeater-control-roundtrip", b,
                {"dstar.repeater": "0", "dstar.repeater_control": "7", "dstar.your_call": "DL2DEF  "},
                ref=R_D, note="a direct (simplex) header with the repeater-control value 7")))
    out.append(("03-cut-header-is-malformed.json", vec(P, "cut-header-is-malformed", a[:40], error="malformed-wire", ref=R_D,
                note="40 of the 41 octets")))
    return P, out


def dmr_vectors():
    P = "dmr-data-header"
    out = []
    a = bits([(1, 1), (0, 1), (0, 2), (2, 4), (0, 4), (0, 4), (9, 24), (2621441, 24), (1, 1), (3, 7), (0, 8)]) + bytes([0xAB, 0xCD])
    out.append(("01-unconfirmed-data-roundtrip.json", vec(P, "unconfirmed-data-roundtrip", a,
                {"dmr.group": "1", "dmr.dpf": "2", "dmr.destination_id": "9", "dmr.source_id": "2621441", "dmr.full_message": "1",
                 "dmr.blocks": "3", "dmr.crc": "abcd"}, ref=R_R, note="unconfirmed data to talkgroup 9, three blocks")))
    b = bits([(0, 1), (1, 1), (0, 2), (3, 4), (0, 4), (0, 4), (2621442, 24), (2621441, 24), (1, 1), (5, 7), (1, 1), (4, 3), (0, 4)]) + bytes(2)
    out.append(("02-confirmed-data-roundtrip.json", vec(P, "confirmed-data-roundtrip", b,
                {"dmr.response_requested": "1", "dmr.dpf": "3", "dmr.blocks": "5", "dmr.resync": "1", "dmr.send_sequence": "4"},
                ref=R_R, note="confirmed data, individual, response requested, send sequence 4")))
    c = bits([(1, 1), (0, 1), (0, 2), (0, 4), (0, 4), (0, 4), (9, 24), (2621441, 24), (0, 6), (2, 2), (0, 8)]) + bytes([0x12, 0x34])
    out.append(("03-udt-roundtrip.json", vec(P, "udt-roundtrip", c, {"dmr.dpf": "0", "dmr.udt_blocks_less_one": "2"},
                ref=R_R, note="a unified data transport header, three blocks")))
    d = bits([(0, 1), (0, 1), (0, 2), (15, 4), (0, 4), (0, 4), (0, 24), (0, 24), (0xBEEF, 16)]) + bytes(2)
    out.append(("04-proprietary-as-hex-roundtrip.json", vec(P, "proprietary-as-hex-roundtrip", d, {"dmr.dpf": "15", "dmr.octets8_9": "beef"},
                ref=R_R, note="a proprietary header: octets 8 and 9 as hex")))
    out.append(("05-cut-header-is-malformed.json", vec(P, "cut-header-is-malformed", a[:11], error="malformed-wire", ref=R_R)))
    return P, out


def build(out):
    counts = {}
    for pack, fname, v in m17_vectors():
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = counts.get(pack, 0) + 1
    for pack, vs in (dstar_vectors(), dmr_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("hamdig-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
