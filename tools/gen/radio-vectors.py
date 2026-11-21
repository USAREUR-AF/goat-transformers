#!/usr/bin/env python3
"""radio-vectors: write the vectors of the amateur and paging radio packs.

Packs: ax25-frame, kiss-frame, pocsag-batch.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of AX.25 v2.2 (TAPR, 1998) sections 3 and 4, the KISS TNC note
(Chepponis and Karn, 1987) section 4, and Rec. ITU-R M.584-2 Annex 1 sections 1.2 to 1.4. The
POCSAG check bits are computed here from the generator polynomial the Recommendation gives, and the
encoder is checked against the idle codeword it lists.

Inputs: frames built here field by field from values chosen here; no frame is taken from a
document or a capture. Callsigns are N0CALL-style placeholders, not real stations.

`expect` of every vector is this program's packing of the decoded values, which for these frames
is the input; `model` holds values that were packed.

Usage: python3 -I tools/gen/radio-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/radio-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_AX = "AX.25 v2.2 (TAPR 1998) sections 3.12 and 4.2 to 4.3"
R_KISS = "the KISS TNC note (1987) section 4"
R_POC = "Rec. ITU-R M.584-2 Annex 1 sections 1.2 to 1.4"


def u8(*v):
    return bytes(v)


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


# ---------------------------------------------------------------- AX.25

def addr(call, ssid, top, ext, reserved=3):
    """One address subfield: six characters shifted left one bit, then the SSID octet."""
    assert len(call) <= 6
    c = call.ljust(6)
    return bytes(ord(x) << 1 for x in c) + u8((top << 7) | (reserved << 5) | (ssid << 1) | ext)


def frame(dest, src, rpts, control, pid=None, info=b"", dest_c=1, src_c=0):
    """dest and src are (call, ssid); rpts a list of (call, ssid, h)."""
    out = addr(dest[0], dest[1], dest_c, 0) + addr(src[0], src[1], src_c, 0 if rpts else 1)
    for i, (call, ssid, h) in enumerate(rpts):
        out += addr(call, ssid, h, 1 if i == len(rpts) - 1 else 0)
    out += u8(control)
    if pid is not None:
        out += u8(pid)
    return out + info


def call_model(role, call):
    c = call.ljust(6)
    return {"ax25.%s_call_%d" % (role, i + 1): c[i] for i in range(6)}


def ax25_vectors():
    p = "ax25-frame"
    out = []
    info = b"!4903.50N/07201.75W-Test"
    a = frame(("APRS", 0), ("N0CALL", 7), [], 0x03, 0xF0, info)
    m = {**call_model("dest", "APRS"), **call_model("src", "N0CALL"), "ax25.dest_c": "1", "ax25.dest_reserved": "3",
         "ax25.dest_ssid": "0", "ax25.dest_ext": "0", "ax25.src_c": "0", "ax25.src_ssid": "7", "ax25.src_ext": "1",
         "ax25.control": "3", "ax25.pid": str(0xF0), "ax25.info.#": str(len(info))}
    out.append((p, "01-ui-frame-roundtrip.json", vec(p, "ui-frame-roundtrip", a, m,
                ref=R_AX + "; a UI frame with no repeaters, PID 0xF0 and an information field")))
    b = frame(("APRS", 0), ("N0CALL", 9), [("WIDE1", 1, 1), ("WIDE2", 2, 0)], 0x03, 0xF0, b">status")
    out.append((p, "02-two-repeaters-roundtrip.json", vec(p, "two-repeaters-roundtrip", b,
                {**call_model("rpt1", "WIDE1"), **call_model("rpt2", "WIDE2"), "ax25.src_ext": "0", "ax25.rpt1_h": "1",
                 "ax25.rpt1_ssid": "1", "ax25.rpt1_ext": "0", "ax25.rpt2_h": "0", "ax25.rpt2_ssid": "2", "ax25.rpt2_ext": "1",
                 "ax25.info.#": "7"},
                ref=R_AX + "; a UI frame through two repeaters, the first already repeated (H set)")))
    c = frame(("N1ABC", 0), ("N0CALL", 1), [], 0x56, 0xF0, b"hello")
    out.append((p, "03-i-frame-roundtrip.json", vec(p, "i-frame-roundtrip", c,
                {"ax25.control": str(0x56), "ax25.pid": str(0xF0), "ax25.info.#": "5"},
                ref=R_AX + "; an I frame with N(R) 2, P 1 and N(S) 3 (control 0x56)")))
    d = frame(("N1ABC", 0), ("N0CALL", 1), [], 0xA1, dest_c=0, src_c=1)
    out.append((p, "04-rr-response-roundtrip.json", vec(p, "rr-response-roundtrip", d,
                {"ax25.control": str(0xA1), "ax25.dest_c": "0", "ax25.src_c": "1"},
                ref=R_AX + "; an RR supervisory response with N(R) 5 (control 0xA1), no PID or information")))
    e = frame(("N1ABC", 0), ("N0CALL", 1), [], 0x3F)
    out.append((p, "05-sabm-roundtrip.json", vec(p, "sabm-roundtrip", e, {"ax25.control": str(0x3F)},
                ref=R_AX + "; a SABM command with P set (control 0x3F)")))
    f = frame(("N1ABC", 0), ("N0CALL", 1), [], 0xF3, info=b"ping")
    out.append((p, "06-test-frame-roundtrip.json", vec(p, "test-frame-roundtrip", f,
                {"ax25.control": str(0xF3), "ax25.info.#": "4"},
                ref=R_AX + "; a TEST command with P set and an information field, no PID")))
    rp = [("RPT%d" % i, i, 1 if i <= 3 else 0) for i in range(1, 9)]
    g = frame(("APRS", 0), ("N0CALL", 0), rp, 0x03, 0xF0, b"x")
    out.append((p, "07-eight-repeaters-roundtrip.json", vec(p, "eight-repeaters-roundtrip", g,
                {"ax25.rpt8_call_1": "R", "ax25.rpt8_call_4": "8", "ax25.rpt8_ssid": "8", "ax25.rpt8_ext": "1",
                 "ax25.rpt3_h": "1", "ax25.rpt4_h": "0", "ax25.info.#": "1"},
                ref=R_AX + "; the largest address field the pack reads, eight repeaters (the version 2.0 limit; version 2.2 "
                    "allows two)")))
    h = frame(("APRS", 0), ("N0CALL", 0), [(rp[i][0], 0, 0) for i in range(8)] + [("RPT9", 0, 0)], 0x03, 0xF0, b"x")
    out.append((p, "08-nine-repeaters-is-no-kind.json", vec(p, "nine-repeaters-is-no-kind", h, error="no-kind",
                ref=R_AX + "; nine repeaters: the eighth repeater's extension bit is 0")))
    out.append((p, "09-cut-address-is-malformed.json", vec(p, "cut-address-is-malformed", a[:10], error="malformed-wire",
                ref=R_AX + "; the frame of vector 01 cut inside its destination address")))
    return out, a


# ---------------------------------------------------------------- KISS

def kiss_vectors(ax):
    p = "kiss-frame"
    out = []
    out.append((p, "01-data-frame-roundtrip.json", vec(p, "data-frame-roundtrip", u8(0x00) + ax,
                {"kiss.port": "0", "kiss.command": "0", "kiss.data.#": str(len(ax))},
                ref=R_KISS + "; a data frame on port 0 carrying the AX.25 frame of ax25-frame vector 01")))
    out.append((p, "02-data-frame-port-1-roundtrip.json", vec(p, "data-frame-port-1-roundtrip", u8(0x10) + b"\x01\x02\x03",
                {"kiss.port": "1", "kiss.command": "0", "kiss.data.#": "3"}, ref=R_KISS + "; a data frame on port 1")))
    out.append((p, "03-txdelay-roundtrip.json", vec(p, "txdelay-roundtrip", u8(0x01, 50),
                {"kiss.command": "1", "kiss.value": "50"}, ref=R_KISS + "; TXDELAY of 50 (500 ms)")))
    out.append((p, "04-persistence-roundtrip.json", vec(p, "persistence-roundtrip", u8(0x02, 63),
                {"kiss.command": "2", "kiss.value": "63"}, ref=R_KISS + "; persistence P 63")))
    out.append((p, "05-full-duplex-port-2-roundtrip.json", vec(p, "full-duplex-port-2-roundtrip", u8(0x25, 1),
                {"kiss.port": "2", "kiss.command": "5", "kiss.value": "1"}, ref=R_KISS + "; full duplex on port 2")))
    out.append((p, "06-return-roundtrip.json", vec(p, "return-roundtrip", u8(0xFF), {"kiss.port": "15", "kiss.command": "15"},
                ref=R_KISS + "; the Return command (type 0xFF)")))
    out.append((p, "07-set-hardware-roundtrip.json", vec(p, "set-hardware-roundtrip", u8(0x06, 0x12, 0x34),
                {"kiss.command": "6", "kiss.data.#": "2"}, ref=R_KISS + "; SetHardware with two octets")))
    out.append((p, "08-cut-txdelay-is-malformed.json", vec(p, "cut-txdelay-is-malformed", u8(0x01), error="malformed-wire",
                ref=R_KISS + "; TXDELAY without its parameter")))
    return out


# ---------------------------------------------------------------- POCSAG

GEN = 0b11101101001   # x^10 + x^9 + x^8 + x^6 + x^5 + x^3 + 1
SYNC = 0x7CD215D8
IDLE = 0x7A89C197


def codeword(info21):
    rem = info21 << 10
    for bit in range(30, 9, -1):
        if rem & (1 << bit):
            rem ^= GEN << (bit - 10)
    cw31 = (info21 << 10) | rem
    parity = bin(cw31).count("1") & 1
    return (cw31 << 1) | parity


assert codeword(IDLE >> 11) == IDLE, "the encoder does not reproduce the idle codeword"


def address_cw(address18, function):
    return codeword((0 << 20) | (address18 << 2) | function)


def message_cw(bits20):
    return codeword((1 << 20) | bits20)


def numeric(digits):
    """Numeric message bits: each digit's 4 bits sent least significant first, 5 digits a codeword, space (0xC) fill."""
    codes = {str(d): d for d in range(10)}
    codes[" "] = 0xC
    s = digits + " " * (-len(digits) % 5)
    out = []
    for i in range(0, len(s), 5):
        v = 0
        for ch in s[i:i + 5]:
            n = codes[ch]
            r = int("{:04b}".format(n)[::-1], 2)
            v = (v << 4) | r
        out.append(v)
    return out


def batch(cws):
    assert len(cws) == 16
    return struct.pack(">I", SYNC) + b"".join(struct.pack(">I", c) for c in cws)


def pocsag_vectors():
    p = "pocsag-batch"
    out = []
    ident = 1234562
    addr18, frame_no = ident >> 3, ident & 7
    msg = numeric("5551234")
    cws = [IDLE] * 16
    slot = 2 * frame_no
    cws[slot] = address_cw(addr18, 0)
    for i, mb in enumerate(msg):
        cws[slot + 1 + i] = message_cw(mb)
    a = batch(cws)
    a_bits = (cws[slot] >> 1) & 0x3FF
    m = {"pocsag.codewords.#": "16", "pocsag.codewords[%d].pocsag.flag" % slot: "0",
         "pocsag.codewords[%d].pocsag.address" % slot: str(addr18), "pocsag.codewords[%d].pocsag.function" % slot: "0",
         "pocsag.codewords[%d].pocsag.bch" % slot: str(a_bits),
         "pocsag.codewords[%d].pocsag.flag" % (slot + 1): "1",
         "pocsag.codewords[%d].pocsag.message_bits" % (slot + 1): "%05x" % msg[0],
         "pocsag.codewords[0].pocsag.address": str(IDLE >> 13), "pocsag.codewords[0].pocsag.function": str((IDLE >> 11) & 3)}
    assert slot + 1 + len(msg) <= 16
    out.append((p, "01-numeric-page-roundtrip.json", vec(p, "numeric-page-roundtrip", a, m,
                ref=R_POC + "; a batch with the address codeword of identity 1234562 (frame 2) and a two-codeword numeric "
                    "message, idle codewords elsewhere; check bits computed with the Recommendation's polynomial")))
    b = batch([IDLE] * 16)
    out.append((p, "02-idle-batch-roundtrip.json", vec(p, "idle-batch-roundtrip", b,
                {"pocsag.codewords.#": "16", "pocsag.codewords[15].pocsag.flag": "0",
                 "pocsag.codewords[15].pocsag.bch": str((IDLE >> 1) & 0x3FF), "pocsag.codewords[15].pocsag.parity": str(IDLE & 1)},
                ref=R_POC + "; a batch of idle codewords")))
    cws2 = [IDLE] * 16
    cws2[2] = address_cw(1000, 3)
    cws2[3] = message_cw(0x12345)
    cws2[4] = message_cw(0xABCDE)
    c = batch(cws2)
    out.append((p, "03-alphanumeric-function-roundtrip.json", vec(p, "alphanumeric-function-roundtrip", c,
                {"pocsag.codewords[2].pocsag.address": "1000", "pocsag.codewords[2].pocsag.function": "3",
                 "pocsag.codewords[3].pocsag.message_bits": "12345", "pocsag.codewords[4].pocsag.message_bits": "abcde"},
                ref=R_POC + "; an address codeword in frame 1 with function bits 3 and two message codewords whose bits are "
                    "kept as hex")))
    out.append((p, "04-no-sync-is-no-kind.json", vec(p, "no-sync-is-no-kind", struct.pack(">I", IDLE) + b[4:], error="no-kind",
                ref=R_POC + "; a batch whose first codeword is not the synchronization codeword")))
    out.append((p, "05-cut-codeword-is-malformed.json", vec(p, "cut-codeword-is-malformed", b[:6], error="malformed-wire",
                ref=R_POC + "; the synchronization codeword and half a codeword")))
    return out


def build_files(out):
    written = {}
    ax_out, ax = ax25_vectors()
    for pack, fname, v in ax_out + kiss_vectors(ax) + pocsag_vectors():
        assert v["from"] == pack
        out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("radio-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
