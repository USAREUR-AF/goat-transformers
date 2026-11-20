#!/usr/bin/env python3
"""Generate goat-transformers packs from the Septentrio Binary Format (SBF)
block definitions of pysbf2 (github.com/semuconsulting/pysbf2,
src/pysbf2/sbftypes_core.py and sbftypes_blocks.py).

Reads   <src>/src/pysbf2/sbftypes_core.py, sbftypes_blocks.py and <src>/LICENSE,
        as Python syntax trees: no file of the source is run;
        tools/gen/sources/sbf-PROVENANCE.md (the tag, commit and SHA-256 of every
        file; a file that differs is refused)
Writes  <out>/model/sbf.def                    the block-header key `revision`
        <out>/model/sbf<group>.def             one module per block group
        <out>/packs/sbf-<group>/pack.def       one pack per block group of the source,
        <out>/packs/sbf-<group>/pack.md        one kind per block of fixed length
        <out>/packs/sbf-<group>/PROVENANCE.md
        <out>/packs/sbf-<group>/vectors/*.json
        tools/gen/sources/sbf-PROVENANCE.md   (only with --commit)

The message is one SBF block without its sync characters and CRC: the block ID
(u16, little-endian: the block number in its low 13 bits, the revision in the
high 3), the block length (u16), and the block body, padded to the length. A
kind is selected by the block number and the length.

Every vector's block is written by a serializer in this file from the
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

NAME = "sbf2pack"
VERSION = "0.1.0"
REPO = "https://github.com/semuconsulting/pysbf2"
PROV = "tools/gen/sources/sbf-PROVENANCE.md"
PKG_DIR = "src/pysbf2"
FILES = ["sbftypes_core.py", "sbftypes_blocks.py"]
HEADER_MODULE = "sbf"
HEADER_BYTES = 8                # sync 2, CRC 2, ID 2, length 2: the length counts them all
PAYLOAD_BIT0 = 32               # the message starts at the ID: ID 16, length 16
MAX_REQUIRES = 3
LICENSE_LINE = "BSD 3-Clause, copyright (c) 2020 semuadmin (Steve Smith)"
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
        core = assignments(read_text(os.path.join(base, "sbftypes_core.py")), "sbftypes_core.py")
        blocks = assignments(read_text(os.path.join(base, "sbftypes_blocks.py")), "sbftypes_blocks.py")
        self.names = collections.OrderedDict(core)
        for k, v in blocks.items():
            self.names.setdefault(k, v)
        self.consts = {k: v.value for k, v in core.items()
                       if isinstance(v, ast.Constant) and isinstance(v.value, (str, int, float))}
        if "SBF_MSGIDS" not in core:
            raise GenError("sbftypes_core.py has no SBF_MSGIDS")
        self.numbers = {}                  # block name -> block number
        for k, v in zip(core["SBF_MSGIDS"].keys, core["SBF_MSGIDS"].values):
            num = ast.literal_eval(k)
            name = ast.literal_eval(v.elts[0]) if isinstance(v, ast.Tuple) else ast.literal_eval(v)
            if name in self.numbers:
                raise GenError("block %s has two numbers" % name)
            self.numbers[name] = num
        # the block groups: the dictionaries SBF_BLOCKS spreads, in its order
        top = blocks.get("SBF_BLOCKS")
        if not isinstance(top, ast.Dict):
            raise GenError("sbftypes_blocks.py has no SBF_BLOCKS")
        self.groups = collections.OrderedDict()
        for k, v in zip(top.keys, top.values):
            if k is not None or not isinstance(v, ast.Name):
                raise GenError("SBF_BLOCKS holds an entry that is not a spread group")
            self.groups[v.id] = self.literal(blocks[v.id], v.id)

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
    m = re.fullmatch(r"[UIXFCV](\d+)", ty)
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
        if key == src.consts.get("PAD"):
            raise Variable("a sub-block padded to a length the block states")
        if key.endswith("_bit"):
            ty, _ = unpack_type(src, v[0], where)
            size = width(ty)
            if not ty.startswith("X") or size is None:
                raise GenError("%s: bit field %s of type %s" % (where, key, ty))
            pos = bitpos
            for sub, sv in v[1].items():
                sty, scale = unpack_type(src, sv, where)
                n = width(sty)
                if sty[0] not in "UIX" or not n:
                    raise GenError("%s: bit %s of type %s" % (where, sub, sty))
                leaves.append(Leaf(sub, "s" if sty[0] == "I" else "u", pos, n, scale))
                pos += n
            if pos > bitpos + 8 * size:
                raise GenError("%s: the bits of %s exceed its %d bytes" % (where, key, size))
            bitpos += 8 * size
        elif isinstance(v, tuple) and len(v) == 2 and isinstance(v[1], dict):
            spec = v[0]
            if isinstance(spec, tuple):
                raise Variable("a part present only when field `%s` is %r" % spec)
            if isinstance(spec, int) and not isinstance(spec, bool):
                for i in range(1, spec + 1):
                    sub = []
                    bitpos = flatten(src, v[1], bitpos, where, sub)
                    leaves.extend(l._replace(name="%s_%02d" % (l.name, i)) for l in sub)
                continue
            raise Variable("a group repeated by field `%s`" % spec)
        else:
            ty, scale = unpack_type(src, v, where)
            n = width(ty)
            if n is None or ty[0] == "V":
                raise Variable("a field of type %s whose length the block length gives" % ty)
            if ty[0] == "C":
                if n > 255:
                    raise GenError("%s: text of %d bytes" % (where, n))
                leaves.append(Leaf(key, "ascii", bitpos, 8 * n, None))
                bitpos += 8 * n
            elif ty[0] == "F":
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
                leaves.append(Leaf(key, "s" if ty[0] == "I" else "u", bitpos, 8 * n, scale))
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
    def __init__(self, name, block, num, body_bytes, lines):
        self.name, self.block, self.num, self.lines = name, block, num, lines
        self.body_bytes = body_bytes
        self.length = HEADER_BYTES + 4 * ((body_bytes + 3) // 4)     # padded to a multiple of 4
        self.requires = []
        end = PAYLOAD_BIT0 + 8 * body_bytes
        stop = PAYLOAD_BIT0 + 8 * (self.length - HEADER_BYTES)
        self.pads = []
        while end < stop:
            n = min(64, stop - end)
            self.pads.append((end, n))
            end += n


class GroupPlan:
    def __init__(self, var, cname):
        self.var = var
        name = re.sub(r"^SBF_|_BLOCKS$", "", var).lower()
        self.cname = name
        self.format = "sbf-" + name.replace("_", "-")
        self.module = "sbf" + re.sub(r"[^a-z0-9]", "", name)
        self.kinds, self.keys = [], collections.OrderedDict()
        self.not_built = []            # (block, number, reason)
        self.scaled = []

    def add(self, src, block, defn):
        num = src.numbers.get(block)
        if num is None:
            self.not_built.append((block, None, "no block number in SBF_MSGIDS"))
            return
        leaves = []
        try:
            nbits = flatten(src, defn, PAYLOAD_BIT0, block, leaves)
        except Variable as e:
            self.not_built.append((block, num, str(e)))
            return
        if not leaves:
            self.not_built.append((block, num, "an empty body: a kind needs at least one field"))
            return
        body = (nbits - PAYLOAD_BIT0) // 8
        kind = slug(block)
        lines, seen = [], set()
        for leaf in leaves:
            base = "%s_%s" % (kind, slug(leaf.name))
            name, n = base, 2
            while name in seen:
                name, n = "%s_%d" % (base, n), n + 1
            seen.add(name)
            if leaf.kind == "ascii":
                tr, typ = "ascii", "string"
            elif leaf.kind in ("f32", "f64") and leaf.scale not in (None, 1):
                tr, typ = "%sscale:%s" % (leaf.kind, factor_text(leaf.scale)), "float"
                self.scaled.append((kind, leaf.name, tr))
            elif leaf.kind in ("f32", "f64"):
                tr, typ = leaf.kind, "float"
            elif leaf.scale is not None and leaf.scale != 1:
                if leaf.scale.denominator == 1:
                    tr, typ = ("siscale:" if leaf.kind == "s" else "uiscale:") + factor_text(leaf.scale), "int"
                else:
                    tr, typ = ("sscale:" if leaf.kind == "s" else "uscale:") + factor_text(leaf.scale), "float"
                self.scaled.append((kind, leaf.name, tr))
            else:
                tr, typ = ("twos" if leaf.kind == "s" else "uint"), "int"
            self.keys[name] = (typ, block, leaf.name)
            lines.append(Line("%s.%s" % (self.module, name), leaf.bitpos, leaf.bits, tr, leaf))
        if any(k.name == kind for k in self.kinds):
            raise GenError("two blocks give the kind %s" % kind)
        self.kinds.append(KindPlan(kind, block, num, body, lines))

    def finish(self):
        own = self.module + "."
        usage = collections.Counter(l.key for k in self.kinds for l in k.lines)
        for k in self.kinds:
            raw = [l.key for l in k.lines if l.key.startswith(own)]
            ranked = sorted(range(len(raw)), key=lambda i: (usage[raw[i]], i))
            k.requires = [raw[i] for i in sorted(ranked[:MAX_REQUIRES])]


def plan(src):
    out = []
    numbered = set()
    for var, blocks in src.groups.items():
        gp = GroupPlan(var, var)
        for block, defn in blocks.items():
            if not isinstance(defn, dict):
                raise GenError("%s: not a dictionary" % block)
            gp.add(src, block, defn)
            numbered.add(block)
        gp.finish()
        out.append(gp)
    return out


# ------------------------------------------------------------------- emit ---

def loc(pos, n):
    return "0:%d:%d" % (pos, n)


def source_line(tag, sha):
    return 'source        "%s %s/sbftypes_blocks.py at %s (commit %s)"' % (REPO, PKG_DIR, tag, sha)


def pack_text(gp, sha, tag):
    o = ["# SBF blocks of the group %s of pysbf2, one kind per block of fixed length." % gp.var,
         "# Generated by tools/gen/sbf2pack.py; do not edit by hand.",
         "# The message is one SBF block without its sync characters and CRC: block ID",
         "# (u16), length (u16), body. Body bit 0 is bit %d." % PAYLOAD_BIT0,
         "format        %s" % gp.format,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(tag, sha),
         "uses          %s" % HEADER_MODULE,
         "uses          %s" % gp.module,
         "wire          bits",
         "bit_order     lsb",
         "word_bytes    1",
         "field  %s.revision %s uint" % (HEADER_MODULE, loc(13, 3))]
    for k in gp.kinds:
        o.append("")
        o.append("kind      %s" % k.name)
        o.append("when      %s %d" % (loc(0, 13), k.num))
        o.append("when      %s %d" % (loc(16, 16), k.length))
        if k.requires:
            o.append("requires  %s" % " ".join(k.requires))
        for l in k.lines:
            o.append("field     %s %s %s" % (l.key, loc(l.pos, l.bits), l.tr))
        for pos, n in k.pads:
            o.append("const     %s 0" % loc(pos, n))
    return "\n".join(o) + "\n"


def module_text(gp, sha, tag):
    o = ["# The %s module: the body fields of the SBF block group %s." % (gp.module, gp.var),
         "# Generated by tools/gen/sbf2pack.py; do not edit by hand. A key is",
         "# <block>_<field> in lower case; a scale the definition states is applied;",
         "# the source states no unit, so none is declared.",
         "module        %s" % gp.module,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(tag, sha)]
    for name, (typ, block, fname) in gp.keys.items():
        o.append('key  %s  %s  -  "field %s of block %s"' % (name, typ, fname, block))
    return "\n".join(o) + "\n"


def header_module_text(sha, tag):
    return "\n".join([
        "# The sbf module: the SBF block-header key shared by every SBF pack.",
        "# Generated by tools/gen/sbf2pack.py; do not edit by hand.",
        "module        %s" % HEADER_MODULE,
        "version       %s" % VERSION,
        "distribution  public",
        'source        "%s %s/sbftypes_core.py at %s (commit %s)"' % (REPO, PKG_DIR, tag, sha),
        'key  revision  int  -  "SBF block header: the block revision, the high 3 bits of the block ID"',
        ""])


# ------------------------------------------------- serializer (vectors) ---

def crc16(data):
    """CRC-16-CCITT as SBF blocks use it (polynomial 0x1021, initial value 0) over
    the ID, the length and the body; for the scratch cross-check and the tests."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def raw_of(leaf, value):
    if leaf.kind in ("u", "s"):
        return value & ((1 << leaf.bits) - 1)
    if leaf.kind == "f32":
        return int.from_bytes(struct.pack("<f", value), "little")
    if leaf.kind == "f64":
        return int.from_bytes(struct.pack("<d", value), "little")
    return int.from_bytes(value.encode("ascii").ljust(leaf.bits // 8, b"\0"), "little")


def block_bytes(k, values, revision):
    acc = k.num | (revision << 13) | (k.length << 16)
    for l in k.lines:
        acc |= raw_of(l.leaf, values[l.leaf.name]) << l.pos
    return acc.to_bytes(k.length - 4, "little")


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


def vector_files(gp):
    files = []
    for i, k in enumerate(gp.kinds):
        values = {l.leaf.name: sample(l.leaf, k.num * 31 + j * 7 + 3) for j, l in enumerate(k.lines)}
        data = block_bytes(k, values, i % 8).hex()
        files.append(("rt-%04d-%s.json" % (k.num, k.name), vector_text([
            ("name", "%s-roundtrip-%s" % (gp.format, k.name)), ("from", gp.format), ("to", gp.format),
            ("input", data), ("expect", data), ("model", {"@kind": k.name})])))
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

def pack_md(gp, sha, tag, nvec):
    o = []
    a = o.append
    a("# Pack: %s" % gp.format)
    a("")
    a("Septentrio Binary Format (SBF) blocks of the group `%s` of the pysbf2 block" % gp.var)
    a("definitions (`%s`, `%s/sbftypes_blocks.py`) at %s, commit `%s`. Public." % (REPO, PKG_DIR, tag, sha))
    a("Generated by `tools/gen/sbf2pack.py`; do not edit `pack.def`, this file,")
    a("`PROVENANCE.md`, `model/%s.def` or the vectors by hand." % gp.module)
    a("")
    a("Status: Built. Generated and checked by the generator's own serializer and codec.")
    a("")
    a("No Septentrio document was read: the definitions are pysbf2's BSD-licensed")
    a("restatement, read as Python syntax trees.")
    a("")
    a("## The message")
    a("")
    a("`wire bits`, `bit_order lsb`, `word_bytes 1`; hex text. One SBF block without")
    a("its sync characters (`$@`) and its CRC; every number is little-endian:")
    a("")
    a("| Bytes | Content | In the pack |")
    a("|---|---|---|")
    a("| 0-1 | block ID: the block number in bits 0-12, the revision in bits 13-15 | per-kind `when` on the number; `sbf.revision` |")
    a("| 2-3 | block length in bytes, counting the 8-byte header | per-kind `when` |")
    a("| 4 … | body, padded with bytes to a multiple of 4 | the kind's `field` lines; the padding a `const` of 0 |")
    a("")
    a("The message is the block without sync and CRC, in both directions. A framer")
    a("adds the two sync characters and the CRC before the ID, and checks them on")
    a("receipt: CRC-16 CCITT (polynomial 0x1021, initial value 0) over the ID, the")
    a("length and the body. That is the item \"Layered wires and framing\" of")
    a("`docs/roadmap.md`. Because the length counts the sync and CRC too, a message of")
    a("this pack is 4 bytes shorter than its length field.")
    a("")
    a("## Blocks")
    a("")
    a("| Kind | Block | Number | Length in bytes |")
    a("|---|---|---|---|")
    for k in gp.kinds:
        a("| `%s` | %s | %d | %d |" % (k.name, k.block, k.num, k.length))
    a("")
    a("## What is mapped")
    a("")
    a("| Definition type | Transform | Model type |")
    a("|---|---|---|")
    a("| `U1` … `U8`, `X1` … `X8` | `uint` | int |")
    a("| `I1` … `I8` | `twos` | int |")
    a("| `F4`, `F8` | `f32`, `f64` | float |")
    a("| `C<n>` (text of a fixed length) | `ascii` | string |")
    a("| an integer with a fractional scale | `uscale` / `sscale` with the scale as an exact fraction | float |")
    a("| an integer with an integer scale (1000, 10^9) | `uiscale` / `siscale` | int |")
    a("| a bit field (`_bit`) | each named bit group as its own field, from the least significant bit | int |")
    a("| an unsigned integer wider than 8 bytes | 8-byte `uint` parts, `_01` … appended | int |")
    a("")
    a("Keys are `%s.<block>_<field>` in lower case with underscores. A scale the" % gp.module)
    a("source states is applied; the source states no unit, so the module declares")
    a("none (`-`). The bytes that pad a body to a multiple of 4 are a `const` of 0:")
    a("decode ignores them, encode writes zeros.")
    if gp.scaled:
        a("")
        a("Scaled fields:")
        a("")
        a("| Kind | Field | Transform |")
        a("|---|---|---|")
        for k, f, tr in gp.scaled:
            a("| `%s` | `%s` | `%s` |" % (k, f, tr))
    a("")
    a("### Core keys")
    a("")
    a("None. The source states no unit for any field: PVTGeodetic and the blocks like")
    a("it carry latitude and longitude as doubles that the definition file marks in a")
    a("comment as radians, and a height. Without a unit stated as data the pack binds")
    a("nothing; with one, the 0.16 derive `deg` would give `lat` and `lon` in degrees")
    a("from radians, and the Cartesian blocks the ECEF derives.")
    a("")
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own keys, so an entity from another format" % MAX_REQUIRES)
    a("selects a kind only when it holds them.")
    a("")
    a("## What is not mapped")
    a("")
    if gp.not_built:
        a("| Block | Number | Reason |")
        a("|---|---|---|")
        for b, num, why in gp.not_built:
            a("| %s | %s | %s |" % (b, "-" if num is None else num, why))
        a("")
    a("- A block whose length varies: a group repeated by a count field, sub-blocks")
    a("  padded to a length the block states, or a part present only for one value of")
    a("  a field. Stating them needs a counted group whose items are padded to a")
    a("  stated sub-block length.")
    a("- The block revision does not select a layout: the source gives one definition")
    a("  per block.")
    a("- The sync characters and the CRC (see The message).")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-<number>-<kind>.json`: one same-format round trip per kind, the")
    a("block written by a serializer in the generator from sample values.")
    a("")
    a("%d vectors." % nvec)
    return "\n".join(o) + "\n"


def provenance_md(gp, sha, tag, table):
    rows = ["# Provenance: %s" % gp.format, "",
            "| Fact | Value |", "|---|---|",
            "| repository | %s |" % REPO,
            "| tag | `%s` |" % tag,
            "| commit | `%s` |" % sha]
    for f in FILES:
        rows.append("| definition read | `%s/%s` (SHA-256 `%s`) |" % (PKG_DIR, f, table["%s/%s" % (PKG_DIR, f)]))
    rows += ["| license | %s: `LICENSE` at the root of the commit (SHA-256 `%s`), verbatim in `%s` |" % (
                 LICENSE_LINE, table["LICENSE"], PROV),
             "| date read | 2026-11-19 |",
             "| what the pack takes | block names and numbers; field names, types, scales and bit widths; no description text |",
             "| generator | `tools/gen/sbf2pack.py` |", ""]
    return "\n".join(rows)


def write_sources_provenance(out, src, sha, tag):
    lic = read_text(os.path.join(src, "LICENSE"))
    o = ["# Provenance of the SBF inputs", "",
         "| Fact | Value |", "|---|---|",
         "| repository | %s |" % REPO,
         "| tag | `%s` |" % tag,
         "| commit | `%s` (the commit of the tag, read 2026-11-19) |" % sha,
         "| archive | `https://codeload.github.com/semuconsulting/pysbf2/tar.gz/%s` |" % sha,
         "| license | %s: the file `LICENSE` at the root of the commit, verbatim below |" % LICENSE_LINE,
         "",
         "The definition files say in their header that their content was taken from",
         "a Septentrio receiver reference guide (copyright Septentrio NV/SA). This",
         "repository reads only the definition files of pysbf2, never a Septentrio",
         "document, and takes no description text from them.",
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
    plans = plan(Source(args.src))
    built = [gp for gp in plans if gp.kinds]
    core_text = read_text(args.core_def) if args.core_def else out.read("model/core.def")
    out.write("model/%s.def" % HEADER_MODULE, header_module_text(sha, tag))
    total = 0
    for gp in built:
        pdir = "packs/" + gp.format
        out.write("model/%s.def" % gp.module, module_text(gp, sha, tag))
        out.write(pdir + "/pack.def", pack_text(gp, sha, tag))
        vecs = vector_files(gp)
        keep = {n for n, _ in vecs}
        for old in out.listdir(pdir + "/vectors"):
            if old.endswith(".json") and old not in keep:
                out.remove("%s/vectors/%s" % (pdir, old))
        for n, t in vecs:
            out.write("%s/vectors/%s" % (pdir, n), t)
        model = gtcheck.Model()
        model.add(core_text, "model/core.def")
        model.add(out.read("model/%s.def" % HEADER_MODULE), "model/%s.def" % HEADER_MODULE)
        model.add(out.read("model/%s.def" % gp.module), "model/%s.def" % gp.module)
        pack = gtcheck.load_pack(out.read(pdir + "/pack.def"), model, pdir + "/pack.def")
        total += check_vectors(pack, [(n, out.read("%s/vectors/%s" % (pdir, n))) for n, _ in vecs], gp.format)
        out.write(pdir + "/pack.md", pack_md(gp, sha, tag, len(vecs)))
        out.write(pdir + "/PROVENANCE.md", provenance_md(gp, sha, tag, table))
    reasons = collections.Counter(re.sub(r"`[^`]*`|\d+", "…", w) for gp in plans for _, _, w in gp.not_built)
    return ["tag             %s (commit %s)" % (tag, sha),
            "groups          %d, packs %d%s" % (len(plans), len(built), "".join(
                "\nno pack         %s" % gp.var for gp in plans if not gp.kinds)),
            "blocks          %d, kinds %d" % (sum(len(gp.kinds) + len(gp.not_built) for gp in plans),
                                              sum(len(gp.kinds) for gp in built)),
            "not built       %d" % sum(reasons.values())] + ["  %3d  %s" % (n, w) for w, n in reasons.most_common()] + [
            "field lines     %d" % sum(len(k.lines) for gp in built for k in gp.kinds),
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
