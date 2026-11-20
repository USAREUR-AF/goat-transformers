#!/usr/bin/env python3
"""Generate the goat-transformers pack of RTCM 3 (RTCM 10403.x) messages from
the message definitions of pyrtcm (github.com/semuconsulting/pyrtcm,
src/pyrtcm/rtcmtypes_core.py and rtcmtypes_get*.py).

Reads   <src>/src/pyrtcm/rtcmtypes_core.py, rtcmtypes_get.py,
        rtcmtypes_get_msm.py, rtcmtypes_get_igs.py and <src>/LICENSE, as Python
        syntax trees: no file of the source is run;
        tools/gen/sources/rtcm3-PROVENANCE.md (the tag, commit and SHA-256 of
        every file; a file that differs is refused)
Writes  <out>/model/rtcm3.def                  the module of the RTCM 3 keys and lists
        <out>/packs/rtcm3/pack.def             one pack, one kind per message number
        <out>/packs/rtcm3/pack.md
        <out>/packs/rtcm3/PROVENANCE.md
        <out>/packs/rtcm3/vectors/*.json
        tools/gen/sources/rtcm3-PROVENANCE.md (only with --commit)

The message is the body of one RTCM 3 frame: what follows the 3-octet frame
header (preamble, reserved bits, length) and precedes the CRC-24Q. It is read
most significant bit first, as a sequence (`layout sequential`): a message is
its data fields in order, a group counted by the field just before it, and a
part a presence bit before it gates. The message number (DF002, 12 bits) is
each kind's `when`.

Every vector's message is written by a serializer in this file from the
definitions; the generator then loads the pack with gtcheck and decodes and
encodes every vector with its own codec of the sequential bits layout.

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
import sys
from decimal import Decimal
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

NAME = "rtcm2pack"
VERSION = "0.1.0"
REPO = "https://github.com/semuconsulting/pyrtcm"
PROV = "tools/gen/sources/rtcm3-PROVENANCE.md"
PKG_DIR = "src/pyrtcm"
FILES = ["rtcmtypes_core.py", "rtcmtypes_get.py", "rtcmtypes_get_msm.py", "rtcmtypes_get_igs.py"]
FORMAT = MODULE = "rtcm3"
LICENSE_LINE = "BSD 3-Clause, copyright (c) 2020 semuadmin (Steve Smith)"
MSGNUM = "DF002"
MSGNUM_BITS = 12
MAX_REQUIRES = 3
GROUP_SAMPLE_ITEMS = 2
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
# A name resolves to a module-level assignment (ubxtypes-style constants, the
# HDR_* header dictionaries); `**HDR` spreads one dictionary into another; a
# scale written as an expression of numbers and names (`25 * 10 ** 6`,
# `1 / 256`, `P2_31`) is evaluated exactly: P2_n is 2^-n and P2_Pn is 2^n.

def scale_of_name(name):
    m = re.fullmatch(r"P2_(P?)(\d+)", name)
    if m:
        n = int(m.group(2))
        return Fraction(2 ** n) if m.group(1) else Fraction(1, 2 ** n)
    return None


class Reader:
    def __init__(self, names):
        self.names = names              # module-level assignments, name -> ast node

    def value(self, node, where):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in self.names:
                raise GenError("%s: unknown name %s" % (where, node.id))
            return self.value(self.names[node.id], where)
        if isinstance(node, (ast.Tuple, ast.List)):
            return tuple(self.value(e, where) for e in node.elts)
        if isinstance(node, ast.Dict):
            out = collections.OrderedDict()
            for k, v in zip(node.keys, node.values):
                if k is None:                       # **spread
                    spread = self.value(v, where)
                    if not isinstance(spread, dict):
                        raise GenError("%s: a spread that is not a dictionary" % where)
                    out.update(spread)
                else:
                    out[self.value(k, where)] = self.value(v, where)
            return out
        raise GenError("%s: an expression the generator does not read (line %d)" % (where, node.lineno))

    def scale(self, node, where):
        """An exact Fraction for a scale expression."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise GenError("%s: scale %r" % (where, node.value))
            return Fraction(node.value) if isinstance(node.value, int) else Fraction(Decimal(repr(node.value)))
        if isinstance(node, ast.Name):
            f = scale_of_name(node.id)
            if f is not None:
                return f
            if node.id in self.names:
                return self.scale(self.names[node.id], where)
            raise GenError("%s: scale name %s" % (where, node.id))
        if isinstance(node, ast.BinOp):
            a, b = self.scale(node.left, where), self.scale(node.right, where)
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                if b == 0:
                    raise GenError("%s: a scale divided by 0" % where)
                return a / b
            if isinstance(node.op, ast.Pow) and b.denominator == 1 and 0 <= b <= 64:
                return a ** int(b)
        raise GenError("%s: a scale expression the generator does not read" % where)


def assignments(text, where):
    out = collections.OrderedDict()
    for st in ast.parse(text, where).body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            out[st.targets[0].id] = st.value
    return out


Field = collections.namedtuple("Field", "name typ bits scale")


class Source:
    def __init__(self, src):
        base = os.path.join(src, PKG_DIR)
        names = collections.OrderedDict()
        for f in FILES:
            for k, v in assignments(read_text(os.path.join(base, f)), f).items():
                names.setdefault(k, v)
        self.reader = r = Reader(names)
        self.fields = {}
        node = names.get("RTCM_DATA_FIELDS")
        if not isinstance(node, ast.Dict):
            raise GenError("rtcmtypes_core.py has no RTCM_DATA_FIELDS")
        for k, v in zip(node.keys, node.values):
            key = r.value(k, "RTCM_DATA_FIELDS")
            if not isinstance(v, ast.Tuple) or len(v.elts) != 4:
                raise GenError("data field %s: not a 4-tuple" % key)
            typ = r.value(v.elts[0], key)
            bits = r.value(v.elts[1], key)
            scale = r.scale(v.elts[2], key)
            self.fields[key] = Field(key, typ, bits, scale)
        self.msgids = r.value(names["RTCM_MSGIDS"], "RTCM_MSGIDS")
        self.payloads = collections.OrderedDict()
        for var, origin in (("RTCM_PAYLOADS_GET", "rtcmtypes_get.py"),
                            ("RTCM_PAYLOADS_GET_IGS", "rtcmtypes_get_igs.py"),
                            ("RTCM_PAYLOADS_GET_MSM", "rtcmtypes_get_msm.py")):
            if var not in names or not isinstance(names[var], ast.Dict):
                raise GenError("%s defines no %s" % (origin, var))
            if origin.endswith("_msm.py"):
                # MSM messages are listed, not built: only their numbers are read
                for k in names[var].keys:
                    if k is not None:
                        self.payloads[str(r.value(k, var))] = (None, origin)
                continue
            for k, v in r.value(names[var], var).items():
                self.payloads[str(k)] = (v, origin)
        self.consts = {k: r.value(v, k) for k, v in names.items()
                       if isinstance(v, ast.Constant) and isinstance(v.value, (int, str))}


# ------------------------------------------------------------------- plan ---

class NotBuilt(Exception):
    """A part of the message the pack cannot state; the text says what."""


def base_name(name):
    """A data field name without pyrtcm's `+n` nesting suffix."""
    return re.sub(r"\+\d+$", "", name)


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
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


def transform(field, where):
    """(transform text, model type) of a data field, or NotBuilt."""
    typ, n, f = field.typ, field.bits, field.scale
    if not isinstance(n, int) or not 1 <= n <= 64:
        raise NotBuilt("data field %s of %r bits" % (field.name, n))
    scaled = f not in (0, 1)
    integral = scaled and f.denominator == 1
    if typ in ("UINT", "BIT"):
        if not scaled:
            return "uint", "int"
        return ("uiscale:%s" % factor_text(f), "int") if integral else ("uscale:%s" % factor_text(f), "float")
    if typ == "INT":
        if n < 2 and not scaled:
            return "twos", "int"
        if not scaled:
            return "twos", "int"
        return ("siscale:%s" % factor_text(f), "int") if integral else ("sscale:%s" % factor_text(f), "float")
    if typ == "SNT":
        if n < 2:
            raise NotBuilt("a sign-magnitude field of 1 bit (%s)" % field.name)
        return ("smag", "int") if not scaled else ("smscale:%s" % factor_text(f), "float")
    if typ == "CHA":
        if n % 8 or scaled:
            raise NotBuilt("text field %s of %d bits" % (field.name, n))
        return "ascii", "string"
    if typ == "STR":
        if scaled:
            raise NotBuilt("text field %s with a scale" % field.name)
        return "uint", "int"           # one UTF-8 code unit: a byte value
    raise NotBuilt("data field %s of type %s (%s)" % (field.name, typ, where))


Line = collections.namedtuple("Line", "d key bits tr field body extra")
# d: field | group | presence | if ; for group: key = list, extra = count bits, body = lines;
# for presence: key = name, bits = n; for if: key = presence name, extra = bit number, body.


class KindPlan:
    def __init__(self, name, num, lines, origin):
        self.name, self.num, self.lines, self.origin = name, num, lines, origin
        self.requires = []


class Plan:
    def __init__(self, src):
        self.src = src
        self.kinds, self.keys, self.lists = [], collections.OrderedDict(), collections.OrderedDict()
        self.not_built = []            # (message, reason)
        for name, (defn, origin) in src.payloads.items():
            if origin.endswith("_msm.py"):
                self.not_built.append((name, "an MSM message: the number of satellite and signal fields "
                                             "is the number of 1 bits in its masks"))
                continue
            self.plan_message(name, defn, origin)
        own = MODULE + "."
        usage = collections.Counter(l.key for k in self.kinds for l in walk(k.lines) if l.d == "field")
        for k in self.kinds:
            raw = [l.key for l in k.lines if l.d == "field" and l.key.startswith(own)]
            ranked = sorted(range(len(raw)), key=lambda i: (usage[raw[i]], i))
            k.requires = [raw[i] for i in sorted(ranked[:MAX_REQUIRES])]

    def plan_message(self, name, defn, origin):
        if not re.fullmatch(r"\d+", name):
            self.not_built.append((name, "a sub-type of message %s chosen by fields after a 3-bit version; "
                                         "a kind's `when` lines must come first" % name.split("_")[0]))
            return
        items = list(defn.items())
        if not items or items[0][0] != MSGNUM:
            self.not_built.append((name, "the message number is not its first field"))
            return
        kname = "m" + name
        state = {"presence": 0, "seen": set(), "pending": []}
        try:
            lines = self.scope(items[1:], kname, kname, state)
        except NotBuilt as e:
            self.not_built.append((name, str(e)))
            for k in state["pending"]:
                self.keys.pop(k, None)
                self.lists.pop(k, None)
            return
        if not any(l.d != "presence" for l in lines):
            self.not_built.append((name, "no field after the message number"))
            return
        self.kinds.append(KindPlan(kname, int(name), lines, origin))

    def declare(self, state, name, typ, what):
        if name in self.keys or name in self.lists:
            raise GenError("key %s declared twice" % name)
        if typ == "list":
            self.lists[name] = what
        else:
            self.keys[name] = (typ, what)
        state["pending"].append(name)

    def key_for(self, prefix, fname, state):
        base = "%s_%s" % (prefix, slug(base_name(fname)))
        name, n = base, 2
        while name in state["seen"]:
            name, n = "%s_%d" % (base, n), n + 1
        state["seen"].add(name)
        return name

    def scope(self, items, prefix, kname, state):
        """The lines of one scope (the message after its number, or a group's
        item) from its definition items."""
        lines = []
        i = 0
        while i < len(items):
            key, v = items[i]
            if isinstance(v, str):                    # a data field, its description as the value
                fname = base_name(key)
                if fname not in self.src.fields:
                    raise NotBuilt("data field %s is not in RTCM_DATA_FIELDS" % fname)
                field = self.src.fields[fname]
                if field.typ in ("PRN", "CPR", "CSG"):
                    i += 1
                    continue                          # derived by pyrtcm, not on the wire
                tr, typ = transform(field, kname)
                name = self.key_for(prefix, key, state)
                self.declare(state, name, typ, "data field %s of message %s" % (fname, kname[1:]))
                lines.append(Line("field", MODULE + "." + name, field.bits, tr, fname, None, None))
                i += 1
                continue
            if not (isinstance(v, tuple) and len(v) == 2 and isinstance(v[1], dict)):
                raise NotBuilt("part %s of a form the generator does not read" % key)
            spec, body = v
            if isinstance(spec, tuple):               # a conditional part
                run = self.presence_run(items, i, lines)
                if run is None:
                    raise NotBuilt("a part present only when field %s has value %r, not stated as a run "
                                   "of 1-bit flags just before the parts they gate" % (spec[0], spec[1]))
                flags, parts = run
                del lines[-len(flags):]
                state["presence"] += 1
                pname = "p%d" % state["presence"]
                lines.append(Line("presence", pname, len(flags), None, None, None, None))
                for n, (pkey, (_, pbody)) in enumerate(parts, 1):
                    inner = self.scope(list(pbody.items()), prefix, kname, state)
                    lines.append(Line("if", pname, None, None, None, inner, n))
                for f in flags:
                    self.keys.pop(f.key.split(".", 1)[1], None)
                i += len(parts)
                continue
            gname = slug(re.sub(r"_grp$", "", key))
            count = spec
            if isinstance(count, str) and count in self.src.consts and isinstance(self.src.consts[count], int):
                count = self.src.consts[count]
            if isinstance(count, int) and not isinstance(count, bool):
                for n in range(1, count + 1):
                    lines.extend(self.scope(list(body.items()), "%s_%s_%02d" % (prefix, gname, n), kname, state))
                i += 1
                continue
            if not isinstance(count, str) or not re.fullmatch(r"[A-Z]*DF\d+(_\d+)?(\+\d+)?", count):
                raise NotBuilt("a group whose count is computed (%s)" % count)
            cname = base_name(count)
            if not lines or lines[-1].d != "field" or lines[-1].field != cname:
                raise NotBuilt("a group counted by field %s, which does not come just before it" % cname)
            if not lines[-1].tr == "uint":
                raise NotBuilt("a group counted by field %s, which is not a plain unsigned field" % cname)
            count_line = lines.pop()
            self.keys.pop(count_line.key.split(".", 1)[1], None)
            lname = "%s_%s" % (prefix, gname)
            self.declare(state, lname, "list", "group %s of message %s, counted by data field %s"
                         % (gname, kname[1:], cname))
            inner = self.scope(list(body.items()), lname, kname, state)
            lines.append(Line("group", MODULE + "." + lname, None, None, None, inner, count_line.bits))
            i += 1
        return lines

    def presence_run(self, items, i, lines):
        """When items[i:] start k conditional parts, each gated by `field == 1`,
        and the last k lines are exactly those k 1-bit fields in that order: (the
        k flag lines, the k parts)."""
        parts = []
        j = i
        while j < len(items):
            k, v = items[j]
            if not (isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], tuple) and isinstance(v[1], dict)):
                break
            parts.append((k, v))
            j += 1
        if not parts or len(lines) < len(parts):
            return None
        flags = lines[-len(parts):]
        for flag, (_, (cond, _)) in zip(flags, parts):
            if (flag.d != "field" or flag.field != base_name(cond[0]) or cond[1] != 1 or flag.bits != 1):
                return None
        return flags, parts


def walk(lines):
    for l in lines:
        yield l
        if l.body:
            yield from walk(l.body)


# ------------------------------------------------------------------- emit ---

def pack_text(plan, sha, tag):
    o = ["# RTCM 3 (RTCM 10403.x) message bodies, one kind per message number.",
         "# Generated by tools/gen/rtcm2pack.py; do not edit by hand.",
         "# The message is the body of one frame: after the 3-octet frame header,",
         "# before the CRC-24Q; most significant bit first, read in sequence.",
         "format        %s" % FORMAT,
         "version       %s" % VERSION,
         "distribution  public",
         'source        "%s %s/rtcmtypes_core.py and rtcmtypes_get.py at %s (commit %s)"' % (REPO, PKG_DIR, tag, sha),
         "uses          %s" % MODULE,
         "wire          bits",
         "layout        sequential",
         "bit_order     msb"]

    def body(lines, depth):
        pad = "  " * depth
        for l in lines:
            if l.d == "field":
                o.append("%sfield     %s %d %s" % (pad, l.key, l.bits, l.tr))
            elif l.d == "presence":
                o.append("%spresence  %s %d" % (pad, l.key, l.bits))
            elif l.d == "if":
                o.append("%sif        %s.%d" % (pad, l.key, l.extra))
                body(l.body, depth + 1)
                o.append("%send" % pad)
            elif l.d == "group":
                o.append("%sgroup     %s count %d" % (pad, l.key, l.extra))
                body(l.body, depth + 1)
                o.append("%send" % pad)
    for k in plan.kinds:
        o.append("")
        o.append("kind      %s" % k.name)
        o.append("when      %d %d" % (MSGNUM_BITS, k.num))
        if k.requires:
            o.append("requires  %s" % " ".join(k.requires))
        body(k.lines, 0)
    return "\n".join(o) + "\n"


def module_text(plan, sha, tag):
    o = ["# The rtcm3 module: the data fields of the RTCM 3 messages the rtcm3 pack maps.",
         "# Generated by tools/gen/rtcm2pack.py; do not edit by hand. A key is",
         "# m<message>_<data field>; inside a group, <list>_<data field>. A scale the",
         "# source states is applied; the source states no unit, so none is declared.",
         "module        %s" % MODULE,
         "version       %s" % VERSION,
         "distribution  public",
         'source        "%s %s/rtcmtypes_core.py at %s (commit %s)"' % (REPO, PKG_DIR, tag, sha)]
    for name, (typ, what) in plan.keys.items():
        o.append('key   %s  %s  -  "%s"' % (name, typ, what))
    for name, what in plan.lists.items():
        o.append('list  %s  "%s"' % (name, what))
    return "\n".join(o) + "\n"


# -------------------------------------------------- serializer (vectors) ---

class Bits:
    def __init__(self):
        self.v, self.n = 0, 0

    def put(self, value, n):
        self.v = (self.v << n) | (value & ((1 << n) - 1))
        self.n += n

    def bytes(self):
        pad = (-self.n) % 8
        return ((self.v << pad).to_bytes((self.n + pad) // 8, "big")) if self.n + pad else b""


def raw_sample(tr, n, salt):
    """A raw bit pattern for a field whose decode then encode returns it."""
    if tr == "ascii":
        text = ("R%d" % (salt % 97))[:n // 8]
        return int.from_bytes(text.encode("ascii").ljust(n // 8, b"\0"), "big")
    span = 1 << min(n, 31)
    v = (salt * 2654435761 + 12345) % span
    if tr.startswith(("smag", "smscale")) and n > 1:
        v &= ~(1 << (n - 1)) if salt % 3 else (1 << (n - 1)) - 1
        if salt % 2:
            v |= 1 << (n - 1)
        if v == 1 << (n - 1):
            v |= 1                         # sign 1 with magnitude 0 encodes back as 0
    if n == 64 and salt % 2 and tr == "uint":
        v |= 1 << 63
    return v & ((1 << n) - 1)


def serialize(lines, out, salt, items_per_group, present):
    for j, l in enumerate(lines):
        s = salt * 7 + j * 13 + 5
        if l.d == "field":
            out.put(raw_sample(l.tr, l.bits, s), l.bits)
        elif l.d == "presence":
            ifs = [x for x in lines if x.d == "if" and x.key == l.key]
            for x in sorted(ifs, key=lambda x: x.extra):
                out.put(1 if present(x) else 0, 1)
        elif l.d == "if":
            if present(l):
                serialize(l.body, out, s, items_per_group, present)
        elif l.d == "group":
            out.put(items_per_group, l.extra)
            for n in range(items_per_group):
                serialize(l.body, out, s + 101 * (n + 1), items_per_group, present)


def message_bytes(k, items, present):
    out = Bits()
    out.put(k.num, MSGNUM_BITS)
    serialize(k.lines, out, k.num, items, present)
    return out.bytes()


def vector_text(pairs):
    return json.dumps(collections.OrderedDict(pairs), indent=2) + "\n"


def vector_files(plan):
    files = []
    for k in plan.kinds:
        has_group = any(l.d == "group" for l in walk(k.lines))
        has_if = any(l.d == "if" for l in walk(k.lines))
        cases = [("", GROUP_SAMPLE_ITEMS, lambda x: True)]
        if has_group:
            cases.append(("-no-items", 0, lambda x: True))
        if has_if:
            cases.append(("-some-absent", GROUP_SAMPLE_ITEMS, lambda x: x.extra % 2 == 1))
        for suffix, items, present in cases:
            data = message_bytes(k, items, present).hex()
            model = collections.OrderedDict([("@kind", k.name)])
            for l in k.lines:
                if l.d == "group":
                    model[l.key + ".#"] = str(items)
            files.append(("rt-%04d-%s%s.json" % (k.num, k.name, suffix), vector_text([
                ("name", "%s-roundtrip-%s%s" % (FORMAT, k.name, suffix)), ("from", FORMAT), ("to", FORMAT),
                ("input", data), ("expect", data), ("model", model)])))
    return files


# -------------------------------------- codec of the sequential bits layout ---

class Cursor:
    def __init__(self, data):
        self.v, self.total, self.pos = int.from_bytes(data, "big"), 8 * len(data), 0

    def take(self, n):
        if self.pos + n > self.total:
            raise CodecError("malformed-wire")
        x = (self.v >> (self.total - self.pos - n)) & ((1 << n) - 1)
        self.pos += n
        return x


def round_half_away(q):
    """round-half-away-from-zero of an exact Fraction."""
    n = abs(q)
    r = math.floor(n + Fraction(1, 2))
    return r if q >= 0 else -r


def exact(text):
    m = re.fullmatch(r"(-?)(\d+)/(\d+)", text)
    if m:
        return Fraction(int(m.group(2)), int(m.group(3))) * (-1 if m.group(1) else 1)
    return Fraction(Decimal(text))


def decode_value(node, raw):
    tr, n = node.tr, node.bits
    args = node.targs or []
    if tr == "uint":
        return raw - (1 << 64) if n == 64 and raw >> 63 else raw
    signed = raw - (1 << n) if raw >> (n - 1) else raw
    if tr == "twos":
        return signed
    if tr in ("smag", "smscale"):
        mag = raw & ((1 << (n - 1)) - 1)
        v = -mag if raw >> (n - 1) else mag
        if tr == "smag":
            return v
        f = gtcheck.parse_factor(args[0])
        return v * f[0] / f[1] if isinstance(f, tuple) else v * f
    if tr in ("uscale", "sscale"):
        v = raw if tr == "uscale" else signed
        f = gtcheck.parse_factor(args[0])
        return v * f[0] / f[1] if isinstance(f, tuple) else v * f
    if tr in ("uiscale", "siscale"):
        v = raw if tr == "uiscale" else signed
        return int(round_half_away(v * exact(args[0])))
    if tr == "ascii":
        text = raw.to_bytes(n // 8, "big").rstrip(b"\0")
        if any(b < 0x20 or b > 0x7E for b in text):
            raise CodecError("transform-decode")
        return text.decode("ascii")
    raise CodecError("transform-decode %s" % tr)


def encode_value(node, x):
    tr, n = node.tr, node.bits
    args = node.targs or []
    mask = (1 << n) - 1
    if tr in ("uint", "twos"):
        return x & mask
    if tr == "smag":
        if abs(x) >= 1 << (n - 1):
            raise CodecError("transform-encode")
        return ((1 << (n - 1)) if x < 0 else 0) | abs(x)
    if tr in ("uscale", "sscale", "smscale"):
        f = gtcheck.parse_factor(args[0])
        q = x * f[1] / f[0] if isinstance(f, tuple) else x / f
        r = int(math.floor(abs(q) + 0.5)) * (1 if q >= 0 else -1)
        if tr == "smscale":
            if abs(r) >= 1 << (n - 1):
                raise CodecError("transform-encode")
            return ((1 << (n - 1)) if r < 0 else 0) | abs(r)
        return r & mask
    if tr in ("uiscale", "siscale"):
        return int(round_half_away(Fraction(x) / exact(args[0]))) & mask
    if tr == "ascii":
        b = x.encode("ascii")
        return int.from_bytes(b.ljust(n // 8, b"\0"), "big")
    raise CodecError("transform-encode %s" % tr)


def decode_scope(lines, cur, ent, lists, pres):
    for n in lines:
        if n.d == "field":
            ent[n.key] = decode_value(n, cur.take(n.bits))
        elif n.d == "presence":
            pres[n.name] = [cur.take(1) for _ in range(n.bits)]
        elif n.d == "if":
            if all((pres[name][bit - 1] == 0) if neg else (pres[name][bit - 1] == 1) for neg, name, bit in n.conds):
                decode_scope(n.body, cur, ent, lists, pres)
        elif n.d == "group":
            count = cur.take(n.count)
            items = []
            for _ in range(count):
                item, sub = collections.OrderedDict(), {}
                decode_scope(n.body, cur, item, sub, dict(pres))
                item["@lists"] = sub
                items.append(item)
            lists[n.key] = items
        elif n.d in ("when", "requires", "default"):
            pass
        else:
            raise CodecError("line %s" % n.d)


def decode(pack, data):
    for kind in pack.kinds:
        cur = Cursor(data)
        whens = [n for n in kind.lines if n.d == "when"]
        try:
            if all(cur.take(n.bits) == int(n.value) for n in whens):
                ent, lists = collections.OrderedDict(), {}
                decode_scope([n for n in kind.lines if n.d != "when"], cur, ent, lists, {})
                return kind.name, ent, lists
        except CodecError:
            continue
    raise CodecError("no-kind")


def writes(lines, ent, lists):
    for n in lines:
        if n.d == "field" and n.key in ent:
            return True
        if n.d == "group" and n.key in lists:
            return True
        if n.d == "if" and writes(n.body, ent, lists):
            return True
    return False


def encode_scope(lines, out, ent, lists):
    pres = {}
    for n in lines:
        if n.d == "if":
            for neg, name, bit in n.conds:
                pres.setdefault(name, {})
                if writes(n.body, ent, lists):
                    pres[name][bit] = 1
    for n in lines:
        if n.d == "field":
            out.put(encode_value(n, ent[n.key]) if n.key in ent else 0, n.bits)
        elif n.d == "presence":
            for b in range(1, n.bits + 1):
                out.put(pres.get(n.name, {}).get(b, 0), 1)
        elif n.d == "if":
            if all(pres.get(name, {}).get(bit, 0) == (0 if neg else 1) for neg, name, bit in n.conds):
                encode_scope(n.body, out, ent, lists)
        elif n.d == "group":
            items = lists.get(n.key, [])
            out.put(len(items), n.count)
            for item in items:
                encode_scope(n.body, out, item, item.get("@lists", {}))


def encode(pack, name, ent, lists):
    kind = next(k for k in pack.kinds if k.name == name)
    out = Bits()
    for n in kind.lines:
        if n.d == "when":
            out.put(int(n.value), n.bits)
    encode_scope([n for n in kind.lines if n.d != "when"], out, ent, lists)
    return out.bytes()


def check_vectors(pack, vectors):
    n, seen = 0, set()
    for fn, text in vectors:
        vec = json.loads(text)
        try:
            kname, ent, lists = decode(pack, bytes.fromhex(vec["input"]))
            for key, want in vec.get("model", {}).items():
                got = kname if key == "@kind" else (str(len(lists[key[:-2]])) if key.endswith(".#") else ent.get(key))
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

def pack_md(plan, sha, tag, nvec):
    o = []
    a = o.append
    a("# Pack: %s" % FORMAT)
    a("")
    a("RTCM 3 (RTCM 10403.x) message bodies, one kind per message number, from the")
    a("message definitions of `%s` (`%s/rtcmtypes_core.py`, `rtcmtypes_get.py`)" % (REPO, PKG_DIR))
    a("at %s, commit `%s`. Public. Generated by `tools/gen/rtcm2pack.py`; do not edit" % (tag, sha))
    a("`pack.def`, this file, `PROVENANCE.md`, `model/%s.def` or the vectors by hand." % MODULE)
    a("")
    a("Status: Built. Generated and checked by the generator's own serializer and codec.")
    a("")
    a("No RTCM document was read: the definitions are pyrtcm's BSD-licensed")
    a("restatement, read as Python syntax trees.")
    a("")
    a("## The message")
    a("")
    a("`wire bits`, `layout sequential`, `bit_order msb`; hex text. The message is the")
    a("body of one RTCM 3 frame: what follows the frame header (the preamble 0xD3, six")
    a("reserved bits and the 10-bit length) and comes before the 24-bit CRC. A framer")
    a("adds and checks those (the item \"Layered wires and framing\" of")
    a("`docs/roadmap.md`). The body is read in order, most significant bit first; a")
    a("message whose bit count is not a multiple of 8 ends in zero padding bits, as")
    a("the frame carries it. The message number (data field DF002, 12 bits) is the")
    a("kind's `when`.")
    a("")
    a("## Messages")
    a("")
    a("| Kind | Message number | Parts |")
    a("|---|---|---|")
    for k in plan.kinds:
        parts = []
        if any(l.d == "group" for l in walk(k.lines)):
            parts.append("counted groups")
        if any(l.d == "if" for l in walk(k.lines)):
            parts.append("parts gated by presence bits")
        a("| `%s` | %d | %s |" % (k.name, k.num, ", ".join(parts) or "fixed fields"))
    a("")
    a("## What is mapped")
    a("")
    a("| Data field type | Transform | Model type |")
    a("|---|---|---|")
    a("| `UINT`, `BIT` | `uint`; with an integer scale `uiscale`, with another `uscale` | int, int, float |")
    a("| `INT` (two's complement) | `twos`; `siscale`; `sscale` | int, int, float |")
    a("| `INTS` (sign and magnitude) | `smag`; with a scale `smscale` | int, float |")
    a("| `CHA` (characters) | `ascii` | string |")
    a("| `STR` (one byte of a UTF-8 string in a group) | `uint` | int |")
    a("")
    a("A scale is the resolution the source gives the data field, as an exact")
    a("fraction (decimal text where a fraction does not fit 64 bits); the source")
    a("states no unit, so the module declares none (`-`). A group repeated by the")
    a("field just before it is a `group … count <bits>`: that field is the count and")
    a("has no key. A group with a fixed number of repeats is written out, `_01`,")
    a("`_02`, … appended. A run of 1-bit flags followed by the parts each flag gates")
    a("is a `presence` line and one `if` block per part.")
    a("")
    a("### Core keys")
    a("")
    a("None. The reference station position (messages 1005 and 1006, data fields")
    a("DF025 to DF027) is geocentric (ECEF) and the source states no unit for it, so")
    a("it stays raw; the 0.16 derives `lat_of_ecef`, `lon_of_ecef` and `hae_of_ecef`")
    a("would give a position from it once the unit (metres) is shown by a source.")
    a("Ephemeris and time fields stay raw.")
    a("")
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own keys, so an entity from another format" % MAX_REQUIRES)
    a("selects a kind only when it holds them.")
    a("")
    a("## What is not mapped")
    a("")
    a("| Message | Reason |")
    a("|---|---|")
    for m, why in plan.not_built:
        a("| %s | %s |" % (m, why))
    a("")
    mask = sum(1 for _, w in plan.not_built if "masks" in w)
    if mask:
        a("%d MSM messages need a count that is the number of 1 bits in a mask (a" % mask)
        a("popcount), which the pack language does not have.")
        a("")
    a("- The frame header and the CRC-24Q (see The message).")
    a("- Enumerations and flag fields are carried as integers.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-<message>-<kind>.json`: one same-format round trip per kind, the")
    a("body written by a serializer in the generator from sample bit patterns; a kind")
    a("with a counted group also has one with no items (`-no-items`), and a kind with")
    a("gated parts one with some parts absent (`-some-absent`). No conversion vector:")
    a("no field binds a core key.")
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
             "| what the pack takes | message numbers; data field numbers, types, bit sizes and resolutions; group and presence structure; no description text |",
             "| generator | `tools/gen/rtcm2pack.py` |", ""]
    return "\n".join(rows)


def write_sources_provenance(out, src, sha, tag):
    lic = read_text(os.path.join(src, "LICENSE"))
    o = ["# Provenance of the RTCM 3 inputs", "",
         "| Fact | Value |", "|---|---|",
         "| repository | %s |" % REPO,
         "| tag | `%s` |" % tag,
         "| commit | `%s` (the commit of the tag, read 2026-11-19) |" % sha,
         "| archive | `https://codeload.github.com/semuconsulting/pyrtcm/tar.gz/%s` |" % sha,
         "| license | %s: the file `LICENSE` at the root of the commit, verbatim below |" % LICENSE_LINE,
         "",
         "The definition files say in their header that their content was taken from",
         "the RTCM standard 10403.3 (copyright RTCM). This repository reads only the",
         "definition files of pyrtcm, never an RTCM document, and takes no description",
         "text from them.",
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
    total = check_vectors(pack, [(n, out.read("%s/vectors/%s" % (pdir, n))) for n, _ in vecs])
    out.write(pdir + "/pack.md", pack_md(plan, sha, tag, len(vecs)))
    out.write(pdir + "/PROVENANCE.md", provenance_md(sha, tag, table))
    reasons = collections.Counter(re.sub(r"\b(DF|IDF)\d+(_\d+)?\b", "DF…", re.sub(r"\(.*?\)", "(…)", w))
                                  for _, w in plan.not_built)
    return ["tag             %s (commit %s)" % (tag, sha),
            "messages        %d, kinds %d" % (len(plan.src.payloads), len(plan.kinds)),
            "not built       %d" % len(plan.not_built)] + ["  %3d  %s" % (n, w) for w, n in reasons.most_common()] + [
            "keys            %d, lists %d" % (len(plan.keys), len(plan.lists)),
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
