#!/usr/bin/env python3
"""Generate the goat-transformers pack `mavlink2` from the MAVLink XML definitions.

Reads   <out>/sources/{common,standard,minimal}.xml and <out>/sources/PROVENANCE.md
Writes  <out>/model/mavlink.def
        <out>/packs/mavlink2/pack.def
        <out>/packs/mavlink2/pack.md
        <out>/packs/mavlink2/vectors/*.json

The run has four stages, each a set of functions that can be called alone:

  parse   `load_messages`: the XML files as SourceMessage and SourceField records
  plan    `make_plan`: wire layout (`lay_out`), model keys (`assign_keys`) and
          `requires` (`choose_requires`) of every kind, with every decision made
  emit    `emit_model`, `emit_pack`, `vector_files`, `emit_pack_md`: text only
  check   the module and the pack are loaded by gtcheck (the rules of
          spec/engine-spec.md), `check_frame_invariants` holds the pack to the
          MAVLink 2 frame, and `check_vectors` decodes and encodes every vector
          with the small codec in this file

Guarantees: the same inputs give the same bytes; a source file whose SHA-256
differs from PROVENANCE.md is refused; exit status 0 only when every check
passed, 1 for a refused input or a failed check, 2 for a usage error.

Python 3 standard library only.

With --dialect NAME (a dialect file name without `.xml`) the run writes the
pack `mavlink2-<name in lower case>` instead: the messages NAME.xml itself
defines, payload keys in module `mavlink<name>`, the frame-header keys of
module `mavlink` (so model/mavlink.def must exist). Every message id and name
of the whole include closure must be unique. Sources come from --src (default
<out>/sources) and the SHA-256 table from --provenance (default
<src>/PROVENANCE.md; with --dialect <out>/packs/<format>/PROVENANCE.md).

--max-array N maps non-char arrays of up to N elements, one key per element
(default 8, as version 0.1.0); --compat-flags maps the INCOMPAT and COMPAT
bytes (default: not mapped).

Usage: mavlink2pack.py [--out DIR] [--check] [--core-def PATH/model/core.def]
                       [--dialect NAME] [--src DIR] [--provenance FILE]
                       [--max-array N] [--compat-flags]
"""
import argparse
import collections
import hashlib
import json
import math
import os
import re
import struct
import sys
from decimal import Decimal
from xml.parsers import expat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402  (the script directory is not on the path under `python3 -I`)
import gtcheck    # noqa: E402

NAME = "mavlink2pack"
FORMAT = "mavlink2"
PACK_VERSION = "0.1.0"
MODULE = "mavlink"
XML_FILES = ["common.xml", "standard.xml", "minimal.xml"]
ROOT_XML = "common.xml"
REPO = "https://github.com/mavlink/mavlink"
XML_DIR = "message_definitions/v1.0"

SOURCE_DIR = "sources"
MODEL_PATH = "model/%s.def" % MODULE
PACK_DIR = "packs/%s" % FORMAT
PACK_PATH = PACK_DIR + "/pack.def"
PACK_MD_PATH = PACK_DIR + "/pack.md"
VECTOR_DIR = PACK_DIR + "/vectors"

# MAVLink 2 frame: STX LEN INCOMPAT COMPAT SEQ SYSID COMPID MSGID(3, LE) PAYLOAD CRC(2).
# A location is (first bit counted from the STX byte, length in bits).
STX = 0xFD
HEADER_BYTES = 10
PAYLOAD_BIT0 = HEADER_BYTES * 8
LOC_STX = (0, 8)
LOC_LEN = (8, 8)
LOC_SEQ = (32, 8)
LOC_SYSID = (40, 8)
LOC_COMPID = (48, 8)
LOC_MSGID = (56, 24)
LOC_INCOMPAT = (16, 8)
LOC_COMPAT = (24, 8)
COMMON_KEYS = [("seq", LOC_SEQ, "frame sequence number of the sending component, 0..255"),
               ("sysid", LOC_SYSID, "system id of the sender"),
               ("compid", LOC_COMPID, "component id of the sender")]
# The flag bytes, mapped with --compat-flags after the three keys above.
FLAG_KEYS = [("incompat_flags", LOC_INCOMPAT, "incompatibility flags; bit 0x01 means the frame is signed"),
             ("compat_flags", LOC_COMPAT, "compatibility flags")]
# The frame-header names a payload key may not take (the rule that named the
# keys of version 0.1.0).
NAMING_RESERVED = ("seq", "sysid", "compid")
HEADER_MODULE = "mavlink"     # module of the frame-header keys, in every MAVLink pack
DIALECT = None                # --dialect

MAX_ARRAY_ELEMENTS = 8        # longer non-char arrays are named in a pass of their own
MAX_ARRAY = 8                 # --max-array: longer non-char arrays are not mapped
FLAGS = False                 # --compat-flags
LEGACY = True                 # neither option: the output of version 0.1.0
MAX_REQUIRES = 6
DEGE7 = "1/10000000"         # engine-spec 0.5 ruling 1: a power-of-ten scale is a fraction

# What the pack is checked against when --core-def is not given: a module that
# declares the only two core keys this pack maps.
CORE_STAND_IN = ("module core\nversion 0.0.0\ndistribution public\n"
                 'source "stand-in for model/core.def: the two core keys the mavlink2 pack maps"\n'
                 "key lat float deg\nkey lon float deg\n")

TYPE_RE = re.compile(r"^(char|u?int(?:8|16|32|64)_t|float|double)(?:\[(\d+)\])?$")
SIZES = {"char": 1, "uint8_t": 1, "int8_t": 1, "uint16_t": 2, "int16_t": 2,
         "uint32_t": 4, "int32_t": 4, "float": 4, "uint64_t": 8, "int64_t": 8,
         "double": 8}
STRUCT_CODES = {"uint8_t": "B", "int8_t": "b", "uint16_t": "H", "int16_t": "h",
                "uint32_t": "I", "int32_t": "i", "uint64_t": "Q", "int64_t": "q",
                "float": "f", "double": "d"}

# CRC_EXTRA values fixed by the protocol; a wrong field order changes them.
KNOWN_CRC_EXTRA = {"HEARTBEAT": 50, "SYS_STATUS": 124, "ATTITUDE": 39,
                   "GLOBAL_POSITION_INT": 104, "GPS_RAW_INT": 24,
                   "COMMAND_LONG": 152}

# The transforms the codec of this file implements; the pack uses no other.
CODEC_TRANSFORMS = ("uint", "twos", "uscale", "sscale", "f32", "f64", "ascii")
KIND_NAME_RE = re.compile(r"^[a-z0-9_]+$")



# Dialects: CRC_EXTRA and full payload length of every message a dialect file
# defines, by message id, as the C library that the MAVLink project generates
# from the same definitions states them (github.com/mavlink/c_library_v2,
# <dialect>/<dialect>.h, MAVLINK_MESSAGE_CRCS; commit in each PROVENANCE.md).
# The generator computes both from the XML and stops when one differs.
KNOWN_DIALECT = {
    "ardupilotmega": {150: (134, 42), 151: (219, 8), 152: (208, 8), 153: (188, 12),
        154: (84, 15), 155: (22, 13), 156: (19, 6), 157: (21, 15), 158: (134, 15),
        160: (78, 12), 161: (68, 3), 163: (127, 28), 164: (154, 44), 165: (21, 3),
        166: (21, 9), 167: (144, 22), 168: (1, 12), 169: (234, 18), 170: (73, 34),
        171: (181, 66), 172: (22, 98), 173: (83, 8), 174: (167, 48), 175: (138, 19),
        176: (234, 3), 177: (240, 20), 178: (47, 24), 179: (189, 29), 180: (52, 47),
        181: (174, 4), 182: (229, 40), 183: (85, 2), 184: (159, 206), 185: (186, 7),
        186: (72, 29), 191: (92, 27), 193: (71, 26), 194: (98, 33), 195: (120, 37),
        200: (134, 42), 201: (205, 14), 214: (69, 8), 215: (101, 3), 216: (50, 3),
        217: (202, 6), 218: (17, 7), 219: (162, 2), 226: (207, 8), 11000: (134, 52),
        11001: (15, 136), 11002: (234, 180), 11003: (64, 5), 11004: (11, 232),
        11005: (93, 230), 11010: (46, 49), 11011: (106, 44), 11020: (205, 16),
        11030: (144, 44), 11031: (133, 44), 11032: (85, 44), 11033: (195, 37),
        11034: (79, 5), 11035: (128, 8), 11036: (177, 34), 11037: (130, 28),
        11038: (47, 38), 11039: (142, 9), 11040: (132, 44), 11041: (208, 44),
        11042: (201, 44), 11043: (193, 44), 11044: (189, 44), 11060: (162, 78)},
    "ASLUAV": {223: (119, 47), 224: (102, 45), 8002: (218, 16), 8003: (231, 41),
        8004: (172, 98), 8005: (251, 38), 8006: (97, 14), 8007: (64, 32), 8008: (234, 33),
        8009: (144, 16), 8010: (155, 41), 8011: (20, 102), 8012: (54, 16), 8013: (222, 46),
        8014: (200, 14), 8015: (23, 24), 8016: (149, 18)},
    "AVSSUAS": {60050: (220, 14), 60051: (245, 24), 60052: (101, 44), 60053: (45, 6)},
    "csAirLink": {52000: (13, 100), 52001: (239, 1)},
    "cubepilot": {50001: (246, 32), 50002: (181, 246), 50003: (62, 19), 50004: (240, 10),
        50005: (152, 6)},
    "development": {354: (210, 14), 355: (6, 12), 369: (145, 27), 414: (109, 16),
        415: (161, 16), 421: (149, 70), 441: (169, 17), 510: (245, 106), 511: (28, 71),
        512: (21, 12), 292: (227, 223), 513: (99, 45), 514: (197, 54), 515: (128, 3),
        442: (189, 49), 516: (125, 35), 517: (126, 10)},
    "icarous": {42000: (227, 1), 42001: (239, 46)},
    "loweheiser": {10151: (195, 85)},
    "marsh": {52501: (240, 17), 52502: (88, 78), 52503: (96, 85), 52504: (177, 28),
        52505: (215, 50)},
    "paparazzi": {180: (231, 54), 181: (129, 4), 182: (115, 2), 183: (186, 4),
        184: (40, 2)},
    "stemstudios": {52600: (181, 38), 52601: (102, 36)},
    "storm32": {60010: (208, 33), 60011: (183, 7), 60012: (99, 36), 60013: (129, 24),
        60014: (134, 8), 60020: (202, 4), 60000: (4, 22), 60040: (156, 245),
        60041: (191, 255), 60045: (14, 23), 60046: (171, 28), 60047: (55, 7)},
    "uAvionix": {10001: (209, 20), 10002: (186, 41), 10003: (4, 1), 10004: (133, 9),
        10005: (103, 9), 10006: (193, 4), 10007: (71, 17), 10008: (240, 14)},
}

# What the position of each message that binds core lat/lon is, in this
# project's words, from the message's description in the dialect file.
POSITION_NOTES = {
    "SIMSTATE": "the vehicle in the simulation environment (simulator state, not a measurement)",
    "RALLY_POINT": "a rally point sent to or read from the vehicle, not the vehicle",
    "AHRS2": "the vehicle, as the secondary attitude and heading filter estimates it",
    "CAMERA_FEEDBACK": "the vehicle when the camera captured an image",
    "AHRS3": "the vehicle, as the third attitude and heading filter estimates it",
    "WATER_DEPTH": "the vehicle when the water depth was measured",
    "AVSS_DRONE_POSITION": "the drone",
    "TARGET_ABSOLUTE": "a target observed by the vehicle's sensors, not the vehicle (WGS84 stated)",
}

# Cross-format cases per dialect, as CROSS below. `expect` is written by hand
# from the field values: degrees = value / 10^7, GeoJSON coordinates are
# [lon, lat], `properties` empty.
CROSS_DIALECT = {
    "ardupilotmega": [
        ("AHRS2", 21, 1, 1,
         {"roll": 0.5, "pitch": -0.25, "yaw": 1.5, "altitude": 120.5,
          "lat": 473977420, "lng": 85455940},
         '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.545594,47.397742]},"properties":{}}'),
        ("WATER_DEPTH", 22, 2, 194,
         {"time_boot_ms": 60000, "id": 1, "healthy": 1, "lat": -338568000, "lng": 1512153000,
          "alt": -2.5, "roll": 0.0, "pitch": 0.0, "yaw": 0.75, "distance": 12.25,
          "temperature": 18.5},
         '{"type":"Feature","geometry":{"type":"Point","coordinates":[151.2153,-33.8568]},"properties":{}}'),
        ("RALLY_POINT", 23, 255, 190,
         {"target_system": 1, "target_component": 1, "idx": 0, "count": 1,
          "lat": -900000000, "lng": 1800000000, "alt": 80, "break_alt": 40,
          "land_dir": 27000, "flags": 0},
         '{"type":"Feature","geometry":{"type":"Point","coordinates":[180,-90]},"properties":{}}'),
    ],
    "AVSSUAS": [
        ("AVSS_DRONE_POSITION", 31, 1, 1,
         {"time_boot_ms": 5000, "lat": 515007000, "lon": -1246000, "alt": 35000,
          "ground_alt": 30.5, "barometer_alt": 31.25},
         '{"type":"Feature","geometry":{"type":"Point","coordinates":[-0.1246,51.5007]},"properties":{}}'),
    ],
    "development": [
        ("TARGET_ABSOLUTE", 41, 1, 1,
         {"timestamp": 1700000000000000, "id": 3, "sensor_capabilities": 1,
          "lat": 356762000, "lon": 1396503000, "alt": 40.0,
          "vel": [1.0, 0.5, 0.0], "acc": [0.0, 0.0, 0.0], "q_target": [1.0, 0.0, 0.0, 0.0],
          "rates": [0.0, 0.0, 0.0], "position_std": [2.5, 2.5], "vel_std": [0.5, 0.5, 0.5],
          "acc_std": [0.25, 0.25, 0.25]},
         '{"type":"Feature","geometry":{"type":"Point","coordinates":[139.6503,35.6762]},"properties":{}}'),
    ],
}


class GenError(Exception):
    """A refused input or a failed check. `file` and `line` say where, when the
    error belongs to a place in a source file or in a generated file."""

    def __init__(self, message, file=None, line=None):
        self.message, self.file, self.line = message, file, line
        super().__init__(message, file, line)

    def __str__(self):
        if self.file is None:
            return self.message
        if self.line is None:
            return "%s: %s" % (self.file, self.message)
        return "%s:%d: %s" % (self.file, self.line, self.message)


class CodecError(Exception):
    """A message the codec cannot decode or an entity it cannot encode; the
    text is the error kind of the specification (`no-kind`, `malformed-wire`,
    `transform-decode`, `transform-encode`)."""


def set_names(fmt, module):
    """Point the format, module and output paths at one pack."""
    global FORMAT, MODULE, MODEL_PATH, PACK_DIR, PACK_PATH, PACK_MD_PATH, VECTOR_DIR
    FORMAT, MODULE = fmt, module
    MODEL_PATH = "model/%s.def" % MODULE
    PACK_DIR = "packs/%s" % FORMAT
    PACK_PATH = PACK_DIR + "/pack.def"
    PACK_MD_PATH = PACK_DIR + "/pack.md"
    VECTOR_DIR = PACK_DIR + "/vectors"


def source_label(name):
    """How an error names a source file: its path below the --out directory."""
    return "%s/%s" % (SOURCE_DIR, name)


# ------------------------------------------------------------------ parse ---

class SourceField(collections.namedtuple("SourceField", "name base n units enum invalid ext line")):
    """One <field> of a message. `base` is the element type, `n` the array
    length (None for a scalar), `ext` is true after <extensions/>, `line` the
    line of the element in its file."""
    __slots__ = ()

    @property
    def size(self):
        """Bytes of one element."""
        return SIZES[self.base]

    @property
    def bytes(self):
        """Bytes of the whole field in the payload."""
        return self.size * (self.n or 1)

    @property
    def is_array(self):
        """True for `type[n]` of a numeric type; `char[n]` is one text value."""
        return self.n is not None and self.base != "char"


SourceMessage = collections.namedtuple("SourceMessage", "name id fields file line marks",
                                       defaults=((),))
SourceMessage.__doc__ = """One <message>: its name, id, fields in declaration order, the name of the
file that declares it, the line of the element, and `marks`: the names of
its <wip/> and <deprecated> children."""


def read_provenance(src, path=None):
    """The commit PROVENANCE.md states, after checking that every XML file has
    the SHA-256 its table row states. `path` is the PROVENANCE.md to read
    (default: the one in `src`)."""
    label = path or source_label("PROVENANCE.md")
    with open(path or os.path.join(src, "PROVENANCE.md"), encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"Commit: `([0-9a-f]{40})`", text)
    if not m:
        raise GenError("no `Commit:` line with a 40-hex SHA", label)
    for name in XML_FILES:
        row = re.search(r"\| `%s` \|[^|]*\| `([0-9a-f]{64})` \|" % re.escape(name), text)
        if not row:
            raise GenError("no SHA-256 row for %s" % name, label)
        with open(os.path.join(src, name), "rb") as fh:
            got = hashlib.sha256(fh.read()).hexdigest()
        if got != row.group(1):
            raise GenError("does not match the SHA-256 in PROVENANCE.md", source_label(name))
    return m.group(1)


def parse_field(attrs, message_name, ext, label, line):
    """A SourceField from the attributes of a <field> element."""
    name, text = attrs.get("name"), attrs.get("type")
    if not name or text is None:
        raise GenError("%s: a field has no name or no type" % message_name, label, line)
    if text == "uint8_t_mavlink_version":       # the protocol version byte is a uint8_t on the wire
        text = "uint8_t"
    tm = TYPE_RE.match(text)
    if not tm:
        raise GenError("%s.%s: unknown type %s" % (message_name, name, text), label, line)
    base, n = tm.group(1), int(tm.group(2)) if tm.group(2) else None
    if n == 0 or (base == "char" and n is None):
        raise GenError("%s.%s: type %s has no length" % (message_name, name, text), label, line)
    return SourceField(name, base, n, attrs.get("units"), attrs.get("enum"), attrs.get("invalid"), ext, line)


class _OpenElement:
    """An element the parser is inside. `message` is set for a <message>;
    `text` collects character data until the first child element starts and
    is None for an element whose text is not read."""
    __slots__ = ("tag", "message", "text")

    def __init__(self, tag, message=None, text=None):
        self.tag, self.message, self.text = tag, message, text


class _MessageDraft:
    """A <message> while its children are read."""
    __slots__ = ("name", "id", "fields", "line", "in_extensions", "marks")

    def __init__(self, name, msgid, line):
        self.name, self.id, self.line = name, msgid, line
        self.fields, self.in_extensions, self.marks = [], False, []


class _DialectReader:
    """The expat handlers that collect, from one dialect file, the <include>
    children of the root element and every <message> with its <field> and
    <extensions/> children. Other elements (enums, descriptions) are skipped."""

    def __init__(self, parser, label):
        self.parser, self.label = parser, label
        self.includes = []
        self.messages = []          # _MessageDraft, in document order
        self.stack = []             # _OpenElement, the root first

    def start(self, tag, attrs):
        line = self.parser.CurrentLineNumber
        parent = self.stack[-1] if self.stack else None
        element = _OpenElement(tag)
        if parent is not None:
            parent.text = None                  # text after a child element is not the element's text
        if tag == "message":
            element.message = _MessageDraft(self._message_name(attrs, line), self._message_id(attrs, line), line)
            self.messages.append(element.message)
        elif tag == "include" and len(self.stack) == 1:
            element.text = []
        elif parent is not None and parent.message is not None:
            message = parent.message
            if tag == "extensions":
                message.in_extensions = True
            elif tag in ("wip", "deprecated"):
                message.marks.append(tag)
            elif tag == "field":
                message.fields.append(parse_field(attrs, message.name, message.in_extensions, self.label, line))
        self.stack.append(element)

    def text(self, data):
        if self.stack and self.stack[-1].text is not None:
            self.stack[-1].text.append(data)

    def end(self, tag):
        element = self.stack.pop()
        if element.tag == "include" and len(self.stack) == 1:
            name = "".join(element.text or ()).strip()
            if not name:
                raise GenError("an <include> names no file", self.label, self.parser.CurrentLineNumber)
            self.includes.append(name)

    def _message_name(self, attrs, line):
        if not attrs.get("name"):
            raise GenError("a message has no name", self.label, line)
        return attrs["name"]

    def _message_id(self, attrs, line):
        try:
            return int(attrs.get("id", ""))
        except ValueError:
            raise GenError("%s: id `%s` is not a number" % (attrs.get("name"), attrs.get("id")),
                           self.label, line) from None


def parse_dialect(data, file_name):
    """One dialect file (bytes) -> (names of the files it includes, its
    SourceMessage records in document order).

    Read as the MAVLink schema states: <include> elements are children of the
    root; a <message> has `id` and `name`; its <field> children have `type`,
    `name` and optional `units`, `enum` and `invalid`; a field after
    <extensions/> is an extension field."""
    label = source_label(file_name)
    # The separator keeps an element of an XML namespace from being read as a
    # MAVLink element of the same local name.
    parser = expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True
    reader = _DialectReader(parser, label)
    parser.StartElementHandler = reader.start
    parser.EndElementHandler = reader.end
    parser.CharacterDataHandler = reader.text
    try:
        parser.Parse(data, True)
    except expat.ExpatError as e:
        raise GenError("not well-formed XML: %s (column %d)" % (expat.ErrorString(e.code), e.offset),
                       label, e.lineno) from None
    return reader.includes, [SourceMessage(m.name, m.id, tuple(m.fields), file_name, m.line, tuple(m.marks))
                             for m in reader.messages]


def load_messages(src):
    """Every message of ROOT_XML and of the files it includes, in id order
    (with --dialect: only the messages of ROOT_XML). Refuses an include chain
    that is not exactly XML_FILES, and two messages with one id or one name."""
    messages, seen = [], []

    def read(name):
        if name in seen:
            return
        seen.append(name)
        with open(os.path.join(src, name), "rb") as fh:
            includes, own = parse_dialect(fh.read(), name)
        for included in includes:
            read(included)
        messages.extend(own)

    read(ROOT_XML)
    if set(seen) != set(XML_FILES):
        raise GenError("include chain is %s, expected %s" % (sorted(seen), sorted(XML_FILES)),
                       source_label(ROOT_XML))
    by_id, by_name = {}, {}
    for m in messages:
        for what, value, known in (("id", m.id, by_id), ("name", m.name, by_name)):
            if value in known:
                first = known[value]
                raise GenError("message %s %s is also declared at %s:%d"
                               % (what, value, source_label(first.file), first.line),
                               source_label(m.file), m.line)
            known[value] = m
    if DIALECT:
        # a dialect pack holds only the messages its own file defines
        messages = [m for m in messages if m.file == ROOT_XML]
    return sorted(messages, key=lambda m: m.id)


def include_closure(src, top):
    """Every file `top` includes, directly or not, `top` first."""
    out = []

    def walk(name):
        if name in out:
            return
        out.append(name)
        with open(os.path.join(src, name), "rb") as fh:
            includes, _ = parse_dialect(fh.read(), name)
        for included in includes:
            walk(included)
    walk(top)
    return out


# ------------------------------------------------------------------- plan ---

Placed = collections.namedtuple("Placed", "field offset")
Placed.__doc__ = "A field and the byte offset of its first byte in the payload."

Layout = collections.namedtuple("Layout", "message wire length crc_extra")
Layout.__doc__ = """A message on the wire: its Placed fields in wire order, the full payload
length in bytes and its CRC_EXTRA."""

Line = collections.namedtuple("Line", "key pos bits transform")
Line.__doc__ = "One `field` line of the pack: model key, first bit, length in bits, transform."

MappedField = collections.namedtuple("MappedField", "field offset status lines")
MappedField.__doc__ = """A placed field with its mapping decided. `status` is `core`, `scalar`,
`ascii`, `elements` (one line per array element) or `unmapped` (no line)."""

KeyDecl = collections.namedtuple("KeyDecl", "type unit uses")
KeyDecl.__doc__ = "A key of module `mavlink`: type, unit and the (message, field) names that map it."

Assignment = collections.namedtuple("Assignment", "fields core_ok keys qualified")
Assignment.__doc__ = """The result of `assign_keys`. `fields[i]` and `core_ok[i]` belong to the i-th
layout; `keys` maps a key name to its KeyDecl in first-use order; `qualified`
maps (message name, field name) to the reason the key carries the message name."""


class KindPlan(collections.namedtuple("KindPlan", "message name length crc_extra core_ok fields "
                                                  "requires shadowed_by")):
    """Everything the emitters need for one kind. `core_ok` is false when
    `lat`/`lon` stay raw because the message has no other mappable field;
    `shadowed_by` names the messages that map every key this kind requires."""
    __slots__ = ()

    @property
    def raw_keys(self):
        return raw_keys(self.fields)

    @property
    def mapped_len(self):
        """Payload bytes up to the end of the last mapped field."""
        return max((f.offset + f.field.bytes for f in self.fields if f.status != "unmapped"), default=0)


Plan = collections.namedtuple("Plan", "kinds keys qualified")
Plan.__doc__ = "The kinds in id order, the module keys and the message-qualified fields."


def x25(data, crc=0xFFFF):
    """CRC-16/MCRF4XX as MAVLink uses it (initial value 0xFFFF, no final XOR)."""
    for b in data:
        tmp = b ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


def wire_order(fields):
    """MAVLink 2 wire order: the fields before <extensions/> by descending
    type size, fields of one size in declaration order; then the extension
    fields in declaration order. An array sorts by the size of its element."""
    base = [f for f in fields if not f.ext]
    return sorted(base, key=lambda f: -f.size) + [f for f in fields if f.ext]     # sorted() is stable


def crc_extra(message_name, fields):
    """CRC_EXTRA of a message: the X.25 checksum of the message name and of the
    type, name and array length of every non-extension field in wire order,
    folded to one byte. Extension fields are not part of it."""
    crc = x25((message_name + " ").encode())
    for f in wire_order(fields):
        if f.ext:
            continue
        crc = x25((f.base + " " + f.name + " ").encode(), crc)
        if f.n:
            crc = x25(bytes([f.n]), crc)
    return (crc & 0xFF) ^ (crc >> 8)


def lay_out(msg):
    """The Layout of a message: every field at its payload offset."""
    label = source_label(msg.file)
    wire, offset = [], 0
    for f in wire_order(msg.fields):
        wire.append(Placed(f, offset))
        offset += f.bytes
    if not 0 < offset <= 255:
        raise GenError("%s: payload length %d outside 1..255" % (msg.name, offset), label, msg.line)
    if not 0 <= msg.id < (1 << 24):
        raise GenError("%s: id out of range" % msg.name, label, msg.line)
    return Layout(msg, tuple(wire), offset, crc_extra(msg.name, msg.fields))


def slug(text):
    """A field name or a unit as part of a key name: lower case, `%` as `pct`,
    `/` as `_per_`, `*` as `_x`, `^` dropped, any other run of characters
    outside a-z and 0-9 as one `_`, no `_` at either end."""
    s = text.lower()
    for a, b in (("%", "pct"), ("/", "_per_"), ("*", "_x"), ("^", "")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def base_key(f):
    """The key name a field proposes: its name, then its unit unless the name
    is the unit or already ends with it."""
    name = slug(f.name)
    if f.units:
        u = slug(f.units)
        if u and name != u and not name.endswith("_" + u):
            name = name + "_" + u
    return name


def type_class(f):
    """The model type of a field's key: `string`, `float` or `int`."""
    if f.base == "char":
        return "string"
    if f.base in ("float", "double"):
        return "float"
    return "int"


def transform_for(f):
    """The bits transform of a raw field (engine-spec 0.2 and 0.5)."""
    if f.base == "char":
        return "ascii"
    if f.base == "float":
        return "f32"
    if f.base == "double":
        return "f64"
    return "uint" if f.base.startswith("u") else "twos"


LAT_NAMES = ("lat",)
LON_NAMES = ("lon", "lng")    # `lng` is the spelling of the ardupilotmega dialect


def is_core_latlon(f):
    """True for a position this pack can state as core `lat` or `lon`: an
    int32_t in degE7 with that name and no value that means unknown."""
    return (f.name in LAT_NAMES + LON_NAMES and f.units == "degE7" and f.base == "int32_t"
            and f.n is None and f.invalid is None)


def core_name(f):
    """The core key of a field is_core_latlon accepts."""
    return "lat" if f.name in LAT_NAMES else "lon"


def core_pair(layout):
    """A message maps core lat/lon only when it has exactly one qualifying
    latitude field and one qualifying longitude field."""
    c = collections.Counter(core_name(p.field) for p in layout.wire if is_core_latlon(p.field))
    return c["lat"] == 1 and c["lon"] == 1


def is_long_array(f):
    return f.is_array and f.n > MAX_ARRAY_ELEMENTS


def long_mapped(f):
    """An array longer than MAX_ARRAY_ELEMENTS that --max-array still maps."""
    return f.is_array and MAX_ARRAY_ELEMENTS < f.n <= MAX_ARRAY


def classify(layout):
    """(core_ok, the status of every field in wire order) of one message.

    A kind needs a raw key of its own for `requires`, so a message whose only
    mappable fields are lat and lon keeps them raw (core_ok is false)."""
    core_ok = any(not is_core_latlon(p.field) and not is_long_array(p.field) for p in layout.wire)
    pair = core_pair(layout)
    statuses = []
    for p in layout.wire:
        f = p.field
        if is_long_array(f):
            statuses.append("long" if long_mapped(f) else "unmapped")
        elif is_core_latlon(f) and core_ok and pair:
            statuses.append("core")
        elif f.is_array:
            statuses.append("elements")
        else:
            statuses.append("ascii" if f.base == "char" else "scalar")
    return core_ok, statuses


def _clash_reason(name, uses, reserved):
    """Why the fields that propose one key name cannot share it, or None.
    `uses` is [(message, field)]."""
    sigs = {(type_class(f), f.units, f.enum) for _, f in uses}
    per_message = collections.Counter(m.name for m, _ in uses)
    if name in reserved:
        return "same name as a frame-header key"
    if len({s[0] for s in sigs}) > 1:
        return "different types"
    if len({s[1] for s in sigs}) > 1:
        return "different units"
    if len(sigs) > 1:
        return "different enums"
    if max(per_message.values()) > 1:
        return "two fields of one message give the same name"
    return None


def assign_keys(layouts):
    """Decide every field's mapping and its model key; an Assignment.

    A key name is shared by every message whose field proposes it, as long as
    all of them agree on type class, units and enum, the name is not a
    frame-header key and no message proposes it twice. Otherwise every field
    that proposes the name takes its message name as a prefix."""
    classes = [classify(layout) for layout in layouts]

    # pass 1: the key names the raw fields propose, in first-appearance order
    proposals = collections.OrderedDict()         # key name -> [(message, field)]
    for layout, (_, statuses) in zip(layouts, classes):
        for placed, status in zip(layout.wire, statuses):
            f = placed.field
            if status == "elements":
                for i in range(f.n):
                    proposals.setdefault("%s_%d" % (base_key(f), i), []).append((layout.message, f))
            elif status in ("ascii", "scalar"):
                proposals.setdefault(base_key(f), []).append((layout.message, f))

    # pass 2: the fields whose proposed name cannot be shared
    reserved = set(NAMING_RESERVED)
    qualified = collections.OrderedDict()         # (message name, field name) -> reason
    for name, uses in proposals.items():
        reason = _clash_reason(name, uses, reserved)
        if reason:
            for m, f in uses:
                qualified[(m.name, f.name)] = reason

    # pass 3: declare the keys and write the lines
    keys = collections.OrderedDict()
    sig_of = {}                                   # key name -> (type class, units, enum)

    def declare(name, typ, unit, m, f):
        label = source_label(m.file)
        sig_of.setdefault(name, (type_class(f), f.units, f.enum))
        if name not in keys:
            keys[name] = KeyDecl(typ, unit, [])
        elif keys[name].type != typ or keys[name].unit != unit:
            raise GenError("%s.%s: key %s is already declared with another type or unit"
                           % (m.name, f.name, name), label, f.line)
        for other_message, other_field in keys[name].uses:
            if other_message == m.name:
                raise GenError("%s: fields %s and %s both give the key %s"
                               % (m.name, other_field, f.name, name), label, f.line)
        keys[name].uses.append((m.name, f.name))

    fields = []
    for layout, (_, statuses) in zip(layouts, classes):
        m, mapped = layout.message, []
        for placed, status in zip(layout.wire, statuses):
            f, lines = placed.field, []
            pos = PAYLOAD_BIT0 + 8 * placed.offset
            if status == "core":
                lines.append(Line(core_name(f), pos, 32, "sscale:" + DEGE7))
            elif status not in ("unmapped", "long"):
                stem = base_key(f)
                if (m.name, f.name) in qualified:
                    stem = kind_name(m) + "_" + stem
                unit = f.units or "-"
                if status == "elements":
                    for i in range(f.n):
                        key = "%s_%d" % (stem, i)
                        declare(key, type_class(f), unit, m, f)
                        lines.append(Line(MODULE + "." + key, pos + 8 * f.size * i, 8 * f.size,
                                          transform_for(f)))
                else:
                    declare(stem, type_class(f), unit, m, f)
                    lines.append(Line(MODULE + "." + stem, pos, 8 * f.bytes, transform_for(f)))
            mapped.append(MappedField(f, placed.offset, status, tuple(lines)))
        fields.append(mapped)

    # pass 4: arrays of more than MAX_ARRAY_ELEMENTS elements (--max-array),
    # named after every other key so that no key the earlier passes give
    # changes. A field's element names are shared only when every long use
    # agrees on type class, units and enum, no message has the stem twice and
    # every name that already exists has the same signature; otherwise the
    # field takes its message name as a prefix. Their keys come last.
    longs = collections.OrderedDict()             # stem -> [(message, field)]
    for layout, mapped in zip(layouts, fields):
        for mf in mapped:
            if mf.status == "long":
                longs.setdefault(base_key(mf.field), []).append((layout.message, mf.field))
    for stem, uses in longs.items():
        sigs = {(type_class(f), f.units, f.enum) for _, f in uses}
        names = {"%s_%d" % (stem, i) for _, f in uses for i in range(f.n)}
        reason = _clash_reason(stem, uses, ())
        if not reason and names & set(NAMING_RESERVED):
            reason = "same name as a frame-header key"
        if not reason and any(n in sig_of and sig_of[n] != next(iter(sigs)) for n in names):
            reason = "an existing key of that name differs"
        if reason:
            for m, f in uses:
                qualified[(m.name, f.name)] = reason
    for layout, mapped in zip(layouts, fields):
        m = layout.message
        for i, mf in enumerate(mapped):
            if mf.status != "long":
                continue
            f, pos, lines = mf.field, PAYLOAD_BIT0 + 8 * mf.offset, []
            stem = base_key(f)
            if (m.name, f.name) in qualified:
                stem = kind_name(m) + "_" + stem
            for j in range(f.n):
                key = "%s_%d" % (stem, j)
                if key in sig_of and sig_of[key] != (type_class(f), f.units, f.enum):
                    raise GenError("%s.%s: key %s is already declared with another meaning"
                                   % (m.name, f.name, key), source_label(m.file), f.line)
                declare(key, type_class(f), f.units or "-", m, f)
                lines.append(Line(MODULE + "." + key, pos + 8 * f.size * j, 8 * f.size, transform_for(f)))
            mapped[i] = MappedField(f, mf.offset, "elements_long", tuple(lines))
    fields = [tuple(mapped) for mapped in fields]

    for k, _, _ in COMMON_KEYS:
        if k in keys and (MODULE == HEADER_MODULE or k in NAMING_RESERVED):
            raise GenError("payload key collides with common key %s" % k)
    return Assignment(fields, [core_ok for core_ok, _ in classes], keys, qualified)


def kind_name(msg):
    """A kind is named by its message name in lower case."""
    return msg.name.lower()


def raw_keys(fields):
    """The `mavlink.` keys a kind maps, in line order."""
    return [line.key for f in fields for line in f.lines if line.key.startswith(MODULE + ".")]


def choose_requires(names, raw):
    """The `requires` keys of every kind: up to MAX_REQUIRES of its own raw
    keys, the ones the fewest kinds map (ties: the earlier line), written in
    line order. `names[i]` and `raw[i]` belong to one kind."""
    usage = collections.Counter()
    for keys in raw:
        usage.update(set(keys))
    chosen = []
    for name, keys in zip(names, raw):
        ranked = sorted(range(len(keys)), key=lambda i: (usage[keys[i]], i))
        picked = sorted(ranked[:MAX_REQUIRES])
        if not picked:
            raise GenError("%s has no raw key to require" % name)
        chosen.append([keys[i] for i in picked])
    return chosen


def find_shadows(names, requires, raw):
    """For every kind, the names of the other kinds that map all of its
    required keys: an entity with those keys and no kind selects the first."""
    key_sets = [set(keys) for keys in raw]
    return [[names[j] for j in range(len(names)) if j != i and set(required) <= key_sets[j]]
            for i, required in enumerate(requires)]


def make_plan(messages):
    """The Plan of a list of messages: nothing is left for the emitters to decide."""
    layouts = [lay_out(m) for m in messages]
    assigned = assign_keys(layouts)
    names = [m.name for m in messages]
    raw = [raw_keys(fields) for fields in assigned.fields]
    requires = choose_requires(names, raw)
    shadows = find_shadows(names, requires, raw)
    kinds = [KindPlan(layout.message, kind_name(layout.message), layout.length, layout.crc_extra,
                      assigned.core_ok[i], assigned.fields[i], requires[i], shadows[i])
             for i, layout in enumerate(layouts)]
    return Plan(kinds, assigned.keys, assigned.qualified)


def check_known_crc_extra(kinds):
    """The field order is right when the messages whose CRC_EXTRA the protocol
    fixes give that value. Refuses a source in which one differs or is absent."""
    for name, want in KNOWN_CRC_EXTRA.items():
        got = [k.crc_extra for k in kinds if k.message.name == name]
        if got != [want]:
            raise GenError("CRC_EXTRA of %s is %s, protocol value is %d" % (name, got, want))


def collect_stats(plan):
    """The counts pack.md and the run summary state."""
    kinds = plan.kinds
    fields = [f for k in kinds for f in k.fields]

    def count(status):
        return sum(f.status == status for f in fields)

    stats = {
        "per_file": collections.Counter(k.message.file for k in kinds), "fields": len(fields),
        "scalar": count("scalar"), "ascii": count("ascii"), "elements": count("elements"),
        "element_lines": sum(len(f.lines) for f in fields if f.status == "elements"),
        "long": count("elements_long"),
        "long_lines": sum(len(f.lines) for f in fields if f.status == "elements_long"),
        "core": count("core"), "unmapped": count("unmapped"),
        "field_lines": len(COMMON_KEYS) + sum(len(f.lines) for f in fields),
    }
    stats["mapped"] = stats["fields"] - stats["unmapped"]
    return stats


# ------------------------------------------------------------------- emit ---

def loc(pos, length):
    """A fixed-layout bits locator `<word>:<pos>:<len>`. Every locator of this
    pack is written from word 0, so `pos` is the bit offset from the STX byte
    (engine-spec 0.5 "bits: fields that run past their word")."""
    return "0:%d:%d" % (pos, length)


def _source_lines(sha):
    out = ['source        "%s %s/%s at commit %s"' % (REPO, XML_DIR, name, sha) for name in XML_FILES]
    out.append('source        "MAVLink 2 packet format, https://mavlink.io/en/guide/serialization.html"')
    return out


def emit_model(keys, sha):
    """The text of model/<module>.def."""
    if DIALECT:
        first = ["# The %s module: fields of the messages that the MAVLink dialect" % MODULE,
                 "# %s defines itself, in their wire units, as raw values." % ROOT_XML]
    else:
        first = ["# The mavlink module: MAVLink fields in their wire units, as raw values."]
    out = first + [
           "# Generated by tools/gen/mavlink2pack.py; do not edit by hand.",
           "# A key is shared by every message whose field has that name, type class,",
           "# units and enum; otherwise the key carries its message name.",
           "module        %s" % MODULE,
           "version       %s" % PACK_VERSION,
           "distribution  public"]
    out += _source_lines(sha)
    if MODULE == HEADER_MODULE:
        for k, _, meaning in COMMON_KEYS:
            out.append('key  %s  int  -  "MAVLink 2 frame header: %s"' % (k, meaning))
    for k, decl in keys.items():
        names = [m for m, _ in decl.uses]
        fname = decl.uses[0][1]
        shown = ", ".join(names[:3]) + (" and %d more" % (len(names) - 3) if len(names) > 3 else "")
        out.append('key  %s  %s  %s  "field %s of %s"' % (k, decl.type, decl.unit, fname, shown))
    return "\n".join(out) + "\n"


def emit_pack(kinds, sha):
    """The text of packs/mavlink2/pack.def: the header, the common `when` on
    STX and the three frame-header fields, then one kind per message selected
    by a `when` on the message id and a `when` on the payload length."""
    if DIALECT:
        first = ["# MAVLink 2 frames, the messages the dialect %s defines itself." % ROOT_XML,
                 "# The included files are read only to check that ids and names are unique."]
    else:
        first = ["# MAVLink 2 frames, message set common.xml (with standard.xml, minimal.xml)."]
    out = first + [
           "# Generated by tools/gen/mavlink2pack.py; do not edit by hand.",
           "# One byte-aligned frame addressed by bit offset from the STX byte:",
           "# STX(8) LEN(8) INCOMPAT(8) COMPAT(8) SEQ(8) SYSID(8) COMPID(8) MSGID(24) PAYLOAD CRC(16).",
           ("# Payload starts at bit %d. The CRC and a signature are not mapped." if FLAGS else
            "# Payload starts at bit %d. CRC, INCOMPAT and COMPAT are not mapped.") % PAYLOAD_BIT0,
           "format        %s" % FORMAT,
           "version       %s" % PACK_VERSION,
           "distribution  public"]
    out += _source_lines(sha)
    if MODULE != HEADER_MODULE:
        out.append("uses          %s" % HEADER_MODULE)
    out += ["uses          %s" % MODULE,
            "wire          bits",
            "bit_order     lsb",
            "word_bytes    1",
            "when   %s %d" % (loc(*LOC_STX), STX)]
    for k, location, _ in COMMON_KEYS:
        out.append("field  %s.%s %s uint" % (HEADER_MODULE, k, loc(*location)))
    for kind in kinds:
        out.append("")
        out.append("kind      %s" % kind.name)
        out.append("when      %s %d" % (loc(*LOC_MSGID), kind.message.id))
        out.append("when      %s %d" % (loc(*LOC_LEN), kind.length))
        out.append("requires  %s" % " ".join(kind.requires))
        for f in kind.fields:
            for line in f.lines:
                out.append("field     %s %s %s" % (line.key, loc(line.pos, line.bits), line.transform))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- vectors ---

def fmt_float(x):
    """Shortest round-trip decimal, plain notation, integers without a point."""
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 1e17:
        return str(int(x))
    r = repr(x)
    return format(Decimal(r), "f") if "e" in r or "E" in r else r


def sample_value(f, salt):
    """A value inside the field's range that survives decode then encode."""
    if f.base == "char":
        return ("M%d" % (salt % 97))[:f.n]
    if f.base == "float":
        return ((salt % 41) - 20) * 0.25
    if f.base == "double":
        return ((salt % 2001) - 1000) * 0.125
    bits = 8 * f.size
    if f.base.startswith("u"):
        v = (salt * 2654435761 + 12345) % min(1 << bits, 1 << 31)
        if bits == 64 and salt % 2:
            v |= 1 << 63               # ruling 2: top bit set must round-trip
        return v
    span = min(1 << bits, 1 << 31)
    return (salt * 40503 + 7) % span - span // 2


def pack_scalar(f, v):
    """One element of a field as MAVLink writes it: little-endian; text
    padded with NUL bytes to the field length."""
    if f.base == "char":
        return v.encode("ascii").ljust(f.n, b"\0")
    return struct.pack("<" + STRUCT_CODES[f.base], v)


def build_payload(kind, values):
    """The full payload of a kind. values: {field name: scalar | list for an
    array}. A field that is not named is zero."""
    unknown = set(values) - {f.field.name for f in kind.fields}
    if unknown:
        raise GenError("%s has no field %s" % (kind.message.name, sorted(unknown)))
    out = b""
    for mapped in kind.fields:
        f = mapped.field
        if f.name not in values:
            out += bytes(f.bytes)
        elif f.is_array:
            out += b"".join(pack_scalar(f, v) for v in values[f.name])
        else:
            out += pack_scalar(f, values[f.name])
    if len(out) != kind.length:
        raise GenError("%s: the values give %d payload bytes, the message has %d"
                       % (kind.message.name, len(out), kind.length))
    return out


def frame(kind, payload, seq, sysid, compid, with_crc, compat=0):
    """A MAVLink 2 frame with INCOMPAT zero and COMPAT `compat`. LEN is the kind's full
    payload length even when `payload` is cut short. The CRC covers every byte
    after STX and then CRC_EXTRA, and is written little-endian."""
    head = bytes([STX, kind.length, 0, compat, seq, sysid, compid]) + kind.message.id.to_bytes(3, "little")
    body = head + payload
    if with_crc:
        crc = x25(body[1:] + bytes([kind.crc_extra]))
        body += struct.pack("<H", crc)
    return body


def roundtrip_vector(kind, index):
    """The frame of a kind's round-trip vector, as the encoder writes it: every
    mapped field holds a sample value, unmapped arrays are zero, the bytes end
    at the last mapped byte and there is no CRC."""
    msgid = kind.message.id
    values = {}
    for j, mapped in enumerate(kind.fields):
        f = mapped.field
        salt = msgid * 31 + j * 7 + 3
        if mapped.status == "unmapped":
            continue                       # bits no field maps stay zero
        if mapped.status == "core":
            values[f.name] = {"lat": 1, "lon": -1}[core_name(f)] * (100000000 + 1250000 * (msgid % 37))
        elif mapped.status in ("elements", "elements_long"):
            values[f.name] = [sample_value(f, salt + i) for i in range(f.n)]
        else:
            values[f.name] = sample_value(f, salt)
    payload = build_payload(kind, values)
    # with --compat-flags every other frame sets COMPAT (it changes no layout);
    # INCOMPAT stays 0, its bit 0x01 would announce a signature
    return frame(kind, payload[:kind.mapped_len], index % 256, 1 + msgid % 250, 1 + msgid % 191, False,
                 index % 2 if FLAGS else 0)


# Five cross-format cases. `expect` is written by hand from the field values:
# lat and lon are int32 degE7, so degrees = value / 10^7; GeoJSON coordinates
# are [lon, lat]; geojson carries no other key this pack maps, so `properties`
# is empty. The generator checks each against its own codec.
CROSS = [
    ("GLOBAL_POSITION_INT", 7, 1, 1,
     {"time_boot_ms": 123456, "lat": 473977420, "lon": 85455940, "alt": 488100,
      "relative_alt": 12500, "vx": 150, "vy": -75, "vz": 10, "hdg": 9000},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.545594,47.397742]},"properties":{}}'),
    ("GPS_RAW_INT", 8, 1, 1,
     {"time_usec": 1700000000000000, "fix_type": 3, "lat": -338568000, "lon": 1512153000,
      "alt": 58000, "eph": 120, "epv": 180, "vel": 0, "cog": 0, "satellites_visible": 11},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[151.2153,-33.8568]},"properties":{}}'),
    ("GPS2_RAW", 9, 1, 1,
     {"time_usec": 5000000, "fix_type": 3, "lat": 515007000, "lon": -1246000,
      "alt": 35000, "satellites_visible": 9},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[-0.1246,51.5007]},"properties":{}}'),
    ("HIL_GPS", 10, 42, 200,
     {"time_usec": 1000000, "fix_type": 3, "lat": 0, "lon": -1800000000, "alt": 0,
      "satellites_visible": 7},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[-180,0]},"properties":{}}'),
    ("UTM_GLOBAL_POSITION", 11, 3, 1,
     {"time": 1700000000000000, "lat": 356762000, "lon": 1396503000, "alt": 40000,
      "relative_alt": 5000, "flight_state": 3},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[139.6503,35.6762]},"properties":{}}'),
]


def _vector_text(pairs):
    return json.dumps(collections.OrderedDict(pairs), indent=2) + "\n"


def vector_files(kinds):
    """[(file name, text)] of every vector: one round trip per kind in id
    order, then the cross-format cases of CROSS."""
    files = []
    for i, kind in enumerate(kinds):
        data = roundtrip_vector(kind, i).hex()
        files.append(("rt-%05d-%s.json" % (kind.message.id, kind.name), _vector_text([
            ("name", "roundtrip-%s" % kind.name), ("from", FORMAT), ("to", FORMAT),
            ("input", data), ("expect", data), ("model", {"@kind": kind.name})])))
    by_name = {kind.message.name: kind for kind in kinds}
    for n, (name, seq, sysid, compid, values, expect) in enumerate(CROSS, 1):
        if name not in by_name:
            raise GenError("the source has no message %s, which a vector to geojson is written from" % name)
        kind = by_name[name]
        data = frame(kind, build_payload(kind, values), seq, sysid, compid, True)
        pos = {core_name(f.field): values[f.field.name] for f in kind.fields if f.status == "core"}
        model = collections.OrderedDict([("@kind", kind.name),
                                         ("lat", fmt_float(pos["lat"] * 1.0 / 10000000.0)),
                                         ("lon", fmt_float(pos["lon"] * 1.0 / 10000000.0)),
                                         (HEADER_MODULE + ".seq", str(seq)),
                                         (HEADER_MODULE + ".sysid", str(sysid)),
                                         (HEADER_MODULE + ".compid", str(compid))])
        files.append(("x-%02d-%s-to-geojson.json" % (n, kind.name), _vector_text([
            ("name", "%s-to-geojson" % kind.name), ("from", FORMAT), ("to", "geojson"),
            ("input", data.hex()), ("expect", expect), ("model", model)])))
    return files


def write_vectors(out, files):
    """Write the vector files and remove every other .json of the directory."""
    keep = {name for name, _ in files}
    for old in out.listdir(VECTOR_DIR):
        if old.endswith(".json") and old not in keep:
            out.remove("%s/%s" % (VECTOR_DIR, old))
    for name, text in files:
        out.write("%s/%s" % (VECTOR_DIR, name), text)


# ---------------------------------------------------------------- pack.md ---

def _ticked(names):
    return ", ".join("`%s`" % name for name in names)


def _md_layout(sha):
    o = []
    a = o.append
    a("# Pack: mavlink2")
    a("")
    a("MAVLink 2 frames carrying the `common.xml` message set (with the files it")
    a("includes, `standard.xml` and `minimal.xml`). Public. Generated by")
    a("`tools/gen/mavlink2pack.py` from `%s` at commit `%s`;" % (REPO, sha))
    a("do not edit `pack.def`, `model/mavlink.def`, this file or the vectors by hand.")
    a("I/O is hex text (`spec/engine-spec.md`, bits wire).")
    a("")
    a("Status: Built. Generated and checked by the generator's own reader; every engine")
    a("runs every vector in `vectors/` in the conformance suite.")
    a("")
    a("## Layout")
    a("")
    a("`wire bits`, `bit_order lsb`, `word_bytes 1`. A locator is `0:<bit offset>:<len>`")
    a("counted from the first bit of the STX byte.")
    a("")
    a("| Part | Bytes | Locator | In the pack |")
    a("|---|---|---|---|")
    a("| STX | 1 | `0:0:8` | common `when` = 253 (0xFD) |")
    a("| LEN | 1 | `0:8:8` | per-kind `when` = full payload length |")
    if FLAGS:
        a("| INCOMPAT | 1 | `0:16:8` | `mavlink.incompat_flags` |")
        a("| COMPAT | 1 | `0:24:8` | `mavlink.compat_flags` |")
    else:
        a("| INCOMPAT | 1 | `0:16:8` | not mapped |")
        a("| COMPAT | 1 | `0:24:8` | not mapped |")
    a("| SEQ | 1 | `0:32:8` | `mavlink.seq` |")
    a("| SYSID | 1 | `0:40:8` | `mavlink.sysid` |")
    a("| COMPID | 1 | `0:48:8` | `mavlink.compid` |")
    a("| MSGID | 3, little-endian | `0:56:24` | per-kind `when` = message id |")
    a("| PAYLOAD | LEN | from `0:80` | the kind's `field` lines |")
    a("| CRC | 2 | after the payload | not mapped |")
    a("")
    a("One `kind` per message, named by the message name in lower case, in message-id")
    a("order. Payload fields sit at their MAVLink 2 wire offsets: base fields in")
    a("descending type-size order (stable), then extension fields in declaration order.")
    a("The generator confirms its field order by computing each message's CRC_EXTRA and")
    a("comparing six of them with the values the protocol fixes.")
    a("")
    return o


def _md_numbers(plan, stats):
    n_kinds = len(plan.kinds)
    o = []
    a = o.append
    a("## Numbers")
    a("")
    a("| | Count |")
    a("|---|---|")
    a("| Messages in the source (common %d, standard %d, minimal %d) | %d |" % (
        stats["per_file"]["common.xml"], stats["per_file"]["standard.xml"],
        stats["per_file"]["minimal.xml"], n_kinds))
    a("| Kinds | %d |" % n_kinds)
    a("| Payload fields in the source | %d |" % stats["fields"])
    a("| Payload fields mapped | %d |" % stats["mapped"])
    a("| ... scalar to a raw `mavlink.` key | %d |" % stats["scalar"])
    a("| ... `char[n]` to a string key (`ascii`) | %d |" % stats["ascii"])
    a("| ... array of 2 to %d elements, one key per element | %d (%d element lines) |" % (
        MAX_ARRAY_ELEMENTS, stats["elements"], stats["element_lines"]))
    md_long_rows(a, stats)
    a("| ... `lat` / `lon` in degE7 to core `lat` / `lon` | %d |" % stats["core"])
    md_unmapped_row(a, stats)
    a("| `field` lines in `pack.def` (%d common + per kind) | %d |" % (len(COMMON_KEYS), stats["field_lines"]))
    a("| Keys in module `mavlink` (%d frame-header + payload) | %d |" % (
        len(COMMON_KEYS), len(plan.keys) + len(COMMON_KEYS)))
    a("| Vectors (%d same-format round trips + %d to geojson) | %d |" % (
        n_kinds, len(CROSS), n_kinds + len(CROSS)))
    a("")
    return o


def _md_mapped(plan):
    reasons = collections.Counter(plan.qualified.values())
    o = []
    a = o.append
    a("## What is mapped")
    a("")
    a("| MAVLink type | Transform | Model type |")
    a("|---|---|---|")
    a("| `uint8_t` `uint16_t` `uint32_t` `uint64_t` | `uint` | int |")
    a("| `int8_t` `int16_t` `int32_t` `int64_t` | `twos` | int |")
    a("| `float` | `f32` | float |")
    a("| `double` | `f64` | float |")
    a("| `char[n]` | `ascii` over `8n` bits | string |")
    a("| other `type[n]`, n of 2 to %d | one line per element, keys `…_0`, `…_1`, … | as the element |" % MAX_ARRAY_ELEMENTS)
    a("| `int32_t` degE7 named `lat` or `lon`, with no `invalid` value declared | `sscale:%s` | float, core `lat` / `lon` |" % DEGE7)
    a("")
    a("Every other value is raw: the integer or float on the wire, in the unit the")
    a("definition states, which `model/mavlink.def` records in the key's unit column.")
    md_long_text(a, md_messages(plan))
    a("")
    a("### Key names")
    a("")
    a("A key is `mavlink.<field name>` with the unit appended when the field declares")
    a("one and the name does not already end with it (`mavlink.alt_mm`,")
    a("`mavlink.time_boot_ms`). Unit text is lower-cased; `/` becomes `_per_`, `%`")
    a("becomes `pct`, `*` becomes `_x`. One key is shared by every message whose field")
    a("has that name with the same type class (int, float, string), units and enum.")
    a("When the uses of a name disagree, every use takes the message name as a prefix")
    a("(`mavlink.<message>_<field>…`). %d fields are named that way:" % len(plan.qualified))
    a("")
    a("| Reason | Fields |")
    a("|---|---|")
    # most fields first; reasons with one count stay in first-use order (the sort is stable)
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        a("| %s | %d |" % (r, c))
    a("")
    return o


def _md_core(plan):
    kinds = plan.kinds
    core = [k for k in kinds if any(f.status == "core" for f in k.fields)]
    nocore = [k for k in kinds if not k.core_ok]
    raw_latlon = [f for k in kinds for f in k.fields
                  if f.field.units == "degE7" and f.status != "core" and k.core_ok]
    o = []
    a = o.append
    a("### Core keys")
    a("")
    a("%d kinds map core `lat` and `lon`: %s." % (len(core), _ticked(k.name for k in core)))
    a("The position is the one the message reports, which is not always the sending")
    a("vehicle's: `terrain_request`, `terrain_data` and `terrain_report`")
    a("carry a terrain grid point, `follow_target` a target, `camera_image_captured` the")
    a("camera at capture time.")
    if nocore:
        a("%s has no field but `lat` and `lon`; they stay raw there so the kind has a raw" % _ticked(k.name for k in nocore))
        a("key to require, otherwise any entity with a position would encode as that kind.")
    a("")
    a("Left raw on purpose:")
    a("")
    a("- degE7 fields that are not named `lat` / `lon` or that declare an `invalid`")
    a("  value (%d fields, for example `latitude`, `lat_int`, and `lat` of `adsb_vehicle`," % len(raw_latlon))
    a("  `ais_vessel`, `global_position_sensor`, where INT32_MAX means unknown and would")
    a("  decode to 214.7483647 degrees).")
    a("- UTC epoch times in microseconds (`time_unix_usec`, `time_usec`, `time_utc`):")
    a("  core `time_ms` is an integer and the only scaling transforms yield float; a")
    a("  64-bit microsecond count scaled by 0.001 is not exact in a double.")
    a("- Altitude. MAVLink `alt` fields are above mean sea level; core `hae` is above")
    a("  the WGS84 ellipsoid.")
    a("- Speed, course, heading and velocity components (`vel`, `cog`, `hdg`, `vx`…):")
    a("  the reference frame is in the description text, not in the units, and most")
    a("  declare an `invalid` value (UINT16_MAX).")
    a("")
    return o


def _md_requires(plan):
    shadow = [k for k in plan.kinds if k.shadowed_by]
    o = []
    a = o.append
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own raw keys, the ones used by the fewest" % MAX_REQUIRES)
    a("kinds, so encoding an entity that came from another format selects a kind only")
    a("when the entity holds those `mavlink.` keys. No kind requires a core key, so a")
    a("GeoJSON or CoT entity selects no kind (`no-kind`).")
    if shadow:
        a("For %d kinds the required keys are all shared with at least one other kind" % len(shadow))
        a("that maps every one of them; an entity built from such a kind's keys with its")
        a("kind cleared selects the first qualifying kind in id order: %s." % _ticked(k.name for k in shadow))
    a("")
    return o


def _md_not_mapped(plan):
    unmapped = [(k, f.field) for k in plan.kinds for f in k.fields if f.status == "unmapped"]
    o = []
    a = o.append
    a("## What is not mapped")
    a("")
    md_signature(a)
    if unmapped or LEGACY:
        a("- %d array fields of more than %d elements (%d bytes of payload in total):" % (
            len(unmapped), MAX_ARRAY, sum(f.bytes for _, f in unmapped)))
        a("")
        a("| Message | Field | Type |")
        a("|---|---|---|")
        for k, f in unmapped:
            a("| %s | %s | `%s[%d]` |" % (k.message.name, f.name, f.base, f.n))
    a("")
    return o


def _md_limits(plan):
    short = [k for k in plan.kinds if k.mapped_len < k.length]
    o = []
    a = o.append
    a("## Known limits")
    a("")
    a("- **Truncated payloads.** MAVLink 2 senders drop trailing zero bytes of the")
    a("  payload and set LEN to the shorter length. Each kind matches only LEN = the")
    a("  full length, so a truncated frame decodes as `no-kind`. Reading one needs the")
    a("  future framed-binary wire (a length-prefixed payload that is zero-extended).")
    a("- **CRC.** Decode does not verify the checksum and encode does not write it.")
    a("  Encode output is the header and payload up to the last mapped byte; it is not")
    a("  a transmittable frame until a framer adds truncation and the CRC (with the")
    a("  message's CRC_EXTRA). Input that carries the CRC or a signature decodes: bytes")
    a("  after the last mapped bit are ignored.")
    if short or LEGACY:
        a("- **Short output.** In %d kinds the payload ends in unmapped array fields, so" % len(short))
        a("  encode output is shorter than `10 + LEN` bytes: %s." % _ticked(k.name for k in short))
        if FLAGS:
            a("- **Unmapped bits do not round-trip.** The bits wire has no residue: unmapped")
            a("  arrays are written as zero.")
        else:
            a("- **Unmapped bits do not round-trip.** The bits wire has no residue: INCOMPAT,")
            a("  COMPAT and unmapped arrays are written as zero.")
    else:
        a("- **Output length.** Every payload byte is mapped, so encode output is the")
        a("  `10 + LEN` bytes of header and payload, without the CRC.")
    a("- **`invalid` values.** A field's `invalid` attribute (a value that means")
    a("  unknown) is not interpreted; the key holds the number.")
    a("- **Text.** `ascii` refuses bytes outside 0x20..0x7E, so a `char[n]` field that")
    a("  holds UTF-8 or binary data fails to decode. Trailing NULs are dropped; an")
    a("  all-NUL field is the empty string, present.")
    a("- **`uint64_t`** is mapped with `uint` to the model type int; a value of 2^63 or")
    a("  above is the negative model integer with the same bits (engine-spec 0.5, ruling 2).")
    a("- **Enums and bitmasks** are carried as their integer.")
    a("")
    return o


def _md_vectors():
    o = []
    a = o.append
    a("## Vectors")
    a("")
    a("`vectors/rt-<id>-<kind>.json`: one same-format round trip per kind. The input")
    if LEGACY:
        a("is the frame as the encoder writes it (no CRC, unmapped arrays absent or zero),")
        a("so input and expected output are identical. Values are inside each field's")
        a("range; floats are multiples of 0.25 or 0.125; every other `uint64_t` sample has")
        a("its top bit set.")
    else:
        a("is the frame as the encoder writes it (no CRC), so input and expected output")
        a("are identical. Values are inside each field's range; floats are multiples of")
        a("0.25 or 0.125; every other `uint64_t` sample has its top bit set%s." % (
            "; every other\nframe has COMPAT = 1, and INCOMPAT is 0" if FLAGS else ""))
    a("")
    a("`vectors/x-NN-<kind>-to-geojson.json`: %d full frames with a correct CRC," % len(CROSS))
    a("converted to GeoJSON. Expected output: `coordinates` = `[lon, lat]` in degrees")
    a("(wire value / 10^7), `properties` empty because `geojson` carries no other key")
    a("this pack maps.")
    return o



class _MdField:
    """A mapped field as the pack.md text reads it."""

    def __init__(self, field, status, lines):
        self.field, self.status, self.lines = field, status, lines
        for attr in ("name", "base", "n", "units", "enum", "bytes"):
            setattr(self, attr, getattr(field, attr))


class _MdMessage:
    """A kind (or a message with no kind) as the pack.md text reads it."""

    def __init__(self, message, kind, wire, mapped_len, length, shadowed_by):
        self.name, self.id = message.name, message.id
        self.kind = kind or kind_name(message)
        self.wire, self.mapped_len, self.length, self.shadowed_by = wire, mapped_len, length, shadowed_by
        self.wip, self.deprecated = "wip" in message.marks, "deprecated" in message.marks


def md_messages(plan):
    return [_MdMessage(k.message, k.name, [_MdField(f.field, f.status, f.lines) for f in k.fields],
                       k.mapped_len, k.length, k.shadowed_by) for k in plan.kinds]


def md_unmapped_row(a, stats):
    if LEGACY:
        a("| Payload fields not mapped (arrays of more than %d elements) | %d |" % (
            MAX_ARRAY_ELEMENTS, stats["unmapped"]))
    else:
        a("| Payload fields not mapped | %d |" % stats["unmapped"])


SIGNATURE_TEXT = [
    "- CRC (2 bytes after the payload) and the 13-byte signature of a signed frame.",
    "  A field line with the `optional` option could read them, but encode writes",
    "  every field line of the kind whether its key is present or not (vector",
    "  `06-optional-truncated-roundtrip-writes-whole-message` of",
    "  `conformance-rules-bits`), so every unsigned frame would gain 13 zero bytes",
    "  and every frame from another format a CRC of zero. Mapping them needs a rule",
    "  that computes the checksum and one that writes a part only when a flag is set.",
]


def md_signature(a):
    if FLAGS:
        for line in SIGNATURE_TEXT:
            a(line)
    else:
        a("- CRC (2 bytes after the payload), INCOMPAT and COMPAT flags, and the 13-byte")
        a("  signature of a signed frame.")


def md_long_rows(a, stats):
    if stats["long"]:
        a("| ... array of more than %d elements, one key per element | %d (%d element lines) |" % (
            MAX_ARRAY_ELEMENTS, stats["long"], stats["long_lines"]))


def md_long_text(a, msgs):
    longs = [(m, f) for m in msgs for f in m.wire if f.status == "elements_long"]
    if not longs:
        return
    a("")
    a("### Arrays of more than %d elements" % MAX_ARRAY_ELEMENTS)
    a("")
    a("%d array fields (%d bytes of payload) are mapped one key per element as the" % (
        len(longs), sum(f.bytes for _, f in longs)))
    a("shorter arrays are, keys `<name>_0` to `<name>_<n-1>`. Their keys are named in")
    a("a pass after every other key, so they never change a key the shorter-array rule")
    a("gives: a field's element keys are shared with other messages only when every")
    a("long use agrees on type class, units and enum and every key name that already")
    a("exists has the same meaning; otherwise the field takes its message name as a")
    a("prefix. Byte blobs (`uint8_t[n]` holding a file chunk, RTCM data, a URI) are")
    a("carried byte by byte as integers 0..255; the model has no byte-string type a")
    a("`bits` transform yields.")
    a("")
    a("| Message | Field | Type | Keys |")
    a("|---|---|---|---|")
    for m, f in longs:
        k0 = f.lines[0][0]
        a("| %s | %s | `%s[%d]` | `%s` … `_%d` |" % (m.name, f.name, f.base, f.n, k0, f.n - 1))


def emit_dialect_md(plan, skipped_layouts, stats, sha):
    """The text of pack.md of a dialect pack, section by section."""
    msgs = md_messages(plan)
    skipped = [_MdMessage(layout.message, None, [_MdField(p.field, "unmapped", ()) for p in layout.wire],
                          layout.length, layout.length, []) for layout in skipped_layouts]
    keys, qualified = plan.keys, plan.qualified
    core = [m for m in msgs if any(f.status == "core" for f in m.wire)]
    unmapped = [(m, f) for m in msgs for f in m.wire if f.status == "unmapped"]
    short = [m for m in msgs if m.mapped_len < m.length]
    shadow = [m for m in msgs if m.shadowed_by]
    raw_deg = [(m, f) for m in msgs for f in m.wire if f.units == "degE7" and f.status != "core"]
    reasons = collections.Counter(qualified.values())
    included = [x for x in XML_FILES if x != ROOT_XML]
    o = []
    a = o.append
    a("# Pack: %s" % FORMAT)
    a("")
    a("MAVLink 2 frames carrying the messages that the dialect file `%s` defines" % ROOT_XML)
    a("itself. Public. Generated by `tools/gen/mavlink2pack.py --dialect %s` from" % DIALECT)
    a("`%s` (`%s/%s`) at commit `%s`;" % (REPO, XML_DIR, ROOT_XML, sha))
    a("do not edit `pack.def`, `model/%s.def`, this file or the vectors by hand." % MODULE)
    a("I/O is hex text (`spec/engine-spec.md`, bits wire). Source, hashes and license:")
    a("`PROVENANCE.md`.")
    a("")
    a("Status: Built. Generated and checked by the generator's own reader; every engine")
    a("runs every vector in `vectors/` in the conformance suite.")
    a("")
    a("## Scope: the dialect's own messages")
    a("")
    if included:
        a("`%s` includes %s. The pack holds only the messages `%s`" % (
            ROOT_XML, ", ".join("`%s`" % x for x in included), ROOT_XML))
        a("itself defines; the messages of the included files are in the pack of the file")
        a("that defines them (`mavlink2` for `common.xml`, `standard.xml` and `minimal.xml`,")
        a("`mavlink2-<dialect>` for a dialect). The included files are read only to check")
        a("that every message id and every message name of the whole set is unique.")
    else:
        a("`%s` includes no other file. The pack holds the messages it defines." % ROOT_XML)
    a("")
    a("So no message id occurs twice inside the pack, and a message is described by")
    a("exactly one pack in the repository. A system that speaks the dialect loads")
    a("`mavlink2` and the packs of every file the dialect includes, and names the pack")
    a("of the message when it converts. A frame of an included message is `no-kind` in")
    a("this pack.")
    a("")
    a("## Layout")
    a("")
    a("The frame is the one `packs/mavlink2/pack.md` describes: `wire bits`, `bit_order lsb`,")
    a("`word_bytes 1`, locators `0:<bit offset>:<len>` from the STX byte, a common `when`")
    a("on STX = 253, and per kind a `when` on MSGID (`0:56:24`) and on LEN (`0:8:8`) = the")
    if FLAGS:
        a("full payload length. The frame-header keys `mavlink.seq`, `mavlink.sysid`,")
        a("`mavlink.compid`, `mavlink.incompat_flags` and `mavlink.compat_flags` are those of")
        a("module `mavlink`, so they carry over between every")
    else:
        a("full payload length. The frame-header keys `mavlink.seq`, `mavlink.sysid` and")
        a("`mavlink.compid` are those of module `mavlink`, so they carry over between every")
    a("MAVLink pack. Payload keys are in this pack's own module `%s`." % MODULE)
    a("Payload fields sit at their MAVLink 2 wire offsets: base fields in descending")
    a("type-size order (stable), then extension fields in declaration order. The")
    a("generator confirms the order by computing CRC_EXTRA and the payload length of")
    a("%d messages and comparing them with the values in the C library that the" % len(KNOWN_DIALECT.get(DIALECT, {})))
    a("MAVLink project generates from the same definitions (`PROVENANCE.md`).")
    a("")
    a("## Numbers")
    a("")
    a("| | Count |")
    a("|---|---|")
    a("| Messages `%s` defines | %d |" % (ROOT_XML, len(msgs) + len(skipped)))
    a("| Kinds | %d |" % len(msgs))
    a("| Messages with no field the pack can map (no kind) | %d |" % len(skipped))
    a("| Payload fields of the kinds | %d |" % stats["fields"])
    a("| Payload fields mapped | %d |" % stats["mapped"])
    a("| ... scalar to a raw `%s.` key | %d |" % (MODULE, stats["scalar"]))
    a("| ... `char[n]` to a string key (`ascii`) | %d |" % stats["ascii"])
    a("| ... array of 2 to %d elements, one key per element | %d (%d element lines) |" % (
        MAX_ARRAY_ELEMENTS, stats["elements"], stats["element_lines"]))
    md_long_rows(a, stats)
    a("| ... latitude / longitude in degE7 to core `lat` / `lon` | %d |" % stats["core"])
    md_unmapped_row(a, stats)
    a("| `field` lines in `pack.def` (%d common + per kind) | %d |" % (len(COMMON_KEYS), stats["field_lines"]))
    a("| Keys in module `%s` | %d |" % (MODULE, len(keys)))
    a("| Vectors (%d same-format round trips + %d to geojson) | %d |" % (
        len(msgs), len(CROSS), len(msgs) + len(CROSS)))
    a("")
    a("## What is mapped")
    a("")
    a("| MAVLink type | Transform | Model type |")
    a("|---|---|---|")
    a("| `uint8_t` `uint16_t` `uint32_t` `uint64_t` | `uint` | int |")
    a("| `int8_t` `int16_t` `int32_t` `int64_t` | `twos` | int |")
    a("| `float` | `f32` | float |")
    a("| `double` | `f64` | float |")
    a("| `char[n]` | `ascii` over `8n` bits | string |")
    a("| other `type[n]`, n of 2 to %d | one line per element, keys `…_0`, `…_1`, … | as the element |" % MAX_ARRAY_ELEMENTS)
    a("| `int32_t` degE7 named `lat`, and `lon` or `lng`, both in one message, with no `invalid` value declared | `sscale:%s` | float, core `lat` / `lon` |" % DEGE7)
    a("")
    a("Every other value is raw: the integer or float on the wire, in the unit the")
    a("definition states, which `model/%s.def` records in the key's unit column." % MODULE)
    md_long_text(a, msgs)
    a("")
    a("### Key names")
    a("")
    a("The rules of `packs/mavlink2/pack.md` (Key names), within this dialect: a key is")
    a("`%s.<field name>` with the unit appended when the field declares one and" % MODULE)
    a("the name does not already end with it; one key is shared by every message of the")
    a("dialect whose field has that name, type class, units and enum; otherwise every use")
    a("takes the message name as a prefix. %d fields are named that way%s" % (
        len(qualified), ":" if reasons else "."))
    if reasons:
        a("")
        a("| Reason | Fields |")
        a("|---|---|")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
            a("| %s | %d |" % (r, c))
    a("")
    a("### Core keys")
    a("")
    if core:
        a("The binding is the one `mavlink2` makes, for the same field semantics: an")
        a("`int32_t` field in degE7 that the definition names and describes as the")
        a("latitude or longitude, with no `invalid` value. A message binds only when it has")
        a("one latitude and one longitude field that qualify.")
        if any(f.name == "lng" for m in core for f in m.wire if f.status == "core"):
            a("This dialect spells the longitude `lng`; it is treated as `lon`.")
        a("The position is the one the message reports:")
        a("")
        a("| Kind | Fields | Position |")
        a("|---|---|---|")
        for m in core:
            fs = " / ".join("`%s`" % f.name for f in m.wire if f.status == "core")
            a("| `%s` | %s | %s |" % (m.kind, fs, POSITION_NOTES[m.name]))
    else:
        a("No message of `%s` has a latitude and a longitude field that bind core keys," % ROOT_XML)
        a("so no kind maps a shared key and the pack converts to no other format.")
    if raw_deg:
        a("")
        a("Left raw: %s. A field stays raw when its name is not `lat`, `lon` or `lng`," % ", ".join(
            "`%s.%s`" % (m.name, f.name) for m, f in raw_deg))
        a("when it declares an `invalid` value (INT32_MAX would decode to 214.7483647")
        a("degrees), or when its message has no qualifying partner field.")
    a("")
    a("Not bound to a shared key, for the reasons `packs/mavlink2/pack.md` gives:")
    a("altitude (MAVLink altitudes are above mean sea level or relative, core `hae` is")
    a("above the ellipsoid), epoch times in microseconds, and speed, course and velocity")
    a("(the frame is stated in description text, not in the units).")
    a("")
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own raw keys, the ones used by the fewest" % MAX_REQUIRES)
    a("kinds of this pack. No kind requires a core key, so a GeoJSON or CoT entity, or an")
    a("entity decoded by another MAVLink pack, selects no kind here (`no-kind`).")
    if shadow:
        a("For %d kinds the required keys are all mapped by another kind too; an entity" % len(shadow))
        a("built from such a kind's keys with its kind cleared selects the first")
        a("qualifying kind in id order: %s." % ", ".join("`%s`" % m.kind for m in shadow))
    a("")
    a("## What is not mapped")
    a("")
    md_signature(a)
    if skipped:
        a("- Messages with no kind: every payload field is an array of more than %d" % MAX_ARRAY_ELEMENTS)
        a("  elements, so the kind would have no key to map or to require (a kind with no")
        a("  `requires` would be chosen for any entity). A frame of one is `no-kind`:")
        a("")
        a("| Message | Id | Fields |")
        a("|---|---|---|")
        for m in skipped:
            a("| %s | %d | %s |" % (m.name, m.id, ", ".join("`%s` `%s[%d]`" % (f.name, f.base, f.n) for f in m.wire)))
        a("")
    if unmapped:
        a("- %d array fields of more than %d elements (%d bytes of payload in total):" % (
            len(unmapped), MAX_ARRAY_ELEMENTS, sum(f.bytes for _, f in unmapped)))
        a("")
        a("| Message | Field | Type |")
        a("|---|---|---|")
        for m, f in unmapped:
            a("| %s | %s | `%s[%d]` |" % (m.name, f.name, f.base, f.n))
        a("")
    a("- Enum and bitmask values are carried as their integer; enum names are not")
    a("  taken into the model.")
    a("")
    a("## Known limits")
    a("")
    a("Those of `packs/mavlink2/pack.md` (Known limits) hold here unchanged: truncated")
    a("payloads (LEN shorter than the full length) are `no-kind`; the CRC is neither")
    a("checked nor written; unmapped bits are written as zero; an `invalid` value is"
      if LEGACY else "checked nor written; an `invalid` value is")
    a("carried as its number; `ascii` refuses bytes outside 0x20..0x7E; `uint64_t` values")
    a("of 2^63 or above are the negative model integer with the same bits.")
    if short:
        a("In %d kinds the payload ends in unmapped array fields, so encode output is" % len(short))
        a("shorter than `10 + LEN` bytes: %s." % ", ".join("`%s`" % m.kind for m in short))
    wip = [m for m in msgs + skipped if m.wip]
    dep = [m for m in msgs + skipped if m.deprecated]
    if wip or dep:
        a("")
        a("## Message status in the source")
        a("")
        if wip:
            a("The definition marks %d messages as work in progress, liable to change in a" % len(wip))
            a("later commit: %s." % ", ".join("`%s`" % m.kind for m in wip))
        if dep:
            a("The definition marks %d messages as deprecated: %s." % (len(dep), ", ".join("`%s`" % m.kind for m in dep)))
        a("The pack maps them as the pinned commit defines them.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-<id>-<kind>.json`: one same-format round trip per kind, computed by")
    if LEGACY:
        a("the generator's own encoder (no CRC, unmapped arrays absent or zero), so input and")
        a("expected output are identical.")
    else:
        a("the generator's own encoder (no CRC%s), so input" % (
            "; every other frame has COMPAT = 1" if FLAGS else ""))
        a("and expected output are identical.")
    if CROSS:
        a("")
        a("`vectors/x-NN-<kind>-to-geojson.json`: %d full frames with a correct CRC" % len(CROSS))
        a("(computed with the message's CRC_EXTRA), converted to GeoJSON. The expected")
        a("output is written by hand in the generator from the field values: `coordinates`")
        a("= `[lon, lat]` in degrees (wire value / 10^7), `properties` empty because")
        a("`geojson` carries no other key this pack maps.")
    return "\n".join(o) + "\n"


def emit_pack_md(plan, stats, sha):
    """The text of packs/mavlink2/pack.md, section by section."""
    lines = (_md_layout(sha) + _md_numbers(plan, stats) + _md_mapped(plan) + _md_core(plan)
             + _md_requires(plan) + _md_not_mapped(plan) + _md_limits(plan) + _md_vectors())
    return "\n".join(lines) + "\n"


# ------------------------------------------- codec, from the specification ---
#
# Decode and encode for the part of the bits wire this pack uses: fixed
# layout, `bit_order lsb`, `word_bytes 1`, `when` and `field` lines. The codec
# reads the Pack that gtcheck loaded; `check_frame_invariants` refuses a pack
# that holds anything else.

def round_away(x):
    """Round half away from zero (engine-spec 0.2 "Transforms for `bits`")."""
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def get_bits(word, pos, length):
    """`length` bits of the message from bit `pos`. With `bit_order lsb` the
    message is one little-endian integer, `word`."""
    return (word >> pos) & ((1 << length) - 1)


def _scale(targs):
    """(factor, offset) of a `uscale` or `sscale` transform. The factor is a
    float, or (numerator, denominator) for a fraction (0.5 ruling 1)."""
    return gtcheck.parse_factor(targs[0]), float(targs[1]) if len(targs) == 2 else 0.0


def decode_value(tr, targs, bits, raw):
    """The model value of the unsigned integer `raw` read from a field of
    `bits` bits (engine-spec 0.2 "Transforms for `bits`", 0.5 "bits: more
    transforms")."""
    if tr == "uint":
        # 0.5 ruling 2: a 64-bit field with the top bit set is the negative integer
        return raw - (1 << 64) if bits == 64 and raw >> 63 else raw
    if tr == "twos":
        return raw - (1 << bits) if raw >> (bits - 1) else raw
    if tr in ("uscale", "sscale"):
        if tr == "sscale" and raw >> (bits - 1):
            raw -= 1 << bits
        factor, offset = _scale(targs)
        if isinstance(factor, tuple):       # 0.5 ruling 1: v * num / den, then + offset
            return raw * float(factor[0]) / float(factor[1]) + offset
        return raw * factor + offset
    if tr == "f32":
        return struct.unpack("<f", raw.to_bytes(4, "little"))[0]
    if tr == "f64":
        return struct.unpack("<d", raw.to_bytes(8, "little"))[0]
    if tr == "ascii":
        text = raw.to_bytes(bits // 8, "little").rstrip(b"\0")
        if any(b < 0x20 or b > 0x7E for b in text):
            raise CodecError("transform-decode")
        return text.decode("ascii")
    raise CodecError("transform-decode")


def encode_value(tr, targs, bits, value):
    """The unsigned integer a field of `bits` bits holds for a model value."""
    mask = (1 << bits) - 1
    if tr in ("uint", "twos"):
        return value & mask
    if tr in ("uscale", "sscale"):
        factor, offset = _scale(targs)
        if isinstance(factor, tuple):       # 0.5 ruling 1: (x - offset) * den / num
            n = round_away((value - offset) * float(factor[1]) / float(factor[0]))
        else:
            n = round_away((value - offset) / factor)
        lo, hi = (0, mask) if tr == "uscale" else (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
        if not lo <= n <= hi:
            raise CodecError("transform-encode")
        return n & mask
    if tr == "f32":
        return int.from_bytes(struct.pack("<f", value), "little")
    if tr == "f64":
        return int.from_bytes(struct.pack("<d", value), "little")
    if tr == "ascii":
        text = value.encode("ascii")
        if len(text) > bits // 8:
            raise CodecError("transform-encode")
        return int.from_bytes(text.ljust(bits // 8, b"\0"), "little")
    raise CodecError("transform-encode")


def _when_holds(lines, word, total_bits):
    return all(node.start + node.bits <= total_bits and get_bits(word, node.start, node.bits) == int(node.value)
               for node in lines if node.d == "when")


def message_bytes(lines):
    """Bytes up to the last bit a `when` or `field` line of the scope names."""
    return (max(node.start + node.bits for node in lines) + 7) // 8


def engine_decode(pack, data):
    """(kind name, {key: value}) of a message: the first kind in file order
    whose `when` lines and the common ones all hold (engine-spec 0.5 "Message
    kinds")."""
    word, total_bits = int.from_bytes(data, "little"), 8 * len(data)
    kind = None
    if _when_holds(pack.common, word, total_bits):
        kind = next((k for k in pack.kinds if _when_holds(k.lines, word, total_bits)), None)
    if kind is None:
        raise CodecError("no-kind")
    lines = pack.common + kind.lines
    if len(data) < message_bytes(lines):
        raise CodecError("malformed-wire")
    entity = collections.OrderedDict()
    for node in lines:
        if node.d == "field":
            entity[node.key] = decode_value(node.tr, node.targs, node.bits,
                                            get_bits(word, node.start, node.bits))
    return kind.name, entity


def engine_encode(pack, name, entity):
    """The bytes of an entity as the named kind: the fields the entity holds
    and the values of the `when` lines; every other bit is zero; whole bytes
    up to the last bit a line names."""
    kind = next(k for k in pack.kinds if k.name == name)
    lines = pack.common + kind.lines
    word = 0
    for node in lines:
        if node.d == "field" and node.key in entity:
            word |= encode_value(node.tr, node.targs, node.bits, entity[node.key]) << node.start
        elif node.d == "when":
            word |= int(node.value) << node.start
    return word.to_bytes(message_bytes(lines), "little")


def geojson_encode(entity):
    """Canonical GeoJSON for an entity that holds no geojson key but lat/lon
    (engine-spec 0.1.1 rulings 3-5; packs/geojson/pack.def)."""
    if "lat" in entity and "lon" in entity:
        geom = '{"type":"Point","coordinates":[%s,%s]}' % (fmt_float(entity["lon"]), fmt_float(entity["lat"]))
    else:
        geom = "null"
    return '{"type":"Feature","geometry":%s,"properties":{}}' % geom


# ------------------------------------------------------------------ check ---

def _span(node):
    return node.start, node.start + node.bits


def check_frame_invariants(pack):
    """What must hold for a pack of MAVLink 2 frames beyond the load rules of
    the specification, over the Pack gtcheck loaded:

    - fixed-layout bits wire, `bit_order lsb`, `word_bytes 1`, only `when` and
      plain `field` lines with a transform the codec of this file implements;
    - a common `when` on STX;
    - every kind: a lower-case name; exactly one `when` on MSGID, one on LEN
      and no other; `requires` of one or more keys the kind itself maps; no key
      mapped twice; no two lines on the same bit; every field inside the
      payload LEN states, on byte boundaries;
    - no two kinds with the same `when` set."""
    def fail(message, line=None):
        raise GenError(message, pack.label, line)

    if (pack.wire, pack.layout, pack.bit_order, pack.word_bytes) != ("bits", "fixed", "lsb", 1):
        fail("a MAVLink 2 pack is wire bits, fixed layout, bit_order lsb, word_bytes 1")
    for scope in [pack.common] + [k.lines for k in pack.kinds]:
        for node in scope:
            if node.d not in ("when", "field"):
                fail("`%s` line: the frame has only `when` and `field` lines" % node.d, node.line)
            if node.d == "field" and (node.tr not in CODEC_TRANSFORMS or node.via or node.opts or node.also):
                fail("field %s: transform or option outside what a MAVLink 2 frame uses" % node.key, node.line)
    stx = (LOC_STX[0], LOC_STX[0] + LOC_STX[1], STX)
    if not any(n.d == "when" and _span(n) + (int(n.value),) == stx for n in pack.common):
        fail("common `when` on STX missing")
    when_sets = {}
    for kind in pack.kinds:
        where = "kind " + kind.name
        if not KIND_NAME_RE.match(kind.name):
            fail("%s: bad kind name" % where, kind.line)
        whens = [n for n in kind.lines if n.d == "when"]
        fields = [n for n in kind.lines if n.d == "field"]
        seen = set()
        for node in pack.common + fields:
            if node.d == "field":
                if node.key in seen:
                    fail("%s: duplicate-field %s" % (where, node.key), node.line)
                seen.add(node.key)
        if not kind.requires:
            fail("%s: no requires" % where, kind.line)
        own = {n.key for n in fields}
        for key in kind.requires:
            if key not in own:
                fail("%s: requires %s which the kind does not map" % (where, key), kind.line)
        ids = [int(n.value) for n in whens if (n.start, n.bits) == LOC_MSGID]
        lens = [int(n.value) for n in whens if (n.start, n.bits) == LOC_LEN]
        if len(ids) != 1 or len(lens) != 1 or len(whens) != 2:
            fail("%s: needs exactly one MSGID when and one LEN when" % where, kind.line)
        taken = sorted((_span(n) + (n.line,) for n in pack.common + kind.lines))
        for (_, a1, _), (b0, _, line) in zip(taken, taken[1:]):
            if b0 < a1:
                fail("%s: bit ranges overlap at %d" % (where, b0), line)
        end = PAYLOAD_BIT0 + 8 * lens[0]
        for node in fields:
            a0, a1 = _span(node)
            if a0 < PAYLOAD_BIT0 or a1 > end:
                fail("%s: field bits %d..%d outside the payload" % (where, a0, a1), node.line)
            if a0 % 8 or a1 % 8:
                fail("%s: field not byte aligned" % where, node.line)
        when_set = tuple(sorted(_span(n) + (int(n.value),) for n in whens))
        if when_set in when_sets:
            fail("%s: the same `when` set as kind %s" % (where, when_sets[when_set]), kind.line)
        when_sets[when_set] = kind.name


def check_pack_matches_plan(pack, module, plan):
    """The loaded pack states what was planned: the same kinds in the same
    order, each selected by its message id and full payload length, and the
    module declares exactly the `mavlink.` keys the pack maps."""
    if [k.name for k in pack.kinds] != [k.name for k in plan.kinds]:
        raise GenError("the kinds differ from the source messages", pack.label)
    for loaded, kind in zip(pack.kinds, plan.kinds):
        whens = sorted((n.start, n.bits, int(n.value)) for n in loaded.lines if n.d == "when")
        if whens != sorted([LOC_MSGID + (kind.message.id,), LOC_LEN + (kind.length,)]):
            raise GenError("kind %s: when lines do not match id and length" % kind.name, pack.label, loaded.line)
    used = set()
    for _, lines in pack.scopes():
        for node in gtcheck.walk(lines, "field"):
            module_name, key = gtcheck.split_key(node.key)
            if module_name == MODULE:
                used.add(key)
    if used != set(module.keys):
        raise GenError("module keys and mapped keys differ", module.label)


def check_vectors(pack, vectors):
    """Run every vector through the codec; the number checked.

    `vectors` is [(file name, JSON text)]. The input must decode to the kind
    and the model values the vector states; converting to `mavlink2` or to
    `geojson` must give `expect`; and every kind must have a same-format
    round trip."""
    names, kinds_seen, n = set(), set(), 0
    for file_name, text in vectors:
        label = "%s/%s" % (VECTOR_DIR, file_name)
        vec = json.loads(text)
        if vec["name"] in names:
            raise GenError("duplicate vector name " + vec["name"], label)
        names.add(vec["name"])
        try:
            kname, entity = engine_decode(pack, bytes.fromhex(vec["input"]))
            for key, want in vec.get("model", {}).items():
                if key == "@kind":
                    if want != kname:
                        raise GenError("decoded kind %s, vector says %s" % (kname, want), label)
                elif key not in entity:
                    raise GenError("model %s is not decoded" % key, label)
                elif isinstance(entity[key], float):
                    if abs(entity[key] - float(want)) > 1e-9:
                        raise GenError("model %s" % key, label)
                elif str(entity[key]) != want:
                    raise GenError("model %s" % key, label)
            if vec["to"] == FORMAT:
                got = engine_encode(pack, kname, entity).hex()
                kinds_seen.add(kname)
            elif vec["to"] == "geojson":
                got = geojson_encode(entity)
            else:
                raise GenError("unknown target %s" % vec["to"], label)
        except CodecError as e:
            raise GenError(str(e), label) from None
        if got != vec["expect"]:
            raise GenError("convert gives\n  %s\nvector expects\n  %s" % (got, vec["expect"]), label)
        n += 1
    missing = {k.name for k in pack.kinds} - kinds_seen
    if missing:
        raise GenError("kinds with no round-trip vector: %s" % sorted(missing), pack.label)
    return n


def load_output(out, core_text, core_label):
    """Load what the run wrote: (the gtcheck Model, the Pack). The module and
    the pack are read back through `out`, so the bytes checked are the bytes
    written (or, with --check, the bytes that would be written)."""
    model = gtcheck.Model()
    model.add(core_text, core_label)
    if MODULE != HEADER_MODULE:
        header_path = "model/%s.def" % HEADER_MODULE
        model.add(out.read(header_path), header_path)
        header = model.modules[HEADER_MODULE]
        for k, _, _ in COMMON_KEYS:
            if k not in header.keys:
                raise GenError("module %s declares no key %s; generate mavlink2 first" % (HEADER_MODULE, k),
                               header_path)
    model.add(out.read(MODEL_PATH), MODEL_PATH)
    return model, gtcheck.load_pack(out.read(PACK_PATH), model, PACK_PATH)


def read_vectors(out):
    """[(file name, text)] of the .json files in the vector directory, by name."""
    return [(name, out.read("%s/%s" % (VECTOR_DIR, name)))
            for name in out.listdir(VECTOR_DIR) if name.endswith(".json")]


# ------------------------------------------------------------------- main ---

def summary(plan, stats, sha, pack, module, written, checked):
    """The lines a successful run prints."""
    unmapped = collections.Counter(f.field.base for k in plan.kinds for f in k.fields
                                   if f.status == "unmapped")
    kinds = plan.kinds
    return [
        "commit            %s" % sha,
        "messages          %d %s" % (len(kinds), dict(stats["per_file"])),
        "kinds             %d" % len(pack.kinds),
        "payload fields    %d  mapped %d (scalar %d, ascii %d, element arrays %d = %d lines, core %d)"
        % (stats["fields"], stats["mapped"], stats["scalar"], stats["ascii"], stats["elements"],
           stats["element_lines"], stats["core"]),
        "not mapped        %d arrays > %d elements, by element type %s"
        % (stats["unmapped"], MAX_ARRAY_ELEMENTS, dict(unmapped)),
        "field lines       %d" % stats["field_lines"],
        "module keys       %d" % len(module.keys),
        "message-qualified %d fields %s" % (len(plan.qualified),
                                            dict(collections.Counter(plan.qualified.values()))),
        "kinds short of LEN %d; kinds whose requires another kind also satisfies %d"
        % (sum(k.mapped_len < k.length for k in kinds), sum(bool(k.shadowed_by) for k in kinds)),
        "vectors           %d written, %d checked" % (written, checked),
        "self-check        ok",
    ]


def check_known_dialect(messages):
    """Every message of the dialect has the CRC_EXTRA and full payload length
    KNOWN_DIALECT states; refuses one that differs or is missing."""
    table = KNOWN_DIALECT[DIALECT]
    if set(table) != {m.id for m in messages}:
        raise GenError("the CRC_EXTRA table and the messages of %s differ" % ROOT_XML, source_label(ROOT_XML))
    for m in messages:
        layout = lay_out(m)
        if (layout.crc_extra, layout.length) != table[m.id]:
            raise GenError("%s: CRC_EXTRA, length %s; the C library states %s"
                           % (m.name, (layout.crc_extra, layout.length), table[m.id]),
                           source_label(m.file), m.line)


def mappable(f):
    """A field --max-array lets the pack state."""
    return not (f.is_array and f.n > MAX_ARRAY)


def generate(out, core_text, core_label, src=None, provenance=None):
    """One run over the directory of `out`: parse, plan, emit, check. Returns
    the summary lines; raises GenError or gtcheck.CheckError."""
    src = src or out.path(SOURCE_DIR)
    sha = read_provenance(src, provenance)
    messages = load_messages(src)
    skipped = []
    if DIALECT:
        check_known_dialect(messages)
        # a message none of whose fields the pack can map gets no kind: it
        # would have no key to require
        skipped = [m for m in messages if not any(mappable(f) for f in m.fields)]
        messages = [m for m in messages if m not in skipped]
    plan = make_plan(messages)
    if DIALECT:
        for k in plan.kinds:
            if any(f.status == "core" for f in k.fields) and k.message.name not in POSITION_NOTES:
                raise GenError("%s binds core lat/lon but has no POSITION_NOTES entry" % k.message.name)
    else:
        check_known_crc_extra(plan.kinds)

    out.write(MODEL_PATH, emit_model(plan.keys, sha))
    out.write(PACK_PATH, emit_pack(plan.kinds, sha))
    vectors = vector_files(plan.kinds)
    write_vectors(out, vectors)

    model, pack = load_output(out, core_text, core_label)
    module = model.modules[MODULE]
    check_frame_invariants(pack)
    check_pack_matches_plan(pack, module, plan)
    checked = check_vectors(pack, read_vectors(out))
    if checked != len(vectors):
        raise GenError("%d vectors written, %d checked" % (len(vectors), checked), VECTOR_DIR)

    stats = collect_stats(plan)
    if DIALECT:
        out.write(PACK_MD_PATH, emit_dialect_md(plan, [lay_out(m) for m in skipped], stats, sha))
    else:
        out.write(PACK_MD_PATH, emit_pack_md(plan, stats, sha))
    lines = summary(plan, stats, sha, pack, module, len(vectors), checked)
    if skipped:
        lines.insert(2, "no kind           %d (no field the pack can map): %s"
                     % (len(skipped), ", ".join(m.name for m in skipped)))
    return lines


# The module-level choices as imported; `configure` returns to them first.
_BASE = (tuple(COMMON_KEYS), ROOT_XML, tuple(XML_FILES), tuple(CROSS), FORMAT, MODULE)


def build_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        prog=NAME,
        description="Generate the pack `mavlink2` from the MAVLink message definitions. "
                    "Reads DIR/sources/common.xml, standard.xml, minimal.xml and DIR/sources/PROVENANCE.md "
                    "(the commit and the SHA-256 of each file; a file that differs is refused). "
                    "Writes DIR/model/mavlink.def, DIR/packs/mavlink2/pack.def, pack.md and vectors/*.json. "
                    "Guarantees: the same inputs give the same bytes; the module and the pack are loaded by "
                    "gtcheck, the pack is held to the MAVLink 2 frame, and every vector is decoded and "
                    "encoded by the generator's codec. Exit status: 0 when every check passed, 1 for a "
                    "refused input or a failed check (one line on stderr), 2 for a usage error.")
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")),
                        what="the checkout to read sources/ from and to write into")
    ap.add_argument("--root", dest="out", metavar="DIR", default=argparse.SUPPRESS,
                    help="the same as --out")
    ap.add_argument("--core-def", metavar="PATH",
                    help="model/core.def to check the pack against; without it the check uses a stand-in "
                         "that declares only `lat` and `lon`")
    ap.add_argument("--dialect", metavar="NAME",
                    help="write the pack mavlink2-<name> of the dialect NAME.xml (its own messages only)")
    ap.add_argument("--src", metavar="DIR", help="the directory of the XML files (default DIR/sources)")
    ap.add_argument("--provenance", metavar="FILE",
                    help="the PROVENANCE.md with the commit and SHA-256 table (default SRC/PROVENANCE.md; "
                         "with --dialect DIR/packs/<format>/PROVENANCE.md)")
    ap.add_argument("--max-array", type=int, default=8, metavar="N",
                    help="map non-char arrays of up to N elements, one key per element (default 8)")
    ap.add_argument("--compat-flags", action="store_true",
                    help="map the INCOMPAT and COMPAT bytes as mavlink.incompat_flags, mavlink.compat_flags")
    return ap


def configure(args):
    """Set the module-level choices of one run from the parsed arguments."""
    global DIALECT, ROOT_XML, XML_FILES, CROSS, MAX_ARRAY, FLAGS, LEGACY, COMMON_KEYS
    if args.max_array < MAX_ARRAY_ELEMENTS or args.max_array > 255:
        raise GenError("--max-array is %d to 255" % MAX_ARRAY_ELEMENTS)
    MAX_ARRAY, FLAGS = args.max_array, args.compat_flags
    LEGACY = MAX_ARRAY == MAX_ARRAY_ELEMENTS and not FLAGS
    # every run starts from the defaults (main can be called more than once)
    COMMON_KEYS = list(_BASE[0]) + (FLAG_KEYS if FLAGS else [])
    DIALECT, ROOT_XML, XML_FILES, CROSS = None, _BASE[1], list(_BASE[2]), list(_BASE[3])
    set_names(_BASE[4], _BASE[5])
    if args.dialect:
        if args.dialect not in KNOWN_DIALECT:
            raise GenError("no CRC_EXTRA table for dialect %s" % args.dialect)
        DIALECT = args.dialect
        ROOT_XML = DIALECT + ".xml"
        set_names("mavlink2-" + DIALECT.lower(), "mavlink" + re.sub(r"[^a-z0-9]", "", DIALECT.lower()))
        XML_FILES = include_closure(args.src or os.path.join(args.out, SOURCE_DIR), ROOT_XML)
        CROSS = CROSS_DIALECT.get(DIALECT, [])


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = genio.Output(args.out, check=args.check)
    try:
        if args.core_def:
            with open(args.core_def, encoding="utf-8") as fh:
                core_text, core_label = fh.read(), args.core_def
        else:
            core_text, core_label = CORE_STAND_IN, "<core stand-in>"
        configure(args)
        provenance = args.provenance
        if DIALECT and not provenance:
            provenance = out.path(PACK_DIR + "/PROVENANCE.md")
        lines = generate(out, core_text, core_label, args.src, provenance)
    except (GenError, gtcheck.CheckError) as e:
        print("%s: %s" % (NAME, e), file=sys.stderr)
        return 1
    except OSError as e:
        print("%s: %s: %s" % (NAME, e.filename, e.strerror), file=sys.stderr)
        return 1
    print("\n".join(lines))
    return out.report(NAME)


if __name__ == "__main__":
    sys.exit(main())
