#!/usr/bin/env python3
"""Generate goat-transformers packs from the SunSpec Modbus information models
(github.com/sunspec/models, json/model_<id>.json).

Reads   <models>/json/model_*.json and <models>/LICENSE (the model definitions);
        <pysunspec2>/sunspec2/mb.py and <pysunspec2>/LICENSE (the values that
        mean "not implemented", per point type), read as a Python syntax tree:
        no file of the source is run;
        tools/gen/sources/sunspec-PROVENANCE.md (the tags, commits and SHA-256 of
        every file; a file that differs is refused)
Writes  <out>/model/sunspec<id>.def            one module per model
        <out>/packs/sunspec-<id>/pack.def      one pack per model, one kind
        <out>/packs/sunspec-<id>/pack.md
        <out>/packs/sunspec-<id>/PROVENANCE.md
        <out>/packs/sunspec-<id>/vectors/*.json
        tools/gen/sources/sunspec-PROVENANCE.md (only with --commit-models and --commit-pysunspec2)

The message is one model block as the Modbus registers hold it: 16-bit
registers, big-endian, from the model ID register on (ID, then the length L in
registers, then the points). The ID is the kind's `when`, and so is L for a
model of fixed length.

Every vector's block is written by a serializer in this file from the model
definition; the generator then loads the pack with gtcheck and decodes and
encodes every vector with its own codec of the bits wire.

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

NAME = "sunspec2pack"
VERSION = "0.1.0"
MODELS = "https://github.com/sunspec/models"
PYSUNSPEC2 = "https://github.com/sunspec/pysunspec2"
PROV = "tools/gen/sources/sunspec-PROVENANCE.md"
MB_FILE = "sunspec2/mb.py"
MAX_REQUIRES = 3
GROUP_SAMPLE_ITEMS = 2
LICENSE_LINE = "Apache License 2.0"
INT64_MAX = (1 << 63) - 1

# point type: (transform kind, bits per register count, the mb.py constant of its
# unimplemented value). The kind is u (uint), s (twos), f32, f64, ascii, pad.
TYPES = {
    "uint16": ("u", "SUNS_UNIMPL_UINT16"), "acc16": ("u", "SUNS_UNIMPL_ACC16"),
    "enum16": ("u", "SUNS_UNIMPL_ENUM16"), "bitfield16": ("u", "SUNS_UNIMPL_BITFIELD16"),
    "count": ("u", "SUNS_UNIMPL_UINT16"), "int16": ("s", "SUNS_UNIMPL_INT16"),
    "sunssf": ("s", "SUNS_UNIMPL_SUNSSF"),
    "uint32": ("u", "SUNS_UNIMPL_UINT32"), "acc32": ("u", "SUNS_UNIMPL_ACC32"),
    "enum32": ("u", "SUNS_UNIMPL_ENUM32"), "bitfield32": ("u", "SUNS_UNIMPL_BITFIELD32"),
    "int32": ("s", "SUNS_UNIMPL_INT32"), "ipaddr": ("u", "SUNS_UNIMPL_IPADDR"),
    "uint64": ("u", "SUNS_UNIMPL_UINT64"), "acc64": ("u", "SUNS_UNIMPL_ACC64"),
    "int64": ("s", "SUNS_UNIMPL_INT64"),
    "float32": ("f32", "SUNS_UNIMPL_FLOAT32"), "float64": ("f64", "SUNS_UNIMPL_FLOAT64"),
    "eui48": ("u", "SUNS_UNIMPL_EUI48"), "ipv6addr": ("u", "SUNS_UNIMPL_IPV6ADDR"),
    "string": ("ascii", "SUNS_UNIMPL_STRING"), "pad": ("pad", None),
}


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
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name))
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s if s and not s[0].isdigit() else "x" + s


def unimpl_values(text):
    """{constant name: raw unsigned value} of the SUNS_UNIMPL_* assignments of
    mb.py; a negative integer becomes its two's-complement pattern later, per
    width; the EUI-48 text becomes its 48 bits."""
    out = {}
    for st in ast.parse(text, MB_FILE).body:
        if (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name)
                and st.targets[0].id.startswith("SUNS_UNIMPL_")):
            v = ast.literal_eval(st.value)
            if isinstance(v, str) and re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", v):
                v = int(v.replace(":", ""), 16)
            out[st.targets[0].id] = v
    if "SUNS_UNIMPL_UINT16" not in out:
        raise GenError("%s states no SUNS_UNIMPL_ values" % MB_FILE)
    return out


# ------------------------------------------------------------------- plan ---

class NotBuilt(Exception):
    pass


Leaf = collections.namedtuple("Leaf", "path name ptype kind bitpos bits scale sentinel units sf")


def flatten_group(g, prefix, bitpos, leaves, where):
    """Append the leaves of group `g` (its points, then its groups) from
    `bitpos`; the bit after them. A group with a count other than none raises
    NotBuilt unless it is handled by the caller."""
    for p in g.get("points", []):
        t = p["type"]
        if t not in TYPES:
            raise GenError("%s.%s: point type %s" % (where, p["name"], t))
        size = p.get("size", 1)
        if not isinstance(size, int) or size < 1:
            raise GenError("%s.%s: size %r" % (where, p["name"], size))
        bits = 16 * size
        if TYPES[t][0] == "ascii" and bits > 2040:
            # text longer than `ascii` holds (255 bytes): parts of 124 registers
            for i, off in enumerate(range(0, bits, 1984), 1):
                n = min(1984, bits - off)
                leaves.append(Leaf(prefix + ["%s_%02d" % (p["name"], i)], p["name"], t, "ascii", bitpos, n, None,
                                   None, None, None))
                bitpos += n
            continue
        if TYPES[t][0] == "u" and bits > 64:
            # an unsigned value wider than 64 bits (ipv6addr): 64-bit parts
            for i, off in enumerate(range(0, bits, 64), 1):
                n = min(64, bits - off)
                leaves.append(Leaf(prefix + ["%s_%02d" % (p["name"], i)], p["name"], t, "u", bitpos, n, None,
                                   None, None, None))
                bitpos += n
            continue
        leaves.append(Leaf(prefix + [p["name"]], p["name"], t, TYPES[t][0], bitpos, bits, p.get("sf"),
                           None, p.get("units"), p.get("sf")))
        bitpos += bits
    for sg in g.get("groups", []):
        if sg.get("count") is None:
            bitpos = flatten_group(sg, prefix + [sg["name"]], bitpos, leaves, where)
        else:
            raise NotBuilt(sg)
    return bitpos


class Group:
    def __init__(self, key, start, item_bits, count_leaf, lines):
        self.key, self.start, self.item_bits = key, start, item_bits
        self.count_leaf, self.lines = count_leaf, lines


Line = collections.namedtuple("Line", "key pos bits tr leaf absent")


class ModelPlan:
    def __init__(self, mid, doc, unimpl, path):
        self.id, self.path = mid, path
        g = doc["group"]
        self.name = g["name"]
        self.kind = snake(g["name"])
        self.format = "sunspec-%d" % mid
        self.module = "sunspec%d" % mid
        self.keys, self.lists = collections.OrderedDict(), collections.OrderedDict()
        self.not_built = []            # (group path, reason)
        self.dynamic = []              # (point, sf point)
        self.static_sf = []            # (point, sf, transform)
        self.core = []
        self.length = None             # L in registers when the model has a fixed length
        self.group = None
        leaves = []
        bitpos = flatten_group({"points": g.get("points", [])}, [], 0, leaves, mid)
        if [l.name for l in leaves[:2]] != ["ID", "L"]:
            raise GenError("model %d does not start with ID and L" % mid)
        groups = g.get("groups", [])
        variable = False
        for n, sg in enumerate(groups):
            count = sg.get("count")
            if count is None:
                try:
                    bitpos = flatten_group(sg, [sg["name"]], bitpos, leaves, mid)
                except NotBuilt as e:
                    self.not_built.append((sg["name"] + "." + e.args[0]["name"],
                                           "a group inside a group, repeated (count `%s`)" % e.args[0].get("count")))
                    variable = True
                    self.rest_after(groups[n + 1:])
                    break
                continue
            last = n == len(groups) - 1
            if count == 0:
                self.not_built.append((sg["name"], "a block repeated to the end of the model: the number of blocks "
                                                   "is L less the fixed part, divided by the block's length"))
                variable = True
                self.rest_after(groups[n + 1:])
                break
            reason = None
            counts = [l for l in leaves if l.path == [count]]
            if not last:
                reason = "a group counted by `%s` that is not the last part of the model" % count
            elif len(counts) != 1 or counts[0].kind != "u" or counts[0].bits > 64:
                reason = "a group counted by `%s`, which is not one unsigned point of the fixed part" % count
            else:
                items = []
                try:
                    ibits = flatten_group(sg, [], 0, items, mid)
                except NotBuilt as e:
                    reason = "a group counted by `%s` whose items hold a repeated group (`%s`, count `%s`)" % (
                        count, e.args[0]["name"], e.args[0].get("count"))
            if reason:
                self.not_built.append((sg["name"], reason))
                variable = True
                self.rest_after(groups[n + 1:])
                break
            self.group = (sg["name"], counts[0], items, ibits, bitpos)
            variable = True
        self.lines = [self.line(l, unimpl) for l in leaves[2:]]
        self.lines = [l for l in self.lines if l is not None]
        self.consts = [(l.bitpos, l.bits) for l in leaves if l.kind == "pad"]
        if self.group:
            gname, cleaf, items, ibits, start = self.group
            lname = "%s_%s" % (self.kind, snake(gname))
            self.lists[lname] = "model %d, the items of group %s, counted by point %s" % (mid, gname, cleaf.name)
            self.lines = [l for l in self.lines if not (l.leaf is not None and l.leaf.path == cleaf.path)]
            self.keys.pop(self.key_name(cleaf.path), None)
            ilines = [self.line(l, unimpl, prefix=lname) for l in items]
            self.item_consts = [(l.bitpos, l.bits) for l in items if l.kind == "pad"]
            self.group = Group("%s.%s" % (self.module, lname), start, ibits, cleaf,
                               [l for l in ilines if l is not None])
        if variable:
            self.keys["l"] = ("int", "registers", "point L, the model length in registers")
            self.lines.insert(0, Line("%s.l" % self.module, 16, 16, "uint", None, None))
        else:
            self.length = bitpos // 16 - 2
        self.size_bits = bitpos
        self.requires = [l.key for l in self.lines if l.key.startswith(self.module + ".") and l.leaf is not None][:MAX_REQUIRES]

    def rest_after(self, groups):
        for sg in groups:
            self.not_built.append((sg["name"], "follows a part of variable length"))

    def key_name(self, path, prefix=None):
        return "%s_%s" % (prefix or self.kind, "_".join(snake(p) for p in path))

    def line(self, leaf, unimpl, prefix=None):
        if leaf.kind == "pad":
            return None
        name = self.key_name(leaf.path, prefix)
        base, n = name, 2
        while name in self.keys or name in self.lists:
            name, n = "%s_%d" % (base, n), n + 1
        absent = None
        cname = TYPES[leaf.ptype][1]
        if leaf.bits <= 64 and cname and cname in unimpl and leaf.kind != "ascii":
            v = unimpl[cname]
            if isinstance(v, int):
                absent = v & ((1 << leaf.bits) - 1)
        unit = "-"
        if leaf.kind == "ascii":
            if leaf.bits > 2040:
                raise GenError("%s: a string of %d bits" % (name, leaf.bits))
            tr, typ = "ascii", "string"
        elif leaf.kind in ("f32", "f64"):
            if leaf.bits != (32 if leaf.kind == "f32" else 64):
                raise GenError("%s: %s of %d bits" % (name, leaf.ptype, leaf.bits))
            tr, typ = leaf.kind, "float"
            unit = unit_token(leaf.units)
        elif leaf.bits > 64:
            raise GenError("%s: %s of %d bits" % (name, leaf.ptype, leaf.bits))
        else:
            tr, typ = ("twos" if leaf.kind == "s" else "uint"), "int"
            sf = leaf.sf
            if isinstance(sf, int) and not isinstance(sf, bool) and sf != 0:
                f = Fraction(10) ** sf
                if f.denominator == 1:
                    tr, typ = ("siscale:" if leaf.kind == "s" else "uiscale:") + str(f.numerator), "int"
                else:
                    tr, typ = ("sscale:" if leaf.kind == "s" else "uscale:") + "1/%d" % f.denominator, "float"
                self.static_sf.append((".".join(leaf.path), sf, tr))
                unit = unit_token(leaf.units)
            elif isinstance(sf, str):
                self.dynamic.append((".".join(leaf.path), sf))
            else:
                unit = unit_token(leaf.units)
        key = "%s.%s" % (self.module, name)
        if prefix is None and self.id == 305 and leaf.path in (["Lat"], ["Long"]) and leaf.units == "Degrees" \
                and leaf.sf == -7 and leaf.ptype == "int32":
            core = "lat" if leaf.path == ["Lat"] else "lon"
            self.core.append((leaf.name, core, tr))
            return Line(core, leaf.bitpos, leaf.bits, tr, leaf, absent)
        what = "model %d, point %s" % (self.id, ".".join(leaf.path))
        if isinstance(leaf.sf, str):
            what += ", unscaled (scale factor point %s)" % leaf.sf
        self.keys[name] = (typ, unit, what)
        return Line(key, leaf.bitpos, leaf.bits, tr, leaf, absent)


def unit_token(units):
    if not units:
        return "-"
    t = re.sub(r"\s+", "_", str(units).strip())
    return t if re.fullmatch(r"[A-Za-z0-9_%/^().*-]+", t) else "-"


# ------------------------------------------------------------------- emit ---

def loc(pos, n):
    return "0:%d:%d" % (pos, n)


def source_line(prov):
    return 'source        "%s json/model_*.json at %s (commit %s); unimplemented values from %s %s at %s (commit %s)"' % (
        MODELS, prov["models_ref"], prov["models"], PYSUNSPEC2, MB_FILE, prov["pysunspec2_ref"], prov["pysunspec2"])


def field_line(l, indent=""):
    opt = " absent %d" % l.absent if l.absent is not None else ""
    return "%sfield     %s %s %s%s" % (indent, l.key, loc(l.pos, l.bits), l.tr, opt)


def pack_text(mp, prov):
    o = ["# SunSpec model %d (%s), one model block as the Modbus registers hold it." % (mp.id, mp.name),
         "# Generated by tools/gen/sunspec2pack.py; do not edit by hand.",
         "# 16-bit registers, big-endian, from the model ID register on.",
         "format        %s" % mp.format,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(prov),
         "uses          %s" % mp.module,
         "wire          bits",
         "bit_order     msb",
         "word_bytes    1",
         "",
         "kind      %s" % mp.kind,
         "when      %s %d" % (loc(0, 16), mp.id)]
    if mp.length is not None:
        o.append("when      %s %d" % (loc(16, 16), mp.length))
    if mp.requires:
        o.append("requires  %s" % " ".join(mp.requires))
    for l in mp.lines:
        o.append(field_line(l))
    for pos, n in mp.consts:
        o.append("const     %s 0" % loc(pos, n))
    g = mp.group
    if g:
        o.append("group     %s 0:%d item %d count %s" % (g.key, g.start, g.item_bits,
                                                         loc(g.count_leaf.bitpos, g.count_leaf.bits)))
        for l in g.lines:
            o.append(field_line(l, "  "))
        for pos, n in mp.item_consts:
            o.append("  const   %s 0" % loc(pos, n))
        o.append("end")
    return "\n".join(o) + "\n"


def module_text(mp, prov):
    o = ["# The %s module: the points of SunSpec model %d (%s)." % (mp.module, mp.id, mp.name),
         "# Generated by tools/gen/sunspec2pack.py; do not edit by hand. A key is",
         "# <model>_<point path> in lower case with underscores. A point scaled by a",
         "# scale-factor point is carried unscaled; a point with a fixed scale factor",
         "# is scaled, in the unit the model states.",
         "module        %s" % mp.module,
         "version       %s" % VERSION,
         "distribution  public",
         source_line(prov)]
    for name, (typ, unit, what) in mp.keys.items():
        o.append('key   %s  %s  %s  "%s"' % (name, typ, unit, what))
    for name, what in mp.lists.items():
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


def put(acc, total, pos, bits, raw):
    return acc | (raw << (total - pos - bits))


def sample(leaf, salt):
    if leaf.kind == "ascii":
        return ("S%d" % (salt % 97))[:leaf.bits // 8]
    if leaf.kind in ("f32", "f64"):
        return ((salt % 41) - 20) * 0.25
    n = leaf.bits
    span = 1 << min(n, 15)
    v = (salt * 2654435761 + 12345) % (span - 2) + 1        # never 0, never all ones: not a sentinel
    if leaf.kind == "s":
        v -= span // 2
        if v == -(1 << (n - 1)):
            v += 1
    return v


def block_bytes(mp, values, items, absent=False):
    """The model block: `values` by leaf path (absent keys write their
    sentinel when `absent`), `items` for the counted group."""
    bits = mp.size_bits + (len(items) * mp.group.item_bits if mp.group else 0)
    total = bits
    acc = put(0, total, 0, 16, mp.id)
    acc = put(acc, total, 16, 16, mp.length if mp.length is not None else bits // 16 - 2)
    for l in mp.lines:
        if l.leaf is None:
            continue
        if absent and l.absent is not None:
            acc = put(acc, total, l.pos, l.bits, l.absent)
        else:
            acc = put(acc, total, l.pos, l.bits, raw_of(l.leaf, values[tuple(l.leaf.path)]))
    if mp.group:
        g = mp.group
        acc = put(acc, total, g.count_leaf.bitpos, g.count_leaf.bits, len(items))
        for i, item in enumerate(items):
            for l in g.lines:
                acc = put(acc, total, g.start + i * g.item_bits + l.pos, l.bits, raw_of(l.leaf, item[tuple(l.leaf.path)]))
    return acc.to_bytes(total // 8, "big")


def vector_text(pairs):
    return json.dumps(collections.OrderedDict(pairs), indent=2) + "\n"


# Cross-format case: model 305 to GeoJSON, the expected text written by hand:
# latitude and longitude are int32 in 1e-7 degrees.
CROSS_305 = ({"Lat": 473977420, "Long": 85455940},
             '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.545594,47.397742]},"properties":{}}')


def vector_files(mp):
    files = []
    values = {tuple(l.leaf.path): sample(l.leaf, mp.id * 31 + j * 7 + 3) for j, l in enumerate(mp.lines) if l.leaf}
    items = []
    if mp.group:
        items = [{tuple(l.leaf.path): sample(l.leaf, mp.id * 17 + 101 * (n + 1) + 5 * j)
                  for j, l in enumerate(mp.group.lines)} for n in range(GROUP_SAMPLE_ITEMS)]
    cases = [("", items, False)]
    if mp.group:
        cases.append(("-no-items", [], False))
    if any(l.absent is not None for l in mp.lines):
        cases.append(("-unimplemented", [], True))
    for suffix, its, absent in cases:
        data = block_bytes(mp, values, its, absent).hex()
        model = collections.OrderedDict([("@kind", mp.kind)])
        if mp.group:
            model[mp.group.key + ".#"] = str(len(its))
        files.append(("rt-%s%s.json" % (mp.kind, suffix), vector_text([
            ("name", "%s-roundtrip-%s%s" % (mp.format, mp.kind, suffix)), ("from", mp.format), ("to", mp.format),
            ("input", data), ("expect", data), ("model", model)])))
    if mp.core:
        given, expect = CROSS_305
        v = dict(values)
        for k, x in given.items():
            v[(k,)] = x
        data = block_bytes(mp, v, items).hex()
        model = collections.OrderedDict([("@kind", mp.kind)])
        for name, core, tr in mp.core:
            model[core] = format((Decimal(given[name]) / Decimal(10 ** 7)).normalize(), "f")
        files.append(("x-01-%s-to-geojson.json" % mp.kind, vector_text([
            ("name", "%s-%s-to-geojson" % (mp.format, mp.kind)), ("from", mp.format), ("to", "geojson"),
            ("input", data), ("expect", expect), ("model", model)])))
    return files


# -------------------------------------------- codec, from the specification ---

def get_bits(data, pos, n):
    total = 8 * len(data)
    return (int.from_bytes(data, "big") >> (total - pos - n)) & ((1 << n) - 1)


def sentinels(node):
    return [int(x) for x in node.absent.split(",")] if node.absent else []


def exact_factor(text):
    m = re.fullmatch(r"(-?\d+)/(\d+)", text)
    return Fraction(int(m.group(1)), int(m.group(2))) if m else Fraction(Decimal(text))


def round_half_away(q):
    r = math.floor(abs(q) + Fraction(1, 2))
    return r if q >= 0 else -r


def decode_value(node, raw):
    tr, n = node.tr, node.bits
    signed = raw - (1 << n) if raw >> (n - 1) else raw
    if tr == "uint":
        return raw - (1 << 64) if n == 64 and raw >> 63 else raw
    if tr == "twos":
        return signed
    if tr in ("uscale", "sscale"):
        f = gtcheck.parse_factor(node.targs[0])
        v = raw if tr == "uscale" else signed
        return v * f[0] / f[1] if isinstance(f, tuple) else v * f
    if tr in ("uiscale", "siscale"):
        v = raw if tr == "uiscale" else signed
        return int(round_half_away(v * exact_factor(node.targs[0])))
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
    mask = (1 << n) - 1
    if tr in ("uint", "twos"):
        return x & mask
    if tr in ("uscale", "sscale"):
        f = gtcheck.parse_factor(node.targs[0])
        q = x * f[1] / f[0] if isinstance(f, tuple) else x / f
        return int(math.floor(abs(q) + 0.5)) * (1 if q >= 0 else -1) & mask
    if tr in ("uiscale", "siscale"):
        return int(round_half_away(Fraction(x) / exact_factor(node.targs[0]))) & mask
    if tr in ("f32", "f64"):
        return int.from_bytes(struct.pack(">f" if tr == "f32" else ">d", x), "big")
    if tr == "ascii":
        return int.from_bytes(x.encode("ascii").ljust(n // 8, b"\0"), "big")
    raise CodecError("transform-encode")


def decode_fields(lines, data, base, out):
    for n in lines:
        if n.d == "field":
            raw = get_bits(data, base + n.start, n.bits)
            if raw in sentinels(n):
                continue
            out[n.key] = decode_value(n, raw)


def decode(pack, data):
    kind = None
    for k in pack.kinds:
        if all(n.start + n.bits <= 8 * len(data) and get_bits(data, n.start, n.bits) == int(n.value)
               for n in pack.common + k.lines if n.d == "when"):
            kind = k
            break
    if kind is None:
        raise CodecError("no-kind")
    lines = pack.common + kind.lines
    if 8 * len(data) < max(n.start + n.bits for n in lines if n.d in ("when", "field", "const")):
        raise CodecError("malformed-wire")
    ent, lists = collections.OrderedDict(), {}
    decode_fields(lines, data, 0, ent)
    for n in lines:
        if n.d == "group":
            count = get_bits(data, n.count[0], n.count[1])
            if 8 * len(data) < n.start + count * n.item:
                raise CodecError("malformed-wire")
            items = []
            for i in range(count):
                item = collections.OrderedDict()
                decode_fields(n.body, data, n.start + i * n.item, item)
                items.append(item)
            lists[n.key] = items
    return kind.name, ent, lists


def encode(pack, name, ent, lists):
    kind = next(k for k in pack.kinds if k.name == name)
    lines = pack.common + kind.lines
    end = max(n.start + n.bits for n in lines if n.d in ("when", "field", "const"))
    for n in lines:
        if n.d == "group":
            end = max(end, n.start + len(lists.get(n.key, [])) * n.item)
    total = (end + 7) // 8 * 8
    acc = 0

    def write(nodes, base, values):
        nonlocal acc
        for n in nodes:
            if n.d == "field":
                if n.key in values:
                    raw = encode_value(n, values[n.key])
                elif sentinels(n):
                    raw = sentinels(n)[0]
                else:
                    continue
                acc |= raw << (total - base - n.start - n.bits)
    write(lines, 0, ent)
    for n in lines:
        if n.d == "group":
            items = lists.get(n.key, [])
            acc &= ~(((1 << n.count[1]) - 1) << (total - n.count[0] - n.count[1]))
            acc |= len(items) << (total - n.count[0] - n.count[1])
            for i, item in enumerate(items):
                write(n.body, n.start + i * n.item, item)
    for n in lines:
        if n.d in ("when", "const"):
            acc &= ~(((1 << n.bits) - 1) << (total - n.start - n.bits))
            acc |= int(n.value) << (total - n.start - n.bits)
    return acc.to_bytes(total // 8, "big")


def fmt_float(x):
    if x == int(x) and abs(x) < 1e17:
        return str(int(x))
    return repr(x)


def geojson(ent):
    if "lat" in ent and "lon" in ent:
        geom = '{"type":"Point","coordinates":[%s,%s]}' % (fmt_float(ent["lon"]), fmt_float(ent["lat"]))
    else:
        geom = "null"
    return '{"type":"Feature","geometry":%s,"properties":{}}' % geom


def check_vectors(pack, vectors, fmt):
    n, seen = 0, set()
    for fn, text in vectors:
        vec = json.loads(text)
        try:
            kname, ent, lists = decode(pack, bytes.fromhex(vec["input"]))
            for key, want in vec.get("model", {}).items():
                if key == "@kind":
                    got = kname
                elif key.endswith(".#"):
                    got = str(len(lists.get(key[:-2], [])))
                else:
                    got = ent.get(key)
                    if isinstance(got, float):
                        if abs(got - float(want)) > 1e-9:
                            raise GenError("%s/%s: model %s" % (fmt, fn, key))
                        continue
                if str(got) != want:
                    raise GenError("%s/%s: model %s = %s, vector says %s" % (fmt, fn, key, got, want))
            got = encode(pack, kname, ent, lists).hex() if vec["to"] == fmt else geojson(ent)
            seen.add(kname)
        except CodecError as e:
            raise GenError("%s/%s: %s" % (fmt, fn, e))
        if got != vec["expect"]:
            raise GenError("%s/%s: convert gives %s, vector expects %s" % (fmt, fn, got, vec["expect"]))
        n += 1
    if {k.name for k in pack.kinds} - seen:
        raise GenError("%s: a kind with no vector" % fmt)
    return n


# --------------------------------------------------------------- documents ---

def pack_md(mp, prov, nvec):
    o = []
    a = o.append
    a("# Pack: %s" % mp.format)
    a("")
    a("SunSpec information model %d (`%s`), one model block as the Modbus registers" % (mp.id, mp.name))
    a("hold it, from `%s` (`json/model_%d.json`) at %s, commit `%s`. Public." % (MODELS, mp.id, prov["models_ref"], prov["models"]))
    a("Generated by `tools/gen/sunspec2pack.py`; do not edit `pack.def`, this file,")
    a("`PROVENANCE.md`, `model/%s.def` or the vectors by hand." % mp.module)
    a("")
    a("Status: Built. Generated and checked by the generator's own serializer and codec.")
    a("")
    a("## The message")
    a("")
    a("`wire bits`, `bit_order msb`, `word_bytes 1`; hex text. The model block from its")
    a("ID register on: 16-bit registers, each big-endian, in register order. The")
    a("model ID (register 0) is the kind's `when`.")
    if mp.length is not None:
        a("The model has a fixed length: L (register 1) = %d registers, also a `when`." % mp.length)
    else:
        a("The model's length varies, so L (register 1) is the field `%s.l`: encode" % mp.module)
        a("writes it as the entity holds it, and a block encoded from another format needs")
        a("it set (a length derived from the content is not in the pack language).")
    a("Reading the block off a device (its base address, the `SunS` marker, the")
    a("chain of models) is the Modbus layer's, not this pack's.")
    a("")
    a("## What is mapped")
    a("")
    a("| Point type | Transform | Not implemented (`absent`) |")
    a("|---|---|---|")
    a("| `uint16`, `acc16`, `enum16`, `bitfield16`, `count`, `uint32`, `acc32`, `enum32`, `bitfield32`, `uint64`, `acc64`, `ipaddr`, `eui48` | `uint` | the value pysunspec2 gives the type |")
    a("| `int16`, `int32`, `int64`, `sunssf` | `twos` | the most negative value |")
    a("| `float32`, `float64` | `f32`, `f64` | the NaN pattern pysunspec2 gives |")
    a("| `string` | `ascii` | none: `absent` is refused on a field longer than 64 bits, which most strings are, so no string carries it and every length behaves alike; all NUL decodes as empty text |")
    a("| `pad` | `const 0` | - |")
    a("")
    a("Keys are `%s.%s_<point path>` in lower case with underscores. The values that" % (mp.module, mp.kind))
    a("mean \"not implemented\" are the `SUNS_UNIMPL_*` constants of pysunspec2's")
    a("`%s` (Apache-2.0, the SunSpec Alliance's own library): a point that holds one" % MB_FILE)
    a("decodes as absent, and an absent key encodes as it (spec 0.9). For an")
    a("accumulator that value is 0.")
    if mp.static_sf:
        a("")
        a("Points with a fixed scale factor (a number in the model) are scaled exactly,")
        a("in the unit the model states:")
        a("")
        a("| Point | Scale factor | Transform |")
        a("|---|---|---|")
        for p, sf, tr in mp.static_sf:
            a("| `%s` | %d | `%s` |" % (p, sf, tr))
    if mp.dynamic:
        a("")
        a("%d points are scaled by the value of a scale-factor point (`sunssf`), a power" % len(mp.dynamic))
        a("of ten that each device states. The pack language has no transform or derive")
        a("that scales one key by ten to the power of another, so these points are")
        a("carried unscaled, with no unit, and their scale-factor points are keys too:")
        a("")
        a("| Point | Scale factor point |")
        a("|---|---|")
        for p, sf in mp.dynamic:
            a("| `%s` | `%s` |" % (p, sf))
    if mp.group:
        a("")
        a("The group `%s` is a `group` counted by the point `%s`; the count point has no" % (
            mp.group.key, mp.group.count_leaf.name))
        a("key of its own.")
    a("")
    a("### Core keys")
    a("")
    if mp.core:
        a("`Lat` and `Long` are int32 points in degrees (the model's unit) with a fixed")
        a("scale factor of -7, in a model the source names GPS: they bind `lat` and `lon`")
        a("(`sscale:1/10000000`). The model states no datum; GPS coordinates are read as")
        a("WGS 84. `Alt` is in metres with no reference surface stated and stays raw.")
    else:
        a("None: no point of this model states a position, velocity or time with the")
        a("meaning and unit of a shared key.")
    a("")
    a("## What is not mapped")
    a("")
    if mp.not_built:
        a("| Group | Reason |")
        a("|---|---|")
        for gname, why in mp.not_built:
            a("| %s | %s |" % (gname, why))
        a("")
        if any("to the end of the model" in w for _, w in mp.not_built):
            a("A block repeated to the end of the model has a count that is L less the fixed")
            a("part, divided by the block's length: a count computed from the length, which")
            a("the pack language cannot state. The fixed part before it is mapped.")
            a("")
    a("- Scaling by a scale-factor point (above).")
    a("- Enumerations and bit fields are carried as integers.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-*.json`: a same-format round trip of the block written by a")
    a("serializer in the generator from sample values; `-unimplemented` with every")
    a("point that can carry it set to its not-implemented value; `-no-items` with an")
    a("empty counted group.%s" % (" `x-01-*-to-geojson.json`: the position to GeoJSON,"
                                  " the expected text written by hand." if mp.core else ""))
    a("")
    a("%d vectors." % nvec)
    return "\n".join(o) + "\n"


def provenance_md(mp, prov, table):
    return "\n".join([
        "# Provenance: %s" % mp.format, "",
        "| Fact | Value |", "|---|---|",
        "| model | %s `json/model_%d.json` at %s, commit `%s` (SHA-256 `%s`) |" % (
            MODELS, mp.id, prov["models_ref"], prov["models"], table["models/json/model_%d.json" % mp.id]),
        "| not-implemented values | %s `%s` at %s, commit `%s` (SHA-256 `%s`) |" % (
            PYSUNSPEC2, MB_FILE, prov["pysunspec2_ref"], prov["pysunspec2"], table["pysunspec2/" + MB_FILE]),
        "| licenses | %s, both (`LICENSE` of each repository), quoted in `%s` |" % (LICENSE_LINE, PROV),
        "| date read | 2026-11-19 |",
        "| what the pack takes | point names, types, sizes, units and fixed scale factors; group structure; no description text |",
        "| generator | `tools/gen/sunspec2pack.py` |", ""])


def write_sources_provenance(out, models, pss, prov, files):
    o = ["# Provenance of the SunSpec inputs", "",
         "| Fact | Value |", "|---|---|",
         "| models | %s, %s, commit `%s` |" % (MODELS, prov["models_ref"], prov["models"]),
         "| models archive | `https://codeload.github.com/sunspec/models/tar.gz/%s` |" % prov["models"],
         "| not-implemented values | %s, %s, commit `%s` |" % (PYSUNSPEC2, prov["pysunspec2_ref"], prov["pysunspec2"]),
         "| pysunspec2 archive | `https://codeload.github.com/sunspec/pysunspec2/tar.gz/%s` |" % prov["pysunspec2"],
         "| licenses | %s, the `LICENSE` file at the root of each commit (the same text; the models copy is quoted below, and the two SHA-256 are listed) |" % LICENSE_LINE,
         "",
         "## Files", "",
         "| Path | SHA-256 |", "|---|---|",
         "| `models/LICENSE` | `%s` |" % sha256(os.path.join(models, "LICENSE")),
         "| `pysunspec2/LICENSE` | `%s` |" % sha256(os.path.join(pss, "LICENSE")),
         "| `pysunspec2/%s` | `%s` |" % (MB_FILE, sha256(os.path.join(pss, MB_FILE)))]
    for f in files:
        o.append("| `models/%s` | `%s` |" % (f, sha256(os.path.join(models, f))))
    o += ["", "## LICENSE (sunspec/models)", "", "```"] + read_text(os.path.join(models, "LICENSE")).rstrip("\n").splitlines() + ["```", ""]
    out.write(PROV, "\n".join(o))


def read_sources_provenance(text, models, pss, files):
    facts = {}
    for key, rx in (("models", r"\| models \| \S+, ([^,\s]+), commit `([0-9a-f]{40})` \|"),
                    ("pysunspec2", r"\| not-implemented values \| \S+, ([^,\s]+), commit `([0-9a-f]{40})` \|")):
        m = re.search(rx, text)
        if not m:
            raise GenError("%s states no %s commit" % (PROV, key))
        facts[key + "_ref"], facts[key] = m.group(1), m.group(2)
    table = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    want = ["models/LICENSE", "pysunspec2/LICENSE", "pysunspec2/" + MB_FILE] + ["models/" + f for f in files]
    for rel in want:
        if rel not in table:
            raise GenError("%s has no SHA-256 for %s" % (PROV, rel))
        base, sub = rel.split("/", 1)
        if sha256(os.path.join(models if base == "models" else pss, sub)) != table[rel]:
            raise GenError("%s does not match the SHA-256 in %s" % (rel, PROV))
    return facts, table


# -------------------------------------------------------------------- main ---

def model_files(models):
    files = []
    for f in os.listdir(os.path.join(models, "json")):
        m = re.fullmatch(r"model_(\d+)\.json", f)
        if m:
            files.append((int(m.group(1)), "json/" + f))
    return [f for _, f in sorted(files)]


def run(args, out):
    files = model_files(args.models)
    if args.commit_models or args.commit_pysunspec2:
        if not (args.commit_models and args.commit_pysunspec2):
            raise GenError("--commit-models and --commit-pysunspec2 go together")
        write_sources_provenance(out, args.models, args.pysunspec2, {
            "models": args.commit_models, "models_ref": args.ref_models or "untagged",
            "pysunspec2": args.commit_pysunspec2, "pysunspec2_ref": args.ref_pysunspec2 or "untagged"}, files)
    prov, table = read_sources_provenance(out.read(PROV), args.models, args.pysunspec2, files)
    unimpl = unimpl_values(read_text(os.path.join(args.pysunspec2, MB_FILE)))
    core_text = read_text(args.core_def) if args.core_def else out.read("model/core.def")
    total, plans = 0, []
    for f in files:
        doc = json.loads(read_text(os.path.join(args.models, f)))
        mid = int(doc["id"])
        if "model_%d.json" % mid != os.path.basename(f):
            raise GenError("%s holds model %d" % (f, mid))
        mp = ModelPlan(mid, doc, unimpl, f)
        plans.append(mp)
        pdir = "packs/" + mp.format
        out.write("model/%s.def" % mp.module, module_text(mp, prov))
        out.write(pdir + "/pack.def", pack_text(mp, prov))
        vecs = vector_files(mp)
        keep = {n for n, _ in vecs}
        for old in out.listdir(pdir + "/vectors"):
            if old.endswith(".json") and old not in keep:
                out.remove("%s/vectors/%s" % (pdir, old))
        for n, t in vecs:
            out.write("%s/vectors/%s" % (pdir, n), t)
        model = gtcheck.Model()
        model.add(core_text, "model/core.def")
        model.add(out.read("model/%s.def" % mp.module), "model/%s.def" % mp.module)
        pack = gtcheck.load_pack(out.read(pdir + "/pack.def"), model, pdir + "/pack.def")
        total += check_vectors(pack, [(n, out.read("%s/vectors/%s" % (pdir, n))) for n, _ in vecs], mp.format)
        out.write(pdir + "/pack.md", pack_md(mp, prov, len(vecs)))
        out.write(pdir + "/PROVENANCE.md", provenance_md(mp, prov, table))
    reasons = collections.Counter(re.sub(r"`[^`]*`", "`…`", w) for mp in plans for _, w in mp.not_built)
    return ["models          %s (commit %s)" % (prov["models_ref"], prov["models"]),
            "packs           %d (%d of fixed length, %d with a counted group)" % (
                len(plans), sum(1 for p in plans if p.length is not None), sum(1 for p in plans if p.group)),
            "points          %d keys, %d with a dynamic scale factor, %d with a fixed one" % (
                sum(len(p.keys) for p in plans), sum(len(p.dynamic) for p in plans), sum(len(p.static_sf) for p in plans)),
            "not built       %d groups" % sum(reasons.values())] + ["  %3d  %s" % (n, w) for w, n in reasons.most_common()] + [
            "core bindings   %d" % sum(len(p.core) for p in plans),
            "vectors         %d checked" % total,
            "self-check      ok"]


def build_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(prog=NAME, description=__doc__.split("\n")[0])
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("--models", required=True, metavar="DIR", help="a checkout of %s" % MODELS)
    ap.add_argument("--pysunspec2", required=True, metavar="DIR", help="a checkout of %s" % PYSUNSPEC2)
    ap.add_argument("--commit-models", help="write %s: the models commit" % PROV)
    ap.add_argument("--commit-pysunspec2", help="write %s: the pysunspec2 commit" % PROV)
    ap.add_argument("--ref-models", help="the tag of --commit-models")
    ap.add_argument("--ref-pysunspec2", help="the tag of --commit-pysunspec2")
    ap.add_argument("--core-def", help="model/core.def (default <out>/model/core.def)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = genio.Output(args.out, check=args.check)
    try:
        lines = run(args, out)
    except (GenError, gtcheck.CheckError, SyntaxError, ValueError) as e:
        print("%s: %s" % (NAME, e), file=sys.stderr)
        return 1
    except OSError as e:
        print("%s: %s: %s" % (NAME, e.filename, e.strerror), file=sys.stderr)
        return 1
    print("\n".join(lines))
    return out.report(NAME)


if __name__ == "__main__":
    sys.exit(main())
