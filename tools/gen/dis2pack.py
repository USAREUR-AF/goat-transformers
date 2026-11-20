#!/usr/bin/env python3
"""Generate the goat-transformers pack of the Distributed Interactive
Simulation protocol, version 7 (DIS 7), from the open-dis PDU descriptions.

Reads   <xmlpg>/DIS2012.xml and <xmlpg>/LICENSE.md of github.com/open-dis/xmlpg
        (the PDU and record layouts);
        <opendis>/opendis/dis7.py, <opendis>/opendis/PduFactory.py and
        <opendis>/LICENSE of github.com/open-dis/open-dis-python (the PDU type
        number of each PDU class), read as Python syntax trees: no file of the
        source is run;
        tools/gen/sources/dis-PROVENANCE.md (the commits and the SHA-256 of every
        file; a file that differs is refused)
Writes  <out>/model/dis7.def                   the module of the DIS 7 keys and lists
        <out>/packs/dis7/pack.def              one pack, one kind per PDU type
        <out>/packs/dis7/pack.md
        <out>/packs/dis7/PROVENANCE.md
        <out>/packs/dis7/vectors/*.json
        tools/gen/sources/dis-PROVENANCE.md   (only with --commit-xmlpg and --commit-opendis)

The message is one PDU, big-endian (network byte order), from the 12-byte PDU
header on. A kind is selected by the protocol version (7, common to the pack),
the PDU type and, for a PDU of fixed length, the PDU length.

Every vector's PDU is written by a serializer in this file from the XML layout;
the generator then loads the pack with gtcheck and decodes and encodes every
vector with its own codec of the bits wire.

Python 3 standard library only. Exit status 0 when every check passed, 1 for a
refused input or a failed check, 2 for a usage error.
"""
import argparse
import ast
import collections
import hashlib
import json
import math
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

NAME = "dis2pack"
VERSION = "0.1.0"
XMLPG = "https://github.com/open-dis/xmlpg"
OPENDIS = "https://github.com/open-dis/open-dis-python"
PROV = "tools/gen/sources/dis-PROVENANCE.md"
XML_FILE = "DIS2012.xml"
XMLPG_FILES = ["LICENSE.md", XML_FILE]
OPENDIS_FILES = ["LICENSE", "opendis/dis7.py", "opendis/PduFactory.py"]
FORMAT = MODULE = "dis7"
PROTOCOL_VERSION = 7
HEADER_BITS = 96
MAX_REQUIRES = 3
GROUP_SAMPLE_ITEMS = 2

PRIMITIVES = {            # XML primitive type: (kind, bytes)
    "unsigned byte": ("u", 1), "byte": ("s", 1),
    "unsigned short": ("u", 2), "short": ("s", 2),
    "unsigned int": ("u", 4), "int": ("s", 4),
    "unsigned long": ("u", 8), "long": ("s", 8),
    "float": ("f32", 4), "double": ("f64", 8),
}

# The PDU header (class PduSuperclass and Pdu of the XML): the fields every kind
# shares, as the common lines. protocolVersion and pduType are `when` values,
# pduLength a `when` of a fixed-length kind and a field of a kind with a group.
HEADER = {"protocolVersion": 0, "exerciseID": 8, "pduType": 16, "protocolFamily": 24,
          "timestamp": 32, "length": 64, "pduStatus": 80, "padding": 88}


class GenError(Exception):
    pass


class CodecError(Exception):
    pass


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def snake(name):
    name = re.sub(r"IDs(?=[A-Z_]|$)", "Ids", name)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s if s and not s[0].isdigit() else "x" + s


# ----------------------------------------------------------------- sources ---

class Source:
    """The XML classes, and the PDU type of each PDU class from open-dis-python."""

    def __init__(self, xmlpg, opendis):
        text = read_text(os.path.join(xmlpg, XML_FILE))
        if "<!DOCTYPE" in text or "<!ENTITY" in text:
            raise GenError("%s declares a DOCTYPE or an entity; it is refused" % XML_FILE)
        root = ET.fromstring(text)
        self.classes = collections.OrderedDict()
        for c in root.iter("class"):
            self.classes[c.get("name")] = c
        self.types = self.read_types(read_text(os.path.join(opendis, "opendis/dis7.py")))
        self.factory = self.read_factory(read_text(os.path.join(opendis, "opendis/PduFactory.py")))

    @staticmethod
    def read_types(text):
        """{class name: PDU type} from the `pduType: enum8 = N` class annotations."""
        out = {}
        for c in ast.parse(text, "dis7.py").body:
            if isinstance(c, ast.ClassDef):
                for st in c.body:
                    if (isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
                            and st.target.id == "pduType" and isinstance(st.value, ast.Constant)
                            and isinstance(st.value.value, int)):
                        out[c.name] = st.value.value
        if not out:
            raise GenError("dis7.py states no pduType")
        return out

    @staticmethod
    def read_factory(text):
        """{PDU type: class name} of the PduTypeDecoders table, used only to
        choose between two classes that state the same type."""
        for st in ast.parse(text, "PduFactory.py").body:
            if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", "") == "PduTypeDecoders":
                return {k.value: v.id for k, v in zip(st.value.keys, st.value.values)
                        if isinstance(k, ast.Constant) and isinstance(v, ast.Name)}
        raise GenError("PduFactory.py has no PduTypeDecoders table")

    def chain(self, name):
        out, seen = [], set()
        while name and name != "root":
            if name not in self.classes or name in seen:
                raise GenError("class %s: unknown or circular parent" % name)
            seen.add(name)
            out.append(name)
            name = self.classes[name].get("inheritsFrom")
        return out[::-1]

    def attributes(self, name):
        for cname in self.chain(name):
            for a in self.classes[cname].findall("attribute"):
                kids = [k for k in a if isinstance(k.tag, str)]
                if len(kids) != 1:
                    raise GenError("%s.%s: an attribute with %d type elements" % (cname, a.get("name"), len(kids)))
                yield cname, a.get("name"), kids[0]


# ------------------------------------------------------------------- plan ---

Leaf = collections.namedtuple("Leaf", "path kind bitpos bits")
Var = collections.namedtuple("Var", "path count elem bitpos where")


def primitive(el, where):
    t = (el.get("type") or "").strip()
    if t not in PRIMITIVES:
        raise GenError("%s: primitive type %r" % (where, t))
    return PRIMITIVES[t]


def flatten_entries(src, name):
    """All entries of a class, continuing past a Var with an unknown position
    (later entries get bitpos None)."""
    out = []
    pos = [0]

    def walk(cls, prefix, depth=0):
        if depth > 16:
            raise GenError("%s: records nested too deep" % cls)
        for cname, aname, el in src.attributes(cls):
            where = "%s.%s" % (cname, aname)
            tag = el.tag.lower()
            path = prefix + [aname]
            if tag == "list" and el.get("type") == "variable":
                items = [k for k in el if isinstance(k.tag, str)]
                out.append(Var(path, el.get("countFieldName"), items[0] if len(items) == 1 else None,
                               pos[0], where))
                pos[0] = None
            elif tag == "classref":
                walk(el.get("name"), path, depth + 1)
            else:
                tmp = []
                start = pos[0] if pos[0] is not None else 0
                end = flatten_one(src, el, path, start, tmp, where)
                for leaf in tmp:
                    out.append(leaf if pos[0] is not None else leaf._replace(bitpos=None))
                if pos[0] is not None:
                    pos[0] = end
    walk(name, [])
    return out, pos[0]


def flatten_one(src, el, path, bitpos, out, where):
    tag = el.tag.lower()
    if tag == "primitive":
        kind, n = primitive(el, where)
        out.append(Leaf(path, kind, bitpos, 8 * n))
        return bitpos + 8 * n
    if tag == "list" and el.get("type") == "fixed":
        n = int(el.get("length"))
        items = [k for k in el if isinstance(k.tag, str)]
        if len(items) != 1:
            raise GenError("%s: a list with %d element types" % (where, len(items)))
        item = items[0]
        if item.tag.lower() == "primitive":
            kind, size = primitive(item, where)
            if el.get("couldBeString") == "true" and size == 1 and n <= 255:
                out.append(Leaf(path, "ascii", bitpos, 8 * n))
                return bitpos + 8 * n
            for i in range(1, n + 1):
                out.append(Leaf(path + ["%02d" % i], kind, bitpos, 8 * size))
                bitpos += 8 * size
            return bitpos
        for i in range(1, n + 1):
            entries, end = flatten_entries_at(src, item.get("name"), path + ["%02d" % i], bitpos)
            if any(isinstance(e, Var) for e in entries):
                raise GenError("%s: a counted list inside a fixed list" % where)
            out.extend(entries)
            bitpos = end
        return bitpos
    raise GenError("%s: element %s" % (where, el.tag))


def flatten_entries_at(src, name, prefix, bitpos):
    entries, end = flatten_entries(src, name)
    moved = []
    for e in entries:
        moved.append(e._replace(path=prefix + e.path, bitpos=None if e.bitpos is None else e.bitpos + bitpos))
    return moved, (None if end is None else end + bitpos)


Line = collections.namedtuple("Line", "key pos bits tr leaf")


class Group:
    def __init__(self, key, start, item_bits, count_leaf, lines, elem_desc):
        self.key, self.start, self.item_bits = key, start, item_bits
        self.count_leaf, self.lines, self.elem_desc = count_leaf, lines, elem_desc


class KindPlan:
    def __init__(self, name, cls, pdu_type, size, lines, group):
        self.name, self.cls, self.type, self.size = name, cls, pdu_type, size
        self.lines, self.group, self.requires = lines, group, []


TRANSFORM = {"u": ("uint", "int"), "s": ("twos", "int"), "f32": ("f32", "float"),
             "f64": ("f64", "float"), "ascii": ("ascii", "string")}


class Plan:
    def __init__(self, src, exclude=None):
        exclude = exclude or {}
        self.kinds, self.keys, self.lists = [], collections.OrderedDict(), collections.OrderedDict()
        self.not_built = []        # (class, type, reason)
        self.unnumbered = []       # PDU classes the type source does not number
        self.common = []           # header lines
        pdus = [n for n in src.classes if n != "Pdu" and "Pdu" in src.chain(n)]
        by_type = collections.defaultdict(list)
        for n in pdus:
            if n in src.types:
                by_type[src.types[n]].append(n)
            elif not any(c.get("name") != n and src.classes[c.get("name")].get("inheritsFrom") == n
                         for c in src.classes.values()):
                self.unnumbered.append(n)
        for t in sorted(by_type):
            names = by_type[t]
            chosen = [n for n in names if src.factory.get(t) == n] or names[:1]
            for n in names:
                if n != chosen[0]:
                    self.not_built.append((n, t, "the type source gives type %d to %s as well; its factory "
                                                 "decodes that type as %s" % (t, chosen[0], chosen[0])))
            if chosen[0] in exclude:
                self.not_built.append((chosen[0], t, exclude[chosen[0]]))
                continue
            self.plan_pdu(src, chosen[0], t)
        self.header_lines()
        own = MODULE + "."
        usage = collections.Counter(l.key for k in self.kinds for l in k.lines if l.key.startswith(own))
        for k in self.kinds:
            raw = [l.key for l in k.lines if l.key.startswith(own) and l.key != own + "pdu_length"]
            ranked = sorted(range(len(raw)), key=lambda i: (usage[raw[i]], i))
            k.requires = [raw[i] for i in sorted(ranked[:MAX_REQUIRES])]

    def declare(self, name, typ, what):
        if name in self.keys or name in self.lists:
            if self.keys.get(name, (None,))[0] == typ:
                return
            raise GenError("key %s declared twice" % name)
        self.keys[name] = (typ, what)

    def header_lines(self):
        for field, pos in HEADER.items():
            if field in ("protocolVersion", "pduType", "length"):
                continue
            bits = 32 if field == "timestamp" else 8
            name = "header_" + snake(field)
            self.declare(name, "int", "PDU header field %s" % field)
            self.common.append(Line(MODULE + "." + name, pos, bits, "uint", None))

    def plan_pdu(self, src, cls, ptype):
        entries, end = flatten_entries(src, cls)
        header = [e for e in entries if isinstance(e, Leaf) and e.bitpos is not None and e.bitpos < HEADER_BITS]
        if [(e.path[-1], e.bitpos) for e in header] != [(f, p) for f, p in HEADER.items()]:
            self.not_built.append((cls, ptype, "its header differs from the 12-byte PDU header"))
            return
        body = [e for e in entries if e.bitpos is None or e.bitpos >= HEADER_BITS]
        kname = snake(re.sub(r"Pdu$", "", cls))
        vars_ = [e for e in body if isinstance(e, Var)]
        group = None
        if len(vars_) > 1:
            self.not_built.append((cls, ptype, "%d counted lists (%s); a counted list that is not the last "
                                   "part has no fixed place for what follows it"
                                   % (len(vars_), ", ".join("`%s`" % "_".join(v.path) for v in vars_))))
            return
        if vars_:
            v = vars_[0]
            if body[-1] is not v:
                self.not_built.append((cls, ptype, "a counted list (`%s`) that is not the last part of the PDU"
                                       % "_".join(v.path)))
                return
            group = self.plan_group(src, cls, kname, v, body)
            if isinstance(group, str):
                self.not_built.append((cls, ptype, group))
                return
        leaves = [e for e in body if isinstance(e, Leaf) and not (group and e is group.count_leaf)]
        lines, seen = [], set()
        for leaf in leaves:
            key = self.leaf_key(kname, leaf, seen, cls)
            lines.append(Line(MODULE + "." + key, leaf.bitpos, leaf.bits, TRANSFORM[leaf.kind][0], leaf))
        if group:
            self.declare("pdu_length", "int", "PDU header field length, in bytes, of a PDU with a counted list")
            lines.insert(0, Line(MODULE + ".pdu_length", HEADER["length"], 16, "uint", None))
        if not any(l.leaf for l in lines) and not group:
            self.not_built.append((cls, ptype, "no field after the PDU header"))
            return
        size = None if group else end // 8
        self.kinds.append(KindPlan(kname, cls, ptype, size, lines, group))

    def leaf_key(self, kname, leaf, seen, cls):
        base = "%s_%s" % (kname, "_".join(p if p.isdigit() else snake(p) for p in leaf.path))
        name, n = base, 2
        while name in seen:
            name, n = "%s_%d" % (base, n), n + 1
        seen.add(name)
        self.declare(name, TRANSFORM[leaf.kind][1], "%s %s" % (cls, ".".join(leaf.path)))
        return name

    def plan_group(self, src, cls, kname, v, body):
        count = [e for e in body if isinstance(e, Leaf) and e.path[-1] == v.count and e.bitpos is not None]
        if len(count) != 1:
            return "a counted list (`%s`) whose count field `%s` is not one field before it" % (
                "_".join(v.path), v.count)
        count = count[0]
        if count.kind != "u":
            return "a counted list whose count field is not unsigned"
        elem = v.elem
        if elem is None:
            return "a counted list with no single element type"
        lname = "%s_%s" % (kname, "_".join(snake(p) for p in v.path))
        items, seen = [], set()
        if elem.tag.lower() == "primitive":
            kind, n = primitive(elem, v.where)
            items.append(Leaf(["value"], kind, 0, 8 * n))
            bits = 8 * n
            desc = "one %s" % elem.get("type").strip()
        else:
            entries, bits = flatten_entries(src, elem.get("name"))
            if any(isinstance(e, Var) for e in entries) or bits is None:
                return "a counted list of %s records, which hold a counted list themselves" % elem.get("name")
            items = entries
            desc = "one %s record" % elem.get("name")
        if lname in self.keys:
            raise GenError("list %s collides with a key" % lname)
        self.lists[lname] = "%s %s: the items of the counted list, %s each" % (cls, ".".join(v.path), desc)
        lines = []
        for leaf in items:
            key = "%s_%s" % (lname, "_".join(p if p.isdigit() else snake(p) for p in leaf.path))
            if key in seen:
                raise GenError("%s: item key %s twice" % (cls, key))
            seen.add(key)
            self.declare(key, TRANSFORM[leaf.kind][1], "%s %s[] %s" % (cls, ".".join(v.path), ".".join(leaf.path)))
            lines.append(Line(MODULE + "." + key, leaf.bitpos, leaf.bits, TRANSFORM[leaf.kind][0], leaf))
        return Group(MODULE + "." + lname, v.bitpos, bits, count, lines, desc)


# ------------------------------------------------------------------- emit ---

def loc(pos, n):
    return "0:%d:%d" % (pos, n)


def source_line(prov):
    return 'source        "%s %s at %s (commit %s); PDU types from %s opendis/dis7.py at %s (commit %s)"' % (
        XMLPG, XML_FILE, prov["xmlpg_ref"], prov["xmlpg"], OPENDIS, prov["opendis_ref"], prov["opendis"])


def pack_text(plan, prov):
    o = ["# DIS 7 (IEEE 1278.1-2012) PDUs, one kind per PDU type.",
         "# Generated by tools/gen/dis2pack.py; do not edit by hand.",
         "# The message is one PDU, big-endian, from the 12-byte PDU header on.",
         "format        %s" % FORMAT,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(prov),
         "uses          %s" % MODULE,
         "wire          bits",
         "bit_order     msb",
         "word_bytes    1",
         "when   %s %d" % (loc(HEADER["protocolVersion"], 8), PROTOCOL_VERSION)]
    for l in plan.common:
        o.append("field  %s %s %s" % (l.key, loc(l.pos, l.bits), l.tr))
    for k in plan.kinds:
        o.append("")
        o.append("kind      %s" % k.name)
        o.append("when      %s %d" % (loc(HEADER["pduType"], 8), k.type))
        if k.size is not None:
            o.append("when      %s %d" % (loc(HEADER["length"], 16), k.size))
        if k.requires:
            o.append("requires  %s" % " ".join(k.requires))
        for l in k.lines:
            o.append("field     %s %s %s" % (l.key, loc(l.pos, l.bits), l.tr))
        g = k.group
        if g:
            o.append("group     %s 0:%d item %d count %s" % (g.key, g.start, g.item_bits,
                                                             loc(g.count_leaf.bitpos, g.count_leaf.bits)))
            for l in g.lines:
                o.append("  field   %s %s %s" % (l.key, loc(l.pos, l.bits), l.tr))
            o.append("end")
    return "\n".join(o) + "\n"


def module_text(plan, prov):
    o = ["# The dis7 module: the PDU fields of DIS 7, as the open-dis PDU descriptions lay",
         "# them out. Generated by tools/gen/dis2pack.py; do not edit by hand. A key is",
         "# <pdu>_<field path> in lower case with underscores; a list holds the items of a",
         "# counted list. Units are those of DIS: the module states none.",
         "module        %s" % MODULE,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(prov)]
    for name, (typ, what) in plan.keys.items():
        o.append('key   %s  %s  -  "%s"' % (name, typ, what))
    for name, what in plan.lists.items():
        o.append('list  %s  "%s"' % (name, what))
    return "\n".join(o) + "\n"


# -------------------------------------------------- serializer (vectors) ---

def raw_of(leaf, value):
    if leaf.kind in ("u", "s"):
        return value & ((1 << leaf.bits) - 1)
    if leaf.kind == "f32":
        return int.from_bytes(struct.pack(">f", value), "big")
    if leaf.kind == "f64":
        return int.from_bytes(struct.pack(">d", value), "big")
    return int.from_bytes(value.encode("ascii").ljust(leaf.bits // 8, b"\0"), "big")


def put(acc, total_bits, pos, bits, raw):
    return acc | (raw << (total_bits - pos - bits))


def sample(leaf, salt):
    if leaf.kind == "ascii":
        return ("M%d" % (salt % 97))[:leaf.bits // 8]
    if leaf.kind in ("f32", "f64"):
        return ((salt % 41) - 20) * 0.25
    n = leaf.bits
    span = 1 << min(n, 31)
    v = (salt * 2654435761 + 12345) % span
    if leaf.kind == "s":
        v -= span // 2
    elif n == 64 and salt % 2:
        v |= 1 << 63
    return v


def pdu_bytes(plan, k, values, items):
    """The PDU of kind `k`: header values from `values` (by header field name),
    body values by leaf path, items a list of {leaf path: value} for the group."""
    size = k.size if k.size is not None else (k.group.start + len(items) * k.group.item_bits) // 8
    total = 8 * size
    acc = 0
    acc = put(acc, total, HEADER["protocolVersion"], 8, PROTOCOL_VERSION)
    acc = put(acc, total, HEADER["pduType"], 8, k.type)
    acc = put(acc, total, HEADER["length"], 16, size)
    for l in plan.common:
        acc = put(acc, total, l.pos, l.bits, values[l.key] & ((1 << l.bits) - 1))
    for l in k.lines:
        if l.leaf is not None:
            acc = put(acc, total, l.pos, l.bits, raw_of(l.leaf, values[tuple(l.leaf.path)]))
    if k.group:
        g = k.group
        acc = put(acc, total, g.count_leaf.bitpos, g.count_leaf.bits, len(items))
        for i, item in enumerate(items):
            base = g.start + i * g.item_bits
            for l in g.lines:
                acc = put(acc, total, base + l.pos, l.bits, raw_of(l.leaf, item[tuple(l.leaf.path)]))
    return acc.to_bytes(size, "big")


def vector_text(pairs):
    return json.dumps(collections.OrderedDict(pairs), indent=2) + "\n"


def vector_files(plan):
    files = []
    for i, k in enumerate(plan.kinds):
        salt = k.type * 31 + 3
        values = {l.key: sample(Leaf([], "u", 0, l.bits), salt + j) for j, l in enumerate(plan.common)}
        for j, l in enumerate(k.lines):
            if l.leaf is not None:
                values[tuple(l.leaf.path)] = sample(l.leaf, salt + 7 * j + 11)
        items = []
        if k.group:
            for n in range(GROUP_SAMPLE_ITEMS):
                items.append({tuple(l.leaf.path): sample(l.leaf, salt + 101 * (n + 1) + 5 * j)
                              for j, l in enumerate(k.group.lines)})
        data = pdu_bytes(plan, k, values, items).hex()
        model = collections.OrderedDict([("@kind", k.name)])
        if k.group:
            model[k.group.key + ".#"] = str(len(items))
        files.append(("rt-%02d-%s.json" % (k.type, k.name), vector_text([
            ("name", "%s-roundtrip-%s" % (FORMAT, k.name)), ("from", FORMAT), ("to", FORMAT),
            ("input", data), ("expect", data), ("model", model)])))
        if k.group:
            data = pdu_bytes(plan, k, values, []).hex()
            files.append(("rt-%02d-%s-no-items.json" % (k.type, k.name), vector_text([
                ("name", "%s-roundtrip-%s-no-items" % (FORMAT, k.name)), ("from", FORMAT), ("to", FORMAT),
                ("input", data), ("expect", data),
                ("model", collections.OrderedDict([("@kind", k.name), (k.group.key + ".#", "0")]))])))
    return files


# -------------------------------------------- codec, from the specification ---

def get_bits(data, pos, n):
    total = 8 * len(data)
    return (int.from_bytes(data, "big") >> (total - pos - n)) & ((1 << n) - 1)


def decode_value(node, raw):
    tr, n = node.tr, node.bits
    if tr == "uint":
        return raw - (1 << 64) if n == 64 and raw >> 63 else raw
    if tr == "twos":
        return raw - (1 << n) if raw >> (n - 1) else raw
    if tr in ("f32", "f64"):
        v = struct.unpack(">f" if tr == "f32" else ">d", raw.to_bytes(n // 8, "big"))[0]
        if not math.isfinite(v):
            raise CodecError("transform-decode")
        return v
    if tr == "ascii":
        text = raw.to_bytes(n // 8, "big").rstrip(b"\0")
        if any(b < 0x20 or b > 0x7E for b in text):
            raise CodecError("transform-decode")
        return text.decode("ascii")
    raise CodecError("transform-decode")


def encode_value(node, x):
    tr, n = node.tr, node.bits
    if tr in ("uint", "twos"):
        return x & ((1 << n) - 1)
    if tr in ("f32", "f64"):
        return int.from_bytes(struct.pack(">f" if tr == "f32" else ">d", x), "big")
    if tr == "ascii":
        b = x.encode("ascii")
        if len(b) > n // 8:
            raise CodecError("transform-encode")
        return int.from_bytes(b.ljust(n // 8, b"\0"), "big")
    raise CodecError("transform-encode")


def holds(lines, data):
    return all(n.start + n.bits <= 8 * len(data) and get_bits(data, n.start, n.bits) == int(n.value)
               for n in lines if n.d == "when")


def decode(pack, data):
    kind = next((k for k in pack.kinds if holds(k.lines, data)), None) if holds(pack.common, data) else None
    if kind is None:
        raise CodecError("no-kind")
    lines = pack.common + kind.lines
    fixed = [n for n in lines if n.d in ("when", "field")]
    if 8 * len(data) < max(n.start + n.bits for n in fixed):
        raise CodecError("malformed-wire")
    ent, lists = collections.OrderedDict(), {}
    for n in lines:
        if n.d == "field":
            ent[n.key] = decode_value(n, get_bits(data, n.start, n.bits))
        elif n.d == "group":
            count = get_bits(data, n.count[0], n.count[1])
            if 8 * len(data) < n.start + count * n.item:
                raise CodecError("malformed-wire")
            items = []
            for i in range(count):
                base = n.start + i * n.item
                items.append(collections.OrderedDict(
                    (f.key, decode_value(f, get_bits(data, base + f.start, f.bits))) for f in n.body if f.d == "field"))
            lists[n.key] = items
    return kind.name, ent, lists


def encode(pack, name, ent, lists):
    kind = next(k for k in pack.kinds if k.name == name)
    lines = pack.common + kind.lines
    end = max(n.start + n.bits for n in lines if n.d in ("when", "field"))
    for n in lines:
        if n.d == "group":
            end = max(end, n.start + len(lists.get(n.key, [])) * n.item)
    total = (end + 7) // 8 * 8
    acc = 0
    for n in lines:
        if n.d == "field" and n.key in ent:
            acc = put(acc, total, n.start, n.bits, encode_value(n, ent[n.key]))
    for n in lines:
        if n.d == "group" and n.key in lists:
            items = lists[n.key]
            acc &= ~(((1 << n.count[1]) - 1) << (total - n.count[0] - n.count[1]))
            acc = put(acc, total, n.count[0], n.count[1], len(items))
            for i, item in enumerate(items):
                base = n.start + i * n.item
                for f in n.body:
                    if f.d == "field" and f.key in item:
                        acc = put(acc, total, base + f.start, f.bits, encode_value(f, item[f.key]))
    for n in lines:
        if n.d == "when":
            acc &= ~(((1 << n.bits) - 1) << (total - n.start - n.bits))
            acc = put(acc, total, n.start, n.bits, int(n.value))
    return acc.to_bytes(total // 8, "big")


def check_vectors(pack, vectors):
    n, seen = 0, set()
    for fn, text in vectors:
        vec = json.loads(text)
        try:
            kname, ent, lists = decode(pack, bytes.fromhex(vec["input"]))
            for key, want in vec.get("model", {}).items():
                if key == "@kind":
                    got = kname
                elif key.endswith(".#"):
                    got = str(len(lists[key[:-2]])) if key[:-2] in lists else "absent"
                else:
                    got = ent.get(key)
                if str(got) != want:
                    raise GenError("%s: model %s = %s, vector says %s" % (fn, key, got, want))
            got = encode(pack, kname, ent, lists).hex()
            seen.add(kname)
        except CodecError as e:
            raise GenError("%s: %s" % (fn, e))
        if got != vec["expect"]:
            raise GenError("%s: convert gives %s, vector expects %s" % (fn, got, vec["expect"]))
        n += 1
    missing = {k.name for k in pack.kinds} - seen
    if missing:
        raise GenError("kinds with no vector: %s" % sorted(missing)[:5])
    return n


# --------------------------------------------------------------- documents ---

def pack_md(plan, prov, nvec):
    o = []
    a = o.append
    a("# Pack: %s" % FORMAT)
    a("")
    a("Distributed Interactive Simulation, version 7 (IEEE 1278.1-2012): one kind per")
    a("PDU type. Layouts from the open-dis PDU descriptions (`%s`, `%s`, commit" % (XMLPG, XML_FILE))
    a("`%s`); the PDU type numbers from open-dis-python (`%s`, `opendis/dis7.py`," % (prov["xmlpg"], OPENDIS))
    a("commit `%s`). Public. Generated by `tools/gen/dis2pack.py`; do not edit" % prov["opendis"])
    a("`pack.def`, this file, `PROVENANCE.md`, `model/%s.def` or the vectors by hand." % MODULE)
    a("")
    a("Status: Built. Generated and checked by the generator's own serializer and codec.")
    a("")
    a("No IEEE document was read: the layouts are those of the open-dis project, a")
    a("BSD-licensed restatement. The xmlpg README says the XML description is no")
    a("longer maintained and that corrections go to the generated libraries; each")
    a("built kind was compared with open-dis-python's own reading of its vector (see")
    a("PROVENANCE.md).")
    a("")
    a("## The message")
    a("")
    a("`wire bits`, `bit_order msb`, `word_bytes 1`; hex text. One PDU from its first")
    a("byte; every number is big-endian (network byte order: open-dis-python reads")
    a("with `>` struct formats). The PDU header is 12 bytes:")
    a("")
    a("| Bytes | Field | In the pack |")
    a("|---|---|---|")
    a("| 0 | protocol version | common `when` = %d |" % PROTOCOL_VERSION)
    a("| 1 | exercise id | `dis7.header_exercise_id` |")
    a("| 2 | PDU type | per-kind `when` |")
    a("| 3 | protocol family | `dis7.header_protocol_family` |")
    a("| 4-7 | timestamp | `dis7.header_timestamp` |")
    a("| 8-9 | PDU length in bytes | per-kind `when` for a fixed length; `dis7.pdu_length` for a kind with a counted list |")
    a("| 10 | PDU status | `dis7.header_pdu_status` |")
    a("| 11 | padding | `dis7.header_padding` |")
    a("")
    a("A kind with a counted list cannot state its length as a `when`, and the pack")
    a("does not compute it: encode writes `dis7.pdu_length` as the entity holds it, so a")
    a("PDU encoded from another format needs the length set by the caller (or a derive")
    a("of the length from the items, which the pack language does not have).")
    a("")
    a("## PDUs")
    a("")
    a("| Kind | PDU class | Type | Length in bytes |")
    a("|---|---|---|---|")
    for k in plan.kinds:
        a("| `%s` | %s | %d | %s |" % (k.name, k.cls, k.type, k.size if k.size is not None else
                                        "%d + %d per item of `%s`" % (k.group.start // 8, k.group.item_bits // 8,
                                                                      k.group.key)))
    a("")
    a("## What is mapped")
    a("")
    a("| Description | Transform | Model type |")
    a("|---|---|---|")
    a("| unsigned byte, short, int, long | `uint` | int |")
    a("| byte, short, int, long | `twos` | int |")
    a("| float, double | `f32`, `f64` (big-endian) | float |")
    a("| a fixed list of bytes marked as text (an entity marking) | `ascii` | string |")
    a("| a record (`classref`) | its fields in place, the path joined by `_` | as the field |")
    a("| a fixed list | one field per element, `_01`, `_02`, … appended | as the element |")
    a("| a counted list that ends the PDU, of fixed-size items | a `group` of `item` bits counted by its count field | a list |")
    a("")
    a("The count field of a counted list is the group's count locator: encode writes")
    a("the number of items there, and the field has no key of its own.")
    a("")
    a("### Core keys")
    a("")
    a("None. The Entity State PDU and the others that place an entity give its")
    a("location as geocentric (ECEF) coordinates in metres and its velocity in the")
    a("same frame: binding `lat`, `lon` and `hae` needs a derive from ECEF to geodetic")
    a("coordinates (WGS84), which the pack language does not have, so they stay raw")
    a("keys (`entity_state_entity_location_x`, …). The entity id is three numbers (site,")
    a("application, entity) with no single-key form in the source, so it stays raw too;")
    a("a derive that joins them would give `uid`. The marking is free text, not stated")
    a("as a call sign. The timestamp counts units of an hour, not epoch time.")
    a("")
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own keys, so an entity from another format" % MAX_REQUIRES)
    a("selects a kind only when it holds them.")
    a("")
    a("## What is not mapped")
    a("")
    if plan.not_built:
        a("PDU types with no kind:")
        a("")
        a("| PDU class | Type | Reason |")
        a("|---|---|---|")
        for cls, t, why in plan.not_built:
            a("| %s | %d | %s |" % (cls, t, why))
        a("")
    if plan.unnumbered:
        a("PDU classes of the XML that the type source gives no PDU type: %s." % ", ".join(plan.unnumbered))
        a("")
    a("- A counted list that is not the last part of its PDU, or a second one: the")
    a("  pack language places a counted `bits` group only at the end of its scope.")
    a("- DIS 6 and earlier: the source describes DIS 7 only.")
    a("- Enumerations and bit fields are carried as integers.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-<type>-<kind>.json`: one same-format round trip per kind, the PDU")
    a("written by a serializer in the generator from sample values; a kind with a")
    a("counted list has one with two items and one with none (`-no-items`). No")
    a("conversion vector: no field binds a core key without the ECEF derive.")
    a("")
    a("%d vectors." % nvec)
    return "\n".join(o) + "\n"


def provenance_md(prov, table):
    rows = ["# Provenance: %s" % FORMAT, "",
            "| Fact | Value |", "|---|---|",
            "| layouts | %s `%s` at %s, commit `%s` (SHA-256 `%s`) |" % (
                XMLPG, XML_FILE, prov["xmlpg_ref"], prov["xmlpg"], table["xmlpg/" + XML_FILE]),
            "| PDU types | %s `opendis/dis7.py` at %s, commit `%s` (SHA-256 `%s`) |" % (
                OPENDIS, prov["opendis_ref"], prov["opendis"], table["opendis/opendis/dis7.py"]),
            "| licenses | BSD 2-Clause, both: `LICENSE.md` of xmlpg (Copyright (c) 2015, mcgredonps) and `LICENSE` of open-dis-python (Copyright (c) 2023, Open DIS), verbatim in `%s` |" % PROV,
            "| date read | 2026-11-19 |",
            "| what the pack takes | PDU and record names, field names, types, list lengths and count fields, PDU type numbers; no comment text |",
            "| no IEEE document | the pack restates the open-dis descriptions; IEEE 1278.1 itself was not read |",
            "| generator | `tools/gen/dis2pack.py` |", ""]
    return "\n".join(rows)


def write_sources_provenance(out, xmlpg, opendis, prov):
    o = ["# Provenance of the DIS inputs", "",
         "| Fact | Value |", "|---|---|",
         "| layouts | %s, %s, commit `%s` |" % (XMLPG, prov["xmlpg_ref"], prov["xmlpg"]),
         "| xmlpg archive | `https://codeload.github.com/open-dis/xmlpg/tar.gz/%s` |" % prov["xmlpg"],
         "| PDU types | %s, %s, commit `%s` |" % (OPENDIS, prov["opendis_ref"], prov["opendis"]),
         "| open-dis-python archive | `https://codeload.github.com/open-dis/open-dis-python/tar.gz/%s` |" % prov["opendis"],
         "",
         "The xmlpg README calls `DIS2012.xml` the original specification file of Open",
         "DIS, no longer maintained, with corrections made in the generated libraries.",
         "The generator takes the layouts from it, the PDU type numbers from the class",
         "annotations of open-dis-python, and reads both as data (an XML tree and a",
         "Python syntax tree); it runs neither. No IEEE document was read.",
         "",
         "## Files", "",
         "| Path | SHA-256 |", "|---|---|"]
    for f in XMLPG_FILES:
        o.append("| `xmlpg/%s` | `%s` |" % (f, sha256(os.path.join(xmlpg, f))))
    for f in OPENDIS_FILES:
        o.append("| `opendis/%s` | `%s` |" % (f, sha256(os.path.join(opendis, f))))
    for label, path in (("xmlpg LICENSE.md", os.path.join(xmlpg, "LICENSE.md")),
                        ("open-dis-python LICENSE", os.path.join(opendis, "LICENSE"))):
        o += ["", "## %s" % label, "", "```"] + read_text(path).rstrip("\n").splitlines() + ["```"]
    o.append("")
    out.write(PROV, "\n".join(o))


def read_sources_provenance(text, xmlpg, opendis):
    facts = {}
    for key, rx in (("xmlpg", r"\| layouts \| [^,\s]+, ([^,\s]+), commit `([0-9a-f]{40})` \|"),
                    ("opendis", r"\| PDU types \| [^,\s]+, ([^,\s]+), commit `([0-9a-f]{40})` \|")):
        m = re.search(rx, text)
        if not m:
            raise GenError("%s states no %s commit" % (PROV, key))
        facts[key + "_ref"], facts[key] = m.group(1), m.group(2)
    table = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    want = ["xmlpg/" + f for f in XMLPG_FILES] + ["opendis/" + f for f in OPENDIS_FILES]
    for rel in want:
        if rel not in table:
            raise GenError("%s has no SHA-256 for %s" % (PROV, rel))
        base, sub = rel.split("/", 1)
        if sha256(os.path.join(xmlpg if base == "xmlpg" else opendis, sub)) != table[rel]:
            raise GenError("%s does not match the SHA-256 in %s" % (rel, PROV))
    return facts, table


# -------------------------------------------------------------------- main ---

def run(args, out):
    if args.commit_xmlpg or args.commit_opendis:
        if not (args.commit_xmlpg and args.commit_opendis):
            raise GenError("--commit-xmlpg and --commit-opendis go together")
        write_sources_provenance(out, args.xmlpg, args.opendis, {
            "xmlpg": args.commit_xmlpg, "xmlpg_ref": args.ref_xmlpg or "untagged",
            "opendis": args.commit_opendis, "opendis_ref": args.ref_opendis or "untagged"})
    prov, table = read_sources_provenance(out.read(PROV), args.xmlpg, args.opendis)
    src = Source(args.xmlpg, args.opendis)
    exclude = {}
    for item in args.exclude or []:
        cls, sep, why = item.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z0-9]+", cls) or not why.strip():
            raise GenError("--exclude takes CLASS=REASON, not %r" % item)
        if cls not in src.classes:
            raise GenError("--exclude: no class %s" % cls)
        exclude[cls] = why.strip()
    plan = Plan(src, exclude)
    unused = set(exclude) - {c for c, _, _ in plan.not_built}
    if unused:
        raise GenError("--exclude names a class that is not a numbered PDU: %s" % sorted(unused))
    pdir = "packs/" + FORMAT
    out.write("model/%s.def" % MODULE, module_text(plan, prov))
    out.write(pdir + "/pack.def", pack_text(plan, prov))
    vecs = vector_files(plan)
    keep = {n for n, _ in vecs}
    for old in out.listdir(pdir + "/vectors"):
        if old.endswith(".json") and old not in keep:
            out.remove("%s/vectors/%s" % (pdir, old))
    for n, t in vecs:
        out.write("%s/vectors/%s" % (pdir, n), t)
    core_text = read_text(args.core_def) if args.core_def else out.read("model/core.def")
    model = gtcheck.Model()
    model.add(core_text, "model/core.def")
    model.add(out.read("model/%s.def" % MODULE), "model/%s.def" % MODULE)
    pack = gtcheck.load_pack(out.read(pdir + "/pack.def"), model, pdir + "/pack.def")
    total = check_vectors(pack, [(n, out.read("%s/vectors/%s" % (pdir, n))) for n, _ in vecs])
    out.write(pdir + "/pack.md", pack_md(plan, prov, len(vecs)))
    out.write(pdir + "/PROVENANCE.md", provenance_md(prov, table))
    return ["layouts         %s (commit %s)" % (prov["xmlpg_ref"], prov["xmlpg"]),
            "types           %s (commit %s)" % (prov["opendis_ref"], prov["opendis"]),
            "kinds           %d (%d with a counted list)" % (len(plan.kinds), sum(1 for k in plan.kinds if k.group)),
            "not built       %d" % len(plan.not_built),
            "unnumbered      %s" % ", ".join(plan.unnumbered),
            "keys            %d, lists %d" % (len(plan.keys), len(plan.lists)),
            "vectors         %d checked" % total,
            "self-check      ok"]


def build_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(prog=NAME, description=__doc__.split("\n")[0])
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("--xmlpg", required=True, metavar="DIR", help="a checkout of %s" % XMLPG)
    ap.add_argument("--opendis", required=True, metavar="DIR", help="a checkout of %s" % OPENDIS)
    ap.add_argument("--commit-xmlpg", help="write %s: the xmlpg commit" % PROV)
    ap.add_argument("--commit-opendis", help="write %s: the open-dis-python commit" % PROV)
    ap.add_argument("--ref-xmlpg", help="the branch or tag of --commit-xmlpg")
    ap.add_argument("--ref-opendis", help="the branch or tag of --commit-opendis")
    ap.add_argument("--exclude", action="append", metavar="CLASS=REASON",
                    help="build no kind for this PDU class, and list it with the reason")
    ap.add_argument("--core-def", help="model/core.def (default <out>/model/core.def)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = genio.Output(args.out, check=args.check)
    try:
        lines = run(args, out)
    except (GenError, gtcheck.CheckError, SyntaxError, ET.ParseError) as e:
        print("%s: %s" % (NAME, e), file=sys.stderr)
        return 1
    except OSError as e:
        print("%s: %s: %s" % (NAME, e.filename, e.strerror), file=sys.stderr)
        return 1
    print("\n".join(lines))
    return out.report(NAME)


if __name__ == "__main__":
    sys.exit(main())
