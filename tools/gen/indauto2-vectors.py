#!/usr/bin/env python3
"""indauto2-vectors: write the vectors of bacnet-ip-bvlc, enip-encapsulation and hart-ip-message.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of:
- bacnet-stack bvlc.c and npdu.c: BVLC type 0x81, function, 16-bit length of the whole message;
  result code; BDT entries (address, port, mask); FDT entries (address, port, TTL, remaining);
  forwarded NPDU (address, port, NPDU); register (TTL); delete (address, port); NPDU: version,
  control octet (bit 7 network message, 5 destination, 3 source, 2 expecting reply, 1-0
  priority), DNET, DLEN, DADR, SNET, SLEN, SADR, hop count when a destination is present,
  message type and, from 0x80, a vendor ID; every integer big-endian;
- Wireshark packet-enip.c: the 24-octet little-endian encapsulation header (command, length of
  the data after the header, session handle, status, 8-octet sender context, options);
  RegisterSession version and flags; SendRRData and SendUnitData interface handle, timeout and
  the item list (count; each item type, length, data); connected address (connection ID),
  sequenced address (connection ID, sequence number), socket address info (family, port,
  address big-endian, 8 zero octets);
- Wireshark packet-hartip.c: version, message type, message ID, status, 16-bit sequence number,
  16-bit length of the whole message, all big-endian; session initiate (master type, 32-bit
  inactivity timer); error and NAK (error code); pass-through: delimiter (bit 7 address type,
  bits 6-5 expansion count, 4-3 physical layer, 2-0 frame type), short address (low 6 bits of
  one octet) or 5-octet long address, expansion octets, command, byte count, response code and
  device status in frame types 1 and 6, then the data and the checksum.

Inputs: messages built here field by field from values chosen here; no message is taken from a
document or a capture. Addresses are from RFC 5737.

`expect` of a round trip is this program's packing of the decoded values, which for these
messages is the input. Hexadecimal text in `model` under the little-endian bit order of
enip-encapsulation follows the specification's rule for `hex` there: each octet's low digit
first. `model` holds values that were packed.

Usage: python3 -I tools/gen/indauto2-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/indauto2-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_B = "bacnet-stack bvlc.c and npdu.c"
R_E = "Wireshark packet-enip.c"
R_H = "Wireshark packet-hartip.c"


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


def v4(s):
    return int(ipaddress.IPv4Address(s))


def be16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def be32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def le16(*v):
    return b"".join(struct.pack("<H", x) for x in v)


def le32(*v):
    return b"".join(struct.pack("<I", x) for x in v)


def lsb_hex(raw):
    """`hex` under bit_order lsb: each octet's low nibble digit first."""
    return "".join("%x%x" % (b & 15, b >> 4) for b in raw)


# ---------------------------------------------------------------- BACnet/IP

def bvlc(fn, body):
    return bytes([0x81, fn]) + be16(4 + len(body)) + body


def npdu(apdu=b"", expecting=0, prio=0, dest=None, src=None, hop=255, netmsg=None, vendor=None):
    ctrl = (0x80 if netmsg is not None else 0) | (0x20 if dest else 0) | (0x08 if src else 0) | (expecting << 2) | prio
    out = bytes([1, ctrl])
    if dest:
        out += be16(dest[0]) + bytes([len(dest[1])]) + dest[1]
    if src:
        out += be16(src[0]) + bytes([len(src[1])]) + src[1]
    if dest:
        out += bytes([hop])
    if netmsg is not None:
        out += bytes([netmsg])
        if netmsg >= 0x80:
            out += be16(vendor)
    return out + apdu


WHO_IS = bytes([0x10, 0x08])
READ_PV = bytes.fromhex("0005010c0c0000000a19551e")


def bacnet_vectors():
    P = "bacnet-ip-bvlc"
    out = []
    a = bvlc(11, npdu(WHO_IS))
    out.append(("01-original-broadcast-who-is-roundtrip.json", vec(P, "original-broadcast-who-is-roundtrip", a,
                {"bacnetip.function": "11", "bacnetip.npdu_version": "1", "bacnetip.destination_present": "0", "bacnetip.payload.#": "2"},
                ref=R_B, note="an original broadcast NPDU with no routing, its APDU two octets")))
    b = bvlc(10, npdu(READ_PV, expecting=1, prio=0, dest=(5, bytes([0x0a])), hop=254))
    out.append(("02-original-unicast-routed-roundtrip.json", vec(P, "original-unicast-routed-roundtrip", b,
                {"bacnetip.function": "10", "bacnetip.expecting_reply": "1", "bacnetip.destination_present": "1", "bacnetip.dnet": "5",
                 "bacnetip.dadr.#": "1", "bacnetip.hop_count": "254", "bacnetip.payload.#": str(len(READ_PV))},
                ref=R_B, note="a confirmed request to network 5, MAC address 0x0A, hop count 254")))
    c = bvlc(4, be32(v4("192.0.2.40")) + be16(47808) + npdu(bytes([0x10, 0x00, 0xc4]), src=(7, bytes([0x01, 0x02])), prio=3))
    out.append(("03-forwarded-npdu-with-source-roundtrip.json", vec(P, "forwarded-npdu-with-source-roundtrip", c,
                {"bacnetip.function": "4", "bacnetip.ip_address": str(v4("192.0.2.40")), "bacnetip.udp_port": "47808",
                 "bacnetip.source_present": "1", "bacnetip.snet": "7", "bacnetip.sadr.#": "2", "bacnetip.priority": "3"},
                ref=R_B, note="a forwarded NPDU from 192.0.2.40:47808 with a source network, life-safety priority")))
    d = bvlc(9, npdu(bytes([0x00, 0x05]), netmsg=0x80, vendor=260, dest=(65535, b""), hop=255))
    out.append(("04-network-message-with-vendor-roundtrip.json", vec(P, "network-message-with-vendor-roundtrip", d,
                {"bacnetip.network_message": "1", "bacnetip.dnet": "65535", "bacnetip.dadr.#": "0", "bacnetip.network_message_type": "128",
                 "bacnetip.vendor_id": "260"},
                ref=R_B, note="a proprietary network message (type 0x80, vendor 260) broadcast to all networks")))
    e = bvlc(0, be16(0x30))
    out.append(("05-result-nak-roundtrip.json", vec(P, "result-nak-roundtrip", e, {"bacnetip.result_code": str(0x30)},
                ref=R_B, note="a result: register foreign device NAK")))
    f = bvlc(5, be16(300))
    out.append(("06-register-foreign-device-roundtrip.json", vec(P, "register-foreign-device-roundtrip", f, {"bacnetip.ttl": "300"}, ref=R_B)))
    g = bvlc(3, be32(v4("192.0.2.1")) + be16(47808) + be32(0xFFFFFFFF) + be32(v4("198.51.100.1")) + be16(47808) + be32(0xFFFFFF00))
    out.append(("07-read-bdt-ack-roundtrip.json", vec(P, "read-bdt-ack-roundtrip", g,
                {"bacnetip.bdt_entries.#": "2", "bacnetip.bdt_entries[1].bacnetip.bdt_mask": str(0xFFFFFF00)},
                ref=R_B, note="a read BDT ack with two entries")))
    h = bvlc(7, be32(v4("203.0.113.9")) + be16(47809) + be16(300, 125))
    out.append(("08-read-fdt-ack-roundtrip.json", vec(P, "read-fdt-ack-roundtrip", h,
                {"bacnetip.fdt_entries[0].bacnetip.fdt_ttl": "300", "bacnetip.fdt_entries[0].bacnetip.fdt_remaining": "125"},
                ref=R_B, note="a read FDT ack with one entry")))
    out.append(("09-bvll-type-other-is-no-kind.json", vec(P, "bvll-type-other-is-no-kind", bytes([0x82]) + a[1:], error="no-kind",
                ref=R_B, note="the first octet is not the BACnet/IP type 0x81")))
    out.append(("10-shorter-than-length-is-malformed.json", vec(P, "shorter-than-length-is-malformed", b[:-1], error="malformed-wire",
                ref=R_B, note="the BVLC length states one octet more than the input holds")))
    return P, out


# ---------------------------------------------------------------- EtherNet/IP

CTX = bytes.fromhex("0102030405060708")


def enip(cmd, data, session=0, status=0, ctx=CTX, options=0):
    return le16(cmd, len(data)) + le32(session, status) + ctx + le32(options) + data


def item(typ, data):
    return le16(typ, len(data)) + data


def enip_vectors():
    P = "enip-encapsulation"
    out = []
    a = enip(0x65, le16(1, 0))
    out.append(("01-register-session-roundtrip.json", vec(P, "register-session-roundtrip", a,
                {"enip.command": "101", "enip.session_handle": "0", "enip.sender_context": lsb_hex(CTX), "enip.protocol_version": "1",
                 "enip.option_flags": "0"},
                ref=R_E, note="a RegisterSession request")))
    cip = bytes.fromhex("0e03200124013003")
    b = enip(0x6F, le32(0) + le16(10) + le16(2) + item(0, b"") + item(0xB2, cip), session=0x1A2B3C4D)
    out.append(("02-send-rr-data-unconnected-roundtrip.json", vec(P, "send-rr-data-unconnected-roundtrip", b,
                {"enip.command": "111", "enip.session_handle": str(0x1A2B3C4D), "enip.timeout": "10", "enip.items.#": "2",
                 "enip.items[0].enip.item_type": "0", "enip.items[1].enip.item_type": "178", "enip.items[1].enip.item_data.#": str(len(cip))},
                ref=R_E, note="SendRRData with a null address item and an unconnected data item holding a CIP request")))
    c = enip(0x70, le32(0) + le16(0) + le16(2) + item(0xA1, le32(0x80010203)) + item(0xB1, le16(7) + bytes.fromhex("cc000000")),
             session=0x1A2B3C4D)
    out.append(("03-send-unit-data-connected-roundtrip.json", vec(P, "send-unit-data-connected-roundtrip", c,
                {"enip.command": "112", "enip.items[0].enip.connection_id": str(0x80010203), "enip.items[1].enip.item_data.#": "6"},
                ref=R_E, note="SendUnitData with a connected address item and connected data")))
    sock = be16(2, 2222) + be32(v4("192.0.2.50")) + bytes(8)
    d = enip(0x6F, le32(0) + le16(0) + le16(3) + item(0, b"") + item(0xB2, bytes.fromhex("d40000")) + item(0x8001, sock),
             session=0x1A2B3C4D)
    out.append(("04-socket-address-item-roundtrip.json", vec(P, "socket-address-item-roundtrip", d,
                {"enip.items[2].enip.item_type": str(0x8001), "enip.items[2].enip.sin_family": "2", "enip.items[2].enip.sin_port": "2222",
                 "enip.items[2].enip.sin_addr": str(v4("192.0.2.50")), "enip.items[2].enip.sin_zero": "0" * 16},
                ref=R_E, note="a reply carrying a T->O socket address item, its fields big-endian")))
    e = enip(0x70, le32(0) + le16(0) + le16(2) + item(0x8002, le32(0x00112233, 42)) + item(0xB1, bytes(range(6))))
    out.append(("05-sequenced-address-roundtrip.json", vec(P, "sequenced-address-roundtrip", e,
                {"enip.items[0].enip.connection_id": str(0x00112233), "enip.items[0].enip.sequence_number": "42"},
                ref=R_E, note="a sequenced address item and connected data, as I/O data is framed")))
    f = enip(0x63, b"")
    out.append(("06-list-identity-request-roundtrip.json", vec(P, "list-identity-request-roundtrip", f,
                {"enip.command": "99", "enip.command_data.#": "0"}, ref=R_E, note="a ListIdentity request, no command data")))
    g = enip(0x66, b"", session=0x1A2B3C4D, status=0x65)
    out.append(("07-unregister-with-status-roundtrip.json", vec(P, "unregister-with-status-roundtrip", g,
                {"enip.command": "102", "enip.status": str(0x65)}, ref=R_E, note="UnRegisterSession with a status value")))
    out.append(("08-cut-header-is-malformed.json", vec(P, "cut-header-is-malformed", a[:20], error="malformed-wire",
                ref=R_E, note="the header stops four octets short")))
    return P, out


# ---------------------------------------------------------------- HART-IP

def hartip(mtype, mid, seq, body, status=0, version=1):
    return bytes([version, mtype, mid, status]) + be16(seq, 8 + len(body)) + body


def delim(long_addr, exp, phys, frame):
    return bytes([(long_addr << 7) | (exp << 5) | (phys << 3) | frame])


def hartip_vectors():
    P = "hart-ip-message"
    out = []
    a = hartip(0, 0, 1, bytes([1]) + be32(600000))
    out.append(("01-session-initiate-roundtrip.json", vec(P, "session-initiate-roundtrip", a,
                {"hartip.version": "1", "hartip.message_type": "0", "hartip.message_id": "0", "hartip.sequence_number": "1",
                 "hartip.master_type": "1", "hartip.inactivity_close_timer": "600000"},
                ref=R_H, note="a session initiate request from a primary master")))
    b = hartip(0, 3, 2, delim(0, 0, 0, 2) + bytes([0x00, 0x00, 0x00, 0x02]))
    out.append(("02-pass-through-short-request-roundtrip.json", vec(P, "pass-through-short-request-roundtrip", b,
                {"hartip.message_id": "3", "hartip.address_type": "0", "hartip.frame_type": "2", "hartip.short_address": "0",
                 "hartip.command": "0", "hartip.byte_count": "0", "hartip.data.#": "1"},
                ref=R_H, note="command 0 to polling address 0, the checksum as the last data octet")))
    c = hartip(1, 3, 3, delim(1, 0, 0, 6) + bytes.fromhex("a63e123456") + bytes([3, 26, 0, 0x40]) + bytes(24) + bytes([0x5a]))
    out.append(("03-pass-through-long-response-roundtrip.json", vec(P, "pass-through-long-response-roundtrip", c,
                {"hartip.message_type": "1", "hartip.address_type": "1", "hartip.frame_type": "6", "hartip.long_address": "a63e123456",
                 "hartip.command": "3", "hartip.byte_count": "26", "hartip.response_code": "0", "hartip.device_status": str(0x40),
                 "hartip.data.#": "25"},
                ref=R_H, note="a command 3 response to a long address, with response code and device status")))
    d = hartip(0, 3, 4, delim(0, 2, 0, 2) + bytes([0x81, 0xAA, 0xBB, 0x01, 0x00, 0x7f]))
    out.append(("04-pass-through-expansion-octets-roundtrip.json", vec(P, "pass-through-expansion-octets-roundtrip", d,
                {"hartip.short_reserved": "2", "hartip.short_address": "1", "hartip.expansion.#": "2", "hartip.command": "1"},
                ref=R_H, note="two expansion octets after a short address with the high bit set")))
    e = hartip(3, 0, 5, bytes([1]))
    out.append(("05-error-roundtrip.json", vec(P, "error-roundtrip", e, {"hartip.message_type": "3", "hartip.error_code": "1"},
                ref=R_H, note="an error: primary session unavailable")))
    f = hartip(0, 2, 6, b"")
    out.append(("06-keep-alive-roundtrip.json", vec(P, "keep-alive-roundtrip", f, {"hartip.message_id": "2", "hartip.body.#": "0"},
                ref=R_H, note="a keep alive with an empty body")))
    out.append(("07-shorter-than-length-is-malformed.json", vec(P, "shorter-than-length-is-malformed", a[:-1], error="malformed-wire",
                ref=R_H, note="the length states one octet more than the input holds")))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (bacnet_vectors(), enip_vectors(), hartip_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("indauto2-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
