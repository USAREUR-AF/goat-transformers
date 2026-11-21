#!/usr/bin/env python3
"""vehnet-vectors: write the vectors of isotp-frame, uds-message and doip-message.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of:
- python-can-isotp (class PDU): the high half of the first octet is the frame type; single frame:
  the low half is the length, or 0 and the next octet is the length; first frame: 12 bits of
  length, or 0 and a 32-bit length; consecutive frame: the low half is the sequence number;
  flow control: the low half is the flow status, then block size and STmin; data follows;
- python-udsoncan: the service ID; for services with a subfunction, bit 7 suppresses the positive
  response and the low 7 bits are the subfunction; routine control: a 16-bit routine ID after the
  subfunction; read data by identifier: 16-bit identifiers; write: a 16-bit identifier and the
  record; positive response ID = request ID + 0x40; responses echo the subfunction; the session
  control response carries 16-bit P2 and P2*; negative response: 0x7F, the request ID, the code;
- Wireshark packet-doip.c: version, inverse version, 16-bit payload type, 32-bit payload length;
  the payload fields of each type at the offsets given there. Every integer big-endian.

Inputs: messages built here field by field from values chosen here; no message is taken from a
document or a capture. The VIN is invented (17 characters of the allowed set).

`expect` of a round trip is this program's packing of the decoded values, which for these
messages is the input, except where noted: a DoIP vehicle announcement without the sync status
is written back with a zero octet for it, because encode writes every line of a length block, an
absent one as zero bits (ruling 7 of 0.8 of the specification).

Usage: python3 -I tools/gen/vehnet-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/vehnet-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_I = "python-can-isotp isotp/protocol.py"
R_U = "python-udsoncan Request.py, Response.py and the service modules"
R_D = "Wireshark packet-doip.c"


def vec(pack, name, inp, model=None, error=None, ref="", expect=None, note=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = (expect if expect is not None else inp).hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


def be16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def be32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


# ---------------------------------------------------------------- ISO-TP

def isotp_vectors():
    P = "isotp-frame"
    out = []
    a = bytes([0x03, 0x22, 0xF1, 0x90]) + bytes([0xCC] * 4)
    out.append(("01-single-frame-roundtrip.json", vec(P, "single-frame-roundtrip", a,
                {"@kind": "single-frame", "isotp.data.#": "3", "isotp.padding.#": "4"},
                ref=R_I, note="a single frame of three octets padded to eight with 0xCC")))
    payload = bytes(range(1, 21))
    b = bytes([0x00, len(payload)]) + payload + bytes([0xAA] * 2)
    out.append(("02-single-frame-escape-roundtrip.json", vec(P, "single-frame-escape-roundtrip", b,
                {"@kind": "single-frame-escape", "isotp.data.#": "20", "isotp.padding.#": "2"},
                ref=R_I, note="a CAN FD single frame with the escape length (20 octets) in a 24-octet frame")))
    c = bytes([0x10, 0x14, 0x62, 0xF1, 0x90, 0x57, 0x30, 0x4C])
    out.append(("03-first-frame-roundtrip.json", vec(P, "first-frame-roundtrip", c,
                {"@kind": "first-frame", "isotp.message_length": "20", "isotp.data.#": "6"},
                ref=R_I, note="a first frame announcing a 20-octet message")))
    d = bytes([0x10, 0x00]) + be32(5000) + bytes([0xAB, 0xCD])
    out.append(("04-first-frame-escape-roundtrip.json", vec(P, "first-frame-escape-roundtrip", d,
                {"@kind": "first-frame-escape", "isotp.message_length": "5000", "isotp.data.#": "2"},
                ref=R_I, note="a first frame with the escape value and a 32-bit length of 5000")))
    e = bytes([0x21, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x31])
    out.append(("05-consecutive-frame-roundtrip.json", vec(P, "consecutive-frame-roundtrip", e,
                {"@kind": "consecutive-frame", "isotp.sequence_number": "1", "isotp.data.#": "7"},
                ref=R_I, note="consecutive frame number 1")))
    f = bytes([0x30, 0x08, 0xF3]) + bytes([0x55] * 5)
    out.append(("06-flow-control-roundtrip.json", vec(P, "flow-control-roundtrip", f,
                {"@kind": "flow-control", "isotp.flow_status": "0", "isotp.block_size": "8", "isotp.st_min": str(0xF3),
                 "isotp.padding.#": "5"},
                ref=R_I, note="continue to send, block size 8, STmin 300 microseconds")))
    out.append(("07-frame-type-4-is-no-kind.json", vec(P, "frame-type-4-is-no-kind", bytes([0x40, 0, 0, 0, 0, 0, 0, 0]), error="no-kind",
                ref=R_I, note="frame type 4 is not defined")))
    out.append(("08-single-frame-longer-than-frame-is-malformed.json", vec(P, "single-frame-longer-than-frame-is-malformed",
                bytes([0x07, 1, 2, 3]), error="malformed-wire", ref=R_I, note="a single frame stating seven octets with three present")))
    return P, out


# ---------------------------------------------------------------- UDS

def uds_vectors():
    P = "uds-message"
    out = []
    a = bytes([0x10, 0x03])
    out.append(("01-session-control-request-roundtrip.json", vec(P, "session-control-request-roundtrip", a,
                {"uds.sid": "16", "uds.suppress_positive_response": "0", "uds.subfunction": "3", "uds.data.#": "0"},
                ref=R_U, note="extended diagnostic session")))
    b = bytes([0x50, 0x03]) + be16(50, 500)
    out.append(("02-session-control-response-roundtrip.json", vec(P, "session-control-response-roundtrip", b,
                {"uds.sid": "80", "uds.session_echo": "3", "uds.session_parameter_record.#": "4"},
                ref=R_U, note="P2 50 ms, P2* 5000 ms")))
    c = bytes([0x3E, 0x80])
    out.append(("03-tester-present-suppressed-roundtrip.json", vec(P, "tester-present-suppressed-roundtrip", c,
                {"uds.sid": "62", "uds.suppress_positive_response": "1", "uds.subfunction": "0"},
                ref=R_U, note="tester present with the positive response suppressed")))
    d = bytes([0x22]) + be16(0xF190, 0xF18C)
    out.append(("04-read-data-by-identifier-request-roundtrip.json", vec(P, "read-data-by-identifier-request-roundtrip", d,
                {"uds.dids.#": "2", "uds.dids[0].uds.did": str(0xF190), "uds.dids[1].uds.did": str(0xF18C)},
                ref=R_U, note="two identifiers, the VIN and the serial number")))
    e = bytes([0x62]) + be16(0xF190) + b"W0L000051T2123456"
    out.append(("05-read-data-by-identifier-response-roundtrip.json", vec(P, "read-data-by-identifier-response-roundtrip", e,
                {"uds.sid": "98", "uds.data_identifier": str(0xF190), "uds.data_record.#": "17"},
                ref=R_U, note="the VIN identifier and its 17 octets")))
    f = bytes([0x2E]) + be16(0x0101) + bytes([0x12, 0x34])
    out.append(("06-write-data-by-identifier-request-roundtrip.json", vec(P, "write-data-by-identifier-request-roundtrip", f,
                {"uds.data_identifier": str(0x0101), "uds.data_record.#": "2"}, ref=R_U)))
    g = bytes([0x67, 0x01, 0xDE, 0xAD, 0xBE, 0xEF])
    out.append(("07-security-access-seed-response-roundtrip.json", vec(P, "security-access-seed-response-roundtrip", g,
                {"uds.security_level_echo": "1", "uds.security_data.#": "4"}, ref=R_U, note="a 4-octet seed for level 1")))
    h = bytes([0x31, 0x01]) + be16(0xFF00) + bytes([0x01])
    out.append(("08-routine-control-request-roundtrip.json", vec(P, "routine-control-request-roundtrip", h,
                {"uds.subfunction": "1", "uds.routine_id": str(0xFF00), "uds.routine_option.#": "1"},
                ref=R_U, note="start routine 0xFF00 with one option octet")))
    i = bytes([0x71, 0x01]) + be16(0xFF00) + bytes([0x00])
    out.append(("09-routine-control-response-roundtrip.json", vec(P, "routine-control-response-roundtrip", i,
                {"uds.control_type_echo": "1", "uds.routine_id": str(0xFF00), "uds.routine_status.#": "1"}, ref=R_U)))
    j = bytes([0x7F, 0x27, 0x35])
    out.append(("10-negative-response-roundtrip.json", vec(P, "negative-response-roundtrip", j,
                {"uds.sid": "127", "uds.rejected_sid": "39", "uds.nrc": str(0x35)}, ref=R_U, note="security access rejected: invalid key")))
    k = bytes([0x11, 0x81])
    out.append(("11-ecu-reset-suppressed-roundtrip.json", vec(P, "ecu-reset-suppressed-roundtrip", k,
                {"uds.sid": "17", "uds.suppress_positive_response": "1", "uds.subfunction": "1"}, ref=R_U, note="hard reset, response suppressed")))
    m = bytes([0x50, 0x01])
    out.append(("12-session-response-without-timing-roundtrip.json", vec(P, "session-response-without-timing-roundtrip", m,
                {"uds.session_echo": "1", "uds.session_parameter_record.#": "0"}, ref=R_U,
                note="a response in the form before the 2013 edition, with no session parameter record")))
    n = bytes([0x19, 0x02, 0xFF])
    out.append(("13-other-service-as-octets-roundtrip.json", vec(P, "other-service-as-octets-roundtrip", n,
                {"uds.sid": str(0x19), "uds.data.#": "2"}, ref=R_U, note="a service the pack does not lay out (0x19) keeps its octets")))
    out.append(("14-cut-routine-request-is-malformed.json", vec(P, "cut-routine-request-is-malformed", bytes([0x31, 0x01, 0xFF]),
                error="malformed-wire", ref=R_U, note="the routine identifier is cut")))
    return P, out


# ---------------------------------------------------------------- DoIP

def doip(ptype, payload, version=2):
    return bytes([version, version ^ 0xFF]) + be16(ptype) + be32(len(payload)) + payload


VIN = b"W0L000051T2123456"
EID = bytes.fromhex("00005e0053af")


def doip_vectors():
    P = "doip-message"
    out = []
    a = doip(1, b"", version=0xFF)
    out.append(("01-vehicle-identification-request-roundtrip.json", vec(P, "vehicle-identification-request-roundtrip", a,
                {"doip.version": "255", "doip.inverse_version": "0", "doip.payload_type": "1"},
                ref=R_D, note="a vehicle identification request with the default version 0xFF")))
    b = doip(4, VIN + be16(0x1001) + EID + EID + bytes([0x00, 0x00]))
    out.append(("02-vehicle-announcement-roundtrip.json", vec(P, "vehicle-announcement-roundtrip", b,
                {"doip.payload_type": "4", "doip.vin": VIN.decode(), "doip.logical_address": str(0x1001), "doip.eid": EID.hex(),
                 "doip.gid": EID.hex(), "doip.further_action": "0", "doip.sync_status": "0"},
                ref=R_D, note="a vehicle announcement with the sync status")))
    c = doip(5, be16(0x0E80) + bytes([0x00]) + be32(0))
    out.append(("03-routing-activation-request-roundtrip.json", vec(P, "routing-activation-request-roundtrip", c,
                {"doip.payload_type": "5", "doip.source_address": str(0x0E80), "doip.activation_type": "0", "doip.reserved_iso": "0",
                 "doip.reserved_oem.#": "0"},
                ref=R_D, note="routing activation, version 2, default activation, no OEM field")))
    d = doip(5, be16(0x0E80) + be16(1) + be32(0) + be32(0x12345678), version=1)
    out.append(("04-routing-activation-request-v1-oem-roundtrip.json", vec(P, "routing-activation-request-v1-oem-roundtrip", d,
                {"doip.version": "1", "doip.activation_type": "1", "doip.reserved_oem.#": "4"},
                ref=R_D, note="version 1: a 16-bit activation type, and the OEM field present")))
    e = doip(6, be16(0x0E80, 0x1001) + bytes([0x10]) + be32(0))
    out.append(("05-routing-activation-response-roundtrip.json", vec(P, "routing-activation-response-roundtrip", e,
                {"doip.tester_address": str(0x0E80), "doip.source_address": str(0x1001), "doip.response_code": str(0x10)},
                ref=R_D, note="routing activated")))
    f = doip(0x8001, be16(0x0E80, 0x1001) + bytes([0x22, 0xF1, 0x90]))
    out.append(("06-diagnostic-message-roundtrip.json", vec(P, "diagnostic-message-roundtrip", f,
                {"doip.payload_type": str(0x8001), "doip.source_address": str(0x0E80), "doip.target_address": str(0x1001),
                 "doip.user_data.#": "3"},
                ref=R_D, note="a diagnostic message carrying a UDS read of the VIN")))
    g = doip(0x8002, be16(0x1001, 0x0E80) + bytes([0x00, 0x22, 0xF1]))
    out.append(("07-diagnostic-ack-roundtrip.json", vec(P, "diagnostic-ack-roundtrip", g,
                {"doip.ack_code": "0", "doip.previous_message.#": "2"}, ref=R_D, note="a positive ACK repeating part of the request")))
    h = doip(0x4002, bytes([0x00, 0x04, 0x01]) + be32(4096))
    out.append(("08-entity-status-response-roundtrip.json", vec(P, "entity-status-response-roundtrip", h,
                {"doip.node_type": "0", "doip.max_sockets": "4", "doip.current_sockets": "1", "doip.max_data_size": "4096"}, ref=R_D)))
    i = doip(0, bytes([0x02]))
    out.append(("09-generic-nack-roundtrip.json", vec(P, "generic-nack-roundtrip", i, {"doip.nack_code": "2"}, ref=R_D)))
    j = doip(4, VIN + be16(0x1001) + EID + EID + bytes([0x00]), version=1)
    out.append(("10-announcement-without-sync-gains-zero.json", vec(P, "announcement-without-sync-gains-zero", j,
                expect=doip(4, VIN + be16(0x1001) + EID + EID + bytes([0x00, 0x00]), version=1), ref=R_D,
                note="version 1 has no sync status: the absent field is written as one zero octet and the length grows by one (ruling 7 of 0.8)")))
    out.append(("11-cut-payload-is-malformed.json", vec(P, "cut-payload-is-malformed", f[:-1], error="malformed-wire",
                ref=R_D, note="the payload length states one octet more than the input holds")))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (isotp_vectors(), uds_vectors(), doip_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("vehnet-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
