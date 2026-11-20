#!/usr/bin/env python3
"""opcua2pack: turn the structured DataTypes of an OPC UA NodeSet into one pack.

Reads: the NodeSet2 XML files given by --nodeset (the namespace to build and
every namespace its structures refer to; namespace 0 is
`http://opcfoundation.org/UA/`), model/core.def under --out, and the notes
file. Writes under --out: model/<module>.def, packs/<format>/pack.def,
pack.md and vectors/gen-*.json (every gen-*.json there is replaced).

The message of the pack is one ExtensionObject in the OPC UA binary encoding
(OPC 10000-6, 5.2) whose body is a structure of the namespace: the TypeId (the
NodeId of the structure's "Default Binary" encoding, in its compact form), the
encoding byte 0x01, the Int32 length of the body, then the body. The TypeId is
what selects the kind. The wire is `bits`, `layout sequential`, `bit_order
lsb`, so a field of 8n bits at a byte boundary is a little-endian integer.

How each built-in type is laid out (all counts and lengths Int32, LSB first):

  Boolean, (S)Byte, (U)Int16/32/64  uint or twos of 8, 16, 32, 64 bits
  Float, Double                      f32, f64
  DateTime                           twos 64 (100 ns ticks since 1601-01-01 UTC), or with
                                     --time-ms, core time_ms through
                                     siscale:1/10000:-11644473600000, absent for 0 and
                                     for the largest Int64 (no valid time)
  StatusCode, enumerations           uint 32, twos 32
  String, ByteString, XmlElement     a group of bytes counted by the length
  Guid                               uint 32, 16, 16 and eight bytes
  NodeId, ExpandedNodeId             the encoding byte and a `switch` on it
  QualifiedName                      uint 16 and a String
  LocalizedText                      `presence` of the mask, then the two Strings
  arrays (ValueRank 1)               a group counted by the length
  optional fields                    `presence` of the 32-bit EncodingMask, one `if` each
  unions                             the 32-bit SwitchField and a `switch` on it

What the language cannot state is not built and is listed in pack.md: a null
String, ByteString or array (length -1, which `count` and `length` read as
unsigned), Variant, DataValue, DiagnosticInfo and ExtensionObject fields
(abstract or subtyped field types), matrices, and recursive structures.

Guarantees: the same input gives the same bytes. A refused input writes
nothing. What was written is loaded with gtcheck, and every generated vector
is checked twice: its bytes are made by an OPC UA binary encoder written from
the type definitions, and a reader of the written pack.def (written from the
sequential-layout sections of the specification, importing no engine) must
decode them to the expected model and encode that model back to the same
bytes.

Exit status: 0 done (with --check: every file is what the generator writes),
1 a refused input, a failed check or a --check difference, 2 a usage error.

Python 3 standard library only.
"""
import argparse
import json
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

UANS = "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"
NS0 = "http://opcfoundation.org/UA/"
T = "{%s}" % UANS

BUILTIN = {1: "Boolean", 2: "SByte", 3: "Byte", 4: "Int16", 5: "UInt16", 6: "Int32", 7: "UInt32",
           8: "Int64", 9: "UInt64", 10: "Float", 11: "Double", 12: "String", 13: "DateTime",
           14: "Guid", 15: "ByteString", 16: "XmlElement", 17: "NodeId", 18: "ExpandedNodeId",
           19: "StatusCode", 20: "QualifiedName", 21: "LocalizedText", 22: "Structure",
           23: "DataValue", 24: "BaseDataType", 25: "DiagnosticInfo", 26: "Number", 27: "Integer",
           28: "UInteger", 29: "Enumeration"}
# fixed-size scalars: bits, transform, struct format
SCALAR = {"Boolean": (8, "uint", "<B"), "SByte": (8, "twos", "<b"), "Byte": (8, "uint", "<B"),
          "Int16": (16, "twos", "<h"), "UInt16": (16, "uint", "<H"), "Int32": (32, "twos", "<i"),
          "UInt32": (32, "uint", "<I"), "Int64": (64, "twos", "<q"), "UInt64": (64, "uint", "<Q"),
          "Float": (32, "f32", "<f"), "Double": (64, "f64", "<d"), "DateTime": (64, "twos", "<q"),
          "StatusCode": (32, "uint", "<I")}
BYTESEQ = ("String", "ByteString", "XmlElement")
NOT_CARRIED = {"DataValue": "a DataValue field", "BaseDataType": "a Variant field (BaseDataType)",
               "DiagnosticInfo": "a DiagnosticInfo field", "Number": "a Variant field (Number)",
               "Integer": "a Variant field (Integer)", "UInteger": "a Variant field (UInteger)",
               "Structure": "an ExtensionObject field (abstract Structure)"}
TICKS_TO_MS = "siscale:1/10000:-11644473600000"
EPOCH_OFFSET_MS = 11644473600000


class GenError(Exception):
    pass


class Unsupported(Exception):
    """A field the pack language cannot state; the message is the reason."""


# --------------------------------------------------------------------------
# reading NodeSets
# --------------------------------------------------------------------------

class DataType:
    def __init__(self, key, name, abstract, parent, fields, union, encoding, file):
        self.key, self.name, self.abstract, self.parent = key, name, abstract, parent
        self.fields, self.union, self.encoding, self.file = fields, union, encoding, file


class Field:
    def __init__(self, name, dtype, rank, dims, optional, subtypes):
        self.name, self.dtype, self.rank, self.dims = name, dtype, rank, dims
        self.optional, self.subtypes = optional, subtypes


def parse_nodeid(text, uris, label):
    """(namespace uri, identifier text) of a NodeId string in a file whose
    NamespaceUris are `uris` (index 1 is uris[0])."""
    m = re.fullmatch(r"(?:ns=(\d+);)?([isgb]=.+)", text.strip())
    if not m:
        raise GenError("%s: `%s` is not a NodeId" % (label, text))
    idx = int(m.group(1) or 0)
    if idx == 0:
        return (NS0, m.group(2))
    if idx > len(uris):
        raise GenError("%s: NodeId `%s` names namespace %d, which the file does not list" % (label, text, idx))
    return (uris[idx - 1], m.group(2))


def read_nodesets(paths):
    """{(uri, id): DataType} and {(uri, id): browse name} of every file."""
    types, encodings, models, inverse = {}, {}, {}, {}
    seen = set()
    for path in paths:
        label = os.path.basename(path)
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as e:
            raise GenError("%s: not well-formed XML: %s" % (label, e))
        if root.tag != T + "UANodeSet":
            raise GenError("%s: the root element is not a UANodeSet" % label)
        nu = root.find(T + "NamespaceUris")
        uris = [u.text.strip() for u in nu.findall(T + "Uri")] if nu is not None else []
        al = root.find(T + "Aliases")
        aliases = {a.get("Alias"): a.text.strip() for a in al.findall(T + "Alias")} if al is not None else {}
        for m in root.iter(T + "Model"):
            models[m.get("ModelUri")] = (m.get("Version"), m.get("PublicationDate"), label)

        def nid(text):
            return parse_nodeid(aliases.get(text.strip(), text.strip()), uris, label)

        for node in root:
            if node.get("NodeId") is None:
                continue
            key = nid(node.get("NodeId"))
            if key in seen:
                raise GenError("%s: NodeId %s is defined twice" % (label, node.get("NodeId")))
            seen.add(key)
            bname = node.get("BrowseName") or ""
            bname = bname.split(":", 1)[1] if re.match(r"\d+:", bname) else bname
            if node.tag == T + "UAObject" and bname == "Default Binary":
                encodings[key] = True
                refs = node.find(T + "References")
                for r in (refs.findall(T + "Reference") if refs is not None else []):
                    rt = aliases.get(r.get("ReferenceType"), r.get("ReferenceType"))
                    if rt in ("HasEncoding", "i=38") and r.get("IsForward", "true") == "false":
                        inverse.setdefault(nid(r.text), []).append(key)
            if node.tag != T + "UADataType":
                continue
            parent, encs = None, []
            refs = node.find(T + "References")
            for r in (refs.findall(T + "Reference") if refs is not None else []):
                rt = aliases.get(r.get("ReferenceType"), r.get("ReferenceType"))
                forward = r.get("IsForward", "true") != "false"
                if rt in ("HasSubtype", "i=45") and not forward:
                    if parent is not None:
                        raise GenError("%s: DataType %s has two supertypes" % (label, bname))
                    parent = nid(r.text)
                elif rt in ("HasEncoding", "i=38") and forward:
                    encs.append(nid(r.text))
            fields, union = None, False
            d = node.find(T + "Definition")
            if d is not None:
                union = d.get("IsUnion") == "true"
                fl = d.findall(T + "Field")
                if fl and any(f.get("Value") is not None for f in fl):
                    fields = "enum"
                else:
                    fields = []
                    for f in fl:
                        dt = f.get("DataType", "i=24")
                        dims = f.get("ArrayDimensions")
                        fields.append(Field(f.get("Name"), nid(dt), int(f.get("ValueRank", "-1")), dims,
                                            f.get("IsOptional") == "true", f.get("AllowSubTypes") == "true"))
            types[key] = DataType(key, bname, node.get("IsAbstract") == "true", parent, fields, union,
                                  encs, label)
    for t in types.values():
        found = sorted(set(e for e in t.encoding if e in encodings) | set(inverse.get(t.key, [])))
        if len(found) > 1:
            raise GenError("%s: DataType %s has %d Default Binary encodings" % (t.file, t.name, len(found)))
        t.encoding = found[0] if found else None
    return types, models


# --------------------------------------------------------------------------
# classifying types
# --------------------------------------------------------------------------

def builtin_of(types, key, label):
    """The name of the built-in type `key` is, or derives from, by HasSubtype."""
    seen = set()
    while True:
        if key[0] == NS0 and key[1].startswith("i=") and int(key[1][2:]) in BUILTIN:
            return BUILTIN[int(key[1][2:])]
        if key in seen:
            raise GenError("%s: the supertypes of %s form a cycle" % (label, key))
        seen.add(key)
        t = types.get(key)
        if t is None:
            raise GenError("%s: DataType %s is in no given NodeSet" % (label, "%s %s" % key))
        if t.parent is None:
            raise GenError("%s: DataType %s has no supertype" % (label, t.name))
        key = t.parent


def is_struct(types, key):
    return builtin_of(types, key, "?") == "Structure" and key != (NS0, "i=22")


def all_fields(types, t):
    """The fields of structure `t` in encoding order: those of its supertypes first."""
    chain = []
    k = t.key
    while k is not None and k != (NS0, "i=22") and k in types and types[k].fields not in (None, "enum"):
        chain.append(types[k])
        k = types[k].parent
    out = []
    for c in reversed(chain):
        out += c.fields
    return out


def snake(name):
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([0-9])([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s or "x"


# --------------------------------------------------------------------------
# planning lines
# --------------------------------------------------------------------------
# A line is a tuple:
#   ("field", key, bits, transform, absent or None)
#   ("group", list, [lines])                 counted by 32 bits
#   ("presence", name, n)
#   ("if", [name.i], [lines])
#   ("switch", key, [(value, [lines])])
#   ("length", [lines])

class Planner:
    def __init__(self, types, module, time_fields):
        self.types, self.module, self.time_fields = types, module, set(time_fields)
        self.keys = {}       # name -> (type, meaning)
        self.lists = {}      # name -> meaning
        self.presence = 0
        self.dropped = []    # (where, reason) of optional fields and union members left out

    def key(self, name, typ, meaning):
        old = self.keys.get(name)
        if name in self.lists or (old and old[0] != typ):
            raise GenError("key name `%s` is made twice with different meanings" % name)
        self.keys.setdefault(name, (typ, meaning))
        return self.module + "." + name

    def lst(self, name, meaning):
        if name in self.keys:
            raise GenError("list name `%s` is also a key" % name)
        self.lists.setdefault(name, meaning)
        return self.module + "." + name

    def pname(self):
        self.presence += 1
        return "p%d" % self.presence

    def byteseq(self, p, what):
        lst = self.lst(p, "the bytes of %s, one item per byte" % what)
        return [("group", lst, [("field", self.key(p + "_byte", "int", "one byte of %s" % what),
                                 8, "uint", None)])]

    def builtin(self, b, p, what):
        if b in SCALAR:
            bits, tr, _ = SCALAR[b]
            unit = "-"
            meaning = "%s (%s)" % (what, b)
            if b == "DateTime":
                meaning = "%s (DateTime, 100 ns ticks since 1601-01-01 UTC)" % what
            return [("field", self.key(p, "float" if tr in ("f32", "f64") else "int", meaning), bits, tr, None)]
        if b in BYTESEQ:
            return self.byteseq(p, what)
        if b == "Guid":
            out = [("field", self.key(p + "_data1", "int", "%s, Guid Data1" % what), 32, "uint", None),
                   ("field", self.key(p + "_data2", "int", "%s, Guid Data2" % what), 16, "uint", None),
                   ("field", self.key(p + "_data3", "int", "%s, Guid Data3" % what), 16, "uint", None)]
            for i in range(8):
                out.append(("field", self.key("%s_data4_%d" % (p, i), "int", "%s, Guid Data4 byte %d" % (what, i)),
                            8, "uint", None))
            return out
        if b == "QualifiedName":
            return [("field", self.key(p + "_namespace_index", "int", "%s, namespace index" % what), 16, "uint", None)] \
                + self.byteseq(p + "_name", "%s, name" % what)
        if b == "LocalizedText":
            n = self.pname()
            return [("presence", n, 8),
                    ("if", [n + ".1"], self.byteseq(p + "_locale", "%s, locale" % what)),
                    ("if", [n + ".2"], self.byteseq(p + "_text", "%s, text" % what))]
        if b == "NodeId":
            enc = self.key(p + "_encoding", "int", "%s, NodeId encoding byte" % what)
            return [("field", enc, 8, "uint", None), self.nodeid_switch(enc, p, what)]
        if b == "ExpandedNodeId":
            enc = self.key(p + "_encoding", "int", "%s, ExpandedNodeId encoding (low six bits)" % what)
            n = self.pname()
            return [("field", enc, 6, "uint", None), ("presence", n, 2), self.nodeid_switch(enc, p, what),
                    ("if", [n + ".2"], self.byteseq(p + "_namespace_uri", "%s, namespace URI" % what)),
                    ("if", [n + ".1"], [("field", self.key(p + "_server_index", "int", "%s, server index" % what),
                                         32, "uint", None)])]
        raise Unsupported(NOT_CARRIED.get(b, "a %s field" % b))

    def nodeid_switch(self, enc, p, what):
        ns = lambda bits: ("field", self.key(p + "_namespace", "int", "%s, namespace index" % what), bits, "uint", None)
        ident = lambda bits: ("field", self.key(p + "_id", "int", "%s, numeric identifier" % what), bits, "uint", None)
        return ("switch", enc, [
            (0, [ident(8)]),
            (1, [ns(8), ident(16)]),
            (2, [ns(16), ident(32)]),
            (3, [ns(16)] + self.byteseq(p + "_string_id", "%s, string identifier" % what)),
            (4, [ns(16)] + self.builtin("Guid", p + "_guid_id", "%s, Guid identifier" % what)),
            (5, [ns(16)] + self.byteseq(p + "_opaque_id", "%s, opaque identifier" % what))])

    def element(self, key, p, what, stack):
        """Lines of one value of DataType `key` at name prefix `p`."""
        b = builtin_of(self.types, key, what)
        if b == "Enumeration":
            if key == (NS0, "i=29"):
                raise Unsupported("an abstract Enumeration field")
            return [("field", self.key(p, "int", "%s (enumeration, Int32)" % what), 32, "twos", None)]
        if b != "Structure":
            return self.builtin(b, p, what)
        t = self.types[key]
        if key == (NS0, "i=22") or t.abstract:
            raise Unsupported("an ExtensionObject field (abstract structure %s)" % t.name)
        if key in stack:
            raise Unsupported("a recursive structure (%s)" % t.name)
        return self.body(t, p, stack + [key], top=False)

    def body(self, t, p, stack, top):
        fields = all_fields(self.types, t)
        out = []
        if t.union:
            sw = self.key(p + "_switch_field", "int", "%s: the union's SwitchField" % t.name)
            cases = []
            for i, f in enumerate(fields, 1):
                try:
                    cases.append((i, self.member(t, f, p, stack, top)))
                except Unsupported as e:
                    self.dropped.append(("%s.%s" % (t.name, f.name), str(e)))
            return [("field", sw, 32, "uint", None), ("switch", sw, [(0, [])] + cases)]
        optional = [f for f in fields if f.optional]
        mask = None
        if optional:
            mask = self.pname()
            out.append(("presence", mask, 32))
        bit = 0
        for f in fields:
            if f.optional:
                bit += 1
                try:
                    out.append(("if", ["%s.%d" % (mask, bit)], self.member(t, f, p, stack, top)))
                except Unsupported as e:
                    self.dropped.append(("%s.%s" % (t.name, f.name), str(e)))
            else:
                out += self.member(t, f, p, stack, top)
        return out

    def member(self, t, f, p, stack, top):
        q = p + "_" + snake(f.name)
        what = "field %s of %s" % (f.name, t.name)
        if f.subtypes:
            raise Unsupported("a field whose value may be a subtype (AllowSubTypes)")
        if f.rank == -1:
            if top and f.name in self.time_fields and builtin_of(self.types, f.dtype, what) == "DateTime":
                return [("field", "time_ms", 64, TICKS_TO_MS, "0,9223372036854775807")]
            return self.element(f.dtype, q, what, stack)
        if f.rank == 1 and (f.dims or "0") == "0":
            items = self.element(f.dtype, q + "_item" if self.scalar_like(f.dtype, what) else q, what + ", one item",
                                 stack)
            return [("group", self.lst(q, "the items of array %s" % what), items)]
        raise Unsupported("an array of ValueRank %d" % f.rank)

    def scalar_like(self, key, what):
        b = builtin_of(self.types, key, what)
        return b != "Structure" or key == (NS0, "i=22")


def compact_nodeid(ns, ident):
    """The bytes of a numeric NodeId in its smallest encoding (OPC 10000-6, 5.2.2.9)."""
    if ns == 0 and ident <= 0xFF:
        return [(8, 0), (8, ident)]
    if ns <= 0xFF and ident <= 0xFFFF:
        return [(8, 1), (8, ns), (16, ident)]
    return [(8, 2), (16, ns), (32, ident)]


# --------------------------------------------------------------------------
# writing the pack
# --------------------------------------------------------------------------

def emit(lines, ind, out):
    sp = "  " * ind
    for ln in lines:
        k = ln[0]
        if k == "field":
            s = "%sfield  %s  %d  %s" % (sp, ln[1], ln[2], ln[3])
            if ln[4] is not None:
                s += "  absent %s" % ln[4]
            out.append(s)
        elif k == "group":
            out.append("%sgroup  %s  count 32" % (sp, ln[1]))
            emit(ln[2], ind + 1, out)
            out.append(sp + "end")
        elif k == "presence":
            out.append("%spresence  %s  %d" % (sp, ln[1], ln[2]))
        elif k == "if":
            out.append("%sif  %s" % (sp, " ".join(ln[1])))
            emit(ln[2], ind + 1, out)
            out.append(sp + "end")
        elif k == "switch":
            out.append("%sswitch  %s" % (sp, ln[1]))
            for v, body in ln[2]:
                out.append("%s  case  %d" % (sp, v))
                emit(body, ind + 2, out)
            out.append(sp + "end")
        elif k == "length":
            out.append("%slength  32  bytes" % sp)
            emit(ln[1], ind + 1, out)
            out.append(sp + "end")
        elif k == "when":
            out.append("%swhen  %d  %d" % (sp, ln[1], ln[2]))
        else:
            raise AssertionError(k)


def first_key(lines):
    for ln in lines:
        if ln[0] == "field" and ln[1] != "time_ms":
            return ln[1]
        if ln[0] == "group":
            return ln[1]
    for ln in lines:
        if ln[0] == "if":
            k = first_key(ln[2])
            if k:
                return k
    return None


# --------------------------------------------------------------------------
# a reader of the written pack (engine-spec 0.7, 0.8, 0.9, 0.15, 0.20), for checks
# --------------------------------------------------------------------------

class Malformed(Exception):
    pass


def parse_pack(text):
    """(common lines, [(kind, when lines, lines)]) of a pack.def this generator writes."""
    rows = []
    for raw in text.split("\n"):
        s = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("source") else raw.rstrip()
        if not s.strip():
            continue
        rows.append(s.split())
    pos = 0
    header = {"format", "version", "distribution", "source", "uses", "wire", "layout", "bit_order"}

    def block(stop):
        nonlocal pos
        out = []
        while pos < len(rows):
            r = rows[pos]
            if r[0] in stop:
                return out
            pos += 1
            if r[0] == "field":
                out.append(("field", r[1], int(r[2]), r[3], r[5] if len(r) > 5 and r[4] == "absent" else None))
            elif r[0] == "group":
                body = block({"end"}); pos += 1
                out.append(("group", r[1], body))
            elif r[0] == "presence":
                out.append(("presence", r[1], int(r[2])))
            elif r[0] == "if":
                body = block({"end"}); pos += 1
                out.append(("if", r[1:], body))
            elif r[0] == "length":
                body = block({"end"}); pos += 1
                out.append(("length", body))
            elif r[0] == "when":
                out.append(("when", int(r[1]), int(r[2])))
            elif r[0] == "switch":
                cases = []
                while rows[pos][0] == "case":
                    v = int(rows[pos][1]); pos += 1
                    cases.append((v, block({"case", "end"})))
                pos += 1
                out.append(("switch", r[1], cases))
            elif r[0] in header or r[0] == "requires":
                continue
            else:
                raise GenError("reader: unexpected line %s" % " ".join(r))
        return out

    common = block({"kind"})
    kinds = []
    while pos < len(rows):
        name = rows[pos][1]; pos += 1
        lines = block({"kind"})
        whens = [ln for ln in lines if ln[0] == "when"]
        kinds.append((name, whens, [ln for ln in lines if ln[0] != "when"]))
    return common, kinds


class Bits:
    def __init__(self, data):
        self.data, self.pos, self.limit = data, 0, [len(data) * 8]

    def read(self, n):
        if self.pos + n > self.limit[-1]:
            raise Malformed("read past the end")
        v = 0
        for k in range(n):
            i = self.pos + k
            v |= ((self.data[i // 8] >> (i % 8)) & 1) << k
        self.pos += n
        return v


def raw_to(tr, n, v):
    if tr == "uint":
        return v
    if tr == "twos":
        return v - (1 << n) if v >> (n - 1) else v
    if tr == "f32":
        return struct.unpack("<f", struct.pack("<I", v))[0]
    if tr == "f64":
        return struct.unpack("<d", struct.pack("<Q", v))[0]
    if tr == TICKS_TO_MS:
        s = v - (1 << 64) if v >> 63 else v
        q, r = divmod(abs(s), 10000)
        q += 1 if r * 2 >= 10000 else 0
        return (q if s >= 0 else -q) - EPOCH_OFFSET_MS
    raise AssertionError(tr)


def to_raw(tr, n, x):
    if tr in ("uint", "twos"):
        return x & ((1 << n) - 1)
    if tr == "f32":
        return struct.unpack("<I", struct.pack("<f", x))[0]
    if tr == "f64":
        return struct.unpack("<Q", struct.pack("<d", x))[0]
    if tr == TICKS_TO_MS:
        return ((x + EPOCH_OFFSET_MS) * 10000) & ((1 << 64) - 1)
    raise AssertionError(tr)


def new_ent():
    return {"keys": {}, "lists": {}}


def dec_lines(r, lines, ent, pres):
    pres = dict(pres)
    for ln in lines:
        k = ln[0]
        if r.pos >= r.limit[-1] and len(r.limit) > 1 and k in ("field", "group"):
            continue
        if k == "field":
            v = r.read(ln[2])
            if ln[4] is not None and v in [int(x) for x in ln[4].split(",")]:
                continue
            ent["keys"][ln[1]] = raw_to(ln[3], ln[2], v)
        elif k == "group":
            n = r.read(32)
            if n * 8 > r.limit[-1] - r.pos:
                raise Malformed("count larger than the bits left")
            items = []
            for _ in range(n):
                it = new_ent()
                dec_lines(r, ln[2], it, {})
                items.append(it)
            ent["lists"][ln[1]] = items
        elif k == "presence":
            v = r.read(ln[2])
            pres[ln[1]] = [(v >> i) & 1 for i in range(ln[2])]
            named = set()
            for other in lines:
                if other[0] == "if":
                    for c in other[1]:
                        nm, i = c.split(".")
                        if nm == ln[1]:
                            named.add(int(i))
            if any(b and (i + 1) not in named for i, b in enumerate(pres[ln[1]])):
                raise Malformed("presence bit with no block")
        elif k == "if":
            if all(pres[c.split(".")[0]][int(c.split(".")[1]) - 1] for c in ln[1]):
                dec_lines(r, ln[2], ent, pres)
        elif k == "switch":
            v = ent["keys"].get(ln[1])
            body = next((b for val, b in ln[2] if val == v), None)
            if body is None:
                raise Malformed("no case")
            dec_lines(r, body, ent, pres)
        elif k == "length":
            n = r.read(32)
            end = r.pos + 8 * n
            if end > r.limit[-1]:
                raise Malformed("length past the end")
            r.limit.append(end)
            dec_lines(r, ln[1], ent, pres)
            r.limit.pop()
            r.pos = end
        else:
            raise AssertionError(k)


def decode(pack, data):
    common, kinds = pack
    r = Bits(data)
    ent = new_ent()
    for ln in common:
        if ln[0] == "when":
            if r.read(ln[1]) != ln[2]:
                raise Malformed("no-kind")
        else:
            dec_lines(r, [ln], ent, {})
    start = r.pos
    for name, whens, lines in kinds:
        r.pos = start
        if all(r.read(w[1]) == w[2] for w in whens):
            ent["kind"] = name
            dec_lines(r, lines, ent, {})
            return ent
    raise Malformed("no-kind")


class Out:
    def __init__(self):
        self.bits = []

    def write(self, n, v):
        self.bits += [(v >> k) & 1 for k in range(n)]

    def data(self):
        b = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(sum(b[i + k] << k for k in range(8)) for i in range(0, len(b), 8))


def has_content(lines, ent):
    for ln in lines:
        k = ln[0]
        if k == "field" and ln[1] in ent["keys"]:
            return True
        if k == "group" and ent["lists"].get(ln[1]):
            return True
        if k in ("if", "length") and has_content(ln[-1], ent):
            return True
        if k == "switch":
            v = ent["keys"].get(ln[1], 0)
            body = next((b for val, b in ln[2] if val == v), [])
            if has_content(body, ent):
                return True
    return False


def enc_lines(w, lines, ent, pres):
    pres = dict(pres)
    for ln in lines:
        k = ln[0]
        if k == "field":
            if ln[1] in ent["keys"]:
                w.write(ln[2], to_raw(ln[3], ln[2], ent["keys"][ln[1]]))
            else:
                w.write(ln[2], int(ln[4].split(",")[0]) if ln[4] is not None else 0)
        elif k == "group":
            items = ent["lists"].get(ln[1], [])
            w.write(32, len(items))
            for it in items:
                enc_lines(w, ln[2], it, {})
        elif k == "presence":
            bits = [0] * ln[2]
            for other in lines:
                if other[0] == "if" and has_content(other[2], ent):
                    for c in other[1]:
                        nm, i = c.split(".")
                        if nm == ln[1]:
                            bits[int(i) - 1] = 1
            pres[ln[1]] = bits
            w.write(ln[2], sum(b << i for i, b in enumerate(bits)))
        elif k == "if":
            if all(pres[c.split(".")[0]][int(c.split(".")[1]) - 1] for c in ln[1]):
                enc_lines(w, ln[2], ent, pres)
        elif k == "switch":
            v = ent["keys"].get(ln[1], 0)
            body = next((b for val, b in ln[2] if val == v), None)
            if body is None:
                raise Malformed("no case on encode")
            enc_lines(w, body, ent, pres)
        elif k == "length":
            sub = Out()
            enc_lines(sub, ln[1], ent, pres)
            data = sub.data()
            w.write(32, len(data))
            for byte in data:
                w.write(8, byte)
        else:
            raise AssertionError(k)


def encode(pack, ent):
    common, kinds = pack
    w = Out()
    for ln in common:
        if ln[0] == "when":
            w.write(ln[1], ln[2])
    enc_lines(w, [ln for ln in common if ln[0] != "when"], ent, {})
    name, whens, lines = next(kd for kd in kinds if kd[0] == ent["kind"])
    for wl in whens:
        w.write(wl[1], wl[2])
    enc_lines(w, lines, ent, {})
    return w.data()


# --------------------------------------------------------------------------
# sample values, the OPC UA binary encoder, and the model they give
# --------------------------------------------------------------------------
# A value is: int, float, bytes (String, ByteString, XmlElement), a dict for a
# structure ({field name: value}, an optional field left out when absent), a
# ("union", index, value) tuple, a list for an array, or a dict with the key
# "@nodeid" / "@guid" / "@qn" / "@lt" / "@xnodeid" for those built-ins.

class Sampler:
    def __init__(self, types, mode):
        self.types, self.mode, self.n = types, mode, 0

    def next(self):
        self.n += 1
        return self.n

    def builtin(self, b, depth):
        n = self.next()
        if b == "Boolean":
            return n % 2
        if b in ("SByte",):
            return -(n % 100)
        if b == "Byte":
            return n % 250 + 1
        if b == "Int16":
            return -300 - n
        if b == "UInt16":
            return 1000 + n
        if b == "Int32":
            return -70000 - n
        if b in ("UInt32", "StatusCode"):
            return 3000000000 + n
        if b == "Int64":
            return -5000000000 - n
        if b == "UInt64":
            return 10000000000000000000 + n
        if b == "Float":
            return n + 0.5
        if b == "Double":
            return -(n + 0.25)
        if b == "DateTime":
            return 133000000000000000 + n * 10000
        if b in BYTESEQ:
            return ("v%d" % n).encode("ascii")
        if b == "Guid":
            return {"@guid": (0x01020304 + n, 0x0506, 0x0708, bytes(range(n % 7, n % 7 + 8)))}
        if b == "QualifiedName":
            return {"@qn": (n % 5, ("q%d" % n).encode())}
        if b == "LocalizedText":
            return {"@lt": (b"en" if self.mode == 0 else None, ("t%d" % n).encode())}
        if b in ("NodeId", "ExpandedNodeId"):
            form = n % 6
            ident = {0: n % 256, 1: 1000 + n, 2: 70000 + n, 3: ("s%d" % n).encode(),
                     4: (0x0a0b0c0d, 1, 2, bytes(range(8))), 5: bytes([n % 256, 1, 2])}[form]
            nid = {"form": form, "ns": 0 if form == 0 else (2 if form == 1 else 300), "id": ident}
            if b == "NodeId":
                return {"@nodeid": nid}
            return {"@xnodeid": (nid, b"urn:x" if self.mode == 0 else None, 7 if self.mode == 0 else None)}
        raise AssertionError(b)

    def value(self, key, depth, stack):
        b = builtin_of(self.types, key, "?")
        if b == "Enumeration":
            return self.next() % 3
        if b != "Structure":
            return self.builtin(b, depth)
        return self.struct(self.types[key], depth, stack + [key])

    def struct(self, t, depth, stack, plan_dropped=()):
        fields = all_fields(self.types, t)
        ok = [i for i, f in enumerate(fields) if ("%s.%s" % (t.name, f.name)) not in self.dropped]
        if t.union:
            if not ok:
                return ("union", 0, None)
            i = ok[0] if self.mode == 0 else ok[-1]
            return ("union", i + 1, self.member(fields[i], depth, stack))
        out = {}
        for i, f in enumerate(fields):
            if f.optional and (self.mode == 1 or i not in ok):
                continue
            out[f.name] = self.member(f, depth, stack)
        return out

    def member(self, f, depth, stack):
        if f.rank == 1:
            count = (2 if depth < 1 else 1) if self.mode == 0 else 0
            return [self.value(f.dtype, depth + 1, stack) for _ in range(count)]
        return self.value(f.dtype, depth, stack)


def enc_bytes(b):
    return struct.pack("<i", len(b)) + b


def enc_guid(g):
    return struct.pack("<IHH", g[0], g[1], g[2]) + g[3]


def enc_nodeid(nid, flags=0):
    f, ns, ident = nid["form"], nid["ns"], nid["id"]
    head = bytes([f | flags])
    if f == 0:
        return head + bytes([ident])
    if f == 1:
        return head + bytes([ns]) + struct.pack("<H", ident)
    if f == 2:
        return head + struct.pack("<HI", ns, ident)
    if f in (3, 5):
        return head + struct.pack("<H", ns) + enc_bytes(ident)
    return head + struct.pack("<H", ns) + enc_guid(ident)


def ua_encode(types, key, v, time_field=None):
    """The OPC UA binary encoding of value `v` of DataType `key` (OPC 10000-6, 5.2)."""
    b = builtin_of(types, key, "?")
    if b == "Enumeration":
        return struct.pack("<i", v)
    if b in SCALAR:
        return struct.pack(SCALAR[b][2], v)
    if b in BYTESEQ:
        return enc_bytes(v)
    if b == "Guid":
        return enc_guid(v["@guid"])
    if b == "QualifiedName":
        return struct.pack("<H", v["@qn"][0]) + enc_bytes(v["@qn"][1])
    if b == "LocalizedText":
        loc, txt = v["@lt"]
        mask = (1 if loc is not None else 0) | (2 if txt is not None else 0)
        return bytes([mask]) + (enc_bytes(loc) if loc is not None else b"") + (enc_bytes(txt) if txt is not None else b"")
    if b == "NodeId":
        return enc_nodeid(v["@nodeid"])
    if b == "ExpandedNodeId":
        nid, uri, srv = v["@xnodeid"]
        out = enc_nodeid(nid, (0x80 if uri is not None else 0) | (0x40 if srv is not None else 0))
        if uri is not None:
            out += enc_bytes(uri)
        if srv is not None:
            out += struct.pack("<I", srv)
        return out
    t = types[key]
    fields = all_fields(types, t)
    if t.union:
        _, i, inner = v
        out = struct.pack("<I", i)
        return out + (ua_member(types, fields[i - 1], inner) if i else b"")
    out = b""
    optional = [f for f in fields if f.optional]
    if optional:
        mask = sum(1 << j for j, f in enumerate(optional) if f.name in v)
        out += struct.pack("<I", mask)
    for f in fields:
        if f.name in v:
            out += ua_member(types, f, v[f.name])
    return out


def ua_member(types, f, v):
    if f.rank == 1:
        return struct.pack("<i", len(v)) + b"".join(ua_encode(types, f.dtype, x) for x in v)
    return ua_encode(types, f.dtype, v)


class ModelOf:
    """The decoded model a value gives, with the key names of the Planner."""

    def __init__(self, types, module, time_fields):
        self.types, self.m, self.time_fields = types, module, set(time_fields)

    def k(self, name):
        return self.m + "." + name

    def bytes_(self, ent, p, b):
        ent["lists"][self.k(p)] = [{"keys": {self.k(p + "_byte"): x}, "lists": {}} for x in b]

    def nodeid(self, ent, p, nid, enc_key_bits_extra=0):
        f, ns, ident = nid["form"], nid["ns"], nid["id"]
        ent["keys"][self.k(p + "_encoding")] = f
        if f != 0:
            ent["keys"][self.k(p + "_namespace")] = ns
        if f in (0, 1, 2):
            ent["keys"][self.k(p + "_id")] = ident
        elif f == 3:
            self.bytes_(ent, p + "_string_id", ident)
        elif f == 5:
            self.bytes_(ent, p + "_opaque_id", ident)
        else:
            self.guid(ent, p + "_guid_id", ident)

    def guid(self, ent, p, g):
        ent["keys"][self.k(p + "_data1")] = g[0]
        ent["keys"][self.k(p + "_data2")] = g[1]
        ent["keys"][self.k(p + "_data3")] = g[2]
        for i in range(8):
            ent["keys"][self.k("%s_data4_%d" % (p, i))] = g[3][i]

    def value(self, ent, key, p, v):
        b = builtin_of(self.types, key, "?")
        if b == "Enumeration" or b in SCALAR:
            ent["keys"][self.k(p)] = v
        elif b in BYTESEQ:
            self.bytes_(ent, p, v)
        elif b == "Guid":
            self.guid(ent, p, v["@guid"])
        elif b == "QualifiedName":
            ent["keys"][self.k(p + "_namespace_index")] = v["@qn"][0]
            self.bytes_(ent, p + "_name", v["@qn"][1])
        elif b == "LocalizedText":
            loc, txt = v["@lt"]
            if loc:
                self.bytes_(ent, p + "_locale", loc)
            if txt:
                self.bytes_(ent, p + "_text", txt)
        elif b == "NodeId":
            self.nodeid(ent, p, v["@nodeid"])
        elif b == "ExpandedNodeId":
            nid, uri, srv = v["@xnodeid"]
            self.nodeid(ent, p, nid)
            if uri is not None:
                self.bytes_(ent, p + "_namespace_uri", uri)
            if srv is not None:
                ent["keys"][self.k(p + "_server_index")] = srv
        else:
            self.struct(ent, self.types[key], p, v, top=False)

    def struct(self, ent, t, p, v, top):
        fields = all_fields(self.types, t)
        if t.union:
            _, i, inner = v
            ent["keys"][self.k(p + "_switch_field")] = i
            if i:
                self.member(ent, t, fields[i - 1], p, inner, top)
            return
        for f in fields:
            if f.name in v:
                self.member(ent, t, f, p, v[f.name], top)

    def member(self, ent, t, f, p, v, top):
        q = p + "_" + snake(f.name)
        if f.rank == 1:
            scalar = builtin_of(self.types, f.dtype, "?") != "Structure"
            items = []
            for x in v:
                it = {"keys": {}, "lists": {}}
                self.value(it, f.dtype, q + "_item" if scalar else q, x)
                items.append(it)
            ent["lists"][self.k(q)] = items
        elif top and f.name in self.time_fields and builtin_of(self.types, f.dtype, "?") == "DateTime":
            ent["keys"]["time_ms"] = raw_to(TICKS_TO_MS, 64, v)
        else:
            self.value(ent, f.dtype, q, v)


def fmt(x):
    if isinstance(x, float):
        if x == int(x) and abs(x) < 1e17:
            return str(int(x))
        r = repr(x)
        return format(Decimal(r), "f") if "e" in r or "E" in r else r
    return str(x)


def model_strings(ent, prefix=""):
    out = {}
    for k, v in ent["keys"].items():
        out[prefix + k] = fmt(v)
    for name, items in ent["lists"].items():
        out[prefix + name + ".#"] = str(len(items))
        for i, it in enumerate(items):
            out.update(model_strings(it, "%s%s[%d]." % (prefix, name, i)))
    return out


def same_ent(a, b):
    return model_strings(a) == model_strings(b)


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def build(args):
    types, models = read_nodesets(args.nodeset)
    target = args.namespace
    if target not in models:
        raise GenError("no given NodeSet defines the model %s" % target)
    planner = Planner(types, args.module, args.time_ms)
    kinds, skipped = [], []
    ns_index = 0 if target == NS0 else 2
    for t in sorted((t for t in types.values() if t.key[0] == target), key=lambda t: t.name):
        if t.fields is None or t.fields == "enum":
            continue
        try:
            if not is_struct(types, t.key):
                continue
        except GenError:
            continue
        if t.abstract:
            skipped.append((t.name, "abstract: no encoding of its own"))
            continue
        if t.encoding is None:
            skipped.append((t.name, "no Default Binary encoding"))
            continue
        if not t.encoding[1].startswith("i="):
            skipped.append((t.name, "the encoding NodeId is not numeric"))
            continue
        saved = (dict(planner.keys), dict(planner.lists), planner.presence, list(planner.dropped))
        try:
            body = planner.body(t, snake(t.name), [t.key], top=True)
        except Unsupported as e:
            planner.keys, planner.lists, planner.presence, planner.dropped = saved
            skipped.append((t.name, str(e)))
            continue
        if first_key(body) is None:
            planner.keys, planner.lists, planner.presence, planner.dropped = saved
            skipped.append((t.name, "no field the pack can carry"))
            continue
        ident = int(t.encoding[1][2:])
        if target == NS0:
            whens = [("when", n, v) for n, v in compact_nodeid(0, ident)]
        else:
            if ident > 0xFFFF:
                skipped.append((t.name, "encoding id above 65535: not the four-byte NodeId form"))
                continue
            whens = [("when", 16, ident)]
        whens.append(("when", 8, 1))
        kinds.append((t, snake(t.name), whens, [("length", body)]))
    if not kinds:
        raise GenError("no structured DataType of %s can be built" % target)
    names = [k[1] for k in kinds]
    if len(set(names)) != len(names):
        raise GenError("two kinds have the same name")
    return types, models, planner, kinds, skipped, ns_index


def pack_text(args, planner, kinds):
    out = ["# OPC UA structured DataTypes of %s, binary encoding, one ExtensionObject per message." % args.namespace,
           "# Generated by tools/gen/opcua2pack.py; do not edit by hand. The kind is selected by the",
           "# NodeId of the type's Default Binary encoding; what is not mapped: pack.md.",
           "format        %s" % args.format,
           "version       %s" % args.pack_version,
           "distribution  public"]
    out += ["source        %s" % json.dumps(s) for s in args.source]
    out += ["uses          %s" % args.module, "wire          bits", "layout        sequential",
            "bit_order     lsb", ""]
    if args.namespace != NS0:
        out += ["# a NodeId in the four-byte form; the namespace index is the server's for this namespace",
                "when  8  1",
                "field  %s.namespace_index  8  uint" % args.module, ""]
    for t, name, whens, lines in kinds:
        out.append("kind  %s" % name)
        emit(whens, 0, out)
        out.append("requires  %s" % first_key(lines[0][1]))
        emit(lines, 0, out)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def module_text(args, planner):
    out = ["# Raw keys of the OPC UA structured DataTypes of %s." % args.namespace,
           "# Generated by tools/gen/opcua2pack.py; do not edit by hand.",
           "module        %s" % args.module,
           "version       %s" % args.module_version,
           "distribution  public"]
    out += ["source        %s" % json.dumps(s) for s in args.source]
    out.append("")
    if args.namespace != NS0:
        out.append('key   namespace_index  int  -  "the namespace index the message gives this namespace"')
    for name in sorted(planner.keys):
        typ, meaning = planner.keys[name]
        out.append("key   %s  %s  -  %s" % (name, typ, json.dumps(meaning)))
    for name in sorted(planner.lists):
        out.append("list  %s  %s" % (name, json.dumps(planner.lists[name])))
    return "\n".join(out) + "\n"


def vectors(args, types, planner, kinds, pack, ns_index):
    files = []
    mo = ModelOf(types, args.module, args.time_ms)
    for n, (t, name, whens, lines) in enumerate(kinds, 1):
        first = None
        for mode in (0, 1):
            s = Sampler(types, mode)
            s.dropped = {d[0] for d in planner.dropped}
            v = s.struct(t, 0, [t.key])
            body = ua_encode(types, t.key, v)
            if mode == 1 and body == first:
                continue
            first = body
            ident = int(t.encoding[1][2:])
            head = b"".join(x.to_bytes(bits // 8, "little") for bits, x in compact_nodeid(ns_index, ident))
            data = head + b"\x01" + struct.pack("<i", len(body)) + body
            ent = {"keys": {}, "lists": {}, "kind": name}
            if args.namespace != NS0:
                ent["keys"][args.module + ".namespace_index"] = ns_index
            mo.struct(ent, t, snake(t.name), v, top=True)
            got = decode(pack, data)
            if got.get("kind") != name or not same_ent(got, ent):
                a, b = model_strings(got), model_strings(ent)
                diff = sorted(set(a.items()) ^ set(b.items()))[:6]
                raise GenError("vector of kind %s: the pack decodes the encoder's bytes to another model: %s"
                               % (name, diff))
            back = encode(pack, got)
            if back != data:
                raise GenError("vector of kind %s: the pack does not encode the model back to the same bytes" % name)
            model = {"@kind": name}
            model.update(model_strings(ent))
            vec = {"name": "gen-%s-%s-%s" % (args.format, name, "full" if mode == 0 else "sparse"),
                   "from": args.format, "to": args.format,
                   "source": "tools/gen/opcua2pack.py: values made by the generator, bytes by its OPC UA binary encoder",
                   "input": data.hex(), "expect": data.hex(), "model": model}
            files.append(("gen-%03d-%s-%s.json" % (n, name, "full" if mode == 0 else "sparse"),
                          json.dumps(vec, indent=2) + "\n"))
    return files


def pack_md(args, models, planner, kinds, skipped, nvec):
    ver = models[args.namespace]
    out = ["# %s" % args.format, "",
           "Generated by `tools/gen/opcua2pack.py`; do not edit by hand. The structured DataTypes of the",
           "OPC UA namespace `%s` (model version %s, published %s, file `%s`) in the OPC UA binary"
           % (args.namespace, ver[0], ver[1], ver[2]),
           "encoding: %d kinds, one per structured DataType that has a Default Binary encoding and whose"
           % len(kinds),
           "fields the pack language can state. Every field is a raw key of module `%s` unless the notes"
           % args.module, "below bind it.", "",
           "## The message", "",
           "One ExtensionObject in the binary encoding, as a Variant or an ExtensionObject field carries it:",
           "the TypeId (the NodeId of the DataType's Default Binary encoding object, in the smallest NodeId",
           "form that holds it), the encoding byte 1 (a binary body), the Int32 length of the body, and the",
           "body. The TypeId selects the kind; a TypeId in a larger NodeId form than the smallest does not",
           "select a kind. A structure without that header (a field of a DataSet message, an element of a",
           "typed array) is not a message of this pack: it has no type identifier, so nothing in the bytes",
           "names its kind, and the language has no way for a caller to name one in a pack of several kinds.",
           ""] + ([] if args.namespace == NS0 else [
           "A namespace other than 0 has no fixed index: the server's namespace table gives it one. The",
           "four-byte NodeId form is required, and the index the message holds is the key",
           "`%s.namespace_index`; an entity without it encodes index 0." % args.module, ""]) + [
           "## Layout", "",
           "Little-endian, as `bit_order lsb` reads a byte-aligned field. String, ByteString and XmlElement",
           "are lists of bytes counted by their Int32 length (a list of byte values, not text: the `bits`",
           "wire has no text of a stated length). Arrays are lists counted by their Int32 length. Optional",
           "fields are `if` blocks under the 32-bit EncodingMask read as `presence`; a union is its 32-bit",
           "SwitchField and a `switch` on it; NodeId and ExpandedNodeId are their encoding byte and a",
           "`switch` on it; LocalizedText is its mask read as `presence`. DateTime is a raw 64-bit integer",
           "of 100 ns ticks since 1601-01-01 UTC unless the notes bind it.", "",
           "## Not mapped", "",
           "- A null String, ByteString, XmlElement or array (length -1): `count` and `length` read their",
           "  field as unsigned, so -1 is a count larger than the message and the decode is",
           "  `malformed-wire`. An empty one (length 0) is carried. Missing: a signed count or length whose",
           "  value -1 means absent.",
           "- An optional field or LocalizedText part that is present and empty (length 0): its presence bit",
           "  is not set on encode (engine-spec 0.8, ruling 5), so it comes back absent.",
           "- Text: the bytes of a String are carried, not the text. Missing: a transform that reads a",
           "  length-prefixed UTF-8 string.", ""]
    if skipped:
        out += ["### DataTypes not built (%d)" % len(skipped), "", "| DataType | Reason |", "|---|---|"]
        out += ["| %s | %s |" % (n, r) for n, r in skipped]
        out.append("")
    if planner.dropped:
        out += ["### Optional fields and union members not carried (%d)" % len(set(planner.dropped)), "",
                "A message that holds one is `malformed-wire` (an optional field: a presence bit no `if` names)",
                "or `no-kind` (a union member: no `case`).", "", "| Field | Reason |", "|---|---|"]
        out += ["| %s | %s |" % (n, r) for n, r in sorted(set(planner.dropped))]
        out.append("")
    out += ["## Kinds", "", "| Kind | DataType | Default Binary encoding |", "|---|---|---|"]
    out += ["| `%s` | %s | %s |" % (name, t.name, t.encoding[1]) for t, name, _, _ in kinds]
    out += ["", "## Generated vectors", "",
            "`vectors/gen-<n>-<kind>-full.json`: every optional field present, the first union member,",
            "arrays of two items (one inside an item); `-sparse.json`, where it differs: optional fields",
            "absent, the last union member, empty arrays. %d vectors. The bytes come from the generator's"
            % nvec, "OPC UA binary encoder; the generator's reader of this pack.def decodes them to the expected",
            "model and encodes the model back to the same bytes.", ""]
    if args.notes_file:
        with open(args.notes_file, encoding="utf-8") as fh:
            out += [fh.read().rstrip("\n"), ""]
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(prog="opcua2pack", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    genio.add_arguments(p)
    p.add_argument("--nodeset", nargs="+", required=True, help="NodeSet2 XML files")
    p.add_argument("--namespace", required=True, help="model URI of the namespace to build")
    p.add_argument("--format", required=True)
    p.add_argument("--module", required=True)
    p.add_argument("--source", action="append", required=True)
    p.add_argument("--time-ms", action="append", default=[], metavar="FIELD",
                   help="a DateTime field of this name at the top of a kind binds core time_ms")
    p.add_argument("--notes-file")
    p.add_argument("--pack-version", default="0.1.0")
    p.add_argument("--module-version", default="0.1.0")
    args = p.parse_args(argv)
    try:
        types, models, planner, kinds, skipped, ns_index = build(args)
        ptext = pack_text(args, planner, kinds)
        mtext = module_text(args, planner)
        model = gtcheck.Model()
        with open(os.path.join(args.out, "model", "core.def"), encoding="utf-8") as fh:
            model.add(fh.read(), "model/core.def")
        model.add(mtext, "model/%s.def" % args.module)
        gtcheck.load_pack(ptext, model, label="packs/%s/pack.def" % args.format)
        pack = parse_pack(ptext)
        vecs = vectors(args, types, planner, kinds, pack, ns_index)
    except (GenError, gtcheck.CheckError) as e:
        print("opcua2pack: %s" % e, file=sys.stderr)
        return 1
    out = genio.Output(args.out, check=args.check)
    out.write("model/%s.def" % args.module, mtext)
    base = "packs/%s/" % args.format
    out.write(base + "pack.def", ptext)
    out.write(base + "pack.md", pack_md(args, models, planner, kinds, skipped, len(vecs)))
    have = [n for n in out.listdir(base + "vectors") if n.startswith("gen-")]
    names = {n for n, _ in vecs}
    for n in have:
        if n not in names:
            out.remove(base + "vectors/" + n)
    for n, text in vecs:
        out.write(base + "vectors/" + n, text)
    print(json.dumps({"format": args.format, "kinds": len(kinds), "not_built": len(skipped),
                      "dropped": len(set(planner.dropped)), "keys": len(planner.keys), "lists": len(planner.lists),
                      "vectors": len(vecs)}))
    return out.report("opcua2pack")


if __name__ == "__main__":
    sys.exit(main())
