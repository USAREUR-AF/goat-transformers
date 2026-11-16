#!/usr/bin/env python3
"""Checker, packer and vector generator for the remote-id and adsb packs.

Status: this script reads engine-spec 0.5. The remote-id pack and model/rid.def
now use lines of 0.6 and 0.7 (`default`, `group`, `list`, for the Message Pack
kind), so they and their vectors are maintained by hand, and the script stops
with a message that names those lines. packs/adsb and its vectors are as the
script last wrote them. What follows describes the script on a tree it can
read.

Standard library only. Written from spec/engine-spec.md (versions 0.1.1, 0.2,
0.4, 0.5) of goat-transformers, not from any engine.

What it does, in order:

  1. writes packs/adsb/pack.def from the layout table in this file;
  2. loads model/core.def (from the reference checkout, read-only) and
     model/rid.def and model/adsb.def (from this tree) and checks them;
  3. loads packs/remote-id/pack.def, packs/adsb/pack.def and the reference
     packs/geojson/pack.def, applying the load checks of versions 0.4 and 0.5
     plus two stricter lints of its own (no overlapping bit ranges in a kind,
     no two kinds with the same `when` set);
  4. checks every published message against its published decoded values,
     using decoders written here for that purpose only;
  5. writes every vector, computing bytes and expected values itself;
  6. reads every vector file back from disk and replays it.

Usage:  python3 tools/gen/adsb-remoteid-gen.py [--ref <goat-transformers checkout>] [--check]
        --ref names the checkout that model/core.def and packs/geojson are
        read from; the default is this checkout.
        --check replays the vectors on disk and writes nothing.
"""
import json
import math
import os
import struct
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_REF = ROOT  # this checkout


class PackError(Exception):
    def __init__(self, kind, msg):
        super().__init__("%s: %s" % (kind, msg))
        self.kind = kind


# ---------------------------------------------------------------- grammar

def tokenize(line):
    """Whitespace-separated tokens; double quotes wrap a token with spaces;
    `#` starts a comment only at the start of a token (0.1.1 ruling 1)."""
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t\r\n":
            i += 1
        elif c == "#":
            break
        elif c == '"':
            j = line.find('"', i + 1)
            if j < 0:
                raise PackError("bad-directive", "unterminated quote: " + line)
            out.append(line[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and line[j] not in " \t\r\n":
                j += 1
            out.append(line[i:j])
            i = j
    return out


def directives(text):
    for raw in text.split("\n"):
        t = tokenize(raw)
        if t:
            yield t


KEY_TYPES = ("string", "float", "int")


def load_model(text, modules):
    name = dist = None
    sources, keys = [], {}
    for t in directives(text):
        d, a = t[0], t[1:]
        if d == "module" and len(a) == 1:
            name = a[0]
        elif d == "version" and len(a) == 1:
            pass
        elif d == "distribution" and len(a) == 1:
            if a[0] not in ("public", "controlled"):
                raise PackError("bad-directive", "distribution " + a[0])
            dist = a[0]
        elif d == "source" and len(a) == 1:
            sources.append(a[0])
        elif d == "key" and len(a) in (3, 4):
            if "." in a[0] or a[1] not in KEY_TYPES:
                raise PackError("bad-directive", " ".join(t))
            if a[0] in keys:
                raise PackError("duplicate-key", a[0])
            keys[a[0]] = a[1]
        else:
            raise PackError("bad-directive", " ".join(t))
    if dist is None:
        raise PackError("missing-distribution", str(name))
    if not sources:
        raise PackError("missing-source", str(name))
    if name in modules:
        raise PackError("duplicate-module", name)
    modules[name] = {"distribution": dist, "keys": keys, "sources": sources}
    return name


BITS_YIELD = {"uint": "int", "twos": "int", "linscale": "float",
              "uscale": "float", "sscale": "float", "f32": "float",
              "f64": "float", "ascii": "string"}
TEXT_YIELD = {"string": "string", "float": "float", "int": "int",
              "iso8601_ms": "int"}


class Transform:
    def __init__(self, text, wire, length=None):
        p = text.split(":")
        self.text, self.name, self.args = text, p[0], p[1:]
        table = BITS_YIELD if wire == "bits" else TEXT_YIELD
        if self.name not in table:
            raise PackError("unknown-transform", "%s on wire %s" % (text, wire))
        self.yields = table[self.name]
        if wire != "bits":
            if self.args:
                raise PackError("bad-directive", text)
            return
        try:
            if self.name == "linscale":
                if len(self.args) != 2:
                    raise ValueError
                self.maxpos, self.range = float(self.args[0]), float(self.args[1])
            elif self.name in ("uscale", "sscale"):
                if len(self.args) not in (1, 2):
                    raise ValueError
                # 0.5 ruling 1: a factor is a decimal number or a fraction
                # <num>/<den> of two decimal integers
                if "/" in self.args[0]:
                    num, den = self.args[0].split("/")
                    if not (num.isdigit() and den.isdigit()):
                        raise ValueError
                    self.num, self.den, self.factor = float(num), float(den), None
                    if self.num == 0 or self.den == 0:
                        raise ValueError
                else:
                    self.num = self.den = None
                    self.factor = float(self.args[0])
                    if self.factor == 0:
                        raise ValueError
                self.offset = float(self.args[1]) if len(self.args) == 2 else 0.0
            elif self.args:
                raise ValueError
        except ValueError:
            raise PackError("bad-directive", "transform " + text)
        if self.name == "ascii":
            if length % 8 or not 8 <= length <= 2040:
                raise PackError("bad-directive", "ascii len %d" % length)
        elif not 1 <= length <= 64:
            raise PackError("bad-directive", "len %d" % length)
        if self.name == "f32" and length != 32:
            raise PackError("bad-directive", "f32 len %d" % length)
        if self.name == "f64" and length != 64:
            raise PackError("bad-directive", "f64 len %d" % length)


class Field:
    def __init__(self, key, locator, transform):
        self.key, self.locator, self.transform = key, locator, transform
        self.pos = self.len = None


class Kind:
    def __init__(self, name):
        self.name, self.whens, self.requires, self.fields = name, [], [], []


def bits_locator(text, word_bytes):
    p = text.split(":")
    try:
        word, pos, length = (int(x) for x in p)
        if len(p) != 3 or word < 0 or pos < 0 or length < 1:
            raise ValueError
    except ValueError:
        raise PackError("bad-directive", "locator " + text)
    return word * word_bytes * 8 + pos, length


def split_key(key):
    if "." in key:
        return key.split(".", 1)
    return "core", key


def load_pack(text, modules, max_distribution="controlled"):
    p = {"format": None, "wire": None, "word_bytes": None, "bit_order": None,
         "distribution": None, "sources": [], "uses": ["core"],
         "common": Kind(None), "kinds": []}
    cur = p["common"]
    pending = []                      # (kind, tokens) resolved once wire is known
    for t in directives(text):
        d, a = t[0], t[1:]
        if d in ("format", "version", "wire", "root") and len(a) == 1:
            if d != "version":
                p[d] = a[0]
        elif d == "distribution" and len(a) == 1:
            if a[0] not in ("public", "controlled"):
                raise PackError("bad-directive", "distribution " + a[0])
            p["distribution"] = a[0]
        elif d == "source" and len(a) == 1:
            p["sources"].append(a[0])
        elif d == "uses" and len(a) == 1:
            if a[0] not in p["uses"]:
                p["uses"].append(a[0])
        elif d == "word_bytes" and len(a) == 1 and a[0].isdigit() and int(a[0]) > 0:
            p["word_bytes"] = int(a[0])
        elif d == "bit_order" and len(a) == 1 and a[0] in ("lsb", "msb"):
            p["bit_order"] = a[0]
        elif d == "kind" and len(a) == 1:
            if any(k.name == a[0] for k in p["kinds"]):
                raise PackError("duplicate-kind", a[0])
            cur = Kind(a[0])
            p["kinds"].append(cur)
        elif d == "when" and len(a) == 2:
            pending.append((cur, t))
        elif d == "requires" and len(a) >= 1:
            if cur is p["common"]:
                raise PackError("bad-directive", "requires before the first kind")
            cur.requires.extend(a)
        elif d == "field" and len(a) == 3:
            pending.append((cur, t))
        elif d == "typemap" and len(a) == 2:
            pass
        else:
            raise PackError("bad-directive", " ".join(t))
    wire = p["wire"]
    if wire not in ("bits", "geojson"):
        raise PackError("bad-directive", "this checker handles wire bits and geojson, not %s" % wire)
    if wire != "bits" and p["bit_order"] is not None:
        raise PackError("bad-directive", "bit_order on wire " + wire)
    if wire == "bits":
        if p["word_bytes"] is None:
            raise PackError("bad-directive", "bits wire without word_bytes")
        p["bit_order"] = p["bit_order"] or "lsb"
    for kind, t in pending:
        if t[0] == "when":
            if wire == "bits":
                pos, length = bits_locator(t[1], p["word_bytes"])
                if not t[2].isdigit() or length > 64 or int(t[2]) >= 1 << length:
                    raise PackError("bad-directive", " ".join(t))
                kind.whens.append((pos, length, int(t[2])))
            else:
                kind.whens.append((t[1], t[2]))
        else:
            f = Field(t[1], t[2], None)
            if wire == "bits":
                f.pos, f.len = bits_locator(t[2], p["word_bytes"])
                f.transform = Transform(t[3], wire, f.len)
            else:
                f.transform = Transform(t[3], wire)
            kind.fields.append(f)
    # duplicate-field: within one kind plus common a model key is mapped once
    for kind in p["kinds"] or [Kind(None)]:
        seen = set()
        for f in p["common"].fields + kind.fields:
            if f.key in seen:
                raise PackError("duplicate-field", "%s in kind %s" % (f.key, kind.name))
            seen.add(f.key)
    # version 0.4 checks, in the order the specification gives
    if p["distribution"] is None:
        raise PackError("missing-distribution", str(p["format"]))
    if not p["sources"]:
        raise PackError("missing-source", str(p["format"]))
    if max_distribution == "public" and p["distribution"] == "controlled":
        raise PackError("distribution-refused", p["format"])
    for m in p["uses"]:
        if m not in modules:
            raise PackError("unknown-module", m)
    if p["distribution"] == "public":
        for m in p["uses"]:
            if modules[m]["distribution"] != "public":
                raise PackError("distribution-violation", m)
    everything = [p["common"]] + p["kinds"]
    mapped = [(f.key, f) for k in everything for f in k.fields]
    required = [(key, None) for k in everything for key in k.requires]
    for key, _ in mapped + required:
        if split_key(key)[0] not in p["uses"]:
            raise PackError("module-not-used", key)
    for key, _ in mapped + required:
        m, n = split_key(key)
        if n not in modules[m]["keys"]:
            raise PackError("undeclared-key", key)
    for key, f in mapped:
        m, n = split_key(key)
        if modules[m]["keys"][n] != f.transform.yields:
            raise PackError("key-type-mismatch", "%s is %s, %s yields %s" % (
                key, modules[m]["keys"][n], f.transform.text, f.transform.yields))
    return p


def lint_bits_pack(p):
    """Stricter than the specification: properties these two packs rely on."""
    problems = []
    seen_when = {}
    for kind in p["kinds"]:
        # 0.5 ruling 5 allows overlapping lines. These packs use one form only:
        # a field over exactly the bits of a when. Anything else is a mistake.
        whens = p["common"].whens + kind.whens
        spans = sorted((f.pos, f.pos + f.len, f.key) for f in p["common"].fields + kind.fields)
        for a, b in zip(spans, spans[1:]):
            if b[0] < a[1]:
                problems.append("kind %s: %s overlaps %s" % (kind.name, a[2], b[2]))
        for a in spans:
            for w in whens:
                if a[0] < w[0] + w[1] and w[0] < a[1] and (a[0], a[1]) != (w[0], w[0] + w[1]):
                    problems.append("kind %s: %s partly overlaps a when" % (kind.name, a[2]))
        for a, b in zip(sorted(whens), sorted(whens)[1:]):
            if b[0] < a[0] + a[1]:
                problems.append("kind %s: two when lines overlap" % kind.name)
        sig = tuple(sorted(kind.whens))
        if sig in seen_when:
            problems.append("kinds %s and %s have the same when set" % (seen_when[sig], kind.name))
        seen_when[sig] = kind.name
        for key in kind.requires:
            if key not in [f.key for f in p["common"].fields + kind.fields]:
                problems.append("kind %s requires %s which it does not map" % (kind.name, key))
        if not kind.requires:
            problems.append("kind %s has no requires" % kind.name)
        if len(kind.requires) > 6:
            problems.append("kind %s has more than 6 requires" % kind.name)
    return problems


def coverage(p, kind):
    """(message bits, mapped bits) for a kind of a bits pack."""
    total = message_bits(p, kind)
    got = set()
    for f in p["common"].fields + kind.fields:
        got.update(range(f.pos, f.pos + f.len))
    for w in p["common"].whens + kind.whens:
        got.update(range(w[0], w[0] + w[1]))
    return total, len(got)


# ---------------------------------------------------------------- bits wire

def get_bits(buf, pos, n, order):
    v = 0
    for k in range(n):
        i = pos + k
        if order == "lsb":
            v |= ((buf[i // 8] >> (i % 8)) & 1) << k
        else:
            v = (v << 1) | ((buf[i // 8] >> (7 - i % 8)) & 1)
    return v


def set_bits(buf, pos, n, order, v):
    for k in range(n):
        i = pos + k
        if order == "lsb":
            bit, mask = (v >> k) & 1, 1 << (i % 8)
        else:
            bit, mask = (v >> (n - 1 - k)) & 1, 1 << (7 - i % 8)
        if bit:
            buf[i // 8] |= mask
        else:
            buf[i // 8] &= ~mask & 0xFF


def round_half_away(x):
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def signed(v, n):
    return v - (1 << n) if v >> (n - 1) else v


def field_decode(p, buf, f):
    t, order = f.transform, p["bit_order"]
    if t.name == "ascii":
        raw = bytes(get_bits(buf, f.pos + 8 * j, 8, order) for j in range(f.len // 8))
        raw = raw.rstrip(b"\x00")
        if any(b < 0x20 or b > 0x7E for b in raw):
            raise PackError("transform-decode", "%s: byte outside 0x20-0x7E" % f.key)
        return raw.decode("ascii")
    v = get_bits(buf, f.pos, f.len, order)
    if t.name == "uint":
        return v
    if t.name == "twos":
        return signed(v, f.len)
    if t.name == "linscale":
        return signed(v, f.len) / t.maxpos * t.range
    if t.name in ("uscale", "sscale"):
        if t.name == "sscale":
            v = signed(v, f.len)
        # 0.5 ruling 1: v * factor, or v * num / den, then + offset
        scaled = v * t.factor if t.factor is not None else v * t.num / t.den
        return scaled + t.offset
    if t.name == "f32":
        return struct.unpack(">f", v.to_bytes(4, "big"))[0]
    if t.name == "f64":
        return struct.unpack(">d", v.to_bytes(8, "big"))[0]
    raise AssertionError(t.name)


def field_encode(p, buf, f, x):
    t, order, n = f.transform, p["bit_order"], f.len
    if t.name == "ascii":
        raw = x.encode("ascii")
        if len(raw) > n // 8:
            raise PackError("transform-encode", "%s: text longer than %d" % (f.key, n // 8))
        raw = raw + b"\x00" * (n // 8 - len(raw))
        for j, b in enumerate(raw):
            set_bits(buf, f.pos + 8 * j, 8, order, b)
        return
    if t.name in ("uint", "twos"):
        v = int(x)
    elif t.name == "linscale":
        v = round_half_away(x / t.range * t.maxpos)
    elif t.name in ("uscale", "sscale"):
        if t.factor is not None:
            v = round_half_away((x - t.offset) / t.factor)
        else:
            v = round_half_away((x - t.offset) * t.den / t.num)
        lo, hi = (0, (1 << n) - 1) if t.name == "uscale" else (-(1 << (n - 1)), (1 << (n - 1)) - 1)
        if not lo <= v <= hi:
            raise PackError("transform-encode", "%s: %r out of range" % (f.key, x))
    elif t.name == "f32":
        v = int.from_bytes(struct.pack(">f", x), "big")
    elif t.name == "f64":
        v = int.from_bytes(struct.pack(">d", x), "big")
    else:
        raise AssertionError(t.name)
    set_bits(buf, f.pos, n, order, v & ((1 << n) - 1))


def message_bits(p, kind):
    end = 0
    for f in p["common"].fields + kind.fields:
        end = max(end, f.pos + f.len)
    for w in p["common"].whens + kind.whens:
        end = max(end, w[0] + w[1])
    word = p["word_bytes"] * 8
    return -(-end // word) * word


def when_holds(p, buf, w):
    pos, n, value = w
    if pos + n > len(buf) * 8:
        return False
    return get_bits(buf, pos, n, p["bit_order"]) == value


def bits_decode(p, hextext):
    h = "".join(hextext.split())
    if len(h) % 2:
        raise PackError("malformed-wire", "odd hex length")
    buf = bytearray.fromhex(h)
    if not all(when_holds(p, buf, w) for w in p["common"].whens):
        raise PackError("no-kind", "a common when does not hold")
    for kind in p["kinds"]:
        if all(when_holds(p, buf, w) for w in kind.whens):
            break
    else:
        raise PackError("no-kind", "no kind matches")
    if len(buf) * 8 < message_bits(p, kind):
        raise PackError("malformed-wire", "input shorter than the message")
    entity = {}
    for f in p["common"].fields + kind.fields:
        entity[f.key] = field_decode(p, buf, f)
    return kind.name, entity


def bits_encode(p, entity, kind_name=None):
    kind = None
    if kind_name is not None:
        kind = [k for k in p["kinds"] if k.name == kind_name][0]
    else:
        for k in p["kinds"]:
            if all(key in entity for key in k.requires):
                kind = k
                break
        if kind is None:
            raise PackError("no-kind", "no kind qualifies")
    buf = bytearray(message_bits(p, kind) // 8)
    for f in p["common"].fields + kind.fields:
        if f.key in entity:
            field_encode(p, buf, f, entity[f.key])
    for pos, n, value in p["common"].whens + kind.whens:
        set_bits(buf, pos, n, p["bit_order"], value)
    return buf.hex()


# ---------------------------------------------------------------- geojson out

def float_text(x):
    """Shortest round-trip decimal, plain notation, no decimal point on an
    integer value, negative zero as 0 (0.1.1 ruling 3)."""
    if x == 0:
        return "0"
    s = repr(float(x))
    if "e" in s or "E" in s:
        s = format(Decimal(s), "f")
    if s.endswith(".0"):
        s = s[:-2]
    return s


def scalar_text(f, v):
    y = f.transform.yields
    if y == "string":
        return json.dumps(v, ensure_ascii=False)
    if y == "int":
        return str(int(v))
    return float_text(v)


def geojson_encode(p, entity):
    by_loc = {f.locator: f for f in p["common"].fields}
    geo = {}
    for slot in ("lon", "lat", "alt"):
        f = by_loc.get("geometry." + slot)
        if f is not None and f.key in entity:
            geo[slot] = scalar_text(f, entity[f.key])
    if "lon" in geo and "lat" in geo:
        coords = [geo["lon"], geo["lat"]] + ([geo["alt"]] if "alt" in geo else [])
        geometry = '{"type":"Point","coordinates":[%s]}' % ",".join(coords)
    else:
        geometry = "null"                                   # 0.1.1 ruling 5
    props, top = [], []
    for f in p["common"].fields:
        if f.key not in entity or f.locator.startswith("geometry."):
            continue
        if f.locator.startswith("properties."):
            props.append('"%s":%s' % (f.locator[len("properties."):], scalar_text(f, entity[f.key])))
        else:
            top.append('"%s":%s' % (f.locator, scalar_text(f, entity[f.key])))
    out = '{"type":"Feature","geometry":%s,"properties":{%s}' % (geometry, ",".join(props))
    if top:
        out += "," + ",".join(top)
    return out + "}"


def convert(packs, src, dst, hextext):
    kind, entity = bits_decode(packs[src], hextext)
    if dst == src:
        return bits_encode(packs[dst], entity, kind)
    if packs[dst]["wire"] == "geojson":
        return geojson_encode(packs[dst], entity)
    return bits_encode(packs[dst], entity)


def model_text(v):
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    return float_text(v)


# ---------------------------------------------------------------- adsb layout

# (key, first ME bit numbered from 1 as in the source tables, length)
POSITION_TAIL = [("time_flag", 21, 1), ("cpr_odd", 22, 1), ("cpr_lat", 23, 17), ("cpr_lon", 40, 17)]
IDENT = [("category", 6, 3)] + [("cs_c%d" % (i + 1), 9 + 6 * i, 6) for i in range(8)]
SURFACE = [("movement_raw", 6, 7), ("track_valid", 13, 1), ("track_raw", 14, 7)] + POSITION_TAIL
AIR_BARO = [("ss", 6, 2), ("saf", 8, 1), ("alt_baro_raw", 9, 12)] + POSITION_TAIL
AIR_GNSS = [("ss", 6, 2), ("saf", 8, 1), ("gnss_height_m", 9, 12)] + POSITION_TAIL
VEL_HEAD = [("intent_change", 9, 1), ("ifr", 10, 1), ("nac_v", 11, 3)]
VEL_TAIL = [("vr_source", 36, 1), ("vr_sign", 37, 1), ("vr_raw", 38, 9), ("reserved", 47, 2),
            ("galt_diff_sign", 49, 1), ("galt_diff_raw", 50, 7)]
VEL_GROUND = VEL_HEAD + [("ew_sign", 14, 1), ("ew_raw", 15, 10), ("ns_sign", 25, 1), ("ns_raw", 26, 10)] + VEL_TAIL
VEL_AIR = VEL_HEAD + [("heading_valid", 14, 1), ("heading_raw", 15, 10), ("airspeed_true", 25, 1),
                      ("airspeed_raw", 26, 10)] + VEL_TAIL
STATUS = [("emergency_state", 9, 3), ("squawk_raw", 12, 13), ("reserved", 25, 32)]
TARGET = [("sil_supp", 8, 1), ("sel_alt_fms", 9, 1), ("sel_alt_raw", 10, 11), ("baro_setting_raw", 21, 9),
          ("sel_heading_valid", 30, 1), ("sel_heading_sign", 31, 1), ("sel_heading_raw", 32, 8),
          ("nac_p", 40, 4), ("nic_baro", 44, 1), ("sil", 45, 2), ("mode_valid", 47, 1),
          ("autopilot", 48, 1), ("vnav", 49, 1), ("alt_hold", 50, 1), ("reserved", 51, 1),
          ("approach", 52, 1), ("tcas_operational", 53, 1), ("lnav", 54, 1), ("reserved2", 55, 2)]
OPS_TAIL_A = [("operational_mode", 25, 16), ("version", 41, 3), ("nic_supp_a", 44, 1), ("nac_p", 45, 4)]
OPS_AIR = [("capability_class", 9, 16)] + OPS_TAIL_A + [
    ("gva", 49, 2), ("sil", 51, 2), ("nic_baro", 53, 1), ("hrd", 54, 1), ("sil_supp", 55, 1), ("reserved", 56, 1)]
OPS_SURF = [("surface_capability_class", 9, 12), ("length_width", 21, 4)] + OPS_TAIL_A + [
    ("reserved2", 49, 2), ("sil", 51, 2), ("track_heading", 53, 1), ("hrd", 54, 1), ("sil_supp", 55, 1),
    ("reserved", 56, 1)]

# (kind name, [(ME first bit, length, value) when lines], requires, fields, comment)
ADSB_KINDS = []
for tc in range(1, 5):
    ADSB_KINDS.append(("identification-tc%d" % tc, [(1, 5, tc)],
                       "icao category cs_c1 cs_c8", IDENT, "Aircraft identification, type code %d." % tc))
for tc in range(5, 9):
    ADSB_KINDS.append(("surface-position-tc%d" % tc, [(1, 5, tc)],
                       "icao movement_raw track_raw cpr_odd cpr_lat cpr_lon", SURFACE,
                       "Surface position, type code %d." % tc))
for tc in range(9, 19):
    ADSB_KINDS.append(("airborne-position-baro-tc%d" % tc, [(1, 5, tc)],
                       "icao alt_baro_raw cpr_odd cpr_lat cpr_lon", AIR_BARO,
                       "Airborne position with barometric altitude, type code %d." % tc))
for st in (1, 2):
    ADSB_KINDS.append(("airborne-velocity-ground-st%d" % st, [(1, 5, 19), (6, 3, st)],
                       "icao ew_raw ns_raw vr_raw", VEL_GROUND,
                       "Airborne velocity, type code 19, subtype %d: ground velocity components%s."
                       % (st, "" if st == 1 else ", supersonic scale")))
for st in (3, 4):
    ADSB_KINDS.append(("airborne-velocity-air-st%d" % st, [(1, 5, 19), (6, 3, st)],
                       "icao heading_raw airspeed_raw vr_raw", VEL_AIR,
                       "Airborne velocity, type code 19, subtype %d: airspeed and magnetic heading%s."
                       % (st, "" if st == 3 else ", supersonic scale")))
for tc in range(20, 23):
    ADSB_KINDS.append(("airborne-position-gnss-tc%d" % tc, [(1, 5, tc)],
                       "icao gnss_height_m cpr_odd cpr_lat cpr_lon", AIR_GNSS,
                       "Airborne position with GNSS height, type code %d." % tc))
ADSB_KINDS.append(("aircraft-status-emergency", [(1, 5, 28), (6, 3, 1)],
                   "icao emergency_state squawk_raw", STATUS,
                   "Aircraft status, type code 28, subtype 1: emergency / priority status and Mode A code."))
ADSB_KINDS.append(("target-state", [(1, 5, 29), (6, 2, 1)],
                   "icao sel_alt_raw baro_setting_raw sel_heading_raw", TARGET,
                   "Target state and status, type code 29, subtype 1 (ADS-B version 2)."))
ADSB_KINDS.append(("operational-status-airborne", [(1, 5, 31), (6, 3, 0)],
                   "icao capability_class operational_mode version", OPS_AIR,
                   "Aircraft operational status, type code 31, subtype 0 (airborne), version 2 field names."))
ADSB_KINDS.append(("operational-status-surface", [(1, 5, 31), (6, 3, 1)],
                   "icao surface_capability_class length_width operational_mode version", OPS_SURF,
                   "Aircraft operational status, type code 31, subtype 1 (surface), version 2 field names."))

ADSB_HEAD = """# Mode S Extended Squitter, downlink format 17: ADS-B. 112 bits. Public.
# GENERATED by tools/gen/gen.py from its layout table; edit the table, not this file.
# pack.md states what is mapped, what is not, and why every key is a raw integer.
#
# Addressing: word_bytes 1 and bit_order msb, so a locator is
# 0:<bit offset>:<len> with bit offset 0 = the first transmitted bit, and a
# field's value is its bits with the first bit most significant. The source
# tables number message bits from 1: message bit n is offset n - 1, and bit n
# of the 56-bit ME field is offset 31 + n.
format        adsb
version       0.1.0
distribution  public
source        "Junzi Sun, The 1090 Megahertz Riddle, second edition, TU Delft OPEN Publishing, https://mode-s.org/1090mhz/ (CC BY-NC-SA 4.0): ADS-B chapters 1-6; the layouts documented there are from ICAO Annex 10 Volume IV, ICAO Doc 9871 and RTCA DO-260B"
source        "pyModeS tests (https://github.com/junzis/pyModeS, GPL-3.0): published messages with decoded values, used as facts to check the type code 28 and 29 layouts; no code copied"
uses          adsb
wire          bits
word_bytes    1
bit_order     msb

# Frame: [DF : 5][CA : 3][ICAO address : 24][ME : 56][PI : 24]. Every kind
# starts with the 5-bit type code at ME bit 1 (offset 32). The downlink format
# and the type code are each a `when` and a field over the same bits: the
# `when` selects, the field puts the value in the model (adsb.df, adsb.tc).
when   0:0:5   17
field  adsb.df                        0:0:5      uint
field  adsb.ca                        0:5:3      uint
field  adsb.icao                      0:8:24     uint
field  adsb.parity                    0:88:24    uint
"""


def adsb_pack_text():
    out = [ADSB_HEAD]
    for name, whens, requires, fields, comment in ADSB_KINDS:
        out.append("\n# %s\nkind      %s\n" % (comment, name))
        for first, length, value in whens:
            out.append("when      %-10s %d\n" % ("0:%d:%d" % (31 + first, length), value))
        out.append("requires  %s\n" % " ".join("adsb." + k for k in requires.split()))
        out.append("field  %-30s %-10s uint\n" % ("adsb.tc", "0:32:5"))
        for key, first, length in fields:
            out.append("field  %-30s %-10s uint\n" % ("adsb." + key, "0:%d:%d" % (31 + first, length)))
    return "".join(out)


# ---------------------------------------------------------------- fact checks
# Decoders for the published values only. They are not part of any pack: they
# exist so that a wrong bit offset in the layout table fails here.

def crc24(first88):
    """Mode S parity: remainder of the first 88 bits x 2^24 by 0x1FFF409."""
    v = first88 << 24
    for i in range(111, 23, -1):
        if v >> i & 1:
            v ^= 0x1FFF409 << (i - 24)
    return v & 0xFFFFFF


def callsign(e):
    table = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######"
    return "".join(table[e["adsb.cs_c%d" % i]] for i in range(1, 9)).rstrip()


def baro_altitude_ft(raw):
    assert raw >> 4 & 1, "Q bit not set"
    n = (raw >> 5) << 4 | (raw & 0xF)
    return n * 25 - 1000


def squawk(raw):
    b = [(raw >> (12 - i)) & 1 for i in range(13)]   # C1 A1 C2 A2 C4 A4 X B1 D1 B2 D2 B4 D4
    a = b[1] + 2 * b[3] + 4 * b[5]
    bb = b[7] + 2 * b[9] + 4 * b[11]
    c = b[0] + 2 * b[2] + 4 * b[4]
    d = b[8] + 2 * b[10] + 4 * b[12]
    return "%d%d%d%d" % (a, bb, c, d)


def ground_velocity(e):
    vx = (e["adsb.ew_raw"] - 1) * (-1 if e["adsb.ew_sign"] else 1)
    vy = (e["adsb.ns_raw"] - 1) * (-1 if e["adsb.ns_sign"] else 1)
    return math.hypot(vx, vy), math.degrees(math.atan2(vx, vy)) % 360


def vertical_rate(e):
    return (e["adsb.vr_raw"] - 1) * 64 * (-1 if e["adsb.vr_sign"] else 1)


PUB_BOOK = "The 1090 Megahertz Riddle, 2nd ed., https://mode-s.org/1090mhz/, ADS-B chapter %s"
PUB_PMS = "pyModeS tests/%s at commit 4bf0832, https://github.com/junzis/pyModeS"

# published messages whose last 24 bits are not the remainder of the first 88
PARITY_NOT_VALID = {"target-state-heading-sign"}

# (vector name, message as published, reference, expected kind, fact check, model keys to pin)
PUBLISHED = [
    ("identification-klm1023", "8D4840D6202CC371C32CE0576098", PUB_BOOK % "2 (Aircraft identification)",
     "identification-tc4",
     lambda e: (e["adsb.icao"] == 0x4840D6, callsign(e) == "KLM1023", e["adsb.category"] == 0),
     ["adsb.icao", "adsb.ca", "adsb.category", "adsb.cs_c1", "adsb.cs_c2", "adsb.cs_c3", "adsb.cs_c4",
      "adsb.cs_c5", "adsb.cs_c6", "adsb.cs_c7", "adsb.cs_c8", "adsb.parity"]),
    ("identification-ezy85mh", "8D406B902015A678D4D220AA4BDA", PUB_PMS % "test_bds08.py",
     "identification-tc4",
     lambda e: (e["adsb.icao"] == 0x406B90, callsign(e) == "EZY85MH", e["adsb.category"] == 0),
     ["adsb.icao", "adsb.category", "adsb.cs_c1", "adsb.cs_c7", "adsb.cs_c8"]),
    ("airborne-position-even", "8D40621D58C382D690C8AC2863A7", PUB_BOOK % "3 (Airborne position)",
     "airborne-position-baro-tc11",
     lambda e: (e["adsb.icao"] == 0x40621D, baro_altitude_ft(e["adsb.alt_baro_raw"]) == 38000,
                e["adsb.cpr_odd"] == 0, e["adsb.cpr_lat"] == 93000, e["adsb.cpr_lon"] == 51372),
     ["adsb.icao", "adsb.alt_baro_raw", "adsb.cpr_odd", "adsb.cpr_lat", "adsb.cpr_lon", "adsb.parity"]),
    ("airborne-position-odd", "8D40621D58C386435CC412692AD6", PUB_BOOK % "3 (Airborne position)",
     "airborne-position-baro-tc11",
     lambda e: (baro_altitude_ft(e["adsb.alt_baro_raw"]) == 38000, e["adsb.cpr_odd"] == 1,
                e["adsb.cpr_lat"] == 74158, e["adsb.cpr_lon"] == 50194),
     ["adsb.icao", "adsb.alt_baro_raw", "adsb.cpr_odd", "adsb.cpr_lat", "adsb.cpr_lon"]),
    ("airborne-position-39000ft-even", "8D40058B58C901375147EFD09357", PUB_PMS % "test_bds05.py",
     "airborne-position-baro-tc11",
     lambda e: (baro_altitude_ft(e["adsb.alt_baro_raw"]) == 39000, e["adsb.cpr_odd"] == 0),
     ["adsb.icao", "adsb.alt_baro_raw", "adsb.cpr_odd", "adsb.cpr_lat", "adsb.cpr_lon"]),
    ("airborne-position-39000ft-odd", "8D40058B58C904A87F402D3B8C59", PUB_PMS % "test_bds05.py",
     "airborne-position-baro-tc11",
     lambda e: (baro_altitude_ft(e["adsb.alt_baro_raw"]) == 39000, e["adsb.cpr_odd"] == 1),
     ["adsb.icao", "adsb.alt_baro_raw", "adsb.cpr_odd", "adsb.cpr_lat", "adsb.cpr_lon"]),
    ("airborne-velocity-ground", "8D485020994409940838175B284F",
     PUB_BOOK % "5 (Airborne velocity), message A" + "; " + PUB_PMS % "test_bds09.py",
     "airborne-velocity-ground-st1",
     lambda e: (e["adsb.icao"] == 0x485020, e["adsb.ew_sign"] == 1, e["adsb.ew_raw"] == 9,
                e["adsb.ns_sign"] == 1, e["adsb.ns_raw"] == 160, int(ground_velocity(e)[0]) == 159,
                abs(ground_velocity(e)[1] - 182.88) < 0.01, vertical_rate(e) == -832,
                e["adsb.vr_source"] == 0, e["adsb.ifr"] == 1, e["adsb.vr_raw"] == 14,
                e["adsb.galt_diff_raw"] == 23, (e["adsb.galt_diff_raw"] - 1) * 25 == 550),
     ["adsb.icao", "adsb.ew_sign", "adsb.ew_raw", "adsb.ns_sign", "adsb.ns_raw", "adsb.vr_sign",
      "adsb.vr_raw", "adsb.galt_diff_raw"]),
    ("airborne-velocity-airspeed", "8DA05F219B06B6AF189400CBC33F",
     PUB_BOOK % "5 (Airborne velocity), message B" + "; " + PUB_PMS % "test_bds09.py",
     "airborne-velocity-air-st3",
     lambda e: (e["adsb.icao"] == 0xA05F21, e["adsb.heading_valid"] == 1, e["adsb.heading_raw"] == 694,
                abs(e["adsb.heading_raw"] * 360 / 1024 - 243.98) < 0.01, e["adsb.airspeed_true"] == 1,
                e["adsb.airspeed_raw"] == 376, vertical_rate(e) == -2304, e["adsb.vr_source"] == 1,
                e["adsb.galt_diff_raw"] == 0),
     ["adsb.icao", "adsb.heading_valid", "adsb.heading_raw", "adsb.airspeed_true", "adsb.airspeed_raw",
      "adsb.vr_raw"]),
    ("surface-position-even", "8C4841753AAB238733C8CD4020B1", PUB_BOOK % "4 (Surface position)",
     "surface-position-tc7",
     lambda e: (e["adsb.icao"] == 0x484175, e["adsb.ca"] == 4, e["adsb.movement_raw"] == 0b0101010,
                e["adsb.track_valid"] == 1, e["adsb.track_raw"] == 0b0110010, e["adsb.time_flag"] == 0,
                e["adsb.cpr_odd"] == 0, e["adsb.cpr_lat"] == 0b11100001110011001,
                e["adsb.cpr_lon"] == 0b11100100011001101),
     ["adsb.icao", "adsb.ca", "adsb.movement_raw", "adsb.track_valid", "adsb.track_raw", "adsb.cpr_odd",
      "adsb.cpr_lat", "adsb.cpr_lon"]),
    ("surface-position-odd", "8C4841753A8A35323FAEBDAC702D", PUB_BOOK % "4 (Surface position)",
     "surface-position-tc7",
     lambda e: (e["adsb.movement_raw"] == 0b0101000, e["adsb.track_valid"] == 1,
                e["adsb.track_raw"] == 0b0100011, e["adsb.cpr_odd"] == 1,
                e["adsb.cpr_lat"] == 0b01001100100011111, e["adsb.cpr_lon"] == 0b11010111010111101),
     ["adsb.icao", "adsb.movement_raw", "adsb.track_raw", "adsb.cpr_odd", "adsb.cpr_lat", "adsb.cpr_lon"]),
    ("surface-position-17kt", "8C4841753A9A153237AEF0F275BE", PUB_BOOK % "4 (Surface position)",
     "surface-position-tc7",
     lambda e: (e["adsb.movement_raw"] == 0b0101001, e["adsb.track_valid"] == 1,
                e["adsb.track_raw"] == 0b0100001, abs(e["adsb.track_raw"] * 360 / 128 - 92.8125) < 1e-9,
                e["adsb.cpr_odd"] == 1, e["adsb.cpr_lat"] == 0b01001100100011011,
                e["adsb.cpr_lon"] == 0b11010111011110000),
     ["adsb.icao", "adsb.movement_raw", "adsb.track_raw", "adsb.cpr_odd", "adsb.cpr_lat", "adsb.cpr_lon"]),
    ("aircraft-status-squawk-6513", "8DA2C1B6E112B600000000760759", PUB_PMS % "test_bds61.py",
     "aircraft-status-emergency",
     lambda e: (e["adsb.icao"] == 0xA2C1B6, e["adsb.emergency_state"] == 0,
                squawk(e["adsb.squawk_raw"]) == "6513", e["adsb.reserved"] == 0),
     ["adsb.icao", "adsb.emergency_state", "adsb.squawk_raw"]),
    ("target-state", "8DA05629EA21485CBF3F8CADAEEB", PUB_PMS % "test_bds62.py",
     "target-state",
     lambda e: (e["adsb.icao"] == 0xA05629, (e["adsb.sel_alt_raw"] - 1) * 32 == 16992,
                e["adsb.sel_alt_fms"] == 0, abs(800 + (e["adsb.baro_setting_raw"] - 1) * 0.8 - 1012.8) < 1e-9,
                e["adsb.sel_heading_valid"] == 1, e["adsb.sel_heading_sign"] == 0,
                abs(e["adsb.sel_heading_raw"] * 180 / 256 - 66.8) < 0.1, e["adsb.mode_valid"] == 1,
                e["adsb.autopilot"] == 1, e["adsb.vnav"] == 1, e["adsb.alt_hold"] == 0,
                e["adsb.approach"] == 0, e["adsb.tcas_operational"] == 1, e["adsb.lnav"] == 1),
     ["adsb.icao", "adsb.sel_alt_raw", "adsb.baro_setting_raw", "adsb.sel_heading_sign",
      "adsb.sel_heading_raw", "adsb.autopilot", "adsb.vnav", "adsb.alt_hold", "adsb.approach",
      "adsb.tcas_operational", "adsb.lnav", "adsb.nac_p", "adsb.sil"]),
    ("target-state-heading-sign", "8DA05629EA21485EBF3F8CADAEEB", PUB_PMS % "test_bds62.py",
     "target-state",
     lambda e: (e["adsb.sel_heading_sign"] == 1,
                abs(e["adsb.sel_heading_raw"] * 180 / 256 + 180 - 246.796875) < 1e-9),
     ["adsb.icao", "adsb.sel_heading_sign", "adsb.sel_heading_raw"]),
]


# ---------------------------------------------------------------- vectors

def write_vector(path, vec):
    with open(path, "w") as fh:
        json.dump(vec, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def pinned(kind, entity, keys):
    m = {"@kind": kind}
    for k in keys:
        m[k] = model_text(entity[k])
    return m


def remote_id_vectors(packs):
    p = packs["remote-id"]
    out = []
    inout = "values from opendroneid-core-c test/test_inout.c, quantized as libopendroneid/opendroneid.c encodes them; bytes computed by tools/gen/gen.py"

    def roundtrip(name, kind, values, pins, reference, source="constructed"):
        values = dict(values)
        values.setdefault("rid.proto_version", 2)
        hexmsg = bits_encode(p, values, kind)
        assert len(hexmsg) == 50, (name, len(hexmsg))
        got_kind, entity = bits_decode(p, hexmsg)
        assert got_kind == kind
        out.append({"name": name, "from": "remote-id", "to": "remote-id", "input": hexmsg,
                    "expect": hexmsg, "model": pinned(kind, entity, pins),
                    "source": source, "reference": reference})
        return hexmsg, entity

    roundtrip("basic-id-roundtrip", "basic-id",
              {"rid.ua_type": 2, "rid.id_type": 2, "uid": "12345678901234567890", "rid.reserved": 0},
              ["rid.msg_type", "uid", "rid.id_type", "rid.ua_type", "rid.proto_version"], inout)

    location = {"rid.speed_mult": 0, "rid.ew_direction": 1, "rid.height_type": 1, "rid.status": 2,
                "rid.direction_raw": 36, "rid.speed_h_raw": 22, "rid.speed_v": 5.5,
                "lat": 45.539309, "lon": -122.966389, "rid.alt_baro": 100.0, "hae": 110.0,
                "rid.height": 80.0, "rid.horiz_acc": 11, "rid.vert_acc": 6, "rid.speed_acc": 3,
                "rid.baro_acc": 5, "rid.timestamp_ds": 3605, "rid.ts_acc": 2, "rid.reserved": 0}
    loc_hex, loc_entity = roundtrip(
        "location-roundtrip", "location", location,
        ["rid.msg_type", "lat", "lon", "hae", "rid.alt_baro", "rid.height", "rid.speed_v", "rid.status",
         "rid.direction_raw", "rid.ew_direction", "rid.speed_h_raw", "rid.speed_mult",
         "rid.timestamp_ds"], inout)
    # the integers the C encoder produces for the test_inout.c inputs
    raw = bytes.fromhex(loc_hex)
    assert raw[0] == 0x12 and raw[1] == 0x26 and raw[2] == 36 and raw[3] == 22 and raw[4] == 11
    assert struct.unpack("<ii", raw[5:13]) == (455393090, -1229663890)
    assert struct.unpack("<HHH", raw[13:19]) == (2200, 2220, 2160)
    assert raw[19] == 0x6B and raw[20] == 0x53 and struct.unpack("<H", raw[21:23]) == (3605,)
    assert raw[23] == 2 and raw[24] == 0

    roundtrip("auth-page0-roundtrip", "auth-page0",
              {"rid.auth_type": 1, "rid.auth_last_page_index": 1, "rid.auth_length": 40,
               "rid.auth_timestamp": 28000000, "rid.auth_data_last": 0},
              ["rid.msg_type", "rid.auth_type", "rid.auth_last_page_index", "rid.auth_length", "rid.auth_timestamp"],
              "header " + inout + "; authentication data bytes zero")
    roundtrip("auth-page-roundtrip", "auth-page",
              {"rid.auth_data_page": 1, "rid.auth_type": 1, "rid.auth_data_last": 0},
              ["rid.msg_type", "rid.auth_data_page", "rid.auth_type"],
              "header " + inout + "; authentication data bytes zero")
    roundtrip("self-id-roundtrip", "self-id",
              {"rid.desc_type": 0, "rid.description": "DronesRUS: Real Estate"},
              ["rid.msg_type", "rid.desc_type", "rid.description"], inout)
    sys_hex, _ = roundtrip(
        "system-roundtrip", "system",
        {"rid.operator_location_type": 0, "rid.classification_type": 1,
         "rid.operator_lat": 45.539319, "rid.operator_lon": -122.966379, "rid.area_count": 35,
         "rid.area_radius": 70.0, "rid.area_ceiling": 177.0, "rid.area_floor": 41.5,
         "rid.class_eu": 4, "rid.category_eu": 2, "rid.operator_hae": 20.5,
         "rid.system_timestamp": 28000000, "rid.reserved": 0},
        ["rid.msg_type", "rid.operator_lat", "rid.operator_lon", "rid.operator_hae", "rid.area_count",
         "rid.area_radius", "rid.area_ceiling", "rid.area_floor", "rid.classification_type",
         "rid.category_eu", "rid.class_eu", "rid.system_timestamp"], inout)
    raw = bytes.fromhex(sys_hex)
    assert raw[0] == 0x42 and raw[1] == 0x04
    assert struct.unpack("<ii", raw[2:10]) == (455393190, -1229663790)
    assert struct.unpack("<HBHH", raw[10:17]) == (35, 7, 2354, 2083)
    assert raw[17] == 0x24 and struct.unpack("<HI", raw[18:24]) == (2041, 28000000)
    roundtrip("operator-id-roundtrip", "operator-id",
              {"rid.operator_id_type": 0, "rid.operator_id": "98765432100123456789", "rid.reserved": 0},
              ["rid.msg_type", "rid.operator_id_type", "rid.operator_id"], inout)

    # the one complete 25-byte message that the upstream tests hold as fixed bytes
    spec = bytes([0x02, 0x14]) + b"USS-Enterprise" + bytes(9)
    assert len(spec) == 25
    spec_ref = ("opendroneid-core-c test/unit_odid_wifi_beacon.cpp, expectedBuffer, "
                "Open Drone ID message #1 (Basic ID): 0x02, 0x14, 'USS-Enterprise', NUL padding")
    kind, entity = bits_decode(p, spec.hex())
    assert kind == "basic-id" and entity["uid"] == "USS-Enterprise"
    assert entity["rid.ua_type"] == 4 and entity["rid.id_type"] == 1
    out.append({"name": "basic-id-upstream-test-bytes", "from": "remote-id", "to": "remote-id",
                "input": spec.hex(), "expect": spec.hex(),
                "model": pinned(kind, entity, ["rid.msg_type", "uid", "rid.id_type", "rid.ua_type", "rid.proto_version"]),
                "source": "specification", "reference": spec_ref})
    out.append({"name": "basic-id-upstream-test-bytes-to-geojson", "from": "remote-id", "to": "geojson",
                "input": spec.hex(), "expect": geojson_encode(packs["geojson"], entity),
                "model": pinned(kind, entity, ["uid"]),
                "source": "specification", "reference": spec_ref})

    # Location -> geojson. geojson carries lat, lon and hae of this kind.
    def to_geojson(name, values, reference):
        values = dict(values)
        values.setdefault("rid.proto_version", 2)
        hexmsg = bits_encode(p, values, "location")
        kind, entity = bits_decode(p, hexmsg)
        # sscale:1/10000000 divides, as the C source does (0.5 ruling 1), so
        # the decoded double is the nearest double to the decimal value
        for key in ("lat", "lon", "hae"):
            assert entity[key] == values[key], (name, key, entity[key])
        out.append({"name": name, "from": "remote-id", "to": "geojson", "input": hexmsg,
                    "expect": geojson_encode(packs["geojson"], entity),
                    "model": pinned(kind, entity, ["lat", "lon", "hae"]),
                    "source": "constructed", "reference": reference})

    to_geojson("location-to-geojson", location, inout)
    south_east = dict(location)
    south_east.update({"lat": -33.8567844, "lon": 151.2152967, "hae": 58.5, "rid.ew_direction": 0,
                       "rid.direction_raw": 90, "rid.speed_mult": 1, "rid.speed_h_raw": 10,
                       "rid.speed_v": -2.5, "rid.alt_baro": 61.0, "rid.height": 40.5,
                       "rid.height_type": 0, "rid.timestamp_ds": 35999})
    to_geojson("location-south-east-to-geojson", south_east,
               "constructed: negative latitude, half-meter altitude, speed multiplier set, negative vertical speed")
    unknown_alt = dict(location)
    unknown_alt.update({"lat": 51.4778, "lon": -0.0014, "hae": -1000.0, "rid.alt_baro": -1000.0,
                        "rid.height": -1000.0, "rid.status": 1, "rid.direction_raw": 181,
                        "rid.ew_direction": 1, "rid.speed_h_raw": 255, "rid.speed_mult": 1,
                        "rid.speed_v": 63.0, "rid.timestamp_ds": 65535, "rid.horiz_acc": 0,
                        "rid.vert_acc": 0, "rid.baro_acc": 0, "rid.speed_acc": 0, "rid.ts_acc": 0})
    to_geojson("location-unknown-values-to-geojson", unknown_alt,
               "constructed: every field that has an unknown value in opendroneid.h carries it; "
               "the geodetic altitude raw 0 reaches geojson as -1000")

    # Message Pack (type 0xF) is not mapped: no kind applies.
    pack_msg = bytes([0xF2, 0x19, 0x01]) + spec
    out.append({"name": "message-pack-no-kind", "from": "remote-id", "to": "remote-id",
                "input": pack_msg.hex(), "expect_error": "no-kind",
                "source": "constructed",
                "reference": "Message Pack header (type 0xF, version 2, message size 25, one message) "
                             "followed by the Basic ID message of unit_odid_wifi_beacon.cpp"})
    return out


def adsb_vectors(packs):
    p = packs["adsb"]
    out = []
    kinds = {k.name: k for k in p["kinds"]}
    # every kind: constructed values, valid parity, byte-identical round trip
    for n, (name, _w, requires, _f, _c) in enumerate(ADSB_KINDS):
        kind = kinds[name]
        values = {"adsb.df": 17, "adsb.ca": 5, "adsb.icao": 0xABC000 + n + 1, "adsb.parity": 0}
        for i, f in enumerate(kind.fields):
            if f.key == "adsb.tc":
                values[f.key] = _w[0][2]
            elif f.key in ("adsb.reserved", "adsb.reserved2"):
                values[f.key] = 0
            else:
                values[f.key] = (37 * (i + 1) * (n + 3) + 11) % (1 << f.len) or 1
        first = int(bits_encode(p, values, name), 16) >> 24
        values["adsb.parity"] = crc24(first)
        hexmsg = bits_encode(p, values, name)
        got_kind, entity = bits_decode(p, hexmsg)
        assert got_kind == name and len(hexmsg) == 28
        assert entity == values, name
        pins = ["adsb.df", "adsb.tc"] + ["adsb." + k for k in requires.split()] + ["adsb.parity"]
        out.append({"name": name + "-roundtrip", "from": "adsb", "to": "adsb", "input": hexmsg,
                    "expect": hexmsg, "model": pinned(name, entity, pins), "source": "constructed",
                    "reference": "field values chosen by tools/gen/gen.py; parity computed there with "
                                 "the Mode S generator 0x1FFF409 so the frame is self-consistent"})
    # published messages: decode checks and byte-identical round trips
    for name, msg, reference, kind_name, facts, pins in PUBLISHED:
        hexmsg = msg.lower()
        kind, entity = bits_decode(p, hexmsg)
        assert kind == kind_name, (name, kind)
        results = facts(entity)
        assert all(results), (name, results)
        parity_ok = crc24(int(hexmsg, 16) >> 24) == entity["adsb.parity"]
        assert parity_ok == (name not in PARITY_NOT_VALID), name + ": parity"
        if not parity_ok:
            reference += "; one bit differs from the message above and the source leaves the parity unchanged, so the parity field is not the frame's remainder"
        assert bits_encode(p, entity, kind) == hexmsg, name
        out.append({"name": name, "from": "adsb", "to": "adsb", "input": hexmsg, "expect": hexmsg,
                    "model": pinned(kind, entity, ["adsb.df", "adsb.tc"] + pins), "source": "specification",
                    "reference": "published message " + msg + ": " + reference})
    # downlink format 18 uses the same ME layouts but is not DF17: the common when fails
    out.append({"name": "df18-no-kind", "from": "adsb", "to": "adsb",
                "input": "90406b902015a678d4d220aa4bda", "expect_error": "no-kind",
                "source": "specification",
                "reference": "published message 90406B902015A678D4D220AA4BDA (DF18): " + PUB_PMS % "test_adsb.py"})
    # type code 0 has no kind
    tc0 = int("8d406b902015a678d4d220", 16) & ~(0x1F << 51)
    out.append({"name": "type-code-0-no-kind", "from": "adsb", "to": "adsb",
                "input": "%022x%06x" % (tc0, crc24(tc0)), "expect_error": "no-kind",
                "source": "constructed",
                "reference": "8D406B902015A678D4D220AA4BDA with the type code set to 0 and parity recomputed"})
    return out


def replay(packs, pack_name, directory):
    names, count = set(), 0
    for fn in sorted(os.listdir(directory)):
        with open(os.path.join(directory, fn)) as fh:
            v = json.load(fh)
        assert v["name"] not in names, "duplicate vector name " + v["name"]
        names.add(v["name"])
        assert v["from"] == pack_name, fn
        if "expect_error" in v:
            try:
                convert(packs, v["from"], v["to"], v["input"])
            except PackError as e:
                assert e.kind == v["expect_error"], (fn, e.kind)
            else:
                raise AssertionError(fn + ": expected " + v["expect_error"])
        else:
            got = convert(packs, v["from"], v["to"], v["input"])
            assert got == v["expect"], (fn, got, v["expect"])
            kind, entity = bits_decode(packs[v["from"]], v["input"])
            for key, want in v.get("model", {}).items():
                if key == "@kind":
                    assert kind == want, (fn, kind)
                elif isinstance(entity[key], float):
                    assert abs(entity[key] - float(want)) <= 1e-9, (fn, key)
                else:
                    assert str(entity[key]) == want, (fn, key, entity[key], want)
        count += 1
    return count


# Directives of engine-spec 0.6 and 0.7 that load_model and load_pack do not read.
PAST_0_5 = ("default", "const", "map", "group", "list", "derive")


def lines_past_0_5():
    """-> ["<file>: <directive>", ...] for the files this script loads from this tree."""
    found = []
    for rel in ("model/rid.def", "model/adsb.def", "packs/remote-id/pack.def"):
        seen = []
        with open(os.path.join(ROOT, *rel.split("/"))) as fh:
            for t in directives(fh.read()):
                if t[0] in PAST_0_5 and t[0] not in seen:
                    seen.append(t[0])
        if seen:
            found.append("%s: %s" % (rel, ", ".join("`%s`" % d for d in seen)))
    return found


def main(argv):
    ref = DEFAULT_REF
    if "--ref" in argv:
        ref = argv[argv.index("--ref") + 1]
    check_only = "--check" in argv

    newer = lines_past_0_5()
    if newer:
        sys.stderr.write(
            "adsb-remoteid-gen: this script reads engine-spec 0.5 and cannot run on this tree.\n"
            "  Lines it does not read: %s.\n"
            "  packs/remote-id, model/rid.def and their vectors are maintained by hand\n"
            "  (the Message Pack kind uses `default`, `group` and a `list`, engine-spec 0.6 and 0.7).\n"
            "  packs/adsb and its vectors are as this script last wrote them.\n"
            "  To run it again, extend load_model and load_pack here to engine-spec 0.7.\n"
            % "; ".join(newer))
        return 2

    adsb_def = os.path.join(ROOT, "packs", "adsb", "pack.def")
    if not check_only:
        with open(adsb_def, "w") as fh:
            fh.write(adsb_pack_text())
    else:
        with open(adsb_def) as fh:
            assert fh.read() == adsb_pack_text(), "packs/adsb/pack.def differs from the layout table"

    modules = {}
    for path in (os.path.join(ref, "model", "core.def"),
                 os.path.join(ROOT, "model", "adsb.def"),
                 os.path.join(ROOT, "model", "rid.def")):
        with open(path) as fh:
            load_model(fh.read(), modules)
    packs = {}
    for name, path in (("geojson", os.path.join(ref, "packs", "geojson", "pack.def")),
                       ("remote-id", os.path.join(ROOT, "packs", "remote-id", "pack.def")),
                       ("adsb", adsb_def)):
        with open(path) as fh:
            # a public-only engine must load all three
            packs[name] = load_pack(fh.read(), modules, max_distribution="public")
        assert packs[name]["format"] == name

    problems = lint_bits_pack(packs["remote-id"]) + lint_bits_pack(packs["adsb"])
    assert not problems, problems

    # every key a module declares is mapped by its pack, and the reverse is a load check
    for mod, pack in (("rid", "remote-id"), ("adsb", "adsb")):
        used = {split_key(f.key)[1] for k in [packs[pack]["common"]] + packs[pack]["kinds"]
                for f in k.fields if split_key(f.key)[0] == mod}
        unused = set(modules[mod]["keys"]) - used
        assert not unused, (mod, unused)

    for name in ("remote-id", "adsb"):
        p = packs[name]
        print("pack %s: %d kinds, %d common field(s), %d field lines in all, %d distinct keys" % (
            name, len(p["kinds"]), len(p["common"].fields),
            len(p["common"].fields) + sum(len(k.fields) for k in p["kinds"]),
            len({f.key for k in [p["common"]] + p["kinds"] for f in k.fields})))
        for k in p["kinds"]:
            total, got = coverage(p, k)
            print("  %-34s %2d fields  %3d of %3d bits mapped" % (k.name, len(k.fields), got, total))
            assert total == (200 if name == "remote-id" else 112), k.name
            if name == "adsb":
                assert got == total, k.name

    for name, build in (("remote-id", remote_id_vectors), ("adsb", adsb_vectors)):
        directory = os.path.join(ROOT, "packs", name, "vectors")
        if not check_only:
            vectors = build(packs)
            for old in os.listdir(directory):
                os.remove(os.path.join(directory, old))
            for i, v in enumerate(vectors, 1):
                write_vector(os.path.join(directory, "%02d-%s.json" % (i, v["name"])), v)
        n = replay(packs, name, directory)
        print("pack %s: %d vectors replayed from disk, all pass" % (name, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
