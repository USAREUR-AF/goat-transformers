#!/usr/bin/env python3
"""Generate goat-transformers packs from the Swift Navigation Binary Protocol
(SBP) message definitions (github.com/swift-nav/libsbp, spec/yaml).

Reads   <src>/spec/yaml/swiftnav/sbp/*.yaml and <src>/LICENSE;
        tools/gen/sources/sbp-PROVENANCE.md (the tag, commit and SHA-256 of every
        file; a file that differs is refused)
Writes  <out>/model/sbp.def                    the frame-header key `sender`
        <out>/model/sbp<package>.def           one module per YAML package
        <out>/packs/sbp-<package>/pack.def     one pack per package, one kind per
        <out>/packs/sbp-<package>/pack.md      message
        <out>/packs/sbp-<package>/PROVENANCE.md
        <out>/packs/sbp-<package>/vectors/*.json
        tools/gen/sources/sbp-PROVENANCE.md   (only with --commit)

The message is one SBP frame from the preamble through the payload: preamble
0x55, message type (u16, little-endian), sender (u16), payload length (u8),
payload, without the CRC (a framer adds and checks it). A kind is selected by the
message type and, for a message of fixed size, the payload length.

Every vector's frame is written by an SBP serializer in this file from the
YAML field layout (fields in order, little-endian, no padding); the generator
then loads the pack with gtcheck and decodes and encodes every vector with its
own codec of the bits wire.

Python 3 standard library only. Exit status 0 when every check passed, 1 for a
refused input or a failed check, 2 for a usage error.
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
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

NAME = "sbp2pack"
VERSION = "0.1.0"
REPO = "https://github.com/swift-nav/libsbp"
PROV = "tools/gen/sources/sbp-PROVENANCE.md"
YAML_DIR = "spec/yaml/swiftnav/sbp"
HEADER_MODULE = "sbp"
PREAMBLE = 0x55
PAYLOAD_BIT0 = 48               # preamble 8, type 16, sender 16, length 8
MAX_UNROLL = 255                # a fixed array of more elements is not mapped (a payload holds 255 bytes)
MAX_REQUIRES = 3
LICENSE_LINE = "MIT, copyright (c) 2015-2021 Swift Navigation"


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


# --------------------------------------------------------------- YAML subset ---
# The libsbp definitions use a small part of YAML: block mappings and
# sequences by indentation (a sequence may sit at its key's indentation),
# plain, quoted and folded (`>`) scalars, plain scalars over several lines,
# flow sequences, and `#` comments. This reader handles exactly that.

class YamlError(Exception):
    pass

def _strip_comment(s):
    out, q = [], None
    for i, c in enumerate(s):
        if q:
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        out.append(c)
    return "".join(out).rstrip()


def scalar(t):
    t = t.strip()
    if not t:
        return None
    if t[0] in "'\"" and t[-1] == t[0] and len(t) >= 2:
        return t[1:-1].replace("''", "'") if t[0] == "'" else t[1:-1]
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [scalar(x) for x in _split_flow(inner)] if inner else []
    return t


def _split_flow(s):
    parts, depth, cur, q = [], 0, [], None
    for c in s:
        if q:
            cur.append(c)
            if c == q:
                q = None
            continue
        if c in "'\"":
            q = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append("".join(cur)); cur = []
            continue
        cur.append(c)
    parts.append("".join(cur))
    return parts


def load(text):
    raw = text.split("\n")
    lines = []                         # [indent, text, raw line] of content lines
    for r in raw:
        if not r.strip() or r.lstrip().startswith("#"):
            lines.append(None)
            continue
        lines.append(r)
    p = _Parser(lines)
    return p.block(0, -1)


class _Parser:
    def __init__(self, lines):
        self.lines, self.i = lines, 0

    def peek(self):
        while self.i < len(self.lines) and self.lines[self.i] is None:
            self.i += 1
        if self.i >= len(self.lines):
            return None
        r = self.lines[self.i]
        return len(r) - len(r.lstrip(" ")), r.strip()

    def block(self, _unused, parent_indent):
        nxt = self.peek()
        if nxt is None or nxt[0] <= parent_indent:
            return None
        ind, t = nxt
        if t.startswith("- ") or t == "-":
            return self.seq(ind)
        if not _is_key(t):
            # a plain scalar on the lines below its key (folded)
            texts = []
            while True:
                nxt = self.peek()
                if nxt is None or nxt[0] <= parent_indent:
                    break
                texts.append(_strip_comment(nxt[1]))
                self.i += 1
            return scalar(" ".join(texts))
        return self.mapping(ind)

    def seq(self, ind):
        out = []
        while True:
            nxt = self.peek()
            if nxt is None or nxt[0] != ind or not (nxt[1].startswith("- ") or nxt[1] == "-"):
                break
            r = self.lines[self.i]
            rest = r[ind + 1:]
            item_ind = ind + 1 + (len(rest) - len(rest.lstrip(" ")))
            content = rest.strip()
            if not content:
                self.i += 1
                out.append(self.block(0, ind))
            elif _is_key(content):
                # an inline mapping: rewrite the line so its key sits at item_ind
                self.lines[self.i] = " " * item_ind + content
                out.append(self.mapping(item_ind))
            else:
                self.i += 1
                out.append(scalar(_strip_comment(content)))
        return out

    def mapping(self, ind):
        out = {}
        while True:
            nxt = self.peek()
            if nxt is None or nxt[0] != ind or nxt[1].startswith("- "):
                if nxt is not None and nxt[0] > ind:
                    raise YamlError("line %d: unexpected indentation" % (self.i + 1))
                break
            t = _strip_comment(nxt[1])
            # A plain key character excludes quotes, so each character has one
            # reading and the match cannot backtrack exponentially.
            m = re.match(r"^((?:'[^']*'|\"[^\"]*\"|[^:'\"])+?)\s*:(?:\s+(.*))?$", t)
            if not m:
                raise YamlError("line %d: not a key: %r" % (self.i + 1, t))
            key, val = scalar(m.group(1)), (m.group(2) or "").strip()
            self.i += 1
            if val in (">", "|", ">-", "|-", ">+", "|+"):
                out[key] = self.block_scalar(ind, val[0])
            elif val:
                # a plain scalar may go on over more-indented lines (folded)
                more = []
                while True:
                    nxt = self.peek()
                    if nxt is None or nxt[0] <= ind:
                        break
                    more.append(_strip_comment(nxt[1]))
                    self.i += 1
                out[key] = scalar(" ".join([val] + more)) if more else scalar(val)
            else:
                nxt = self.peek()
                if nxt is not None and nxt[0] == ind and (nxt[1].startswith("- ") or nxt[1] == "-"):
                    out[key] = self.seq(ind)          # a sequence may sit at its key's indent
                else:
                    out[key] = self.block(0, ind)
        return out

    def block_scalar(self, ind, style):
        texts, first = [], None
        while self.i < len(self.lines):
            r = self.lines[self.i]
            if r is None:
                texts.append("")
                self.i += 1
                continue
            k = len(r) - len(r.lstrip(" "))
            if k <= ind:
                break
            if first is None:
                first = k
            texts.append(r[first:] if k >= first else r.strip())
            self.i += 1
        while texts and texts[-1] == "":
            texts.pop()
        if style == "|":
            return "\n".join(texts) + "\n"
        return " ".join(t for t in texts if t)        # folded, enough for descriptions


def _is_key(content):
    t = _strip_comment(content)
    return bool(re.match(r"^((?:'[^']*'|\"[^\"]*\"|[^:\s][^:]*?))\s*:(\s|$)", t)) and not t.startswith(("'", '"')) or \
        bool(re.match(r"^('[^']*'|\"[^\"]*\")\s*:(\s|$)", t))


# ------------------------------------------------------------------ parse ---

PRIMS = {"u8": 1, "u16": 2, "u32": 4, "u64": 8, "s8": 1, "s16": 2, "s32": 4, "s64": 8,
         "float": 4, "double": 8}


class Package:
    def __init__(self, name, path, doc):
        self.name, self.path = name, path                 # name: the last part, `navigation`
        self.messages, self.types = [], {}
        for item in doc.get("definitions") or []:
            (key, spec), = item.items()
            if not isinstance(spec, dict):
                continue
            if "id" in spec:
                self.messages.append((key, int(str(spec["id"]), 0), spec))
            elif spec.get("type") not in ("primitive", "collection", "basic"):
                self.types[key] = spec


def field_list(spec):
    """[(name, field spec)] of a message or type definition."""
    out = []
    for item in spec.get("fields") or []:
        (name, fs), = item.items()
        out.append((str(name), fs or {}))
    return out


def load_packages(src):
    base = os.path.join(src, YAML_DIR)
    packages = []
    for f in sorted(os.listdir(base)):
        if f.endswith(".yaml"):
            doc = load(read_text(os.path.join(base, f)))
            pkg = str(doc.get("package", "")).rsplit(".", 1)[-1]
            if not pkg:
                raise GenError("%s names no package" % f)
            packages.append(Package(pkg, "%s/%s" % (YAML_DIR, f), doc))
    types = {}
    for p in packages:
        for k, v in p.types.items():
            if k in types:
                raise GenError("type %s defined twice" % k)
            types[k] = v
    ids = collections.Counter(mid for p in packages for _, mid, _ in p.messages)
    dup = [hex(i) for i, c in ids.items() if c > 1]
    if dup:
        raise GenError("message ids used twice: %s" % dup)
    return packages, types


def source_files(src):
    base = os.path.join(src, YAML_DIR)
    return ["%s/%s" % (YAML_DIR, f) for f in sorted(os.listdir(base)) if f.endswith(".yaml")]


# ------------------------------------------------------------------- plan ---

class Variable(Exception):
    """A part of the message whose length is not fixed; the text says what."""


Leaf = collections.namedtuple("Leaf", "path base offset size units desc strlen")
Leaf.__doc__ = """A field at a fixed payload offset: `base` is a primitive name or
`string`; `strlen` the byte length of a string."""


def type_size(t, types, where):
    if t in PRIMS:
        return PRIMS[t]
    if t in types:
        return sum(spec_size(fs, types, where) for _, fs in field_list(types[t]))
    raise GenError("%s: unknown type %s" % (where, t))


def spec_size(fs, types, where):
    t = fs.get("type")
    if t == "string":
        if "size" not in fs:
            raise Variable("a string with no stated length")
        return int(fs["size"])
    if t == "array":
        if "size" not in fs:
            raise Variable("an array counted by field `%s`" % fs["size_fn"] if "size_fn" in fs
                           else "an array with no stated length")
        return int(fs["size"]) * type_size(str(fs["fill"]), types, where)
    return type_size(str(t), types, where)


def flatten(fields, types, prefix, offset, where, leaves, skipped):
    """Append the leaves of `fields` from byte `offset`; the offset after them."""
    for name, fs in fields:
        t = str(fs.get("type"))
        path = prefix + [name]
        if t in PRIMS:
            leaves.append(Leaf(path, t, offset, PRIMS[t], fs.get("units"), fs.get("desc"), None))
            offset += PRIMS[t]
        elif t == "string":
            n = spec_size(fs, types, where)
            if 8 * n > 2040:
                skipped.append(("_".join(path), "string of %d bytes (more than 255)" % n))
            else:
                leaves.append(Leaf(path, "string", offset, n, None, fs.get("desc"), n))
            offset += n
        elif t == "array":
            n = int(fs["size"]) if "size" in fs else None
            if n is None:
                spec_size(fs, types, where)                # raises Variable
            fill = str(fs["fill"])
            esize = type_size(fill, types, where)
            if n > MAX_UNROLL:
                skipped.append(("_".join(path), "array of %d elements (more than %d)" % (n, MAX_UNROLL)))
                offset += n * esize
                continue
            for i in range(n):
                if fill in PRIMS:
                    leaves.append(Leaf(path + [str(i)], fill, offset, esize, fs.get("units"), fs.get("desc"), None))
                    offset += esize
                else:
                    offset = flatten(field_list(types[fill]), types, path + [str(i)], offset, where, leaves, skipped)
        elif t in types:
            offset = flatten(field_list(types[t]), types, path, offset, where, leaves, skipped)
        else:
            raise GenError("%s: unknown type %s" % (where, t))
    return offset


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return s if s and not s[0].isdigit() else "x" + s


UNIT = r"([A-Za-z][A-Za-z0-9/^ -]*?|\([A-Za-z][A-Za-z0-9/^ -]*\))"
UNIT_NUM_FIRST = re.compile(r"^(\d+(?:\.\d+)?(?:e-?\d+)?)\s+" + UNIT + r"$")
UNIT_DIVIDED = re.compile(r"^" + UNIT + r"\s*/\s*(\d+)$")
UNIT_DIVIDED_POW2 = re.compile(r"^" + UNIT + r"\s*/\s*\(\s*2\s*\^\s*(\d+)\s*\)$")
UNIT_TIMES = re.compile(r"^" + UNIT + r"\s*\*\s*(\d+(?:\.\d+)?)$")
UNIT_TIMES_POW2 = re.compile(r"^" + UNIT + r"\s*\*\s*2\s*\^\s*-(\d+)$")


def unit_scale(units):
    """(factor as a Fraction, base unit) for units that state a scale in the
    unit text (`0.005 m`, `dB Hz / 4`, `m * 0.02`), else None."""
    if not units:
        return None
    u = str(units).strip()
    found = None
    m = UNIT_NUM_FIRST.match(u)
    if m:
        found = Fraction(Decimal(m.group(1))), m.group(2)
    for rx, fac in ((UNIT_DIVIDED, lambda g: Fraction(1, int(g))),
                    (UNIT_DIVIDED_POW2, lambda g: Fraction(1, 2 ** int(g))),
                    (UNIT_TIMES, lambda g: Fraction(Decimal(g))),
                    (UNIT_TIMES_POW2, lambda g: Fraction(1, 2 ** int(g)))):
        m = found is None and rx.match(u)
        if m:
            found = fac(m.group(2)), m.group(1)
    if found is None or found[0] == 0:
        return None
    base = found[1].strip()
    if base.startswith("(") and base.endswith(")"):
        base = base[1:-1].strip()
    return found[0], re.sub(r"\s+", " ", re.sub(r"\s*([/*^])\s*", r"\1", base))


def unit_token(units):
    if not units:
        return "-"
    t = re.sub(r"\s+", "_", str(units).strip())
    return "-" if not t or any(c in t for c in '"#') else t


def factor_text(f):
    return str(f.numerator) if f.denominator == 1 else "%d/%d" % (f.numerator, f.denominator)


Line = collections.namedtuple("Line", "key pos bits tr leaf")


class KindPlan:
    def __init__(self, name, msg_name, msg_id, size, lines, requires):
        self.name, self.msg_name, self.msg_id, self.size = name, msg_name, msg_id, size
        self.lines, self.requires = lines, requires

    @property
    def mapped_len(self):
        return max(((l.pos + l.bits + 7) // 8 for l in self.lines), default=PAYLOAD_BIT0 // 8) - PAYLOAD_BIT0 // 8


def is_lat_lon(leaf):
    """`lat` or `lon` for a double in degrees named lat or lon whose description
    starts with Latitude or Longitude, else None."""
    name = leaf.path[-1]
    desc = str(leaf.desc or "").strip().lower()
    if leaf.base != "double" or str(leaf.units).strip() != "deg" or len(leaf.path) != 1:
        return None
    if name == "lat" and desc.startswith("latitude"):
        return "lat"
    if name == "lon" and desc.startswith("longitude"):
        return "lon"
    return None


# Velocity and course fields whose definition states the meaning that a core or
# track key holds: (field name, base type, unit, start of the description in
# lower case, key, transform). The unit is converted exactly: mm/s to m/s,
# microdegrees to degrees; down is the negative of up.
MOTION = [
    ("n", "s32", "mm/s", "velocity north coordinate", "track.vel_north_ms", "sscale:1/1000"),
    ("e", "s32", "mm/s", "velocity east coordinate", "track.vel_east_ms", "sscale:1/1000"),
    ("d", "s32", "mm/s", "velocity down coordinate", "track.vel_up_ms", "sscale:-0.001"),
    ("v_up", "s32", "mm/s", "vertical velocity component (positive up)", "track.vel_up_ms", "sscale:1/1000"),
    ("cog", "u32", "microdegrees", "course over ground relative to north direction", "course", "uscale:1/1000000"),
    ("sog", "u32", "mm/s", "speed over ground", "speed_ms", "uscale:1/1000"),
]


def motion(leaf):
    if len(leaf.path) != 1:
        return None
    desc = re.sub(r"\s+", " ", str(leaf.desc or "").strip().lower())
    for name, base, unit, start, key, tr in MOTION:
        if leaf.path[0] == name and leaf.base == base and str(leaf.units).strip() == unit and desc.startswith(start):
            return key, tr
    return None


def is_hae(leaf):
    desc = str(leaf.desc or "").lower()
    return (leaf.base == "double" and str(leaf.units).strip() == "m" and leaf.path == ["height"]
            and "above wgs84 ellipsoid" in re.sub(r"\s+", " ", desc))


class PackagePlan:
    def __init__(self, pkg, types):
        self.pkg = pkg
        self.format = "sbp-" + pkg.name.replace("_", "-")
        self.module = "sbp" + re.sub(r"[^a-z0-9]", "", pkg.name)
        self.kinds, self.keys = [], collections.OrderedDict()
        self.not_built = []            # (message, id, reason)
        self.skipped = []              # (message, field, reason)
        self.core = []                 # (kind, field, core or track key, transform)
        self.scaled = []               # (kind, field, units, transform)
        for msg_name, mid, spec in pkg.messages:
            self.plan_message(msg_name, mid, spec, types)
        own = self.module + "."
        usage = collections.Counter(l.key for k in self.kinds for l in k.lines if l.key.startswith(own))
        for k in self.kinds:
            raw = [l.key for l in k.lines if l.key.startswith(own)]
            ranked = sorted(range(len(raw)), key=lambda i: (usage[raw[i]], i))
            k.requires = [raw[i] for i in sorted(ranked[:MAX_REQUIRES])]

    def plan_message(self, msg_name, mid, spec, types):
        leaves, skipped = [], []
        fields = field_list(spec)
        try:
            size = flatten(fields, types, [], 0, msg_name, leaves, skipped)
        except Variable as e:
            last = fields[-1][1] if fields else {}
            trailing = (last.get("type") in ("string", "array") and "size" not in last
                        and "size_fn" not in last)
            self.not_built.append((msg_name, mid, ("ends in %s that runs to the end of the frame" % e)
                                   if trailing else str(e)))
            return
        if size > 255:
            self.not_built.append((msg_name, mid, "payload of %d bytes (the length byte holds 255)" % size))
            return
        kind = slug(re.sub(r"^MSG_", "", msg_name))
        cores = {}
        for leaf in leaves:
            c = is_lat_lon(leaf)
            if c:
                cores[c] = leaf
        pair = set(cores) == {"lat", "lon"}
        moves = {m[0]: leaf for leaf in leaves for m in [motion(leaf)] if m}
        ned = {"track.vel_north_ms", "track.vel_east_ms"} <= set(moves)
        cog = {"course", "speed_ms"} <= set(moves)
        lines = []
        for leaf in leaves:
            pos, bits = PAYLOAD_BIT0 + 8 * leaf.offset, 8 * leaf.size
            core = is_lat_lon(leaf) if pair else None
            if not core and pair and is_hae(leaf):
                core = "hae"
            if core:
                lines.append(Line(core, pos, bits, "f64", leaf))
                self.core.append((kind, "_".join(leaf.path), core, "f64"))
                continue
            mv = motion(leaf)
            if mv and (ned if mv[0].startswith("track.vel_") and leaf.path[0] in "ned" else cog):
                lines.append(Line(mv[0], pos, bits, mv[1], leaf))
                self.core.append((kind, "_".join(leaf.path), mv[0], mv[1]))
                continue
            key = "%s.%s_%s" % (self.module, kind, "_".join(p if p.isdigit() else slug(p) for p in leaf.path))
            if leaf.base == "string":
                tr, typ, unit = "ascii", "string", "-"
            elif leaf.base in ("float", "double"):
                tr, typ, unit = ("f32" if leaf.base == "float" else "f64"), "float", unit_token(leaf.units)
            else:
                sc = unit_scale(leaf.units)
                if sc and sc[0] == 1:          # `1 day`: an integer in the base unit
                    tr, typ, unit = ("twos" if leaf.base[0] == "s" else "uint"), "int", unit_token(sc[1])
                elif sc:
                    tr = ("sscale:" if leaf.base[0] == "s" else "uscale:") + factor_text(sc[0])
                    typ, unit = "float", unit_token(sc[1])
                    self.scaled.append((kind, "_".join(leaf.path), str(leaf.units), tr))
                else:
                    tr, typ, unit = ("twos" if leaf.base[0] == "s" else "uint"), "int", unit_token(leaf.units)
            name = key.split(".", 1)[1]
            if name in self.keys:
                raise GenError("%s: key %s twice" % (msg_name, name))
            self.keys[name] = (typ, unit, msg_name, "_".join(leaf.path))
            lines.append(Line(key, pos, bits, tr, leaf))
        for f, why in skipped:
            self.skipped.append((msg_name, f, why))
        if not any(l.key.startswith(self.module + ".") for l in lines):
            self.not_built.append((msg_name, mid, "an empty payload: a kind needs at least one field"
                                   if not leaves else "every field binds a shared key: no key of its own "
                                   "would select the kind on encode"))
            return
        if any(k.name == kind for k in self.kinds):
            raise GenError("two messages give the kind %s" % kind)
        self.kinds.append(KindPlan(kind, msg_name, mid, size, lines, []))


# ------------------------------------------------------------------- emit ---

def loc(pos, n):
    return "0:%d:%d" % (pos, n)


def pack_text(pp, sha, tag):
    o = ["# SBP frames of the package swiftnav.sbp.%s, one kind per message." % pp.pkg.name,
         "# Generated by tools/gen/sbp2pack.py; do not edit by hand.",
         "# The message is one SBP frame from the preamble through the payload:",
         "# preamble 0x55, message type (u16), sender (u16), length (u8), payload.",
         "# The message carries no CRC: a framer adds and checks it. Payload bit 0 is bit %d." % PAYLOAD_BIT0,
         "format        %s" % pp.format,
         "version       %s" % VERSION,
         "distribution  public",
         'source        "%s %s at %s (commit %s)"' % (REPO, pp.pkg.path, tag, sha),
         "uses          %s" % HEADER_MODULE,
         "uses          %s" % pp.module] + (
        ["uses          track"] if any(c[2].startswith("track.") for c in pp.core) else []) + [
         "wire          bits",
         "bit_order     lsb",
         "word_bytes    1",
         "when   %s %d" % (loc(0, 8), PREAMBLE),
         "field  %s.sender %s uint" % (HEADER_MODULE, loc(24, 16))]
    for k in pp.kinds:
        o.append("")
        o.append("kind      %s" % k.name)
        o.append("when      %s %d" % (loc(8, 16), k.msg_id))
        o.append("when      %s %d" % (loc(40, 8), k.size))
        if k.requires:
            o.append("requires  %s" % " ".join(k.requires))
        for l in k.lines:
            o.append("field     %s %s %s" % (l.key, loc(l.pos, l.bits), l.tr))
    return "\n".join(o) + "\n"


def module_text(pp, sha, tag):
    o = ["# The %s module: the message fields of the SBP package swiftnav.sbp.%s." % (pp.module, pp.pkg.name),
         "# Generated by tools/gen/sbp2pack.py; do not edit by hand. A key is",
         "# <message>_<field path>, in the unit the definition states (a scale written",
         "# in the unit text is applied: the key holds the base unit).",
         "module        %s" % pp.module,
         "version       %s" % VERSION,
         "distribution  public",
         'source        "%s %s at %s (commit %s)"' % (REPO, pp.pkg.path, tag, sha)]
    for name, (typ, unit, mname, fname) in pp.keys.items():
        o.append('key  %s  %s  %s  "field %s of %s"' % (name, typ, unit, fname, mname))
    return "\n".join(o) + "\n"


def header_module_text(sha, tag):
    return "\n".join([
        "# The sbp module: the SBP frame-header keys shared by every SBP pack.",
        "# Generated by tools/gen/sbp2pack.py; do not edit by hand.",
        "module        %s" % HEADER_MODULE,
        "version       %s" % VERSION,
        "distribution  public",
        'source        "%s %s/base.yaml at %s (commit %s)"' % (REPO, YAML_DIR, tag, sha),
        'key  sender  int  -  "SBP frame header: the sender id of the frame"',
        ""])


# ------------------------------------------------- SBP serializer (vectors) ---

def crc16(data):
    """CRC-16-CCITT as SBP frames use it: polynomial 0x1021, initial value 0, no
    reflection, no final XOR, computed bit by bit."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


STRUCT = {"u8": "B", "u16": "H", "u32": "I", "u64": "Q", "s8": "b", "s16": "h", "s32": "i", "s64": "q",
          "float": "f", "double": "d"}


def put(payload, leaf, value):
    if leaf.base == "string":
        payload[leaf.offset:leaf.offset + leaf.size] = value.encode("ascii").ljust(leaf.size, b"\0")
    else:
        payload[leaf.offset:leaf.offset + leaf.size] = struct.pack("<" + STRUCT[leaf.base], value)


def frame(msg_id, sender, payload, with_crc, length=None):
    """The frame of `payload`; the length byte is `length` when the payload
    given is only the mapped part of a longer one."""
    body = struct.pack("<HHB", msg_id, sender, len(payload) if length is None else length) + bytes(payload)
    out = bytes([PREAMBLE]) + body
    return out + struct.pack("<H", crc16(body)) if with_crc else out


def sample(leaf, line, salt):
    if line.key == "lat":
        return 47.25 + (salt % 97) * 0.001953125
    if line.key == "lon":
        return -8.5 - (salt % 89) * 0.001953125
    if line.key == "hae":
        return 400.0 + (salt % 50) * 0.25
    if leaf.base == "string":
        return ("S%d" % (salt % 97))[:leaf.size]
    if leaf.base in ("float", "double"):
        return ((salt % 41) - 20) * 0.25
    bits = 8 * leaf.size
    if leaf.base[0] == "u":
        v = (salt * 2654435761 + 12345) % min(1 << bits, 1 << 31)
        if bits == 64 and salt % 2:
            v |= 1 << 63
        return v
    span = min(1 << bits, 1 << 31)
    return (salt * 40503 + 7) % span - span // 2


# Cross-format cases: (message, sender, field values, expected GeoJSON written by
# hand: coordinates are [lon, lat, height], the three doubles as they are).
CROSS = [
    ("MSG_POS_LLH", 0x88D3,
     {"tow": 326825000, "lat": 47.397742, "lon": 8.545594, "height": 488.25,
      "h_accuracy": 12, "v_accuracy": 20, "n_sats": 14, "flags": 2},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.545594,47.397742,488.25]},"properties":{}}'),
]


def vector_text(pairs):
    return json.dumps(collections.OrderedDict(pairs), indent=2) + "\n"


def vector_files(pp):
    files = []
    for i, k in enumerate(pp.kinds):
        payload = bytearray(k.size)
        for j, l in enumerate(k.lines):
            put(payload, l.leaf, sample(l.leaf, l, k.msg_id * 31 + j * 7 + 3))
        if k.mapped_len != k.size:
            raise GenError("%s: the mapped fields end before the payload does" % k.msg_name)
        data = frame(k.msg_id, 0x0100 + i % 256, payload, False).hex()
        files.append(("rt-%04x-%s.json" % (k.msg_id, k.name), vector_text([
            ("name", "%s-roundtrip-%s" % (pp.format, k.name)), ("from", pp.format), ("to", pp.format),
            ("input", data), ("expect", data), ("model", {"@kind": k.name})])))
    by_name = {k.msg_name: k for k in pp.kinds}
    for n, (name, sender, values, expect) in enumerate(CROSS, 1):
        if name not in by_name:
            continue
        k = by_name[name]
        payload = bytearray(k.size)
        for l in k.lines:
            put(payload, l.leaf, values["_".join(l.leaf.path)])
        model = collections.OrderedDict([("@kind", k.name)])
        for l in k.lines:
            if l.key in ("lat", "lon", "hae"):
                model[l.key] = fmt_float(values["_".join(l.leaf.path)])
        model[HEADER_MODULE + ".sender"] = str(sender)
        files.append(("x-%02d-%s-to-geojson.json" % (n, k.name), vector_text([
            ("name", "%s-%s-to-geojson" % (pp.format, k.name)), ("from", pp.format), ("to", "geojson"),
            ("input", frame(k.msg_id, sender, payload, False).hex()), ("expect", expect), ("model", model)])))
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
    if 8 * len(data) < max(n.start + n.bits for n in lines if n.d in ("when", "field")):
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
        elif n.d == "when":
            acc |= int(n.value) << n.start
    nbytes = (max(n.start + n.bits for n in lines if n.d in ("when", "field")) + 7) // 8
    return acc.to_bytes(nbytes, "little")


def geojson(ent):
    if "lat" in ent and "lon" in ent:
        coords = [fmt_float(ent["lon"]), fmt_float(ent["lat"])] + ([fmt_float(ent["hae"])] if "hae" in ent else [])
        geom = '{"type":"Point","coordinates":[%s]}' % ",".join(coords)
    else:
        geom = "null"
    return '{"type":"Feature","geometry":%s,"properties":{}}' % geom


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

def pack_md(pp, sha, tag, nvec):
    o = []
    a = o.append
    a("# Pack: %s" % pp.format)
    a("")
    a("SBP (Swift Navigation Binary Protocol) frames of the message package")
    a("`swiftnav.sbp.%s`, from `%s` (`%s`) at %s, commit `%s`." % (pp.pkg.name, REPO, pp.pkg.path, tag, sha))
    a("Public. Generated by `tools/gen/sbp2pack.py`; do not edit `pack.def`, this file,")
    a("`PROVENANCE.md`, `model/%s.def` or the vectors by hand." % pp.module)
    a("")
    a("Status: Built. Generated and checked by the generator's own serializer and codec.")
    a("")
    a("## The message")
    a("")
    a("`wire bits`, `bit_order lsb`, `word_bytes 1`; hex text. One SBP frame from the")
    a("preamble through the payload; all numbers are little-endian:")
    a("")
    a("| Bytes | Content | In the pack |")
    a("|---|---|---|")
    a("| 0 | preamble 0x55 | common `when` |")
    a("| 1-2 | message type | per-kind `when` |")
    a("| 3-4 | sender id | `sbp.sender` (module `sbp`, shared by every SBP pack) |")
    a("| 5 | payload length in bytes | per-kind `when` = the message's fixed size |")
    a("| 6 … | payload | the kind's `field` lines, at their offsets |")
    a("| after the payload | CRC-16 (2 bytes) | not mapped |")
    a("")
    a("The message is the frame without its CRC, in both directions: decode takes the")
    a("preamble, header and payload, and encode writes them. A framer adds the CRC")
    a("before sending and checks it on receipt: CRC-16 CCITT (polynomial 0x1021,")
    a("initial value 0) over the header and the payload, preamble excluded, written")
    a("little-endian after the payload. That is the item \"Layered wires and framing\"")
    a("of `docs/roadmap.md`. The fields of a payload follow one another with no")
    a("padding.")
    a("")
    a("## Messages")
    a("")
    a("| Kind | Message | Type id | Payload bytes |")
    a("|---|---|---|---|")
    for k in pp.kinds:
        a("| `%s` | %s | 0x%04X (%d) | %d |" % (k.name, k.msg_name, k.msg_id, k.msg_id, k.size))
    a("")
    a("## What is mapped")
    a("")
    a("| Definition | Transform | Model type |")
    a("|---|---|---|")
    a("| `u8` `u16` `u32` `u64` | `uint` | int |")
    a("| `s8` `s16` `s32` `s64` | `twos` | int |")
    a("| `float`, `double` | `f32`, `f64` | float |")
    a("| `string` of a stated size | `ascii` | string |")
    a("| an integer whose unit text states a scale (`0.005 m`, `dB Hz / 4`, `m * 0.02`) | `uscale` / `sscale` with that factor as an exact fraction, the key in the base unit | float |")
    a("| a nested type, or an array of a stated size (up to %d elements) | its fields in place, the path joined by `_` | as the field |" % MAX_UNROLL)
    a("")
    a("Keys are `%s.<message>_<field path>` in lower case, the message name without" % pp.module)
    a("`MSG_`. Bit fields inside an integer (a flags byte) are carried as the whole")
    a("integer.")
    if pp.scaled:
        a("")
        a("Scaled from the unit text:")
        a("")
        a("| Kind | Field | Unit text | Transform |")
        a("|---|---|---|---|")
        for k, f, u, tr in pp.scaled:
            a("| `%s` | `%s` | %s | `%s` |" % (k, f, u, tr))
    a("")
    a("### Core keys")
    a("")
    if pp.core:
        a("A key is bound only where the definition states the meaning and unit the")
        a("shared key holds; the unit is converted exactly by the transform:")
        a("")
        a("- `lat`, `lon`: a double in degrees named `lat` / `lon` that the definition")
        a("  describes as latitude / longitude; `hae`: in such a message, the double")
        a("  `height` in metres described as height above the WGS84 ellipsoid.")
        a("- `track.vel_north_ms`, `track.vel_east_ms`, `track.vel_up_ms`: the signed")
        a("  32-bit `n`, `e`, `d` in mm/s described as the north, east and down velocity")
        a("  coordinates (up is the negative of down), or `v_up` in mm/s described as the")
        a("  vertical velocity, positive up.")
        a("- `course`, `speed_ms`: the unsigned 32-bit `cog` in microdegrees described as")
        a("  the course over ground from north, and `sog` in mm/s described as the speed")
        a("  over ground.")
        a("")
        a("| Kind | Field | Key | Transform |")
        a("|---|---|---|---|")
        for k, f, c, tr in pp.core:
            a("| `%s` | `%s` | `%s` | `%s` |" % (k, f, c, tr))
        a("")
        a("Accuracy fields (standard deviations) and covariances stay raw: `ce` and `le`")
        a("are error bounds of another kind. Times stay raw: an SBP time is a week number")
        a("and a time of week on the satellite time scale, which give an epoch time only")
        a("together and only with the leap-second offset to UTC.")
    else:
        a("No key is bound to a `core` or `track` key: no message of this package states")
        a("a position, velocity or course with the meaning and unit of a shared key.")
    a("")
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own keys, so an entity from another format" % MAX_REQUIRES)
    a("selects a kind only when it holds them.")
    a("")
    a("## What is not mapped")
    a("")
    if pp.not_built:
        a("Messages with no kind:")
        a("")
        a("| Message | Type id | Reason |")
        a("|---|---|---|")
        for m, mid, why in pp.not_built:
            a("| %s | 0x%04X | %s |" % (m, mid, why))
        a("")
        trailing = sum(1 for _, _, w in pp.not_built if "end of the frame" in w)
        if trailing:
            a("%d of them end in an array or a string that runs to the end of the frame;" % trailing)
            a("stating one needs a trailing field whose length is what remains of the")
            a("payload (the payload length minus the fixed part).")
            a("")
    if pp.skipped:
        a("Fields not mapped:")
        a("")
        a("| Message | Field | Reason |")
        a("|---|---|---|")
        for m, f, why in pp.skipped:
            a("| %s | %s | %s |" % (m, f, why))
        a("")
    a("- The CRC (see The message), and frames whose payload length is not the")
    a("  message's fixed size: such a frame selects no kind (`no-kind`).")
    a("- Enumerations and bit fields are carried as integers.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-<type id>-<kind>.json`: one same-format round trip per kind, the frame")
    a("written by an SBP serializer in the generator from sample values (no CRC).")
    if any(name in {k.msg_name for k in pp.kinds} for name, _, _, _ in CROSS):
        a("")
        a("`vectors/x-*-to-geojson.json`: a frame (without its CRC) converted to GeoJSON;")
        a("the expected text is written by hand from the field values.")
    a("")
    a("%d vectors." % nvec)
    return "\n".join(o) + "\n"


def provenance_md(pp, sha, tag, table):
    return "\n".join([
        "# Provenance: %s" % pp.format,
        "",
        "| Fact | Value |",
        "|---|---|",
        "| repository | %s |" % REPO,
        "| tag | `%s` |" % tag,
        "| commit | `%s` |" % sha,
        "| definition read | `%s` (SHA-256 `%s`), and the type definitions of the other files of `%s/`, each with its SHA-256 in `%s` |" % (pp.pkg.path, table[pp.pkg.path], YAML_DIR, PROV),
        "| license | %s: `LICENSE` at the root of the commit (SHA-256 `%s`), verbatim in `%s`. Each YAML file's header comment refers to that file |" % (LICENSE_LINE, table["LICENSE"], PROV),
        "| date read | 2026-11-19 |",
        "| what the pack takes | message names and type ids; field names, types, sizes and units; no description text |",
        "| generator | `tools/gen/sbp2pack.py` |",
        ""])


def write_sources_provenance(out, src, sha, tag, files):
    lic = read_text(os.path.join(src, "LICENSE"))
    o = ["# Provenance of the SBP inputs",
         "",
         "| Fact | Value |",
         "|---|---|",
         "| repository | %s |" % REPO,
         "| tag | `%s` |" % tag,
         "| commit | `%s` (the commit of the tag, read 2026-11-19) |" % sha,
         "| archive | `https://codeload.github.com/swift-nav/libsbp/tar.gz/%s` |" % sha,
         "| license | %s: the file `LICENSE` at the root of the commit, verbatim below |" % LICENSE_LINE,
         "",
         "Each YAML file starts with a comment that names Swift Navigation as copyright",
         "holder and points to the `LICENSE` file for the terms; it adds no other terms.",
         "",
         "## Files",
         "",
         "| Path | SHA-256 |",
         "|---|---|",
         "| `LICENSE` | `%s` |" % sha256(os.path.join(src, "LICENSE"))]
    for f in files:
        o.append("| `%s` | `%s` |" % (f, sha256(os.path.join(src, f))))
    o += ["", "## LICENSE", "", "```"] + lic.rstrip("\n").splitlines() + ["```", ""]
    out.write(PROV, "\n".join(o))


def read_sources_provenance(text, src, files):
    m = re.search(r"\| commit \| `([0-9a-f]{40})`", text)
    t = re.search(r"\| tag \| `([^`]+)`", text)
    if not m or not t:
        raise GenError("%s states no commit or tag" % PROV)
    table = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    for rel in ["LICENSE"] + files:
        if rel not in table:
            raise GenError("%s has no SHA-256 for %s" % (PROV, rel))
        if sha256(os.path.join(src, rel)) != table[rel]:
            raise GenError("%s does not match the SHA-256 in %s" % (rel, PROV))
    return m.group(1), t.group(1), table


# -------------------------------------------------------------------- main ---

def run(args, out):
    src = args.src
    files = source_files(src)
    if args.commit:
        write_sources_provenance(out, src, args.commit, args.tag or "untagged", files)
    sha, tag, table = read_sources_provenance(out.read(PROV), src, files)
    packages, types = load_packages(src)
    plans = [PackagePlan(p, types) for p in packages]
    built = [pp for pp in plans if pp.kinds]
    core_text = read_text(args.core_def) if args.core_def else out.read("model/core.def")
    track_text = read_text(args.track_def) if args.track_def else out.read("model/track.def")
    out.write("model/%s.def" % HEADER_MODULE, header_module_text(sha, tag))
    total = 0
    for pp in built:
        pdir = "packs/" + pp.format
        out.write("model/%s.def" % pp.module, module_text(pp, sha, tag))
        out.write(pdir + "/pack.def", pack_text(pp, sha, tag))
        vecs = vector_files(pp)
        keep = {n for n, _ in vecs}
        for old in out.listdir(pdir + "/vectors"):
            if old.endswith(".json") and old not in keep:
                out.remove("%s/vectors/%s" % (pdir, old))
        for n, t in vecs:
            out.write("%s/vectors/%s" % (pdir, n), t)
        model = gtcheck.Model()
        model.add(core_text, "model/core.def")
        model.add(track_text, "model/track.def")
        model.add(out.read("model/%s.def" % HEADER_MODULE), "model/%s.def" % HEADER_MODULE)
        model.add(out.read("model/%s.def" % pp.module), "model/%s.def" % pp.module)
        pack = gtcheck.load_pack(out.read(pdir + "/pack.def"), model, pdir + "/pack.def")
        total += check_vectors(pack, [(n, out.read("%s/vectors/%s" % (pdir, n))) for n, _ in vecs], pp.format)
        out.write(pdir + "/pack.md", pack_md(pp, sha, tag, len(vecs)))
        out.write(pdir + "/PROVENANCE.md", provenance_md(pp, sha, tag, table))
    nb = collections.Counter(("trailing" if "end of the frame" in w else w.split(" (")[0])
                             for pp in plans for _, _, w in pp.not_built)
    return ["tag             %s (commit %s)" % (tag, sha),
            "packages        %d, packs %d%s" % (len(plans), len(built), "".join(
                "\nno pack         %s" % pp.pkg.name for pp in plans if not pp.kinds)),
            "messages        %d, kinds %d" % (sum(len(pp.pkg.messages) for pp in plans),
                                              sum(len(pp.kinds) for pp in built)),
            "field lines     %d" % sum(len(k.lines) for pp in built for k in pp.kinds),
            "scaled fields   %d" % sum(len(pp.scaled) for pp in built),
            "core bindings   %d" % sum(len(pp.core) for pp in built),
            "not built       %d %s" % (sum(nb.values()), dict(nb)),
            "fields left     %d" % sum(len(pp.skipped) for pp in plans),
            "vectors         %d checked" % total,
            "self-check      ok"]


def build_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(prog=NAME, description=__doc__.split("\n")[0] + " One pack per YAML "
                                 "package, one kind per message, the frame from the preamble through "
                                 "the payload.")
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("--src", required=True, metavar="DIR", help="a checkout of github.com/swift-nav/libsbp")
    ap.add_argument("--commit", help="write %s for this commit" % PROV)
    ap.add_argument("--tag", help="the tag of --commit, for the provenance file")
    ap.add_argument("--core-def", help="model/core.def (default <out>/model/core.def)")
    ap.add_argument("--track-def", help="model/track.def (default <out>/model/track.def)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = genio.Output(args.out, check=args.check)
    try:
        lines = run(args, out)
    except (GenError, YamlError, gtcheck.CheckError) as e:
        print("%s: %s" % (NAME, e), file=sys.stderr)
        return 1
    except OSError as e:
        print("%s: %s: %s" % (NAME, e.filename, e.strerror), file=sys.stderr)
        return 1
    print("\n".join(lines))
    return out.report(NAME)


if __name__ == "__main__":
    sys.exit(main())
