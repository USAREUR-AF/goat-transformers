#!/usr/bin/env python3
"""Generate goat-transformers packs from the u-blox UBX message definitions
of pyubx2 (github.com/semuconsulting/pyubx2, src/pyubx2/ubxtypes_*.py).

Reads   <src>/src/pyubx2/ubxtypes_core.py, ubxtypes_get.py, ubxtypes_set.py,
        ubxtypes_poll.py and <src>/LICENSE, as Python syntax trees: no file of
        the source is run;
        tools/gen/sources/ubx-PROVENANCE.md (the tag, commit and SHA-256 of every
        file; a file that differs is refused)
Writes  <out>/model/ubx<class>.def             one module per message class
        <out>/packs/ubx-<class>/pack.def       one pack per class, one kind per
        <out>/packs/ubx-<class>/pack.md        message definition of fixed length
        <out>/packs/ubx-<class>/PROVENANCE.md
        <out>/packs/ubx-<class>/vectors/*.json
        tools/gen/sources/ubx-PROVENANCE.md   (only with --commit)

The message is one UBX frame without its checksum: the sync characters 0xB5
0x62, the class, the id, the payload length (u16, little-endian) and the
payload. A kind is selected by the class, the id and the payload length, and
for a message whose identity includes the first payload byte, by that byte.

Every vector's frame is written by a UBX serializer in this file from the
definition's layout (fields in order, little-endian, bit fields from the least
significant bit); the generator then loads the pack with gtcheck and decodes
and encodes every vector with its own codec of the bits wire.

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
from decimal import Decimal
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

NAME = "ubx2pack"
VERSION = "0.1.0"
REPO = "https://github.com/semuconsulting/pyubx2"
PROV = "tools/gen/sources/ubx-PROVENANCE.md"
PKG_DIR = "src/pyubx2"
FILES = ["ubxtypes_core.py", "ubxtypes_get.py", "ubxtypes_set.py", "ubxtypes_poll.py", "ubxvariants.py"]
MODES = [("GET", "ubxtypes_get.py", "UBX_PAYLOADS_GET", ""),
         ("SET", "ubxtypes_set.py", "UBX_PAYLOADS_SET", "_set"),
         ("POLL", "ubxtypes_poll.py", "UBX_PAYLOADS_POLL", "_poll")]
SYNC = (0xB5, 0x62)
PAYLOAD_BIT0 = 48               # sync 16, class 8, id 8, length 16
MAX_REQUIRES = 3
LICENSE_LINE = "BSD 3-Clause, copyright (c) 2020 semuadmin (Steve Smith)"


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


# ------------------------------------------------------------ definitions ---
#
# The definitions are Python dictionary literals. They are read with `ast`,
# never run: a name resolves to the value of a module-level assignment in
# ubxtypes_core.py, and a scale written as a product of numbers and names
# (`180 * P2_N24`) is evaluated exactly. A scale name states its value: E1_Nk
# is 10^-k, P2_Nk is 2^-k, P2_Pk is 2^k.

Ref = collections.namedtuple("Ref", "name")         # a name from ubxtypes_core.py
Alias = collections.namedtuple("Alias", "mode name")  # UBX_GET["NAME"]: that definition


def scale_of_name(name):
    m = re.fullmatch(r"E1_N(\d+)", name)
    if m:
        return Fraction(1, 10 ** int(m.group(1)))
    m = re.fullmatch(r"P2_([NP])(\d+)", name)
    if m:
        return Fraction(1, 2 ** int(m.group(2))) if m.group(1) == "N" else Fraction(2 ** int(m.group(2)))
    return None


def literal(node, where):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return Ref(node.id)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(literal(e, where) for e in node.elts)
    if isinstance(node, ast.Dict):
        out = collections.OrderedDict()
        for k, v in zip(node.keys, node.values):
            if k is None:
                raise GenError("%s: a ** entry in a dictionary" % where)
            out[literal(k, where)] = literal(v, where)
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        a, b = exact(literal(node.left, where), where), exact(literal(node.right, where), where)
        return a * b
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
            and node.value.id.startswith("UBX_") and isinstance(node.slice, ast.Constant)):
        return Alias(node.value.id, node.slice.value)
    raise GenError("%s: an expression the generator does not read (line %d)" % (where, node.lineno))


def exact(v, where):
    """A scale as an exact fraction."""
    if isinstance(v, Fraction):
        return v
    if isinstance(v, Ref):
        f = scale_of_name(v.name)
        if f is None:
            raise GenError("%s: scale name %s" % (where, v.name))
        return f
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise GenError("%s: scale %r" % (where, v))
    return Fraction(v) if isinstance(v, int) else Fraction(Decimal(repr(v)))


def module_updates(text, where, var):
    """The names merged into `var` by module-level `var.update(NAME)` lines."""
    out = []
    for st in ast.parse(text, where).body:
        if (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call)
                and isinstance(st.value.func, ast.Attribute) and st.value.func.attr == "update"
                and isinstance(st.value.func.value, ast.Name) and st.value.func.value.id == var):
            args = st.value.args
            if len(args) != 1 or not isinstance(args[0], ast.Name) or st.value.keywords:
                raise GenError("%s: an update of %s the generator does not read" % (where, var))
            out.append(args[0].id)
    return out


def module_assignments(text, where):
    out = collections.OrderedDict()
    for st in ast.parse(text, where).body:
        if isinstance(st, (ast.Assign, ast.AnnAssign)):
            target = st.targets[0] if isinstance(st, ast.Assign) else st.target
            if isinstance(target, ast.Name) and st.value is not None:
                out[target.id] = st.value
    return out


class Source:
    def __init__(self, src, units=None):
        self.units = units
        base = os.path.join(src, PKG_DIR)
        core = module_assignments(read_text(os.path.join(base, "ubxtypes_core.py")), "ubxtypes_core.py")
        self.consts = {}
        for name, node in core.items():
            if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float)):
                self.consts[name] = node.value
        self.ids = collections.OrderedDict()     # name -> identity bytes
        for k, v in zip(core["UBX_MSGIDS"].keys, core["UBX_MSGIDS"].values):
            key, name = literal(k, "UBX_MSGIDS"), literal(v, "UBX_MSGIDS")
            if name not in self.ids:
                self.ids[name] = key
        self.classes = {}
        for k, v in zip(core["UBX_CLASSES"].keys, core["UBX_CLASSES"].values):
            self.classes[literal(k, "UBX_CLASSES")] = literal(v, "UBX_CLASSES")
        self.variants, self.selectors = self.read_variants(read_text(os.path.join(base, "ubxvariants.py")))
        self.defs = collections.OrderedDict()    # mode -> {name: definition}
        for mode, fname, var, _ in MODES:
            text = read_text(os.path.join(base, fname))
            nodes = module_assignments(text, fname)
            if var not in nodes:
                raise GenError("%s defines no %s" % (fname, var))
            self.defs[mode] = literal(nodes[var], fname)
            for other in module_updates(text, fname, var):
                if other not in nodes:
                    raise GenError("%s: %s.update(%s) of an unknown name" % (fname, var, other))
                self.defs[mode].update(literal(nodes[other], fname))

    @staticmethod
    def read_variants(text):
        """({(mode, identity bytes): (function name, [definition names])},
        {definition name: (payload byte, value)}) from the
        VARIANTS table of ubxvariants.py: the definitions a function chooses
        among for one identity, by a rule in its code (a version byte, the
        length)."""
        tree = ast.parse(text, "ubxvariants.py")
        names, selectors = {}, {}
        for st in tree.body:
            if isinstance(st, ast.FunctionDef):
                Source.read_selectors(st, selectors)
                found = []
                for node in ast.walk(st):
                    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                            and node.value.id.startswith("UBX_PAYLOADS_") and isinstance(node.slice, ast.Constant)
                            and node.slice.value not in found):
                        found.append(node.slice.value)
                names[st.name] = found
        out = {}
        for st in tree.body:
            if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name) and st.targets[0].id == "VARIANTS":
                for mk, mv in zip(st.value.keys, st.value.values):
                    mode = mk.id
                    for ik, iv in zip(mv.keys, mv.values):
                        out[(mode, ast.literal_eval(ik))] = (iv.id, names.get(iv.id, []))
        if not out:
            raise GenError("ubxvariants.py has no VARIANTS table")
        return out, selectors

    @staticmethod
    def read_selectors(func, selectors):
        """Definitions a variant function returns when one payload byte has one
        value: `v = kwargs["payload"][i:i+1]` and then `if v == b"\\xNN": return
        UBX_PAYLOADS_X["NAME"]`."""
        places = {}
        for node in ast.walk(func):
            if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Subscript) and isinstance(node.value.slice, ast.Slice)
                    and isinstance(node.value.value, ast.Subscript)
                    and isinstance(node.value.value.slice, ast.Constant) and node.value.value.slice.value == "payload"):
                lo, hi = node.value.slice.lower, node.value.slice.upper
                if isinstance(lo, ast.Constant) and isinstance(hi, ast.Constant) and hi.value == lo.value + 1:
                    places[node.targets[0].id] = lo.value
        for node in ast.walk(func):
            if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and len(node.test.ops) == 1
                    and isinstance(node.test.ops[0], ast.Eq) and isinstance(node.test.left, ast.Name)
                    and node.test.left.id in places and isinstance(node.test.comparators[0], ast.Constant)
                    and isinstance(node.test.comparators[0].value, bytes) and len(node.test.comparators[0].value) == 1
                    and node.body and isinstance(node.body[0], ast.Return)
                    and isinstance(node.body[0].value, ast.Subscript)
                    and isinstance(node.body[0].value.slice, ast.Constant)):
                selectors[node.body[0].value.slice.value] = (places[node.test.left.id],
                                                             node.test.comparators[0].value[0])

    def variant_identity(self, mode, name):
        """(identity, function) when `name` is one of the definitions a variant
        function of `mode` chooses among."""
        for (m, ident), (func, names) in self.variants.items():
            if m == mode and name in names:
                return ident, func
        return None

    def type_name(self, v):
        """The type text of a Ref (`U004`), or the text itself."""
        if isinstance(v, Ref):
            if v.name not in self.consts:
                raise GenError("unknown name %s" % v.name)
            return str(self.consts[v.name])
        return v

    def identity_name(self, ident):
        return next((n for n, i in self.ids.items() if i == ident), None)

    def identity(self, name):
        """(identity bytes, the message name it belongs to) of a definition name:
        the name itself, or the longest message name it extends (`MON-RF-V0`,
        `CFG-NMEAvX`); None when there is none."""
        if name in self.ids:
            return self.ids[name], name
        best = None
        for mname in self.ids:
            if name.startswith(mname) and len(name) > len(mname) and name[len(mname)] in "-v":
                if best is None or len(mname) > len(best):
                    best = mname
        return (self.ids[best], best) if best else None


# ------------------------------------------------------------------- plan ---

class Variable(Exception):
    """A part of the message whose length is not fixed; the text says what."""


Leaf = collections.namedtuple("Leaf", "name kind bitpos bits scale")
Leaf.__doc__ = """A field of the payload: `kind` is u, s, f32, f64 or ascii;
`bitpos` counts from payload bit 0, least significant bit first; `scale` is a
Fraction for a scaled integer, else None."""


def width(ty):
    m = re.fullmatch(r"[UIXELRCA](\d+)", ty)
    if not m:
        return None
    return int(m.group(1))


def unpack_type(src, v, where):
    """(type text, scale or None) of a field value."""
    if isinstance(v, tuple) and len(v) == 2 and not isinstance(v[1], (dict, collections.OrderedDict)):
        return src.type_name(v[0]), exact(v[1], where)
    if isinstance(v, (Ref, str)):
        return src.type_name(v), None
    raise GenError("%s: a field value the generator does not read" % where)


def flatten(src, defn, suffix, bitpos, where, leaves):
    """Append the leaves of `defn` from payload bit `bitpos`; the bit after them."""
    for key, v in defn.items():
        if key.endswith("_bit"):
            ty, _ = unpack_type(src, v[0], where)
            size = width(ty)
            if ty[0] != "X" or size is None:
                raise GenError("%s: bit field %s of type %s" % (where, key, ty))
            pos = bitpos
            for sub, sv in v[1].items():
                sty, scale = unpack_type(src, sv, where)
                n = width(sty)
                if sty[0] not in "UIX" or not n:
                    raise GenError("%s: bit %s of type %s" % (where, sub, sty))
                kind = "s" if sty[0] == "I" else "u"
                leaves.append(Leaf(sub + suffix, kind, pos, n, scale))
                pos += n
            if pos > bitpos + 8 * size:
                raise GenError("%s: the bits of %s exceed its %d bytes" % (where, key, size))
            bitpos += 8 * size
        elif key.endswith("_grp") or (isinstance(v, tuple) and len(v) == 2 and isinstance(v[1], dict)):
            count, body = v
            count = src.type_name(count) if isinstance(count, Ref) else count
            if isinstance(count, int) and not isinstance(count, bool):
                for i in range(1, count + 1):
                    bitpos = flatten(src, body, "%s_%02d" % (suffix, i), bitpos, where, leaves)
            elif count == src.consts.get("VARIABLE"):
                raise Variable("a group repeated to the end of the payload")
            elif isinstance(count, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", count):
                raise Variable("a group repeated by field `%s`" % count)
            else:
                raise Variable("a group whose count is %r" % (count,))
        else:
            ty, scale = unpack_type(src, v, where)
            n = width(ty)
            if ty in (src.consts.get("CH"), src.consts.get("PMPLEN")) or n is None:
                raise Variable("a field of type %s whose length the payload length gives" % ty
                               if ty != "CH" else "text that runs to the end of the payload")
            name = key + suffix
            if ty[0] == "A":
                for i in range(1, n + 1):
                    leaves.append(Leaf("%s_%02d" % (name, i), "u", bitpos, 8, None))
                    bitpos += 8
            elif ty[0] == "C":
                if n > 255:
                    raise GenError("%s: text of %d bytes" % (where, n))
                leaves.append(Leaf(name, "ascii", bitpos, 8 * n, None))
                bitpos += 8 * n
            elif ty[0] == "R":
                if n not in (4, 8) or scale is not None:
                    raise GenError("%s: float %s" % (where, ty))
                leaves.append(Leaf(name, "f32" if n == 4 else "f64", bitpos, 8 * n, None))
                bitpos += 8 * n
            elif n > 8:
                if scale is not None:
                    raise GenError("%s: a scaled field of %d bytes" % (where, n))
                for i, off in enumerate(range(0, n, 8), 1):
                    k = min(8, n - off)
                    leaves.append(Leaf("%s_%02d" % (name, i), "u", bitpos, 8 * k, None))
                    bitpos += 8 * k
            else:
                leaves.append(Leaf(name, "s" if ty[0] == "I" else "u", bitpos, 8 * n, scale))
                bitpos += 8 * n
    return bitpos


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return s if s and not s[0].isdigit() else "x" + s


def factor_text(f):
    return str(f.numerator) if f.denominator == 1 else "%d/%d" % (f.numerator, f.denominator)


Line = collections.namedtuple("Line", "key pos bits tr leaf")


class KindPlan:
    def __init__(self, name, mode, defname, msgname, ident, size, lines):
        self.name, self.mode, self.defname, self.msgname = name, mode, defname, msgname
        self.ident, self.size, self.lines, self.requires = ident, size, lines, []
        # payload bytes that select the kind: the identity's third byte, a selector
        self.fixed = [(i, b) for i, b in enumerate(ident[2:])]
        self.selector = None
        end = max(l.pos + l.bits for l in lines)
        self.pads = []                 # (bit, len): unmapped bits after the last field, written 0
        stop = PAYLOAD_BIT0 + 8 * size
        while end < stop:
            n = min(64, stop - end)
            self.pads.append((end, n))
            end += n

    @property
    def cls(self):
        return self.ident[0]

    @property
    def mid(self):
        return self.ident[1]


# Messages whose position fields the source shows as WGS84 degrees and whose
# `height` it shows as the height above the ellipsoid in millimetres (pack.md
# states the evidence).
POSITION = {"NAV-PVT", "NAV-POSLLH", "NAV-HPPOSLLH"}
DEG7 = Fraction(1, 10 ** 7)


# Units from the ublox_msgs message files (github.com/KumarRobotics/ublox,
# ublox_msgs/msg, BSD; the commit the ros2-ublox-msgs pack uses). For each
# definition: (pyubx2 field, leaf kind, leaf scale, ublox_msgs field, words its
# comment must hold, the unit in its brackets, key, transform). The generator
# reads each file and binds a field only when its comment holds the words and
# states that unit; down is the negative of up, and a course is read as from
# true north.
DEG5 = Fraction(1, 10 ** 5)
UNITS = {
    "NAV-PVT": ("NavPVT.msg", [
        ("lon", "s", DEG7, "lon", ("longitude",), "deg / 1e-7", "lon", "sscale:1/10000000"),
        ("lat", "s", DEG7, "lat", ("latitude",), "deg / 1e-7", "lat", "sscale:1/10000000"),
        ("height", "s", None, "height", ("height", "ellipsoid"), "mm", "hae", "sscale:1/1000"),
        ("velN", "s", None, "vel_n", ("north", "velocity"), "mm/s", "track.vel_north_ms", "sscale:1/1000"),
        ("velE", "s", None, "vel_e", ("east", "velocity"), "mm/s", "track.vel_east_ms", "sscale:1/1000"),
        ("velD", "s", None, "vel_d", ("down", "velocity"), "mm/s", "track.vel_up_ms", "sscale:-0.001"),
        ("gSpeed", "s", None, "g_speed", ("ground speed", "2-d"), "mm/s", "speed_ms", "sscale:1/1000"),
        ("headMot", "s", DEG5, "heading", ("heading of motion", "2-d"), "deg / 1e-5", "course", "sscale:1/100000"),
    ]),
    "NAV-VELNED": ("NavVELNED.msg", [
        ("velN", "s", None, "vel_n", ("north", "velocity"), "cm/s", "track.vel_north_ms", "sscale:1/100"),
        ("velE", "s", None, "vel_e", ("east", "velocity"), "cm/s", "track.vel_east_ms", "sscale:1/100"),
        ("velD", "s", None, "vel_d", ("down", "velocity"), "cm/s", "track.vel_up_ms", "sscale:-0.01"),
        ("gSpeed", "u", None, "g_speed", ("ground speed", "2-d"), "cm/s", "speed_ms", "uscale:1/100"),
        ("heading", "s", DEG5, "heading", ("heading of motion", "2-d"), "deg / 1e-5", "course", "sscale:1/100000"),
    ]),
    "HNR-PVT": ("HnrPVT.msg", [
        ("lon", "s", DEG7, "lon", ("longitude",), "deg / 1e-7", "lon", "sscale:1/10000000"),
        ("lat", "s", DEG7, "lat", ("latitude",), "deg / 1e-7", "lat", "sscale:1/10000000"),
        ("height", "s", None, "height", ("height", "ellipsoid"), "mm", "hae", "sscale:1/1000"),
        ("gSpeed", "s", None, "g_speed", ("ground speed", "2-d"), "mm/s", "speed_ms", "sscale:1/1000"),
        ("headMot", "s", DEG5, "head_mot", ("heading of motion", "2-d"), "deg / 1e-5", "course", "sscale:1/100000"),
    ]),
}
UBLOX_MSGS_REPO = "https://github.com/KumarRobotics/ublox"
UBLOX_MSGS_COMMIT = "3a3e1c253722b68e350a60aee6ef399d8c2304cb"
UBLOX_MSGS_FILES = ["ublox_msgs/msg/NavPVT.msg", "ublox_msgs/msg/NavVELNED.msg", "ublox_msgs/msg/HnrPVT.msg",
                    "ublox_msgs/package.xml", "ublox_msgs/src/ublox_msgs.cpp"]


def read_msg_units(text):
    """{field: (comment in lower case, unit text)} of a ublox_msgs .msg file."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"u?int\d+(?:\[\d*\])?[ \t]+(\w+)[ \t]*#(.*)", line.strip())
        if m:
            comment = m.group(2).strip()
            u = re.search(r"\[([^\]]*)\]$", comment)
            out[m.group(1)] = (comment.lower(), u.group(1).strip() if u else None)
    return out


def unit_bindings(units, defname, leaves):
    """{leaf name: (key, transform, evidence)} from UNITS, checked against the
    .msg file; a field whose comment or unit differs is not bound."""
    if units is None or defname not in UNITS:
        return {}
    fname, rows = UNITS[defname]
    msg = units[fname]
    names = {l.name: l for l in leaves}
    out = {}
    for field, kind, scale, mfield, words, unit, key, tr in rows:
        leaf = names.get(field)
        if leaf is None or leaf.kind != kind or leaf.bits != 32 or leaf.scale != scale or mfield not in msg:
            continue
        comment, stated = msg[mfield]
        if stated == unit and all(w in comment for w in words):
            out[field] = (key, tr, "%s `%s` [%s]" % (fname, mfield, unit))
    return out


def bindings(mode, defname, leaves, alias_of=None, units=None):
    """{leaf name: (core key, transform)} for a definition; `alias_of` is the
    GET definition the source gives it as its own (NAV2-PVT is NAV-PVT)."""
    if mode != "GET":
        return {}
    out = {}
    for name in (alias_of, defname):
        if name:
            out.update(unit_bindings(units, name, leaves))
    if not ({defname, alias_of} & POSITION):
        return out
    names = {l.name: l for l in leaves}
    lat, lon = names.get("lat"), names.get("lon")
    if not (lat and lon and all(l.kind == "s" and l.bits == 32 and l.scale == DEG7 for l in (lat, lon))):
        return {}
    ex = "pyubx2 examples"
    out.setdefault("lat", ("lat", "sscale:1/10000000", ex))
    out.setdefault("lon", ("lon", "sscale:1/10000000", ex))
    h, msl = names.get("height"), names.get("hMSL")
    if h and msl and h.kind == "s" and h.bits == 32 and h.scale is None:
        out.setdefault("height", ("hae", "sscale:1/1000", ex))
    return out


class ClassPlan:
    def __init__(self, cls, cname):
        self.cls, self.cname = cls, cname
        self.format = "ubx-" + slug(cname).replace("_", "-")
        self.module = "ubx" + re.sub(r"[^a-z0-9]", "", cname.lower())
        self.kinds, self.keys = [], collections.OrderedDict()
        self.not_built = []            # (mode, definition, identity, reason)
        self.core = []                 # (kind, field, key, transform)
        self.scaled = []               # (kind, field, transform)
        self.aliases = {}              # kind -> the definition the source gives as its own

    def add(self, src, mode, defname, msgname, ident, defn, suffix, alias_of=None):
        where = "%s %s" % (mode, defname)
        leaves = []
        try:
            nbits = flatten(src, defn, "", PAYLOAD_BIT0 - PAYLOAD_BIT0, where, leaves)
        except Variable as e:
            self.not_built.append((mode, defname, ident, str(e)))
            return
        size = nbits // 8
        if not leaves:
            self.not_built.append((mode, defname, ident, "an empty payload: a kind needs at least one field"))
            return
        if size > 0xFFFF:
            raise GenError("%s: payload of %d bytes" % (where, size))
        sel = src.selectors.get(defname)
        for k in self.kinds:
            if k.ident == ident and k.size == size and (sel or None) == k.selector:
                self.not_built.append((mode, defname, ident, "the same class, id and payload length as kind `%s`"
                                       % k.name))
                return
        kind = slug(defname) + suffix
        if any(k.name == kind for k in self.kinds):
            raise GenError("two definitions give the kind %s" % kind)
        bound = bindings(mode, defname, leaves, alias_of, src.units)
        if alias_of:
            self.aliases[kind] = alias_of
        lines, seen = [], set()
        for leaf in leaves:
            pos = PAYLOAD_BIT0 + leaf.bitpos
            if leaf.name in bound:
                key, tr, evidence = bound[leaf.name]
                lines.append(Line(key, pos, leaf.bits, tr, leaf))
                self.core.append((kind, leaf.name, key, tr, evidence))
                continue
            base = "%s_%s" % (kind, slug(leaf.name))
            name, n = base, 2
            while name in seen:
                name, n = "%s_%d" % (base, n), n + 1
            seen.add(name)
            if leaf.kind == "ascii":
                tr, typ = "ascii", "string"
            elif leaf.kind in ("f32", "f64"):
                tr, typ = leaf.kind, "float"
            elif leaf.scale is not None:
                tr = ("sscale:" if leaf.kind == "s" else "uscale:") + factor_text(leaf.scale)
                typ = "float"
                self.scaled.append((kind, leaf.name, tr))
            else:
                tr, typ = ("twos" if leaf.kind == "s" else "uint"), "int"
            if name in self.keys:
                raise GenError("%s: key %s twice" % (where, name))
            self.keys[name] = (typ, defname, mode, leaf.name)
            lines.append(Line("%s.%s" % (self.module, name), pos, leaf.bits, tr, leaf))
        if not any(l.key.startswith(self.module + ".") for l in lines):
            self.not_built.append((mode, defname, ident, "every field binds a shared key"))
            return
        kp = KindPlan(kind, mode, defname, msgname, ident, size, lines)
        if defname in src.selectors:
            pos, value = src.selectors[defname]
            if pos < len(kp.fixed) or 8 * pos >= 8 * size:
                raise GenError("%s: selector byte %d" % (where, pos))
            kp.fixed.append((pos, value))
            kp.selector = (pos, value)
        self.kinds.append(kp)

    def finish(self):
        # a kind chosen by a selector byte goes before a kind of the same
        # identity and length that is not, which would also hold for its frames
        ordered = []
        for k in self.kinds:
            if k.selector:
                at = next((i for i, o in enumerate(ordered)
                           if o.ident == k.ident and o.size == k.size and not o.selector), len(ordered))
                ordered.insert(at, k)
            else:
                ordered.append(k)
        self.kinds = ordered
        own = self.module + "."
        usage = collections.Counter(l.key for k in self.kinds for l in k.lines if l.key.startswith(own))
        for k in self.kinds:
            raw = [l.key for l in k.lines if l.key.startswith(own)]
            ranked = sorted(range(len(raw)), key=lambda i: (usage[raw[i]], i))
            k.requires = [raw[i] for i in sorted(ranked[:MAX_REQUIRES])]


def fixed_size(src, defn):
    """The payload length of a definition, or None when it varies."""
    if isinstance(defn, Alias):
        defn = src.defs[{"UBX_PAYLOADS_GET": "GET", "UBX_GET": "GET", "UBX_PAYLOADS_SET": "SET",
                         "UBX_PAYLOADS_POLL": "POLL"}[defn.mode]][defn.name]
    try:
        return flatten(src, defn, "", 0, "variant", []) // 8
    except Variable:
        return None


def variant_clash(src, mode, var, defname):
    """Why a definition that a variant function chooses is not built, or None:
    a definition the function chooses by the value of one payload byte is
    built with a `when` on that byte; any other is built only when every other
    definition of its identity not so chosen has a fixed length and a different
    one, so that the length tells them apart."""
    ident, func = var
    names = src.variants[(mode, ident)][1]
    mine = fixed_size(src, src.defs[mode][defname])
    if mine is None or defname in src.selectors:
        return None                    # variable anyway, or told apart by its selector byte
    for other in names:
        if other == defname or other not in src.defs[mode] or other in src.selectors:
            continue
        size = fixed_size(src, src.defs[mode][other])
        if size is None or size == mine:
            return ("one of the variants `%s` chooses by a rule in its code; %s, another variant, %s"
                    % (func, other, "has a variable length" if size is None else "has the same length"))
    return None


def plan(src):
    """(class plans in class order, definitions with no identity)."""
    plans, orphans = collections.OrderedDict(), []
    for mode, _, _, suffix in MODES:
        for defname, defn in src.defs[mode].items():
            alias_of = None
            if isinstance(defn, Alias):
                target = {"UBX_GET": "GET", "UBX_SET": "SET", "UBX_POLL": "POLL",
                          "UBX_PAYLOADS_GET": "GET", "UBX_PAYLOADS_SET": "SET",
                          "UBX_PAYLOADS_POLL": "POLL"}.get(defn.mode)
                if target is None or defn.name not in src.defs[target]:
                    raise GenError("%s %s: alias %s[%r]" % (mode, defname, defn.mode, defn.name))
                alias_of = defn.name if target == "GET" else None
                defn = src.defs[target][defn.name]
            if not isinstance(defn, dict):
                raise GenError("%s %s: not a dictionary" % (mode, defname))
            found = src.identity(defname)
            var = src.variant_identity(mode, defname)
            if var and (found is None or found[0][:2] == var[0]):
                found = (var[0] if found is None else found[0], src.identity_name(var[0]))
            if found is None:
                orphans.append((mode, defname))
                continue
            ident, msgname = found
            if var:
                clash = variant_clash(src, mode, var, defname)
                if clash:
                    cls = ident[:1]
                    if cls not in plans:
                        plans[cls] = ClassPlan(ident[0], src.classes[cls])
                    plans[cls].not_built.append((mode, defname, ident, clash))
                    continue
            cls = ident[:1]
            if cls not in src.classes:
                orphans.append((mode, defname))
                continue
            if cls not in plans:
                plans[cls] = ClassPlan(ident[0], src.classes[cls])
            plans[cls].add(src, mode, defname, msgname, ident, defn, suffix, alias_of)
    out = sorted(plans.values(), key=lambda p: p.cls)
    for p in out:
        p.finish()
    return out, orphans


# ------------------------------------------------------------------- emit ---

def loc(pos, n):
    return "0:%d:%d" % (pos, n)


def source_line(tag, sha):
    return 'source        "%s %s/ubxtypes_get.py, ubxtypes_set.py, ubxtypes_poll.py at %s (commit %s)"' % (
        REPO, PKG_DIR, tag, sha)


def pack_text(cp, sha, tag):
    o = ["# UBX frames of the message class %s (0x%02X), one kind per message definition." % (cp.cname, cp.cls),
         "# Generated by tools/gen/ubx2pack.py; do not edit by hand.",
         "# The message is one UBX frame without its checksum: sync 0xB5 0x62, class,",
         "# id, payload length (u16), payload. Payload bit 0 is bit %d." % PAYLOAD_BIT0,
         "format        %s" % cp.format,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(tag, sha),
         "uses          %s" % cp.module] + (
        ["uses          track"] if any(c[2].startswith("track.") for c in cp.core) else []) + [
         "wire          bits",
         "bit_order     lsb",
         "word_bytes    1",
         "when   %s %d" % (loc(0, 8), SYNC[0]),
         "when   %s %d" % (loc(8, 8), SYNC[1]),
         "when   %s %d" % (loc(16, 8), cp.cls)]
    for k in cp.kinds:
        o.append("")
        o.append("kind      %s" % k.name)
        o.append("when      %s %d" % (loc(24, 8), k.mid))
        o.append("when      %s %d" % (loc(32, 16), k.size))
        for i, b in k.fixed:
            o.append("when      %s %d" % (loc(PAYLOAD_BIT0 + 8 * i, 8), b))
        if k.requires:
            o.append("requires  %s" % " ".join(k.requires))
        for l in k.lines:
            o.append("field     %s %s %s" % (l.key, loc(l.pos, l.bits), l.tr))
        for pos, n in k.pads:
            o.append("const     %s 0" % loc(pos, n))
    return "\n".join(o) + "\n"


def module_text(cp, sha, tag):
    o = ["# The %s module: the payload fields of the UBX message class %s." % (cp.module, cp.cname),
         "# Generated by tools/gen/ubx2pack.py; do not edit by hand. A key is",
         "# <definition>_<field>, the field name in lower case with a group's repeat",
         "# number appended; a scale the definition states is applied.",
         "module        %s" % cp.module,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(tag, sha)]
    for name, (typ, defname, mode, fname) in cp.keys.items():
        o.append('key  %s  %s  -  "field %s of %s %s"' % (name, typ, fname, mode, defname))
    return "\n".join(o) + "\n"


# ------------------------------------------------- UBX serializer (vectors) ---

def checksum(data):
    """The two UBX checksum bytes (8-bit Fletcher) over class, id, length and
    payload."""
    a = b = 0
    for x in data:
        a = (a + x) & 0xFF
        b = (b + a) & 0xFF
    return bytes([a, b])


def raw_of(leaf, value):
    """The leaf's bits for a value in the leaf's own terms: an integer for u and
    s (scaled ones too: the stored integer), a float, or text."""
    if leaf.kind in ("u", "s"):
        return value & ((1 << leaf.bits) - 1)
    if leaf.kind == "f32":
        return int.from_bytes(struct.pack("<f", value), "little")
    if leaf.kind == "f64":
        return int.from_bytes(struct.pack("<d", value), "little")
    return int.from_bytes(value.encode("ascii").ljust(leaf.bits // 8, b"\0"), "little")


def payload_of(kind, values):
    acc = 0
    for l in kind.lines:
        acc |= raw_of(l.leaf, values[l.leaf.name]) << l.leaf.bitpos
    for i, b in kind.fixed:                 # bytes that select the kind
        acc = (acc & ~(0xFF << (8 * i))) | (b << (8 * i))
    return acc.to_bytes(kind.size, "little")


def frame(kind, payload, with_checksum):
    body = bytes([kind.cls, kind.mid]) + struct.pack("<H", len(payload)) + payload
    return bytes(SYNC) + body + (checksum(body) if with_checksum else b"")


def sample(leaf, salt):
    if leaf.kind == "ascii":
        return ("S%d" % (salt % 97))[:leaf.bits // 8]
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


# Cross-format cases: (definition, field values as stored integers, expected
# GeoJSON written by hand: coordinates [lon, lat, height], lon and lat in 1e-7
# degrees, height in millimetres).
CROSS = [
    ("NAV-PVT", {"lat": 473977420, "lon": 85455940, "height": 488250, "hMSL": 440120, "numSV": 14,
                 "fixType": 3, "iTOW": 326825000, "velN": 1500, "velE": -2500, "velD": 300,
                 "gSpeed": 12340, "headMot": 4512345},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.545594,47.397742,488.25]},'
     '"properties":{"course":45.12345,"speed_ms":12.34}}'),
]


def vector_text(pairs):
    return json.dumps(collections.OrderedDict(pairs), indent=2) + "\n"


def vector_files(cp):
    files = []
    for i, k in enumerate(cp.kinds):
        values = {l.leaf.name: sample(l.leaf, k.mid * 31 + j * 7 + i * 3 + 3) for j, l in enumerate(k.lines)}
        data = frame(k, payload_of(k, values), False).hex()
        files.append(("rt-%02x%02x-%s.json" % (k.cls, k.mid, k.name), vector_text([
            ("name", "%s-roundtrip-%s" % (cp.format, k.name)), ("from", cp.format), ("to", cp.format),
            ("input", data), ("expect", data), ("model", {"@kind": k.name})])))
    by_name = {(k.mode, k.defname): k for k in cp.kinds}
    for n, (name, given, expect) in enumerate(CROSS, 1):
        k = by_name.get(("GET", name))
        if k is None:
            continue
        values = {l.leaf.name: given.get(l.leaf.name, 0 if l.leaf.kind != "ascii" else "") for l in k.lines}
        model = collections.OrderedDict([("@kind", k.name)])
        for l in k.lines:
            if not l.key.startswith(cp.module + "."):
                num, _, den = l.tr.split(":", 1)[1].partition("/")
                exact_value = Decimal(given[l.leaf.name]) * Decimal(num) / Decimal(den or 1)
                model[l.key] = format(exact_value.normalize(), "f")
        files.append(("x-%02d-%s-to-geojson.json" % (n, k.name), vector_text([
            ("name", "%s-%s-to-geojson" % (cp.format, k.name)), ("from", cp.format), ("to", "geojson"),
            ("input", frame(k, payload_of(k, values), False).hex()), ("expect", expect), ("model", model)])))
    return files


# -------------------------------------------- codec, from the specification ---

def fmt_float(x):
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 1e17:
        return str(int(x))
    r = repr(x)
    return format(Decimal(r), "f") if "e" in r or "E" in r else r


def get_bits(data, pos, n):
    return (int.from_bytes(data, "little") >> pos) & ((1 << n) - 1)


def round_away(x):
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def decode_value(node, raw):
    tr, n = node.tr, node.bits
    if tr == "uint":
        return raw - (1 << 64) if n == 64 and raw >> 63 else raw
    if tr == "twos":
        return raw - (1 << n) if raw >> (n - 1) else raw
    if tr in ("uscale", "sscale"):
        if tr == "sscale" and raw >> (n - 1):
            raw -= 1 << n
        f = gtcheck.parse_factor(node.targs[0])
        return raw * float(f[0]) / float(f[1]) if isinstance(f, tuple) else raw * f
    if tr in ("f32", "f64"):
        v = struct.unpack("<f" if tr == "f32" else "<d", raw.to_bytes(n // 8, "little"))[0]
        if not math.isfinite(v):
            raise CodecError("transform-decode")
        return v
    if tr == "ascii":
        text = raw.to_bytes(n // 8, "little").rstrip(b"\0")
        if any(b < 0x20 or b > 0x7E for b in text):
            raise CodecError("transform-decode")
        return text.decode("ascii")
    raise CodecError("transform-decode")


def encode_value(node, x):
    tr, n = node.tr, node.bits
    mask = (1 << n) - 1
    if tr in ("uint", "twos"):
        return x & mask
    if tr in ("uscale", "sscale"):
        f = gtcheck.parse_factor(node.targs[0])
        r = round_away(x * float(f[1]) / float(f[0]) if isinstance(f, tuple) else x / f)
        lo, hi = (0, mask) if tr == "uscale" else (-(1 << (n - 1)), (1 << (n - 1)) - 1)
        if not lo <= r <= hi:
            raise CodecError("transform-encode")
        return r & mask
    if tr in ("f32", "f64"):
        return int.from_bytes(struct.pack("<f" if tr == "f32" else "<d", x), "little")
    if tr == "ascii":
        b = x.encode("ascii")
        if len(b) > n // 8:
            raise CodecError("transform-encode")
        return int.from_bytes(b.ljust(n // 8, b"\0"), "little")
    raise CodecError("transform-encode")


def holds(lines, data):
    return all(n.start + n.bits <= 8 * len(data) and get_bits(data, n.start, n.bits) == int(n.value)
               for n in lines if n.d == "when")


def decode(pack, data):
    kind = next((k for k in pack.kinds if holds(k.lines, data)), None) if holds(pack.common, data) else None
    if kind is None:
        raise CodecError("no-kind")
    lines = pack.common + kind.lines
    if 8 * len(data) < max(n.start + n.bits for n in lines if n.d in ("when", "field", "const")):
        raise CodecError("malformed-wire")
    ent = collections.OrderedDict()
    for n in lines:
        if n.d == "field":
            ent[n.key] = decode_value(n, get_bits(data, n.start, n.bits))
    return kind.name, ent


def encode(pack, name, ent):
    kind = next(k for k in pack.kinds if k.name == name)
    lines = pack.common + kind.lines
    acc = 0
    for n in lines:
        if n.d == "field" and n.key in ent:
            acc |= encode_value(n, ent[n.key]) << n.start
        elif n.d in ("when", "const"):
            acc |= int(n.value) << n.start
    nbytes = (max(n.start + n.bits for n in lines if n.d in ("when", "field", "const")) + 7) // 8
    return acc.to_bytes(nbytes, "little")


def geojson(ent):
    if "lat" in ent and "lon" in ent:
        coords = [fmt_float(ent["lon"]), fmt_float(ent["lat"])] + ([fmt_float(ent["hae"])] if "hae" in ent else [])
        geom = '{"type":"Point","coordinates":[%s]}' % ",".join(coords)
    else:
        geom = "null"
    props = ",".join('"%s":%s' % (k, fmt_float(ent[k])) for k in ("course", "speed_ms") if k in ent)
    return '{"type":"Feature","geometry":%s,"properties":{%s}}' % (geom, props)


def check_vectors(pack, vectors, fmt):
    n, seen = 0, set()
    for fn, text in vectors:
        vec = json.loads(text)
        try:
            kname, ent = decode(pack, bytes.fromhex(vec["input"]))
            for key, want in vec.get("model", {}).items():
                got = kname if key == "@kind" else ent.get(key)
                if got is None:
                    raise GenError("%s/%s: model %s not decoded" % (fmt, fn, key))
                if key != "@kind" and isinstance(got, float):
                    if abs(got - float(want)) > 1e-9:
                        raise GenError("%s/%s: model %s" % (fmt, fn, key))
                elif str(got) != want:
                    raise GenError("%s/%s: model %s = %s, vector says %s" % (fmt, fn, key, got, want))
            got = encode(pack, kname, ent).hex() if vec["to"] == fmt else geojson(ent)
            seen.add(kname)
        except CodecError as e:
            raise GenError("%s/%s: %s" % (fmt, fn, e))
        if got != vec["expect"]:
            raise GenError("%s/%s: convert gives %s, vector expects %s" % (fmt, fn, got, vec["expect"]))
        n += 1
    missing = {k.name for k in pack.kinds} - seen
    if missing:
        raise GenError("%s: kinds with no vector: %s" % (fmt, sorted(missing)[:5]))
    return n



# --------------------------------------------------------------- documents ---

def ident_text(ident):
    return " ".join("0x%02X" % b for b in ident)


def pack_md(cp, sha, tag, nvec):
    o = []
    a = o.append
    a("# Pack: %s" % cp.format)
    a("")
    a("u-blox UBX frames of the message class %s (0x%02X), from the message definitions" % (cp.cname, cp.cls))
    a("of `%s` (`%s/ubxtypes_get.py`, `ubxtypes_set.py`, `ubxtypes_poll.py`) at %s," % (REPO, PKG_DIR, tag))
    a("commit `%s`. Public. Generated by `tools/gen/ubx2pack.py`; do not edit" % sha)
    a("`pack.def`, this file, `PROVENANCE.md`, `model/%s.def` or the vectors by hand." % cp.module)
    a("")
    a("Status: Built. Generated and checked by the generator's own serializer and codec.")
    a("")
    a("## The message")
    a("")
    a("`wire bits`, `bit_order lsb`, `word_bytes 1`; hex text. One UBX frame without")
    a("its checksum; numbers are little-endian:")
    a("")
    a("| Bytes | Content | In the pack |")
    a("|---|---|---|")
    a("| 0-1 | sync characters 0xB5 0x62 | common `when` |")
    a("| 2 | class, 0x%02X | common `when` |" % cp.cls)
    a("| 3 | id | per-kind `when` |")
    a("| 4-5 | payload length in bytes | per-kind `when` = the definition's fixed length |")
    a("| 6 … | payload | the kind's `field` lines, at their offsets |")
    a("")
    a("The message is the frame without its checksum, in both directions: decode takes")
    a("the sync characters, header and payload, and encode writes them. A framer adds")
    a("the two checksum bytes before sending and checks them on receipt: an 8-bit")
    a("Fletcher checksum over class, id, length and payload (a running sum A of the")
    a("bytes and a running sum B of A, each modulo 256), written after the payload.")
    a("That is the item \"Layered wires and framing\" of `docs/roadmap.md`. A message")
    a("whose identity includes the first payload byte (the MGA messages) has a per-kind")
    a("`when` on that byte. Where the source chooses among definitions of one identity")
    a("by the value of one payload byte (`ubxvariants.py`: a version or type byte), the")
    a("kind it chooses that way has a `when` on that byte; the other definitions of the")
    a("identity are told apart by their length.")
    a("")
    a("## Messages")
    a("")
    a("A definition is the receiver's output (GET), a command to it (SET, kind suffix")
    a("`_set`) or a request (POLL, suffix `_poll`), as the source groups them.")
    a("")
    a("| Kind | Definition | Mode | Identity | Payload bytes |")
    a("|---|---|---|---|---|")
    for k in cp.kinds:
        a("| `%s` | %s | %s | %s | %d |" % (k.name, k.defname, k.mode, ident_text(k.ident), k.size))
    a("")
    a("## What is mapped")
    a("")
    a("| Definition type | Transform | Model type |")
    a("|---|---|---|")
    a("| `U1` … `U8`, `X1` … `X8`, `E1` … `E4`, `L` | `uint` | int |")
    a("| `I1` … `I8` | `twos` | int |")
    a("| `R4`, `R8` | `f32`, `f64` | float |")
    a("| `C<n>` (text of a fixed length) | `ascii` | string |")
    a("| an integer with a scale | `uscale` / `sscale` with the scale as an exact fraction | float |")
    a("| a bit field (`_bit`) | each named bit group as its own field, from the least significant bit | int |")
    a("| a group with a fixed repeat count (`_grp`) | its fields once per repeat, `_01`, `_02`, … appended | as the field |")
    a("| `A<n>` (a byte array) | one `uint` byte per element, `_01` … appended | int |")
    a("| an unsigned integer wider than 8 bytes | 8-byte `uint` parts, `_01` … appended, the last part shorter | int |")
    a("")
    a("Keys are `%s.<kind>_<field>` in lower case. A scale the source states is" % cp.module)
    a("applied; the source states no unit, so the module declares none (`-`).")
    if cp.scaled:
        a("")
        a("Scaled fields:")
        a("")
        a("| Kind | Field | Transform |")
        a("|---|---|---|")
        for k, f, tr in cp.scaled:
            a("| `%s` | `%s` | `%s` |" % (k, f, tr))
    a("")
    a("### Core keys")
    a("")
    if cp.core:
        a("pyubx2 states a scale for a field but rarely its unit or meaning. A field binds")
        a("a core or track key only where a public source shows both:")
        a("")
        if any(c[4] == "pyubx2 examples" for c in cp.core):
            a("- pyubx2 examples: in NAV-PVT, NAV-POSLLH and NAV-HPPOSLLH, and in the NAV2")
            a("  messages the source defines as those, `lat` and `lon` (signed 32-bit, scale")
            a("  1e-7) are written by the examples of the same commit as the latitude and")
            a("  longitude of GPX track points (`examples/gpxtracker.py`) and of SRID 4326")
            a("  points (`examples/ubx_spatialite.py`): WGS84 degrees. `height` is read as")
            a("  millimetres above the ellipsoid: the NAV-HPPOSLLH definition marks `height`")
            a("  and `hMSL` as millimetres, and `examples/gnssapp.py` derives the geoid")
            a("  separation in metres as their difference over 1000.")
        if any(c[4] != "pyubx2 examples" for c in cp.core):
            a("- ublox_msgs (`%s`, package `ublox_msgs`, commit `%s`, BSD;" % (UBLOX_MSGS_REPO, UBLOX_MSGS_COMMIT[:12]))
            a("  the commit the ros2-ublox-msgs pack uses): the .msg file of the message states")
            a("  the unit of the field in its comment, and says what the field is (the north,")
            a("  east or down velocity, the 2-D ground speed, the 2-D heading of motion, the")
            a("  latitude, longitude or height above the ellipsoid). The generator reads the")
            a("  file and binds a field only when the comment says so and states the unit the")
            a("  table below converts: mm/s or cm/s to m/s, 1e-5 degrees to degrees, 1e-7")
            a("  degrees to degrees, mm to m. Up is the negative of down. A heading of motion")
            a("  binds `course`, read as degrees from true north, as for a GNSS solution in a")
            a("  north-east-down frame.")
        a("")
        a("| Kind | Field | Key | Transform | Evidence |")
        a("|---|---|---|---|---|")
        for k, f, key, tr, ev in cp.core:
            a("| `%s` | `%s` | `%s` | `%s` | %s |" % (k, f, key, tr, ev))
        a("")
        if any(k.defname == "NAV-HPPOSLLH" for k in cp.kinds):
            a("In NAV-HPPOSLLH the high-precision parts (`_HPlat`, `_HPlon`, `_HPheight`) stay")
            a("raw keys; the core keys hold the standard-precision part (1e-7 degrees, 1 mm).")
            a("")
        a("Every other field stays a raw key, accuracies and times among them: the")
        a("sources above state no unit for it, or state one this pack does not convert.")
    else:
        a("No key is bound to a `core` or `track` key: no public source this pack reads")
        a("states the unit and meaning of a field of this class.")
    a("")
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own keys, so an entity from another format" % MAX_REQUIRES)
    a("selects a kind only when it holds them.")
    a("")
    a("## What is not mapped")
    a("")
    if cp.not_built:
        a("Definitions with no kind:")
        a("")
        a("| Definition | Mode | Identity | Reason |")
        a("|---|---|---|---|")
        for mode, d, ident, why in cp.not_built:
            a("| %s | %s | %s | %s |" % (d, mode, ident_text(ident), why))
        a("")
        var = sum(1 for _, _, _, w in cp.not_built if "repeated" in w or "end of the payload" in w
                  or "payload length gives" in w)
        if var:
            a("%d of them have a variable part: a group repeated by a count field or to the end" % var)
            a("of the payload, or text that runs to the end. Stating one needs a repeated group")
            a("counted by a field, or a trailing field of the remaining length.")
            a("")
        same = sum(1 for _, _, _, w in cp.not_built if w.startswith("the same class"))
        if same:
            a("%d have the class, id and length of a kind above; the source tells the" % same)
            a("variants apart by a version field or by the direction of the message, which a")
            a("`when` on the length alone cannot.")
            a("")
    a("- The checksum (see The message), and frames whose payload length is not the")
    a("  definition's fixed length: such a frame selects no kind (`no-kind`).")
    a("- Enumerations are carried as integers; the bits of a bit field that the")
    a("  definition does not name are not mapped.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-<class><id>-<kind>.json`: one same-format round trip per kind, the")
    a("frame written by a UBX serializer in the generator from sample values.")
    if any(k.mode == "GET" and k.defname == name for k in cp.kinds for name, _, _ in CROSS):
        a("")
        a("`vectors/x-*-to-geojson.json`: a frame converted to GeoJSON; the expected text")
        a("is written by hand from the field values.")
    a("")
    a("%d vectors." % nvec)
    return "\n".join(o) + "\n"


def provenance_md(cp, sha, tag, table):
    rows = ["# Provenance: %s" % cp.format,
            "",
            "| Fact | Value |",
            "|---|---|",
            "| repository | %s |" % REPO,
            "| tag | `%s` |" % tag,
            "| commit | `%s` |" % sha]
    for f in FILES:
        rows.append("| definition read | `%s/%s` (SHA-256 `%s`) |" % (PKG_DIR, f, table["%s/%s" % (PKG_DIR, f)]))
    rows += [
        "| license | %s: `LICENSE` at the root of the commit (SHA-256 `%s`), verbatim in `%s` |" % (
            LICENSE_LINE, table["LICENSE"], PROV),
        "| date read | 2026-11-19 |",
        "| what the pack takes | message names and identities; field names, types, scales, bit widths and repeat counts; no description text |",
        "| generator | `tools/gen/ubx2pack.py` |",
        ""]
    return "\n".join(rows)


def ublox_license_text(udir):
    """The licence of ublox_msgs as the package states it: the comment block at
    the top of src/ublox_msgs.cpp, and the license element of package.xml."""
    block = []
    for line in read_text(os.path.join(udir, "ublox_msgs/src/ublox_msgs.cpp")).splitlines():
        if not line.strip():
            block.append("")
            continue
        if not line.startswith("//"):
            break                      # the first line of code ends the comment
        text = line[3:] if line.startswith("// ") else line[2:]
        block.append("" if text and set(text) <= {"="} else text.rstrip())
    lic = re.search(r"<license>[^<]*</license>", read_text(os.path.join(udir, "ublox_msgs/package.xml")))
    if not lic:
        raise GenError("ublox_msgs/package.xml states no license")
    return "\n".join(l for l in block).strip("\n"), lic.group(0)


def write_sources_provenance(out, src, sha, tag, udir):
    lic = read_text(os.path.join(src, "LICENSE"))
    ulic, uxml = ublox_license_text(udir)
    o = ["# Provenance of the UBX inputs",
         "",
         "| Fact | Value |",
         "|---|---|",
         "| repository | %s |" % REPO,
         "| tag | `%s` |" % tag,
         "| commit | `%s` (the commit of the tag, read 2026-11-19) |" % sha,
         "| archive | `https://codeload.github.com/semuconsulting/pyubx2/tar.gz/%s` |" % sha,
         "| license | %s: the file `LICENSE` at the root of the commit, verbatim below |" % LICENSE_LINE,
         "",
         "The definition files say in their header that their content was taken from",
         "the public u-blox interface specifications (copyright u-blox AG). This",
         "repository reads only the definition files of pyubx2, never a u-blox",
         "document, and takes no description text from them.",
         "",
         "## Files",
         "",
         "| Path | SHA-256 |",
         "|---|---|",
         "| `LICENSE` | `%s` |" % sha256(os.path.join(src, "LICENSE"))]
    for f in FILES + ["../../examples/gpxtracker.py", "../../examples/ubx_spatialite.py",
                      "../../examples/gnssapp.py"]:
        rel = os.path.normpath("%s/%s" % (PKG_DIR, f))
        o.append("| `%s` | `%s` |" % (rel, sha256(os.path.join(src, rel))))
    o += ["", "## LICENSE", "", "```"] + lic.rstrip("\n").splitlines() + ["```", ""]
    o += ["## The units: ublox_msgs",
          "",
          "| Fact | Value |",
          "|---|---|",
          "| repository | %s (the package `ublox_msgs`) |" % UBLOX_MSGS_REPO,
          "| commit | `%s` (branch ros2; the commit `tools/gen/ros2-run.sh` uses for the ros2-ublox-msgs pack) |"
          % UBLOX_MSGS_COMMIT,
          "| files | `https://raw.githubusercontent.com/KumarRobotics/ublox/%s/<path>` |" % UBLOX_MSGS_COMMIT,
          "| license | BSD, as the package states it: `ublox_msgs/package.xml` holds `%s`, and the comment at the top of `ublox_msgs/src/ublox_msgs.cpp` holds the text below; the repository has no LICENSE file and the .msg files carry no licence header |" % uxml,
          "",
          "The generator reads the units of the fields it binds from these .msg files",
          "and binds a field only where the file states the unit; it takes no other",
          "text from them.",
          "",
          "| Path | SHA-256 |",
          "|---|---|"]
    for f in UBLOX_MSGS_FILES:
        o.append("| `ublox/%s` | `%s` |" % (f, sha256(os.path.join(udir, f))))
    o += ["", "### ublox_msgs/src/ublox_msgs.cpp, the licence comment", "", "```"] + ulic.splitlines() + ["```", ""]
    out.write(PROV, "\n".join(o))


def read_sources_provenance(text, src, udir):
    m = re.search(r"\| commit \| `([0-9a-f]{40})`", text)
    t = re.search(r"\| tag \| `([^`]+)`", text)
    if not m or not t:
        raise GenError("%s states no commit or tag" % PROV)
    table = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    for rel in ["LICENSE"] + ["%s/%s" % (PKG_DIR, f) for f in FILES] + ["ublox/" + f for f in UBLOX_MSGS_FILES]:
        if rel not in table:
            raise GenError("%s has no SHA-256 for %s" % (PROV, rel))
    for rel, digest in table.items():
        path = os.path.join(udir, rel[len("ublox/"):]) if rel.startswith("ublox/") else os.path.join(src, rel)
        if sha256(path) != digest:
            raise GenError("%s does not match the SHA-256 in %s" % (rel, PROV))
    return m.group(1), t.group(1), table


# -------------------------------------------------------------------- main ---

def run(args, out):
    src = args.src
    udir = args.ublox_msgs
    if args.commit:
        write_sources_provenance(out, src, args.commit, args.tag or "untagged", udir)
    sha, tag, table = read_sources_provenance(out.read(PROV), src, udir)
    units = {os.path.basename(f): read_msg_units(read_text(os.path.join(udir, f)))
             for f in UBLOX_MSGS_FILES if f.endswith(".msg")}
    source = Source(src, units)
    plans, orphans = plan(source)
    plans = [cp for cp in plans if cp.cname != "FOO"]          # the source's test class
    built = [cp for cp in plans if cp.kinds]
    core_text = read_text(args.core_def) if args.core_def else out.read("model/core.def")
    track_text = read_text(args.track_def) if args.track_def else out.read("model/track.def")
    total = 0
    for cp in built:
        pdir = "packs/" + cp.format
        out.write("model/%s.def" % cp.module, module_text(cp, sha, tag))
        out.write(pdir + "/pack.def", pack_text(cp, sha, tag))
        vecs = vector_files(cp)
        keep = {n for n, _ in vecs}
        for old in out.listdir(pdir + "/vectors"):
            if old.endswith(".json") and old not in keep:
                out.remove("%s/vectors/%s" % (pdir, old))
        for n, t in vecs:
            out.write("%s/vectors/%s" % (pdir, n), t)
        model = gtcheck.Model()
        model.add(core_text, "model/core.def")
        model.add(track_text, "model/track.def")
        model.add(out.read("model/%s.def" % cp.module), "model/%s.def" % cp.module)
        pack = gtcheck.load_pack(out.read(pdir + "/pack.def"), model, pdir + "/pack.def")
        total += check_vectors(pack, [(n, out.read("%s/vectors/%s" % (pdir, n))) for n, _ in vecs], cp.format)
        out.write(pdir + "/pack.md", pack_md(cp, sha, tag, len(vecs)))
        out.write(pdir + "/PROVENANCE.md", provenance_md(cp, sha, tag, table))
    nb = collections.Counter(re.sub(r"`[^`]*`", "`…`", w) for cp in plans for _, _, _, w in cp.not_built)
    return ["tag             %s (commit %s)" % (tag, sha),
            "classes         %d, packs %d%s" % (len(plans), len(built), "".join(
                "\nno pack         %s" % cp.cname for cp in plans if not cp.kinds)),
            "definitions     %d, kinds %d" % (sum(len(source.defs[m]) for m in source.defs),
                                              sum(len(cp.kinds) for cp in built)),
            "no identity     %s" % ", ".join("%s %s" % o for o in orphans),
            "field lines     %d" % sum(len(k.lines) for cp in built for k in cp.kinds),
            "scaled fields   %d" % sum(len(cp.scaled) for cp in built),
            "core bindings   %d" % sum(len(cp.core) for cp in built),
            "not built       %d %s" % (sum(nb.values()), dict(nb)),
            "vectors         %d checked" % total,
            "self-check      ok"]


def build_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(prog=NAME, description=__doc__.split("\n")[0] + " One pack per message "
                                 "class, one kind per definition of fixed length, the frame without its "
                                 "checksum.")
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("--src", required=True, metavar="DIR", help="a checkout of github.com/semuconsulting/pyubx2")
    ap.add_argument("--commit", help="write %s for this commit" % PROV)
    ap.add_argument("--tag", help="the tag of --commit, for the provenance file")
    ap.add_argument("--ublox-msgs", required=True, metavar="DIR",
                    help="the files of github.com/KumarRobotics/ublox at %s that state the units: %s"
                    % (UBLOX_MSGS_COMMIT[:12], ", ".join(UBLOX_MSGS_FILES)))
    ap.add_argument("--core-def", help="model/core.def (default <out>/model/core.def)")
    ap.add_argument("--track-def", help="model/track.def (default <out>/model/track.def)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = genio.Output(args.out, check=args.check)
    try:
        lines = run(args, out)
    except (GenError, gtcheck.CheckError, SyntaxError) as e:
        print("%s: %s" % (NAME, e), file=sys.stderr)
        return 1
    except OSError as e:
        print("%s: %s: %s" % (NAME, e.filename, e.strerror), file=sys.stderr)
        return 1
    print("\n".join(lines))
    return out.report(NAME)


if __name__ == "__main__":
    sys.exit(main())
