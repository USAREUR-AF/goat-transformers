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

Usage: mavlink2pack.py [--out DIR] [--check] [--core-def PATH/model/core.def]
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
COMMON_KEYS = [("seq", LOC_SEQ, "frame sequence number of the sending component, 0..255"),
               ("sysid", LOC_SYSID, "system id of the sender"),
               ("compid", LOC_COMPID, "component id of the sender")]

MAX_ARRAY_ELEMENTS = 8        # longer non-char arrays are not mapped
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


SourceMessage = collections.namedtuple("SourceMessage", "name id fields file line")
SourceMessage.__doc__ = """One <message>: its name, id, fields in declaration order, the name of the
file that declares it and the line of the element."""


def read_provenance(src):
    """The commit PROVENANCE.md states, after checking that every XML file has
    the SHA-256 its table row states."""
    label = source_label("PROVENANCE.md")
    with open(os.path.join(src, "PROVENANCE.md"), encoding="utf-8") as fh:
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
    __slots__ = ("name", "id", "fields", "line", "in_extensions")

    def __init__(self, name, msgid, line):
        self.name, self.id, self.line = name, msgid, line
        self.fields, self.in_extensions = [], False


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
    return reader.includes, [SourceMessage(m.name, m.id, tuple(m.fields), file_name, m.line)
                             for m in reader.messages]


def load_messages(src):
    """Every message of common.xml and of the files it includes, in id order.
    Refuses an include chain that is not exactly the three known files, and
    two messages with one id or one name."""
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
    return sorted(messages, key=lambda m: m.id)


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


def is_core_latlon(f):
    """True for a position this pack can state as core `lat` or `lon`: an
    int32_t in degE7 with that name and no value that means unknown."""
    return (f.name in ("lat", "lon") and f.units == "degE7" and f.base == "int32_t"
            and f.n is None and f.invalid is None)


def is_long_array(f):
    return f.is_array and f.n > MAX_ARRAY_ELEMENTS


def classify(layout):
    """(core_ok, the status of every field in wire order) of one message.

    A kind needs a raw key of its own for `requires`, so a message whose only
    mappable fields are lat and lon keeps them raw (core_ok is false)."""
    core_ok = any(not is_core_latlon(p.field) and not is_long_array(p.field) for p in layout.wire)
    statuses = []
    for p in layout.wire:
        f = p.field
        if is_long_array(f):
            statuses.append("unmapped")
        elif is_core_latlon(f) and core_ok:
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
    reserved = {k for k, _, _ in COMMON_KEYS}
    qualified = collections.OrderedDict()         # (message name, field name) -> reason
    for name, uses in proposals.items():
        reason = _clash_reason(name, uses, reserved)
        if reason:
            for m, f in uses:
                qualified[(m.name, f.name)] = reason

    # pass 3: declare the keys and write the lines
    keys = collections.OrderedDict()

    def declare(name, typ, unit, m, f):
        label = source_label(m.file)
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
                lines.append(Line(f.name, pos, 32, "sscale:" + DEGE7))
            elif status != "unmapped":
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
        fields.append(tuple(mapped))
    for k, _, _ in COMMON_KEYS:
        if k in keys:
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
    """The text of model/mavlink.def."""
    out = ["# The mavlink module: MAVLink fields in their wire units, as raw values.",
           "# Generated by tools/gen/mavlink2pack.py; do not edit by hand.",
           "# A key is shared by every message whose field has that name, type class,",
           "# units and enum; otherwise the key carries its message name.",
           "module        %s" % MODULE,
           "version       %s" % PACK_VERSION,
           "distribution  public"]
    out += _source_lines(sha)
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
    out = ["# MAVLink 2 frames, message set common.xml (with standard.xml, minimal.xml).",
           "# Generated by tools/gen/mavlink2pack.py; do not edit by hand.",
           "# One byte-aligned frame addressed by bit offset from the STX byte:",
           "# STX(8) LEN(8) INCOMPAT(8) COMPAT(8) SEQ(8) SYSID(8) COMPID(8) MSGID(24) PAYLOAD CRC(16).",
           "# Payload starts at bit %d. CRC, INCOMPAT and COMPAT are not mapped." % PAYLOAD_BIT0,
           "format        %s" % FORMAT,
           "version       %s" % PACK_VERSION,
           "distribution  public"]
    out += _source_lines(sha)
    out += ["uses          %s" % MODULE,
            "wire          bits",
            "bit_order     lsb",
            "word_bytes    1",
            "when   %s %d" % (loc(*LOC_STX), STX)]
    for k, location, _ in COMMON_KEYS:
        out.append("field  %s.%s %s uint" % (MODULE, k, loc(*location)))
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


def frame(kind, payload, seq, sysid, compid, with_crc):
    """A MAVLink 2 frame with both flag bytes zero. LEN is the kind's full
    payload length even when `payload` is cut short. The CRC covers every byte
    after STX and then CRC_EXTRA, and is written little-endian."""
    head = bytes([STX, kind.length, 0, 0, seq, sysid, compid]) + kind.message.id.to_bytes(3, "little")
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
            values[f.name] = {"lat": 1, "lon": -1}[f.name] * (100000000 + 1250000 * (msgid % 37))
        elif mapped.status == "elements":
            values[f.name] = [sample_value(f, salt + i) for i in range(f.n)]
        else:
            values[f.name] = sample_value(f, salt)
    payload = build_payload(kind, values)
    return frame(kind, payload[:kind.mapped_len], index % 256, 1 + msgid % 250, 1 + msgid % 191, False)


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
        model = collections.OrderedDict([("@kind", kind.name),
                                         ("lat", fmt_float(values["lat"] * 1.0 / 10000000.0)),
                                         ("lon", fmt_float(values["lon"] * 1.0 / 10000000.0)),
                                         (MODULE + ".seq", str(seq)),
                                         (MODULE + ".sysid", str(sysid)),
                                         (MODULE + ".compid", str(compid))])
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
    a("| ... `lat` / `lon` in degE7 to core `lat` / `lon` | %d |" % stats["core"])
    a("| Payload fields not mapped (arrays of more than %d elements) | %d |" % (
        MAX_ARRAY_ELEMENTS, stats["unmapped"]))
    a("| `field` lines in `pack.def` (3 common + per kind) | %d |" % stats["field_lines"])
    a("| Keys in module `mavlink` (3 frame-header + payload) | %d |" % (len(plan.keys) + 3))
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
    a("- CRC (2 bytes after the payload), INCOMPAT and COMPAT flags, and the 13-byte")
    a("  signature of a signed frame.")
    a("- %d array fields of more than %d elements (%d bytes of payload in total):" % (
        len(unmapped), MAX_ARRAY_ELEMENTS, sum(f.bytes for _, f in unmapped)))
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
    a("- **Short output.** In %d kinds the payload ends in unmapped array fields, so" % len(short))
    a("  encode output is shorter than `10 + LEN` bytes: %s." % _ticked(k.name for k in short))
    a("- **Unmapped bits do not round-trip.** The bits wire has no residue: INCOMPAT,")
    a("  COMPAT and unmapped arrays are written as zero.")
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
    a("is the frame as the encoder writes it (no CRC, unmapped arrays absent or zero),")
    a("so input and expected output are identical. Values are inside each field's")
    a("range; floats are multiples of 0.25 or 0.125; every other `uint64_t` sample has")
    a("its top bit set.")
    a("")
    a("`vectors/x-NN-<kind>-to-geojson.json`: %d full frames with a correct CRC," % len(CROSS))
    a("converted to GeoJSON. Expected output: `coordinates` = `[lon, lat]` in degrees")
    a("(wire value / 10^7), `properties` empty because `geojson` carries no other key")
    a("this pack maps.")
    return o


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


def generate(out, core_text, core_label):
    """One run over the directory of `out`: parse, plan, emit, check. Returns
    the summary lines; raises GenError or gtcheck.CheckError."""
    src = out.path(SOURCE_DIR)
    sha = read_provenance(src)
    plan = make_plan(load_messages(src))
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
    out.write(PACK_MD_PATH, emit_pack_md(plan, stats, sha))
    return summary(plan, stats, sha, pack, module, len(vectors), checked)


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
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = genio.Output(args.out, check=args.check)
    try:
        if args.core_def:
            with open(args.core_def, encoding="utf-8") as fh:
                core_text, core_label = fh.read(), args.core_def
        else:
            core_text, core_label = CORE_STAND_IN, "<core stand-in>"
        lines = generate(out, core_text, core_label)
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
