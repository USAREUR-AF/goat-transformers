#!/usr/bin/env python3
"""health-vectors: write the vectors of hl7v2-segment and dicom-part10.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of:
- hl7apy v2_5: a segment line is the segment ID and its fields joined by '|'; in MSH the separator
  itself is MSH-1, so MSH-2 (the encoding characters) is the first field after the ID; the field
  numbers of MSH, PID and OBX as hl7apy lists them;
- pydicom: a Part 10 file is a 128-octet preamble, "DICM", then data elements; with explicit VR little
  endian each element is group (2), element (2), VR (two letters), then a 2-octet length for the VRs
  AE AS AT CS DA DS DT FL FD IS LO LT PN SH SL SS ST TM UI UL US, or two reserved octets and a 4-octet
  length for the others, then the value.

Inputs: values chosen here; no message is taken from a document or a capture. The patient and the
identifiers are invented. `expect` of a round trip is the input (the HL7 fields are marked `optional`,
so no trailing separators are added; spec section "Writing a record", step 5). `model` holds values
that were packed.

Usage: python3 -I tools/gen/health-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/health-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_H = "hl7apy v2_5 fields.py and segments.py"
R_D = "pydicom filereader.py and valuerep.py"


def vec(pack, name, inp, model=None, error=None, ref="", note="", text=False):
    v = {"name": name, "from": pack, "to": pack, "input": inp if text else inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp if text else inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


def hl7_vectors():
    P = "hl7v2-segment"
    out = []
    a = "MSH|^~\\&|LAB|HOSP|EHR|HOSP|20250115123000||ORU^R01|MSG00001|P|2.5"
    out.append(("01-msh-roundtrip.json", vec(P, "msh-roundtrip", a,
                {"@kind": "msh", "hl7v2.msh_2_encoding_characters": "^~\\&", "hl7v2.msh_3_sending_application": "LAB",
                 "hl7v2.msh_7_date_time_of_message": "20250115123000", "hl7v2.msh_9_message_type": "ORU^R01",
                 "hl7v2.msh_10_message_control_id": "MSG00001", "hl7v2.msh_11_processing_id": "P", "hl7v2.msh_12_version_id": "2.5"},
                ref=R_H, note="an ORU^R01 header; MSH-2 is the first field after the segment ID", text=True)))
    b = "PID|1||12345^^^HOSP^MR||DOE^JOHN||19700101|M"
    out.append(("02-pid-roundtrip.json", vec(P, "pid-roundtrip", b,
                {"@kind": "pid", "hl7v2.pid_1_set_id_pid": "1", "hl7v2.pid_3_patient_identifier_list": "12345^^^HOSP^MR",
                 "hl7v2.pid_5_patient_name": "DOE^JOHN", "hl7v2.pid_7_date_time_of_birth": "19700101", "hl7v2.pid_8_administrative_sex": "M"},
                ref=R_H, note="an invented patient", text=True)))
    c = "OBX|1|NM|8867-4^Heart rate^LN||72|/min|||||F"
    out.append(("03-obx-roundtrip.json", vec(P, "obx-roundtrip", c,
                {"@kind": "obx", "hl7v2.obx_2_value_type": "NM", "hl7v2.obx_3_observation_identifier": "8867-4^Heart rate^LN",
                 "hl7v2.obx_5_observation_value": "72", "hl7v2.obx_6_units": "/min", "hl7v2.obx_11_observation_result_status": "F"},
                ref=R_H, note="a numeric observation: heart rate 72 per minute", text=True)))
    d = "OBX|2|ST|NOTE^Comment^L||Patient resting~seated||||||P"
    out.append(("04-obx-repetition-roundtrip.json", vec(P, "obx-repetition-roundtrip", d,
                {"hl7v2.obx_5_observation_value": "Patient resting~seated", "hl7v2.obx_11_observation_result_status": "P"},
                ref=R_H, note="a string value with a repetition separator kept in the field", text=True)))
    out.append(("05-other-segment-is-no-kind.json", vec(P, "other-segment-is-no-kind", "EVN|R01|20250115123000", error="no-kind",
                ref=R_H, note="EVN is not one of the three segments", text=True)))
    return P, out


def element(group, elem, vr, value):
    if len(value) % 2:
        raise ValueError("odd value length")
    head = struct.pack("<HH", group, elem) + vr.encode("ascii")
    if vr in "AE AS AT CS DA DS DT FL FD IS LO LT PN SH SL SS ST TM UI UL US".split():
        return head + struct.pack("<H", len(value)) + value
    return head + b"\x00\x00" + struct.pack("<I", len(value)) + value


def dicom_vectors():
    P = "dicom-part10"
    out = []
    ts = b"1.2.840.10008.1.2.1\x00"
    meta = element(0x0002, 0x0010, "UI", ts)
    body = (element(0x0002, 0x0000, "UL", struct.pack("<I", len(meta))) + meta + element(0x0010, 0x0010, "PN", b"DOE^JOHN") +
            element(0x0028, 0x0010, "US", struct.pack("<H", 2)) + element(0x7FE0, 0x0010, "OW", bytes([0x10, 0x00, 0x20, 0x00])))
    a = bytes(128) + b"DICM" + body
    out.append(("01-file-roundtrip.json", vec(P, "file-roundtrip", a,
                {"@kind": "part10", "dicom.preamble": "0" * 256, "dicom.elements.#": "5", "dicom.elements[0].dicom.group": "2", "dicom.elements[0].dicom.vr": "UL",
                 "dicom.elements[1].dicom.vr": "UI", "dicom.elements[1].dicom.value.#": "20", "dicom.elements[2].dicom.group": "16",
                 "dicom.elements[2].dicom.vr": "PN", "dicom.elements[4].dicom.group": str(0x7FE0), "dicom.elements[4].dicom.vr": "OW",
                 "dicom.elements[4].dicom.reserved": "0", "dicom.elements[4].dicom.value.#": "4"},
                ref=R_D, note="file meta (group length, transfer syntax), patient name, rows, and four octets of pixel data under OW")))
    b = bytes(128) + b"DICM" + element(0x0008, 0x0060, "CS", b"MR") + element(0x0018, 0x9087, "FD", struct.pack("<d", 1000.0)) + \
        element(0x0008, 0x0119, "UC", b"LONGCODE")
    out.append(("02-short-and-long-length-vrs-roundtrip.json", vec(P, "short-and-long-length-vrs-roundtrip", b,
                {"dicom.elements.#": "3", "dicom.elements[0].dicom.vr": "CS", "dicom.elements[1].dicom.vr": "FD",
                 "dicom.elements[2].dicom.vr": "UC", "dicom.elements[2].dicom.value.#": "8"},
                ref=R_D, note="CS and FD with 16-bit lengths, UC with the reserved octets and a 32-bit length")))
    out.append(("03-no-dicm-prefix-is-no-kind.json", vec(P, "no-dicm-prefix-is-no-kind", bytes(128) + b"DICX" + body,
                error="no-kind", ref=R_D, note="the prefix after the preamble is not DICM")))
    out.append(("04-cut-element-is-malformed.json", vec(P, "cut-element-is-malformed", a[:-2], error="malformed-wire",
                ref=R_D, note="the last value is two octets short of its length")))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (hl7_vectors(), dicom_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("health-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
