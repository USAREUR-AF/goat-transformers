#!/usr/bin/env python3
"""Write the smart-home serial framing packs and their modules:

- zwave-serial-frame: a Z-Wave Serial API frame between host and controller: the single-octet ACK,
  NAK and CAN, and the data frame (SOF, length, type, function, payload, checksum). Layout restated
  from zwave-js (packages/serial/src/message/Message.ts, MessageHeaders.ts, Constants.ts).
- enocean-esp3: an EnOcean Serial Protocol 3 packet: sync, data length, optional length, packet type,
  header CRC, data, optional data, data CRC. Layout restated from kipe/enocean
  (enocean/protocol/packet.py, constants.py).

The vectors are not written here: tools/gen/smarthome-vectors.py derives them with an encoder of its
own.

Usage: python3 -I tools/gen/smarthome-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

ZJ = "03756e4f179a4461f85822d2e5c71b1089667a22"
EN = "80a253bcea1e3cb99295f53f04c0558190dca5f3"
SRC = {
    "zw": ('source        "zwave-js, https://github.com/zwave-js/zwave-js at commit %s, packages/serial/src/message/Message.ts, '
           'MessageHeaders.ts and Constants.ts (MIT License, Copyright (c) 2018-2024 AlCalzone); layout restated, no code copied; '
           'the Silicon Labs Z-Wave Host API specification not used"' % ZJ),
    "en": ('source        "kipe/enocean, https://github.com/kipe/enocean at commit %s, enocean/protocol/packet.py and constants.py '
           '(MIT License, Copyright (c) 2014-2016 Kimmo Huoman); layout restated, no code copied; the EnOcean ESP3 specification '
           'not used"' % EN),
}


def F(k, b, tr="uint"):
    return "field  %s  %d  %s" % (k, b, tr)


def head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC[src]]
    for t, k, d in keys:
        L.append('list  %-*s  "%s"' % (w, k, d) if t == "list" else 'key   %-*s  %-6s  -  "%s"' % (w, k, t, d))
    return "\n".join(L) + "\n"


def zwave_pack():
    L = head("zwave-serial-frame", ["Z-Wave Serial API frame: ACK, NAK, CAN, or SOF, length, type, function, payload and checksum. Written by",
                                    "tools/gen/smarthome-pack.py; do not edit by hand."], "zw", ["zwave"])
    L += ["kind  ack", "when  8  6", "", "kind  nak", "when  8  21", "", "kind  can", "when  8  24", "",
          "kind  data-frame", "when  8  1", "length  8  bytes  plus  1", "  " + F("zwave.message_type", 8), "  " + F("zwave.function_id", 8),
          "  group  zwave.payload  rest", "    " + F("zwave.octet", 8), "  end", "end", F("zwave.checksum", 8)]
    return "\n".join(L) + "\n"


ZWAVE_KEYS = [
    ("int", "message_type", "0 request, 1 response"),
    ("int", "function_id", "Serial API function (0x02 GetSerialApiInitData, 0x04 ApplicationCommand, 0x13 SendData, 0x15 GetControllerVersion, 0x20 GetControllerId, 0x49 ApplicationUpdateRequest, 0xA8 BridgeApplicationCommand ...)"),
    ("list", "payload", "the function's payload, as octets"),
    ("int", "checksum", "the checksum, as sent (0xFF XOR every octet from the length to the last payload octet; not computed)"),
    ("int", "octet", "one octet"),
]


def esp3_pack():
    L = head("enocean-esp3", ["EnOcean Serial Protocol 3 packet: sync, lengths, packet type, header CRC, data, optional data, data CRC.",
                              "Written by tools/gen/smarthome-pack.py; do not edit by hand."], "en", ["esp3"])
    L += ["kind  esp3", "when  8  85", "count  data_length  16", "count  optional_length  8", F("esp3.packet_type", 8), F("esp3.header_crc", 8),
          "group  esp3.data  count  @data_length", "  " + F("esp3.octet", 8), "end",
          "group  esp3.optional_data  count  @optional_length", "  " + F("esp3.octet", 8), "end", F("esp3.data_crc", 8)]
    return "\n".join(L) + "\n"


ESP3_KEYS = [
    ("int", "packet_type", "packet type: 1 radio ERP1, 2 response, 3 radio sub-telegram, 4 event, 5 common command, 6 smart acknowledge command, 7 remote management command, 9 radio message, 10 radio ERP2"),
    ("int", "header_crc", "CRC8 over the data length, optional length and packet type, as sent (not computed)"),
    ("list", "data", "the data (its length is written from the list): for ERP1 the RORG, payload, sender ID and status"),
    ("list", "optional_data", "the optional data (its length is written from the list): for ERP1 the subtelegram count, destination ID, dBm and security level"),
    ("int", "data_crc", "CRC8 over the data and optional data, as sent (not computed)"),
    ("int", "octet", "one octet"),
]


def build(out):
    out.write("packs/zwave-serial-frame/pack.def", zwave_pack())
    out.write("packs/enocean-esp3/pack.def", esp3_pack())
    out.write("model/zwave.def", module("zwave", ["# The zwave module: Z-Wave Serial API frame fields. Written by tools/gen/smarthome-pack.py."], "zw", ZWAVE_KEYS))
    out.write("model/esp3.def", module("esp3", ["# The esp3 module: EnOcean ESP3 packet fields. Written by tools/gen/smarthome-pack.py."], "en", ESP3_KEYS))
    return {"smarthome": 4}


def main(argv=None):
    return genio.vector_main("smarthome-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
