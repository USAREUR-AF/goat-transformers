#!/usr/bin/env python3
"""modbus-vectors: write the vectors of the Modbus packs.

Packs: modbus-tcp-request, modbus-tcp-response, modbus-rtu-request, modbus-rtu-response.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of the MODBUS Application Protocol V1.1b3 section 6 (the PDU of
each function code), the MODBUS Messaging on TCP/IP Implementation Guide V1.0b section 3.1 (the
MBAP header) and MODBUS over Serial Line V1.02 section 2.5 and Appendix B (the RTU frame and its
CRC): every multi-octet field big-endian except the CRC, sent low octet first. The CRC is computed
here (polynomial 0xA001 reflected, initial value 0xFFFF); the packs carry it, they do not check it.

Inputs: frames built here field by field from values chosen here. No frame is taken from a
document. `expect` of every vector is this program's packing of the decoded values, which for these
frames is the input; `model` holds the values that were packed.

Usage: python3 -I tools/gen/modbus-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = ("built by tools/gen/modbus-vectors.py from values chosen there; layout restated from the "
          "MODBUS Application Protocol V1.1b3 section 6 and %s; expect derived there, no engine run")
TCP_REF = "the MODBUS Messaging on TCP/IP Implementation Guide V1.0b section 3.1"
RTU_REF = "MODBUS over Serial Line V1.02 section 2.5 and Appendix B"


def u8(*v):
    return bytes(v)


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def tcp(tx, unit, pdu):
    return u16(tx, 0, 1 + len(pdu)) + u8(unit) + pdu


def rtu(addr, pdu):
    frame = u8(addr) + pdu
    return frame + struct.pack("<H", crc16(frame))


def vec(pack, name, inp, model=None, error=None, what=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = (SOURCE % (TCP_REF if "tcp" in pack else RTU_REF)) + "; " + what
    return v


def tcp_request():
    p = "modbus-tcp-request"
    out = []
    add = lambda n, inp, m=None, w="", e=None: out.append((p, n, vec(p, n, inp, m, e, w)))
    add("read-holding-registers", tcp(1, 1, u8(3) + u16(0x006B, 3)),
        {"modbus.transaction_id": "1", "modbus.protocol_id": "0", "modbus.unit_id": "1", "modbus.function_code": "3",
         "modbus.start_address": "107", "modbus.quantity": "3"}, "read 3 holding registers from address 107")
    add("write-single-coil", tcp(2, 1, u8(5) + u16(0x00AC, 0xFF00)),
        {"modbus.output_address": "172", "modbus.output_value": "65280"}, "turn coil 172 on")
    add("write-multiple-coils", tcp(3, 1, u8(15) + u16(19, 10) + u8(2, 0xCD, 0x01)),
        {"modbus.quantity": "10", "modbus.coil_bytes.#": "2", "modbus.coil_bytes[0].modbus.octet": "205"},
        "write 10 coils from address 19")
    add("write-multiple-registers", tcp(4, 17, u8(16) + u16(1, 2) + u8(4) + u16(0x000A, 0x0102)),
        {"modbus.unit_id": "17", "modbus.registers.#": "2", "modbus.registers[1].modbus.register": "258"},
        "write 2 registers from address 1")
    sub = u8(6) + u16(4, 1, 2) + u8(6) + u16(3, 9, 2)
    add("read-file-record", tcp(5, 1, u8(20) + u8(len(sub)) + sub),
        {"modbus.file_sub_requests.#": "2", "modbus.file_sub_requests[1].modbus.file_number": "3",
         "modbus.file_sub_requests[1].modbus.record_number": "9", "modbus.file_sub_requests[0].modbus.record_length": "2"},
        "read two file records")
    ws = u8(6) + u16(4, 7, 3) + u16(0x06AF, 0x04BE, 0x100D)
    add("write-file-record", tcp(6, 1, u8(21) + u8(len(ws)) + ws),
        {"modbus.file_sub_requests.#": "1", "modbus.file_sub_requests[0].modbus.record_data.#": "3",
         "modbus.file_sub_requests[0].modbus.record_data[2].modbus.register": str(0x100D)},
        "write one record of 3 registers; the record length is written from the list")
    add("mask-write-register", tcp(7, 1, u8(22) + u16(4, 0x00F2, 0x0025)),
        {"modbus.register_address": "4", "modbus.and_mask": "242", "modbus.or_mask": "37"}, "mask write register 4")
    add("read-write-multiple-registers", tcp(8, 1, u8(23) + u16(3, 6, 14, 3) + u8(6) + u16(0x00FF, 0x00FF, 0x00FF)),
        {"modbus.read_start": "3", "modbus.read_quantity": "6", "modbus.write_start": "14", "modbus.write_quantity": "3",
         "modbus.write_registers.#": "3"}, "read 6 and write 3 registers")
    add("read-fifo-queue", tcp(9, 1, u8(24) + u16(0x04DE)), {"modbus.fifo_address": "1246"}, "read the FIFO at 1246")
    add("read-device-identification", tcp(10, 1, u8(43, 14, 1, 0)),
        {"modbus.function_code": "43", "modbus.mei_type": "14", "modbus.read_device_id_code": "1", "modbus.object_id": "0"},
        "read the basic device identification")
    add("user-function-code", tcp(11, 1, u8(65, 1, 2, 3)),
        {"modbus.function_code": "65", "modbus.pdu_data.#": "3"}, "function code 65 (user defined), its data as octets")
    add("truncated-is-malformed", tcp(1, 1, u8(3) + u16(0x006B, 3))[:-1], e="malformed-wire",
        w="the first request without its last octet")
    return out


def tcp_response():
    p = "modbus-tcp-response"
    out = []
    add = lambda n, inp, m=None, w="", e=None: out.append((p, n, vec(p, n, inp, m, e, w)))
    add("read-holding-registers", tcp(1, 1, u8(3, 6) + u16(0x022B, 0x0000, 0x0064)),
        {"modbus.function_code": "3", "modbus.registers.#": "3", "modbus.registers[0].modbus.register": "555",
         "modbus.registers[2].modbus.register": "100"}, "three registers")
    add("read-coils", tcp(2, 1, u8(1, 3, 0xCD, 0x6B, 0x05)),
        {"modbus.coil_bytes.#": "3", "modbus.coil_bytes[2].modbus.octet": "5"}, "19 coils in 3 octets")
    add("exception", tcp(3, 1, u8(0x83, 2)),
        {"modbus.function_code": "131", "modbus.exception_code": "2"}, "exception response to function 3: illegal data address")
    sr = u8(5, 6) + u16(0x0DFE, 0x0020) + u8(5, 6) + u16(0x33CD, 0x0040)
    add("read-file-record", tcp(4, 1, u8(20, len(sr)) + sr),
        {"modbus.file_sub_responses.#": "2", "modbus.file_sub_responses[0].modbus.record_data.#": "2",
         "modbus.file_sub_responses[1].modbus.record_data[0].modbus.register": str(0x33CD)}, "two sub-responses")
    objs = u8(0, 7) + b"Example" + u8(1, 5) + b"MB-01" + u8(2, 4) + b"V1.0"
    add("read-device-identification", tcp(5, 1, u8(43, 14, 1, 0x01, 0, 0, 3) + objs),
        {"modbus.mei_type": "14", "modbus.conformity_level": "1", "modbus.more_follows": "0", "modbus.objects.#": "3",
         "modbus.objects[0].modbus.object_value.#": "7", "modbus.objects[2].modbus.object_id": "2"},
        "basic device identification with three objects")
    add("read-fifo-queue", tcp(6, 1, u8(24) + u16(6, 2, 0x01B8, 0x1284)),
        {"modbus.fifo_count": "2", "modbus.registers.#": "2"}, "a FIFO of two registers")
    add("write-multiple-registers", tcp(7, 17, u8(16) + u16(1, 2)),
        {"modbus.start_address": "1", "modbus.quantity": "2"}, "the echo of start and quantity")
    add("read-write-multiple-registers", tcp(8, 1, u8(23, 12) + u16(0xFE, 0xACF, 0x0, 0x0, 0x0, 0xFF)),
        {"modbus.registers.#": "6"}, "six registers read")
    return out


def rtu_request():
    p = "modbus-rtu-request"
    out = []
    add = lambda n, inp, m=None, w="", e=None: out.append((p, n, vec(p, n, inp, m, e, w)))
    f = rtu(17, u8(3) + u16(0x006B, 3))
    add("read-holding-registers", f, {"modbus.unit_id": "17", "modbus.function_code": "3", "modbus.quantity": "3",
                                      "modbus.crc": str(crc16(f[:-2]))}, "read 3 registers from server 17, with its CRC")
    add("diagnostics", rtu(1, u8(8) + u16(0, 0xA537)),
        {"modbus.sub_function": "0", "modbus.diagnostic_data": str(0xA537)}, "diagnostics, return query data")
    add("read-exception-status", rtu(1, u8(7)), {"modbus.function_code": "7"}, "read exception status, no data")
    add("get-comm-event-counter", rtu(1, u8(11)), {"modbus.function_code": "11"}, "get comm event counter")
    add("report-server-id", rtu(1, u8(17)), {"modbus.function_code": "17"}, "report server id")
    add("write-single-register", rtu(0, u8(6) + u16(1, 3)),
        {"modbus.unit_id": "0", "modbus.register_address": "1", "modbus.register_value": "3"}, "broadcast write of register 1")
    add("unknown-function-is-no-kind", rtu(1, u8(65, 1, 2)), e="no-kind",
        w="function code 65 (user defined): its length is not known, so the frame cannot be read")
    add("truncated-is-malformed", rtu(1, u8(3) + u16(0, 1))[:-1], e="malformed-wire",
        w="a request without the last octet of its CRC")
    return out


def rtu_response():
    p = "modbus-rtu-response"
    out = []
    add = lambda n, inp, m=None, w="", e=None: out.append((p, n, vec(p, n, inp, m, e, w)))
    f = rtu(17, u8(3, 6) + u16(0x022B, 0, 0x64))
    add("read-holding-registers", f, {"modbus.registers.#": "3", "modbus.crc": str(crc16(f[:-2]))}, "three registers")
    add("read-exception-status", rtu(1, u8(7, 0x6D)), {"modbus.exception_status": "109"}, "exception status outputs")
    add("get-comm-event-counter", rtu(1, u8(11) + u16(0xFFFF, 0x0108)),
        {"modbus.comm_status": "65535", "modbus.event_count": "264"}, "a busy status and the event count")
    add("get-comm-event-log", rtu(1, u8(12, 8) + u16(0, 0x0108, 0x0121) + u8(0x20, 0x00)),
        {"modbus.event_count": "264", "modbus.message_count": "289", "modbus.events.#": "2"}, "two events")
    add("report-server-id", rtu(1, u8(17, 3, 0x42, 0xFF, 0x01)),
        {"modbus.server_id.#": "3"}, "a server id, run indicator on, one more octet")
    add("exception", rtu(1, u8(0x81, 1)), {"modbus.function_code": "129", "modbus.exception_code": "1"},
        "exception response to function 1: illegal function")
    ws = u8(6) + u16(4, 7, 1) + u16(0x06AF)
    add("write-file-record", rtu(1, u8(21, len(ws)) + ws),
        {"modbus.file_sub_requests[0].modbus.record_data.#": "1"}, "the echo of a write file record")
    add("diagnostics", rtu(1, u8(8) + u16(0x000B, 0x0042)),
        {"modbus.sub_function": "11", "modbus.diagnostic_data": "66"}, "diagnostics, return bus message count")
    return out


def build_files(out):
    written = {}
    by_pack = {}
    for pack, name, v in tcp_request() + tcp_response() + rtu_request() + rtu_response():
        by_pack.setdefault(pack, []).append((name, v))
    for pack, items in by_pack.items():
        for i, (name, v) in enumerate(items, 1):
            assert v["from"] == pack
            out.write("packs/%s/vectors/%02d-%s.json" % (pack, i, name), json.dumps(v, indent=2) + "\n")
            written[pack] = written.get(pack, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("modbus-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
