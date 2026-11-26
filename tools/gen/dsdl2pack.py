#!/usr/bin/env python3
"""Generate goat-transformers packs from DroneCAN (UAVCAN v0) DSDL definitions.

Reads   <dsdl>/<namespace>/**/*.uavcan and <dsdl>/LICENSE (github.com/dronecan/DSDL)
        tools/gen/sources/dronecan-PROVENANCE.md (commit and SHA-256 of every file)
Writes  <root>/model/dc<namespace>.def           one module per DSDL namespace
        <root>/packs/dronecan-<type>/pack.def    one pack per data type that has a
        <root>/packs/dronecan-<type>/pack.md     default data type ID (a service
        <root>/packs/dronecan-<type>/PROVENANCE.md   gives a -request and a
        <root>/packs/dronecan-<type>/vectors/    -response pack)
        tools/gen/sources/dronecan-PROVENANCE.md (only with --commit)

A DroneCAN transfer carries its data type ID in the CAN identifier, not in the
payload, so a payload alone does not say which type it is. Each data type is
therefore its own format; the caller names it when converting. Input and output
are the reassembled transfer payload (no transfer CRC, no tail bytes).

Python 3 standard library only. Re-runnable: the same inputs give the same
bytes. Each round-trip vector is produced by a DroneCAN serializer written in
this file from the DSDL rules; after writing, the script reads its packs back
from disk and decodes and re-encodes every vector with a small sequential-bits
engine written from spec/engine-spec.md (Versions 0.5, 0.6, 0.8). Exit status
is non-zero when a check fails.

Usage: dsdl2pack.py --dsdl DIR [--root DIR] [--namespaces uavcan,dronecan,...]
                    [--commit SHA] [--core-def PATH]
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
import genio      # noqa: E402  (the script directory is not on the path under `python3 -I`)

VERSION = "0.1.0"
REPO = "https://github.com/dronecan/DSDL"
SPEC = "https://dronecan.github.io/Specification/3._Data_structure_description_language/"
PROV_NAME = "dronecan-PROVENANCE.md"
MAX_STATIC_UNROLL = 64      # a static array of more elements is not unrolled
NAMESPACES = ["uavcan", "dronecan", "ardupilot", "com", "cuav", "mppt"]


class GenError(Exception):
    pass


# Fields bound to core keys: (data type, field) -> (core key, the evidence in
# this project's words). Only a latitude and longitude pair whose definition
# states degrees, as degrees or as degrees times 10^7 in an int32.
CORE = {
    ("uavcan.navigation.GlobalNavigationSolution", "latitude"):
        ("lat", "float64, the definition's heading for the pair says angular degrees; the fused position of the vehicle"),
    ("uavcan.navigation.GlobalNavigationSolution", "longitude"):
        ("lon", "as latitude"),
    ("uavcan.equipment.camera_gimbal.GEOPOICommand", "latitude_deg_1e7"):
        ("lat", "int32, 1 LSB = 1e-7 degree as the definition states; the point of interest the gimbal is to aim at, not the vehicle"),
    ("uavcan.equipment.camera_gimbal.GEOPOICommand", "longitude_deg_1e7"):
        ("lon", "as latitude"),
    ("ardupilot.equipment.trafficmonitor.TrafficReport", "latitude_deg_1e7"):
        ("lat", "int32 in 1e-7 degree (the name); the position of the reported traffic, not of the vehicle"),
    ("ardupilot.equipment.trafficmonitor.TrafficReport", "longitude_deg_1e7"):
        ("lon", "as latitude"),
    ("dronecan.remoteid.Location", "latitude"):
        ("lat", "int32 in degE7 as the definition states; the location of the unmanned aircraft (Open Drone ID Location)"),
    ("dronecan.remoteid.Location", "longitude"):
        ("lon", "as latitude"),
    ("com.xacti.GnssStatus", "latitude"):
        ("lat", "float64 in degrees as the definition states; the GNSS position the gimbal reports"),
    ("com.xacti.GnssStatus", "longitude"):
        ("lon", "as latitude"),
}

# One conversion to GeoJSON per pack that binds core keys. The raw wire values
# and the expected text are written by hand: degrees = value / 10^7 for an
# int32, the value itself for a float64; coordinates are [lon, lat].
CROSS = {
    "uavcan.navigation.GlobalNavigationSolution": (35.6762, 139.6503,
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[139.6503,35.6762]},"properties":{}}'),
    "uavcan.equipment.camera_gimbal.GEOPOICommand": (473977420, 85455940,
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.545594,47.397742]},"properties":{}}'),
    "ardupilot.equipment.trafficmonitor.TrafficReport": (-338568000, 1512153000,
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[151.2153,-33.8568]},"properties":{}}'),
    "dronecan.remoteid.Location": (515007000, -1246000,
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[-0.1246,51.5007]},"properties":{}}'),
    "com.xacti.GnssStatus": (-90.0, 180.0,
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[180,-90]},"properties":{}}'),
}
DEGE7 = "1/10000000"

# Fields bound to core `time_ms` (epoch milliseconds UTC): (data type, field) ->
# (transform, evidence in this project's words). The transform is an integer
# scale of engine-spec 0.15.
TIME = {
    ("dronecan.remoteid.System", "timestamp"):
        ("uiscale:1000:1546300800000",
         "uint32, seconds since 2019-01-01 00:00:00 UTC as the definition states, which is "
         "1546300800 s after the Unix epoch"),
}

# One conversion to GeoJSON per pack that binds time_ms: the raw value and the
# expected text, written by hand. 153699200 s after 2019-01-01 is
# 2023-11-14T22:13:20Z, 1700000000000 ms.
TIME_CROSS = {
    "dronecan.remoteid.System": (153699200,
        '{"type":"Feature","geometry":null,"properties":{"time_ms":1700000000000}}'),
}


# ------------------------------------------------------------------ DSDL ---

class Prim:
    def __init__(self, kind, bits):
        self.kind, self.bits = kind, bits     # kind: uint int float bool

    def __repr__(self):
        return "%s%d" % (self.kind, self.bits)


class Void:
    def __init__(self, bits):
        self.bits = bits


class Arr:
    def __init__(self, elem, mode, n):
        self.elem, self.mode, self.n = elem, mode, n   # mode: static | dynamic
        # n is the element count (static) or the maximum count (dynamic)


class Ref:
    def __init__(self, full):
        self.full = full


class Field:
    def __init__(self, name, typ):
        self.name, self.typ = name, typ


class Body:
    def __init__(self):
        self.fields, self.union, self.consts = [], False, []


class DType:
    def __init__(self, full, dtid, path):
        self.full, self.dtid, self.path = full, dtid, path
        self.bodies = [Body()]       # one for a message, two for a service
        self.service = False
        self.deprecated = False
        self.override_signature = None

    @property
    def ns(self):
        return self.full.rsplit(".", 1)[0]

    @property
    def short(self):
        return self.full.rsplit(".", 1)[1]


PRIM_RE = re.compile(r"^(uint|int|float)(\d+)$")
ARR_RE = re.compile(r"^(.+)\[(<=|<)?(\d+)\]$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_type_text(text, ns):
    m = ARR_RE.match(text)
    if m:
        inner, op, n = m.group(1), m.group(2), int(m.group(3))
        elem = parse_type_text(inner, ns)
        if op is None:
            return Arr(elem, "static", n)
        return Arr(elem, "dynamic", n if op == "<=" else n - 1)
    if text == "bool":
        return Prim("bool", 1)
    m = PRIM_RE.match(text)
    if m:
        k, b = m.group(1), int(m.group(2))
        if k == "float" and b not in (16, 32, 64):
            raise GenError("bad float width " + text)
        if not 1 <= b <= 64 or (k == "int" and b < 2):
            raise GenError("bad width " + text)
        return Prim(k, b)
    m = re.match(r"^void(\d+)$", text)
    if m:
        return Void(int(m.group(1)))
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", text):
        raise GenError("bad type " + text)
    return Ref(text if "." in text else ns + "." + text)


def parse_file(path, rel):
    parts = rel[:-len(".uavcan")].split("/")
    fname = parts[-1]
    m = re.match(r"^(?:(\d+)\.)?([A-Za-z][A-Za-z0-9_]*)$", fname)
    if not m:
        raise GenError("bad file name " + rel)
    dtid = int(m.group(1)) if m.group(1) else None
    full = ".".join(parts[:-1] + [m.group(2)])
    t = DType(full, dtid, rel)
    body = t.bodies[0]
    for ln, raw in enumerate(read_text(path).splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line == "---":
            if t.service:
                raise GenError("%s:%d: second ---" % (rel, ln))
            t.service = True
            body = Body()
            t.bodies.append(body)
            continue
        if line.startswith("@"):
            if line == "@union":
                body.union = True
            elif line == "@deprecated":
                t.deprecated = True
            else:
                raise GenError("%s:%d: unknown directive %s" % (rel, ln, line))
            continue
        toks = line.split()
        if toks[0] == "OVERRIDE_SIGNATURE" and len(toks) == 2:
            t.override_signature = toks[1]   # changes the data type signature only
            continue
        if toks[0] in ("saturated", "truncated"):
            toks = toks[1:]
        if re.match(r"^\S+\s+[A-Za-z_][A-Za-z0-9_]*\s*=", " ".join(toks)):
            body.consts.append(line)          # a constant: not on the wire
            continue
        if len(toks) == 1 and toks[0].startswith("void"):
            body.fields.append(Field(None, parse_type_text(toks[0], t.ns)))
            continue
        if len(toks) != 2 or not NAME_RE.match(toks[1]):
            raise GenError("%s:%d: cannot read %r" % (rel, ln, raw))
        body.fields.append(Field(toks[1], parse_type_text(toks[0], t.ns)))
    return t


def load_dsdl(dsdl, namespaces):
    types = {}
    for ns in namespaces:
        base = os.path.join(dsdl, ns)
        for dp, dn, fn in os.walk(base):
            dn.sort()
            for f in sorted(fn):
                if f.endswith(".uavcan"):
                    p = os.path.join(dp, f)
                    rel = os.path.relpath(p, dsdl).replace(os.sep, "/")
                    t = parse_file(p, rel)
                    if t.full in types:
                        raise GenError("type %s defined twice" % t.full)
                    types[t.full] = t
    for t in types.values():
        for b in t.bodies:
            for f in b.fields:
                check_refs(f.typ, types, t.full)
    return types


def check_refs(typ, types, where):
    if isinstance(typ, Arr):
        check_refs(typ.elem, types, where)
    elif isinstance(typ, Ref):
        if typ.full not in types:
            raise GenError("%s refers to unknown type %s" % (where, typ.full))
        if types[typ.full].service:
            raise GenError("%s nests a service type" % where)


def bits_for(n):
    """Bits of a count 0..n, or of a tag 0..n-1 for n variants."""
    return max(1, int(n).bit_length())


def tag_bits(nvariants):
    return max(1, (nvariants - 1).bit_length())


def min_max_bits(typ, types):
    """(min, max) serialized bit length outside any tail array optimisation."""
    if isinstance(typ, (Prim, Void)):
        return typ.bits, typ.bits
    if isinstance(typ, Ref):
        return body_min_max(types[typ.full].bodies[0], types)
    lo, hi = min_max_bits(typ.elem, types)
    if typ.mode == "static":
        return lo * typ.n, hi * typ.n
    p = bits_for(typ.n)
    return p, p + hi * typ.n


def body_min_max(body, types):
    mm = [min_max_bits(f.typ, types) for f in body.fields]
    if body.union:
        t = tag_bits(len(body.fields))
        return t + min(a for a, _ in mm), t + max(b for _, b in mm)
    return sum(a for a, _ in mm), sum(b for _, b in mm)


def is_fixed(typ, types):
    a, b = min_max_bits(typ, types)
    return a == b


def tail_sensitive(typ, types):
    """Whether the value is written differently in tail position."""
    if isinstance(typ, (Prim, Void)):
        return False
    if isinstance(typ, Ref):
        b = types[typ.full].bodies[0]
        if b.union:
            return any(tail_sensitive(f.typ, types) for f in b.fields)
        return bool(b.fields) and tail_sensitive(b.fields[-1].typ, types)
    if typ.mode == "static":
        return typ.n > 0 and tail_sensitive(typ.elem, types)
    return tao_applies(typ, types) or tail_sensitive(typ.elem, types)


def tao_applies(arr, types):
    """A dynamic array in tail position loses its length prefix when its
    element type is at least 8 bits long."""
    return arr.mode == "dynamic" and min_max_bits(arr.elem, types)[0] >= 8


# ------------------------------------------------- DroneCAN serializer -----
# Written from the DSDL serialization rules: fields in order, no padding
# between them; a value of n bits is cut into bytes little-endian, each byte
# written most significant bit first, a last partial byte holding the top
# bits; a dynamic array has a length prefix unless the tail-array rule
# applies; a union starts with its tag.

class BitWriter:
    def __init__(self):
        self.bits = []

    def write_uint(self, v, n):
        if n <= 8:
            self.bits += [(v >> (n - 1 - i)) & 1 for i in range(n)]
            return
        left = n
        while left > 0:
            take = min(8, left)
            byte = v & ((1 << take) - 1)
            v >>= take
            self.bits += [(byte >> (take - 1 - i)) & 1 for i in range(take)]
            left -= take

    def to_bytes(self):
        b = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, b[i:i + 8])), 2) for i in range(0, len(b), 8))


def f16_bits(x):
    return struct.unpack("<H", struct.pack("<e", x))[0]


def ser_value(w, typ, val, types, tao):
    if isinstance(typ, Void):
        w.write_uint(0, typ.bits)
    elif isinstance(typ, Prim):
        if typ.kind == "float":
            raw = {16: f16_bits, 32: lambda x: struct.unpack("<I", struct.pack("<f", x))[0],
                   64: lambda x: struct.unpack("<Q", struct.pack("<d", x))[0]}[typ.bits](val)
            w.write_uint(raw, typ.bits)
        else:
            w.write_uint(val & ((1 << typ.bits) - 1), typ.bits)
    elif isinstance(typ, Ref):
        ser_body(w, types[typ.full].bodies[0], val, types, tao)
    else:
        # the tail-array rule passes on to the last element (as the reference
        # implementation pydronecan does)
        last = len(val) - 1
        if typ.mode == "static":
            for i, v in enumerate(val):
                ser_value(w, typ.elem, v, types, tao and i == last)
        elif tao and tao_applies(typ, types):
            for v in val:
                ser_value(w, typ.elem, v, types, False)
        else:
            w.write_uint(len(val), bits_for(typ.n))
            for i, v in enumerate(val):
                ser_value(w, typ.elem, v, types, tao and i == last)


def ser_body(w, body, val, types, tao):
    if body.union:
        tag, inner = val
        w.write_uint(tag, tag_bits(len(body.fields)))
        ser_value(w, body.fields[tag].typ, inner, types, tao)
        return
    for i, f in enumerate(body.fields):
        last = i == len(body.fields) - 1
        ser_value(w, f.typ, val.get(f.name) if f.name else None, types, tao and last)


# --------------------------------------------------------- the pack layout ---
# The layout of one body as a tree of nodes, before kinds are formed:
#   ("field", key, bits, transform, swap, value-path)   one model key
#   ("pad", bits, reason)                                bits the pack skips
#   ("group", list, prefix bits, [nodes], elem type)     a dynamic array
#   ("union", tag bits, [(variant, [nodes])])            a union
#   ("stop", reason)                                     nothing after it is mapped

def snake(name):
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    s = re.sub(r"(?<=[A-Z])([A-Z][a-z])", r"_\1", s)
    return s.lower()


def prim_line(typ):
    """(transform, swap) for a primitive, or None when the pack cannot state it."""
    if typ.kind in ("uint", "bool"):
        tr = "uint"
    elif typ.kind == "int":
        tr = "twos"
    else:
        if typ.bits == 16:
            return None                  # no half-precision transform
        tr = "f32" if typ.bits == 32 else "f64"
    if typ.bits <= 8:
        return tr, False
    if typ.bits % 8 == 0:
        return tr, True                  # little-endian bytes in an msb pack
    return None                          # bytes little-endian, last one partial


class Layout:
    def __init__(self, types, module, top=None, depth=0):
        self.types, self.module = types, module
        self.top, self.depth = top, depth  # data type and prefix length, for CORE
        self.unmapped = []               # (path, type text, reason)

    def key(self, path):
        return "%s.%s" % (self.module, "_".join(path))

    def body(self, body, path, tao):
        if body.union:
            variants = []
            for f in body.fields:
                variants.append((f.name, self.value(f.typ, path + [f.name], tao)))
            return [("union", tag_bits(len(body.fields)), variants)]
        out = []
        for i, f in enumerate(body.fields):
            last = i == len(body.fields) - 1
            if f.name is None:
                out.append(("pad", f.typ.bits, "void"))
                continue
            out += self.value(f.typ, path + [f.name], tao and last)
        return out

    def value(self, typ, path, tao):
        types = self.types
        if isinstance(typ, Void):
            return [("pad", typ.bits, "void")]
        if isinstance(typ, Prim):
            pl = prim_line(typ)
            if pl is None:
                why = ("float16: no half-precision transform" if typ.kind == "float"
                       else "%d-bit integer: not a whole number of bytes, wider than 8 bits" % typ.bits)
                self.unmapped.append(("_".join(path), repr(typ), why))
                return [("pad", typ.bits, why)]
            tm = TIME.get((self.top, "_".join(path[self.depth:]))) if self.top else None
            if tm:
                if typ.kind != "uint":
                    raise GenError("TIME entry for a %r field" % typ)
                return [("field", "time_ms", typ.bits, tm[0], pl[1], tuple(path))]
            core = CORE.get((self.top, "_".join(path[self.depth:]))) if self.top else None
            if core:
                if typ.kind == "int" and typ.bits == 32:
                    return [("field", core[0], 32, "sscale:" + DEGE7, True, tuple(path))]
                if typ.kind == "float" and typ.bits == 64:
                    return [("field", core[0], 64, "f64", True, tuple(path))]
                raise GenError("CORE entry for a %r field" % typ)
            return [("field", self.key(path), typ.bits, pl[0], pl[1], tuple(path))]
        if isinstance(typ, Ref):
            return self.body(types[typ.full].bodies[0], path, tao)
        if typ.mode == "static":
            if typ.n > MAX_STATIC_UNROLL:
                lo, hi = min_max_bits(typ, types)
                why = "static array of %d elements (more than %d)" % (typ.n, MAX_STATIC_UNROLL)
                self.unmapped.append(("_".join(path), "%s[%d]" % (type_text(typ.elem), typ.n), why))
                if lo == hi:
                    return [("pad", lo, why)]
                return [("stop", why)]
            out = []
            for i in range(typ.n):
                out += self.value(typ.elem, path + [str(i)], tao and i == typ.n - 1)
            return out
        # dynamic
        if tao and tao_applies(typ, types):
            why = "tail array: no length prefix, the items run to the end of the payload"
            self.unmapped.append(("_".join(path), "%s[<=%d]" % (type_text(typ.elem), typ.n), why))
            return [("stop", why)]
        if tao and tail_sensitive(typ.elem, types):
            why = "the last item of the array is written by the tail-array rule, the others are not"
            self.unmapped.append(("_".join(path), "%s[<=%d]" % (type_text(typ.elem), typ.n), why))
            return [("stop", why)]
        inner = Layout(types, self.module)
        nodes = inner.value(typ.elem, path + ["item"], False)
        self.unmapped += inner.unmapped
        return [("group", self.key(path), bits_for(typ.n), nodes, typ)]


def type_text(typ):
    if isinstance(typ, Prim):
        return repr(typ)
    if isinstance(typ, Ref):
        return typ.full
    if isinstance(typ, Void):
        return "void%d" % typ.bits
    return type_text(typ.elem) + ("[%d]" % typ.n if typ.mode == "static" else "[<=%d]" % typ.n)


class Unsupported(Exception):
    pass


def resolve(nodes, top):
    """Turn a node list into (common lines, kinds). A kind is (name, tag bits,
    tag value, lines). At most one union per scope; a second one, or a stop or
    union that cannot be stated, ends the scope at top level and makes an
    inner scope unsupported."""
    common, i = [], 0
    while i < len(nodes):
        n = nodes[i]
        if n[0] == "union":
            rest = nodes[i + 1:]
            kinds = []
            for v, (vname, vnodes) in enumerate(n[2]):
                body = vnodes + rest
                lines = flat(body, top, allow_union=False)
                kinds.append((vname, n[1], v, lines))
            return common, kinds
        if n[0] == "stop":
            if top:
                common.append(("stop", n[1]))
                return common, []
            raise Unsupported(n[1])
        common += flat([n], top, allow_union=False)
        i += 1
    return common, []


def flat(nodes, top, allow_union):
    out = []
    for n in nodes:
        if n[0] in ("field", "pad"):
            out.append(n)
        elif n[0] == "stop":
            if top:
                out.append(n)
                return out
            raise Unsupported(n[1])
        elif n[0] == "union":
            why = "a second union in one scope"
            if top:
                out.append(("stop", why))
                return out
            raise Unsupported(why)
        elif n[0] == "group":
            try:
                c, k = resolve(n[3], top=False)
            except Unsupported as e:
                why = "array %s: %s" % (n[1], e)
                if top:
                    out.append(("stop", why))
                    return out
                raise
            out.append(("group", n[1], n[2], c, k, n[4]))
    return out


# --------------------------------------------------------------- emitting ---

def emit_lines(lines, ind, out, keys, lists):
    for ln in lines:
        if ln[0] == "field":
            _, key, bits, tr, swap, path = ln
            out.append("%sfield  %s  %d  %s%s" % (ind, key, bits, tr, "  swap" if swap else ""))
            if "." in key:
                keys[key] = "float" if tr.startswith(("f", "sscale")) else "int"
        elif ln[0] == "pad":
            out.append("%spad    %d" % (ind, ln[1]))
        elif ln[0] == "stop":
            out.append("%s# not mapped from here on: %s" % (ind, ln[1]))
        elif ln[0] == "group":
            _, lst, pbits, common, kinds, _t = ln
            lists[lst] = True
            out.append("%sgroup  %s  count %d" % (ind, lst, pbits))
            emit_scope(common, kinds, ind + "  ", out, keys, lists)
            out.append("%send" % ind)


def emit_scope(common, kinds, ind, out, keys, lists):
    emit_lines(common, ind, out, keys, lists)
    # kinds with no key to require go last, so encode picks them only when no
    # other kind qualifies
    order = sorted(kinds, key=lambda k: (not req_keys(k[3]), k[2]))
    for name, tbits, tval, lines in order:
        out.append("%skind   %s" % (ind, name))
        out.append("%swhen   %d  %d" % (ind, tbits, tval))
        rk = req_keys(lines)
        if rk:
            out.append("%srequires %s" % (ind, " ".join(rk[:4])))
        emit_lines(lines, ind, out, keys, lists)


def req_keys(lines):
    return [ln[1] for ln in lines if ln[0] == "field"]


class PackSpec:
    def __init__(self, t, body_index):
        self.t = t
        self.bi = body_index
        base = t.full.lower().replace("_", "-").replace(".", "-")
        self.role = None
        if t.service:
            self.role = "request" if body_index == 0 else "response"
            base += "-" + self.role
        self.format = "dronecan-" + base
        self.body = t.bodies[body_index]
        self.prefix = [snake(t.short)] + ([self.role] if t.service else [])


def module_name(ns):
    return "dc" + re.sub(r"[^a-z0-9]", "", ns.lower())


def build_pack(ps, types):
    mod = module_name(ps.t.ns)
    lay = Layout(types, mod, ps.t.full, len(ps.prefix))
    nodes = lay.body(ps.body, ps.prefix, True)
    common, kinds = resolve(nodes, top=True)
    out, keys, lists = [], collections.OrderedDict(), collections.OrderedDict()
    emit_scope(common, kinds, "", out, keys, lists)
    ps.common, ps.kinds, ps.lines_text = common, kinds, out
    ps.keys, ps.lists, ps.unmapped, ps.module = keys, lists, lay.unmapped, mod
    ps.stops = collect_stops(common) + [s for k in kinds for s in collect_stops(k[3])]
    ps.lat_lon_seen = {ln[1] for ln in iter_fields(common, kinds) if ln[1] in ("lat", "lon")}
    if ps.lat_lon_seen and ps.lat_lon_seen != {"lat", "lon"}:
        raise GenError("%s maps only one of lat and lon" % ps.format)


def collect_stops(lines):
    out = []
    for ln in lines:
        if ln[0] == "stop":
            out.append(ln[1])
        elif ln[0] == "group":
            out += collect_stops(ln[3])
            for k in ln[4]:
                out += collect_stops(k[3])
    return out


# Data types whose all-zero payload is a command or a state by their definition (a hardpoint release, a
# parameter save, GOOD_TO_ARM ...), or a message that sets something. Their pack has one kind that requires
# every top-level field, so that a conversion from a format with none of them is no-kind and not zeros.
REQUIRE_ALL = {
    "dronecan-uavcan-equipment-hardpoint-command", "dronecan-uavcan-equipment-safety-armingstatus",
    "dronecan-uavcan-equipment-camera-gimbal-angularcommand", "dronecan-ardupilot-indication-safetystate",
    "dronecan-dronecan-remoteid-armstatus", "dronecan-uavcan-protocol-param-executeopcode-request",
    "dronecan-uavcan-protocol-file-beginfirmwareupdate-request", "dronecan-uavcan-protocol-file-write-request",
    "dronecan-uavcan-protocol-enumeration-begin-request", "dronecan-com-hobbywing-esc-setbaud-request",
    "dronecan-com-hobbywing-esc-setdirection-request", "dronecan-com-hobbywing-esc-setthrottlesource-request",
    "dronecan-com-hobbywing-esc-setid-request", "dronecan-com-hobbywing-esc-setangle-request",
    "dronecan-com-hobbywing-esc-setled-request", "dronecan-com-tmotor-esc-focctrl",
    "dronecan-com-tmotor-esc-paramcfg",
    "cyphal-uavcan-node-executecommand-1-0-request", "cyphal-uavcan-node-executecommand-1-1-request",
    "cyphal-uavcan-node-executecommand-1-2-request", "cyphal-uavcan-node-executecommand-1-3-request",
    "cyphal-uavcan-file-write-1-0-request", "cyphal-uavcan-file-write-1-1-request",
    "cyphal-uavcan-file-modify-1-0-request", "cyphal-uavcan-file-modify-1-1-request",
}


def with_required(fmt, lines):
    """The lines of a pack without kinds, under one kind that requires its top-level fields."""
    if fmt not in REQUIRE_ALL:
        return lines
    need, depth = [], 0
    for line in lines:
        t = line.split()
        if t and t[0] in ("group", "switch", "length", "if"):
            depth += 1
        elif t and t[0] == "end":
            depth -= 1
        elif t and t[0] == "field" and depth == 0:
            need.append(t[1])
        elif t and t[0] == "kind" and depth == 0:
            raise GenError(fmt + " has kinds already")
    if not need:
        raise GenError(fmt + " has no top-level field to require")
    return ["", "kind  message", "requires  " + "  ".join(need)] + [x for x in lines if x]


def pack_text(ps, sha):
    t = ps.t
    o = ["# DroneCAN (UAVCAN v0) data type %s%s, default data type ID %d." % (
            t.full, " (%s)" % ps.role if ps.role else "", t.dtid),
         "# Generated by tools/gen/dsdl2pack.py; do not edit by hand.",
         "# The message is the reassembled transfer payload. The data type ID travels",
         "# in the CAN identifier, so the caller names this format.",
         "format        %s" % ps.format,
         "version       %s" % VERSION,
         "distribution  public",
         'source        "%s %s at commit %s"' % (REPO, t.path, sha),
         'source        "DroneCAN specification, data structure description language, %s"' % SPEC,
         "uses          %s" % ps.module,
         "wire          bits",
         "layout        sequential",
         "bit_order     msb"]
    return "\n".join(o + with_required(ps.format, ps.lines_text)) + "\n"


def module_text(ns, packs, sha):
    mod = module_name(ns)
    o = ["# The %s module: fields of the DroneCAN data types in namespace %s." % (mod, ns),
         "# Generated by tools/gen/dsdl2pack.py; do not edit by hand.",
         "# Raw values in the units the definition states; a key is <type>_<field path>.",
         "module        %s" % mod,
         "version       %s" % VERSION,
         "distribution  public"]
    paths = sorted({p.t.path for p in packs})
    for p in paths:
        o.append('source        "%s %s at commit %s"' % (REPO, p, sha))
    seen = set()
    for p in packs:
        for k, typ in p.keys.items():
            name = k.split(".", 1)[1]
            if name in seen:
                raise GenError("key %s twice in module %s" % (name, mod))
            seen.add(name)
            o.append('key   %s  %s  -  "%s of %s"' % (name, typ, field_words(name, p), p.t.full))
        # a field now bound to core time_ms keeps the raw key it had before, so
        # no key of the module is removed (AGENTS.md rule 7)
        for (tfull, fname) in TIME:
            name = "_".join(p.prefix + [fname])
            if tfull == p.t.full and not p.role and name not in seen:
                seen.add(name)
                o.append('key   %s  int  -  "%s of %s; no longer mapped, the value is core time_ms"'
                         % (name, field_words(name, p), p.t.full))
        for l in p.lists:
            name = l.split(".", 1)[1]
            if name in seen:
                raise GenError("list %s twice in module %s" % (name, mod))
            seen.add(name)
            o.append('list  %s  "the items of dynamic array %s of %s"' % (
                name, name[len("_".join(p.prefix)) + 1:], p.t.full))
    return "\n".join(o) + "\n"


def field_words(name, p):
    rest = name[len("_".join(p.prefix)) + 1:]
    return "field %s%s" % (rest, " (%s)" % p.role if p.role else "")


# --------------------------------------------------------- sample values ---

def sample(typ, types, salt, path):
    """A value of the DroneCAN type; unmappable primitives are 0 so the pack's
    zero padding reproduces them."""
    if isinstance(typ, Void):
        return None
    if isinstance(typ, Prim):
        if prim_line(typ) is None:
            return 0.0 if typ.kind == "float" else 0
        if typ.kind == "float":
            return ((salt % 41) - 20) * 0.25
        if typ.kind in ("uint", "bool"):
            v = (salt * 2654435761 + 12345) % (1 << min(typ.bits, 31))
            if typ.bits == 64 and salt % 2:
                v |= 1 << 63
            return v
        span = 1 << min(typ.bits, 31)
        return (salt * 40503 + 7) % span - span // 2
    if isinstance(typ, Ref):
        return sample_body(types[typ.full].bodies[0], types, salt, path, None)
    if typ.mode == "static":
        if typ.n > MAX_STATIC_UNROLL:
            return [zero(typ.elem, types) for _ in range(typ.n)]
        return [sample(typ.elem, types, salt + 3 * i + 1, path) for i in range(typ.n)]
    count = min(typ.n, 1 + salt % 3)
    return [sample(typ.elem, types, salt + 5 * i + 2, path) for i in range(count)]


def zero(typ, types):
    if isinstance(typ, Void):
        return None
    if isinstance(typ, Prim):
        return 0.0 if typ.kind == "float" else 0
    if isinstance(typ, Ref):
        b = types[typ.full].bodies[0]
        if b.union:
            return (0, zero(b.fields[0].typ, types))
        return {f.name: zero(f.typ, types) for f in b.fields if f.name}
    if typ.mode == "static":
        return [zero(typ.elem, types) for _ in range(typ.n)]
    return []


def sample_body(body, types, salt, path, variant):
    if body.union:
        v = variant if variant is not None else salt % len(body.fields)
        return (v, sample(body.fields[v].typ, types, salt + 11, path))
    return {f.name: sample(f.typ, types, salt + 7 * i + 1, path)
            for i, f in enumerate(body.fields) if f.name}


def fit_to_layout(val, typ, types, tao, nodes_stop):
    """Zero what the pack does not reproduce: a tail array and anything after
    a stop. Returns the value and whether a stop was reached."""
    return val


# ------------------------------------------------ independent pack engine ---
# A reader and a small engine for the subset of the sequential bits wire this
# generator writes (field, pad, group count, kind/when/requires; msb order;
# swap), written from spec/engine-spec.md.

def tokens(line):
    out, i, n = [], 0, len(line)
    while i < n:
        if line[i].isspace():
            i += 1
        elif line[i] == "#":
            break
        elif line[i] == '"':
            j = line.find('"', i + 1)
            out.append(line[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and not line[j].isspace():
                j += 1
            out.append(line[i:j])
            i = j
    return out


def read_pack(text):
    head, uses = {}, []
    root = {"lines": [], "kinds": []}
    stack = [root]
    cur = root["lines"]
    in_kind = [None]
    for ln, raw in enumerate(text.splitlines(), 1):
        t = tokens(raw)
        if not t:
            continue
        d, a = t[0], t[1:]
        scope = stack[-1]
        if d in ("format", "version", "distribution", "wire", "layout", "bit_order"):
            head[d] = a[0]
        elif d == "source":
            head.setdefault("sources", 0)
            head["sources"] += 1
        elif d == "uses":
            uses.append(a[0])
        elif d == "field":
            cur.append(("field", a[0], int(a[1]), a[2], "swap" in a[3:]))
        elif d == "pad":
            cur.append(("pad", int(a[0])))
        elif d == "group":
            if a[1] != "count":
                raise GenError("line %d: group form %s" % (ln, a[1]))
            g = {"list": a[0], "count": int(a[2]), "lines": [], "kinds": []}
            cur.append(("group", g))
            stack.append(g)
            cur = g["lines"]
        elif d == "end":
            stack.pop()
            scope = stack[-1]
            cur = scope["kinds"][-1]["lines"] if scope["kinds"] else scope["lines"]
        elif d == "kind":
            k = {"name": a[0], "when": [], "requires": [], "lines": []}
            scope["kinds"].append(k)
            cur = k["lines"]
        elif d == "when":
            scope["kinds"][-1]["when"].append((int(a[0]), int(a[1])))
        elif d == "requires":
            scope["kinds"][-1]["requires"] += a
        else:
            raise GenError("line %d: directive %s" % (ln, d))
    if len(stack) != 1:
        raise GenError("unbalanced group")
    for need in ("format", "version", "distribution", "wire", "layout", "bit_order"):
        if need not in head:
            raise GenError("pack lacks " + need)
    if not head.get("sources"):
        raise GenError("missing-source")
    return head, uses, root


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def read(self, n):
        if self.pos + n > 8 * len(self.data):
            raise GenError("malformed-wire")
        v = 0
        for i in range(n):
            p = self.pos + i
            v = (v << 1) | ((self.data[p // 8] >> (7 - p % 8)) & 1)
        self.pos += n
        return v


def from_raw(tr, n, v, swap):
    if swap:
        v = int.from_bytes(v.to_bytes(n // 8, "big"), "little")
    if tr == "uint":
        return v - (1 << 64) if n == 64 and v >> 63 else v
    if tr == "twos":
        return v - (1 << n) if v >> (n - 1) else v
    if tr == "f32":
        return struct.unpack(">f", v.to_bytes(4, "big"))[0]
    if tr == "f64":
        return struct.unpack(">d", v.to_bytes(8, "big"))[0]
    if tr.startswith("sscale:"):
        num, den = (int(x) for x in tr.split(":")[1].split("/"))
        if v >> (n - 1):
            v -= 1 << n
        return v * float(num) / float(den)         # engine-spec 0.5 ruling 1
    if tr.startswith("uiscale:"):
        num, den, off = int_scale(tr)               # engine-spec 0.15: round(v * factor) + offset
        q = Fraction(v * num, den)
        return int(math.floor(abs(q) + Fraction(1, 2))) * (1 if q >= 0 else -1) + off
    raise GenError("transform " + tr)


def int_scale(tr):
    """(numerator, denominator, offset) of a `uiscale:<factor>[:<offset>]`."""
    parts = tr.split(":")[1:]
    f = Fraction(*map(int, parts[0].split("/"))) if "/" in parts[0] else Fraction(Decimal(parts[0]))
    return f.numerator, f.denominator, int(parts[1]) if len(parts) > 1 else 0


def to_raw(tr, n, x, swap):
    if tr in ("uint", "twos"):
        v = x & ((1 << n) - 1)
    elif tr.startswith("sscale:"):
        num, den = (int(x_) for x_ in tr.split(":")[1].split("/"))
        q = (x * float(den) / float(num))
        r = int(math.floor(abs(q) + 0.5)) * (1 if q >= 0 else -1)
        v = r & ((1 << n) - 1)
    elif tr == "f32":
        v = int.from_bytes(struct.pack(">f", x), "big")
    elif tr.startswith("uiscale:"):
        num, den, off = int_scale(tr)               # round((x - offset) / factor)
        q = Fraction((x - off) * den, num)
        v = int(math.floor(abs(q) + Fraction(1, 2))) * (1 if q >= 0 else -1)
        if not 0 <= v < 1 << n:
            raise GenError("transform-encode")
    else:
        v = int.from_bytes(struct.pack(">d", x), "big")
    if swap:
        v = int.from_bytes(v.to_bytes(n // 8, "big"), "little")
    return v


def dec_scope(r, scope, ent):
    dec_lines(r, scope["lines"], ent)
    if scope["kinds"]:
        start = r.pos
        for k in scope["kinds"]:
            r.pos = start
            if all(r.pos + n <= 8 * len(r.data) and r.read(n) == v for n, v in k["when"]):
                ent["@kind"] = k["name"]
                dec_lines(r, k["lines"], ent)
                return
        raise GenError("no-kind")


def dec_lines(r, lines, ent):
    for ln in lines:
        if ln[0] == "field":
            _, key, n, tr, swap = ln
            ent[key] = from_raw(tr, n, r.read(n), swap)
        elif ln[0] == "pad":
            r.read(ln[1])
        else:
            g = ln[1]
            cnt = r.read(g["count"])
            items = []
            for _ in range(cnt):
                it = {}
                dec_scope(r, g, it)
                items.append(it)
            ent[g["list"]] = items


class Writer:
    def __init__(self):
        self.bits = []

    def write(self, v, n):
        self.bits += [(v >> (n - 1 - i)) & 1 for i in range(n)]

    def to_bytes(self):
        b = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, b[i:i + 8])), 2) for i in range(0, len(b), 8))


def enc_scope(w, scope, ent):
    enc_lines(w, scope["lines"], ent)
    if scope["kinds"]:
        k = None
        if "@kind" in ent:
            k = next(x for x in scope["kinds"] if x["name"] == ent["@kind"])
        else:
            for x in scope["kinds"]:
                if all(rk in ent for rk in x["requires"]):
                    k = x
                    break
        if k is None:
            raise GenError("no-kind")
        for n, v in k["when"]:
            w.write(v, n)
        enc_lines(w, k["lines"], ent)


def enc_lines(w, lines, ent):
    for ln in lines:
        if ln[0] == "field":
            _, key, n, tr, swap = ln
            w.write(to_raw(tr, n, ent[key], swap) if key in ent else 0, n)
        elif ln[0] == "pad":
            w.write(0, ln[1])
        else:
            g = ln[1]
            items = ent.get(g["list"], [])
            w.write(len(items), g["count"])
            for it in items:
                enc_scope(w, g, it)


# --------------------------------------------------------------- vectors ---

def fmt_float(x):
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 1e17:
        return str(int(x))
    r = repr(x)
    return format(Decimal(r), "f") if "e" in r or "E" in r else r


def elem_supported(typ, types, module):
    lay = Layout(types, module)
    try:
        resolve(lay.value(typ, ["x"], False), top=False)
        return True
    except Unsupported:
        return False


def mapped_prefix_bits(ps, types, val):
    """The bit length of the part of the serialized value the pack maps: the
    whole value, or the bits before the first point the layout cannot state
    (a tail array, a second union in the message's scope, an array whose items
    cannot be stated, a long static array of varying length)."""
    w = BitWriter()

    class Stop(Exception):
        pass

    unions = [0]

    def walk_body(body, v, tao):
        if body.union:
            unions[0] += 1
            if unions[0] > 1:
                raise Stop()
            tag, inner = v
            w.write_uint(tag, tag_bits(len(body.fields)))
            walk_val(body.fields[tag].typ, inner, tao)
            return
        for i, f in enumerate(body.fields):
            last = i == len(body.fields) - 1
            walk_val(f.typ, v.get(f.name) if f.name else None, tao and last)

    def walk_val(typ, v, tao):
        if isinstance(typ, Ref):
            walk_body(types[typ.full].bodies[0], v, tao)
        elif isinstance(typ, Arr) and typ.mode == "dynamic":
            if tao and tao_applies(typ, types):
                raise Stop()
            if tao and tail_sensitive(typ.elem, types):
                raise Stop()
            if not elem_supported(typ.elem, types, ps.module):
                raise Stop()
            ser_value(w, typ, v, types, False)
        elif isinstance(typ, Arr):
            if typ.n > MAX_STATIC_UNROLL:
                if not is_fixed(typ, types):
                    raise Stop()
                ser_value(w, typ, v, types, False)
            else:
                for i, x in enumerate(v):
                    walk_val(typ.elem, x, tao and i == len(v) - 1)
        else:
            ser_value(w, typ, v, types, False)

    try:
        walk_body(ps.body, val, True)
    except Stop:
        pass
    return len(w.bits)


def model_of(ps, val):
    """The entity the pack decodes from the value, built from the DSDL value
    and the key-naming rule, not from the pack."""
    ent = collections.OrderedDict()
    types = ps.types

    def body(b, v, path, out):
        if b.union:
            tag, inner = v
            if "@kind" not in out:          # the first union of the scope selects the kind
                out["@kind"] = b.fields[tag].name
            value(b.fields[tag].typ, inner, path + [b.fields[tag].name], out)
            return
        for f in b.fields:
            if f.name:
                value(f.typ, v[f.name], path + [f.name], out)

    def value(typ, v, path, out):
        key = "%s.%s" % (ps.module, "_".join(path))
        core = CORE.get((ps.t.full, "_".join(path[len(ps.prefix):])))
        tm = TIME.get((ps.t.full, "_".join(path[len(ps.prefix):])))
        if isinstance(typ, Prim) and tm:
            out["time_ms"] = from_raw(tm[0], typ.bits, v, False)
            return
        if isinstance(typ, Prim) and core:
            out[core[0]] = v / 10000000.0 if typ.kind == "int" else v
            return
        if isinstance(typ, Prim):
            if prim_line(typ) is not None:
                if typ.kind == "uint" and typ.bits == 64 and v >> 63:
                    v -= 1 << 64          # engine-spec 0.5 ruling 2: same bits, negative
                out[key] = v
        elif isinstance(typ, Ref):
            body(types[typ.full].bodies[0], v, path, out)
        elif typ.mode == "static":
            if typ.n <= MAX_STATIC_UNROLL:
                for i, x in enumerate(v):
                    value(typ.elem, x, path + [str(i)], out)
        else:
            items = []
            for x in v:
                it = collections.OrderedDict()
                value(typ.elem, x, path + ["item"], it)
                items.append(it)
            out[key] = items

    body(ps.body, val, ps.prefix, ent)
    return ent


def prune(ent, ps):
    """Keep only what the pack maps (keys and lists that appear in it)."""
    names = set(ps.keys) | set(ps.lists) | {"lat", "lon", "time_ms"}
    out = collections.OrderedDict()
    for k, v in ent.items():
        if k == "@kind" or k in names:
            out[k] = [prune(i, ps) for i in v] if isinstance(v, list) else v
    return out


def model_strings(ent, prefix=""):
    out = collections.OrderedDict()
    for k, v in ent.items():
        if k == "@kind":
            out[prefix + "@kind"] = v
        elif isinstance(v, list):
            out[prefix + k + ".#"] = str(len(v))
            for i, it in enumerate(v):
                out.update(model_strings(it, "%s%s[%d]." % (prefix, k, i)))
        elif isinstance(v, float):
            out[prefix + k] = fmt_float(v)
        else:
            out[prefix + k] = str(v)
    return out


def values_for(ps, types):
    """One value per kind (per union variant at top level), or one value.
    A field bound to a core key takes the hand-chosen value of CROSS."""
    vals = values_for_raw(ps, types)
    if ps.t.full in CROSS and not ps.t.service:
        lat, lon = CROSS[ps.t.full][:2]
        for v in vals:
            for (tfull, fname), (ck, _) in CORE.items():
                if tfull == ps.t.full and fname in v:
                    v[fname] = lat if ck == "lat" else lon
    return vals


def values_for_raw(ps, types):
    salt = (ps.t.dtid or 0) * 31 + (17 if ps.role == "response" else 3)
    if ps.kinds and ps.body.union:
        return [sample_body(ps.body, types, salt + i, None, i) for i in range(len(ps.body.fields))]
    if ps.kinds:
        # a union nested in the body: one value per variant of that union
        vals = []
        for i in range(len(ps.kinds)):
            vals.append(force_variant(sample_body(ps.body, types, salt + i, None, None),
                                      ps.body, types, i))
        return vals
    return [sample_body(ps.body, types, salt, None, None)]


def force_variant(val, body, types, v):
    """Set the first union met in the value (depth first, fields in order,
    outside arrays) to variant v."""
    done = [False]

    def walk_body(b, x):
        if b.union:
            if not done[0]:
                done[0] = True
                return (v, sample(b.fields[v].typ, types, 13 + v, None))
            return x
        for f in b.fields:
            if f.name and not done[0]:
                x[f.name] = walk_val(f.typ, x[f.name])
        return x

    def walk_val(typ, x):
        if isinstance(typ, Ref):
            return walk_body(types[typ.full].bodies[0], x)
        if isinstance(typ, Arr) and typ.mode == "static" and typ.n <= MAX_STATIC_UNROLL:
            return [walk_val(typ.elem, e) for e in x]
        return x
    return walk_body(body, val)


def vector_text(vec):
    return json.dumps(vec, indent=2) + "\n"


def vector_files(ps, types):
    """[(file name, text)] of the vectors of one pack."""
    vecs = []
    for i, val in enumerate(values_for(ps, types)):
        w = BitWriter()
        ser_body(w, ps.body, val, types, True)
        full = w.to_bytes()
        nbits = mapped_prefix_bits(ps, types, val)
        exp_bits = w.bits[:nbits] + [0] * (-nbits % 8)
        expect = bytes(int("".join(map(str, exp_bits[j:j + 8])), 2) for j in range(0, len(exp_bits), 8))
        ent = prune(model_of(ps, val), ps)
        name = "roundtrip" + ("-" + ent["@kind"] if "@kind" in ent else "")
        vec = collections.OrderedDict([
            ("name", "%s-%s" % (ps.format, name)), ("from", ps.format), ("to", ps.format),
            ("input", full.hex()), ("expect", expect.hex()),
            ("model", model_strings(ent))])
        fn = "rt-%02d%s.json" % (i, ("-" + ent["@kind"]) if "@kind" in ent else "")
        vecs.append((fn, vector_text(vec)))
    if ps.t.full in CROSS and not ps.t.service:
        val = values_for(ps, types)[0]
        w = BitWriter()
        ser_body(w, ps.body, val, types, True)
        ent = prune(model_of(ps, val), ps)
        model = collections.OrderedDict((k, v) for k, v in model_strings(ent).items()
                                        if k in ("lat", "lon", "@kind"))
        vec = collections.OrderedDict([
            ("name", "%s-to-geojson" % ps.format), ("from", ps.format), ("to", "geojson"),
            ("input", w.to_bytes().hex()), ("expect", CROSS[ps.t.full][2]), ("model", model)])
        vecs.append(("x-01-to-geojson.json", vector_text(vec)))
    if ps.t.full in TIME_CROSS and not ps.t.service:
        raw, expect = TIME_CROSS[ps.t.full]
        val = values_for(ps, types)[0]
        for (tfull, fname) in TIME:
            if tfull == ps.t.full:
                val[fname] = raw
        w = BitWriter()
        ser_body(w, ps.body, val, types, True)
        ent = prune(model_of(ps, val), ps)
        vec = collections.OrderedDict([
            ("name", "%s-time-to-geojson" % ps.format), ("from", ps.format), ("to", "geojson"),
            ("input", w.to_bytes().hex()), ("expect", expect),
            ("model", collections.OrderedDict([("time_ms", str(ent["time_ms"]))]))])
        vecs.append(("x-02-time-to-geojson.json", vector_text(vec)))
    return vecs


def write_vectors(out, vdir, files):
    """Write the vector files of a pack; remove every other .json there."""
    keep = {name for name, _ in files}
    for old in out.listdir(vdir):
        if old.endswith(".json") and old not in keep:
            out.remove("%s/%s" % (vdir, old))
    for name, text in files:
        out.write("%s/%s" % (vdir, name), text)


def geojson_of(ent):
    if "lat" in ent and "lon" in ent:
        geom = '{"type":"Point","coordinates":[%s,%s]}' % (fmt_float(ent["lon"]), fmt_float(ent["lat"]))
    else:
        geom = "null"
    props = '"time_ms":%d' % ent["time_ms"] if "time_ms" in ent else ""
    return '{"type":"Feature","geometry":%s,"properties":{%s}}' % (geom, props)


def check_vectors(pack_root, vectors, fmt, reader=None, decode=None, encode=None):
    """Decode and encode every vector [(file name, text)] with the reader of
    this file; the number checked."""
    reader, decode, encode = reader or Reader, decode or dec_scope, encode or (Writer, enc_scope)
    n = 0
    for fn, text in vectors:
        vec = json.loads(text)
        data = bytes.fromhex(vec["input"])
        ent = {}
        r = reader(data)
        decode(r, pack_root, ent)
        got_model = model_strings(collections.OrderedDict(
            (k, v) for k, v in ent.items()))
        for k, want in vec["model"].items():
            if k not in got_model:
                raise GenError("%s/%s: model %s absent" % (fmt, fn, k))
            g = got_model[k]
            if g != want:
                try:
                    if abs(float(g) - float(want)) <= 1e-9:
                        continue
                except ValueError:
                    pass
                raise GenError("%s/%s: model %s = %s, vector says %s" % (fmt, fn, k, g, want))
        if vec["to"] == "geojson":
            got = geojson_of(ent)
            if got != vec["expect"]:
                raise GenError("%s/%s: geojson %s, vector expects %s" % (fmt, fn, got, vec["expect"]))
            n += 1
            continue
        w = encode[0]()
        encode[1](w, pack_root, ent)
        got = w.to_bytes().hex()
        if got != vec["expect"]:
            raise GenError("%s/%s: encode gives %s, vector expects %s" % (fmt, fn, got, vec["expect"]))
        n += 1
    return n


def check_model(text, keys_needed):
    mod = {"keys": {}, "lists": set()}
    for raw in text.splitlines():
        t = tokens(raw)
        if not t:
            continue
        if t[0] == "key":
            if t[2] not in ("int", "float", "string"):
                raise GenError("bad key type")
            mod["keys"][t[1]] = t[2]
        elif t[0] == "list":
            mod["lists"].add(t[1])
    return mod


def check_pack_keys(root_scope, module, mods):
    def walk(scope):
        for ln in scope["lines"] + [l for k in scope["kinds"] for l in k["lines"]]:
            if ln[0] == "field":
                m, k = ln[1].split(".", 1) if "." in ln[1] else ("core", ln[1])
                if m not in (module, "core") or k not in mods[m]["keys"]:
                    raise GenError("undeclared-key " + ln[1])
                want = "float" if ln[3].startswith(("f", "sscale")) else "int"
                if mods[m]["keys"][k] != want:
                    raise GenError("key-type-mismatch " + ln[1])
            elif ln[0] == "group":
                m, k = ln[1]["list"].split(".", 1)
                if k not in mods[m]["lists"]:
                    raise GenError("undeclared list " + ln[1]["list"])
                walk(ln[1])
        for k in scope["kinds"]:
            for rk in k["requires"]:
                m, n = rk.split(".", 1)
                if n not in mods[m]["keys"] and n not in mods[m]["lists"]:
                    raise GenError("requires undeclared " + rk)
        names = [k["name"] for k in scope["kinds"]]
        if len(set(names)) != len(names):
            raise GenError("duplicate-kind")
    walk(root_scope)


# ------------------------------------------------------------- documents ---

def keyless_note(ps):
    """The pack.md sentence for union variants that map no key: on encode with no recorded kind
    (engine-spec Encode step 2) only the first of them can be chosen (tools/gen/kindorder.py)."""
    import kindorder
    _, kinds = kindorder._parse(list(ps.lines_text))
    names = [k["name"] for k in kinds if not k["keys"]]
    if len(kinds) < 2 or not names:
        return []
    if len(names) == 1:
        return ["", "On encode with no recorded kind, each variant is chosen by its keys; an entity",
                "with none of them is written as `%s`, the variant that maps no key." % names[0]]
    return ["", "On encode with no recorded kind, each variant is chosen by its keys. The variants",
            "%s map no key, so an entity with none is written as `%s`;" % (", ".join("`%s`" % n for n in names), names[0]),
            "the others are chosen only by a recorded kind."]


def pack_md(ps, sha, nvec):
    t = ps.t
    o = []
    a = o.append
    nfields = count_lines(ps.common, ps.kinds)
    a("# Pack: %s" % ps.format)
    a("")
    a("DroneCAN (UAVCAN v0) data type `%s`%s, default data type ID %d, as" % (
        t.full, " (the %s of the service)" % ps.role if ps.role else "", t.dtid))
    a("the payload of a transfer. Public. Generated by `tools/gen/dsdl2pack.py` from")
    a("`%s` (`%s`) at commit `%s`; do not edit `pack.def`, this file," % (REPO, t.path, sha))
    a("`PROVENANCE.md` or the vectors by hand. Module: `model/%s.def`." % ps.module)
    if t.deprecated:
        a("")
        a("The definition marks the type deprecated.")
    a("")
    a("Status: Built. Generated and checked by the generator's own codec and reader.")
    a("")
    a("## The message")
    a("")
    a("`wire bits`, `layout sequential`, `bit_order msb`. The input is the transfer")
    a("payload as the receiver reassembles it: for a single-frame transfer the frame")
    a("data without its tail byte, for a multi-frame transfer the data of all frames")
    a("without the tail bytes and without the transfer CRC. Hex text.")
    if ps.format in REQUIRE_ALL:
        a("")
        a("On encode from another format the one kind requires the top-level fields; an")
        a("entity without them is `no-kind`, not a payload of zeros. `Entity.kind` is now")
        a("recorded (`message`); same-format bytes do not change.")
    a("")
    a("**Which type a payload is.** The data type ID (%d) travels in the 29-bit CAN" % t.dtid)
    a("identifier%s, not in the payload, and" % (
        ", with the request/response bit" if t.service else ""))
    a("the payload has no field that tells the types apart. So each data type is its")
    a("own format, and the caller names the format: a receiver that reads data type")
    a("ID %d from a CAN identifier converts from `%s`." % (t.dtid, ps.format))
    a("")
    a("## What is mapped")
    a("")
    a("Fields follow one another with no padding, in definition order; a nested type")
    a("is written in place. The keys are `%s.%s_<field path>`, the path" % (ps.module, "_".join(ps.prefix)))
    a("joined by `_`, an element of a static array numbered from 0.")
    a("")
    a("| DSDL | Pack line | Model type |")
    a("|---|---|---|")
    a("| `uintN`, `bool`, N up to 8 | `field … N uint` | int |")
    a("| `intN`, N up to 8 | `field … N twos` | int |")
    a("| `uintN`, `intN` with N = 16, 24, 32, 40, 48, 56, 64 | `uint` / `twos` with `swap` | int |")
    a("| `float32`, `float64` | `f32` / `f64` with `swap` | float |")
    a("| `voidN` | `pad N` | - |")
    a("| `T[N]`, N up to %d | one line per element | as the element |" % MAX_STATIC_UNROLL)
    a("| `T[<=N]`, `T[<N]` with a length prefix | `group … count <bits of N>` | list |")
    a("| `@union` at the top of the type, or one union in it | one `kind` per variant, `when <tag bits> <variant>` | - |")
    a("")
    a("DroneCAN cuts a value of more than 8 bits into bytes least significant first and")
    a("writes each byte most significant bit first. For a whole number of bytes that is")
    a("a little-endian field read most significant bit first, which `swap` states. The")
    a("field need not start on a byte boundary; `swap` reverses the bytes of the field's")
    a("own bits.")
    a("")
    a("| | Count |")
    a("|---|---|")
    a("| `field` lines | %d |" % nfields)
    a("| model keys | %d |" % len(ps.keys))
    a("| lists (dynamic arrays) | %d |" % len(ps.lists))
    a("| kinds | %d |" % len(ps.kinds))
    a("| fields not mapped | %d |" % len(ps.unmapped))
    a("| vectors | %d |" % nvec)
    if ps.kinds:
        a("")
        a("Kinds: %s. A union's tag is the `when` of each kind; the lines after the" % ", ".join(
            "`%s` (tag %d)" % (k[0], k[2]) for k in ps.kinds))
        a("union are repeated in every kind. Encode chooses a kind by its `requires`;")
        a("a variant with no key is tried last.")
    a("")
    bound = [(f, v) for (t, f), v in CORE.items() if t == ps.t.full and v[0] in ps.lat_lon_seen]
    if bound:
        a("Core keys, bound by a table in the generator with the evidence the definition")
        a("gives (its field name, or the unit its comment states):")
        a("")
        a("| Field | Core key | Transform | Evidence |")
        a("|---|---|---|---|")
        for f, (ck, why) in bound:
            tr = [ln for ln in iter_fields(ps.common, ps.kinds) if ln[1] == ck][0][3]
            a("| `%s` | `%s` | `%s` with `swap` | %s |" % (f, ck, tr, why))
        a("")
        a("No other key is bound to a `core` or `track` key. Heights are left raw: the")
        a("definitions name the reference (ellipsoid, mean sea level) without the datum.")
    else:
        a("No key of this pack is bound to a `core` or `track` key: units and frames are")
        a("stated in the definition's comments, and the generator binds only the")
        a("latitude/longitude pairs it lists with their evidence.")
    times = [(f, v) for (t, f), v in TIME.items() if t == ps.t.full and not ps.role]
    if times:
        a("")
        a("Bound to core `time_ms` (epoch milliseconds UTC) by the generator's TIME table,")
        a("with an integer scale of engine-spec 0.15:")
        a("")
        a("| Field | Core key | Transform | Evidence |")
        a("|---|---|---|---|")
        for f, (tr, why) in times:
            a("| `%s` | `time_ms` | `%s` with `swap` | %s |" % (f, tr, why))
        a("")
        a("The raw key the field had before stays declared in the module, not mapped.")
    a("")
    a("## What is not mapped")
    a("")
    if ps.unmapped:
        a("| Field | Type | Reason |")
        a("|---|---|---|")
        for p, ty, why in ps.unmapped:
            a("| `%s` | `%s` | %s |" % (p, ty, why))
        a("")
        a("A field of fixed length that is not mapped is a `pad` line: decode skips it,")
        a("encode writes zero bits. A tail array, or anything whose length varies and that")
        a("cannot be stated, ends the mapped part: decode ignores the rest of the payload")
        a("and encode writes nothing after it.")
    else:
        a("Every field is mapped.")
    if ps.stops:
        a("")
        a("Mapping ends early: %s." % "; ".join(sorted(set(ps.stops))))
    for line in keyless_note(ps):
        a(line)
    a("")
    a("- Constants of the definition (they are not on the wire).")
    a("- The transfer layer: CAN identifier, tail byte, toggle bit, transfer CRC.")
    a("- Cast modes (`saturated`, `truncated`): encode writes the low bits of a value.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-NN*.json`: a same-format round trip%s. The input is the payload a" % (
        " per kind" if ps.kinds else ""))
    a("DroneCAN serializer written in the generator produces from sample values; fields")
    a("the pack does not map are zero. The expected output is that payload cut after")
    a("the last bit the pack maps. The generator decodes and re-encodes every vector")
    a("with its own reader of the pack.")
    return "\n".join(o) + "\n"


def iter_fields(common, kinds):
    for ln in common + [l for k in kinds for l in k[3]]:
        if ln[0] == "field":
            yield ln
        elif ln[0] == "group":
            yield from iter_fields(ln[3], ln[4])


def count_lines(common, kinds):
    n = 0
    for ln in common + [l for k in kinds for l in k[3]]:
        if ln[0] == "field":
            n += 1
        elif ln[0] == "group":
            n += count_lines(ln[3], ln[4])
    return n


def provenance_md(ps, sha, file_sha, license_sha):
    return "\n".join([
        "# Provenance: %s" % ps.format,
        "",
        "| Fact | Value |",
        "|---|---|",
        "| data type | `%s`%s, default data type ID %d |" % (
            ps.t.full, " (%s)" % ps.role if ps.role else "", ps.t.dtid),
        "| definition read | `%s` of %s |" % (ps.t.path, REPO),
        "| commit | `%s` |" % sha,
        "| SHA-256 of the definition | `%s` |" % file_sha,
        "| license of the repository | MIT, copyright (c) 2014-2015 Pavel Kirienko: `LICENSE` at the root of the commit (SHA-256 `%s`), verbatim in `tools/gen/sources/%s`; the definition file carries no license or copyright header of its own |" % (license_sha, PROV_NAME),
        "| date read | 2026-11-19 |",
        "| what the pack takes | type and field names, field types, array bounds, the `@union` marker and the data type ID; no comment text is copied (for the latitude/longitude pairs the generator binds to core keys, the unit a comment states is the evidence, restated in `pack.md`) |",
        "| generator | `tools/gen/dsdl2pack.py` |",
        ""])


def write_sources_provenance(out, rel, dsdl, sha, files):
    lic = read_text(os.path.join(dsdl, "LICENSE"))
    o = ["# Provenance of the DroneCAN DSDL inputs",
         "",
         "| Fact | Value |",
         "|---|---|",
         "| repository | %s |" % REPO,
         "| commit | `%s` (head of `master`, read 2026-11-19) |" % sha,
         "| archive | `https://codeload.github.com/dronecan/DSDL/tar.gz/%s` |" % sha,
         "| license | MIT, the file `LICENSE` at the root of the commit, verbatim below |",
         "",
         "## Files",
         "",
         "| Path | SHA-256 |",
         "|---|---|",
         "| `LICENSE` | `%s` |" % sha256(os.path.join(dsdl, "LICENSE"))]
    for f in files:
        o.append("| `%s` | `%s` |" % (f, sha256(os.path.join(dsdl, f))))
    o += ["", "## LICENSE", "", "```"] + lic.rstrip("\n").splitlines() + ["```", ""]
    out.write(rel, "\n".join(o))


def sha256(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read_text(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def read_sources_provenance(path, dsdl, files, text=None):
    if text is None:
        text = read_text(path)
    m = re.search(r"\| commit \| `([0-9a-f]{40})`", text)
    if not m:
        raise GenError("%s states no commit" % path)
    table = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    for rel in ["LICENSE"] + files:
        if rel not in table:
            raise GenError("%s has no SHA-256 for %s" % (path, rel))
        if sha256(os.path.join(dsdl, rel)) != table[rel]:
            raise GenError("%s does not match the SHA-256 in %s" % (rel, path))
    return m.group(1), table


# ================================================================ Cyphal ===
# Cyphal (UAVCAN v1) DSDL, github.com/OpenCyphal/public_regulated_data_types.
#
# Serialization, as the Cyphal DSDL rules state and pydsdl implements them:
# bits are filled least significant first (`bit_order lsb`); a primitive needs
# no alignment; a composite starts and ends on a byte boundary; a
# variable-length array has a length prefix of 8, 16, 32 or 64 bits (the
# smallest that holds the capacity), then its elements; a union starts with a
# tag of 8, 16, 32 or 64 bits; a composite that is not @sealed is written
# after a 32-bit delimiter header that states its length in bytes. A message
# at top level has no delimiter header.

CY_REPO = "https://github.com/OpenCyphal/public_regulated_data_types"
CY_SPEC = "https://opencyphal.org/specification"
CY_PROV_NAME = "cyphal-PROVENANCE.md"
CY_NAMESPACES = ["uavcan", "reg"]
CY_FILE_RE = re.compile(r"^(?:(\d+)\.)?([A-Za-z_][A-Za-z0-9_]*)\.(\d+)\.(\d+)\.dsdl$")
CY_PRIM_RE = re.compile(r"^(uint|int|float)(\d+)$")


class CyBody:
    def __init__(self):
        self.fields, self.union, self.sealed, self.extent = [], False, False, None
        self.consts = {}              # name -> expression text


class CyType:
    def __init__(self, ns, short, major, minor, port, path):
        self.ns, self.short, self.major, self.minor, self.port, self.path = ns, short, major, minor, port, path
        self.name = "%s.%s" % (ns, short)
        self.full = "%s.%d.%d" % (self.name, major, minor)
        self.bodies = [CyBody()]
        self.service = False
        self.deprecated = False


def cy_ref(text, ns):
    """A composite type reference: `a.b.Name.1.0` or, in the same namespace,
    `Name.1.0`."""
    parts = text.split(".")
    if len(parts) < 3 or not parts[-1].isdigit() or not parts[-2].isdigit():
        raise GenError("bad type reference " + text)
    if len(parts) == 3:
        return "%s.%s" % (ns, text)
    return text


CY_ARR_RE = re.compile(r"^([^\[]+)\[(<=|<)?([^\]]+)\]$")


def cy_parse_type(text, ns):
    m = CY_ARR_RE.match(text)
    if m:
        inner, op, n = m.group(1), m.group(2), m.group(3)
        return ("array", cy_parse_type(inner, ns), op, n)       # n resolved later
    if text == "bool":
        return Prim("bool", 1)
    if text in ("utf8", "byte"):
        return Prim("uint", 8)
    m = CY_PRIM_RE.match(text)
    if m:
        k, b = m.group(1), int(m.group(2))
        if k == "float" and b not in (16, 32, 64):
            raise GenError("bad float width " + text)
        return Prim(k, b)
    m = re.match(r"^void(\d+)$", text)
    if m:
        return Void(int(m.group(1)))
    return Ref(cy_ref(text, ns))


def cy_parse_file(path, rel):
    parts = rel.split("/")
    m = CY_FILE_RE.match(parts[-1])
    if not m:
        raise GenError("bad file name " + rel)
    port = int(m.group(1)) if m.group(1) else None
    t = CyType(".".join(parts[:-1]), m.group(2), int(m.group(3)), int(m.group(4)), port, rel)
    body = t.bodies[0]
    text = read_text(path)
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        where = "%s:%d" % (rel, ln)
        if line == "---":
            t.service = True
            body = CyBody()
            t.bodies.append(body)
            continue
        if line.startswith("@"):
            d = line.split(None, 1)
            if d[0] == "@union":
                body.union = True
            elif d[0] == "@sealed":
                body.sealed = True
            elif d[0] == "@extent":
                body.extent = d[1]
            elif d[0] == "@deprecated":
                t.deprecated = True
            elif d[0] in ("@assert", "@print"):
                pass
            else:
                raise GenError("%s: unknown directive %s" % (where, d[0]))
            continue
        toks = line.split(None, 1)
        if toks[0] in ("saturated", "truncated"):
            line = toks[1]
        m = re.match(r"^(\S+)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", line)
        if m:
            body.consts[m.group(2)] = m.group(3)
            continue
        toks = line.split()
        if len(toks) == 1 and toks[0].startswith("void"):
            body.fields.append(Field(None, cy_parse_type(toks[0], t.ns)))
            continue
        if len(toks) != 2 or not NAME_RE.match(toks[1]):
            raise GenError("%s: cannot read %r" % (where, raw))
        body.fields.append(Field(toks[1], cy_parse_type(toks[0], t.ns)))
    return t


class CyEval:
    """Integer and rational expressions of the DSDL: numbers, + - * / % **,
    parentheses, constants of the same body and `Type.M.N.CONST` of others."""

    def __init__(self, types):
        self.types = types

    def value(self, text, t, body):
        import ast
        from fractions import Fraction
        refs = {}

        def sub(m):
            name = m.group(0)
            if re.match(r"^0[xX][0-9a-fA-F]+$", name) or re.match(r"^\d", name):
                return name
            if name in ("true", "false"):
                return "1" if name == "true" else "0"
            key = "_r%d" % len(refs)
            refs[key] = self.resolve(name, t, body)
            return key
        expr = re.sub(r"[A-Za-z_0-9][A-Za-z_0-9.]*", sub, text.strip())
        tree = ast.parse(expr, mode="eval")

        def ev(node):
            if isinstance(node, ast.Expression):
                return ev(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return Fraction(node.value)
            if isinstance(node, ast.Name) and node.id in refs:
                return refs[node.id]
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                v = ev(node.operand)
                return -v if isinstance(node.op, ast.USub) else v
            if isinstance(node, ast.BinOp):
                a, b = ev(node.left), ev(node.right)
                op = type(node.op)
                if op is ast.Add:
                    return a + b
                if op is ast.Sub:
                    return a - b
                if op is ast.Mult:
                    return a * b
                if op is ast.Div:
                    return a / b
                if op is ast.FloorDiv:
                    return Fraction(a // b)
                if op is ast.Mod:
                    return a % b
                if op is ast.Pow and b.denominator == 1:
                    return a ** int(b)
            raise GenError("%s: expression %r not understood" % (t.path, text))
        return ev(tree)

    def resolve(self, name, t, body):
        if "." not in name:
            if name in body.consts:
                return self.value(body.consts[name], t, body)
            raise GenError("%s: unknown constant %s" % (t.path, name))
        type_part, const = name.rsplit(".", 1)
        full = cy_ref(type_part, t.ns)
        if full not in self.types:
            raise GenError("%s: unknown type %s" % (t.path, full))
        other = self.types[full]
        return self.value(other.bodies[0].consts[const], other, other.bodies[0])

    def integer(self, text, t, body):
        v = self.value(text, t, body)
        if v.denominator != 1:
            raise GenError("%s: %r is not an integer" % (t.path, text))
        return int(v)


def cy_load(root, namespaces):
    types = {}
    for ns in namespaces:
        for dp, dn, fn in os.walk(os.path.join(root, ns)):
            dn.sort()
            for f in sorted(fn):
                if f.endswith(".dsdl"):
                    p = os.path.join(dp, f)
                    rel = os.path.relpath(p, root).replace(os.sep, "/")
                    t = cy_parse_file(p, rel)
                    if t.full in types:
                        raise GenError("type %s defined twice" % t.full)
                    types[t.full] = t
    ev = CyEval(types)

    def fix(typ, t, body):
        if isinstance(typ, tuple):
            _, elem, op, n = typ
            cap = ev.integer(n, t, body)
            elem = fix(elem, t, body)
            if op is None:
                return Arr(elem, "static", cap)
            return Arr(elem, "dynamic", cap if op == "<=" else cap - 1)
        if isinstance(typ, Ref):
            if typ.full not in types:
                raise GenError("%s refers to unknown type %s" % (t.path, typ.full))
            if types[typ.full].service:
                raise GenError("%s nests a service type" % t.path)
        return typ

    for t in types.values():
        for b in t.bodies:
            for f in b.fields:
                f.typ = fix(f.typ, t, b)
            if b.extent is not None:
                b.extent_bits = ev.integer(b.extent, t, b)
    return types


def cy_align(typ, types):
    """The alignment of a type in bits: 8 for a composite, 1 for a primitive or
    void, that of the element for an array."""
    if isinstance(typ, Ref):
        return 8
    if isinstance(typ, Arr):
        return cy_align(typ.elem, types)
    return 1


def cy_std_bits(n, align):
    """8, 16, 32 or 64: the smallest that holds n bits, and not below `align`."""
    b = 8
    while b < n:
        b *= 2
    return max(b, align)


def cy_prefix_bits(arr, types):
    return cy_std_bits(arr.n.bit_length(), cy_align(arr.elem, types))


def cy_tag_bits(body, types):
    return cy_std_bits((len(body.fields) - 1).bit_length(), max(cy_align(f.typ, types) for f in body.fields))


def cy_sealed(full, types):
    return types[full].bodies[0].sealed


class CyWriter:
    """Bits least significant first; `align`; nested writers for delimited
    composites."""

    def __init__(self):
        self.bits = []

    def write(self, v, n):
        self.bits += [(v >> i) & 1 for i in range(n)]

    def align(self, n):
        self.bits += [0] * (-len(self.bits) % n)

    def to_bytes(self):
        b = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(sum(b[i + j] << j for j in range(8)) for i in range(0, len(b), 8))


def cy_ser_value(w, typ, val, types):
    if isinstance(typ, Void):
        w.write(0, typ.bits)
    elif isinstance(typ, Prim):
        if typ.kind == "float":
            raw = {16: f16_bits, 32: lambda x: struct.unpack("<I", struct.pack("<f", x))[0],
                   64: lambda x: struct.unpack("<Q", struct.pack("<d", x))[0]}[typ.bits](val)
            w.write(raw, typ.bits)
        else:
            w.write(val & ((1 << typ.bits) - 1), typ.bits)
    elif isinstance(typ, Ref):
        w.align(8)
        body = types[typ.full].bodies[0]
        if body.sealed:
            cy_ser_body(w, body, val, types)
        else:
            inner = CyWriter()
            cy_ser_body(inner, body, val, types)
            data = inner.to_bytes()
            w.write(len(data), 32)
            for byte in data:
                w.write(byte, 8)
    else:
        w.align(cy_align(typ.elem, types))
        if typ.mode == "dynamic":
            w.write(len(val), cy_prefix_bits(typ, types))
        for v in val:
            cy_ser_value(w, typ.elem, v, types)


def cy_ser_body(w, body, val, types):
    if body.union:
        tag, inner = val
        w.write(tag, cy_tag_bits(body, types))
        cy_ser_value(w, body.fields[tag].typ, inner, types)
    else:
        for f in body.fields:
            if f.name is None:
                w.write(0, f.typ.bits)
            else:
                cy_ser_value(w, f.typ, val[f.name], types)
    w.align(8)


# ------------------------------------------------------- Cyphal layout ---

def cy_prim_line(typ):
    if typ.kind in ("uint", "bool"):
        return "uint"
    if typ.kind == "int":
        return "twos"
    if typ.bits == 16:
        return None
    return "f32" if typ.bits == 32 else "f64"


class CyLayout:
    """Nodes, as for DroneCAN, plus ("align", 8) and ("block", nodes) for a
    delimited composite."""

    def __init__(self, types, module):
        self.types, self.module = types, module
        self.unmapped = []

    def key(self, path):
        return "%s.%s" % (self.module, "_".join(path))

    def body(self, body, path):
        if body.union:
            variants = [(f.name, self.value(f.typ, path + [f.name]) + [("align", 8)]) for f in body.fields]
            return [("union", cy_tag_bits(body, self.types), variants)]
        out = []
        for f in body.fields:
            if f.name is None:
                out.append(("pad", f.typ.bits, "void"))
            else:
                out += self.value(f.typ, path + [f.name])
        return out + [("align", 8)]

    def value(self, typ, path):
        types = self.types
        if isinstance(typ, Void):
            return [("pad", typ.bits, "void")]
        if isinstance(typ, Prim):
            tr = cy_prim_line(typ)
            if tr is None:
                why = "float16: no half-precision transform"
                self.unmapped.append(("_".join(path), repr(typ), why))
                return [("pad", 16, why)]
            return [("field", self.key(path), typ.bits, tr, False, tuple(path))]
        if isinstance(typ, Ref):
            inner = self.body(types[typ.full].bodies[0], path)
            if types[typ.full].bodies[0].sealed:
                return [("align", 8)] + inner
            return [("align", 8), ("block", inner)]
        align = [("align", 8)] if cy_align(typ.elem, types) == 8 else []
        if typ.mode == "static":
            if typ.n > MAX_STATIC_UNROLL:
                why = "static array of %d elements (more than %d)" % (typ.n, MAX_STATIC_UNROLL)
                self.unmapped.append(("_".join(path), "%s[%d]" % (type_text(typ.elem), typ.n), why))
                if cy_fixed(typ, types):
                    return align + [("pad", cy_fixed(typ, types), why)]
                return [("stop", why)]
            out = list(align)
            for i in range(typ.n):
                out += self.value(typ.elem, path + [str(i)])
            return out
        inner = CyLayout(types, self.module)
        nodes = inner.value(typ.elem, path + ["item"])
        self.unmapped += inner.unmapped
        return align + [("group", self.key(path), cy_prefix_bits(typ, types), nodes, typ)]


def cy_fixed(typ, types):
    """The bit length of a value of fixed length, or None."""
    if isinstance(typ, (Prim, Void)):
        return typ.bits
    if isinstance(typ, Arr):
        e = cy_fixed(typ.elem, types)
        return e * typ.n if typ.mode == "static" and e is not None and cy_align(typ.elem, types) == 1 else None
    return None


def cy_flat(nodes, scope):
    """Flatten nodes of one scope. `scope` is "top", "item" or "block". In a
    block (a delimited composite) a union or a stop ends what the block maps;
    decode skips the rest of the block by its length."""
    out = []
    for n in nodes:
        if n[0] in ("field", "pad", "align"):
            out.append(n)
        elif n[0] in ("stop", "union"):
            why = n[1] if n[0] == "stop" else (
                "a union inside a delimited type" if scope == "block" else "a second union in one scope")
            if scope in ("top", "block"):
                out.append(("stop", why))
                return out, True
            raise Unsupported(why)
        elif n[0] == "block":
            inner, _ = cy_flat(n[1], "block")
            out.append(("block", inner))
        elif n[0] == "group":
            try:
                c, k = cy_resolve(n[3], "item")
            except Unsupported as e:
                why = "array %s: %s" % (n[1], e)
                if scope in ("top", "block"):
                    out.append(("stop", why))
                    return out, True
                raise
            out.append(("group", n[1], n[2], c, k, n[4]))
    return out, False


def cy_resolve(nodes, scope):
    """(common lines, kinds) of a message or group-item scope: the first union
    of the scope becomes one kind per variant, the rest of the scope repeated in
    each."""
    common = []
    for i, n in enumerate(nodes):
        if n[0] == "union":
            kinds = []
            for v, (vname, vnodes) in enumerate(n[2]):
                lines, _ = cy_flat(vnodes + nodes[i + 1:], scope)
                kinds.append((vname, n[1], v, lines))
            return common, kinds
        lines, stopped = cy_flat([n], scope)
        common += lines
        if stopped:
            return common, []
    return common, []


def cy_emit_lines(lines, ind, out, keys, lists):
    for ln in lines:
        if ln[0] == "field":
            _, key, bits, tr, _, _ = ln
            out.append("%sfield  %s  %d  %s" % (ind, key, bits, tr))
            if "." in key:
                keys[key] = "float" if tr.startswith(("f", "sscale")) else "int"
        elif ln[0] == "pad":
            out.append("%spad    %d" % (ind, ln[1]))
        elif ln[0] == "align":
            if not (out and out[-1] == "%salign  %d" % (ind, ln[1])):   # one line for two in a row
                out.append("%salign  %d" % (ind, ln[1]))
        elif ln[0] == "stop":
            out.append("%s# not mapped from here on: %s" % (ind, ln[1]))
        elif ln[0] == "block":
            out.append("%slength 32 bytes" % ind)
            cy_emit_lines(ln[1], ind + "  ", out, keys, lists)
            out.append("%send" % ind)
        elif ln[0] == "group":
            _, lst, pbits, common, kinds, _t = ln
            lists[lst] = True
            out.append("%sgroup  %s  count %d" % (ind, lst, pbits))
            cy_emit_scope(common, kinds, ind + "  ", out, keys, lists)
            out.append("%send" % ind)


def cy_emit_scope(common, kinds, ind, out, keys, lists):
    cy_emit_lines(common, ind, out, keys, lists)
    order = sorted(kinds, key=lambda k: (not cy_req_keys(k[3]), k[2]))
    for name, tbits, tval, lines in order:
        out.append("%skind   %s" % (ind, name))
        out.append("%swhen   %d  %d" % (ind, tbits, tval))
        rk = cy_req_keys(lines)
        if rk:
            out.append("%srequires %s" % (ind, " ".join(rk[:4])))
        cy_emit_lines(lines, ind, out, keys, lists)


def cy_req_keys(lines):
    out = []
    for ln in lines:
        if ln[0] == "field":
            out.append(ln[1])
        elif ln[0] == "block":
            out += cy_req_keys(ln[1])
    return out


def cy_iter(lines):
    for ln in lines:
        if ln[0] == "field":
            yield ln
        elif ln[0] == "block":
            yield from cy_iter(ln[1])
        elif ln[0] == "group":
            yield from cy_iter(ln[3])
            for k in ln[4]:
                yield from cy_iter(k[3])


def cy_stops(lines):
    out = []
    for ln in lines:
        if ln[0] == "stop":
            out.append(ln[1])
        elif ln[0] == "block":
            out += cy_stops(ln[1])
        elif ln[0] == "group":
            out += cy_stops(ln[3])
            for k in ln[4]:
                out += cy_stops(k[3])
    return out


class CyPack:
    def __init__(self, t, bi, types):
        self.t, self.bi, self.types = t, bi, types
        self.body = t.bodies[bi]
        self.role = None if not t.service else ("request" if bi == 0 else "response")
        base = ("%s-%d-%d" % (t.name, t.major, t.minor)).lower().replace("_", "-").replace(".", "-")
        self.format = "cyphal-" + base + ("-" + self.role if self.role else "")
        self.module = "cy" + re.sub(r"[^a-z0-9]", "", t.ns.lower())
        self.prefix = ["%s_%d_%d" % (snake(t.short), t.major, t.minor)] + ([self.role] if self.role else [])
        lay = CyLayout(types, self.module)
        nodes = lay.body(self.body, self.prefix)
        self.common, self.kinds = cy_resolve(nodes, "top")
        self.unmapped = lay.unmapped
        lines, self.keys, self.lists = [], collections.OrderedDict(), collections.OrderedDict()
        cy_emit_scope(self.common, self.kinds, "", lines, self.keys, self.lists)
        self.lines_text = lines
        self.stops = cy_stops(self.common) + [s for k in self.kinds for s in cy_stops(k[3])]
        self.nfields = sum(1 for _ in cy_iter(self.common + [l for k in self.kinds for l in k[3]]))


def cy_pack_text(ps, sha):
    t = ps.t
    port = ("fixed port-ID %d" % t.port) if t.port is not None else "no fixed port-ID"
    o = ["# Cyphal (UAVCAN v1) data type %s%s, %s." % (t.full, " (%s)" % ps.role if ps.role else "", port),
         "# Generated by tools/gen/dsdl2pack.py --cyphal; do not edit by hand.",
         "# The message is the transfer payload. The subject-ID or service-ID travels",
         "# in the transport frame, so the caller names this format.",
         "format        %s" % ps.format,
         "version       %s" % VERSION,
         "distribution  public",
         'source        "%s %s at commit %s"' % (CY_REPO, t.path, sha),
         'source        "Cyphal specification, data structure description language, %s"' % CY_SPEC,
         "uses          %s" % ps.module,
         "wire          bits",
         "layout        sequential",
         "bit_order     lsb"]
    return "\n".join(o + with_required(ps.format, ps.lines_text)) + "\n"


def cy_module_text(ns, packs, sha):
    mod = packs[0].module
    o = ["# The %s module: fields of the Cyphal data types in namespace %s." % (mod, ns),
         "# Generated by tools/gen/dsdl2pack.py --cyphal; do not edit by hand.",
         "# Raw values in the units the definition states; a key is",
         "# <type>_<major>_<minor>_<field path>.",
         "module        %s" % mod,
         "version       %s" % VERSION,
         "distribution  public"]
    for p in sorted({p.t.path for p in packs}):
        o.append('source        "%s %s at commit %s"' % (CY_REPO, p, sha))
    seen = set()
    for p in packs:
        plen = len("_".join(p.prefix)) + 1
        for k, typ in p.keys.items():
            name = k.split(".", 1)[1]
            if name in seen:
                raise GenError("key %s twice in module %s" % (name, mod))
            seen.add(name)
            o.append('key   %s  %s  -  "field %s%s of %s"' % (
                name, typ, name[plen:], " (%s)" % p.role if p.role else "", p.t.full))
        for l in p.lists:
            name = l.split(".", 1)[1]
            if name in seen:
                raise GenError("list %s twice in module %s" % (name, mod))
            seen.add(name)
            o.append('list  %s  "the items of variable-length array %s of %s"' % (name, name[plen:], p.t.full))
    return "\n".join(o) + "\n"


# --------------------------------------------- Cyphal reader and engine ---

def cy_read_pack(text):
    head, uses = {}, []
    root = {"lines": [], "kinds": []}
    stack = [("scope", root, root["lines"])]

    def cur():
        return stack[-1][2]

    for ln, raw in enumerate(text.splitlines(), 1):
        t = tokens(raw)
        if not t:
            continue
        d, a = t[0], t[1:]
        if d in ("format", "version", "distribution", "wire", "layout", "bit_order"):
            head[d] = a[0]
        elif d == "source":
            head["sources"] = head.get("sources", 0) + 1
        elif d == "uses":
            uses.append(a[0])
        elif d == "field":
            cur().append(("field", a[0], int(a[1]), a[2]))
        elif d == "pad":
            cur().append(("pad", int(a[0])))
        elif d == "align":
            cur().append(("align", int(a[0])))
        elif d == "length":
            if a != ["32", "bytes"]:
                raise GenError("line %d: length form %s" % (ln, a))
            blk = {"lines": []}
            cur().append(("block", blk))
            stack.append(("block", blk, blk["lines"]))
        elif d == "group":
            if a[1] != "count":
                raise GenError("line %d: group form %s" % (ln, a[1]))
            g = {"list": a[0], "count": int(a[2]), "lines": [], "kinds": []}
            cur().append(("group", g))
            stack.append(("scope", g, g["lines"]))
        elif d == "end":
            stack.pop()
        elif d == "kind":
            scope = next(s[1] for s in reversed(stack) if s[0] == "scope")
            k = {"name": a[0], "when": [], "requires": [], "lines": []}
            scope["kinds"].append(k)
            stack[-1] = (stack[-1][0], stack[-1][1], k["lines"])
        elif d == "when":
            scope = next(s[1] for s in reversed(stack) if s[0] == "scope")
            scope["kinds"][-1]["when"].append((int(a[0]), int(a[1])))
        elif d == "requires":
            scope = next(s[1] for s in reversed(stack) if s[0] == "scope")
            scope["kinds"][-1]["requires"] += a
        else:
            raise GenError("line %d: directive %s" % (ln, d))
    if len(stack) != 1:
        raise GenError("unbalanced block")
    for need in ("format", "version", "distribution", "wire", "layout", "bit_order"):
        if need not in head:
            raise GenError("pack lacks " + need)
    if head["bit_order"] != "lsb" or head["layout"] != "sequential":
        raise GenError("a Cyphal pack is sequential, bit_order lsb")
    return head, uses, root


class CyReader:
    """Reads bits least significant first, within an extent (engine-spec 0.8,
    Lengths: a line that starts at or after the end of the extent is absent)."""

    def __init__(self, data):
        self.data, self.pos, self.end = data, 0, 8 * len(data)

    def read(self, n):
        if self.pos + n > self.end:
            raise GenError("malformed-wire")
        v = 0
        for i in range(n):
            p = self.pos + i
            v |= ((self.data[p // 8] >> (p % 8)) & 1) << i
        self.pos += n
        return v


def cy_from_raw(tr, n, v):
    if tr == "uint":
        return v - (1 << 64) if n == 64 and v >> 63 else v
    if tr == "twos":
        return v - (1 << n) if v >> (n - 1) else v
    if tr == "f32":
        return struct.unpack("<f", v.to_bytes(4, "little"))[0]
    if tr == "f64":
        return struct.unpack("<d", v.to_bytes(8, "little"))[0]
    raise GenError("transform " + tr)


def cy_to_raw(tr, n, x):
    if tr in ("uint", "twos"):
        return x & ((1 << n) - 1)
    if tr == "f32":
        return int.from_bytes(struct.pack("<f", x), "little")
    return int.from_bytes(struct.pack("<d", x), "little")


def cy_dec_scope(r, scope, ent):
    cy_dec_lines(r, scope["lines"], ent)
    if scope["kinds"]:
        start = r.pos
        for k in scope["kinds"]:
            r.pos = start
            if all(r.pos + n <= r.end and r.read(n) == v for n, v in k["when"]):
                ent["@kind"] = k["name"]
                cy_dec_lines(r, k["lines"], ent)
                return
        raise GenError("no-kind")


def cy_dec_lines(r, lines, ent):
    for ln in lines:
        if ln[0] == "field":
            _, key, n, tr = ln
            if r.pos >= r.end and r.end < 8 * len(r.data):
                continue                    # past the extent of a block: absent
            ent[key] = cy_from_raw(tr, n, r.read(n))
        elif ln[0] == "pad":
            if r.pos >= r.end and r.end < 8 * len(r.data):
                continue
            r.read(ln[1])
        elif ln[0] == "align":
            r.pos = min(r.pos + (-r.pos % ln[1]), max(r.end, r.pos))
        elif ln[0] == "block":
            size = r.read(32)
            outer_end, start = r.end, r.pos
            if start + 8 * size > outer_end:
                raise GenError("malformed-wire")
            r.end = start + 8 * size
            cy_dec_lines(r, ln[1]["lines"], ent)
            r.pos, r.end = start + 8 * size, outer_end
        else:
            g = ln[1]
            cnt = r.read(g["count"])
            items = []
            for _ in range(cnt):
                it = {}
                cy_dec_scope(r, g, it)
                items.append(it)
            ent[g["list"]] = items


def cy_enc_scope(w, scope, ent):
    cy_enc_lines(w, scope["lines"], ent)
    if scope["kinds"]:
        k = None
        if "@kind" in ent:
            k = next(x for x in scope["kinds"] if x["name"] == ent["@kind"])
        else:
            k = next((x for x in scope["kinds"] if all(rk in ent for rk in x["requires"])), None)
        if k is None:
            raise GenError("no-kind")
        for n, v in k["when"]:
            w.write(v, n)
        cy_enc_lines(w, k["lines"], ent)


def cy_enc_lines(w, lines, ent):
    for ln in lines:
        if ln[0] == "field":
            _, key, n, tr = ln
            w.write(cy_to_raw(tr, n, ent[key]) if key in ent else 0, n)
        elif ln[0] == "pad":
            w.write(0, ln[1])
        elif ln[0] == "align":
            w.align(ln[1])
        elif ln[0] == "block":
            inner = CyWriter()
            inner.bits = [0] * len(w.bits)        # so `align` counts from the message start
            cy_enc_lines(inner, ln[1]["lines"], ent)
            body = inner.bits[len(w.bits):]
            body += [0] * (-len(body) % 8)
            w.write(len(body) // 8, 32)
            w.bits += body
        else:
            g = ln[1]
            items = ent.get(g["list"], [])
            w.write(len(items), g["count"])
            for it in items:
                cy_enc_scope(w, g, it)


# ------------------------------------------------- Cyphal sample values ---

def cy_sample(typ, types, salt):
    if isinstance(typ, Void):
        return None
    if isinstance(typ, Prim):
        if typ.kind == "float":
            return 0.0 if typ.bits == 16 else ((salt % 41) - 20) * 0.25
        if typ.kind == "bool":
            return salt % 2
        if typ.kind == "uint":
            v = (salt * 2654435761 + 12345) % (1 << min(typ.bits, 31))
            if typ.bits == 64 and salt % 2:
                v |= 1 << 63
            return v
        span = 1 << min(typ.bits, 31)
        return (salt * 40503 + 7) % span - span // 2
    if isinstance(typ, Ref):
        return cy_sample_body(types[typ.full].bodies[0], types, salt, None)
    if typ.mode == "static":
        if typ.n > MAX_STATIC_UNROLL:
            return [cy_zero(typ.elem, types) for _ in range(typ.n)]
        return [cy_sample(typ.elem, types, salt + 3 * i + 1) for i in range(typ.n)]
    count = min(typ.n, 1 + salt % 3)
    return [cy_sample(typ.elem, types, salt + 5 * i + 2) for i in range(count)]


def cy_zero(typ, types):
    if isinstance(typ, Void):
        return None
    if isinstance(typ, Prim):
        return 0.0 if typ.kind == "float" else 0
    if isinstance(typ, Ref):
        b = types[typ.full].bodies[0]
        if b.union:
            return (0, cy_zero(b.fields[0].typ, types))
        return {f.name: cy_zero(f.typ, types) for f in b.fields if f.name}
    if typ.mode == "static":
        return [cy_zero(typ.elem, types) for _ in range(typ.n)]
    return []


def cy_sample_body(body, types, salt, variant):
    if body.union:
        v = variant if variant is not None else salt % len(body.fields)
        return (v, cy_sample(body.fields[v].typ, types, salt + 11))
    return {f.name: cy_sample(f.typ, types, salt + 7 * i + 1) for i, f in enumerate(body.fields) if f.name}


def cy_force_variant(val, body, types, v):
    """Set the first union of the message scope (fields in order, through sealed
    composites and static arrays, not into arrays of variable length or
    delimited composites) to variant v."""
    done = [False]

    def walk_body(b, x):
        if b.union:
            if not done[0]:
                done[0] = True
                return (v, cy_sample(b.fields[v].typ, types, 13 + v))
            return x
        for f in b.fields:
            if f.name and not done[0]:
                x[f.name] = walk_val(f.typ, x[f.name])
        return x

    def walk_val(typ, x):
        if isinstance(typ, Ref) and types[typ.full].bodies[0].sealed:
            return walk_body(types[typ.full].bodies[0], x)
        if isinstance(typ, Arr) and typ.mode == "static" and typ.n <= MAX_STATIC_UNROLL:
            return [walk_val(typ.elem, e) for e in x]
        return x
    return walk_body(body, val)


def cy_values(ps):
    types = ps.types
    salt = (ps.t.port or 0) * 31 + ps.t.major * 7 + ps.t.minor + (17 if ps.role == "response" else 3)
    if ps.kinds and ps.body.union:
        return [cy_sample_body(ps.body, types, salt + i, i) for i in range(len(ps.body.fields))]
    if ps.kinds:
        return [cy_force_variant(cy_sample_body(ps.body, types, salt + i, None), ps.body, types, i)
                for i in range(len(ps.kinds))]
    return [cy_sample_body(ps.body, types, salt, None)]


# ------------------------------------- Cyphal: what the pack writes back ---
# The expected output is the serialization of the value with the rules above,
# where the pack stops: in a message, everything after a point it cannot
# state; in a delimited composite, the rest of that composite (its length then
# counts the bytes written). This walk follows the serialization rules and the
# layout decisions, not the pack text.

class _CyStop(Exception):
    pass


def cy_supported_item(typ, types, module):
    try:
        cy_resolve(CyLayout(types, module).value(typ, ["x"]), "item")
        return True
    except Unsupported:
        return False


def cy_mapped_bytes(ps, val):
    types = ps.types
    w = CyWriter()
    state = {"unions": 0}

    def body(b, v, scope, w):
        if b.union:
            if scope == "block" or (scope == "top" and state["unions"] >= 1):
                raise _CyStop()
            if scope == "top":
                state["unions"] += 1
            tag, inner = v
            w.write(tag, cy_tag_bits(b, types))
            value(b.fields[tag].typ, inner, scope, w)
        else:
            for f in b.fields:
                if f.name is None:
                    w.write(0, f.typ.bits)
                else:
                    value(f.typ, v[f.name], scope, w)
        w.align(8)

    def value(typ, v, scope, w):
        if isinstance(typ, Ref):
            b = types[typ.full].bodies[0]
            w.align(8)
            if b.sealed:
                body(b, v, scope, w)
                return
            inner = CyWriter()
            inner.bits = [0] * len(w.bits)
            try:
                body(b, v, "block", inner)
            except _CyStop:
                pass
            content = inner.bits[len(w.bits):]
            content += [0] * (-len(content) % 8)
            w.write(len(content) // 8, 32)
            w.bits += content
            return
        if isinstance(typ, Arr):
            if typ.mode == "static" and typ.n > MAX_STATIC_UNROLL and not cy_fixed(typ, types):
                raise _CyStop()
            if typ.mode == "dynamic" and not cy_supported_item(typ.elem, types, ps.module):
                raise _CyStop()
            w.align(cy_align(typ.elem, types))
            if typ.mode == "dynamic":
                w.write(len(v), cy_prefix_bits(typ, types))
                for x in v:
                    cy_ser_value(w, typ.elem, x, types)
            else:
                for x in v:
                    value(typ.elem, x, scope, w)
            return
        cy_ser_value(w, typ, v, types)

    try:
        body(ps.body, val, "top", w)
    except _CyStop:
        pass
    return w.to_bytes()


def cy_model_of(ps, val):
    """The entity the pack decodes from the value, from the DSDL value and the
    key-naming rule; then cut to the keys and lists the pack maps."""
    types = ps.types
    ent = collections.OrderedDict()

    def body(b, v, path, out):
        if b.union:
            tag, inner = v
            if "@kind" not in out:
                out["@kind"] = b.fields[tag].name
            value(b.fields[tag].typ, inner, path + [b.fields[tag].name], out)
            return
        for f in b.fields:
            if f.name:
                value(f.typ, v[f.name], path + [f.name], out)

    def value(typ, v, path, out):
        key = "%s.%s" % (ps.module, "_".join(path))
        if isinstance(typ, Prim):
            if cy_prim_line(typ) is not None:
                if typ.kind in ("uint", "bool") and typ.bits == 64 and v >> 63:
                    v -= 1 << 64
                out[key] = v
        elif isinstance(typ, Ref):
            body(types[typ.full].bodies[0], v, path, out)
        elif typ.mode == "static":
            if typ.n <= MAX_STATIC_UNROLL:
                for i, x in enumerate(v):
                    value(typ.elem, x, path + [str(i)], out)
        else:
            items = []
            for x in v:
                it = collections.OrderedDict()
                value(typ.elem, x, path + ["item"], it)
                items.append(it)
            out[key] = items

    body(ps.body, val, ps.prefix, ent)
    return cy_prune(ent, ps)


def cy_prune(ent, ps):
    names = set(ps.keys) | set(ps.lists)
    out = collections.OrderedDict()
    for k, v in ent.items():
        if k == "@kind" or k in names:
            out[k] = [cy_prune(i, ps) for i in v] if isinstance(v, list) else v
    return out


def cy_vector_files(ps):
    files = []
    for i, val in enumerate(cy_values(ps)):
        w = CyWriter()
        cy_ser_body(w, ps.body, val, ps.types)
        ent = cy_model_of(ps, val)
        kind = ent.get("@kind")
        vec = collections.OrderedDict([
            ("name", "%s-roundtrip%s" % (ps.format, "-" + kind if kind else "")),
            ("from", ps.format), ("to", ps.format),
            ("input", w.to_bytes().hex()), ("expect", cy_mapped_bytes(ps, val).hex()),
            ("model", model_strings(ent))])
        files.append(("rt-%02d%s.json" % (i, "-" + kind if kind else ""), vector_text(vec)))
    return files


# ------------------------------------------------ Cyphal documents, run ---

def cy_pack_md(ps, sha, nvec):
    t = ps.t
    o = []
    a = o.append
    a("# Pack: %s" % ps.format)
    a("")
    a("Cyphal (UAVCAN v1) data type `%s`%s, as the payload of a transfer. Public." % (
        t.full, " (the %s of the service)" % ps.role if ps.role else ""))
    a("Generated by `tools/gen/dsdl2pack.py --cyphal` from `%s` (`%s`) at commit" % (CY_REPO, t.path))
    a("`%s`; do not edit `pack.def`, this file, `PROVENANCE.md` or the vectors by" % sha)
    a("hand. Module: `model/%s.def`." % ps.module)
    if t.deprecated:
        a("")
        a("The definition marks the type deprecated.")
    a("")
    a("Status: Built. Generated and checked by the generator's own codec and reader.")
    a("")
    a("## The message")
    a("")
    a("`wire bits`, `layout sequential`, `bit_order lsb`. The input is the transfer")
    a("payload: the bytes the transport delivers for one transfer, without transport")
    a("headers, tail bytes or transfer CRC. Hex text.")
    if ps.format in REQUIRE_ALL:
        a("")
        a("On encode from another format the one kind requires the top-level fields; an")
        a("entity without them is `no-kind`, not a payload of zeros. `Entity.kind` is now")
        a("recorded (`message`); same-format bytes do not change.")
    a("")
    if t.port is not None:
        a("**Port-ID.** The type has the fixed %s-ID %d. The port-ID travels in the" % (
            "service" if t.service else "subject", t.port))
    else:
        a("**Port-ID.** The type has no fixed port-ID; the subject-ID or service-ID is")
        a("configured on each node. The port-ID travels in the")
    a("transport frame (the CAN identifier, the UDP header), not in the payload, and the")
    a("payload has no field that tells types apart. So each data type is its own")
    a("format, and the caller names the format.")
    a("")
    a("**Extensibility.** The type is %s." % (
        "sealed: its layout never grows" if ps.body.sealed else
        "delimited (`@extent %s` bits): a later minor version may append fields" % (
            getattr(ps.body, "extent_bits", "?"))))
    a("")
    a("## What is mapped")
    a("")
    a("| DSDL | Pack line | Model type |")
    a("|---|---|---|")
    a("| `uintN`, `bool` | `field … N uint` | int |")
    a("| `intN` | `field … N twos` | int |")
    a("| `float32`, `float64` | `f32` / `f64` | float |")
    a("| `voidN` | `pad N` | - |")
    a("| a composite field | `align 8`, its fields, `align 8` | - |")
    a("| a composite field of a type that is not `@sealed` | `align 8`, then `length 32 bytes` … `end` | - |")
    a("| `T[N]`, N up to %d | one line per element | as the element |" % MAX_STATIC_UNROLL)
    a("| `T[<=N]`, `T[<N]` | `group … count <8, 16, 32 or 64>` | list |")
    a("| `@union` at the top of the type, or one union in it | one `kind` per variant, `when <tag bits> <variant>` | - |")
    a("")
    a("Bits are filled least significant first, so a value of any width at any bit")
    a("position is one `field` line. The keys are `%s.%s_<field path>`, the" % (ps.module, "_".join(ps.prefix)))
    a("path joined by `_`, an element of a static array numbered from 0.")
    a("")
    a("| | Count |")
    a("|---|---|")
    a("| `field` lines | %d |" % ps.nfields)
    a("| model keys | %d |" % len(ps.keys))
    a("| lists (variable-length arrays) | %d |" % len(ps.lists))
    a("| kinds | %d |" % len(ps.kinds))
    a("| fields not mapped | %d |" % len(ps.unmapped))
    a("| vectors | %d |" % nvec)
    if ps.kinds:
        a("")
        a("Kinds: %s. The union's tag is the `when` of each kind; the lines after the" % ", ".join(
            "`%s` (tag %d)" % (k[0], k[2]) for k in ps.kinds))
        a("union are repeated in every kind. Encode chooses a kind by its `requires`;")
        a("a variant with no key is tried last.")
    a("")
    a("No key of this pack is bound to a `core` or `track` key. The Cyphal positions")
    a("(`reg.udral.physics.kinematics.geodetic`) are in radians as float64, and the")
    a("pack language has no scaling transform for a float.")
    a("")
    a("## What is not mapped")
    a("")
    if ps.unmapped:
        a("| Field | Type | Reason |")
        a("|---|---|---|")
        for p, ty, why in ps.unmapped:
            a("| `%s` | `%s` | %s |" % (p, ty, why))
        a("")
        a("A field of fixed length that is not mapped is a `pad` line: decode skips it,")
        a("encode writes zero bits.")
    else:
        a("Every field is mapped.")
    if ps.stops:
        a("")
        a("Mapping ends early: %s. In a delimited composite the rest of that composite" % "; ".join(
            sorted(set(ps.stops))))
        a("is skipped by its length; anywhere else decode ignores the rest of the payload.")
    for line in keyless_note(ps):
        a(line)
    a("")
    a("- Implicit zero extension: Cyphal reads a field beyond the end of a short")
    a("  payload, or of a delimited composite, as zero. The pack reads the first as")
    a("  `malformed-wire` and the second as absent.")
    a("- Constants and `@assert` lines (not on the wire). Cast modes: encode writes")
    a("  the low bits of a value.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-NN*.json`: a same-format round trip%s. The input is the payload a" % (
        " per kind" if ps.kinds else ""))
    a("Cyphal serializer written in the generator produces from sample values; fields")
    a("the pack does not map are zero. The expected output is what the pack writes")
    a("back: the same bytes, cut where the mapping ends. The generator decodes and")
    a("re-encodes every vector with its own reader of the pack.")
    return "\n".join(o) + "\n"


def cy_provenance_md(ps, sha, file_sha, license_sha):
    t = ps.t
    return "\n".join([
        "# Provenance: %s" % ps.format,
        "",
        "| Fact | Value |",
        "|---|---|",
        "| data type | `%s`%s, %s |" % (t.full, " (%s)" % ps.role if ps.role else "",
                                       "fixed port-ID %d" % t.port if t.port is not None else "no fixed port-ID"),
        "| definition read | `%s` of %s |" % (t.path, CY_REPO),
        "| commit | `%s` |" % sha,
        "| SHA-256 of the definition | `%s` |" % file_sha,
        "| license of the repository | MIT, copyright (c) 2014-2019 UAVCAN Development Team: `LICENSE` at the root of the commit (SHA-256 `%s`), verbatim in `tools/gen/sources/%s`; the definition file carries no license or copyright header of its own |" % (license_sha, CY_PROV_NAME),
        "| date read | 2026-11-19 |",
        "| what the pack takes | type and field names, field types, array bounds, constants that bound arrays, the `@union`, `@sealed` and `@extent` directives and the fixed port-ID; no comment text |",
        "| generator | `tools/gen/dsdl2pack.py --cyphal` |",
        ""])


def cy_write_sources_provenance(out, rel, root, sha, files):
    lic = read_text(os.path.join(root, "LICENSE"))
    o = ["# Provenance of the Cyphal DSDL inputs",
         "",
         "| Fact | Value |",
         "|---|---|",
         "| repository | %s |" % CY_REPO,
         "| commit | `%s` (head of `master`, read 2026-11-19) |" % sha,
         "| archive | `https://codeload.github.com/OpenCyphal/public_regulated_data_types/tar.gz/%s` |" % sha,
         "| license | MIT, the file `LICENSE` at the root of the commit, verbatim below |",
         "",
         "## Files",
         "",
         "| Path | SHA-256 |",
         "|---|---|",
         "| `LICENSE` | `%s` |" % sha256(os.path.join(root, "LICENSE"))]
    for f in files:
        o.append("| `%s` | `%s` |" % (f, sha256(os.path.join(root, f))))
    o += ["", "## LICENSE", "", "```"] + lic.rstrip("\n").splitlines() + ["```", ""]
    out.write(rel, "\n".join(o))


def cy_check_keys(scope, module, mods):
    def walk(lines):
        for ln in lines:
            if ln[0] == "field":
                m, k = ln[1].split(".", 1) if "." in ln[1] else ("core", ln[1])
                if m not in (module, "core") or k not in mods[m]["keys"]:
                    raise GenError("undeclared-key " + ln[1])
                if mods[m]["keys"][k] != ("float" if ln[3].startswith("f") else "int"):
                    raise GenError("key-type-mismatch " + ln[1])
            elif ln[0] == "block":
                walk(ln[1]["lines"])
            elif ln[0] == "group":
                if ln[1]["list"].split(".", 1)[1] not in mods[module]["lists"]:
                    raise GenError("undeclared list " + ln[1]["list"])
                scope_walk(ln[1])

    def scope_walk(sc):
        walk(sc["lines"])
        names = [k["name"] for k in sc["kinds"]]
        if len(set(names)) != len(names):
            raise GenError("duplicate-kind")
        for k in sc["kinds"]:
            walk(k["lines"])
            for rk in k["requires"]:
                if rk.split(".", 1)[1] not in mods[module]["keys"]:
                    raise GenError("requires undeclared " + rk)
    scope_walk(scope)


def run_cyphal(args, out):
    root = args.dsdl
    namespaces = args.namespaces.split(",") if args.namespaces else CY_NAMESPACES
    types = cy_load(root, namespaces)
    files = sorted(t.path for t in types.values())
    prov = "tools/gen/sources/" + CY_PROV_NAME
    if args.commit:
        cy_write_sources_provenance(out, prov, root, args.commit, files)
    sha, table = read_sources_provenance(prov, root, files, out.read(prov))

    seen = {}
    for t in types.values():
        if t.port is not None:
            # the versions of one type share its port-ID; two types may not
            k = ("service" if t.service else "subject", t.port)
            if k in seen and seen[k].name != t.name:
                raise GenError("fixed port-ID %s used by %s and %s" % (k, seen[k].full, t.full))
            seen[k] = t

    packs, skipped = [], []
    for t in sorted(types.values(), key=lambda x: x.full):
        for bi in range(len(t.bodies)):
            ps = CyPack(t, bi, types)
            if not ps.body.fields:
                skipped.append((ps.format, "the %s has no field" % (ps.role or "type")))
                continue
            if not ps.keys and not ps.lists:
                skipped.append((ps.format, "no field the pack can state: %s" % "; ".join(
                    sorted({w for _, _, w in ps.unmapped} | set(ps.stops)))))
                continue
            packs.append(ps)

    by_ns = collections.OrderedDict()
    for ps in packs:
        by_ns.setdefault(ps.t.ns, []).append(ps)
    for ns, lst in by_ns.items():
        out.write("model/%s.def" % lst[0].module, cy_module_text(ns, lst, sha))
    for ps in packs:
        pdir = "packs/" + ps.format
        out.write(pdir + "/pack.def", cy_pack_text(ps, sha))
        vecs = cy_vector_files(ps)
        write_vectors(out, pdir + "/vectors", vecs)
        out.write(pdir + "/pack.md", cy_pack_md(ps, sha, len(vecs)))
        out.write(pdir + "/PROVENANCE.md", cy_provenance_md(ps, sha, table[ps.t.path], table["LICENSE"]))

    mods = {"core": check_model(core_text(args, out), None)}
    for lst in by_ns.values():
        mods[lst[0].module] = check_model(out.read("model/%s.def" % lst[0].module), None)
    total = 0
    for ps in packs:
        pdir = "packs/" + ps.format
        head, uses, scope = cy_read_pack(out.read(pdir + "/pack.def"))
        if head["format"] != ps.format or uses != [ps.module]:
            raise GenError("%s: header" % ps.format)
        cy_check_keys(scope, ps.module, mods)
        total += check_vectors(scope, read_vectors(out, pdir + "/vectors"), ps.format,
                               CyReader, cy_dec_scope, (CyWriter, cy_enc_scope))

    reasons = collections.Counter(w for p in packs for _, _, w in p.unmapped)
    lines = ["commit          %s" % sha,
             "types           %d (%d with a fixed port-ID)" % (
                 len(types), sum(t.port is not None for t in types.values())),
             "packs           %d in %d modules" % (len(packs), len(by_ns))]
    lines += ["no pack         %s: %s" % (f, why) for f, why in skipped]
    lines += ["field lines     %d" % sum(p.nfields for p in packs),
              "lists           %d" % sum(len(p.lists) for p in packs),
              "kinds           %d" % sum(len(p.kinds) for p in packs),
              "not mapped      %d fields %s" % (sum(reasons.values()), dict(reasons)),
              "ends early      %d packs %s" % (sum(bool(p.stops) for p in packs),
                                               dict(collections.Counter(s for p in packs for s in set(p.stops)))),
              "vectors         %d checked" % total,
              "self-check      ok"]
    return lines


# ------------------------------------------------------------------ main ---

def run_dronecan(args, out):
    """The DroneCAN run; the summary lines."""
    dsdl = args.dsdl
    namespaces = args.namespaces.split(",") if args.namespaces else NAMESPACES
    types = load_dsdl(dsdl, namespaces)
    files = sorted(t.path for t in types.values())
    prov = "tools/gen/sources/" + PROV_NAME
    if args.commit:
        write_sources_provenance(out, prov, dsdl, args.commit, files)
    sha, table = read_sources_provenance(prov, dsdl, files, out.read(prov))

    # data type IDs are unique among messages and among services
    seen = {}
    for t in types.values():
        if t.dtid is None:
            continue
        k = ("service" if t.service else "message", t.dtid)
        if k in seen:
            raise GenError("data type ID %s used by %s and %s" % (k, seen[k], t.full))
        seen[k] = t.full

    packs, skipped = [], []
    for t in sorted(types.values(), key=lambda x: x.full):
        if t.dtid is None:
            continue
        for bi in range(len(t.bodies)):
            ps = PackSpec(t, bi)
            ps.types = types
            if not ps.body.fields:
                skipped.append((ps.format, "the %s has no field" % (ps.role or "message")))
                continue
            build_pack(ps, types)
            if not ps.keys and not ps.lists:
                skipped.append((ps.format, "no field the pack can state: %s" % "; ".join(
                    sorted({w for _, _, w in ps.unmapped} | set(ps.stops)))))
                continue
            packs.append(ps)

    by_ns = collections.OrderedDict()
    for ps in packs:
        by_ns.setdefault(ps.t.ns, []).append(ps)
    for ns, lst in by_ns.items():
        out.write("model/%s.def" % module_name(ns), module_text(ns, lst, sha))

    total_vec = 0
    for ps in packs:
        pdir = "packs/" + ps.format
        out.write(pdir + "/pack.def", pack_text(ps, sha))
        vecs = vector_files(ps, types)
        write_vectors(out, pdir + "/vectors", vecs)
        out.write(pdir + "/pack.md", pack_md(ps, sha, len(vecs)))
        out.write(pdir + "/PROVENANCE.md", provenance_md(ps, sha, table[ps.t.path], table["LICENSE"]))

    # ---- self-check from the files as written
    mods = {"core": check_model(core_text(args, out), None)}
    for ns in by_ns:
        mn = module_name(ns)
        mods[mn] = check_model(out.read("model/%s.def" % mn), None)
    for ps in packs:
        pdir = "packs/" + ps.format
        head, uses, scope = read_pack(out.read(pdir + "/pack.def"))
        if head["format"] != ps.format or uses != [ps.module]:
            raise GenError("%s: header" % ps.format)
        check_pack_keys(scope, ps.module, mods)
        total_vec += check_vectors(scope, read_vectors(out, pdir + "/vectors"), ps.format)

    lines = ["commit          %s" % sha,
             "types           %d (%d with a data type ID)" % (
                 len(types), sum(t.dtid is not None for t in types.values())),
             "packs           %d in %d modules" % (len(packs), len(by_ns))]
    lines += ["no pack         %s: %s" % (f, why) for f, why in skipped]
    reasons = collections.Counter(w for p in packs for _, _, w in p.unmapped)
    lines += ["field lines     %d" % sum(count_lines(p.common, p.kinds) for p in packs),
              "lists           %d" % sum(len(p.lists) for p in packs),
              "kinds           %d" % sum(len(p.kinds) for p in packs),
              "not mapped      %d fields %s" % (sum(reasons.values()), dict(reasons)),
              "ends early      %d packs" % sum(bool(p.stops) for p in packs),
              "vectors         %d checked" % total_vec,
              "self-check      ok"]
    return lines


def core_text(args, out):
    if args.core_def:
        return read_text(args.core_def)
    return out.read("model/core.def")


def read_vectors(out, vdir):
    return [(name, out.read("%s/%s" % (vdir, name))) for name in out.listdir(vdir) if name.endswith(".json")]


def build_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        prog="dsdl2pack",
        description="Generate one pack per data type from DSDL definitions: DroneCAN (UAVCAN v0, "
                    "github.com/dronecan/DSDL) by default, Cyphal (UAVCAN v1, "
                    "github.com/OpenCyphal/public_regulated_data_types) with --cyphal. Reads the DSDL tree "
                    "given by --dsdl and tools/gen/sources/<family>-PROVENANCE.md (the SHA-256 of every file; "
                    "a file that differs is refused). Writes model/<module>.def per namespace and "
                    "packs/<family>-<type>/ (pack.def, pack.md, PROVENANCE.md, vectors/). Every vector is "
                    "decoded and encoded by the generator's own reader of the pack. Exit status: 0 when every "
                    "check passed, 1 for a refused input or a failed check, 2 for a usage error.")
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")),
                        what="the checkout to write into")
    ap.add_argument("--root", dest="out", metavar="DIR", default=argparse.SUPPRESS, help="the same as --out")
    ap.add_argument("--dsdl", required=True, metavar="DIR", help="the root of the DSDL tree")
    ap.add_argument("--cyphal", action="store_true", help="read Cyphal (UAVCAN v1) DSDL")
    ap.add_argument("--namespaces", help="root namespaces to read (default: all the family has)")
    ap.add_argument("--commit", help="write tools/gen/sources/<family>-PROVENANCE.md for this commit")
    ap.add_argument("--core-def", help="model/core.def (default <out>/model/core.def)")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = genio.Output(args.out, check=args.check)
    try:
        lines = run_cyphal(args, out) if args.cyphal else run_dronecan(args, out)
    except GenError as e:
        print("dsdl2pack: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("dsdl2pack: %s: %s" % (e.filename, e.strerror), file=sys.stderr)
        return 1
    print("\n".join(lines))
    return out.report("dsdl2pack")


if __name__ == "__main__":
    sys.exit(main())
