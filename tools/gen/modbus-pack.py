#!/usr/bin/env python3
"""Write the Modbus packs and model/modbus.def: requests and responses of the public function
codes of the Modbus Application Protocol V1.1b3, framed for TCP (the MBAP header of the Modbus
Messaging on TCP/IP Implementation Guide V1.0b) and for serial RTU (address, PDU, CRC; Modbus over
Serial Line V1.02).

A request and its response have different layouts for most function codes, and the wire does not
say which is which, so each direction is its own pack: modbus-tcp-request, modbus-tcp-response,
modbus-rtu-request, modbus-rtu-response. The PDU of each function code is stated once here and
written into the four packs. The vectors are not written here: tools/gen/modbus-vectors.py derives
them with an encoder of its own.

Usage: python3 -I tools/gen/modbus-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SHA = {"app": "f80d0d7132fd035104c3f21b01026470e3310ca3d8d493d9a9737d0d32ad2eb1",
       "tcp": "065d71170475642e82f370c648bf5135263cb20f61ce92c921add975fab6f669",
       "serial": "85a91e278b26d68c94a2f61a5300cd39c9e4c855034833f391abc6541fbdf7e5"}


def F(k, b, extra=""):
    return "field  modbus.%s  %d  uint%s" % (k, b, extra)


def lst(name, key, bits):
    return ["group  modbus.%s  rest" % name, "  " + F(key, bits), "end"]


def block(lenbits, inner):
    return ["length  %d  bytes" % lenbits] + ["  " + x for x in inner] + ["end"]


START_QTY = [F("start_address", 16), F("quantity", 16)]
SUB_REQ = ["group  modbus.file_sub_requests  rest", "  " + F("reference_type", 8), "  " + F("file_number", 16),
           "  " + F("record_number", 16), "  " + F("record_length", 16), "end"]
SUB_WRITE = ["group  modbus.file_sub_requests  rest", "  " + F("reference_type", 8), "  " + F("file_number", 16),
             "  " + F("record_number", 16), "  count  records  16", "  group  modbus.record_data  count  @records",
             "    " + F("register", 16), "  end", "end"]
DEVICE_ID_REQ = [F("mei_type", 8), "switch  modbus.mei_type", "  case  14", "    " + F("read_device_id_code", 8),
                 "    " + F("object_id", 8), "end"]
DEVICE_ID_RESP = [F("mei_type", 8), "switch  modbus.mei_type", "  case  14", "    " + F("read_device_id_code", 8),
                  "    " + F("conformity_level", 8), "    " + F("more_follows", 8), "    " + F("next_object_id", 8),
                  "    group  modbus.objects  count  8", "      " + F("object_id", 8), "      length  8  bytes",
                  "        group  modbus.object_value  rest", "          " + F("octet", 8), "        end",
                  "      end", "    end", "end"]

# function code -> (name, request lines, response lines)
FUNCTIONS = [
    (1, "read coils", START_QTY, block(8, lst("coil_bytes", "octet", 8))),
    (2, "read discrete inputs", START_QTY, block(8, lst("coil_bytes", "octet", 8))),
    (3, "read holding registers", START_QTY, block(8, lst("registers", "register", 16))),
    (4, "read input registers", START_QTY, block(8, lst("registers", "register", 16))),
    (5, "write single coil", [F("output_address", 16), F("output_value", 16)],
     [F("output_address", 16), F("output_value", 16)]),
    (6, "write single register", [F("register_address", 16), F("register_value", 16)],
     [F("register_address", 16), F("register_value", 16)]),
    (7, "read exception status", [], [F("exception_status", 8)]),
    (8, "diagnostics", [F("sub_function", 16), F("diagnostic_data", 16)],
     [F("sub_function", 16), F("diagnostic_data", 16)]),
    (11, "get comm event counter", [], [F("comm_status", 16), F("event_count", 16)]),
    (12, "get comm event log", [], block(8, [F("comm_status", 16), F("event_count", 16), F("message_count", 16)] +
                                         lst("events", "octet", 8))),
    (15, "write multiple coils", START_QTY + block(8, lst("coil_bytes", "octet", 8)), START_QTY),
    (16, "write multiple registers", START_QTY + block(8, lst("registers", "register", 16)), START_QTY),
    (17, "report server id", [], block(8, lst("server_id", "octet", 8))),
    (20, "read file record", block(8, SUB_REQ),
     block(8, ["group  modbus.file_sub_responses  rest", "  length  8  bytes", "    " + F("reference_type", 8),
               "    group  modbus.record_data  rest", "      " + F("register", 16), "    end", "  end", "end"])),
    (21, "write file record", block(8, SUB_WRITE), block(8, SUB_WRITE)),
    (22, "mask write register", [F("register_address", 16), F("and_mask", 16), F("or_mask", 16)],
     [F("register_address", 16), F("and_mask", 16), F("or_mask", 16)]),
    (23, "read/write multiple registers", [F("read_start", 16), F("read_quantity", 16), F("write_start", 16),
                                           F("write_quantity", 16)] + block(8, lst("write_registers", "register", 16)),
     block(8, lst("registers", "register", 16))),
    (24, "read fifo queue", [F("fifo_address", 16)], block(16, [F("fifo_count", 16)] + lst("registers", "register", 16))),
    (43, "encapsulated interface transport", DEVICE_ID_REQ, DEVICE_ID_RESP),
]


def pdu(direction, tcp):
    """The PDU: the function code, then a switch on it."""
    L = [F("function_code", 8), "switch  modbus.function_code"]
    for code, name, req, resp in FUNCTIONS:
        lines = req if direction == "request" else resp
        L.append("  case  %-4d                     # %s" % (code, name))
        L += ["    " + x for x in lines]
    if direction == "response":
        L.append("  case  %s" % ",".join(str(c | 0x80) for c, _, _, _ in FUNCTIONS))
        L.append("    " + F("exception_code", 8))
    if tcp:
        L.append("  else")
        L += ["    " + x for x in lst("pdu_data", "octet", 8)]
    L.append("end")
    return L


def pack_text(transport, direction):
    tcp = transport == "tcp"
    name = "modbus-%s-%s" % (transport, direction)
    head = ["# Modbus %s %s: %s, then the %s PDU of every public function code of the Modbus" %
            ("TCP" if tcp else "RTU", direction, "the MBAP header" if tcp else "the server address",
             direction),
            "# Application Protocol V1.1b3%s. Public; the source states no licence (pack.md). Written by"
            % ("" if tcp else ", then the CRC"),
            "# tools/gen/modbus-pack.py; do not edit by hand. Wire bits, layout sequential, msb; I/O is hex.",
            "format        %s" % name, "version       0.1.0", "distribution  public",
            'source        "Modbus Organization, MODBUS Application Protocol Specification V1.1b3, https://www.modbus.org/file/secure/modbusprotocolspecification.pdf (sha256 %s); layout restated"' % SHA["app"]]
    if tcp:
        head.append('source        "Modbus Organization, MODBUS Messaging on TCP/IP Implementation Guide V1.0b, https://www.modbus.org/file/secure/messagingimplementationguide.pdf (sha256 %s); layout restated"' % SHA["tcp"])
    else:
        head.append('source        "Modbus Organization, MODBUS over Serial Line Specification and Implementation Guide V1.02, https://www.modbus.org/file/secure/modbusoverserial.pdf (sha256 %s); layout restated"' % SHA["serial"])
    head += ["uses          modbus", "wire          bits", "layout        sequential", "bit_order     msb", ""]
    if tcp:
        body = [F("transaction_id", 16), F("protocol_id", 16), "length  16  bytes", "  " + F("unit_id", 8)]
        body += ["  " + x for x in pdu(direction, True)] + ["end"]
    else:
        body = [F("unit_id", 8)] + pdu(direction, False) + [F("crc", 16, "  swap")]
    return "\n".join(head + body) + "\n"


KEYS = [
    ("key", "transaction_id", "int", "-", "TCP: transaction identifier, copied from the request into the response"),
    ("key", "protocol_id", "int", "-", "TCP: protocol identifier, 0 for Modbus"),
    ("key", "unit_id", "int", "-", "unit identifier (TCP) or server address (RTU, 0 broadcast, 1-247)"),
    ("key", "function_code", "int", "-", "function code; in an exception response the code with its high bit set (128 added)"),
    ("key", "exception_code", "int", "-", "exception response: 1 illegal function, 2 illegal data address, 3 illegal data value, 4 server device failure, 5 acknowledge, 6 server device busy, 8 memory parity error, 10 gateway path unavailable, 11 gateway target failed to respond"),
    ("key", "start_address", "int", "-", "address of the first coil, input or register, from 0"),
    ("key", "quantity", "int", "-", "how many coils, inputs or registers"),
    ("list", "coil_bytes", None, None, "coils or discrete inputs, eight to an octet, the lowest address in the low bit of the first octet"),
    ("list", "registers", None, None, "16-bit registers, in address order"),
    ("list", "write_registers", None, None, "read/write multiple registers: the registers to write"),
    ("key", "register", "int", "-", "one 16-bit register value"),
    ("key", "octet", "int", "-", "one octet"),
    ("key", "output_address", "int", "-", "write single coil: the coil address"),
    ("key", "output_value", "int", "-", "write single coil: 65280 (0xFF00) on, 0 off"),
    ("key", "register_address", "int", "-", "write single register and mask write register: the register address"),
    ("key", "register_value", "int", "-", "write single register: the value"),
    ("key", "exception_status", "int", "-", "read exception status: the eight exception status outputs"),
    ("key", "sub_function", "int", "-", "diagnostics: sub-function code"),
    ("key", "diagnostic_data", "int", "-", "diagnostics: the 16-bit data word of the sub-function"),
    ("key", "comm_status", "int", "-", "get comm event counter and log: status word, 65535 while a previous command is in progress"),
    ("key", "event_count", "int", "-", "get comm event counter and log: event counter"),
    ("key", "message_count", "int", "-", "get comm event log: messages processed since the last restart"),
    ("list", "events", None, None, "get comm event log: event octets, most recent first"),
    ("list", "server_id", None, None, "report server id: the device-specific identification and run indicator, as octets"),
    ("list", "file_sub_requests", None, None, "read and write file record: the sub-requests, in order"),
    ("list", "file_sub_responses", None, None, "read file record: the sub-responses, in order"),
    ("key", "reference_type", "int", "-", "file record: reference type, 6"),
    ("key", "file_number", "int", "-", "file record: file number"),
    ("key", "record_number", "int", "-", "file record: starting record number"),
    ("key", "record_length", "int", "-", "read file record: how many registers to read"),
    ("list", "record_data", None, None, "file record: the registers of a record"),
    ("key", "and_mask", "int", "-", "mask write register: AND mask"),
    ("key", "or_mask", "int", "-", "mask write register: OR mask"),
    ("key", "read_start", "int", "-", "read/write multiple registers: first register to read"),
    ("key", "read_quantity", "int", "-", "read/write multiple registers: how many to read"),
    ("key", "write_start", "int", "-", "read/write multiple registers: first register to write"),
    ("key", "write_quantity", "int", "-", "read/write multiple registers: how many to write"),
    ("key", "fifo_address", "int", "-", "read FIFO queue: the FIFO pointer address"),
    ("key", "fifo_count", "int", "-", "read FIFO queue: how many registers the queue holds"),
    ("key", "mei_type", "int", "-", "encapsulated interface transport: MEI type, 14 read device identification, 13 CANopen"),
    ("key", "read_device_id_code", "int", "-", "read device identification: 1 basic, 2 regular, 3 extended, 4 one object"),
    ("key", "object_id", "int", "-", "read device identification: object identifier (0 vendor name, 1 product code, 2 revision, ...)"),
    ("key", "conformity_level", "int", "-", "read device identification: the device's conformity level"),
    ("key", "more_follows", "int", "-", "read device identification: 255 when more objects follow in another transaction, 0 otherwise"),
    ("key", "next_object_id", "int", "-", "read device identification: the object to ask for next when more follow"),
    ("list", "objects", None, None, "read device identification: the objects, in order"),
    ("list", "object_value", None, None, "read device identification: an object's value, as octets"),
    ("list", "pdu_data", None, None, "TCP: the data of a function code the pack does not lay out, as octets"),
    ("key", "crc", "int", "-", "RTU: the CRC-16 of the frame, as the 16-bit value (sent low octet first)"),
]


def module_text():
    w = max(len(k[1]) for k in KEYS)
    L = ["# The modbus module: the fields of Modbus requests and responses (Modbus Application Protocol",
         "# V1.1b3), of the MBAP header and of the RTU frame. Written by tools/gen/modbus-pack.py; do not edit.",
         "module        modbus", "version       0.1.0", "distribution  public",
         'source        "Modbus Organization, MODBUS Application Protocol V1.1b3, Messaging on TCP/IP Implementation Guide V1.0b, over Serial Line V1.02; no licence stated; restated by goat-transformers"']
    for kind, n, vt, unit, meaning in KEYS:
        L.append(('list  %-*s  "%s"' % (w, n, meaning)) if kind == "list" else
                 ('key   %-*s  %-3s  %s  "%s"' % (w, n, vt, unit, meaning)))
    return "\n".join(L) + "\n"


def build(out):
    for t in ("tcp", "rtu"):
        for d in ("request", "response"):
            out.write("packs/modbus-%s-%s/pack.def" % (t, d), pack_text(t, d))
    out.write("model/modbus.def", module_text())
    return {"modbus": 5}


def main(argv=None):
    return genio.vector_main("modbus-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
