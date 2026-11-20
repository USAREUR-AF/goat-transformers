#!/usr/bin/env python3
"""aplog2pack: ArduPilot DataFlash log messages as goat-transformers packs.

Reads   <ardupilot>/ArduCopter, ArduPlane, Rover, ArduSub, AntennaTracker and libraries
        (every .cpp and .h file, except directories named tests or examples): the
        message definitions; <ardupilot>/libraries/AP_Logger/LogStructure.h for the
        format characters, units and multipliers; COPYING.txt and README.md
        tools/gen/sources/ardupilot-log-PROVENANCE.md   (tag, commit and SHA-256 of every
                                                         file a definition comes from;
                                                         written with --commit, checked otherwise)
Writes  <out>/model/aplog.def                             raw keys of every message
        <out>/packs/ardupilot-log-<name>/pack.def          one `bits` pack per message
        <out>/packs/ardupilot-log-<name>/pack.md
        <out>/packs/ardupilot-log-<name>/PROVENANCE.md
        <out>/packs/ardupilot-log-<name>/vectors/gen-*.json
        <out>/packs/geojson/vectors/gen-geojson-to-ardupilot-log-*.json
        <out>/tools/gen/names/ardupilot-log.json          the key name of every field, kept

A record of an ArduPilot binary (DataFlash) log is a 3-byte header (0xA3, 0x95 and
the message type id) and a payload. The log states the layout of each type id in
an FMT record of the same log: the id, the record length, a name of up to four
characters, a format string with one character per field and the comma-separated
field labels. The id is chosen per build and per log, and the payload holds no
value that names its message, so each message is a format of its own and the
caller names it. The message of a pack is the payload: the record without its
3-byte header.

The definitions are what a firmware writes in those FMT records. This script
reads them from the ArduPilot source at a pinned commit, in this project's words:

  - an entry of a log structure table: `{ LOG_<id>, <size>, "NAME", "FORMAT",
    "LABELS", "UNITS", "MULTIPLIERS" ... }`;
  - a `Write`, `WriteStreaming` or `WriteCritical` call whose name, labels and
    format (and units and multipliers when it has them) are string constants.

A string is a literal, several adjacent literals, or a `#define` of literals.
The payload is the fields one after another in format order, with no padding,
little-endian. Field sizes by format character: b B M 1; h H c C 2; i I e E L f
4; q Q d 8; n 4; N 16; Z 64 (text, NUL-padded); a 64 (32 int16).

One pack per message name. A name that has more than one definition gets one
pack per definition: `ardupilot-log-<vehicle>-<name>` for the definitions in a
vehicle's directory, one pack for each vehicle that has it, and
`ardupilot-log-<name>-<library>` for definitions in different libraries.

Python 3 standard library only. Re-runnable: the same inputs give the same bytes.
Each vector is written by a serializer in this file that works from the
definition. After writing, the script loads the module and every pack through
gtcheck, and decodes and re-encodes every vector with a small fixed-layout `bits`
codec written from spec/engine-spec.md (0.2, 0.5, 0.6). With --compare-xml it
also compares the definitions with the LogMessages.xml files ArduPilot's
Tools/autotest/logger_metadata/parse.py writes at the same commit. Exit status is
non-zero when a check fails.

Usage: aplog2pack.py --ardupilot DIR --out DIR [--check] [--commit SHA --tag TAG]
                     [--compare-xml DIR]
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402  (the script directory is not on the path under `python3 -I`)
import gtcheck    # noqa: E402

VERSION = "0.1.0"
MODULE = "aplog"
REPO = "https://github.com/ArduPilot/ardupilot"
PROV_NAME = "ardupilot-log-PROVENANCE.md"
PROV_REL = "tools/gen/sources/" + PROV_NAME
NAMES_REL = "tools/gen/names/ardupilot-log.json"
STRUCTURE_H = "libraries/AP_Logger/LogStructure.h"
LICENSE_FILES = ["COPYING.txt", "README.md"]
VEHICLES = collections.OrderedDict([("Copter", "ArduCopter"), ("Plane", "ArduPlane"), ("Rover", "Rover"),
                                    ("Sub", "ArduSub"), ("Tracker", "AntennaTracker")])
SKIP_DIRS = {"tests", "examples"}

FORMAT = {   # format character -> (bytes, transform, key type, what it is)
    "b": (1, "twos", "int", "int8"), "B": (1, "uint", "int", "uint8"),
    "M": (1, "uint", "int", "uint8 flight mode"),
    "h": (2, "twos", "int", "int16"), "H": (2, "uint", "int", "uint16"),
    "c": (2, "twos", "int", "int16, value times 100"), "C": (2, "uint", "int", "uint16, value times 100"),
    "i": (4, "twos", "int", "int32"), "I": (4, "uint", "int", "uint32"),
    "e": (4, "twos", "int", "int32, value times 100"), "E": (4, "uint", "int", "uint32, value times 100"),
    "L": (4, "twos", "int", "int32 latitude or longitude, degrees times 10^7"),
    "f": (4, "f32", "float", "float32"), "d": (8, "f64", "float", "float64"),
    "q": (8, "twos", "int", "int64"), "Q": (8, "uint", "int", "uint64"),
    "n": (4, "ascii", "string", "char[4]"), "N": (16, "ascii", "string", "char[16]"),
    "Z": (64, "ascii", "string", "char[64]"),
    "a": (64, "twos", "int", "int16[32]"),
}
# Messages whose latitude and longitude are bound to core keys: the position of the
# vehicle (or, for SIM, of the simulated vehicle), each a pair of `L` fields with
# the units deglatitude/deglongitude and the multiplier 1e-7.
BOUND = collections.OrderedDict([
    ("GPS", "the position a GNSS receiver reports for the vehicle"),
    ("POS", "the vehicle position the AHRS estimates"),
    ("AHR2", "the vehicle position the secondary AHRS estimates"),
    ("EAHR", "the vehicle position an external AHRS reports"),
    ("SIM", "the position of the simulated vehicle"),
    ("CAM", "the vehicle position when a camera image was taken"),
    ("TRIG", "the vehicle position when the camera trigger fired"),
])
FROM_GEOJSON = ["GPS", "POS"]
DEGE7 = "1/10000000"


class GenError(Exception):
    pass


def fail(msg):
    raise GenError(msg)


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# --------------------------------------------------------------------------
# Definitions from the source
# --------------------------------------------------------------------------

STR = r'((?:"[^"\n]*"\s*)+|[A-Za-z_]\w*)'
RE_TABLE = re.compile(r"\{\s*LOG_\w+\s*,\s*[^{},]+?\s*,\s*" + r"\s*,\s*".join([STR] * 5))
RE_WRITE = re.compile(r"\bWrite(?:Streaming|Critical)?\s*\(\s*" + STR + r"\s*,\s*" + STR + r"\s*,\s*" + STR +
                      r"(?:\s*,\s*" + STR + r"\s*,\s*" + STR + r")?")
RE_DEFINE = re.compile(r"#\s*define\s+(\w+)\s+((?:\"[^\"\n]*\"\s*)+)")
RE_FORMAT_ONLY = re.compile(r"[%s]+" % "".join(FORMAT))


def clean(text):
    """C source without comments, with continued lines joined."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text.replace("\\\n", " ")


def source_files(root):
    out = []
    for d in list(VEHICLES.values()) + ["libraries"]:
        for dp, dn, fn in os.walk(os.path.join(root, d)):
            dn[:] = sorted(x for x in dn if x not in SKIP_DIRS)
            for f in sorted(fn):
                if f.endswith((".cpp", ".h")):
                    out.append(os.path.relpath(os.path.join(dp, f), root).replace(os.sep, "/"))
    return out


class Definition:
    def __init__(self, name, fmt, labels, units, mults, scope, files):
        self.name, self.fmt, self.labels, self.units, self.mults = name, fmt, labels, units, mults
        self.scope = scope          # a vehicle name, or "lib"
        self.files = files          # where it is written (sorted)
        self.library = None         # the library directory, for a library definition

    @property
    def key(self):
        return (self.fmt, ",".join(self.labels), self.units, self.mults)


def extract(root):
    """{name: [Definition]}: every distinct definition of each name."""
    texts, defines = {}, collections.defaultdict(set)
    for rel in source_files(root):
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
            t = clean(fh.read())
        texts[rel] = t
        for m in RE_DEFINE.finditer(t):
            defines[m.group(1)].add("".join(re.findall(r'"([^"]*)"', m.group(2))))

    def value(s):
        if s is None:
            return None
        s = s.strip()
        if s.startswith('"'):
            return "".join(re.findall(r'"([^"]*)"', s))
        v = defines.get(s)
        return next(iter(v)) if v and len(v) == 1 else None

    found = collections.defaultdict(lambda: collections.defaultdict(set))   # (scope, name) -> key -> files
    for rel, t in texts.items():
        top = rel.split("/")[0]
        scope = next((v for v, d in VEHICLES.items() if d == top), "lib")
        for m in RE_TABLE.finditer(t):
            name, fmt, labels, units, mults = (value(x) for x in m.groups())
            if name and fmt and labels:
                found[(scope, name)][(fmt, labels, units, mults)].add(rel)
        for m in RE_WRITE.finditer(t):
            g = [value(x) for x in m.groups()]
            if not g[0] or not g[1]:
                continue
            if g[3] is not None and g[4] is not None:
                name, labels, units, mults, fmt = g
            else:
                name, labels, fmt, units, mults = g[0], g[1], g[2], None, None
            if fmt and RE_FORMAT_ONLY.fullmatch(fmt) and "," in labels:
                found[(scope, name)][(fmt, labels, units, mults)].add(rel)
    byname = collections.defaultdict(list)
    for (scope, name), variants in sorted(found.items()):
        for (fmt, labels, units, mults), files in sorted(variants.items()):
            d = Definition(name, fmt, labels.split(","), units, mults, scope, sorted(files))
            if scope == "lib":
                libs = sorted({f.split("/")[1] for f in files})
                d.library = libs[0] if len(libs) == 1 else None
            check_definition(d)
            byname[name].append(d)
    return byname, texts


def check_definition(d):
    where = "%s (%s)" % (d.name, ", ".join(d.files))
    if not re.fullmatch(r"[A-Z0-9]{1,4}", d.name):
        fail("%s: a name is one to four capital letters or digits" % where)
    if not RE_FORMAT_ONLY.fullmatch(d.fmt):
        fail("%s: unknown format character in %r" % (where, d.fmt))
    if len(d.labels) != len(d.fmt):
        fail("%s: %d labels for %d format characters" % (where, len(d.labels), len(d.fmt)))
    for what, s in (("units", d.units), ("multipliers", d.mults)):
        if s is not None and len(s) != len(d.fmt):
            fail("%s: %d %s for %d format characters" % (where, len(s), what, len(d.fmt)))


def unit_tables(root):
    """The unit and multiplier tables of LogStructure.h: {char: text}, {char: text}."""
    with open(os.path.join(root, STRUCTURE_H), encoding="utf-8") as fh:
        t = fh.read()
    units = dict(re.findall(r"\{\s*'(.)'\s*,\s*\"([^\"]*)\"\s*\}", t))
    mults = dict(re.findall(r"\{\s*'(.)'\s*,\s*([0-9.eE+-]+)\s*\}", t))
    if units.get("D") != "deglatitude" or units.get("U") != "deglongitude" or mults.get("G") != "1e-7":
        fail("%s: the units D, U or the multiplier G are not what the bindings rely on" % STRUCTURE_H)
    return units, mults


class Pack:
    def __init__(self, fmt_name, prefix, d, vehicles):
        self.format = fmt_name      # ardupilot-log-...
        self.prefix = prefix        # key prefix
        self.d = d
        self.vehicles = vehicles    # the vehicles that log this definition (None: every one)


def plan(byname):
    """The packs, by the rule in the docstring."""
    packs = []
    for name in sorted(byname):
        defs = byname[name]
        low = name.lower()
        if len(defs) == 1:
            d = defs[0]
            packs.append(Pack("ardupilot-log-" + low, low, d, None if d.scope == "lib" else [d.scope]))
            continue
        if all(d.scope != "lib" for d in defs):
            for d in defs:
                for v in VEHICLES:
                    if d.scope == v:
                        packs.append(Pack("ardupilot-log-%s-%s" % (v.lower(), low), "%s_%s" % (v.lower(), low), d, [v]))
            continue
        if all(d.scope == "lib" and d.library for d in defs):
            libs = [d.library for d in defs]
            if len(set(libs)) != len(libs):
                fail("%s: two definitions in one library %s" % (name, libs))
            for d in defs:
                short = re.sub(r"^ap_hal_", "", d.library.lower())
                packs.append(Pack("ardupilot-log-%s-%s" % (low, short.replace("_", "-")), "%s_%s" % (low, short), d, None))
            continue
        fail("%s: definitions in a library and in a vehicle, or a library definition in several "
             "libraries; the naming rule does not cover it: %s" % (name, [(d.scope, d.files) for d in defs]))
    return packs


# --------------------------------------------------------------------------
# Fields
# --------------------------------------------------------------------------

class Leaf:
    def __init__(self, key, bit, length, transform, keytype, label, char, unit, mult):
        self.key, self.bit, self.length, self.transform = key, bit, length, transform
        self.keytype, self.label, self.char, self.unit, self.mult = keytype, label, char, unit, mult


class Namer:
    def __init__(self, names):
        self.names = names
        self.taken = {v: k for k, v in names.items()}

    def name(self, pathid, proposal):
        if pathid not in self.names:
            k, i = proposal, 2
            while k in self.taken and self.taken[k] != pathid:
                k = "%s_%d" % (proposal, i)
                i += 1
            self.names[pathid] = k
            self.taken[k] = pathid
        return self.names[pathid]


def key_part(label):
    return re.sub(r"[^a-z0-9_]", "_", label.lower())


def leaves(p, namer):
    d = p.d
    out, bit = [], 0
    bound = bound_fields(d)
    for i, c in enumerate(d.fmt):
        nbytes, tr, kt, _ = FORMAT[c]
        label = d.labels[i]
        unit = d.units[i] if d.units else None
        mult = d.mults[i] if d.mults else None
        if c == "a":
            for j in range(32):
                k = namer.name("%s:%s[%d]" % (p.format, label, j), "%s_%s_%d" % (p.prefix, key_part(label), j))
                out.append(Leaf(k, bit + j * 16, 16, "twos", "int", "%s[%d]" % (label, j), c, unit, mult))
        elif i in bound:
            out.append(Leaf(bound[i], bit, 32, "sscale:" + DEGE7, "float", label, c, unit, mult))
        else:
            k = namer.name("%s:%s" % (p.format, label), "%s_%s" % (p.prefix, key_part(label)))
            out.append(Leaf(k, bit, nbytes * 8, tr, kt, label, c, unit, mult))
        bit += nbytes * 8
    return out


def bound_fields(d):
    """{field index: core key} for a message of BOUND."""
    if d.name not in BOUND:
        return {}
    lat = [i for i, c in enumerate(d.fmt) if c == "L" and d.units and d.units[i] == "D" and d.mults and d.mults[i] == "G"]
    lon = [i for i, c in enumerate(d.fmt) if c == "L" and d.units and d.units[i] == "U" and d.mults and d.mults[i] == "G"]
    if len(lat) != 1 or len(lon) != 1:
        fail("%s: binding needs one L field with unit D and one with unit U, multiplier G" % d.name)
    return {lat[0]: "lat", lon[0]: "lon"}


def qual(key):
    return key if key in ("lat", "lon") else "%s.%s" % (MODULE, key)


def payload_size(d):
    return sum(FORMAT[c][0] for c in d.fmt)


# --------------------------------------------------------------------------
# Serializer for vectors: works from the definition, not from pack.def
# --------------------------------------------------------------------------

STRUCT = {"b": "b", "B": "B", "M": "B", "h": "h", "H": "H", "c": "h", "C": "H", "i": "i", "I": "I",
          "e": "i", "E": "I", "L": "i", "f": "f", "d": "d", "q": "q", "Q": "Q"}


class Sampler:
    def __init__(self):
        self.n = 0

    def value(self, c):
        self.n += 1
        n = self.n
        if c == "f":
            return (n % 61 - 30.5) * 0.25
        if c == "d":
            return float("%s%d.%03d" % ("-" if n % 3 == 0 else "", n, n * 7 % 1000))
        if c in "nNZ":
            size = FORMAT[c][0]
            t = ("t%d" % n)[:size]
            return t.encode("ascii") + b"\0" * (size - len(t))
        size = FORMAT[c][0] * 8
        signed = STRUCT[c].islower()
        if c == "L":
            return (n * 1234567) % 900000000 - 450000000
        if c in "qQ":
            return -(n * 1000003) if signed else n * 1000003 + 1700000000
        span = 1 << size
        v = (n * 40503 + 7) % span
        return v - span // 2 if signed else v


def serialize(d, sampler, override=None):
    """Payload bytes and {label: value} with sample values; `override` sets fields."""
    buf, values = bytearray(), {}
    for i, c in enumerate(d.fmt):
        label = d.labels[i]
        if c == "a":
            vs = [((sampler.n + j) * 911) % 65536 - 32768 for j in range(32)]
            sampler.n += 1
            buf += struct.pack("<32h", *vs)
            for j, v in enumerate(vs):
                values["%s[%d]" % (label, j)] = v
            continue
        v = override[i] if override and i in override else sampler.value(c)
        if c in "nNZ":
            buf += v
            values[label] = v.rstrip(b"\0").decode("ascii")
        else:
            buf += struct.pack("<" + STRUCT[c], v)
            values[label] = v
    return bytes(buf), values


# --------------------------------------------------------------------------
# Independent check: a fixed-layout `bits` codec from spec/engine-spec.md
# (0.2; 0.5 lsb order, fields past their word, sscale, f32, f64, ascii). It
# reads pack.def text.
# --------------------------------------------------------------------------

class Fail(Exception):
    def __init__(self, kind, detail=""):
        Exception.__init__(self, "%s: %s" % (kind, detail))
        self.kind = kind


def read_lines(text):
    out = []
    for line in text.split("\n"):
        t = gtcheck.tokenize(line)
        if t and t[0] == "field":
            w, p, n = (int(x) for x in t[2].split(":"))
            out.append((t[1], w * 8 + p, n, t[3]))
    return out


def scale(tr):
    num, den = tr.split(":", 1)[1].split("/")
    return int(num), int(den)


def decode_value(raw, length, tr):
    if tr == "uint":
        return raw
    if tr == "twos":
        return raw - (1 << length) if raw >> (length - 1) else raw
    if tr.startswith("sscale:"):
        v = raw - (1 << length) if raw >> (length - 1) else raw
        num, den = scale(tr)
        return v * num / den
    if tr in ("f32", "f64"):
        v = struct.unpack("<f" if tr == "f32" else "<d", raw.to_bytes(length // 8, "little"))[0]
        if math.isnan(v) or math.isinf(v):
            raise Fail("transform-decode", "not finite")
        return v
    if tr == "ascii":
        b = raw.to_bytes(length // 8, "little").rstrip(b"\0")
        if any(c < 0x20 or c > 0x7e for c in b):
            raise Fail("transform-decode", "ascii")
        return b.decode("ascii")
    fail("transform %s not in this codec" % tr)


def round_away(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def encode_value(v, length, tr):
    if tr in ("uint", "twos"):
        return int(v) & ((1 << length) - 1)
    if tr.startswith("sscale:"):
        num, den = scale(tr)
        r = round_away(v * den / num)
        if not -(1 << (length - 1)) <= r < (1 << (length - 1)):
            raise Fail("transform-encode", "out of range")
        return r & ((1 << length) - 1)
    if tr == "f32":
        return int.from_bytes(struct.pack("<f", v), "little")
    if tr == "f64":
        return int.from_bytes(struct.pack("<d", v), "little")
    if tr == "ascii":
        b = v.encode("ascii")
        return int.from_bytes(b + b"\0" * (length // 8 - len(b)), "little")
    fail("transform %s not in this codec" % tr)


def decode(lines, data):
    nbytes = (max(b + n for _, b, n, _ in lines) + 7) // 8
    if len(data) < nbytes:
        raise Fail("malformed-wire", "short input")
    whole = int.from_bytes(data, "little")
    return {k: decode_value((whole >> b) & ((1 << n) - 1), n, tr) for k, b, n, tr in lines}


def encode(lines, ent):
    acc = 0
    for k, b, n, tr in lines:
        if k in ent:
            acc |= encode_value(ent[k], n, tr) << b
    return acc.to_bytes((max(b + n for _, b, n, _ in lines) + 7) // 8, "little")


def fmt_float(x):
    if x == 0:
        return "0"
    s = format(Decimal(repr(float(x))), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def geojson_point(lat, lon):
    return '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},"properties":{}}' % (
        fmt_float(lon), fmt_float(lat))


def check_vector(vec, lines_of, where):
    src, dst = vec["from"], vec["to"]
    try:
        if src == "geojson":
            c = (json.loads(vec["input"]).get("geometry") or {}).get("coordinates") or []
            ent = {"lat": float(c[1]), "lon": float(c[0])} if len(c) >= 2 else {}
            out = encode(lines_of[dst], ent).hex()
        else:
            ent = decode(lines_of[src], bytes.fromhex(vec["input"]))
            if dst == "geojson":
                out = geojson_point(ent["lat"], ent["lon"])
            else:
                out = encode(lines_of[dst], ent).hex()
        for k, want in vec.get("model", {}).items():
            got = ent.get(k)
            ok = abs(got - float(want)) <= 1e-9 if isinstance(got, float) else str(got) == want
            if not ok:
                fail("%s: model %s = %r, want %r" % (where, k, got, want))
    except Fail as e:
        if vec.get("expect_error") == e.kind:
            return
        fail("%s: %s" % (where, e))
    if "expect_error" in vec:
        fail("%s: converted, want error %s" % (where, vec["expect_error"]))
    if out != vec["expect"]:
        fail("%s:\n got    %s\n expect %s" % (where, out, vec["expect"]))


# --------------------------------------------------------------------------
# Comparison with parse.py output
# --------------------------------------------------------------------------

XML_TYPE = {"a": "int16_t[32]", "b": "int8_t", "B": "uint8_t", "h": "int16_t", "H": "uint16_t",
            "i": "int32_t", "I": "uint32_t", "f": "float", "d": "double", "n": "char[4]",
            "N": "char[16]", "Z": "char[64]", "c": "int16_t * 100", "C": "uint16_t * 100",
            "e": "int32_t * 100", "E": "uint32_t * 100", "L": "int32_t latitude/longitude",
            "M": "uint8_t flight mode", "q": "int64_t", "Q": "uint64_t"}


def compare_xml(byname, xml_dir):
    """Compare with <xml_dir>/<Vehicle>/LogMessages.xml. Returns (agree, [(vehicle, name, why)])."""
    import xml.etree.ElementTree as ET
    agree, differ = 0, []
    for v in VEHICLES:
        path = os.path.join(xml_dir, v, "LogMessages.xml")
        root = ET.parse(path).getroot()
        for lf in root.iter("logformat"):
            name = lf.get("name")
            fields = [(f.get("name"), f.get("type")) for f in lf.iter("field")]
            defs = [d for d in byname.get(name, []) if d.scope in ("lib", v)]
            if not defs:
                differ.append((v, name, "documented, no definition found"))
                continue
            mine = [(lab, XML_TYPE[c]) for d in defs[:1] for lab, c in zip(d.labels, d.fmt)]
            if not fields:
                differ.append((v, name, "documented without fields"))
            elif any(fields == [(lab, XML_TYPE[c]) for lab, c in zip(d.labels, d.fmt)] for d in defs):
                agree += 1
            elif any([t for _, t in fields] == [t for _, t in mine] for d in defs):
                differ.append((v, name, "same types; field names in another order"))
            else:
                differ.append((v, name, "types differ: the documentation lists the fields in another order"))
    return agree, differ


# --------------------------------------------------------------------------
# Emit
# --------------------------------------------------------------------------

def sources_lines(tag, commit):
    return ['"ArduPilot log message definitions (log structure tables and Write calls), %s at tag %s, commit %s; message names, format strings, labels, units and multipliers only; GNU General Public License, version 3"' % (REPO, tag, commit),
            '"ArduPilot %s: the format characters, units and multipliers of a log message, at the same commit"' % STRUCTURE_H]


def describe(leaf, units, mults):
    s = "%s, %s" % (leaf.char, FORMAT[leaf.char][3])
    if leaf.unit and leaf.unit not in "-?":
        s += ", unit %s" % units.get(leaf.unit, leaf.unit)
    if leaf.mult and leaf.mult not in "-?":
        s += ", multiplier %s" % mults.get(leaf.mult, leaf.mult)
    return s


def emit_pack(p, items, tag, commit):
    a = ["# ArduPilot log message %s as the payload of a DataFlash log record." % p.d.name,
         "# Generated by tools/gen/aplog2pack.py; do not edit by hand.",
         "# The record without its 3-byte header (0xA3 0x95 type-id); fields packed, little-endian.",
         "format        %s" % p.format, "version       %s" % VERSION, "distribution  public"]
    a += ["source        %s" % s for s in sources_lines(tag, commit)]
    a += ["uses          %s" % MODULE, "wire          bits", "bit_order     lsb", "word_bytes    1"]
    for x in items:
        a.append("field  %s  0:%d:%d  %s" % (qual(x.key), x.bit, x.length, x.transform))
    return "\n".join(a) + "\n"


def emit_module(decls, tag, commit):
    a = ["# The aplog module: raw keys of the ardupilot-log-<name> formats, one per field of an",
         "# ArduPilot log message (an int16[32] field is one key per element).",
         "# Generated by tools/gen/aplog2pack.py; edit the generator, not this file.",
         "module        %s" % MODULE, "version       %s" % VERSION, "distribution  public"]
    a += ["source        %s" % s for s in sources_lines(tag, commit)]
    w = max(len(k) for k, _, _ in decls)
    for k, typ, desc in decls:
        a.append('key  %-*s  %-6s  -  "%s"' % (w, k, typ, desc))
    return "\n".join(a) + "\n"


def emit_pack_md(p, items, units, mults, n_vec, cross_from, same_name):
    d = p.d
    who = "every vehicle that builds the library" if p.vehicles is None else ", ".join(p.vehicles)
    a = ["# %s" % p.format, "",
         "ArduPilot DataFlash log message `%s`, logged by %s, as the payload of one log" % (d.name, who),
         "record. Generated by `tools/gen/aplog2pack.py` (run by `tools/gen/aplog2pack-run.sh`);",
         "do not edit by hand.", "",
         "## Message convention", "",
         "A log record is a 3-byte header (0xA3, 0x95, the type id) and a payload. A message",
         "of this format is the payload, %d bytes. The type id of `%s` is given by an FMT" % (payload_size(d), d.name),
         "record of the same log, and the payload holds no value that names the message, so",
         "no `when` line could select it: each message is a format of its own and the caller",
         "names it. The fields follow one another in the order of the format string `%s`," % d.fmt,
         "with no padding, little-endian, as the FMT record states them.", ""]
    if same_name:
        a += ["## One name, several definitions", "",
              "The name `%s` has %d definitions at this commit: %s. Each is its own pack;" % (
                  d.name, len(same_name), ", ".join("`%s`" % f for f in same_name)),
              "a vehicle's own definition is a pack named `ardupilot-log-<vehicle>-<name>`, a",
              "library's `ardupilot-log-<name>-<library>`. A reader picks the pack by the",
              "vehicle (or board) that wrote the log, or by comparing the FMT record with the",
              "format string above.", ""]
    a += ["## Layout", "",
          "| Offset (bytes) | Bits | Label | Format character | Line |", "|---|---|---|---|---|"]
    for x in items:
        a.append("| %d | %d | `%s` | %s | `%s` %s |" % (x.bit // 8, x.length, x.label,
                                                    describe(x, units, mults), qual(x.key), x.transform))
    a += ["", "## Shared-model keys", ""]
    if d.name in BOUND:
        a += ["| Label | Key | Evidence |", "|---|---|---|"]
        for x in items:
            if x.key in ("lat", "lon"):
                a.append("| `%s` | `%s` | format character `L` (\"int32_t latitude/longitude\" in the format "
                         "table of `%s`), unit `%s` (%s), multiplier `G` (1e-7): degrees times 10^7, "
                         "decoded with `sscale:%s`; %s |" % (
                             x.label, x.key, STRUCTURE_H, x.unit, units[x.unit], DEGE7, BOUND[d.name]))
        a += ["", "The log definition names no datum. The binding rests on the unit and the scale",
              "above and takes the values as the WGS 84 latitude and longitude that `lat` and",
              "`lon` hold; a log whose positions use another datum must not be read through it.",
              "Altitudes are not bound: this family binds latitude and longitude only."]
    else:
        a += ["None. Every field is a raw key of module `%s`, holding the value as it is in" % MODULE,
              "the payload (an `e`, `c` or `L` field keeps its integer, before its multiplier)."]
        if any(x.char == "L" for x in items):
            a += ["", "The `L` fields of this message are latitudes and longitudes in degrees times",
                  "10^7, but not the position of the vehicle (a target, an origin, a mission item",
                  "or a planned point), so they are not bound to `lat` and `lon`."]
    a += ["", "## Not mapped, and why", "", "| What | Why |", "|---|---|",
          "| The 3-byte record header | it belongs to the log, not the message; the type id differs per log |",
          "| Units and multipliers | they are stated in the key meanings of `model/aplog.def`; the raw "
          "keys keep the wire integer, as DataFlash readers before scaling do |",
          "| Bytes of a text field after its first NUL | `ascii` removes trailing NULs and refuses other "
          "bytes outside 0x20-0x7E (`transform-decode`) |",
          "| NaN and infinite floats | the `f32` and `f64` transforms refuse them on decode |",
          "| FMT, FMTU, UNIT and MULT records | they describe the other records of a log and are not "
          "messages of this format |"]
    a += ["", "## Vectors", "",
          "`vectors/gen-rt.json` is a round trip with every field set: values chosen by the generator,",
          "packed by its own serializer from the format string. Other `gen-*` files are edge and",
          "error cases and conversions to geojson, each with its rule in `source`. %d vector file(s)." % n_vec]
    if cross_from:
        a.append("`packs/geojson/vectors/gen-geojson-to-%s.json` converts from geojson." % p.format)
    a += ["", "The definition is in %s; see `PROVENANCE.md`." % ", ".join("`%s`" % f for f in d.files)]
    return "\n".join(a) + "\n"


def emit_provenance(tag, commit, files, date_read):
    a = ["SPDX licence: Apache-2.0", "",
         "# Provenance", "",
         "Generated by `tools/gen/aplog2pack.py`. No source file is copied into this repository.",
         "The generator reads the message name, format string, labels, units and multipliers",
         "of each log message definition, and the format, unit and multiplier tables; it takes",
         "no comment text. Date read: %s." % date_read, "",
         "| Fact | Value |", "|---|---|",
         "| Repository | %s |" % REPO, "| Tag | `%s` |" % tag, "| Commit | `%s` |" % commit, "",
         "Each file is `https://raw.githubusercontent.com/ArduPilot/ardupilot/<commit>/<path>`.", "",
         "| Path | SHA-256 |", "|---|---|"]
    for rel, sha in files:
        a.append("| `%s` | `%s` |" % (rel, sha))
    a += ["", "## License statements in the repository at that commit", "",
          "`COPYING.txt` at the root is the text of the GNU General Public License, Version 3,",
          "29 June 2007 (GPL-3.0); its first lines are `GNU GENERAL PUBLIC LICENSE` and",
          "`Version 3, 29 June 2007`. `README.md` states: \"The ArduPilot project is licensed",
          "under the GNU General Public License, version 3.\"", "",
          "As for `meshtastic` and `cot-protobuf` (also GPL-3.0 sources), the pack holds the",
          "names, types and layout of the messages, which a log states in its own FMT records,",
          "and no code or comment text. The layouts are restated from that GPL-3.0 source;",
          "the pack is Apache-2.0.", "",
          "No source carries a distribution statement, handling marking, export-control",
          "notice or proprietary notice."]
    return "\n".join(a) + "\n"


def emit_sources_provenance(tag, commit, rels, root, date_read):
    a = ["# Provenance of the ArduPilot inputs of tools/gen/aplog2pack.py", "",
         "Written by `aplog2pack.py --commit`; every later run checks the files against it. The",
         "generator scans every .cpp and .h file of ArduCopter, ArduPlane, Rover, ArduSub,",
         "AntennaTracker and libraries (not tests or examples); the table lists the files a",
         "definition comes from, the format table and the licence files. Date read: %s." % date_read, "",
         "| Fact | Value |", "|---|---|",
         "| Repository | %s |" % REPO, "| Tag | `%s` |" % tag, "| Commit | `%s` |" % commit, "",
         "| Path | SHA-256 |", "|---|---|"]
    for rel in rels:
        a.append("| `%s` | `%s` |" % (rel, sha256_file(os.path.join(root, *rel.split("/")))))
    a += ["", "License: GNU General Public License, version 3 (`COPYING.txt`, `README.md`). See any",
          "`packs/ardupilot-log-*/PROVENANCE.md`."]
    return "\n".join(a) + "\n"


def read_sources_provenance(out):
    text = out.read(PROV_REL)
    tag = re.search(r"^\| Tag \| `([^`]+)` \|$", text, re.M).group(1)
    commit = re.search(r"^\| Commit \| `([0-9a-f]{40})` \|$", text, re.M).group(1)
    shas = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    return tag, commit, shas


def vec(name, src, dst, inp, expect=None, model=None, error=None, source=None):
    v = collections.OrderedDict([("name", name), ("from", src), ("to", dst)])
    if source:
        v["source"] = source
    v["input"] = inp
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    return v


def dump_json(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def model_value(x, v):
    if x.transform in ("f32", "f64"):
        return fmt_float(v)
    return str(v)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def build(args, out):
    root = args.ardupilot
    byname, _ = extract(root)
    units, mults = unit_tables(root)
    packs = plan(byname)
    rels = sorted(set(LICENSE_FILES + [STRUCTURE_H] + [f for p in packs for f in p.d.files]))
    if args.commit:
        out.write(PROV_REL, emit_sources_provenance(args.tag, args.commit, rels, root, args.date_read))
    tag, commit, shas = read_sources_provenance(out)
    for rel in rels:
        if shas.get(rel) != sha256_file(os.path.join(root, *rel.split("/"))):
            fail("%s: SHA-256 is not the one in %s" % (rel, PROV_REL))
    if set(shas) != set(rels):
        fail("%s lists other files than the run reads: %s" % (PROV_REL, sorted(set(shas) ^ set(rels))))
    for name in BOUND:
        if name not in byname:
            fail("bound message %s has no definition" % name)
    if args.compare_xml:
        agree, differ = compare_xml(byname, args.compare_xml)
        print("aplog2pack: %d documented messages agree with parse.py; %d differ" % (agree, len(differ)))
        for v, name, why in differ:
            print("aplog2pack:   %s %s: %s" % (v, name, why))
    names = json.loads(out.read(NAMES_REL)) if out.exists(NAMES_REL) else {}
    namer = Namer(names)
    items_of, decls, seen = {}, [], set()
    for p in packs:
        items = leaves(p, namer)
        items_of[p.format] = items
        for x in items:
            if x.key in ("lat", "lon") or x.key in seen:
                continue
            seen.add(x.key)
            decls.append((x.key, x.keytype, "%s.%s (%s)" % (p.d.name, x.label, describe(x, units, mults))))
    out.write("model/%s.def" % MODULE, emit_module(decls, tag, commit))
    out.write(NAMES_REL, json.dumps(collections.OrderedDict(sorted(namer.names.items())), indent=1) + "\n")
    vectors, lines_of, wanted = [], {}, set()
    same = collections.defaultdict(list)
    for p in packs:
        same[p.d.name].append(p.format)
    for p in packs:
        d, items = p.d, items_of[p.format]
        rel = "packs/" + p.format
        wanted.add(p.format)
        out.write(rel + "/pack.def", emit_pack(p, items, tag, commit))
        files = [(r, shas[r]) for r in LICENSE_FILES + [STRUCTURE_H] + [f for f in d.files if f != STRUCTURE_H]]
        out.write(rel + "/PROVENANCE.md", emit_provenance(tag, commit, files, args.date_read))
        payload, values = serialize(d, Sampler())
        model = collections.OrderedDict()
        for x in items:
            if x.label in values and len(model) < 4:
                v = values[x.label]
                model[qual(x.key)] = model_value(x, v * 1e-7 if x.key in ("lat", "lon") else v)
        vs = [("gen-rt.json", vec("rt-" + p.format, p.format, p.format, payload.hex(), payload.hex(), model,
                                  source="tools/gen/aplog2pack.py: values chosen by the generator, packed by its "
                                         "serializer in format-string order"))]
        bound = {i: k for i, k in bound_fields(d).items()}
        if bound:
            lat, lon = -35.3632621, 149.1652374
            ov = {i: round_away((lat if k == "lat" else lon) * 1e7) for i, k in bound.items()}
            payload2, _ = serialize(d, Sampler(), ov)
            vs.append(("gen-x-to-geojson.json", vec(
                "x-%s-to-geojson" % p.format, p.format, "geojson", payload2.hex(),
                geojson_point(ov[[i for i, k in bound.items() if k == "lat"][0]] / 1e7,
                              ov[[i for i, k in bound.items() if k == "lon"][0]] / 1e7),
                {"lat": "-35.3632621", "lon": "149.1652374"},
                source="Lat and Lng are int32 degrees times 10^7 (pack.md), decoded with sscale:1/10000000; "
                       "geojson writes [lon, lat] (RFC 7946, engine-spec 0.1.1 ruling 4)")))
        cross_from = bool(bound) and d.name in FROM_GEOJSON
        if cross_from:
            buf = bytearray(payload_size(d))
            off = 0
            for i, c in enumerate(d.fmt):
                if i in bound:
                    buf[off:off + 4] = struct.pack("<i", round_away((47.3977419 if bound[i] == "lat" else 8.5455938) * 1e7))
                off += FORMAT[c][0]
            gv = vec("gen-geojson-to-%s" % p.format, "geojson", p.format,
                     '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.5455938,47.3977419,488]},'
                     '"properties":{"callsign":"UAV1"},"id":"u-1"}', bytes(buf).hex(),
                     {"lat": "47.3977419", "lon": "8.5455938"},
                     source="tools/gen/aplog2pack.py: only Lat and Lng have a line bound to geojson keys; "
                            "every other byte is zero (absent fields write nothing)")
            path = "packs/geojson/vectors/gen-geojson-to-%s.json" % p.format
            out.write(path, dump_json(gv))
            vectors.append(path)
        if d.name == "GPS":
            vs.append(("gen-err-short.json", vec(
                "err-short", p.format, p.format, payload.hex()[:-2], error="malformed-wire",
                source="one byte short of the %d-byte payload (vector-format, malformed input)" % payload_size(d))))
        for name in out.listdir(rel + "/vectors"):
            if name.startswith("gen-") and name not in {n for n, _ in vs}:
                out.remove(rel + "/vectors/" + name)
        for name, v in vs:
            out.write(rel + "/vectors/" + name, dump_json(v))
            vectors.append(rel + "/vectors/" + name)
        others = same[d.name] if len(same[d.name]) > 1 else []
        out.write(rel + "/pack.md", emit_pack_md(p, items, units, mults, len(vs), cross_from, others))
        lines_of[p.format] = None
    if os.path.isdir(out.path("packs")):
        for dname in sorted(os.listdir(out.path("packs"))):
            if dname.startswith("ardupilot-log-") and dname not in wanted:
                for sub in ("pack.def", "pack.md", "PROVENANCE.md"):
                    out.remove("packs/%s/%s" % (dname, sub))
                for name in out.listdir("packs/%s/vectors" % dname):
                    out.remove("packs/%s/vectors/%s" % (dname, name))
    # check
    model = gtcheck.Model()
    with open(args.core_def, encoding="utf-8") as fh:
        model.add(fh.read(), "model/core.def")
    model.add(out.read("model/%s.def" % MODULE), "model/%s.def" % MODULE)
    for fmt in lines_of:
        text = out.read("packs/%s/pack.def" % fmt)
        try:
            gtcheck.load_pack(text, model, label="packs/%s/pack.def" % fmt)
        except gtcheck.CheckError as e:
            fail(str(e))
        lines_of[fmt] = read_lines(text)
    for path in vectors:
        check_vector(json.loads(out.read(path)), lines_of, path)
    return len(packs), len(byname), len(decls), len(vectors)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ardupilot", required=True, metavar="DIR", help="an ArduPilot checkout")
    genio.add_arguments(ap)
    ap.add_argument("--commit", help="write tools/gen/sources/%s for this commit (with --tag)" % PROV_NAME)
    ap.add_argument("--tag", help="the release tag of --commit")
    ap.add_argument("--compare-xml", metavar="DIR",
                    help="<DIR>/<Vehicle>/LogMessages.xml as Tools/autotest/logger_metadata/parse.py "
                         "writes them; every documented message is compared with its definition")
    ap.add_argument("--core-def", help="model/core.def (default: <out>/model/core.def)")
    ap.add_argument("--date-read", default="2026-11-19")
    args = ap.parse_args(argv)
    if args.commit and not args.tag:
        ap.error("--commit needs --tag")
    args.core_def = args.core_def or os.path.join(args.out, "model", "core.def")
    out = genio.Output(args.out, check=args.check)
    try:
        npk, nn, nk, nv = build(args, out)
    except GenError as e:
        print("aplog2pack: %s" % e, file=sys.stderr)
        return 1
    print("aplog2pack: %d packs for %d message names, %d keys, %d vectors checked" % (npk, nn, nk, nv))
    return out.report("aplog2pack")


if __name__ == "__main__":
    sys.exit(main())
