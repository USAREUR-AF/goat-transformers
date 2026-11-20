#!/usr/bin/env python3
"""Generate the goat-transformers pack of the Unicore UNI binary messages from
the message definitions of pyunigps (github.com/semuconsulting/pyunigps,
src/pyunigps/unitypes_core.py and unitypes_get.py).

Reads   <src>/src/pyunigps/unitypes_core.py, unitypes_get.py and <src>/LICENSE,
        as Python syntax trees: no file of the source is run;
        tools/gen/sources/unicore-PROVENANCE.md (the tag, commit and SHA-256 of
        every file; a file that differs is refused)
Writes  <out>/model/unicore.def                the module of the header and message keys
        <out>/packs/unicore/pack.def           one pack, one kind per message of fixed length
        <out>/packs/unicore/pack.md
        <out>/packs/unicore/PROVENANCE.md
        <out>/packs/unicore/vectors/*.json
        tools/gen/sources/unicore-PROVENANCE.md (only with --commit)

The message is one UNI binary frame without its three sync bytes and its
CRC-32: the 21-byte header (CPU idle, message ID, payload length, time
reference and status, week, time of week, version, reserved, leap seconds,
delay) and the payload, all little-endian. A kind is selected by the message
ID and the payload length.

Every vector's message is written by a serializer in this file from the
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

NAME = "uni2pack"
VERSION = "0.1.0"
REPO = "https://github.com/semuconsulting/pyunigps"
PROV = "tools/gen/sources/unicore-PROVENANCE.md"
PKG_DIR = "src/pyunigps"
FILES = ["unitypes_core.py", "unitypes_get.py"]
FORMAT = MODULE = "unicore"
SYNC = bytes([0xAA, 0x44, 0xB5])
# the header after the sync bytes: (field, bit position, bits), little-endian
HEADER = [("cpuidle", 0, 8), ("msgid", 8, 16), ("length", 24, 16), ("timeref", 40, 8),
          ("timestatus", 48, 8), ("wno", 56, 16), ("tow", 72, 32), ("version", 104, 32),
          ("reserved", 136, 8), ("leapsecond", 144, 8), ("delay", 152, 16)]
PAYLOAD_BIT0 = 168
MAX_REQUIRES = 3
GROUP_SAMPLE_ITEMS = 2
# Messages whose fields pyunigps decodes by rules in its code (unimessage.py)
# that the definition does not state: the pack would give those fields a
# different value, so the message gets no kind.
CODE_DECODED = {
    "OBSVMCMP": "pyunigps decodes three of its fields by rules in its code that the definition does not state "
                "(a lookup table for psrstd, 1 added to adrstd before its scale, 20 added to cno)",
}
LICENSE_LINE = "BSD 3-Clause, copyright (c) 2020 semuadin (Steve Smith)"
INT64_MAX = (1 << 63) - 1


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
# The definitions are Python dictionary literals, read with `ast`, never run.
# A name resolves to a module-level assignment; `**NAME` spreads a dictionary.
# A scale name states its value: E1_Nk is 10^-k, E1_Pk is 10^k, P2_Nk is 2^-k;
# a decimal number is read as the exact value of its digits.

Ref = collections.namedtuple("Ref", "name")


def scale_of_name(name):
    m = re.fullmatch(r"E1_([NP])(\d+)", name)
    if m:
        n = int(m.group(2))
        return Fraction(1, 10 ** n) if m.group(1) == "N" else Fraction(10 ** n)
    m = re.fullmatch(r"P2_([NP])(\d+)", name)
    if m:
        n = int(m.group(2))
        return Fraction(1, 2 ** n) if m.group(1) == "N" else Fraction(2 ** n)
    return None


def assignments(text, where):
    out = collections.OrderedDict()
    for st in ast.parse(text, where).body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            out[st.targets[0].id] = st.value
    return out


class Source:
    def __init__(self, src):
        base = os.path.join(src, PKG_DIR)
        core = assignments(read_text(os.path.join(base, "unitypes_core.py")), "unitypes_core.py")
        get = assignments(read_text(os.path.join(base, "unitypes_get.py")), "unitypes_get.py")
        self.names = collections.OrderedDict(core)
        for k, v in get.items():
            self.names.setdefault(k, v)
        self.consts = {k: v.value for k, v in core.items()
                       if isinstance(v, ast.Constant) and isinstance(v.value, (str, int, float))}
        if "UNI_MSGIDS" not in core:
            raise GenError("unitypes_core.py has no UNI_MSGIDS")
        self.numbers = {}                  # message name -> message ID
        for k, v in zip(core["UNI_MSGIDS"].keys, core["UNI_MSGIDS"].values):
            num, name = ast.literal_eval(k), ast.literal_eval(v)
            if name in self.numbers:
                raise GenError("message %s has two IDs" % name)
            self.numbers[name] = num
        if "UNI_PAYLOADS_GET" not in get:
            raise GenError("unitypes_get.py has no UNI_PAYLOADS_GET")
        self.messages = self.literal(get["UNI_PAYLOADS_GET"], "UNI_PAYLOADS_GET")

    def literal(self, node, where):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.consts:
                return Ref(node.id)
            if node.id in self.names:
                return self.literal(self.names[node.id], where)
            raise GenError("%s: unknown name %s" % (where, node.id))
        if isinstance(node, (ast.Tuple, ast.List)):
            return tuple(self.literal(e, where) for e in node.elts)
        if isinstance(node, ast.Dict):
            out = collections.OrderedDict()
            for k, v in zip(node.keys, node.values):
                if k is None:
                    spread = self.literal(v, where)
                    if not isinstance(spread, dict):
                        raise GenError("%s: a spread that is not a dictionary" % where)
                    out.update(spread)
                else:
                    kk = self.literal(k, where)
                    out[kk.name if isinstance(kk, Ref) else kk] = self.literal(v, where)
            return out
        raise GenError("%s: an expression the generator does not read (line %d)" % (where, node.lineno))

    def type_name(self, v):
        if isinstance(v, Ref):
            return str(self.consts[v.name])
        return v

    def exact(self, v, where):
        if isinstance(v, Ref):
            f = scale_of_name(v.name)
            if f is None:
                raise GenError("%s: scale name %s" % (where, v.name))
            return f
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise GenError("%s: scale %r" % (where, v))
        return Fraction(v) if isinstance(v, int) else Fraction(Decimal(repr(v)))


# ------------------------------------------------------------------- plan ---

class Variable(Exception):
    """A part of the block whose length is not fixed, or a form the pack does not state."""


Leaf = collections.namedtuple("Leaf", "name kind bitpos bits scale")


def width(ty):
    m = re.fullmatch(r"[USXRC](\d+)", ty)
    return int(m.group(1)) if m else None


def unpack_type(src, v, where):
    if isinstance(v, tuple) and len(v) == 2 and not isinstance(v[1], dict):
        return src.type_name(v[0]), src.exact(v[1], where)
    if isinstance(v, (Ref, str)):
        return src.type_name(v), None
    raise GenError("%s: a field value the generator does not read" % where)


def flatten(src, defn, bitpos, where, leaves):
    """Append the leaves of `defn` from body bit `bitpos`; the bit after them."""
    for key, v in defn.items():
        if key.endswith("_bit") or (isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], Ref)
                                    and isinstance(v[1], dict) and str(src.type_name(v[0])).startswith("X")):
            ty, _ = unpack_type(src, v[0], where)
            size = width(ty)
            if not ty.startswith("X") or size is None:
                raise GenError("%s: bit field %s of type %s" % (where, key, ty))
            pos = bitpos
            for sub, sv in v[1].items():
                sty, scale = unpack_type(src, sv, where)
                n = width(sty)
                if sty[0] not in "USX" or not n:
                    raise GenError("%s: bit %s of type %s" % (where, sub, sty))
                leaves.append(Leaf(sub, "s" if sty[0] == "S" else "u", pos, n, scale))
                pos += n
            if pos > bitpos + 8 * size:
                raise GenError("%s: the bits of %s exceed its %d bytes" % (where, key, size))
            bitpos += 8 * size
        elif isinstance(v, tuple) and len(v) == 2 and isinstance(v[1], dict):
            spec = v[0]
            if isinstance(spec, Ref):
                spec = src.type_name(spec)     # a named count, such as FREQNO
            if isinstance(spec, tuple):
                raise Variable("a part present only when field `%s` is %r" % spec)
            if isinstance(spec, int) and not isinstance(spec, bool):
                for i in range(1, spec + 1):
                    sub = []
                    bitpos = flatten(src, v[1], bitpos, where, sub)
                    leaves.extend(l._replace(name="%s_%02d" % (l.name, i)) for l in sub)
                continue
            if spec == src.consts.get("FREQNO"):
                raise Variable("a group whose count pyunigps computes from other fields")
            if spec == "None" or spec is None:
                raise Variable("a group repeated to the end of the payload")
            raise Variable("a group repeated by field `%s`" % spec)
        else:
            ty, scale = unpack_type(src, v, where)
            n = width(ty)
            if n is None:
                raise Variable("a field of type %s whose length the payload length gives" % ty)
            if ty[0] == "C":
                if n > 255:
                    raise GenError("%s: text of %d bytes" % (where, n))
                leaves.append(Leaf(key, "ascii", bitpos, 8 * n, None))
                bitpos += 8 * n
            elif ty[0] == "R":
                if n not in (4, 8):
                    raise GenError("%s: float %s" % (where, ty))
                leaves.append(Leaf(key, "f32" if n == 4 else "f64", bitpos, 8 * n, scale))
                bitpos += 8 * n
            elif n > 8:
                if scale is not None:
                    raise GenError("%s: a scaled field of %d bytes" % (where, n))
                for i, off in enumerate(range(0, n, 8), 1):
                    k = min(8, n - off)
                    leaves.append(Leaf("%s_%02d" % (key, i), "u", bitpos, 8 * k, None))
                    bitpos += 8 * k
            else:
                leaves.append(Leaf(key, "s" if ty[0] == "S" else "u", bitpos, 8 * n, scale))
                bitpos += 8 * n
    return bitpos


def slug(text):
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(text))
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s if s and not s[0].isdigit() else "x" + s


def factor_text(f):
    """`num/den` when both fit a signed 64-bit integer, else exact decimal text."""
    if abs(f.numerator) <= INT64_MAX and f.denominator <= INT64_MAX:
        return str(f.numerator) if f.denominator == 1 else "%d/%d" % (f.numerator, f.denominator)
    den, twos, fives = f.denominator, 0, 0
    while den % 2 == 0:
        den, twos = den // 2, twos + 1
    while den % 5 == 0:
        den, fives = den // 5, fives + 1
    if den != 1:
        raise GenError("scale %s has no exact decimal text" % f)
    places = max(twos, fives)
    digits = str(abs(f.numerator) * 10 ** places // f.denominator).rjust(places + 1, "0")
    whole, frac = digits[:len(digits) - places], digits[len(digits) - places:].rstrip("0")
    return ("-" if f.numerator < 0 else "") + whole + ("." + frac if frac else "")


Line = collections.namedtuple("Line", "key pos bits tr leaf")


class KindPlan:
    def __init__(self, name, msg, num, size, lines, group=None):
        self.name, self.msg, self.num, self.size, self.lines = name, msg, num, size, lines
        self.group = group             # a Group when the payload ends in a counted group, size then None
        self.requires = []


Group = collections.namedtuple("Group", "key name start item_bits count_pos count_bits lines")


def tail_group(src, defn, where):
    """When the definition ends in a group counted by an unsigned field before
    it, and both the part before and one item have a fixed layout: (head leaves,
    the bit after them, group name, the count leaf, item leaves, item bits).
    None when the definition does not end in such a group; Variable with the
    reason when it does but the pack cannot state it."""
    items = list(defn.items())
    if not items:
        return None
    gname, v = items[-1]
    if gname.endswith("_bit") or not (isinstance(v, tuple) and len(v) == 2 and isinstance(v[1], dict)):
        return None
    count = src.type_name(v[0]) if isinstance(v[0], Ref) else v[0]
    if not isinstance(count, str) or count == "None" or count == src.consts.get("FREQNO"):
        return None
    head = collections.OrderedDict(items[:-1])
    leaves = []
    nbits = flatten(src, head, PAYLOAD_BIT0, where, leaves)
    found = [l for l in leaves if l.name == count]
    if len(found) != 1 or found[0].kind != "u" or found[0].scale is not None:
        raise Variable("a group counted by `%s`, which is not one unsigned field before it" % count)
    body = []
    try:
        ibits = flatten(src, v[1], 0, where, body)
    except Variable as e:
        raise Variable("a group counted by field `%s` whose items vary: %s" % (count, e))
    if not body:
        raise Variable("a group counted by field `%s` with empty items" % count)
    return leaves, nbits, gname, found[0], body, ibits


def transform_of(leaf):
    """(transform, model type, scaled) of a leaf."""
    if leaf.kind == "ascii":
        return "ascii", "string", False
    if leaf.kind in ("f32", "f64") and leaf.scale not in (None, 1):
        return "%sscale:%s" % (leaf.kind, factor_text(leaf.scale)), "float", True
    if leaf.kind in ("f32", "f64"):
        return leaf.kind, "float", False
    if leaf.scale is not None and leaf.scale != 1:
        if leaf.scale.denominator == 1:
            return ("siscale:" if leaf.kind == "s" else "uiscale:") + factor_text(leaf.scale), "int", True
        return ("sscale:" if leaf.kind == "s" else "uscale:") + factor_text(leaf.scale), "float", True
    return ("twos" if leaf.kind == "s" else "uint"), "int", False


class Plan:
    def __init__(self, src):
        self.kinds, self.keys, self.lists = [], collections.OrderedDict(), collections.OrderedDict()
        self.not_built = []            # (message, ID, reason)
        self.scaled = []
        for f, _, _ in HEADER:
            if f not in ("msgid", "length"):
                self.keys["header_" + f] = ("int", "header", f)
        for msg, defn in src.messages.items():
            if not isinstance(defn, dict):
                raise GenError("%s: not a dictionary" % msg)
            self.add(src, msg, defn)
        # a kind with a counted group has no length `when`: it goes after the
        # fixed-length kinds, which select first
        self.kinds = [k for k in self.kinds if not k.group] + [k for k in self.kinds if k.group]
        own = MODULE + "."
        usage = collections.Counter(l.key for k in self.kinds for l in k.lines)
        for k in self.kinds:
            raw = [l.key for l in k.lines if l.key.startswith(own) and l.leaf is not None]
            ranked = sorted(range(len(raw)), key=lambda i: (usage[raw[i]], i))
            k.requires = [raw[i] for i in sorted(ranked[:MAX_REQUIRES])]

    def leaf_lines(self, prefix, leaves, msg, where_kind, skip=None):
        lines, seen = [], set()
        for leaf in leaves:
            if leaf is skip:
                continue
            base = "%s_%s" % (prefix, slug(leaf.name))
            name, n = base, 2
            while name in seen:
                name, n = "%s_%d" % (base, n), n + 1
            seen.add(name)
            tr, typ, scaled = transform_of(leaf)
            if scaled:
                self.scaled.append((where_kind, leaf.name, tr))
            if name in self.keys or name in self.lists:
                raise GenError("%s: key %s twice" % (msg, name))
            self.keys[name] = (typ, msg, leaf.name)
            lines.append(Line("%s.%s" % (MODULE, name), leaf.bitpos, leaf.bits, tr, leaf))
        return lines

    def add(self, src, msg, defn):
        num = src.numbers.get(msg)
        if num is None:
            self.not_built.append((msg, None, "no message ID in UNI_MSGIDS"))
            return
        if msg in CODE_DECODED:
            self.not_built.append((msg, num, CODE_DECODED[msg]))
            return
        leaves, group = [], None
        try:
            nbits = flatten(src, defn, PAYLOAD_BIT0, msg, leaves)
        except Variable as e:
            try:
                tail = tail_group(src, defn, msg)
            except Variable as e2:
                self.not_built.append((msg, num, str(e2)))
                return
            if tail is None:
                self.not_built.append((msg, num, str(e)))
                return
            leaves, nbits, gname, count_leaf, body, ibits = tail
            group = (gname, count_leaf, body, ibits)
        if not leaves:
            self.not_built.append((msg, num, "an empty payload: a kind needs at least one field"))
            return
        size = (nbits - PAYLOAD_BIT0) // 8
        if size > 0xFFFF:
            raise GenError("%s: payload of %d bytes" % (msg, size))
        kind = slug(msg)
        if any(k.name == kind for k in self.kinds):
            raise GenError("two messages give the kind %s" % kind)
        if group is None:
            for k in self.kinds:
                if k.num == num and k.size == size:
                    self.not_built.append((msg, num, "the same ID and payload length as kind `%s`" % k.name))
                    return
        lines = self.leaf_lines(kind, leaves, msg, kind, skip=group[1] if group else None)
        g = None
        if group:
            gname, count_leaf, body, ibits = group
            lname = "%s_%s" % (kind, slug(gname[:-4] if gname.endswith("_grp") else gname))
            if lname in self.keys or lname in self.lists:
                raise GenError("%s: list %s collides with a key" % (msg, lname))
            self.lists[lname] = "message %s, the items of group %s, counted by field %s" % (msg, gname, count_leaf.name)
            ilines = self.leaf_lines(lname, body, msg, kind)
            g = Group(MODULE + "." + lname, gname, nbits, ibits, count_leaf.bitpos, count_leaf.bits, ilines)
            self.keys.setdefault("payload_length", ("int", "header", "length, as the message states it"))
            lines.insert(0, Line(MODULE + ".payload_length", 24, 16, "uint", None))
            size = None
        self.kinds.append(KindPlan(kind, msg, num, size, lines, g))


# ------------------------------------------------------------------- emit ---

def loc(pos, n):
    return "0:%d:%d" % (pos, n)


def source_line(tag, sha):
    return 'source        "%s %s/unitypes_get.py at %s (commit %s)"' % (REPO, PKG_DIR, tag, sha)


def pack_text(plan, sha, tag):
    o = ["# Unicore UNI binary messages, one kind per message of fixed length.",
         "# Generated by tools/gen/uni2pack.py; do not edit by hand.",
         "# The message is one frame without its 3 sync bytes and its CRC-32: the",
         "# 21-byte header, then the payload. Payload bit 0 is bit %d." % PAYLOAD_BIT0,
         "format        %s" % FORMAT,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(tag, sha),
         "uses          %s" % MODULE,
         "wire          bits",
         "bit_order     lsb",
         "word_bytes    1"]
    for f, pos, n in HEADER:
        if f not in ("msgid", "length"):
            o.append("field  %s.header_%s %s uint" % (MODULE, f, loc(pos, n)))
    for k in plan.kinds:
        o.append("")
        o.append("kind      %s" % k.name)
        o.append("when      %s %d" % (loc(8, 16), k.num))
        if k.size is not None:
            o.append("when      %s %d" % (loc(24, 16), k.size))
        if k.requires:
            o.append("requires  %s" % " ".join(k.requires))
        for l in k.lines:
            o.append("field     %s %s %s" % (l.key, loc(l.pos, l.bits), l.tr))
        if k.group:
            g = k.group
            o.append("group     %s 0:%d item %d count %s" % (g.key, g.start, g.item_bits, loc(g.count_pos, g.count_bits)))
            for l in g.lines:
                o.append("  field   %s %s %s" % (l.key, loc(l.pos, l.bits), l.tr))
            o.append("end")
    return "\n".join(o) + "\n"


def module_text(plan, sha, tag):
    o = ["# The unicore module: the header and payload fields of the Unicore UNI",
         "# binary messages. Generated by tools/gen/uni2pack.py; do not edit by hand.",
         "# A key is header_<field> or <message>_<field> in lower case; a scale the",
         "# definition states is applied; the source states no unit, so none is declared.",
         "module        %s" % MODULE,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(tag, sha)]
    for name, (typ, msg, fname) in plan.keys.items():
        what = "UNI frame header: field %s" % fname if msg == "header" else "message %s, field %s" % (msg, fname)
        o.append('key  %s  %s  -  "%s"' % (name, typ, what))
    for name, what in plan.lists.items():
        o.append('list  %s  "%s"' % (name, what))
    return "\n".join(o) + "\n"


# ------------------------------------------------- serializer (vectors) ---

def crc32(data):
    """The UNI frame CRC: CRC-32 (reflected polynomial 0xEDB88320, initial value 0,
    no final XOR) over the sync bytes, the header and the payload; for the scratch
    cross-check and the tests."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
    return crc


def raw_of(leaf, value):
    if leaf.kind in ("u", "s"):
        return value & ((1 << leaf.bits) - 1)
    if leaf.kind == "f32":
        return int.from_bytes(struct.pack("<f", value), "little")
    if leaf.kind == "f64":
        return int.from_bytes(struct.pack("<d", value), "little")
    return int.from_bytes(value.encode("ascii").ljust(leaf.bits // 8, b"\0"), "little")


def message_bytes(k, header, values, items=()):
    if k.group:
        g = k.group
        size = (g.start - PAYLOAD_BIT0 + len(items) * g.item_bits + 7) // 8
    else:
        size = k.size
    acc = (k.num << 8) | (size << 24)
    for f, pos, n in HEADER:
        if f not in ("msgid", "length"):
            acc |= (header[f] & ((1 << n) - 1)) << pos
    for l in k.lines:
        if l.leaf is not None:
            acc |= raw_of(l.leaf, values[l.leaf.name]) << l.pos
    if k.group:
        g = k.group
        acc |= len(items) << g.count_pos
        for i, item in enumerate(items):
            for l in g.lines:
                acc |= raw_of(l.leaf, item[l.leaf.name]) << (g.start + i * g.item_bits + l.pos)
    return acc.to_bytes(PAYLOAD_BIT0 // 8 + size, "little")


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


def vector_text(pairs):
    return json.dumps(collections.OrderedDict(pairs), indent=2) + "\n"


def vector_files(plan):
    files = []
    for i, k in enumerate(plan.kinds):
        header = {f: (k.num * 13 + j * 29 + 7) % (1 << min(n, 31)) for j, (f, _, n) in enumerate(HEADER)}
        values = {l.leaf.name: sample(l.leaf, k.num * 31 + j * 7 + 3) for j, l in enumerate(k.lines) if l.leaf}
        cases = [("", ())]
        if k.group:
            items = [{l.leaf.name: sample(l.leaf, k.num * 17 + 101 * (n + 1) + 5 * j) for j, l in enumerate(k.group.lines)}
                     for n in range(GROUP_SAMPLE_ITEMS)]
            cases = [("", items), ("-no-items", ())]
        for suffix, items in cases:
            data = message_bytes(k, header, values, items).hex()
            model = collections.OrderedDict([("@kind", k.name)])
            if k.group:
                model[k.group.key + ".#"] = str(len(items))
            files.append(("rt-%05d-%s%s.json" % (k.num, k.name, suffix), vector_text([
                ("name", "%s-roundtrip-%s%s" % (FORMAT, k.name, suffix)), ("from", FORMAT), ("to", FORMAT),
                ("input", data), ("expect", data), ("model", model)])))
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


def exact_factor(text):
    m = re.fullmatch(r"(-?\d+)/(\d+)", text)
    return Fraction(int(m.group(1)), int(m.group(2))) if m else Fraction(Decimal(text))


def round_half_away(q):
    r = math.floor(abs(q) + Fraction(1, 2))
    return r if q >= 0 else -r


def decode_value(node, raw):
    tr, n = node.tr, node.bits
    if tr in ("uiscale", "siscale"):
        v = raw - (1 << n) if tr == "siscale" and raw >> (n - 1) else raw
        return int(round_half_away(v * exact_factor(node.targs[0])))
    if tr == "uint":
        return raw - (1 << 64) if n == 64 and raw >> 63 else raw
    if tr == "twos":
        return raw - (1 << n) if raw >> (n - 1) else raw
    if tr in ("uscale", "sscale"):
        if tr == "sscale" and raw >> (n - 1):
            raw -= 1 << n
        f = gtcheck.parse_factor(node.targs[0])
        return raw * float(f[0]) / float(f[1]) if isinstance(f, tuple) else raw * f
    if tr in ("f32", "f64", "f32scale", "f64scale"):
        v = struct.unpack("<f" if tr.startswith("f32") else "<d", raw.to_bytes(n // 8, "little"))[0]
        if tr.endswith("scale"):
            f = gtcheck.parse_factor(node.targs[0])
            v = v * f[0] / f[1] if isinstance(f, tuple) else v * f
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
    if tr in ("uiscale", "siscale"):
        r = int(round_half_away(Fraction(x) / exact_factor(node.targs[0])))
        lo, hi = (0, mask) if tr == "uiscale" else (-(1 << (n - 1)), (1 << (n - 1)) - 1)
        if not lo <= r <= hi:
            raise CodecError("transform-encode")
        return r & mask
    if tr in ("uint", "twos"):
        return x & mask
    if tr in ("uscale", "sscale"):
        f = gtcheck.parse_factor(node.targs[0])
        r = round_away(x * float(f[1]) / float(f[0]) if isinstance(f, tuple) else x / f)
        lo, hi = (0, mask) if tr == "uscale" else (-(1 << (n - 1)), (1 << (n - 1)) - 1)
        if not lo <= r <= hi:
            raise CodecError("transform-encode")
        return r & mask
    if tr in ("f32scale", "f64scale"):
        f = gtcheck.parse_factor(node.targs[0])
        x = x * f[1] / f[0] if isinstance(f, tuple) else x / f
        tr = tr[:3]
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
    ent, lists = collections.OrderedDict(), collections.OrderedDict()
    for n in lines:
        if n.d == "field":
            ent[n.key] = decode_value(n, get_bits(data, n.start, n.bits))
        elif n.d == "group":
            # a group counted by a field of the message (0.7): `count` items of
            # `item` bits from `start`, the count read at its locator as unsigned
            count = get_bits(data, n.count[0], n.count[1])
            if 8 * len(data) < n.start + count * n.item:
                raise CodecError("malformed-wire")
            items = []
            for i in range(count):
                base = n.start + i * n.item
                items.append(collections.OrderedDict(
                    (f.key, decode_value(f, get_bits(data, base + f.start, f.bits))) for f in n.body if f.d == "field"))
            lists[n.key] = items
    if lists:
        ent["@lists"] = lists
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
    end = max(n.start + n.bits for n in lines if n.d in ("when", "field", "const"))
    for n in lines:
        if n.d == "group":
            items = ent.get("@lists", {}).get(n.key, [])
            if len(items) >> n.count[1]:
                raise CodecError("transform-encode")
            acc = (acc & ~(((1 << n.count[1]) - 1) << n.count[0])) | (len(items) << n.count[0])
            for i, item in enumerate(items):
                base = n.start + i * n.item
                for f in n.body:
                    if f.d == "field" and f.key in item:
                        acc |= encode_value(f, item[f.key]) << (base + f.start)
            end = max(end, n.start + len(items) * n.item)
    nbytes = (end + 7) // 8
    return acc.to_bytes(nbytes, "little")


def check_vectors(pack, vectors, fmt):
    n, seen = 0, set()
    for fn, text in vectors:
        vec = json.loads(text)
        try:
            kname, ent = decode(pack, bytes.fromhex(vec["input"]))
            for key, want in vec.get("model", {}).items():
                if key.endswith(".#"):
                    got = str(len(ent.get("@lists", {}).get(key[:-2], [])))
                else:
                    got = kname if key == "@kind" else ent.get(key)
                if got is None:
                    raise GenError("%s/%s: model %s not decoded" % (fmt, fn, key))
                if key != "@kind" and isinstance(got, float):
                    if abs(got - float(want)) > 1e-9:
                        raise GenError("%s/%s: model %s" % (fmt, fn, key))
                elif str(got) != want:
                    raise GenError("%s/%s: model %s = %s, vector says %s" % (fmt, fn, key, got, want))
            got = encode(pack, kname, ent).hex()
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

def pack_md(plan, sha, tag, nvec):
    o = []
    a = o.append
    a("# Pack: %s" % FORMAT)
    a("")
    a("Unicore UNI binary messages, one kind per message of fixed length, from the")
    a("message definitions of `%s` (`%s/unitypes_get.py`) at %s, commit `%s`." % (REPO, PKG_DIR, tag, sha))
    a("Public. Generated by `tools/gen/uni2pack.py`; do not edit `pack.def`, this file,")
    a("`PROVENANCE.md`, `model/%s.def` or the vectors by hand." % MODULE)
    a("")
    a("Status: Built. Generated and checked by the generator's own serializer and codec.")
    a("")
    a("No Unicore document was read: the definitions are pyunigps's BSD-licensed")
    a("restatement, read as Python syntax trees.")
    a("")
    a("## The message")
    a("")
    a("`wire bits`, `bit_order lsb`, `word_bytes 1`; hex text. One UNI binary frame")
    a("without its sync bytes (0xAA 0x44 0xB5) and its CRC-32; every number is")
    a("little-endian. The header is 21 bytes:")
    a("")
    a("| Bytes | Field | In the pack |")
    a("|---|---|---|")
    a("| 0 | CPU idle | `unicore.header_cpuidle` |")
    a("| 1-2 | message ID | per-kind `when` |")
    a("| 3-4 | payload length in bytes | per-kind `when` |")
    a("| 5, 6 | time reference, time status | `unicore.header_timeref`, `unicore.header_timestatus` |")
    a("| 7-8, 9-12 | week, time of week | `unicore.header_wno`, `unicore.header_tow` |")
    a("| 13-16, 17, 18, 19-20 | version, reserved, leap seconds, delay | `unicore.header_*` |")
    a("| 21 … | payload | the kind's `field` lines |")
    a("")
    a("A framer adds the sync bytes and the CRC before sending and checks them on")
    a("receipt: CRC-32 (reflected polynomial 0xEDB88320, initial value 0) over the")
    a("sync bytes, the header and the payload, written little-endian after the")
    a("payload. That is the item \"Layered wires and framing\" of `docs/roadmap.md`.")
    a("")
    a("## Messages")
    a("")
    a("| Kind | Message | ID | Payload bytes |")
    a("|---|---|---|---|")
    for k in plan.kinds:
        a("| `%s` | %s | %d | %s |" % (k.name, k.msg, k.num, k.size if k.size is not None else
                                        "%d + %d per item of `%s`" % ((k.group.start - PAYLOAD_BIT0) // 8,
                                                                      k.group.item_bits // 8, k.group.key)))
    a("")
    a("## What is mapped")
    a("")
    a("| Definition type | Transform | Model type |")
    a("|---|---|---|")
    a("| `U1` … `U8` | `uint` | int |")
    a("| `S1` … `S8` | `twos` | int |")
    a("| `R4`, `R8` | `f32`, `f64`; with a scale `f32scale`, `f64scale` | float |")
    a("| `C<n>` (text of a fixed length) | `ascii` | string |")
    a("| an integer with a scale | `uscale` / `sscale` with the scale as an exact fraction | float |")
    a("| a bit field (`_bit`) | each named bit group as its own field, from the least significant bit | int |")
    a("| a group with a fixed repeat count | its fields once per repeat, `_01`, `_02`, … appended | as the field |")
    a("| an unsigned integer or byte field wider than 8 bytes | 8-byte `uint` parts, `_01` … appended | int |")
    a("| a group repeated by an unsigned field before it, ending the payload | a `group` of `item` bits counted by that field (`count <locator>`); the field has no key of its own | a list |")
    a("")
    a("Keys are `%s.<message>_<field>` in lower case. A scale the source states is" % MODULE)
    a("applied; the source states no unit, so the module declares none (`-`).")
    if plan.scaled:
        a("")
        a("Scaled fields:")
        a("")
        a("| Kind | Field | Transform |")
        a("|---|---|---|")
        for k, f, tr in plan.scaled:
            a("| `%s` | `%s` | `%s` |" % (k, f, tr))
    a("")
    a("### Core keys")
    a("")
    a("None. The position messages (BESTNAV and the others like it) carry `lat` and")
    a("`lon` as doubles that pyunigps's own README treats as degrees, and a `datumid`")
    a("field that names the datum of each message. The source does not say which")
    a("`datumid` value is WGS 84, so no message can be shown to hold WGS 84")
    a("coordinates; binding `lat` and `lon` would need that value, and then a gate")
    a("(Version 0.17, `if <locator> <value>`) on `datumid`. The height these messages")
    a("give is above mean sea level (`hmsl`), not the ellipsoid, so it would not bind")
    a("`hae` either.")
    a("")
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own keys, so an entity from another format" % MAX_REQUIRES)
    a("selects a kind only when it holds them.")
    a("")
    a("## What is not mapped")
    a("")
    if plan.not_built:
        a("| Message | ID | Reason |")
        a("|---|---|---|")
        for m, num, why in plan.not_built:
            a("| %s | %s | %s |" % (m, "-" if num is None else num, why))
        a("")
    if any(k.group for k in plan.kinds):
        a("A kind with a counted group has no length `when`: encode writes")
        a("`unicore.payload_length` as the entity holds it, so a message encoded from")
        a("another format needs it set (a length derived from the items is not in the")
        a("pack language). Such kinds come after the fixed-length kinds.")
        a("")
    a("- A message whose length varies otherwise: a group that does not end the")
    a("  payload, a group whose items vary, a group repeated to the end of the")
    a("  payload, or text whose length the payload length gives.")
    a("- The sync bytes and the CRC (see The message).")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-<ID>-<kind>.json`: one same-format round trip per kind, the frame")
    a("written by a serializer in the generator from sample values; a kind with a")
    a("counted group has one with two items and one with none (`-no-items`).")
    a("")
    a("%d vectors." % nvec)
    return "\n".join(o) + "\n"


def provenance_md(sha, tag, table):
    rows = ["# Provenance: %s" % FORMAT, "",
            "| Fact | Value |", "|---|---|",
            "| repository | %s |" % REPO,
            "| tag | `%s` |" % tag,
            "| commit | `%s` |" % sha]
    for f in FILES:
        rows.append("| definition read | `%s/%s` (SHA-256 `%s`) |" % (PKG_DIR, f, table["%s/%s" % (PKG_DIR, f)]))
    rows += ["| license | %s: `LICENSE` at the root of the commit (SHA-256 `%s`), verbatim in `%s` |" % (
                 LICENSE_LINE, table["LICENSE"], PROV),
             "| date read | 2026-11-19 |",
             "| what the pack takes | message names and IDs; field names, types, scales and bit widths; no description text |",
             "| generator | `tools/gen/uni2pack.py` |", ""]
    return "\n".join(rows)


def write_sources_provenance(out, src, sha, tag):
    lic = read_text(os.path.join(src, "LICENSE"))
    o = ["# Provenance of the Unicore inputs", "",
         "| Fact | Value |", "|---|---|",
         "| repository | %s |" % REPO,
         "| tag | `%s` |" % tag,
         "| commit | `%s` (the commit of the tag, read 2026-11-19) |" % sha,
         "| archive | `https://codeload.github.com/semuconsulting/pyunigps/tar.gz/%s` |" % sha,
         "| license | %s: the file `LICENSE` at the root of the commit, verbatim below |" % LICENSE_LINE,
         "",
         "The definition files say in their header that their content was taken from",
         "a Unicore reference manual (copyright Unicore). This repository reads only",
         "the definition files of pyunigps, never a Unicore document, and takes no",
         "description text from them.",
         "",
         "## Files", "",
         "| Path | SHA-256 |", "|---|---|",
         "| `LICENSE` | `%s` |" % sha256(os.path.join(src, "LICENSE"))]
    for f in FILES:
        rel = "%s/%s" % (PKG_DIR, f)
        o.append("| `%s` | `%s` |" % (rel, sha256(os.path.join(src, rel))))
    o += ["", "## LICENSE", "", "```"] + lic.rstrip("\n").splitlines() + ["```", ""]
    out.write(PROV, "\n".join(o))


def read_sources_provenance(text, src):
    m = re.search(r"\| commit \| `([0-9a-f]{40})`", text)
    t = re.search(r"\| tag \| `([^`]+)`", text)
    if not m or not t:
        raise GenError("%s states no commit or tag" % PROV)
    table = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    for rel in ["LICENSE"] + ["%s/%s" % (PKG_DIR, f) for f in FILES]:
        if rel not in table:
            raise GenError("%s has no SHA-256 for %s" % (PROV, rel))
        if sha256(os.path.join(src, rel)) != table[rel]:
            raise GenError("%s does not match the SHA-256 in %s" % (rel, PROV))
    return m.group(1), t.group(1), table


# -------------------------------------------------------------------- main ---

def run(args, out):
    if args.commit:
        write_sources_provenance(out, args.src, args.commit, args.tag or "untagged")
    sha, tag, table = read_sources_provenance(out.read(PROV), args.src)
    plan = Plan(Source(args.src))
    pdir = "packs/" + FORMAT
    out.write("model/%s.def" % MODULE, module_text(plan, sha, tag))
    out.write(pdir + "/pack.def", pack_text(plan, sha, tag))
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
    total = check_vectors(pack, [(n, out.read("%s/vectors/%s" % (pdir, n))) for n, _ in vecs], FORMAT)
    out.write(pdir + "/pack.md", pack_md(plan, sha, tag, len(vecs)))
    out.write(pdir + "/PROVENANCE.md", provenance_md(sha, tag, table))
    reasons = collections.Counter(re.sub(r"`[^`]*`|\d+", "…", w) for _, _, w in plan.not_built)
    return ["tag             %s (commit %s)" % (tag, sha),
            "messages        %d, kinds %d" % (len(plan.kinds) + len(plan.not_built), len(plan.kinds)),
            "not built       %d" % len(plan.not_built)] + ["  %3d  %s" % (n, w) for w, n in reasons.most_common()] + [
            "field lines     %d" % sum(len(k.lines) for k in plan.kinds),
            "vectors         %d checked" % total,
            "self-check      ok"]


def build_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(prog=NAME, description=__doc__.split("\n")[0])
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("--src", required=True, metavar="DIR", help="a checkout of %s" % REPO)
    ap.add_argument("--commit", help="write %s for this commit" % PROV)
    ap.add_argument("--tag", help="the tag of --commit, for the provenance file")
    ap.add_argument("--core-def", help="model/core.def (default <out>/model/core.def)")
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
