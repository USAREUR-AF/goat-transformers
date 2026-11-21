#!/usr/bin/env python3
"""meter2-vectors: write the vectors of mbus-frame, wmbus-frame and dlms-hdlc-frame.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of:
- libmbus: ACK 0xE5; short frame 0x10, C, A, checksum, 0x16; long and control frame 0x68, L, L,
  0x68, C, A, CI, data, checksum, 0x16, with L the octets from C to the last data octet and the
  checksum their sum modulo 256; the variable data header (identification 4 octets BCD low first,
  manufacturer 2, version, medium, access number, status, signature 2); records of DIF (bit 7
  extension, bit 6 storage LSB, bits 5-4 function, bits 3-0 data coding), DIFEs while bit 7 is set,
  VIF and VIFEs likewise, a plain-text VIF 0x7C followed by its length and text, the value by the
  data coding (lengths 0, 1, 2, 3, 4, 4 real, 6, 8, 0, then BCD 1, 2, 3, 4 octets, variable, 6),
  DIF 0x0F/0x1F manufacturer data to the end, DIF 0x2F an idle filler; the fixed data block
  (identification, access, status, two type octets, two 4-octet counters); multi-octet values low
  octet first;
- wmbusmeters wmbus.cc: L, C, manufacturer (2, low first), identification (4), version, device type,
  CI; ELL I (0x8C): CC, ACC; short transport header (0x7A): access number, status, configuration
  (2, low first); long transport header (0x72): identification, manufacturer, version, device type,
  then as the short header;
- Gurux dlms.c: flag 0x7E, frame format 0xA0 with the segmentation bit 0x08 and the top three bits
  of the length in the low bits, then the low octet of the length (the octets from the frame format
  field to the frame check, flags excluded), addresses of 1, 2 or 4 octets each with its low bit set
  on the last, the control field, a 16-bit header check, the information, a 16-bit frame check,
  flag 0x7E.

Inputs: frames built here field by field from values chosen here; no frame is taken from a
document or a capture. The HDLC check values are arbitrary octets (the packs do not compute them).
`expect` of a round trip is the input. `model` holds values that were packed.

Usage: python3 -I tools/gen/meter2-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/meter2-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_M = "libmbus mbus-protocol.h and mbus-protocol.c"
R_W = "wmbusmeters wmbus.cc"
R_D = "Gurux GuruxDLMS.c dlms.c"


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


def le16(v):
    return struct.pack("<H", v)


def le32(v):
    return struct.pack("<I", v)


def bcd_le(digits):
    """'12345678' -> 78 56 34 12."""
    return bytes.fromhex(digits)[::-1]


# ---------------------------------------------------------------- wired M-Bus

def long_frame(c, a, ci, data):
    body = bytes([c, a, ci]) + data
    return bytes([0x68, len(body), len(body), 0x68]) + body + bytes([sum(body) & 0xFF, 0x16])


def short_frame(c, a):
    return bytes([0x10, c, a, (c + a) & 0xFF, 0x16])


def var_header(ident, mfr, version, medium, access, status, sig=0):
    return bcd_le(ident) + le16(mfr) + bytes([version, medium, access, status]) + le16(sig)


def mbus_vectors():
    P = "mbus-frame"
    out = []
    out.append(("01-ack-roundtrip.json", vec(P, "ack-roundtrip", b"\xe5", {"@kind": "ack"}, ref=R_M)))
    a = short_frame(0x5B, 0x05)
    out.append(("02-short-req-ud2-roundtrip.json", vec(P, "short-req-ud2-roundtrip", a,
                {"@kind": "short", "mbus.control_prm": "1", "mbus.control_fcb_acd": "0", "mbus.control_fcv_dfc": "1",
                 "mbus.control_function": "11", "mbus.address": "5", "mbus.checksum": str(0x60)},
                ref=R_M, note="REQ_UD2 (0x5B) to primary address 5")))
    b = long_frame(0x53, 0xFE, 0x50, b"")
    out.append(("03-control-application-reset-roundtrip.json", vec(P, "control-application-reset-roundtrip", b,
                {"@kind": "long", "mbus.ci": str(0x50), "mbus.length_repeat": "3", "mbus.data.#": "0"},
                ref=R_M, note="a control frame (no data): SND_UD with CI 0x50 application reset, to the broadcast address 0xFE")))
    recs = (bytes([0x04, 0x13]) + le32(12345)            # 32-bit integer, VIF 0x13 volume 1e-3 m3
            + bytes([0x82, 0x40, 0x13]) + le16(9876)     # 16-bit integer with a DIFE (storage 0, unit 1), VIF 0x13
            + bytes([0x0C, 0x78]) + bcd_le("12345678")   # 8-digit BCD, VIF 0x78 fabrication number
            + bytes([0x05, 0x2B]) + struct.pack("<f", 1.5)  # 32-bit real, VIF 0x2B power W
            + bytes([0x01, 0xFD, 0x17, 0x00])            # 8-bit integer, VIF 0xFD with VIFE 0x17 (error flags)
            + bytes([0x2F, 0x2F]))                       # idle fillers
    c = long_frame(0x08, 0x05, 0x72, var_header("12345678", 0x4024, 0x01, 0x07, 0x55, 0x00) + recs)
    out.append(("04-variable-data-response-roundtrip.json", vec(P, "variable-data-response-roundtrip", c,
                {"mbus.ci": "114", "mbus.identification": "78563412", "mbus.manufacturer": str(0x4024), "mbus.medium": "7",
                 "mbus.access_number": str(0x55), "mbus.records.#": "7",
                 "mbus.records[0].mbus.data_field": "4", "mbus.records[0].mbus.vif": str(0x13), "mbus.records[0].mbus.value": "12345",
                 "mbus.records[1].mbus.dif_extension": "1", "mbus.records[1].mbus.difes.#": "1",
                 "mbus.records[1].mbus.difes[0].mbus.dife_unit": "1", "mbus.records[1].mbus.value": "9876",
                 "mbus.records[2].mbus.value_bcd": "78563412", "mbus.records[3].mbus.value_real": "1.5",
                 "mbus.records[4].mbus.vif_extension": "1", "mbus.records[4].mbus.vifes[0].mbus.vife": str(0x17),
                 "mbus.records[5].mbus.function_field": "2", "mbus.records[5].mbus.data_field": "15"},
                ref=R_M, note="RSP_UD with the variable data header and five records (integer, integer with a DIFE, BCD, real, VIF with a VIFE), then two idle fillers")))
    recs2 = (bytes([0x0D, 0x7C, 0x03]) + b"lit" + bytes([0x04]) + b"abcd"  # plain-text VIF, LVAR of 4 characters
             + bytes([0x0F]) + bytes([0xDE, 0xAD]))                          # manufacturer data to the end
    d = long_frame(0x08, 0x05, 0x72, var_header("00000001", 0x4024, 0x01, 0x07, 0x56, 0x00) + recs2)
    out.append(("05-plain-text-vif-and-manufacturer-data-roundtrip.json", vec(P, "plain-text-vif-and-manufacturer-data-roundtrip", d,
                {"mbus.records.#": "2", "mbus.records[0].mbus.vif": "124", "mbus.records[0].mbus.vif_text.#": "3",
                 "mbus.records[0].mbus.value_lvar.#": "4", "mbus.records[1].mbus.manufacturer_data.#": "2"},
                ref=R_M, note="a plain-text VIF with a variable-length value, then DIF 0x0F manufacturer data")))
    e = long_frame(0x08, 0x05, 0x73, bcd_le("12345678") + bytes([0x0A, 0x00, 0xE9, 0x7E]) + le32(1) + bcd_le("00000135"))
    out.append(("06-fixed-data-response-roundtrip.json", vec(P, "fixed-data-response-roundtrip", e,
                {"mbus.ci": "115", "mbus.identification": "78563412", "mbus.access_number": "10", "mbus.counter1_type": str(0xE9),
                 "mbus.counter2_type": str(0x7E), "mbus.counter1": "01000000", "mbus.counter2": "35010000"},
                ref=R_M, note="a fixed data response with two counters")))
    out.append(("07-other-start-is-no-kind.json", vec(P, "other-start-is-no-kind", bytes([0x69, 3, 3, 0x69]), error="no-kind",
                ref=R_M, note="0x69 is not a start character")))
    out.append(("08-cut-long-frame-is-malformed.json", vec(P, "cut-long-frame-is-malformed", c[:20], error="malformed-wire",
                ref=R_M, note="the frame stops inside the variable data header")))
    return P, out


# ---------------------------------------------------------------- wireless M-Bus

def wmbus(c, mfr, ident, version, dtype, rest):
    body = bytes([c]) + le16(mfr) + bcd_le(ident) + bytes([version, dtype]) + rest
    return bytes([len(body)]) + body


def wmbus_vectors():
    P = "wmbus-frame"
    out = []
    apl = bytes([0x04, 0x13]) + le32(4321)
    a = wmbus(0x44, 0x2C2D, "12345678", 0x1B, 0x16, bytes([0x7A, 0x20, 0x00]) + le16(0x0000) + apl)
    out.append(("01-short-transport-header-roundtrip.json", vec(P, "short-transport-header-roundtrip", a,
                {"wmbus.control": str(0x44), "wmbus.manufacturer": str(0x2C2D), "wmbus.identification": "78563412",
                 "wmbus.version": str(0x1B), "wmbus.device_type": str(0x16), "wmbus.ci": "122", "wmbus.access_number": str(0x20),
                 "wmbus.configuration": "0", "wmbus.application_data.#": "6"},
                ref=R_W, note="SND_NR with a short transport header, no encryption, one record as application data")))
    b = wmbus(0x44, 0x2C2D, "12345678", 0x1B, 0x16,
              bytes([0x72]) + bcd_le("87654321") + le16(0x4024) + bytes([0x01, 0x07, 0x21, 0x00]) + le16(0x0510) + bytes(16))
    out.append(("02-long-transport-header-encrypted-roundtrip.json", vec(P, "long-transport-header-encrypted-roundtrip", b,
                {"wmbus.ci": "114", "wmbus.tpl_identification": "21436587", "wmbus.tpl_manufacturer": str(0x4024),
                 "wmbus.configuration": str(0x0510), "wmbus.application_data.#": "16"},
                ref=R_W, note="a long transport header (a different meter behind the link address), security mode 5, one encrypted block")))
    c = wmbus(0x44, 0x2C2D, "12345678", 0x1B, 0x16, bytes([0x8C, 0x20, 0x21, 0x7A, 0x21, 0x00]) + le16(0) + apl)
    out.append(("03-ell-then-short-header-roundtrip.json", vec(P, "ell-then-short-header-roundtrip", c,
                {"wmbus.ci": "140", "wmbus.ell_cc": str(0x20), "wmbus.ell_acc": str(0x21), "wmbus.ell_next_ci": "122",
                 "wmbus.access_number": str(0x21)},
                ref=R_W, note="an extended link layer I followed by a short transport header")))
    d = wmbus(0x46, 0x2C2D, "12345678", 0x1B, 0x16, bytes([0x78]) + apl)
    out.append(("04-no-header-as-octets-roundtrip.json", vec(P, "no-header-as-octets-roundtrip", d,
                {"wmbus.control": str(0x46), "wmbus.ci": str(0x78), "wmbus.application_data.#": "6"},
                ref=R_W, note="CI 0x78 (no transport header): the application data follows directly")))
    out.append(("05-cut-frame-is-malformed.json", vec(P, "cut-frame-is-malformed", a[:-1], error="malformed-wire",
                ref=R_W, note="the length states one octet more than the input holds")))
    return P, out


# ---------------------------------------------------------------- DLMS HDLC

def hdlc(dest, src, control, hcs, info=b"", fcs=b"", seg=0):
    inner = dest + src + bytes([control]) + hcs + info + fcs
    length = 2 + len(inner)
    fmt = (0xA << 12) | (seg << 11) | length
    return b"\x7e" + struct.pack(">H", fmt) + inner + b"\x7e"


def dlms_vectors():
    P = "dlms-hdlc-frame"
    out = []
    a = hdlc(bytes([0x03]), bytes([0x21]), 0x93, bytes([0xAB, 0xCD]))
    out.append(("01-snrm-without-information-roundtrip.json", vec(P, "snrm-without-information-roundtrip", a,
                {"dlmshdlc.frame_type": "10", "dlmshdlc.segmentation": "0", "dlmshdlc.destination_part1": "1",
                 "dlmshdlc.destination_last1": "1", "dlmshdlc.source_part1": str(0x10), "dlmshdlc.source_last1": "1",
                 "dlmshdlc.control": str(0x93), "dlmshdlc.header_check": "abcd", "dlmshdlc.information_and_fcs.#": "0"},
                ref=R_D, note="an SNRM from client 16 to server 1 (one-octet addresses), no information: the 16-bit check is the frame check")))
    info = bytes([0xE6, 0xE6, 0x00, 0x60, 0x1D])
    b = hdlc(bytes([0x00, 0x02, 0x00, 0x23]), bytes([0x21]), 0x10, bytes([0x12, 0x34]),
             info, bytes([0x56, 0x78]))
    out.append(("02-i-frame-four-octet-server-address-roundtrip.json", vec(P, "i-frame-four-octet-server-address-roundtrip", b,
                {"dlmshdlc.destination_part1": "0", "dlmshdlc.destination_last1": "0", "dlmshdlc.destination_part2": "1",
                 "dlmshdlc.destination_part4": str(0x11), "dlmshdlc.destination_last4": "1", "dlmshdlc.control": str(0x10),
                 "dlmshdlc.information_and_fcs.#": str(len(info) + 2)},
                ref=R_D, note="an I frame to a four-octet server address (upper 1, lower 17) with an information field and the frame check")))
    c = hdlc(bytes([0x02, 0x23]), bytes([0x41]), 0x32, bytes([0x9A, 0xBC]), bytes(range(10)), bytes([0xDE, 0xF0]), seg=1)
    out.append(("03-segmented-two-octet-address-roundtrip.json", vec(P, "segmented-two-octet-address-roundtrip", c,
                {"dlmshdlc.segmentation": "1", "dlmshdlc.destination_part1": "1", "dlmshdlc.destination_last1": "0",
                 "dlmshdlc.destination_part2": str(0x11), "dlmshdlc.destination_last2": "1", "dlmshdlc.source_part1": str(0x20)},
                ref=R_D, note="a segment (segmentation bit set) to a two-octet server address")))
    out.append(("04-no-opening-flag-is-no-kind.json", vec(P, "no-opening-flag-is-no-kind", a[1:], error="no-kind",
                ref=R_D, note="the frame does not begin with the flag 0x7E")))
    out.append(("05-cut-frame-is-malformed.json", vec(P, "cut-frame-is-malformed", b[:-3], error="malformed-wire",
                ref=R_D, note="the length states more octets than the input holds")))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (mbus_vectors(), wmbus_vectors(), dlms_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("meter2-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
