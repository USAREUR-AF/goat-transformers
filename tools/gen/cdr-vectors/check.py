#!/usr/bin/env python3
"""Re-read every vector of spec 0.43 (the `cdr` wire) with a decoder and an
encoder written here from the spec text, independent of the hand layouts of
gen.py, and report every vector whose `expect`, `expect_error` or `model`
this computation does not reproduce.

What it covers:
- conversion vectors under packs/conformance-cdr/vectors/,
  packs/conformance-cdr2/vectors/ and packs/geojson/vectors/cdr-*.json, and
  with --protobuf-source the in-memory vectors gen.py writes for
  packs/conformance-groups-protobuf/vectors/cdr-*.json;
- load vectors packs/conformance/load-vectors/wire-cdr-*.json, against a
  load checker that implements only the rules those vectors exercise
  (ruling 5b of 0.11 ordering, rulings 3, 4, 10, 12, 13 and 14 of 0.43).

The cdr codec reads the pack.def files of the two packs, computes each
alignment from the Types table (cdr 1 and cdr 2 columns), places a DHEADER by
rulings 8 and 9, selects kinds by `when <n>` (ruling 3), and defers every
transform failure until the structural checks of the whole message have run
(ruling 11). Key types come from model/core.def and model/probe.def.
`convert` follows 0.6 "Order inside convert"; no derive line of a loaded
module sets a key the target packs here map, so step 3 changes no output and
is not run (stated, not computed).

Python 3 standard library only; imports no engine.

Usage: python3 -I tools/gen/cdr-vectors/check.py [--out DIR] [--protobuf-source]
Exit status 0 when every vector is reproduced.
"""
import glob
import json
import math
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

MW, TD, TE, NK = "malformed-wire", "transform-decode", "transform-encode", "no-kind"


class Fail(Exception):
    def __init__(self, kind, why=""):
        super().__init__("%s: %s" % (kind, why))
        self.kind = kind


# --------------------------------------------------------------------------
# Line reading shared by packs and modules: `#` starts a comment at a token
# start; a double-quoted value is one token.

def tokens(line):
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t":
            i += 1
            continue
        if c == "#":
            break
        if c == '"':
            j = line.find('"', i + 1)
            if j < 0:
                raise Fail("unterminated-quote", line)
            out.append(line[i + 1:j])
            i = j + 1
            continue
        j = i
        while j < n and line[j] not in " \t":
            j += 1
        out.append(line[i:j])
        i = j
    return out


def read_module(text):
    mod = {"name": None, "keys": {}, "lists": set()}
    for line in text.split("\n"):
        t = tokens(line)
        if not t:
            continue
        if t[0] == "module":
            mod["name"] = t[1]
        elif t[0] == "key":
            mod["keys"][t[1]] = t[2]
        elif t[0] == "list":
            mod["lists"].add(t[1])
    return mod


def model_types(texts):
    """{qualified key: type} and {qualified list}: core keys bare."""
    keys, lists = {}, set()
    for text in texts:
        m = read_module(text)
        q = "" if m["name"] == "core" else m["name"] + "."
        for k, ty in m["keys"].items():
            keys[q + k] = ty
        for l in m["lists"]:
            lists.add(q + l)
    return keys, lists


# --------------------------------------------------------------------------
# The cdr pack.

TYPES = {
    # name: (size, align cdr1, align cdr2, struct code, kind)
    "int8": (1, 1, 1, "b", "int"), "uint8": (1, 1, 1, "B", "int"), "char8": (1, 1, 1, "B", "int"),
    "octet": (1, 1, 1, "B", "int"), "bool": (1, 1, 1, "B", "bool"),
    "int16": (2, 2, 2, "h", "int"), "uint16": (2, 2, 2, "H", "int"),
    "int32": (4, 4, 4, "i", "int"), "uint32": (4, 4, 4, "I", "int"),
    "int64": (8, 8, 4, "q", "int"), "uint64": (8, 8, 4, "Q", "int"),
    "float32": (4, 4, 4, "f", "float"), "float64": (8, 8, 4, "d", "float"),
    "enum8": (1, 1, 1, "b", "int"), "enum16": (2, 2, 2, "h", "int"), "enum32": (4, 4, 4, "i", "int"),
    "string": (None, 4, 4, None, "string"),
}
DEFAULT_TRANSFORM = {"int": "int", "bool": "bool", "float": "float", "string": "string"}
RANGES = {
    "int8": (-128, 127), "uint8": (0, 255), "char8": (0, 255), "octet": (0, 255), "bool": (0, 1),
    "int16": (-2**15, 2**15 - 1), "uint16": (0, 2**16 - 1), "int32": (-2**31, 2**31 - 1),
    "uint32": (0, 2**32 - 1), "int64": (-2**63, 2**63 - 1), "uint64": (0, 2**63 - 1),
    "enum8": (-128, 127), "enum16": (-2**15, 2**15 - 1), "enum32": (-2**31, 2**31 - 1),
}


def parse_cdr_pack(text):
    pk = {"format": None, "cdr": None, "rep": None, "common": [], "kinds": [], "defaults": {}}
    stack = [pk["common"]]
    scope_kind = None
    for line in text.split("\n"):
        t = tokens(line)
        if not t:
            continue
        d = t[0]
        if d == "format":
            pk["format"] = t[1]
        elif d == "cdr":
            pk["cdr"] = int(t[1])
        elif d == "representation":
            pk["rep"] = bytes.fromhex(t[1])
        elif d == "field":
            tr = t[3] if len(t) > 3 else None
            stack[-1].append({"line": "field", "key": t[1], "type": t[2], "transform": tr})
        elif d == "const":
            stack[-1].append({"line": "const", "type": t[1], "value": int(t[2])})
        elif d == "group":
            mode = t[2]
            g = {"line": "group", "list": t[1], "seq": mode == "seq",
                 "n": None if mode == "seq" else int(mode.split(":")[1]), "body": []}
            stack[-1].append(g)
            stack.append(g["body"])
        elif d == "end":
            stack.pop()
        elif d == "kind":
            scope_kind = {"name": t[1], "when": [], "lines": [], "requires": []}
            pk["kinds"].append(scope_kind)
            stack = [scope_kind["lines"]]
        elif d == "when":
            scope_kind["when"].append((int(t[1]), int(t[2])))
        elif d == "default" and scope_kind is None and len(stack) == 1:
            pk["defaults"][t[1]] = t[2]
        elif d == "requires":
            scope_kind["requires"] += t[1:]
    return pk


def primitive_body(body):
    return len(body) == 1 and body[0]["line"] == "field" and \
        body[0]["type"] not in ("string", "enum8", "enum16", "enum32")


def scale_params(tr):
    name, _, arg = tr.partition(":")
    parts = arg.split(":")
    f = parts[0]
    off = float(parts[1]) if len(parts) > 1 else 0.0
    if "/" in f:
        num, den = f.split("/")
        return name, (int(num), int(den)), off
    return name, float(f), off


def round_half_away(q):
    fl = math.floor(q)
    diff = q - fl
    if diff > 0.5:
        return fl + 1
    if diff < 0.5:
        return fl
    return fl + 1 if q > 0 else fl


# --------------------------------------------------------------------------
# Decode.

class Reader:
    def __init__(self, body, order, version, max_items):
        self.b, self.e, self.v, self.off = body, order, version, 0
        self.deferred = []           # transform-decode failures, raised after the structure
        self.items, self.max_items = 0, max_items

    def align(self, a):
        self.off += (-self.off) % a

    def take(self, n):
        if self.off + n > len(self.b):
            raise Fail(MW, "input ends inside a value at off %d" % self.off)
        d = self.b[self.off:self.off + n]
        self.off += n
        return d

    def prim(self, ty):
        size, a1, a2, code, _ = TYPES[ty]
        self.align(a1 if self.v == 1 else a2)
        return struct.unpack(self.e + code, self.take(size))[0]

    def u32(self):
        self.align(4)
        return struct.unpack(self.e + "I", self.take(4))[0]

    def field(self, ln, into):
        ty = ln["type"]
        if ty == "string":
            n = self.u32()
            if n < 1:
                raise Fail(MW, "string length 0")
            data = self.take(n)
            if data[-1] != 0:
                raise Fail(MW, "string without its final NUL")
            text = data[:-1]
            if 0 in text:
                self.deferred.append("NUL inside a string")
                return None
            try:
                val = text.decode("utf-8")
            except UnicodeDecodeError:
                self.deferred.append("string not UTF-8")
                return None
            into[ln["key"]] = val
            return None
        raw = self.prim(ty)
        kind = TYPES[ty][4]
        tr = ln.get("transform")
        if kind == "bool":
            if raw not in (0, 1):
                self.deferred.append("bool %d" % raw)
            else:
                into[ln["key"]] = raw
        elif kind == "float":
            if math.isnan(raw) or math.isinf(raw):
                self.deferred.append("float not finite")
            else:
                into[ln["key"]] = float(raw)
        else:
            if ty == "uint64" and raw > 2**63 - 1:
                self.deferred.append("uint64 above 2^63-1")
            elif tr and tr.split(":")[0] in ("uscale", "sscale"):
                _, f, off = scale_params(tr)
                if isinstance(f, tuple):
                    into[ln["key"]] = float(raw) * f[0] / f[1] + off
                else:
                    into[ln["key"]] = float(raw) * f + off
            else:
                into[ln["key"]] = raw
        return raw

    def lines(self, lines, into, lists, rawpos=None):
        for ln in lines:
            if ln["line"] == "field":
                raw = self.field(ln, into)
                if rawpos is not None:
                    rawpos.append(raw)
            elif ln["line"] == "const":
                raw = self.prim(ln["type"])
                if rawpos is not None:
                    rawpos.append(raw)
            else:
                self.group(ln, lists)
                if rawpos is not None:
                    rawpos.append(None)

    def group(self, g, lists):
        dh = None
        if self.v == 2 and not primitive_body(g["body"]):
            dh = self.u32()
            start = self.off
        if g["seq"]:
            count = self.u32()
        else:
            count = g["n"]
        if count > len(self.b) - self.off:
            raise Fail(MW, "count %d larger than the %d bytes left" % (count, len(self.b) - self.off))
        if self.items + count > self.max_items:
            raise Fail(MW, "item limit")
        self.items += count
        out = []
        for _ in range(count):
            it_keys, it_lists = {}, {}
            self.lines(g["body"], it_keys, it_lists)
            out.append({"keys": it_keys, "lists": it_lists})
        if dh is not None and dh != self.off - start:
            raise Fail(MW, "DHEADER %d, collection %d" % (dh, self.off - start))
        lists[g["list"]] = out


def hex_bytes(text):
    for c in text:
        if c not in "0123456789abcdefABCDEF \t\n\r":
            raise Fail(MW, "character %r in hex text" % c)
    h = re.sub(r"[ \t\n\r]", "", text)
    if len(h) % 2:
        raise Fail(MW, "odd number of hex digits")
    return bytes.fromhex(h)


def cdr_decode(pk, text, max_items=100000):
    data = hex_bytes(text)
    if len(data) < 4:
        raise Fail(MW, "shorter than 4 bytes")
    rep = pk["rep"]
    if data[0] != rep[0] or (data[1] & 0xFE) != (rep[1] & 0xFE):
        raise Fail(MW, "identifier %s" % data[:2].hex())
    order = "<" if data[1] & 1 else ">"
    r = Reader(data[4:], order, pk["cdr"], max_items)
    keys, lists, rawpos = {}, {}, []
    r.lines(pk["common"], keys, lists, rawpos)
    kind = None
    if pk["kinds"]:
        for k in pk["kinds"]:
            if all(rawpos[n - 1] is not None and rawpos[n - 1] == v for n, v in k["when"]):
                kind = k
                break
        if kind is None:
            rest = r.b[r.off:]
            if len(rest) > 3 or any(rest):           # ruling 25: structural before no-kind
                raise Fail(MW, "trailing bytes %s" % rest.hex())
            raise Fail(NK, "no kind")
        r.lines(kind["lines"], keys, lists)
    rest = r.b[r.off:]
    if len(rest) > 3 or any(rest):
        raise Fail(MW, "trailing bytes %s" % rest.hex())
    if r.deferred:
        raise Fail(TD, "; ".join(r.deferred))
    return {"keys": keys, "lists": lists, "kind": (pk["format"], kind["name"]) if kind else None}


# --------------------------------------------------------------------------
# Encode.

class Writer:
    def __init__(self, version, order=">", defaults=None):
        self.v, self.b, self.e = version, bytearray(), order
        self.defaults = defaults or {}

    def align(self, a):
        self.b += b"\x00" * ((-len(self.b)) % a)

    def prim(self, ty, v):
        size, a1, a2, code, _ = TYPES[ty]
        self.align(a1 if self.v == 1 else a2)
        if TYPES[ty][4] == "float":
            try:
                self.b += struct.pack(self.e + code, v)
            except (OverflowError, struct.error):
                raise Fail(TE, "float out of range")
            return
        lo, hi = RANGES[ty]
        if not (lo <= v <= hi):
            raise Fail(TE, "%d outside %s" % (v, ty))
        self.b += struct.pack(self.e + code, v)

    def u32(self, v):
        self.align(4)
        self.b += struct.pack(self.e + "I", v)

    def field(self, ln, keys, override=None):
        ty = ln["type"]
        if override is not None:
            self.prim(ty, override)
            return
        val = keys.get(ln["key"])
        if val is None and ln["key"] in self.defaults and keys is not None and self.top:
            dv = self.defaults[ln["key"]]
            val = dv if ty == "string" else float(dv) if TYPES[ty][4] == "float" else int(dv)
        if ty == "string":
            s = "" if val is None else val
            if "\x00" in s:
                raise Fail(TE, "U+0000 in a string")
            enc = s.encode("utf-8") + b"\x00"
            self.u32(len(enc))
            self.b += enc
            return
        kind = TYPES[ty][4]
        tr = ln.get("transform")
        if val is None:
            self.prim(ty, 0.0 if kind == "float" else 0)
            return
        if kind == "float":
            self.prim(ty, float(val))
        elif tr and tr.split(":")[0] in ("uscale", "sscale"):
            _, f, off = scale_params(tr)
            q = (val - off) * f[1] / f[0] if isinstance(f, tuple) else (val - off) / f
            if math.isnan(q) or math.isinf(q):
                raise Fail(TE, "scale")
            self.prim(ty, round_half_away(q))
        else:
            self.prim(ty, int(val))

    def lines(self, lines, keys, lists, overrides=None):
        pos = 0
        for ln in lines:
            pos += 1
            ov = overrides.get(pos) if overrides else None
            if ln["line"] == "field":
                self.field(ln, keys, ov)
            elif ln["line"] == "const":
                self.prim(ln["type"], ov if ov is not None else ln["value"])
            else:
                self.group(ln, lists.get(ln["list"]))

    def group(self, g, items):
        if items is None:
            if not g["seq"]:
                raise Fail(TE, "absent list under array:%d" % g["n"])
            items = []
        if not g["seq"] and len(items) != g["n"]:
            raise Fail(TE, "array:%d with %d items" % (g["n"], len(items)))
        dhpos = None
        if self.v == 2 and not primitive_body(g["body"]):
            self.align(4)
            dhpos = len(self.b)
            self.b += b"\x00\x00\x00\x00"
        if g["seq"]:
            self.u32(len(items))
        top, self.top = self.top, False         # a common default does not reach into items
        for it in items:
            self.lines(g["body"], it["keys"], it["lists"])
        self.top = top
        if dhpos is not None:
            struct.pack_into(self.e + "I", self.b, dhpos, len(self.b) - dhpos - 4)


def cdr_encode(pk, ent):
    kind = None
    if pk["kinds"]:
        if ent["kind"] and ent["kind"][0] == pk["format"]:
            kind = next(k for k in pk["kinds"] if k["name"] == ent["kind"][1])
        else:
            for k in pk["kinds"]:
                if all(r in ent["keys"] for r in k["requires"]):
                    kind = k
                    break
            if kind is None:
                raise Fail(NK, "no kind qualifies")
    w = Writer(pk["cdr"], "<" if pk["rep"][1] & 1 else ">", pk["defaults"])
    w.top = True
    overrides = dict(kind["when"]) if kind else {}
    w.lines(pk["common"], ent["keys"], ent["lists"], overrides)
    if kind:
        w.lines(kind["lines"], ent["keys"], ent["lists"])
    p = (-len(w.b)) % 4
    w.b += b"\x00" * p
    ident = bytes(pk["rep"])        # the low bit gives the byte order written
    return (ident + bytes([0, p]) + bytes(w.b)).hex()


# --------------------------------------------------------------------------
# geojson (only what the cdr vectors need) and protobuf (the two fields of
# the --protobuf-source inputs).

def parse_geojson_pack(text):
    lines = []
    for line in text.split("\n"):
        t = tokens(line)
        if t and t[0] == "field":
            lines.append((t[1], t[2], t[3]))
    return lines


def geojson_decode(lines, text):
    obj = json.loads(text)
    keys = {}
    for key, loc, tr in lines:
        if loc.startswith("geometry."):
            g = obj.get("geometry")
            if not g:
                continue
            idx = {"lon": 0, "lat": 1, "alt": 2}[loc.split(".")[1]]
            co = g.get("coordinates", [])
            if idx < len(co):
                keys[key] = float(co[idx])
        elif loc.startswith("properties."):
            v = (obj.get("properties") or {}).get(loc.split(".", 1)[1])
            if v is not None:
                keys[key] = v
        else:
            v = obj.get(loc)
            if v is not None:
                keys[key] = v
    return {"keys": keys, "lists": {}, "kind": None}


def num_text(x):
    if x == int(x) and abs(x) < 2**53:
        return str(int(x))
    r = repr(x)
    assert "e" not in r
    return r


def geojson_encode(lines, ent):
    k = ent["keys"]
    parts = ['"type":"Feature"']
    if "lon" in k and "lat" in k:
        co = [num_text(k["lon"]), num_text(k["lat"])] + ([num_text(k["hae"])] if "hae" in k else [])
        parts.append('"geometry":{"type":"Point","coordinates":[%s]}' % ",".join(co))
    else:
        parts.append('"geometry":null')
    props, top = [], []
    for key, loc, tr in lines:
        if key not in k or loc.startswith("geometry."):
            continue
        v = k[key]
        txt = json.dumps(v, ensure_ascii=False) if tr == "string" else (str(v) if tr == "int" else num_text(v))
        if loc.startswith("properties."):
            props.append('"%s":%s' % (loc.split(".", 1)[1], txt))
        else:
            top.append('"%s":%s' % (loc, txt))
    parts.append('"properties":{%s}' % ",".join(props))
    return "{" + ",".join(parts + top) + "}"


def protobuf_decode(text):
    data = hex_bytes(text)
    keys, gains, i = {}, [], 0
    while i < len(data):
        tag = data[i]
        i += 1
        fno, wt = tag >> 3, tag & 7
        if wt == 2:
            n = data[i]
            i += 1
            if fno == 1:
                keys["uid"] = data[i:i + n].decode("utf-8")
            i += n
        elif wt == 5:
            v = struct.unpack("<f", data[i:i + 4])[0]
            i += 4
            if fno == 7:
                gains.append({"keys": {"probe.ratio": float(v)}, "lists": {}})
        else:
            raise AssertionError("not needed here")
    lists = {"probe.gains": gains} if gains else {}
    return {"keys": keys, "lists": lists, "kind": None}


# --------------------------------------------------------------------------
# Model checks.

def model_value_ok(want, got, ty):
    if got is None:
        return False
    if ty == "int":
        return int(want) == got
    if ty == "float":
        w = float(want)
        return got == w or abs(got - w) < 1e-9
    return want == got


def check_model(model, ent, ktypes):
    bad = []
    for mk, want in model.items():
        if mk == "@kind":
            if not ent["kind"] or ent["kind"][1] != want:
                bad.append("@kind %s, decoded %s" % (want, ent["kind"]))
            continue
        if mk == "@absent":
            for a in want:
                if a in ent["keys"]:
                    bad.append("%s should be absent" % a)
            continue
        if mk == "@complete":
            continue
        scope = ent
        path = mk
        while "[" in path:
            lst, rest = path.split("[", 1)
            idx, rest = rest.split("].", 1)
            items = scope["lists"].get(lst)
            if items is None or int(idx) >= len(items):
                bad.append("%s: no item" % mk)
                scope = None
                break
            scope = items[int(idx)]
            path = rest
        if scope is None:
            continue
        if path.endswith(".#"):
            lst = path[:-2]
            items = scope["lists"].get(lst)
            have = "absent" if items is None else str(len(items))
            if have != want:
                bad.append("%s: %s, decoded %s" % (mk, want, have))
            continue
        if not model_value_ok(want, scope["keys"].get(path), ktypes[path]):
            bad.append("%s: %s, decoded %r" % (mk, want, scope["keys"].get(path)))
    return bad


# --------------------------------------------------------------------------
# convert

class Formats:
    def __init__(self, root):
        self.cdr = {}
        for f in ("conformance-cdr", "conformance-cdr2", "conformance-cdr-tail"):
            with open(os.path.join(root, "packs", f, "pack.def"), encoding="utf-8") as fh:
                self.cdr[f] = parse_cdr_pack(fh.read())
        with open(os.path.join(root, "packs", "geojson", "pack.def"), encoding="utf-8") as fh:
            self.gj = parse_geojson_pack(fh.read())
        texts = []
        for m in ("core", "probe"):
            with open(os.path.join(root, "model", m + ".def"), encoding="utf-8") as fh:
                texts.append(fh.read())
        self.ktypes, self.lists = model_types(texts)

    def decode(self, fmt, text, max_items):
        if fmt in self.cdr:
            return cdr_decode(self.cdr[fmt], text, max_items)
        if fmt == "geojson":
            return geojson_decode(self.gj, text)
        if fmt == "conformance-groups-protobuf":
            return protobuf_decode(text)
        raise AssertionError(fmt)

    def convert(self, v):
        mx = v.get("max_items", 100000)
        ent = self.decode(v["from"], v["input"], mx)
        if v["from"] != v["to"]:
            ent["kind"] = None
        for k, val in (v.get("context") or {}).items():
            if k not in ent["keys"]:
                ty = self.ktypes[k]
                ent["keys"][k] = int(val) if ty == "int" else float(val) if ty == "float" else val
        if v["to"] in self.cdr:
            return cdr_encode(self.cdr[v["to"]], ent)
        if v["to"] == "geojson":
            return geojson_encode(self.gj, ent)
        raise AssertionError(v["to"])


def check_vector(fm, v):
    problems = []
    try:
        got = fm.convert(v)
        if "expect_error" in v:
            problems.append("expected %s, converted to %s" % (v["expect_error"], got))
        elif got != v["expect"]:
            problems.append("expect differs:\n   want %s\n   got  %s" % (v["expect"], got))
    except Fail as e:
        if v.get("expect_error") != e.kind:
            problems.append("expected %s, failed %s" % (v.get("expect_error", "success"), e))
    if "model" in v:
        try:
            ent = fm.decode(v["from"], v["input"], v.get("max_items", 100000))
            problems += check_model(v["model"], ent, fm.ktypes)
        except Fail as e:
            problems.append("model: decode failed %s" % e)
    return problems


# --------------------------------------------------------------------------
# Load checks: the rules the wire-cdr load vectors exercise.

PACK_DIRECTIVES = set("""format version distribution source uses wire root field when const kind requires default
map typemap group end word_bytes bit_order layout also pad align presence if opt chain fx length delimiter start
checksum cdr representation""".split())
ONE_ARG = set("format version distribution source uses wire root kind word_bytes bit_order layout pad align "
              "delimiter start checksum cdr representation".split())
NEEDS_WIRE = set("root field when const group end word_bytes bit_order layout also pad align presence if opt chain "
                 "fx length".split())
WIRES = {"xml", "geojson", "json", "bits", "protobuf", "text", "tlv", "uper", "cdr"}
TRANSFORMS = set("string float int iso8601_ms uint twos linscale uscale sscale f32 f64 ascii pstring pvarint psint "
                 "pdouble pfloat bool".split())
OPTIONS = {"via": 1, "with": 1, "absent": 1, "stop": 1, "swap": 0, "trim": 0, "optional": 0}
INTEGER_TYPES = {"int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "octet"}


def field_parts(t, wire):
    """(key, locator-or-type, transform or None, [(option, arg)])."""
    key, loc, rest = t[1], t[2], t[3:]
    tr = None
    if rest and (rest[0] not in OPTIONS or wire != "cdr"):
        tr, rest = rest[0], rest[1:]
    opts, i = [], 0
    while i < len(rest):
        o = rest[i]
        if o not in OPTIONS:
            raise Fail("bad-directive", "option %s" % o)
        if OPTIONS[o]:
            if i + 1 >= len(rest):
                raise Fail("bad-directive", "option %s without argument" % o)
            opts.append((o, rest[i + 1]))
            i += 2
        else:
            opts.append((o, None))
            i += 1
    if len(set(o for o, _ in opts)) != len(opts):
        raise Fail("bad-directive", "option given twice")
    return key, loc, tr, opts


def load_pack(models, text):
    ktypes, lists = model_types(models)
    seen, wire, lines = {}, None, []
    for raw in text.split("\n"):
        t = tokens(raw)
        if not t:
            continue
        d = t[0]
        if d not in PACK_DIRECTIVES:
            raise Fail("unknown-directive", d)
        if d in ONE_ARG and len(t) != 2:
            raise Fail("bad-directive", "%s takes one argument" % d)
        if d in NEEDS_WIRE and wire is None:
            raise Fail("missing-wire", d)
        if d in ("format", "version", "wire", "distribution") and d in seen:
            raise Fail("bad-directive", "second %s" % d)
        seen[d] = True
        if d == "wire":
            if t[1] not in WIRES:
                raise Fail("unknown-wire", t[1])
            wire = t[1]
        if d == "field":
            _, _, tr, _ = field_parts(t, wire)
            if tr is not None and tr.split(":")[0] not in TRANSFORMS:
                raise Fail("unknown-transform", tr)
        lines.append(t)
    for need in ("format", "version", "wire"):
        if need not in seen:
            raise Fail("missing-" + need, "")
    # checks that need the whole file
    cdr_lines = [t for t in lines if t[0] in ("cdr", "representation")]
    if wire != "cdr":
        if cdr_lines:
            raise Fail("bad-directive", "cdr line on %s" % wire)
    else:
        if "cdr" not in seen or "representation" not in seen:
            raise Fail("bad-directive", "missing cdr or representation")
        if sum(t[0] == "cdr" for t in lines) > 1 or sum(t[0] == "representation" for t in lines) > 1:
            raise Fail("bad-directive", "second cdr or representation line")       # ruling 22
        if next(t[1] for t in lines if t[0] == "cdr") not in ("1", "2"):
            raise Fail("bad-directive", "cdr value")                               # ruling 22
        rep = next(t[1] for t in lines if t[0] == "representation")
        if not re.fullmatch(r"[0-9a-f]{4}", rep):
            raise Fail("bad-directive", "representation %s" % rep)
        depth, common, in_kind, groups = 0, [], False, []
        stack = []
        for t in lines:
            d = t[0]
            if d == "field":
                key, ty, tr, opts = field_parts(t, wire)
                if ty not in TYPES:
                    raise Fail("bad-directive", "type %s" % ty)
                default = DEFAULT_TRANSFORM[TYPES[ty][4]]
                if tr is not None and tr != default:
                    if not (tr.split(":")[0] in ("uscale", "sscale") and ty in INTEGER_TYPES):
                        raise Fail("bad-directive", "transform %s on %s" % (tr, ty))
                if any(o not in ("via", "with") for o, _ in opts):
                    raise Fail("bad-directive", "option on cdr")
                if stack:
                    stack[-1]["wire"] += 1
                elif not in_kind:
                    common.append(("field", ty))
            elif d == "const":
                if stack:
                    stack[-1]["wire"] += 1
                elif not in_kind:
                    common.append(("const", t[1]))
            elif d == "group":
                mode = t[2]
                if mode != "seq" and not re.fullmatch(r"array:[0-9]+", mode):
                    raise Fail("bad-directive", "group mode %s" % mode)
                if mode.startswith("array:") and int(mode[6:]) == 0:
                    raise Fail("bad-directive", "array:0")
                if stack:
                    stack[-1]["wire"] += 1
                elif not in_kind:
                    common.append(("group", None))
                g = {"wire": 0}
                stack.append(g)
                groups.append(g)
            elif d == "end":
                stack.pop()
            elif d == "kind":
                in_kind = True
            elif d == "when":
                if stack:
                    raise Fail("bad-directive", "when inside a group")
                n = int(t[1])
                if n < 1 or n > len(common):
                    raise Fail("bad-directive", "when %d" % n)
                what, ty = common[n - 1]
                if what == "group" or ty == "string" or TYPES[ty][4] == "float":
                    raise Fail("bad-directive", "when names a %s" % (ty or what))
                if not re.fullmatch(r"[0-9]+", t[2]) or int(t[2]) >= 2 ** (8 * TYPES[ty][0]):
                    raise Fail("bad-directive", "when value %s does not fit %s" % (t[2], ty))   # ruling 24
        if any(g["wire"] == 0 for g in groups):
            raise Fail("bad-directive", "group with no wire line")
    # 0.4: keys declared and of the transform's type
    used = [t[1] for t in lines if t[0] == "uses"]
    for t in lines:
        if t[0] != "field":
            continue
        key, loc, tr, opts = field_parts(t, wire)
        if key not in ktypes:
            raise Fail("undeclared-key", key)
        if any(o == "via" for o, _ in opts):
            continue
        if wire == "cdr":
            yields = "float" if tr and tr.split(":")[0] in ("uscale", "sscale") else \
                {"int": "int", "bool": "int", "float": "float", "string": "string"}[TYPES[loc][4]]
        else:
            yields = {"int": "int", "float": "float", "string": "string"}.get(tr, "string")
        if yields != ktypes[key]:
            raise Fail("key-type-mismatch", key)
    return None


def check_load(v):
    try:
        load_pack(v["models"], v["pack"])
        got = None
    except Fail as e:
        got = e.kind
    want = v.get("expect_error")
    return [] if got == want else ["load: expected %s, got %s" % (want or "success", got or "success")]


# --------------------------------------------------------------------------

def main(argv):
    root = ROOT
    if "--out" in argv:
        root = argv[argv.index("--out") + 1]
    fm = Formats(root)
    files = sorted(glob.glob(os.path.join(root, "packs", "conformance-cdr", "vectors", "*.json")) +
                   glob.glob(os.path.join(root, "packs", "conformance-cdr-tail", "vectors", "*.json")) +
                   glob.glob(os.path.join(root, "packs", "conformance-cdr2", "vectors", "*.json")) +
                   glob.glob(os.path.join(root, "packs", "geojson", "vectors", "cdr-*.json")))
    loads = sorted(glob.glob(os.path.join(root, "packs", "conformance", "load-vectors", "wire-cdr-*.json")))
    extra = []
    if "--protobuf-source" in argv:
        sys.path.insert(0, HERE)
        import gen
        extra = [d for _, _, d in gen.build_protobuf_source()]
    bad = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            v = json.load(fh)
        for p in check_vector(fm, v):
            bad += 1
            print("%s: %s" % (os.path.relpath(f, root), p))
    for v in extra:
        for p in check_vector(fm, v):
            bad += 1
            print("(protobuf-source) %s: %s" % (v["name"], p))
    for f in loads:
        with open(f, encoding="utf-8") as fh:
            v = json.load(fh)
        for p in check_load(v):
            bad += 1
            print("%s: %s" % (os.path.relpath(f, root), p))
    print("check.py: %d conversion vector(s), %d protobuf-source vector(s), %d load vector(s), %d problem(s)"
          % (len(files), len(extra), len(loads), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
