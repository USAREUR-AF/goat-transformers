#!/usr/bin/env python3
"""Write the messaging protocol packs and their model modules: MQTT 3.1.1 and MQTT 5.0 control
packets (OASIS), the AMQP 1.0 frame (OASIS), and STUN (RFC 8489) with the TURN attributes and
ChannelData message (RFC 8656).

The MQTT packets repeat a Variable Byte Integer (the Remaining Length, the Subscription
Identifier), a UTF-8 string or binary field with a 2-octet length, and in MQTT 5 a property list
in many places; this script writes each repetition from one statement. The vectors are not written
here: tools/gen/messaging-vectors.py derives them with an encoder of its own.

A Variable Byte Integer is up to four octets, each a continuation bit then 7 value bits, low group
first. The `bits` wire has no transform that reads it as one integer, so it is stated as its
parts: the continuation bit and the 7 bits of each octet are fields, and a `switch` on each
continuation bit reads the next octet. A property list is bounded by its length, also a Variable
Byte Integer: when that length is one octet (properties of up to 127 octets) its 7 bits are a
`length 7 bytes` block; a longer list, and everything after it, is kept as octets.

Usage: python3 -I tools/gen/messaging-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SHA = {"mqtt311": "5ee3be2571a184beeab24b82aa332bf5c79e31c3d054d3af66a84bbd813895b0",
       "mqtt5": "16f24e2b021d86b3bbb2b39c8b5ee134b3d39f69320ba61d3c07a38af74e696c",
       "amqp": "9cd32460d1730975ff0a9dbb66573ff456cbd53ffd8d4f6899c497f02867f637",
       "amqptypes": "2ccf30b2c55924aaa5291cc34430a91b75c85d11d34bc008c36fc7ca7574d28c",
       "rfc8489": "3a1c97ec36576fda83b5f39fbe1d033c6c0b934e2209a29bb21b9ace57ef4289",
       "rfc8656": "271f4386bcf95cf94a31710dda6816a89cefdc2557581451e6a36d79b93b12b0"}


class W:
    def __init__(self, mod):
        self.lines, self.ind, self.mod = [], 0, mod

    def __call__(self, text):
        self.lines.append("  " * self.ind + text)

    def f(self, key, bits, tr="uint"):
        self("field  %s.%s  %d  %s" % (self.mod, key, bits, tr))

    def block(self, head):
        self(head)
        self.ind += 1

    def end(self):
        self.ind -= 1
        self("end")

    def switch(self, key):
        self("switch  %s.%s" % (self.mod, key))
        self.ind += 1

    def case(self, values):
        self("case  %s" % values if values != "else" else "else")
        self.ind += 1

    def endcase(self):
        self.ind -= 1

    def endswitch(self):
        self.ind -= 1
        self("end")

    def octets(self, lst):
        self.block("group  %s.%s  rest" % (self.mod, lst))
        self.f("octet", 8)
        self.end()


# ---------------------------------------------------------------- MQTT

def vbi(w, p):
    """A Variable Byte Integer as its parts: <p>c1, <p>v0, then while the continuation bit is 1
    the next octet's bit and 7 bits; the fourth octet's continuation bit must be 0."""
    w.f(p + "c1", 1)
    w.f(p + "v0", 7)
    w.switch(p + "c1")
    w.case("1")
    w.f(p + "c2", 1)
    w.f(p + "v1", 7)
    w.switch(p + "c2")
    w.case("1")
    w.f(p + "c3", 1)
    w.f(p + "v2", 7)
    w.switch(p + "c3")
    w.case("1")
    w("const  1  0")
    w.f(p + "v3", 7)
    w.endcase()
    w.case("0")
    w.endcase()
    w.endswitch()
    w.endcase()
    w.case("0")
    w.endcase()
    w.endswitch()
    w.endcase()
    w.case("0")
    w.endcase()
    w.endswitch()


def mstring(w, lst):
    """A UTF-8 string or binary data: a 2-octet length, then the octets."""
    w.block("length  16  bytes")
    w.octets(lst)
    w.end()


BYTE_P = "1,23,25,36,37,40,41,42"
U16_P = "19,33,34,35"
U32_P = "2,17,24,39"
STR_P = "3,8,18,21,26,28,31"
BIN_P = "9,22"


def properties(w, lst, after):
    """A property list: the first octet of its length (continuation bit, 7 bits); when the
    length is one octet, a `length 7 bytes` block of properties, then `after`; when it is longer,
    the rest of the packet as octets."""
    w.f(lst + "_length_c", 1)
    w.switch(lst + "_length_c")
    w.case("0")
    w.block("length  7  bytes")
    w.block("group  mqtt.%s  rest" % lst)
    w.f("property_id", 8)
    w.switch("property_id")
    for vals, body in ((BYTE_P, lambda: w.f("property_byte", 8)), (U16_P, lambda: w.f("property_u16", 16)),
                       (U32_P, lambda: w.f("property_u32", 32)), (STR_P, lambda: mstring(w, "property_string")),
                       (BIN_P, lambda: mstring(w, "property_binary")),
                       ("11", lambda: vbi(w, "property_vbi_")),
                       ("38", lambda: (mstring(w, "property_name"), mstring(w, "property_value")))):
        w.case(vals)
        body()
        w.endcase()
    w.case("else")
    w.octets("property_rest")
    w.endcase()
    w.endswitch()
    w.end()
    w.end()
    after()
    w.endcase()
    w.case("1")
    w.f(lst + "_length_low", 7)
    w.octets("packet_rest")
    w.endcase()
    w.endswitch()


def mqtt_pack(v5):
    name = "mqtt5" if v5 else "mqtt311"
    w = W("mqtt")
    for line in ["# MQTT %s control packet (OASIS standard): the fixed header and every packet type. Public;"
                 % ("5.0" if v5 else "3.1.1"),
                 "# the OASIS notice applies (packs/%s/REUSE.toml). Written by tools/gen/messaging-pack.py;" % name,
                 "# do not edit by hand. Wire bits, layout sequential, msb; I/O is hex text. pack.md states",
                 "# what is mapped, how the Variable Byte Integers are read, and what is not mapped.",
                 "format        %s" % name, "version       0.1.0", "distribution  public",
                 ('source        "OASIS, MQTT Version 5.0, OASIS Standard, 7 March 2019, https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html (sha256 %s); layout restated"' % SHA["mqtt5"])
                 if v5 else
                 ('source        "OASIS, MQTT Version 3.1.1, OASIS Standard, 29 October 2014, https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html (sha256 %s); layout restated"' % SHA["mqtt311"]),
                 "uses          mqtt", "wire          bits", "layout        sequential", "bit_order     msb"]:
        w(line)

    def kind(n, t, flags=True):
        w("")
        w("kind    %s" % n)
        w("when    4  %d" % t)
        if flags:
            w.f("flags", 4)
        vbi(w, "remaining_length_")

    # CONNECT
    kind("connect", 1)
    mstring(w, "protocol_name")
    w.f("protocol_level", 8)
    for k, b in (("username_flag", 1), ("password_flag", 1), ("will_retain", 1), ("will_qos", 2),
                 ("will_flag", 1), ("clean_start", 1), ("connect_reserved", 1)):
        w.f(k, b)
    w.f("keep_alive", 16)

    def connect_payload():
        mstring(w, "client_id")
        w.switch("will_flag")
        w.case("1")
        mstring(w, "will_topic")
        mstring(w, "will_payload")
        w.endcase()
        w.case("0")
        w.endcase()
        w.endswitch()
        user_pass()

    def user_pass():
        for flag, lst in (("username_flag", "username"), ("password_flag", "password")):
            w.switch(flag)
            w.case("1")
            mstring(w, lst)
            w.endcase()
            w.case("0")
            w.endcase()
            w.endswitch()

    if v5:
        # with a will, the user name and password follow the will (inside its property branch);
        # without one, they follow the client identifier
        def v5_payload():
            mstring(w, "client_id")
            w.switch("will_flag")
            w.case("1")
            properties(w, "will_properties", lambda: (mstring(w, "will_topic"), mstring(w, "will_payload"),
                                                       user_pass()))
            w.endcase()
            w.case("0")
            user_pass()
            w.endcase()
            w.endswitch()
        properties(w, "properties", v5_payload)
    else:
        connect_payload()

    # CONNACK
    kind("connack", 2)
    w.f("connack_reserved", 7)
    w.f("session_present", 1)
    w.f("reason_code", 8)
    if v5:
        properties(w, "properties", lambda: None)

    # PUBLISH
    w("")
    w("kind    publish")
    w("when    4  3")
    w.f("dup", 1)
    w.f("qos", 2)
    w.f("retain", 1)
    vbi(w, "remaining_length_")
    mstring(w, "topic")
    w.switch("qos")
    w.case("1,2,3")
    w.f("packet_id", 16)
    w.endcase()
    w.case("0")
    w.endcase()
    w.endswitch()
    if v5:
        properties(w, "properties", lambda: w.octets("payload"))
    else:
        w.octets("payload")

    # PUBACK, PUBREC, PUBREL, PUBCOMP
    for t, n in ((4, "puback"), (5, "pubrec"), (6, "pubrel"), (7, "pubcomp")):
        kind(n, t)
        w.f("packet_id", 16)
        if v5:
            ack_tail(w, short=((2, False), (3, True)))

    # SUBSCRIBE
    kind("subscribe", 8)
    w.f("packet_id", 16)

    def subs():
        w.block("group  mqtt.subscriptions  rest")
        mstring(w, "topic_filter")
        if v5:
            for k, b in (("options_reserved", 2), ("retain_handling", 2), ("retain_as_published", 1),
                         ("no_local", 1), ("requested_qos", 2)):
                w.f(k, b)
        else:
            w.f("options_reserved", 6)
            w.f("requested_qos", 2)
        w.end()

    if v5:
        properties(w, "properties", subs)
    else:
        subs()

    # SUBACK, UNSUBACK
    def codes():
        w.block("group  mqtt.reason_codes  rest")
        w.f("code", 8)
        w.end()

    kind("suback", 9)
    w.f("packet_id", 16)
    if v5:
        properties(w, "properties", codes)
    else:
        codes()

    kind("unsubscribe", 10)
    w.f("packet_id", 16)

    def unsubs():
        w.block("group  mqtt.unsubscriptions  rest")
        mstring(w, "topic_filter")
        w.end()

    if v5:
        properties(w, "properties", unsubs)
    else:
        unsubs()

    kind("unsuback", 11)
    w.f("packet_id", 16)
    if v5:
        properties(w, "properties", codes)

    kind("pingreq", 12)
    kind("pingresp", 13)
    kind("disconnect", 14)
    if v5:
        ack_tail(w, short=((0, None), (1, True)))
        kind("auth", 15)
        ack_tail(w, short=((0, None), (1, True)))
    return "\n".join(with_requires(w.lines, "mqtt.packet_type")) + "\n"


def with_requires(lines, key):
    """Each kind's `when` held as `key`, and `requires` with the fields the kind always has:
    those outside every group and switch."""
    out, at, nest = [], None, []
    for line in lines:
        t = line.split()
        if line.startswith("kind"):
            at, nest = None, []
        out.append(line)
        if line.startswith("when") and at is None:
            out[-1] = line + "  as  " + key
            out.append("requires")
            at = len(out) - 1
        elif t and at is not None:
            if t[0] in ("group", "switch", "length", "if"):
                nest.append(t[0])
            elif t[0] == "end":
                nest.pop()
            elif t[0] == "field" and not nest:
                out[at] += "  " + t[1]
    return out


def ack_tail(w, short):
    """The optional reason code and properties of an acknowledgement (MQTT 5): chosen by the
    Remaining Length when it is one octet. `short` lists (length, reason code present) for the
    lengths that carry no property length; a longer packet carries both."""
    w.switch("remaining_length_c1")
    w.case("0")
    w.switch("remaining_length_v0")
    for length, reason in short:
        w.case(str(length))
        if reason:
            w.f("reason_code", 8)
        w.endcase()
    w.case("else")
    w.f("reason_code", 8)
    properties(w, "properties", lambda: None)
    w.endcase()
    w.endswitch()
    w.endcase()
    w.case("1")
    w.f("reason_code", 8)
    properties(w, "properties", lambda: None)
    w.endcase()
    w.endswitch()


MQTT_KEYS = [
    ("key", "packet_type", "int", "-", "the control packet type, 1 to 15"),
    ("key", "flags", "int", "-", "the four flag bits of the fixed header (0 or 2 by packet type; PUBLISH has its own)"),
] + [("key", "remaining_length_c%d" % i, "int", "-", "Remaining Length: continuation bit of octet %d (1 when another octet follows)" % i)
     for i in (1, 2, 3)] + [
    ("key", "remaining_length_v%d" % i, "int", "-", "Remaining Length: the 7 value bits of octet %d; the length is v0 + 128 v1 + 16384 v2 + 2097152 v3" % (i + 1))
    for i in range(4)] + [
    ("key", "octet", "int", "-", "one octet"),
    ("list", "protocol_name", None, None, "CONNECT: the protocol name, as its UTF-8 octets (MQTT)"),
    ("key", "protocol_level", "int", "-", "CONNECT: protocol level, 4 for 3.1.1 and 5 for 5.0"),
    ("key", "username_flag", "int", "-", "CONNECT: 1 when a user name is in the payload"),
    ("key", "password_flag", "int", "-", "CONNECT: 1 when a password is in the payload"),
    ("key", "will_retain", "int", "-", "CONNECT: 1 when the will message is retained"),
    ("key", "will_qos", "int", "-", "CONNECT: QoS of the will message"),
    ("key", "will_flag", "int", "-", "CONNECT: 1 when the payload holds a will"),
    ("key", "clean_start", "int", "-", "CONNECT: clean session (3.1.1) or clean start (5.0)"),
    ("key", "connect_reserved", "int", "-", "CONNECT: reserved flag, 0"),
    ("key", "keep_alive", "int", "s", "CONNECT: the longest gap in seconds between two packets from the client"),
    ("list", "client_id", None, None, "CONNECT: client identifier, as its UTF-8 octets"),
    ("list", "will_topic", None, None, "CONNECT: will topic, as its UTF-8 octets"),
    ("list", "will_payload", None, None, "CONNECT: will message, as its octets"),
    ("list", "username", None, None, "CONNECT: user name, as its UTF-8 octets"),
    ("list", "password", None, None, "CONNECT: password, as its octets"),
    ("key", "connack_reserved", "int", "-", "CONNACK: the seven reserved bits of the acknowledge flags, 0"),
    ("key", "session_present", "int", "-", "CONNACK: 1 when the server holds a session for the client"),
    ("key", "reason_code", "int", "-", "return code (3.1.1 CONNACK) or reason code (5.0): below 128 success, 128 and above failure"),
    ("key", "dup", "int", "-", "PUBLISH: 1 when this may be a resend"),
    ("key", "qos", "int", "-", "PUBLISH: quality of service, 0, 1 or 2"),
    ("key", "retain", "int", "-", "PUBLISH: 1 when the server is to retain the message"),
    ("list", "topic", None, None, "PUBLISH: topic name, as its UTF-8 octets"),
    ("key", "packet_id", "int", "-", "packet identifier (PUBLISH with QoS above 0, the acknowledgements, SUBSCRIBE, UNSUBSCRIBE and their acknowledgements)"),
    ("list", "payload", None, None, "PUBLISH: the application message, as its octets"),
    ("list", "subscriptions", None, None, "SUBSCRIBE: the topic filters and their options, in order"),
    ("list", "unsubscriptions", None, None, "UNSUBSCRIBE: the topic filters, in order"),
    ("list", "topic_filter", None, None, "a topic filter, as its UTF-8 octets"),
    ("key", "options_reserved", "int", "-", "SUBSCRIBE: reserved bits of the options octet, 0"),
    ("key", "retain_handling", "int", "-", "SUBSCRIBE (5.0): 0 send retained messages, 1 only for a new subscription, 2 never"),
    ("key", "retain_as_published", "int", "-", "SUBSCRIBE (5.0): 1 when forwarded messages keep their RETAIN flag"),
    ("key", "no_local", "int", "-", "SUBSCRIBE (5.0): 1 when the client's own messages are not sent back to it"),
    ("key", "requested_qos", "int", "-", "SUBSCRIBE: the highest QoS the client asks for"),
    ("list", "reason_codes", None, None, "SUBACK, UNSUBACK: the return or reason codes, one per filter"),
    ("key", "code", "int", "-", "one return or reason code"),
]
for lst, who in (("properties", "the packet's"), ("will_properties", "the will's")):
    MQTT_KEYS += [
        ("key", lst + "_length_c", "int", "-", "MQTT 5: continuation bit of the first octet of %s property length; 1 when the length takes more than one octet" % who),
        ("key", lst + "_length_low", "int", "-", "MQTT 5: when %s property length takes more than one octet, the 7 bits of its first octet" % who),
        ("list", lst, None, None, "MQTT 5: %s properties, in order" % who),
    ]
MQTT_KEYS += [
    ("key", "property_id", "int", "-", "MQTT 5 property identifier (all identifiers of 5.0 take one octet)"),
    ("key", "property_byte", "int", "-", "value of a property of one octet (identifiers 1, 23, 25, 36, 37, 40, 41, 42)"),
    ("key", "property_u16", "int", "-", "value of a property of two octets (19, 33, 34, 35)"),
    ("key", "property_u32", "int", "-", "value of a property of four octets (2, 17, 24, 39)"),
    ("list", "property_string", None, None, "value of a UTF-8 string property (3, 8, 18, 21, 26, 28, 31), as its octets"),
    ("list", "property_binary", None, None, "value of a binary property (9, 22), as its octets"),
    ("list", "property_name", None, None, "user property (38): its name, as its UTF-8 octets"),
    ("list", "property_value", None, None, "user property (38): its value, as its UTF-8 octets"),
] + [("key", "property_vbi_c%d" % i, "int", "-", "subscription identifier (11): continuation bit of octet %d" % i) for i in (1, 2, 3)] + [
    ("key", "property_vbi_v%d" % i, "int", "-", "subscription identifier (11): the 7 value bits of octet %d" % (i + 1)) for i in range(4)] + [
    ("list", "property_rest", None, None, "a property of an identifier 5.0 does not define, and the properties after it, as octets"),
    ("list", "packet_rest", None, None, "MQTT 5: when a property length takes more than one octet, the rest of the packet from its second octet, as octets"),
]


# ---------------------------------------------------------------- AMQP 1.0

def amqp_pack():
    w = W("amqp")
    for line in ["# AMQP 1.0 frame (OASIS standard, Part 2 Transport, sections 2.2 and 2.3): the protocol",
                 "# header, an empty frame, or a frame with its header, the descriptor of its performative and",
                 "# the rest of the body as octets. Public; the OASIS notice applies (packs/amqp10-frame/REUSE.toml).",
                 "# Written by tools/gen/messaging-pack.py; do not edit by hand. pack.md states what is not mapped.",
                 "format        amqp10-frame", "version       0.1.0", "distribution  public",
                 'source        "OASIS, Advanced Message Queuing Protocol (AMQP) Version 1.0, Part 2: Transport, OASIS Standard, 29 October 2012, https://docs.oasis-open.org/amqp/core/v1.0/os/amqp-core-transport-v1.0-os.xml (sha256 %s); layout restated"' % SHA["amqp"],
                 'source        "OASIS, AMQP Version 1.0, Part 1: Types, https://docs.oasis-open.org/amqp/core/v1.0/os/amqp-core-types-v1.0-os.xml (sha256 %s), the encodings of the descriptor"' % SHA["amqptypes"],
                 "uses          amqp", "wire          bits", "layout        sequential", "bit_order     msb", "",
                 "kind    protocol_header", "when    32  1095586128", "field  amqp.protocol_id  8  uint",
                 "field  amqp.major  8  uint", "field  amqp.minor  8  uint", "field  amqp.revision  8  uint", "",
                 "kind    empty_frame", "when    32  8", "field  amqp.doff  8  uint", "field  amqp.frame_type  8  uint",
                 "field  amqp.channel  16  uint", "",
                 "kind    frame", "length  32  whole", "field  amqp.doff  8  uint", "field  amqp.frame_type  8  uint",
                 "field  amqp.channel  16  uint"]:
        w(line)
    w.switch("doff")
    w.case("2")
    w.f("descriptor_marker", 8)
    w.f("descriptor_constructor", 8)
    w.switch("descriptor_constructor")
    w.case("83")
    w.f("performative", 8)
    w.endcase()
    w.case("128")
    w.f("performative", 64)
    w.endcase()
    w.case("else")
    w.endcase()
    w.endswitch()
    w.octets("body")
    w.endcase()
    w.case("else")
    w.octets("extended_header_and_body")
    w.endcase()
    w.endswitch()
    return "\n".join(w.lines) + "\n"


AMQP_KEYS = [
    ("key", "protocol_id", "int", "-", "protocol header: 0 AMQP, 2 TLS, 3 SASL"),
    ("key", "major", "int", "-", "protocol header: major version, 1"),
    ("key", "minor", "int", "-", "protocol header: minor version, 0"),
    ("key", "revision", "int", "-", "protocol header: revision, 0"),
    ("key", "doff", "int", "-", "frame: data offset, the size of the frame header in 4-octet words, at least 2"),
    ("key", "frame_type", "int", "-", "frame: type, 0 AMQP, 1 SASL"),
    ("key", "channel", "int", "-", "frame: channel number (AMQP frames); type-specific in other frames"),
    ("key", "descriptor_marker", "int", "-", "frame body: the constructor of a described type, 0"),
    ("key", "descriptor_constructor", "int", "-", "frame body: the encoding of the descriptor, 83 (0x53, smallulong) or 128 (0x80, ulong)"),
    ("key", "performative", "int", "-", "frame body: the descriptor code: 16 open, 17 begin, 18 attach, 19 flow, 20 transfer, 21 disposition, 22 detach, 23 end, 24 close; 64-68 the SASL frames"),
    ("key", "octet", "int", "-", "one octet"),
    ("list", "body", None, None, "frame body after the descriptor: the performative's field list and any payload, as octets"),
    ("list", "extended_header_and_body", None, None, "a frame whose data offset is not 2: its extended header and body, as octets"),
]


# ---------------------------------------------------------------- STUN and TURN

def address(w, p):
    w("pad  8")
    w.f(p + "family", 8)
    w.f(p + "port", 16)
    w.switch(p + "family")
    w.case("1")
    w.f(p + "ipv4", 32)
    w.endcase()
    w.case("2")
    w.f(p + "ipv6", 128, "hex")
    w.endcase()
    w.case("else")
    w.octets("attr_value")
    w.endcase()
    w.endswitch()


def stun_pack():
    w = W("stun")
    for line in ["# STUN message (RFC 8489) with the TURN attributes (RFC 8656), and the TURN ChannelData",
                 "# message (RFC 8656 section 12.4). Public. Written by tools/gen/messaging-pack.py; do not edit",
                 "# by hand. Wire bits, layout sequential, msb; I/O is hex text. pack.md states what is mapped.",
                 "format        stun", "version       0.1.0", "distribution  public",
                 'source        "IETF RFC 8489, Session Traversal Utilities for NAT (STUN), February 2020, https://www.rfc-editor.org/rfc/rfc8489.txt (sha256 %s); layout restated"' % SHA["rfc8489"],
                 'source        "IETF RFC 8656, Traversal Using Relays around NAT (TURN), February 2020, https://www.rfc-editor.org/rfc/rfc8656.txt (sha256 %s); layout restated"' % SHA["rfc8656"],
                 "uses          stun", "wire          bits", "layout        sequential", "bit_order     msb", "",
                 "kind    message", "when    2  0", "requires  stun.message_type  stun.magic_cookie  stun.transaction_id", "field  stun.message_type  14  uint",
                 "length  16  bytes  plus  -16", "  field  stun.magic_cookie  32  uint",
                 "  field  stun.transaction_id  96  hex", "  group  stun.attributes  rest"]:
        w(line)
    w.ind = 2
    w.f("attr_type", 16)
    w.block("length  16  bytes")
    w.switch("attr_type")
    cases = [
        ("1,32,18,22,32803", lambda: address(w, "")),          # MAPPED, XOR-MAPPED, XOR-PEER, XOR-RELAYED, ALTERNATE-SERVER
        ("9", lambda: (w("pad  21"), w.f("error_class", 3), w.f("error_number", 8), w.octets("attr_value"))),
        ("32769", lambda: (w.f("error_family", 8), w("pad  13"), w.f("error_class", 3), w.f("error_number", 8),
                           w.octets("attr_value"))),
        ("8", lambda: w.f("integrity", 160, "hex")),
        ("32808", lambda: w.f("fingerprint", 32)),
        ("10", lambda: (w.block("group  stun.unknown_attributes  rest"), w.f("unknown_type", 16), w.end())),
        ("12", lambda: (w.f("channel_number", 16), w("pad  16"))),
        ("13", lambda: w.f("lifetime", 32)),
        ("23,32768", lambda: (w.f("requested_family", 8), w("pad  24"))),
        ("24", lambda: (w.f("even_port_r", 1), w("pad  7"))),
        ("25", lambda: (w.f("requested_transport", 8), w("pad  24"))),
        ("26", lambda: None),
        ("34", lambda: w.f("reservation_token", 64, "hex")),
        ("32772", lambda: (w("pad  16"), w.f("icmp_type", 8), w.f("icmp_code", 8), w.f("icmp_error_data", 32))),
    ]
    for vals, body in cases:
        w.case(vals)
        body()
        w.endcase()
    w.case("else")
    w.octets("attr_value")
    w.endcase()
    w.endswitch()
    w.end()
    w("align  32")
    w.ind = 1
    w("end")
    w.ind = 0
    w("end")
    for line in ["", "kind    channel_data", "when    2  1", "requires  stun.channel_low", "field  stun.channel_low  14  uint",
                 "length  16  bytes", "  group  stun.data  rest", "    field  stun.octet  8  uint", "  end", "end"]:
        w(line)
    return "\n".join(w.lines) + "\n"


STUN_KEYS = [
    ("key", "message_type", "int", "-", "the 14 bits of the message type: method and class interleaved (0x0001 Binding request, 0x0101 Binding success response, 0x0111 Binding error response, 0x0003 Allocate request, ...)"),
    ("key", "magic_cookie", "int", "-", "magic cookie, 0x2112A442 (554869826)"),
    ("key", "transaction_id", "string", "-", "transaction ID, 96 bits as 24 hexadecimal digits"),
    ("list", "attributes", None, None, "the attributes, in order"),
    ("key", "attr_type", "int", "-", "attribute type: 0x0001 MAPPED-ADDRESS, 0x0006 USERNAME, 0x0008 MESSAGE-INTEGRITY, 0x0009 ERROR-CODE, 0x000A UNKNOWN-ATTRIBUTES, 0x0014 REALM, 0x0015 NONCE, 0x0020 XOR-MAPPED-ADDRESS, 0x8022 SOFTWARE, 0x8023 ALTERNATE-SERVER, 0x8028 FINGERPRINT; TURN 0x000C to 0x8004"),
    ("key", "family", "int", "-", "address attribute: family, 1 IPv4, 2 IPv6"),
    ("key", "port", "int", "-", "address attribute: the port as on the wire (in the XOR attributes the port XORed with 0x2112)"),
    ("key", "ipv4", "int", "-", "address attribute: the IPv4 address as on the wire, as an unsigned 32-bit integer (in the XOR attributes XORed with the magic cookie)"),
    ("key", "ipv6", "string", "-", "address attribute: the IPv6 address as on the wire, 32 hexadecimal digits (in the XOR attributes XORed with the magic cookie and transaction ID)"),
    ("key", "error_family", "int", "-", "ADDRESS-ERROR-CODE: the address family the error is about, 1 IPv4, 2 IPv6"),
    ("key", "error_class", "int", "-", "ERROR-CODE and ADDRESS-ERROR-CODE: the hundreds digit of the code, 3 to 6"),
    ("key", "error_number", "int", "-", "ERROR-CODE and ADDRESS-ERROR-CODE: the code modulo 100"),
    ("key", "integrity", "string", "-", "MESSAGE-INTEGRITY: the HMAC-SHA1, 40 hexadecimal digits"),
    ("key", "fingerprint", "int", "-", "FINGERPRINT: CRC-32 of the message up to this attribute, XORed with 0x5354554E"),
    ("list", "unknown_attributes", None, None, "UNKNOWN-ATTRIBUTES: the types the server did not understand"),
    ("key", "unknown_type", "int", "-", "one attribute type"),
    ("key", "channel_number", "int", "-", "CHANNEL-NUMBER: the channel, 0x4000 to 0x4FFF"),
    ("key", "lifetime", "int", "s", "LIFETIME: seconds until the allocation expires"),
    ("key", "requested_family", "int", "-", "REQUESTED-ADDRESS-FAMILY and ADDITIONAL-ADDRESS-FAMILY: 1 IPv4, 2 IPv6"),
    ("key", "even_port_r", "int", "-", "EVEN-PORT: R bit, 1 to reserve the next port too"),
    ("key", "requested_transport", "int", "-", "REQUESTED-TRANSPORT: IP protocol number, 17 UDP"),
    ("key", "reservation_token", "string", "-", "RESERVATION-TOKEN: 64 bits as 16 hexadecimal digits"),
    ("key", "icmp_type", "int", "-", "ICMP: the ICMP type"),
    ("key", "icmp_code", "int", "-", "ICMP: the ICMP code"),
    ("key", "icmp_error_data", "int", "-", "ICMP: error data (the next-hop MTU for a packet-too-big error)"),
    ("list", "attr_value", None, None, "value of an attribute the pack keeps as octets (USERNAME, REALM, NONCE, SOFTWARE, DATA, the reason phrase of an error and others)"),
    ("key", "octet", "int", "-", "one octet"),
    ("key", "channel_low", "int", "-", "ChannelData: the 14 low bits of the channel number (the two high bits are 01)"),
    ("list", "data", None, None, "ChannelData: the application data, as octets"),
]


def module_text(name, header, keys):
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public"]
    w = max(len(k[1]) for k in keys)
    out = []
    for kind, n, vt, unit, meaning in keys:
        if kind == "list":
            out.append('list  %-*s  "%s"' % (w, n, meaning))
        else:
            out.append('key   %-*s  %-6s  %-1s  "%s"' % (w, n, vt, unit, meaning))
    return L, out


def build(out):
    out.write("packs/mqtt311/pack.def", mqtt_pack(False))
    out.write("packs/mqtt5/pack.def", mqtt_pack(True))
    out.write("packs/amqp10-frame/pack.def", amqp_pack())
    out.write("packs/stun/pack.def", stun_pack())
    for name, header, src, keys in (
            ("mqtt", ["# The mqtt module: the fields of MQTT 3.1.1 and 5.0 control packets (OASIS). Written by",
                      "# tools/gen/messaging-pack.py; do not edit by hand. Strings are lists of their octets."],
             'source        "OASIS MQTT Version 3.1.1 and MQTT Version 5.0; restated by goat-transformers"', MQTT_KEYS),
            ("amqp", ["# The amqp module: the fields of the AMQP 1.0 frame header and performative descriptor",
                      "# (OASIS). Written by tools/gen/messaging-pack.py; do not edit by hand."],
             'source        "OASIS AMQP Version 1.0, Parts 1 and 2; restated by goat-transformers"', AMQP_KEYS),
            ("stun", ["# The stun module: the fields of STUN messages (RFC 8489), the TURN attributes and the",
                      "# ChannelData message (RFC 8656). Written by tools/gen/messaging-pack.py; do not edit by hand."],
             'source        "IETF RFC 8489 (STUN) and RFC 8656 (TURN); restated by goat-transformers"', STUN_KEYS)):
        head, body = module_text(name, header, keys)
        out.write("model/%s.def" % name, "\n".join(head + [src] + body) + "\n")
    return {"messaging": 7}


def main(argv=None):
    return genio.vector_main("messaging-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
