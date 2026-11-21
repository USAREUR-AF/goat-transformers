#!/usr/bin/env python3
"""j1939-vectors: write the vectors of j1939-frame.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of:
- Linux include/uapi/linux/can.h: can_id is a 32-bit value whose bit 31 is the extended frame
  flag, bit 30 the RTR flag, bit 29 the error flag and bits 28-0 the extended identifier; the
  message here holds it little-endian, as struct can_frame does on a little-endian host;
- Linux Documentation/networking/j1939.rst and python-can-j1939 message_id.py: the identifier is
  priority (3 bits, bits 28-26), the PGN (18 bits: EDP, DP, PF, PS) and the source address (low 8
  bits); PF below 240 makes PS a destination address, otherwise a group extension;
- python-can-j1939: Request data is the requested PGN in three octets, low first (controller_
  application.py); the NAME is a 64-bit value sent low octet first, identity number in bits 0-20,
  manufacturer code 21-31, ECU instance 32-34, function instance 35-39, function 40-47, reserved
  48, vehicle system 49-55, its instance 56-59, industry group 60-62, arbitrary address capable 63
  (name.py); TP.CM is the control byte (16 RTS, 17 CTS, 19 EOMA, 32 BAM, 255 abort) and its fields,
  then the PGN in three octets (j1939_21.py); TP.DT is the sequence number and seven octets; the
  acknowledgement is control, group function, two 0xFF, the address, the PGN; DM1 is two octets of
  lamp and flash pairs (protect, amber, red, malfunction from the low bits up) and DTCs of four
  octets, a 32-bit value low octet first with the SPN's low 16 bits, the FMI in bits 16-20, the
  SPN's high 3 bits in 21-23, the occurrence count in 24-30 and the conversion method in 31; a
  frame with one DTC is padded with 0xFF 0xFF (diagnostic_messages.py).

Inputs: frames built here field by field from values chosen here; no frame is taken from a
document or a capture. `expect` of a round trip is the input. `model` holds values that were
packed.

Usage: python3 -I tools/gen/j1939-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/j1939-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_ID = "Linux can.h and j1939.rst, python-can-j1939 message_id.py"
R_TP = "python-can-j1939 j1939_21.py"
R_NM = "python-can-j1939 name.py"
R_DM = "python-can-j1939 diagnostic_messages.py"
P = "j1939-frame"


def can_id(prio, pf, ps, sa, dp=0, edp=0, eff=1, rtr=0, err=0):
    v = (eff << 31) | (rtr << 30) | (err << 29) | (prio << 26) | (edp << 25) | (dp << 24) | (pf << 16) | (ps << 8) | sa
    return struct.pack("<I", v)


def pgn3(p):
    return struct.pack("<I", p)[:3]


def name(identity, mfr, ecu, fi, fn, vs, vsi, ig, aac, res=0):
    v = (identity | (mfr << 21) | (ecu << 32) | (fi << 35) | (fn << 40) | (res << 48) | (vs << 49) | (vsi << 56) | (ig << 60) | (aac << 63))
    return struct.pack("<Q", v)


def dtc(spn, fmi, oc, cm=0):
    return struct.pack("<I", (spn & 0xFFFF) | ((spn >> 16) << 21) | (fmi << 16) | (oc << 24) | (cm << 31))


def lamps(pl, awl, rsl, mil, fpl=3, fawl=3, frsl=3, fmil=3):
    return bytes([pl | (awl << 2) | (rsl << 4) | (mil << 6), fpl | (fawl << 2) | (frsl << 4) | (fmil << 6)])


def vec(name_, inp, model=None, error=None, ref="", note=""):
    v = {"name": name_, "from": P, "to": P, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


def vectors():
    out = []
    a = can_id(6, 0xEA, 0xFF, 0xF9) + pgn3(60928)
    out.append(("01-request-address-claim-roundtrip.json", vec("request-address-claim-roundtrip", a,
                {"j1939.priority": "6", "j1939.pdu_format": str(0xEA), "j1939.pdu_specific": "255", "j1939.source_address": str(0xF9),
                 "j1939.can_eff_flag": "1", "j1939.requested_pgn": "60928"},
                ref=R_ID + " and controller_application.py", note="a global request (PS 255) for Address Claimed from address 0xF9")))
    b = can_id(6, 0xEE, 0xFF, 0x00) + name(123456, 1234, 1, 2, 0, 1, 0, 1, 1)
    out.append(("02-address-claimed-roundtrip.json", vec("address-claimed-roundtrip", b,
                {"j1939.pdu_format": str(0xEE), "j1939.name_identity_number": "123456", "j1939.name_manufacturer_code": "1234",
                 "j1939.name_ecu_instance": "1", "j1939.name_function_instance": "2", "j1939.name_function": "0",
                 "j1939.name_vehicle_system": "1", "j1939.name_vehicle_system_instance": "0", "j1939.name_industry_group": "1",
                 "j1939.name_arbitrary_address_capable": "1"},
                ref=R_ID + " and " + R_NM, note="Address Claimed by address 0 with a NAME of chosen values")))
    c = can_id(7, 0xEC, 0x17, 0x00) + bytes([16]) + struct.pack("<H", 20) + bytes([3, 255]) + pgn3(65226)
    out.append(("03-tp-cm-rts-roundtrip.json", vec("tp-cm-rts-roundtrip", c,
                {"j1939.pdu_specific": str(0x17), "j1939.tp_control": "16", "j1939.tp_message_size": "20", "j1939.tp_total_packets": "3",
                 "j1939.tp_max_packets": "255", "j1939.tp_pgn": "65226"},
                ref=R_TP, note="RTS to address 0x17 for a 20-octet DM1 in three packets")))
    d = can_id(7, 0xEC, 0x00, 0x17) + bytes([17, 3, 1, 0xFF, 0xFF]) + pgn3(65226)
    out.append(("04-tp-cm-cts-roundtrip.json", vec("tp-cm-cts-roundtrip", d,
                {"j1939.tp_control": "17", "j1939.tp_packets": "3", "j1939.tp_next_packet": "1", "j1939.tp_reserved": "65535"},
                ref=R_TP, note="CTS: three packets from number 1")))
    e = can_id(7, 0xEC, 0x00, 0x17) + bytes([19]) + struct.pack("<H", 20) + bytes([3, 0xFF]) + pgn3(65226)
    out.append(("05-tp-cm-eoma-roundtrip.json", vec("tp-cm-eoma-roundtrip", e, {"j1939.tp_control": "19", "j1939.tp_message_size": "20"},
                ref=R_TP, note="end of message acknowledgement")))
    f = can_id(7, 0xEC, 0xFF, 0x00) + bytes([32]) + struct.pack("<H", 14) + bytes([2, 0xFF]) + pgn3(65226)
    out.append(("06-tp-cm-bam-roundtrip.json", vec("tp-cm-bam-roundtrip", f,
                {"j1939.pdu_specific": "255", "j1939.tp_control": "32", "j1939.tp_total_packets": "2"},
                ref=R_TP, note="a broadcast announce message for 14 octets in two packets")))
    g = can_id(7, 0xEC, 0x00, 0x17) + bytes([255, 3, 0xFF, 0xFF, 0xFF]) + pgn3(65226)
    out.append(("07-tp-cm-abort-roundtrip.json", vec("tp-cm-abort-roundtrip", g,
                {"j1939.tp_control": "255", "j1939.tp_abort_reason": "3", "j1939.tp_reserved": str(0xFFFFFF)},
                ref=R_TP, note="connection abort for a timeout")))
    h = can_id(7, 0xEB, 0xFF, 0x00) + bytes([1, 0x04, 0xFF, 0x6E, 0x00, 0x03, 0x01, 0x6E])
    out.append(("08-tp-dt-roundtrip.json", vec("tp-dt-roundtrip", h,
                {"j1939.pdu_format": str(0xEB), "j1939.tp_sequence_number": "1", "j1939.data.#": "7"},
                ref=R_TP, note="the first data transfer packet of the BAM")))
    i = can_id(6, 0xE8, 0xFF, 0x00) + bytes([1, 0, 0xFF, 0xFF, 0xF9]) + pgn3(65242)
    out.append(("09-acknowledgement-nack-roundtrip.json", vec("acknowledgement-nack-roundtrip", i,
                {"j1939.pdu_format": str(0xE8), "j1939.ack_control": "1", "j1939.ack_group_function": "0", "j1939.ack_reserved": "65535",
                 "j1939.ack_address": str(0xF9), "j1939.ack_pgn": "65242"},
                ref=R_TP, note="a NACK to address 0xF9 for PGN 65242")))
    j = can_id(6, 0xFE, 0xCA, 0x00) + lamps(0, 1, 0, 0) + dtc(110, 3, 1) + b"\xff\xff"
    out.append(("10-dm1-one-dtc-roundtrip.json", vec("dm1-one-dtc-roundtrip", j,
                {"j1939.pdu_format": "254", "j1939.pdu_specific": "202", "j1939.amber_warning_lamp": "1", "j1939.protect_lamp_flash": "3",
                 "j1939.dtcs.#": "2", "j1939.dtcs[0].j1939.spn_low": "110", "j1939.dtcs[0].j1939.fmi": "3", "j1939.dtcs[0].j1939.spn_high": "0",
                 "j1939.dtcs[0].j1939.occurrence_count": "1", "j1939.dtcs[1].j1939.spn_low": "65535"},
                ref=R_DM, note="DM1 in one frame: amber lamp on, SPN 110 FMI 3, the 0xFF 0xFF padding")))
    k = can_id(6, 0xFE, 0xCA, 0x00) + lamps(1, 1, 0, 0, 1, 3) + dtc(110, 3, 1) + dtc(520192, 31, 126)
    out.append(("11-dm1-two-dtcs-reassembled-roundtrip.json", vec("dm1-two-dtcs-reassembled-roundtrip", k,
                {"j1939.protect_lamp": "1", "j1939.protect_lamp_flash": "1", "j1939.dtcs.#": "2",
                 "j1939.dtcs[1].j1939.spn_low": str(520192 & 0xFFFF), "j1939.dtcs[1].j1939.spn_high": str(520192 >> 16),
                 "j1939.dtcs[1].j1939.fmi": "31", "j1939.dtcs[1].j1939.occurrence_count": "126"},
                ref=R_DM, note="the reassembled data of a DM1 with two DTCs, one with an SPN above 65535")))
    m = can_id(3, 0xF0, 0x04, 0x00) + bytes([0xF0, 0x7D, 0x7D, 0x00, 0x00, 0x00, 0xF0, 0x7D])
    out.append(("12-pdu2-other-pgn-as-octets-roundtrip.json", vec("pdu2-other-pgn-as-octets-roundtrip", m,
                {"j1939.priority": "3", "j1939.pdu_format": str(0xF0), "j1939.pdu_specific": "4", "j1939.data.#": "8"},
                ref=R_ID, note="PGN 61444 (PF 0xF0, group extension 4), its data kept as octets")))
    n = can_id(6, 0xEA, 0x00, 0x00, dp=1) + pgn3(0)
    out.append(("13-data-page-1-as-octets-roundtrip.json", vec("data-page-1-as-octets-roundtrip", n,
                {"j1939.data_page": "1", "j1939.data.#": "3"}, ref=R_ID, note="data page 1: the page-0 layouts do not apply")))
    out.append(("14-cut-name-is-malformed.json", vec("cut-name-is-malformed", b[:-1], error="malformed-wire",
                ref=R_NM, note="the NAME is seven octets")))
    return out


def build(out):
    vs = vectors()
    for fname, v in vs:
        out.write("packs/%s/vectors/%s" % (P, fname), json.dumps(v, indent=2) + "\n")
    return {P: len(vs)}


def main(argv=None):
    return genio.vector_main("j1939-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
