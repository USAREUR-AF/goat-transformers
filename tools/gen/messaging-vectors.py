#!/usr/bin/env python3
"""messaging-vectors: write the vectors of the messaging protocol packs.

Packs: mqtt311, mqtt5, amqp10-frame, stun.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of MQTT 3.1.1 sections 2 and 3, MQTT 5.0 sections 1.5, 2 and 3
(OASIS), AMQP 1.0 Part 2 sections 2.2 and 2.3 and Part 1 section 1.6 (OASIS), RFC 8489 sections 5,
6 and 14 and RFC 8656 sections 12 and 18: every multi-octet field big-endian; a Variable Byte
Integer in 7-bit groups, low group first, the high bit of each octet set when another follows.

Inputs: messages built here field by field from values chosen here. No message is taken from a
document. Addresses are from the documentation ranges of RFC 5737 and RFC 3849.

`expect` of every vector is this program's packing of the decoded values, which for these
messages is the input. `model` holds the values that were packed.

Usage: python3 -I tools/gen/messaging-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import ipaddress
import json
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = ("built by tools/gen/messaging-vectors.py from values chosen there; layout restated "
          "from %s; expect derived there, no engine run")


def u8(*v):
    return bytes(v)


def u16(*v):
    return b"".join(struct.pack(">H", x) for x in v)


def u32(*v):
    return b"".join(struct.pack(">I", x) for x in v)


def vec(name, frm, inp, model=None, error=None, ref=""):
    v = {"name": name, "from": frm, "to": frm, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % ref
    return v


# ---------------------------------------------------------------- MQTT

def vbi(n):
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += u8(b | (0x80 if n else 0))
        if not n:
            return out


def ms(b):
    return u16(len(b)) + b


def packet(t, flags, body):
    return u8((t << 4) | flags) + vbi(len(body)) + body


def props(*items):
    body = b"".join(items)
    return vbi(len(body)) + body


def p_byte(i, v):
    return u8(i, v)


def p_u16(i, v):
    return u8(i) + u16(v)


def p_u32(i, v):
    return u8(i) + u32(v)


def p_str(i, s):
    return u8(i) + ms(s)


def p_pair(name, value):
    return u8(38) + ms(name) + ms(value)


def octets_model(prefix, b):
    return {prefix + ".#": str(len(b)), prefix + "[0].mqtt.octet": str(b[0])} if b else {prefix + ".#": "0"}


R3 = "MQTT 3.1.1 sections 2 and 3"
R5 = "MQTT 5.0 sections 1.5, 2 and 3"


def mqtt311_vectors():
    out = []
    flags = (1 << 7) | (1 << 6) | (0 << 5) | (1 << 3) | (1 << 2) | (1 << 1)
    body = (ms(b"MQTT") + u8(4, flags) + u16(60) + ms(b"sensor-7") + ms(b"status/sensor-7") + ms(b"offline") +
            ms(b"dev") + ms(b"\x01\x02"))
    msg = packet(1, 0, body)
    m = {"@kind": "connect", "mqtt.remaining_length_c1": "0", "mqtt.remaining_length_v0": str(len(body)),
         "mqtt.protocol_level": "4", "mqtt.username_flag": "1", "mqtt.password_flag": "1", "mqtt.will_qos": "1",
         "mqtt.will_flag": "1", "mqtt.clean_start": "1", "mqtt.keep_alive": "60", "mqtt.client_id.#": "8",
         "mqtt.will_topic.#": "15", "mqtt.username.#": "3", "mqtt.password.#": "2"}
    m.update(octets_model("mqtt.protocol_name", b"MQTT"))
    out.append(("01-connect-roundtrip.json", vec("connect-roundtrip", "mqtt311", msg, m,
                ref=R3 + "; CONNECT with a will, a user name and a password")))
    msg = packet(2, 0, u8(1, 0))
    out.append(("02-connack-roundtrip.json", vec("connack-roundtrip", "mqtt311", msg,
                {"@kind": "connack", "mqtt.session_present": "1", "mqtt.reason_code": "0"},
                ref=R3 + "; CONNACK with a session present")))
    msg = packet(3, (0 << 3) | (1 << 1) | 1, ms(b"sensors/7/temp") + u16(10) + b"21.5")
    out.append(("03-publish-qos1-roundtrip.json", vec("publish-qos1-roundtrip", "mqtt311", msg,
                {"@kind": "publish", "mqtt.qos": "1", "mqtt.retain": "1", "mqtt.packet_id": "10",
                 "mqtt.topic.#": "14", "mqtt.payload.#": "4", "mqtt.payload[0].mqtt.octet": "50"},
                ref=R3 + "; PUBLISH at QoS 1, retained, with a packet identifier")))
    big = bytes(range(200))
    body = ms(b"bulk") + big
    msg = packet(3, 0, body)
    out.append(("04-publish-two-octet-length-roundtrip.json", vec("publish-two-octet-length-roundtrip", "mqtt311", msg,
                {"mqtt.qos": "0", "mqtt.remaining_length_c1": "1", "mqtt.remaining_length_v0": str(len(body) & 0x7F),
                 "mqtt.remaining_length_c2": "0", "mqtt.remaining_length_v1": str(len(body) >> 7),
                 "mqtt.payload.#": "200", "@absent": ["mqtt.packet_id"]},
                ref=R3 + "; PUBLISH at QoS 0 with 200 octets of payload: a Remaining Length of two octets")))
    msg = packet(4, 0, u16(10))
    out.append(("05-puback-roundtrip.json", vec("puback-roundtrip", "mqtt311", msg, {"@kind": "puback", "mqtt.packet_id": "10"},
                ref=R3 + "; PUBACK")))
    msg = packet(6, 2, u16(11))
    out.append(("06-pubrel-roundtrip.json", vec("pubrel-roundtrip", "mqtt311", msg, {"@kind": "pubrel", "mqtt.flags": "2"},
                ref=R3 + "; PUBREL, whose fixed header flags are 0010")))
    msg = packet(8, 2, u16(12) + ms(b"sensors/+/temp") + u8(1) + ms(b"alerts/#") + u8(0))
    out.append(("07-subscribe-roundtrip.json", vec("subscribe-roundtrip", "mqtt311", msg,
                {"@kind": "subscribe", "mqtt.packet_id": "12", "mqtt.subscriptions.#": "2",
                 "mqtt.subscriptions[0].mqtt.requested_qos": "1", "mqtt.subscriptions[1].mqtt.topic_filter.#": "8"},
                ref=R3 + "; SUBSCRIBE to two topic filters")))
    msg = packet(9, 0, u16(12) + u8(1, 0x80))
    out.append(("08-suback-roundtrip.json", vec("suback-roundtrip", "mqtt311", msg,
                {"@kind": "suback", "mqtt.reason_codes.#": "2", "mqtt.reason_codes[1].mqtt.code": "128"},
                ref=R3 + "; SUBACK granting QoS 1 and refusing the second filter")))
    msg = packet(10, 2, u16(13) + ms(b"alerts/#"))
    out.append(("09-unsubscribe-roundtrip.json", vec("unsubscribe-roundtrip", "mqtt311", msg,
                {"@kind": "unsubscribe", "mqtt.unsubscriptions.#": "1"}, ref=R3 + "; UNSUBSCRIBE")))
    msg = packet(11, 0, u16(13))
    out.append(("10-unsuback-roundtrip.json", vec("unsuback-roundtrip", "mqtt311", msg, {"@kind": "unsuback", "mqtt.packet_id": "13"},
                ref=R3 + "; UNSUBACK")))
    for i, (t, n) in enumerate(((12, "pingreq"), (13, "pingresp"), (14, "disconnect")), 11):
        msg = packet(t, 0, b"")
        out.append(("%02d-%s-roundtrip.json" % (i, n), vec("%s-roundtrip" % n, "mqtt311", msg,
                    {"@kind": n, "mqtt.remaining_length_v0": "0"}, ref=R3 + "; %s" % n.upper())))
    out.append(("14-reserved-type-is-no-kind.json", vec("reserved-type-is-no-kind", "mqtt311", u8(0, 0), error="no-kind",
                ref=R3 + "; packet type 0, which is reserved")))
    out.append(("15-truncated-is-malformed.json", vec("truncated-is-malformed", "mqtt311", packet(4, 0, u16(10))[:3],
                error="malformed-wire", ref=R3 + "; a PUBACK without the second octet of its packet identifier")))
    return [("mqtt311",) + x for x in out]


def mqtt5_vectors():
    out = []
    flags = (1 << 7) | (0 << 6) | (1 << 5) | (1 << 3) | (1 << 2) | (1 << 1)
    body = (ms(b"MQTT") + u8(5, flags) + u16(30) +
            props(p_u32(17, 3600), p_u16(33, 20), p_pair(b"site", b"lab")) + ms(b"sensor-7") +
            props(p_u32(24, 5), p_str(3, b"text/plain")) + ms(b"status/sensor-7") + ms(b"offline") + ms(b"dev"))
    msg = packet(1, 0, body)
    out.append(("01-connect-roundtrip.json", vec("connect-roundtrip", "mqtt5", msg,
                {"@kind": "connect", "mqtt.protocol_level": "5", "mqtt.will_retain": "1", "mqtt.properties_length_c": "0",
                 "mqtt.properties.#": "3", "mqtt.properties[0].mqtt.property_id": "17",
                 "mqtt.properties[0].mqtt.property_u32": "3600", "mqtt.properties[1].mqtt.property_u16": "20",
                 "mqtt.properties[2].mqtt.property_name.#": "4", "mqtt.properties[2].mqtt.property_value.#": "3",
                 "mqtt.client_id.#": "8", "mqtt.will_properties.#": "2",
                 "mqtt.will_properties[0].mqtt.property_u32": "5",
                 "mqtt.will_properties[1].mqtt.property_string.#": "10", "mqtt.will_payload.#": "7",
                 "mqtt.username.#": "3", "@absent": ["mqtt.password"]},
                ref=R5 + "; CONNECT with session expiry, receive maximum and a user property; a will with will "
                    "delay and content type; a user name")))
    msg = packet(2, 0, u8(0, 0) + props(p_str(18, b"auto-1"), p_byte(36, 1), p_u16(34, 10), p_byte(41, 1)))
    out.append(("02-connack-roundtrip.json", vec("connack-roundtrip", "mqtt5", msg,
                {"@kind": "connack", "mqtt.reason_code": "0", "mqtt.properties.#": "4",
                 "mqtt.properties[0].mqtt.property_string.#": "6", "mqtt.properties[1].mqtt.property_byte": "1",
                 "mqtt.properties[2].mqtt.property_u16": "10", "mqtt.properties[3].mqtt.property_id": "41"},
                ref=R5 + "; CONNACK with an assigned client identifier, maximum QoS, topic alias maximum and "
                    "subscription identifiers available")))
    msg = packet(3, (1 << 1), ms(b"sensors/7/temp") + u16(21) +
                 props(p_u16(35, 3), u8(11) + vbi(300), u8(9) + ms(b"\xca\xfe")) + b"21.5")
    out.append(("03-publish-roundtrip.json", vec("publish-roundtrip", "mqtt5", msg,
                {"@kind": "publish", "mqtt.qos": "1", "mqtt.packet_id": "21", "mqtt.properties.#": "3",
                 "mqtt.properties[0].mqtt.property_u16": "3", "mqtt.properties[1].mqtt.property_vbi_c1": "1",
                 "mqtt.properties[1].mqtt.property_vbi_v0": str(300 & 0x7F),
                 "mqtt.properties[1].mqtt.property_vbi_v1": str(300 >> 7),
                 "mqtt.properties[2].mqtt.property_binary.#": "2", "mqtt.payload.#": "4"},
                ref=R5 + "; PUBLISH at QoS 1 with a topic alias, the subscription identifier 300 (two octets) "
                    "and correlation data")))
    msg = packet(4, 0, u16(21))
    out.append(("04-puback-short-roundtrip.json", vec("puback-short-roundtrip", "mqtt5", msg,
                {"@kind": "puback", "mqtt.packet_id": "21", "@absent": ["mqtt.reason_code"]},
                ref=R5 + "; PUBACK of Remaining Length 2: no reason code, no properties")))
    msg = packet(4, 0, u16(22) + u8(0x10))
    out.append(("05-puback-reason-roundtrip.json", vec("puback-reason-roundtrip", "mqtt5", msg,
                {"mqtt.reason_code": "16", "@absent": ["mqtt.properties"]},
                ref=R5 + "; PUBACK of Remaining Length 3: a reason code, no property length")))
    msg = packet(5, 0, u16(23) + u8(0x80) + props(p_str(31, b"quota")))
    out.append(("06-pubrec-properties-roundtrip.json", vec("pubrec-properties-roundtrip", "mqtt5", msg,
                {"@kind": "pubrec", "mqtt.reason_code": "128", "mqtt.properties.#": "1",
                 "mqtt.properties[0].mqtt.property_id": "31"},
                ref=R5 + "; PUBREC with a failure reason code and a reason string")))
    opts = (1 << 4) | (1 << 3) | (1 << 2) | 2
    msg = packet(8, 2, u16(24) + props(u8(11) + vbi(1)) + ms(b"sensors/#") + u8(opts))
    out.append(("07-subscribe-roundtrip.json", vec("subscribe-roundtrip", "mqtt5", msg,
                {"@kind": "subscribe", "mqtt.properties[0].mqtt.property_vbi_v0": "1",
                 "mqtt.subscriptions[0].mqtt.retain_handling": "1", "mqtt.subscriptions[0].mqtt.retain_as_published": "1",
                 "mqtt.subscriptions[0].mqtt.no_local": "1", "mqtt.subscriptions[0].mqtt.requested_qos": "2"},
                ref=R5 + "; SUBSCRIBE with a subscription identifier and every subscription option")))
    msg = packet(9, 0, u16(24) + props() + u8(2, 0x87))
    out.append(("08-suback-roundtrip.json", vec("suback-roundtrip", "mqtt5", msg,
                {"@kind": "suback", "mqtt.properties.#": "0", "mqtt.reason_codes.#": "2",
                 "mqtt.reason_codes[1].mqtt.code": "135"},
                ref=R5 + "; SUBACK with no properties and two reason codes")))
    msg = packet(10, 2, u16(25) + props() + ms(b"sensors/#"))
    out.append(("09-unsubscribe-roundtrip.json", vec("unsubscribe-roundtrip", "mqtt5", msg,
                {"@kind": "unsubscribe", "mqtt.unsubscriptions.#": "1"}, ref=R5 + "; UNSUBSCRIBE")))
    msg = packet(11, 0, u16(25) + props() + u8(0))
    out.append(("10-unsuback-roundtrip.json", vec("unsuback-roundtrip", "mqtt5", msg,
                {"@kind": "unsuback", "mqtt.reason_codes.#": "1"}, ref=R5 + "; UNSUBACK")))
    out.append(("11-disconnect-empty-roundtrip.json", vec("disconnect-empty-roundtrip", "mqtt5", packet(14, 0, b""),
                {"@kind": "disconnect", "@absent": ["mqtt.reason_code"]},
                ref=R5 + "; DISCONNECT of Remaining Length 0")))
    out.append(("12-disconnect-reason-roundtrip.json", vec("disconnect-reason-roundtrip", "mqtt5", packet(14, 0, u8(4)),
                {"mqtt.reason_code": "4"}, ref=R5 + "; DISCONNECT with a will (reason code 4), no properties")))
    msg = packet(14, 0, u8(0x8E) + props(p_str(31, b"taken over")))
    out.append(("13-disconnect-properties-roundtrip.json", vec("disconnect-properties-roundtrip", "mqtt5", msg,
                {"mqtt.reason_code": "142", "mqtt.properties.#": "1"},
                ref=R5 + "; DISCONNECT, session taken over, with a reason string")))
    msg = packet(15, 0, u8(0x18) + props(p_str(21, b"SCRAM-SHA-1"), u8(22) + ms(b"\x01\x02\x03")))
    out.append(("14-auth-roundtrip.json", vec("auth-roundtrip", "mqtt5", msg,
                {"@kind": "auth", "mqtt.reason_code": "24", "mqtt.properties.#": "2",
                 "mqtt.properties[1].mqtt.property_binary.#": "3"},
                ref=R5 + "; AUTH, continue authentication, with a method and data")))
    longv = b"x" * 150
    msg = packet(3, 0, ms(b"t") + props(p_pair(b"k", longv)) + b"p")
    out.append(("15-publish-long-properties-roundtrip.json", vec("publish-long-properties-roundtrip", "mqtt5", msg,
                {"mqtt.properties_length_c": "1", "@absent": ["mqtt.properties", "mqtt.payload"],
                 "mqtt.packet_rest.#": str(len(msg) - 1 - 2 - 3 - 1)},
                ref=R5 + "; PUBLISH whose properties take 156 octets: the property length takes two octets, so "
                    "the rest of the packet is kept as octets")))
    out.append(("16-pingresp-roundtrip.json", vec("pingresp-roundtrip", "mqtt5", packet(13, 0, b""),
                {"@kind": "pingresp"}, ref=R5 + "; PINGRESP")))
    return [("mqtt5",) + x for x in out]


# ---------------------------------------------------------------- AMQP 1.0

RA = "AMQP 1.0 Part 2 sections 2.2 and 2.3 and Part 1 section 1.6"


def amqp_vectors():
    out = []
    hdr = b"AMQP" + u8(0, 1, 0, 0)
    out.append(("01-protocol-header-roundtrip.json", vec("protocol-header-roundtrip", "amqp10-frame", hdr,
                {"@kind": "protocol_header", "amqp.protocol_id": "0", "amqp.major": "1"},
                ref=RA + "; the AMQP protocol header")))
    empty = u32(8) + u8(2, 0) + u16(0)
    out.append(("02-empty-frame-roundtrip.json", vec("empty-frame-roundtrip", "amqp10-frame", empty,
                {"@kind": "empty_frame", "amqp.doff": "2", "amqp.channel": "0"}, ref=RA + "; an empty frame (heartbeat)")))
    fields = u8(0xA1, 2) + b"c1" + u8(0x40)                       # container-id "c1", hostname null
    lst = u8(0xC0, 1 + len(fields), 2) + fields
    body = u8(0x00, 0x53, 0x10) + lst
    frame = u32(8 + len(body)) + u8(2, 0) + u16(0) + body
    out.append(("03-open-frame-roundtrip.json", vec("open-frame-roundtrip", "amqp10-frame", frame,
                {"@kind": "frame", "amqp.frame_type": "0", "amqp.descriptor_constructor": "83",
                 "amqp.performative": "16", "amqp.body.#": str(len(lst))},
                ref=RA + "; an open performative on channel 0 (container-id and a null hostname, kept as octets)")))
    body = u8(0x00, 0x80) + struct.pack(">Q", 0x13) + u8(0x45)       # flow, with an empty list
    frame = u32(8 + len(body)) + u8(2, 0) + u16(3) + body
    out.append(("04-ulong-descriptor-roundtrip.json", vec("ulong-descriptor-roundtrip", "amqp10-frame", frame,
                {"amqp.channel": "3", "amqp.descriptor_constructor": "128", "amqp.performative": "19",
                 "amqp.body.#": "1"},
                ref=RA + "; a flow performative whose descriptor is written as a ulong")))
    body = u8(0x00, 0x53, 0x40) + u8(0x45)
    frame = u32(8 + len(body)) + u8(2, 1) + u16(0) + body
    out.append(("05-sasl-frame-roundtrip.json", vec("sasl-frame-roundtrip", "amqp10-frame", frame,
                {"amqp.frame_type": "1", "amqp.performative": "64"},
                ref=RA + "; a SASL frame with the sasl-mechanisms descriptor")))
    ext = u8(0xAA, 0xBB, 0xCC, 0xDD) + u8(0x00, 0x53, 0x18, 0x45)
    frame = u32(8 + len(ext)) + u8(3, 0) + u16(0) + ext
    out.append(("06-extended-header-roundtrip.json", vec("extended-header-roundtrip", "amqp10-frame", frame,
                {"amqp.doff": "3", "amqp.extended_header_and_body.#": "8"},
                ref=RA + "; a frame with a data offset of 3: an extended header of 4 octets before the body")))
    out.append(("07-truncated-is-malformed.json", vec("truncated-is-malformed", "amqp10-frame", frame[:-1],
                error="malformed-wire", ref=RA + "; the last frame without its last octet")))
    return [("amqp10-frame",) + x for x in out]


# ---------------------------------------------------------------- STUN and TURN

RS = "RFC 8489 sections 5, 6 and 14 and RFC 8656 sections 12 and 18"
COOKIE = 0x2112A442


def attr(t, value):
    return u16(t, len(value)) + value + b"\0" * (-len(value) % 4)


def stun(mtype, txid, attrs, fingerprint=False):
    body = b"".join(attrs)
    if fingerprint:
        partial = u16(mtype, len(body) + 8) + u32(COOKIE) + txid + body
        crc = (zlib.crc32(partial) ^ 0x5354554E) & 0xFFFFFFFF
        body += attr(0x8028, u32(crc))
    return u16(mtype, len(body)) + u32(COOKIE) + txid + body


def xaddr4(ip, port):
    return u8(0, 1) + u16(port ^ (COOKIE >> 16)) + u32(int(ipaddress.IPv4Address(ip)) ^ COOKIE)


def addr6(ip, port):
    return u8(0, 2) + u16(port) + ipaddress.IPv6Address(ip).packed


def stun_vectors():
    out = []
    tx1 = bytes.fromhex("b7e7a701bc34d686fa87dfae")
    req = stun(0x0001, tx1, [attr(0x8022, b"goat-test")])
    out.append(("01-binding-request-roundtrip.json", vec("binding-request-roundtrip", "stun", req,
                {"@kind": "message", "stun.message_type": "1", "stun.magic_cookie": str(COOKIE),
                 "stun.transaction_id": tx1.hex(), "stun.attributes.#": "1",
                 "stun.attributes[0].stun.attr_value.#": "9"},
                ref=RS + "; a Binding request with SOFTWARE (9 octets, padded to 12)")))
    xm = xaddr4("192.0.2.1", 32853)
    resp = stun(0x0101, tx1, [attr(0x0020, xm), attr(0x0001, addr6("2001:db8::1", 32853))], fingerprint=True)
    out.append(("02-binding-success-roundtrip.json", vec("binding-success-roundtrip", "stun", resp,
                {"stun.message_type": "257", "stun.attributes.#": "3", "stun.attributes[0].stun.family": "1",
                 "stun.attributes[0].stun.port": str(32853 ^ 0x2112),
                 "stun.attributes[0].stun.ipv4": str(int(ipaddress.IPv4Address("192.0.2.1")) ^ COOKIE),
                 "stun.attributes[1].stun.family": "2",
                 "stun.attributes[1].stun.ipv6": ipaddress.IPv6Address("2001:db8::1").packed.hex(),
                 "stun.attributes[2].stun.attr_type": "32808"},
                ref=RS + "; a Binding success response with XOR-MAPPED-ADDRESS (IPv4, the XORed values on the "
                    "wire), MAPPED-ADDRESS (IPv6) and FINGERPRINT")))
    tx2 = bytes.fromhex("0102030405060708090a0b0c")
    err = stun(0x0111, tx2, [attr(0x0009, u8(0, 0, 4, 1) + b"Unauthorized"), attr(0x0014, b"example.org"),
                             attr(0x0015, b"obMatJos2AAACf//499k954d6OL34oL9FSTvy64sA"),
                             attr(0x000A, u16(0x0021, 0x0042))])
    out.append(("03-error-response-roundtrip.json", vec("error-response-roundtrip", "stun", err,
                {"stun.message_type": "273", "stun.attributes[0].stun.error_class": "4",
                 "stun.attributes[0].stun.error_number": "1", "stun.attributes[0].stun.attr_value.#": "12",
                 "stun.attributes[3].stun.unknown_attributes.#": "2",
                 "stun.attributes[3].stun.unknown_attributes[1].stun.unknown_type": "66"},
                ref=RS + "; a Binding error response 401 with REALM, NONCE and UNKNOWN-ATTRIBUTES")))
    tx3 = bytes.fromhex("a1a2a3a4a5a6a7a8a9aaabac")
    mi = bytes(range(20))
    alloc = stun(0x0003, tx3, [attr(0x0019, u8(17, 0, 0, 0)), attr(0x000D, u32(600)), attr(0x001A, b""),
                               attr(0x0018, u8(0x80)), attr(0x0006, b"alice"), attr(0x0008, mi)])
    out.append(("04-allocate-request-roundtrip.json", vec("allocate-request-roundtrip", "stun", alloc,
                {"stun.message_type": "3", "stun.attributes.#": "6", "stun.attributes[0].stun.requested_transport": "17",
                 "stun.attributes[1].stun.lifetime": "600", "stun.attributes[2].stun.attr_type": "26",
                 "stun.attributes[3].stun.even_port_r": "1", "stun.attributes[4].stun.attr_value.#": "5",
                 "stun.attributes[5].stun.integrity": mi.hex()},
                ref=RS + "; an Allocate request with REQUESTED-TRANSPORT, LIFETIME, DONT-FRAGMENT, EVEN-PORT, "
                    "USERNAME and MESSAGE-INTEGRITY")))
    token = bytes.fromhex("0011223344556677")
    ok = stun(0x0103, tx3, [attr(0x0016, xaddr4("198.51.100.7", 49152)), attr(0x000D, u32(600)),
                            attr(0x0022, token), attr(0x0020, xaddr4("192.0.2.1", 32853))])
    out.append(("05-allocate-success-roundtrip.json", vec("allocate-success-roundtrip", "stun", ok,
                {"stun.message_type": "259", "stun.attributes[0].stun.attr_type": "22",
                 "stun.attributes[2].stun.reservation_token": token.hex()},
                ref=RS + "; an Allocate success response with XOR-RELAYED-ADDRESS, LIFETIME, RESERVATION-TOKEN and "
                    "XOR-MAPPED-ADDRESS")))
    bind = stun(0x0009, tx2, [attr(0x000C, u16(0x4001, 0)), attr(0x0012, xaddr4("203.0.113.5", 5000))])
    out.append(("06-channel-bind-roundtrip.json", vec("channel-bind-roundtrip", "stun", bind,
                {"stun.message_type": "9", "stun.attributes[0].stun.channel_number": str(0x4001)},
                ref=RS + "; a ChannelBind request with CHANNEL-NUMBER and XOR-PEER-ADDRESS")))
    data = stun(0x0017, tx1, [attr(0x0012, xaddr4("203.0.113.5", 5000)), attr(0x0013, b"hello"),
                              attr(0x8004, u16(0) + u8(3, 4) + u32(1400)), attr(0x8001, u8(2, 0, 4, 40) + b"no v6"),
                              attr(0x0017, u8(2, 0, 0, 0))])
    out.append(("07-data-indication-roundtrip.json", vec("data-indication-roundtrip", "stun", data,
                {"stun.message_type": "23", "stun.attributes[1].stun.attr_value.#": "5",
                 "stun.attributes[2].stun.icmp_type": "3", "stun.attributes[2].stun.icmp_code": "4",
                 "stun.attributes[2].stun.icmp_error_data": "1400", "stun.attributes[3].stun.error_family": "2",
                 "stun.attributes[3].stun.error_number": "40", "stun.attributes[4].stun.requested_family": "2"},
                ref=RS + "; a Data indication with XOR-PEER-ADDRESS, DATA, ICMP, ADDRESS-ERROR-CODE and "
                    "REQUESTED-ADDRESS-FAMILY")))
    cd = u16(0x4001, 5) + b"hello"
    out.append(("08-channel-data-roundtrip.json", vec("channel-data-roundtrip", "stun", cd,
                {"@kind": "channel_data", "stun.channel_low": str(0x0001), "stun.data.#": "5"},
                ref=RS + "; a ChannelData message on channel 0x4001 with 5 octets")))
    out.append(("09-truncated-is-malformed.json", vec("truncated-is-malformed", "stun", req[:-4], error="malformed-wire",
                ref=RS + "; the Binding request without its last 4 octets, shorter than its length field")))
    return [("stun",) + x for x in out]


def build_files(out):
    written = {}
    for pack_name, fname, v in mqtt311_vectors() + mqtt5_vectors() + amqp_vectors() + stun_vectors():
        assert v["from"] == pack_name
        out.write("packs/%s/vectors/%s" % (pack_name, fname), json.dumps(v, indent=2) + "\n")
        written[pack_name] = written.get(pack_name, 0) + 1
    return written


def main(argv=None):
    return genio.vector_main("messaging-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
