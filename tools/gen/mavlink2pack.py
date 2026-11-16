#!/usr/bin/env python3
"""Generate the goat-transformers pack `mavlink2` from the MAVLink XML definitions.

Reads   <root>/sources/{common,standard,minimal}.xml and PROVENANCE.md
Writes  <root>/model/mavlink.def
        <root>/packs/mavlink2/pack.def
        <root>/packs/mavlink2/pack.md
        <root>/packs/mavlink2/vectors/*.json

Python 3 standard library only. Re-runnable: the same inputs give the same
bytes. After writing, the script reads its own output back from disk and checks
it with a second, independent parser and a small bits-wire engine written from
spec/engine-spec.md (Versions 0.2, 0.4, 0.5). Exit status is non-zero when any
check fails.

Usage: mavlink2pack.py [--root DIR] [--core-def PATH/model/core.def]
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
import xml.etree.ElementTree as ET
from decimal import Decimal

FORMAT = "mavlink2"
PACK_VERSION = "0.1.0"
MODULE = "mavlink"
XML_FILES = ["common.xml", "standard.xml", "minimal.xml"]
REPO = "https://github.com/mavlink/mavlink"
XML_DIR = "message_definitions/v1.0"

# MAVLink 2 frame: STX LEN INCOMPAT COMPAT SEQ SYSID COMPID MSGID(3, LE) PAYLOAD CRC(2)
STX = 0xFD
HEADER_BYTES = 10
PAYLOAD_BIT0 = HEADER_BYTES * 8
LOC_STX = (0, 8)
LOC_LEN = (8, 8)
LOC_SEQ = (32, 8)
LOC_SYSID = (40, 8)
LOC_COMPID = (48, 8)
LOC_MSGID = (56, 24)
COMMON_KEYS = [("seq", LOC_SEQ, "frame sequence number of the sending component, 0..255"),
               ("sysid", LOC_SYSID, "system id of the sender"),
               ("compid", LOC_COMPID, "component id of the sender")]

MAX_ARRAY_ELEMENTS = 8        # longer non-char arrays are not mapped
MAX_REQUIRES = 6
DEGE7 = "1/10000000"         # engine-spec 0.5 ruling 1: a power-of-ten scale is a fraction

# The only core keys this pack maps. Overridden by --core-def when given.
CORE_FALLBACK = {"lat": "float", "lon": "float"}

TYPE_RE = re.compile(r"^(char|u?int(?:8|16|32|64)_t|float|double)(?:\[(\d+)\])?$")
SIZES = {"char": 1, "uint8_t": 1, "int8_t": 1, "uint16_t": 2, "int16_t": 2,
         "uint32_t": 4, "int32_t": 4, "float": 4, "uint64_t": 8, "int64_t": 8,
         "double": 8}

# CRC_EXTRA values fixed by the protocol; a wrong field order changes them.
KNOWN_CRC_EXTRA = {"HEARTBEAT": 50, "SYS_STATUS": 124, "ATTITUDE": 39,
                   "GLOBAL_POSITION_INT": 104, "GPS_RAW_INT": 24,
                   "COMMAND_LONG": 152}


class GenError(Exception):
    pass


# ----------------------------------------------------------------- source ---

def read_provenance(src):
    text = open(os.path.join(src, "PROVENANCE.md"), encoding="utf-8").read()
    m = re.search(r"Commit: `([0-9a-f]{40})`", text)
    if not m:
        raise GenError("PROVENANCE.md has no `Commit:` line with a 40-hex SHA")
    for name in XML_FILES:
        row = re.search(r"\| `%s` \|[^|]*\| `([0-9a-f]{64})` \|" % re.escape(name), text)
        if not row:
            raise GenError("PROVENANCE.md has no SHA-256 row for %s" % name)
        got = hashlib.sha256(open(os.path.join(src, name), "rb").read()).hexdigest()
        if got != row.group(1):
            raise GenError("%s does not match the SHA-256 in PROVENANCE.md" % name)
    return m.group(1)


def x25(data, crc=0xFFFF):
    for b in data:
        tmp = b ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


class Field:
    def __init__(self, name, base, n, units, enum, invalid, ext):
        self.name, self.base, self.n = name, base, n   # n is None for a scalar
        self.units, self.enum, self.invalid, self.ext = units, enum, invalid, ext
        self.size = SIZES[base]
        self.bytes = self.size * (n or 1)
        self.offset = None
        self.lines = []          # [(model key, bit pos, bit len, transform)]
        self.status = None       # core | scalar | ascii | elements | unmapped


class Message:
    def __init__(self, name, msgid, fields, file):
        self.name, self.id, self.fields, self.file = name, msgid, fields, file
        self.kind = name.lower()


def load_messages(src):
    msgs, seen_files, order = [], set(), []

    def walk(fname):
        if fname in seen_files:
            return
        seen_files.add(fname)
        root = ET.parse(os.path.join(src, fname)).getroot()
        for inc in root.findall("include"):
            walk(inc.text.strip())
        order.append(fname)
        for m in root.iter("message"):
            fields, ext = [], False
            for ch in m:
                if ch.tag == "extensions":
                    ext = True
                elif ch.tag == "field":
                    t = ch.get("type")
                    if t == "uint8_t_mavlink_version":
                        t = "uint8_t"
                    tm = TYPE_RE.match(t)
                    if not tm:
                        raise GenError("%s.%s: unknown type %s" % (m.get("name"), ch.get("name"), t))
                    n = int(tm.group(2)) if tm.group(2) else None
                    fields.append(Field(ch.get("name"), tm.group(1), n, ch.get("units"),
                                        ch.get("enum"), ch.get("invalid"), ext))
            msgs.append(Message(m.get("name"), int(m.get("id")), fields, fname))

    walk("common.xml")
    if set(order) != set(XML_FILES):
        raise GenError("include chain is %s, expected %s" % (order, XML_FILES))
    ids = collections.Counter(m.id for m in msgs)
    names = collections.Counter(m.name for m in msgs)
    dup = [i for i, c in ids.items() if c > 1] + [n for n, c in names.items() if c > 1]
    if dup:
        raise GenError("duplicate message ids or names: %s" % dup)
    msgs.sort(key=lambda m: m.id)
    return msgs


def lay_out(msg):
    """MAVLink 2 wire order: base fields by descending type size (stable),
    then extension fields in declaration order."""
    base = [f for f in msg.fields if not f.ext]
    ext = [f for f in msg.fields if f.ext]
    base_sorted = sorted(base, key=lambda f: -f.size)       # sorted() is stable
    off = 0
    for f in base_sorted + ext:
        f.offset = off
        off += f.bytes
    msg.wire = base_sorted + ext
    msg.length = off
    if not 0 < off <= 255:
        raise GenError("%s: payload length %d outside 1..255" % (msg.name, off))
    if not 0 <= msg.id < (1 << 24):
        raise GenError("%s: id out of range" % msg.name)
    crc = x25((msg.name + " ").encode())
    for f in base_sorted:
        crc = x25((f.base + " " + f.name + " ").encode(), crc)
        if f.n:
            crc = x25(bytes([f.n]), crc)
    msg.crc_extra = (crc & 0xFF) ^ (crc >> 8)


# ----------------------------------------------------------------- naming ---

def slug(text):
    s = text.lower()
    for a, b in (("%", "pct"), ("/", "_per_"), ("*", "_x"), ("^", "")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def base_key(f):
    name = slug(f.name)
    if f.units:
        u = slug(f.units)
        if u and name != u and not name.endswith("_" + u):
            name = name + "_" + u
    return name


def type_class(f):
    if f.base == "char":
        return "string"
    if f.base in ("float", "double"):
        return "float"
    return "int"


def transform_for(f):
    if f.base == "char":
        return "ascii"
    if f.base == "float":
        return "f32"
    if f.base == "double":
        return "f64"
    return "uint" if f.base.startswith("u") else "twos"


def is_core_latlon(f):
    return (f.name in ("lat", "lon") and f.units == "degE7" and f.base == "int32_t"
            and f.n is None and f.invalid is None)


def assign_keys(msgs):
    """Decide every field's mapping and its model key. Returns the module keys
    in first-appearance order: {name: (type, unit, [(message, field)])}."""
    # pass 1: classify, propose shared names
    proposals = collections.defaultdict(list)     # key name -> [(msg, field, index)]
    for m in msgs:
        # a kind needs a raw key of its own for `requires`; a message whose only
        # mappable fields are lat/lon keeps them raw
        m.core_ok = any(not is_core_latlon(f) and
                        not (f.n is not None and f.base != "char" and f.n > MAX_ARRAY_ELEMENTS)
                        for f in m.wire)
        for f in m.wire:
            if f.n is not None and f.base != "char" and f.n > MAX_ARRAY_ELEMENTS:
                f.status = "unmapped"
            elif is_core_latlon(f) and m.core_ok:
                f.status = "core"
            elif f.n is not None and f.base != "char":
                f.status = "elements"
                for i in range(f.n):
                    proposals["%s_%d" % (base_key(f), i)].append((m, f, i))
            else:
                f.status = "ascii" if f.base == "char" else "scalar"
                proposals[base_key(f)].append((m, f, None))

    # pass 2: a shared name stands only when every use agrees on type class,
    # units and enum, the name is not a common key, and no kind would get it twice
    reserved = {k for k, _, _ in COMMON_KEYS}
    qualified = {}                                # (msg name, field name) -> reason
    for name, uses in proposals.items():
        sigs = {(type_class(f), f.units, f.enum) for _, f, _ in uses}
        per_msg = collections.Counter(m.name for m, _, _ in uses)
        reason = None
        if name in reserved:
            reason = "same name as a frame-header key"
        elif len({s[0] for s in sigs}) > 1:
            reason = "different types"
        elif len({s[1] for s in sigs}) > 1:
            reason = "different units"
        elif len(sigs) > 1:
            reason = "different enums"
        elif max(per_msg.values()) > 1:
            reason = "two fields of one message give the same name"
        if reason:
            for m, f, _ in uses:
                qualified[(m.name, f.name)] = reason

    keys = collections.OrderedDict()

    def declare(name, typ, unit, m, f):
        if name in keys:
            if keys[name][0] != typ or keys[name][1] != unit:
                raise GenError("key %s declared twice with different type or unit" % name)
        else:
            keys[name] = (typ, unit, [])
        if (m.name, f.name) not in keys[name][2]:
            keys[name][2].append((m.name, f.name))

    for m in msgs:
        for f in m.wire:
            pos = PAYLOAD_BIT0 + 8 * f.offset
            if f.status == "unmapped":
                continue
            if f.status == "core":
                f.lines.append((f.name, pos, 32, "sscale:" + DEGE7))
                continue
            stem = base_key(f)
            if (m.name, f.name) in qualified:
                stem = m.kind + "_" + stem
            unit = f.units or "-"
            if f.status == "elements":
                for i in range(f.n):
                    k = "%s_%d" % (stem, i)
                    declare(k, type_class(f), unit, m, f)
                    f.lines.append((MODULE + "." + k, pos + 8 * f.size * i, 8 * f.size,
                                    transform_for(f)))
            else:
                declare(stem, type_class(f), unit, m, f)
                f.lines.append((MODULE + "." + stem, pos, 8 * f.bytes, transform_for(f)))
    for k, _, _ in COMMON_KEYS:
        if k in keys:
            raise GenError("payload key collides with common key %s" % k)
    return keys, qualified


def choose_requires(msgs):
    usage = collections.Counter()
    for m in msgs:
        m.raw_keys = [k for f in m.wire for k, _, _, _ in f.lines if k.startswith(MODULE + ".")]
        usage.update(set(m.raw_keys))
    for m in msgs:
        ranked = sorted(range(len(m.raw_keys)), key=lambda i: (usage[m.raw_keys[i]], i))
        picked = sorted(ranked[:MAX_REQUIRES])
        m.requires = [m.raw_keys[i] for i in picked]
        if not m.requires:
            raise GenError("%s has no raw key to require" % m.name)
    for m in msgs:
        r = set(m.requires)
        m.shadowed_by = [o.name for o in msgs if o is not m and r <= set(o.raw_keys)]


# ---------------------------------------------------------------- emitting ---

def loc(pos, length):
    return "0:%d:%d" % (pos, length)


def emit_model(keys, sha):
    out = ["# The mavlink module: MAVLink fields in their wire units, as raw values.",
           "# Generated by tools/gen/mavlink2pack.py; do not edit by hand.",
           "# A key is shared by every message whose field has that name, type class,",
           "# units and enum; otherwise the key carries its message name.",
           "module        %s" % MODULE,
           "version       %s" % PACK_VERSION,
           "distribution  public"]
    for name in XML_FILES:
        out.append('source        "%s %s/%s at commit %s"' % (REPO, XML_DIR, name, sha))
    out.append('source        "MAVLink 2 packet format, https://mavlink.io/en/guide/serialization.html"')
    for k, _, meaning in COMMON_KEYS:
        out.append('key  %s  int  -  "MAVLink 2 frame header: %s"' % (k, meaning))
    for k, (typ, unit, uses) in keys.items():
        names = [m for m, _ in uses]
        fname = uses[0][1]
        shown = ", ".join(names[:3]) + (" and %d more" % (len(names) - 3) if len(names) > 3 else "")
        out.append('key  %s  %s  %s  "field %s of %s"' % (k, typ, unit, fname, shown))
    return "\n".join(out) + "\n"


def emit_pack(msgs, sha):
    out = ["# MAVLink 2 frames, message set common.xml (with standard.xml, minimal.xml).",
           "# Generated by tools/gen/mavlink2pack.py; do not edit by hand.",
           "# One byte-aligned frame addressed by bit offset from the STX byte:",
           "# STX(8) LEN(8) INCOMPAT(8) COMPAT(8) SEQ(8) SYSID(8) COMPID(8) MSGID(24) PAYLOAD CRC(16).",
           "# Payload starts at bit %d. CRC, INCOMPAT and COMPAT are not mapped." % PAYLOAD_BIT0,
           "format        %s" % FORMAT,
           "version       %s" % PACK_VERSION,
           "distribution  public"]
    for name in XML_FILES:
        out.append('source        "%s %s/%s at commit %s"' % (REPO, XML_DIR, name, sha))
    out.append('source        "MAVLink 2 packet format, https://mavlink.io/en/guide/serialization.html"')
    out += ["uses          %s" % MODULE,
            "wire          bits",
            "bit_order     lsb",
            "word_bytes    1",
            "when   %s %d" % (loc(*LOC_STX), STX)]
    for k, l, _ in COMMON_KEYS:
        out.append("field  %s.%s %s uint" % (MODULE, k, loc(*l)))
    for m in msgs:
        out.append("")
        out.append("kind      %s" % m.kind)
        out.append("when      %s %d" % (loc(*LOC_MSGID), m.id))
        out.append("when      %s %d" % (loc(*LOC_LEN), m.length))
        out.append("requires  %s" % " ".join(m.requires))
        for f in m.wire:
            for key, pos, length, tr in f.lines:
                out.append("field     %s %s %s" % (key, loc(pos, length), tr))
    return "\n".join(out) + "\n"


# ------------------------------------------------- independent pack reader ---

YIELDS = {"uint": "int", "twos": "int", "f32": "float", "f64": "float", "ascii": "string",
          "uscale": "float", "sscale": "float", "linscale": "float"}
LOC_RE = re.compile(r"^(\d+):(\d+):(\d+)$")
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def tokens(line):
    """Whitespace-separated tokens; `#` starts a comment only at token start;
    double quotes wrap a value that contains whitespace."""
    out, i, n = [], 0, len(line)
    while i < n:
        if line[i].isspace():
            i += 1
        elif line[i] == "#":
            break
        elif line[i] == '"':
            j = line.find('"', i + 1)
            if j < 0:
                raise GenError("unterminated quote: " + line)
            out.append(line[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and not line[j].isspace():
                j += 1
            out.append(line[i:j])
            i = j
    return out


def parse_model(text):
    mod = {"keys": {}, "name": None, "dist": None, "sources": 0}
    for ln, line in enumerate(text.splitlines(), 1):
        t = tokens(line)
        if not t:
            continue
        d, a = t[0], t[1:]
        if d == "module" and len(a) == 1:
            mod["name"] = a[0]
        elif d == "version" and len(a) == 1 and re.match(r"^\d+\.\d+\.\d+$", a[0]):
            pass
        elif d == "distribution" and len(a) == 1 and a[0] in ("public", "controlled"):
            mod["dist"] = a[0]
        elif d == "source" and len(a) == 1:
            mod["sources"] += 1
        elif d == "key" and len(a) in (3, 4):
            if not KEY_RE.match(a[0]) or a[1] not in ("string", "float", "int"):
                raise GenError("model line %d: bad key or type" % ln)
            if a[0] in mod["keys"]:
                raise GenError("model line %d: duplicate-key %s" % (ln, a[0]))
            mod["keys"][a[0]] = a[1]
        else:
            raise GenError("model line %d: bad directive: %s" % (ln, line))
    if not mod["name"] or not mod["dist"] or not mod["sources"]:
        raise GenError("model lacks module, distribution or source")
    return mod


def parse_transform(tr, length, where):
    parts = tr.split(":")
    name = parts[0]
    if name not in YIELDS or name == "linscale":
        raise GenError("%s: transform %s not valid here" % (where, tr))
    if name in ("uscale", "sscale"):
        if len(parts) not in (2, 3):
            raise GenError("%s: bad %s" % (where, tr))
        num_re = r"^-?\d+(\.\d+)?$"
        frac = re.match(r"^(-?\d+)/(\d+)$", parts[1])
        if not (frac or re.match(num_re, parts[1])) or not all(re.match(num_re, p) for p in parts[2:]):
            raise GenError("%s: bad number in %s" % (where, tr))
        off = float(parts[2]) if len(parts) == 3 else 0.0
        if frac:
            if int(frac.group(1)) == 0 or int(frac.group(2)) == 0:
                raise GenError("%s: zero in fraction" % where)
            return name, ("frac", int(frac.group(1)), int(frac.group(2)), off)
        if float(parts[1]) == 0:
            raise GenError("%s: zero factor" % where)
        return name, ("mul", float(parts[1]), None, off)
    elif len(parts) != 1:
        raise GenError("%s: %s takes no argument" % (where, tr))
    if name == "f32" and length != 32:
        raise GenError("%s: f32 needs len 32" % where)
    if name == "f64" and length != 64:
        raise GenError("%s: f64 needs len 64" % where)
    if name == "ascii":
        if length % 8 or not 8 <= length <= 2040:
            raise GenError("%s: ascii len %d" % (where, length))
    elif not 1 <= length <= 64:
        raise GenError("%s: len %d outside 1..64" % (where, length))
    return name, [float(p) for p in parts[1:]]


def parse_pack(text):
    """Read pack.def text into {head, common, kinds}. Checks the grammar."""
    pack = {"head": {}, "uses": [], "sources": 0,
            "common": {"when": [], "fields": []}, "kinds": collections.OrderedDict()}
    cur = pack["common"]
    for ln, line in enumerate(text.splitlines(), 1):
        t = tokens(line)
        if not t:
            continue
        d, a = t[0], t[1:]
        where = "pack line %d" % ln
        if d in ("format", "version", "wire", "bit_order", "word_bytes", "distribution"):
            if len(a) != 1 or d in pack["head"]:
                raise GenError(where + ": bad or repeated " + d)
            pack["head"][d] = a[0]
        elif d == "source" and len(a) == 1:
            pack["sources"] += 1
        elif d == "uses" and len(a) == 1:
            pack["uses"].append(a[0])
        elif d == "kind" and len(a) == 1:
            if a[0] in pack["kinds"]:
                raise GenError(where + ": duplicate-kind " + a[0])
            if not re.match(r"^[a-z0-9_]+$", a[0]):
                raise GenError(where + ": bad kind name")
            cur = {"when": [], "fields": [], "requires": []}
            pack["kinds"][a[0]] = cur
        elif d == "when" and len(a) == 2:
            lm = LOC_RE.match(a[0])
            if not lm or not a[1].isdigit():
                raise GenError(where + ": bad when")
            w, p, l = (int(x) for x in lm.groups())
            if not 1 <= l <= 64 or int(a[1]) >= (1 << l):
                raise GenError(where + ": when value does not fit")
            cur["when"].append((w, p, l, int(a[1])))
        elif d == "requires" and a:
            if cur is pack["common"]:
                raise GenError(where + ": bad-directive requires before first kind")
            cur["requires"] += a
        elif d == "field" and len(a) == 3:
            lm = LOC_RE.match(a[1])
            if not lm:
                raise GenError(where + ": bad locator " + a[1])
            w, p, l = (int(x) for x in lm.groups())
            name, args = parse_transform(a[2], l, where)
            cur["fields"].append((a[0], w, p, l, name, args))
        else:
            raise GenError(where + ": bad directive: " + line)
    h = pack["head"]
    for need in ("format", "version", "wire", "word_bytes", "distribution"):
        if need not in h:
            raise GenError("pack lacks " + need)
    if h["wire"] != "bits" or h.get("bit_order", "lsb") != "lsb" or h["word_bytes"] != "1":
        raise GenError("this checker reads only wire bits, bit_order lsb, word_bytes 1")
    if not pack["sources"]:
        raise GenError("missing-source")
    return pack


def check_pack(pack, modules):
    """Version 0.4 and 0.5 load checks, plus the frame checks of this pack."""
    if pack["head"]["distribution"] == "public":
        for u in pack["uses"]:
            if u not in modules:
                raise GenError("unknown-module " + u)
            if modules[u]["dist"] != "public":
                raise GenError("distribution-violation " + u)

    def key_type(key, where):
        mod, name = key.split(".", 1) if "." in key else ("core", key)
        if mod not in modules:
            raise GenError("%s: unknown-module %s" % (where, mod))
        if mod != "core" and mod not in pack["uses"]:
            raise GenError("%s: module-not-used %s" % (where, mod))
        if name not in modules[mod]["keys"]:
            raise GenError("%s: undeclared-key %s" % (where, key))
        return modules[mod]["keys"][name]

    def span(fields, whens):
        return [(w * 8 + p, w * 8 + p + l) for _, w, p, l, _, _ in fields] + \
               [(w * 8 + p, w * 8 + p + l) for w, p, l, _ in whens]

    common = pack["common"]
    if (0, 0, 8, STX) not in common["when"]:
        raise GenError("common `when` on STX missing")
    for kname, k in pack["kinds"].items():
        where = "kind " + kname
        seen = set()
        for key, w, p, l, tr, _ in common["fields"] + k["fields"]:
            if key in seen:
                raise GenError("%s: duplicate-field %s" % (where, key))
            seen.add(key)
            if key_type(key, where) != YIELDS[tr]:
                raise GenError("%s: key-type-mismatch %s via %s" % (where, key, tr))
        if not k["requires"]:
            raise GenError(where + ": no requires")
        for key in k["requires"]:
            key_type(key, where)
            if key not in {f[0] for f in k["fields"]}:
                raise GenError("%s: requires %s which the kind does not map" % (where, key))
        ids = [v for w, p, l, v in k["when"] if (w * 8 + p, l) == LOC_MSGID]
        lens = [v for w, p, l, v in k["when"] if (w * 8 + p, l) == LOC_LEN]
        if len(ids) != 1 or len(lens) != 1 or len(k["when"]) != 2:
            raise GenError(where + ": needs exactly one MSGID when and one LEN when")
        end = PAYLOAD_BIT0 + 8 * lens[0]
        taken = sorted(span(common["fields"] + k["fields"], common["when"] + k["when"]))
        for (a0, a1), (b0, b1) in zip(taken, taken[1:]):
            if b0 < a1:
                raise GenError("%s: bit ranges overlap at %d" % (where, b0))
        for a0, a1 in span(k["fields"], []):
            if a0 < PAYLOAD_BIT0 or a1 > end:
                raise GenError("%s: field bits %d..%d outside the payload" % (where, a0, a1))
            if a0 % 8 or a1 % 8:
                raise GenError("%s: field not byte aligned" % where)
    pairs = [tuple(sorted(k["when"])) for k in pack["kinds"].values()]
    if len(set(pairs)) != len(pairs):
        raise GenError("two kinds have the same `when` set")


# --------------------------------------------- small engine, from the spec ---

def round_away(x):
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def fmt_float(x):
    """Shortest round-trip decimal, plain notation, integers without a point."""
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 1e17:
        return str(int(x))
    r = repr(x)
    return format(Decimal(r), "f") if "e" in r or "E" in r else r


def get_bits(data, pos, length):
    return (int.from_bytes(data, "little") >> pos) & ((1 << length) - 1)


def message_bytes(lines_fields, lines_when):
    top = max([w * 8 + p + l for _, w, p, l, _, _ in lines_fields] +
              [w * 8 + p + l for w, p, l, _ in lines_when])
    return (top + 7) // 8


def engine_decode(pack, data):
    c = pack["common"]
    def holds(whens):
        return all(w * 8 + p + l <= 8 * len(data) and get_bits(data, w * 8 + p, l) == v
                   for w, p, l, v in whens)
    if not holds(c["when"]):
        raise GenError("no-kind")
    for kname, k in pack["kinds"].items():
        if holds(k["when"]):
            break
    else:
        raise GenError("no-kind")
    fields = c["fields"] + k["fields"]
    if len(data) < message_bytes(fields, c["when"] + k["when"]):
        raise GenError("malformed-wire")
    ent = collections.OrderedDict()
    for key, w, p, l, tr, args in fields:
        v = get_bits(data, w * 8 + p, l)
        if tr == "uint":
            # ruling 2: a 64-bit field with the top bit set is the negative integer
            ent[key] = v - (1 << 64) if l == 64 and v >> 63 else v
        elif tr == "twos":
            ent[key] = v - (1 << l) if v >> (l - 1) else v
        elif tr in ("uscale", "sscale"):
            if tr == "sscale" and v >> (l - 1):
                v -= 1 << l
            mode, a, b, off = args          # ruling 1: v * num / den, then + offset
            ent[key] = (v * float(a) / float(b) if mode == "frac" else v * a) + off
        elif tr == "f32":
            ent[key] = struct.unpack("<f", v.to_bytes(4, "little"))[0]
        elif tr == "f64":
            ent[key] = struct.unpack("<d", v.to_bytes(8, "little"))[0]
        elif tr == "ascii":
            raw = v.to_bytes(l // 8, "little").rstrip(b"\0")
            if any(b < 0x20 or b > 0x7E for b in raw):
                raise GenError("transform-decode ascii")
            ent[key] = raw.decode("ascii")
    return kname, ent


def engine_encode(pack, kname, ent):
    c, k = pack["common"], pack["kinds"][kname]
    fields = c["fields"] + k["fields"]
    whens = c["when"] + k["when"]
    acc = 0
    for key, w, p, l, tr, args in fields:
        if key not in ent:
            continue
        x = ent[key]
        if tr in ("uint", "twos"):
            v = x & ((1 << l) - 1)
        elif tr in ("uscale", "sscale"):
            mode, a, b, off = args          # ruling 1: (x - offset) * den / num
            n = round_away((x - off) * float(b) / float(a) if mode == "frac" else (x - off) / a)
            lo, hi = (0, (1 << l) - 1) if tr == "uscale" else (-(1 << (l - 1)), (1 << (l - 1)) - 1)
            if not lo <= n <= hi:
                raise GenError("transform-encode")
            v = n & ((1 << l) - 1)
        elif tr == "f32":
            v = int.from_bytes(struct.pack("<f", x), "little")
        elif tr == "f64":
            v = int.from_bytes(struct.pack("<d", x), "little")
        elif tr == "ascii":
            raw = x.encode("ascii")
            if len(raw) > l // 8:
                raise GenError("transform-encode ascii")
            v = int.from_bytes(raw.ljust(l // 8, b"\0"), "little")
        acc |= v << (w * 8 + p)
    for w, p, l, v in whens:
        acc |= v << (w * 8 + p)
    return acc.to_bytes(message_bytes(fields, whens), "little")


def geojson_encode(ent):
    """Canonical GeoJSON for an entity that holds no geojson key but lat/lon
    (engine-spec 0.1.1 rulings 3-5; packs/geojson/pack.def)."""
    if "lat" in ent and "lon" in ent:
        geom = '{"type":"Point","coordinates":[%s,%s]}' % (fmt_float(ent["lon"]), fmt_float(ent["lat"]))
    else:
        geom = "null"
    return '{"type":"Feature","geometry":%s,"properties":{}}' % geom


# ------------------------------------------------------------------ vectors ---

def sample_value(f, salt):
    """A value inside the field's range that survives decode then encode."""
    if f.base == "char":
        return ("M%d" % (salt % 97))[:f.n]
    if f.base == "float":
        return ((salt % 41) - 20) * 0.25
    if f.base == "double":
        return ((salt % 2001) - 1000) * 0.125
    bits = 8 * f.size
    if f.base.startswith("u"):
        v = (salt * 2654435761 + 12345) % min(1 << bits, 1 << 31)
        if bits == 64 and salt % 2:
            v |= 1 << 63               # ruling 2: top bit set must round-trip
        return v
    span = min(1 << bits, 1 << 31)
    return (salt * 40503 + 7) % span - span // 2


def pack_scalar(f, v):
    if f.base == "char":
        return v.encode("ascii").ljust(f.n, b"\0")
    code = {"uint8_t": "B", "int8_t": "b", "uint16_t": "H", "int16_t": "h",
            "uint32_t": "I", "int32_t": "i", "uint64_t": "Q", "int64_t": "q",
            "float": "f", "double": "d"}[f.base]
    return struct.pack("<" + code, v)


def build_payload(msg, values):
    """values: {field name: scalar | list}. Unnamed fields are zero."""
    unknown = set(values) - {f.name for f in msg.wire}
    if unknown:
        raise GenError("%s has no field %s" % (msg.name, sorted(unknown)))
    out = b""
    for f in msg.wire:
        if f.name not in values:
            out += bytes(f.bytes)
        elif f.n is not None and f.base != "char":
            out += b"".join(pack_scalar(f, v) for v in values[f.name])
        else:
            out += pack_scalar(f, values[f.name])
    assert len(out) == msg.length
    return out


def frame(msg, payload, seq, sysid, compid, with_crc):
    head = bytes([STX, msg.length, 0, 0, seq, sysid, compid]) + msg.id.to_bytes(3, "little")
    body = head + payload
    if with_crc:
        crc = x25(body[1:] + bytes([msg.crc_extra]))
        body += struct.pack("<H", crc)
    return body


def model_strings(kname, ent):
    out = collections.OrderedDict([("@kind", kname)])
    for k, v in ent.items():
        out[k] = fmt_float(v) if isinstance(v, float) else str(v)
    return out


def roundtrip_vector(msg, index):
    values = {}
    for j, f in enumerate(msg.wire):
        salt = msg.id * 31 + j * 7 + 3
        if f.status == "unmapped":
            continue                       # bits no field maps stay zero
        if f.status == "core":
            values[f.name] = {"lat": 1, "lon": -1}[f.name] * (100000000 + 1250000 * (msg.id % 37))
        elif f.status == "elements":
            values[f.name] = [sample_value(f, salt + i) for i in range(f.n)]
        else:
            values[f.name] = sample_value(f, salt)
    payload = build_payload(msg, values)
    # the encoder writes whole bytes up to the last mapped bit and no CRC
    last = max((f.offset + f.bytes for f in msg.wire if f.status != "unmapped"), default=0)
    data = frame(msg, payload[:last], index % 256, 1 + msg.id % 250, 1 + msg.id % 191, False)
    return data


# Five cross-format cases. `expect` is written by hand from the field values:
# lat and lon are int32 degE7, so degrees = value / 10^7; GeoJSON coordinates
# are [lon, lat]; geojson carries no other key this pack maps, so `properties`
# is empty. The generator checks each against its own engine.
CROSS = [
    ("GLOBAL_POSITION_INT", 7, 1, 1,
     {"time_boot_ms": 123456, "lat": 473977420, "lon": 85455940, "alt": 488100,
      "relative_alt": 12500, "vx": 150, "vy": -75, "vz": 10, "hdg": 9000},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.545594,47.397742]},"properties":{}}'),
    ("GPS_RAW_INT", 8, 1, 1,
     {"time_usec": 1700000000000000, "fix_type": 3, "lat": -338568000, "lon": 1512153000,
      "alt": 58000, "eph": 120, "epv": 180, "vel": 0, "cog": 0, "satellites_visible": 11},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[151.2153,-33.8568]},"properties":{}}'),
    ("GPS2_RAW", 9, 1, 1,
     {"time_usec": 5000000, "fix_type": 3, "lat": 515007000, "lon": -1246000,
      "alt": 35000, "satellites_visible": 9},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[-0.1246,51.5007]},"properties":{}}'),
    ("HIL_GPS", 10, 42, 200,
     {"time_usec": 1000000, "fix_type": 3, "lat": 0, "lon": -1800000000, "alt": 0,
      "satellites_visible": 7},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[-180,0]},"properties":{}}'),
    ("UTM_GLOBAL_POSITION", 11, 3, 1,
     {"time": 1700000000000000, "lat": 356762000, "lon": 1396503000, "alt": 40000,
      "relative_alt": 5000, "flight_state": 3},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[139.6503,35.6762]},"properties":{}}'),
]


def write_vectors(msgs, vec_dir):
    os.makedirs(vec_dir, exist_ok=True)
    for old in os.listdir(vec_dir):
        if old.endswith(".json"):
            os.remove(os.path.join(vec_dir, old))
    by_name = {m.name: m for m in msgs}
    count = 0
    for i, m in enumerate(msgs):
        data = roundtrip_vector(m, i)
        vec = collections.OrderedDict([
            ("name", "roundtrip-%s" % m.kind), ("from", FORMAT), ("to", FORMAT),
            ("input", data.hex()), ("expect", data.hex()),
            ("model", {"@kind": m.kind})])
        with open(os.path.join(vec_dir, "rt-%05d-%s.json" % (m.id, m.kind)), "w", encoding="utf-8") as fh:
            json.dump(vec, fh, indent=2)
            fh.write("\n")
        count += 1
    for n, (name, seq, sysid, compid, values, expect) in enumerate(CROSS, 1):
        m = by_name[name]
        data = frame(m, build_payload(m, values), seq, sysid, compid, True)
        model = collections.OrderedDict([("@kind", m.kind),
                                         ("lat", fmt_float(values["lat"] * 1.0 / 10000000.0)),
                                         ("lon", fmt_float(values["lon"] * 1.0 / 10000000.0)),
                                         (MODULE + ".seq", str(seq)),
                                         (MODULE + ".sysid", str(sysid)),
                                         (MODULE + ".compid", str(compid))])
        vec = collections.OrderedDict([
            ("name", "%s-to-geojson" % m.kind), ("from", FORMAT), ("to", "geojson"),
            ("input", data.hex()), ("expect", expect), ("model", model)])
        with open(os.path.join(vec_dir, "x-%02d-%s-to-geojson.json" % (n, m.kind)), "w", encoding="utf-8") as fh:
            json.dump(vec, fh, indent=2)
            fh.write("\n")
        count += 1
    return count


def check_vectors(pack, vec_dir):
    names, kinds_seen, n = set(), set(), 0
    for fn in sorted(os.listdir(vec_dir)):
        vec = json.load(open(os.path.join(vec_dir, fn), encoding="utf-8"))
        if vec["name"] in names:
            raise GenError("duplicate vector name " + vec["name"])
        names.add(vec["name"])
        data = bytes.fromhex(vec["input"])
        kname, ent = engine_decode(pack, data)
        for k, want in vec.get("model", {}).items():
            if k == "@kind":
                if want != kname:
                    raise GenError("%s: decoded kind %s, vector says %s" % (fn, kname, want))
            elif isinstance(ent[k], float):
                if abs(ent[k] - float(want)) > 1e-9:
                    raise GenError("%s: model %s" % (fn, k))
            elif str(ent[k]) != want:
                raise GenError("%s: model %s" % (fn, k))
        if vec["to"] == FORMAT:
            got = engine_encode(pack, kname, ent).hex()
            kinds_seen.add(kname)
        elif vec["to"] == "geojson":
            got = geojson_encode(ent)
        else:
            raise GenError(fn + ": unknown target")
        if got != vec["expect"]:
            raise GenError("%s: convert gives\n  %s\nvector expects\n  %s" % (fn, got, vec["expect"]))
        n += 1
    missing = set(pack["kinds"]) - kinds_seen
    if missing:
        raise GenError("kinds with no round-trip vector: %s" % sorted(missing))
    return n


# ------------------------------------------------------------------ pack.md ---

def emit_pack_md(msgs, keys, qualified, stats, sha):
    core = [m for m in msgs if any(f.status == "core" for f in m.wire)]
    unmapped = [(m, f) for m in msgs for f in m.wire if f.status == "unmapped"]
    short = [m for m in msgs if m.mapped_len < m.length]
    shadow = [m for m in msgs if m.shadowed_by]
    raw_latlon = [(m, f) for m in msgs for f in m.wire
                  if f.units == "degE7" and f.status != "core" and m.core_ok]
    reasons = collections.Counter(qualified.values())
    o = []
    a = o.append
    a("# Pack: mavlink2")
    a("")
    a("MAVLink 2 frames carrying the `common.xml` message set (with the files it")
    a("includes, `standard.xml` and `minimal.xml`). Public. Generated by")
    a("`tools/gen/mavlink2pack.py` from `%s` at commit `%s`;" % (REPO, sha))
    a("do not edit `pack.def`, `model/mavlink.def`, this file or the vectors by hand.")
    a("I/O is hex text (`spec/engine-spec.md`, bits wire).")
    a("")
    a("Status: Built. Generated and checked by the generator's own reader; every engine")
    a("runs every vector in `vectors/` in the conformance suite.")
    a("")
    a("## Layout")
    a("")
    a("`wire bits`, `bit_order lsb`, `word_bytes 1`. A locator is `0:<bit offset>:<len>`")
    a("counted from the first bit of the STX byte.")
    a("")
    a("| Part | Bytes | Locator | In the pack |")
    a("|---|---|---|---|")
    a("| STX | 1 | `0:0:8` | common `when` = 253 (0xFD) |")
    a("| LEN | 1 | `0:8:8` | per-kind `when` = full payload length |")
    a("| INCOMPAT | 1 | `0:16:8` | not mapped |")
    a("| COMPAT | 1 | `0:24:8` | not mapped |")
    a("| SEQ | 1 | `0:32:8` | `mavlink.seq` |")
    a("| SYSID | 1 | `0:40:8` | `mavlink.sysid` |")
    a("| COMPID | 1 | `0:48:8` | `mavlink.compid` |")
    a("| MSGID | 3, little-endian | `0:56:24` | per-kind `when` = message id |")
    a("| PAYLOAD | LEN | from `0:80` | the kind's `field` lines |")
    a("| CRC | 2 | after the payload | not mapped |")
    a("")
    a("One `kind` per message, named by the message name in lower case, in message-id")
    a("order. Payload fields sit at their MAVLink 2 wire offsets: base fields in")
    a("descending type-size order (stable), then extension fields in declaration order.")
    a("The generator confirms its field order by computing each message's CRC_EXTRA and")
    a("comparing six of them with the values the protocol fixes.")
    a("")
    a("## Numbers")
    a("")
    a("| | Count |")
    a("|---|---|")
    a("| Messages in the source (common %d, standard %d, minimal %d) | %d |" % (
        stats["per_file"]["common.xml"], stats["per_file"]["standard.xml"],
        stats["per_file"]["minimal.xml"], len(msgs)))
    a("| Kinds | %d |" % len(msgs))
    a("| Payload fields in the source | %d |" % stats["fields"])
    a("| Payload fields mapped | %d |" % stats["mapped"])
    a("| ... scalar to a raw `mavlink.` key | %d |" % stats["scalar"])
    a("| ... `char[n]` to a string key (`ascii`) | %d |" % stats["ascii"])
    a("| ... array of 2 to %d elements, one key per element | %d (%d element lines) |" % (
        MAX_ARRAY_ELEMENTS, stats["elements"], stats["element_lines"]))
    a("| ... `lat` / `lon` in degE7 to core `lat` / `lon` | %d |" % stats["core"])
    a("| Payload fields not mapped (arrays of more than %d elements) | %d |" % (
        MAX_ARRAY_ELEMENTS, stats["unmapped"]))
    a("| `field` lines in `pack.def` (3 common + per kind) | %d |" % stats["field_lines"])
    a("| Keys in module `mavlink` (3 frame-header + payload) | %d |" % (len(keys) + 3))
    a("| Vectors (%d same-format round trips + %d to geojson) | %d |" % (
        len(msgs), len(CROSS), len(msgs) + len(CROSS)))
    a("")
    a("## What is mapped")
    a("")
    a("| MAVLink type | Transform | Model type |")
    a("|---|---|---|")
    a("| `uint8_t` `uint16_t` `uint32_t` `uint64_t` | `uint` | int |")
    a("| `int8_t` `int16_t` `int32_t` `int64_t` | `twos` | int |")
    a("| `float` | `f32` | float |")
    a("| `double` | `f64` | float |")
    a("| `char[n]` | `ascii` over `8n` bits | string |")
    a("| other `type[n]`, n of 2 to %d | one line per element, keys `…_0`, `…_1`, … | as the element |" % MAX_ARRAY_ELEMENTS)
    a("| `int32_t` degE7 named `lat` or `lon`, with no `invalid` value declared | `sscale:%s` | float, core `lat` / `lon` |" % DEGE7)
    a("")
    a("Every other value is raw: the integer or float on the wire, in the unit the")
    a("definition states, which `model/mavlink.def` records in the key's unit column.")
    a("")
    a("### Key names")
    a("")
    a("A key is `mavlink.<field name>` with the unit appended when the field declares")
    a("one and the name does not already end with it (`mavlink.alt_mm`,")
    a("`mavlink.time_boot_ms`). Unit text is lower-cased; `/` becomes `_per_`, `%`")
    a("becomes `pct`, `*` becomes `_x`. One key is shared by every message whose field")
    a("has that name with the same type class (int, float, string), units and enum.")
    a("When the uses of a name disagree, every use takes the message name as a prefix")
    a("(`mavlink.<message>_<field>…`). %d fields are named that way:" % len(qualified))
    a("")
    a("| Reason | Fields |")
    a("|---|---|")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        a("| %s | %d |" % (r, c))
    a("")
    a("### Core keys")
    a("")
    a("%d kinds map core `lat` and `lon`: %s." % (len(core), ", ".join("`%s`" % m.kind for m in core)))
    a("The position is the one the message reports, which is not always the sending")
    a("vehicle's: `terrain_request`, `terrain_data` and `terrain_report`")
    a("carry a terrain grid point, `follow_target` a target, `camera_image_captured` the")
    a("camera at capture time.")
    nocore = [m for m in msgs if not m.core_ok]
    if nocore:
        a("%s has no field but `lat` and `lon`; they stay raw there so the kind has a raw" % ", ".join("`%s`" % m.kind for m in nocore))
        a("key to require, otherwise any entity with a position would encode as that kind.")
    a("")
    a("Left raw on purpose:")
    a("")
    a("- degE7 fields that are not named `lat` / `lon` or that declare an `invalid`")
    a("  value (%d fields, for example `latitude`, `lat_int`, and `lat` of `adsb_vehicle`," % len(raw_latlon))
    a("  `ais_vessel`, `global_position_sensor`, where INT32_MAX means unknown and would")
    a("  decode to 214.7483647 degrees).")
    a("- UTC epoch times in microseconds (`time_unix_usec`, `time_usec`, `time_utc`):")
    a("  core `time_ms` is an integer and the only scaling transforms yield float; a")
    a("  64-bit microsecond count scaled by 0.001 is not exact in a double.")
    a("- Altitude. MAVLink `alt` fields are above mean sea level; core `hae` is above")
    a("  the WGS84 ellipsoid.")
    a("- Speed, course, heading and velocity components (`vel`, `cog`, `hdg`, `vx`…):")
    a("  the reference frame is in the description text, not in the units, and most")
    a("  declare an `invalid` value (UINT16_MAX).")
    a("")
    a("### `requires`")
    a("")
    a("Each kind requires up to %d of its own raw keys, the ones used by the fewest" % MAX_REQUIRES)
    a("kinds, so encoding an entity that came from another format selects a kind only")
    a("when the entity holds those `mavlink.` keys. No kind requires a core key, so a")
    a("GeoJSON or CoT entity selects no kind (`no-kind`).")
    if shadow:
        a("For %d kinds the required keys are all shared with at least one other kind" % len(shadow))
        a("that maps every one of them; an entity built from such a kind's keys with its")
        a("kind cleared selects the first qualifying kind in id order: %s." % ", ".join(
            "`%s`" % m.kind for m in shadow))
    a("")
    a("## What is not mapped")
    a("")
    a("- CRC (2 bytes after the payload), INCOMPAT and COMPAT flags, and the 13-byte")
    a("  signature of a signed frame.")
    a("- %d array fields of more than %d elements (%d bytes of payload in total):" % (
        len(unmapped), MAX_ARRAY_ELEMENTS, sum(f.bytes for _, f in unmapped)))
    a("")
    a("| Message | Field | Type |")
    a("|---|---|---|")
    for m, f in unmapped:
        a("| %s | %s | `%s[%d]` |" % (m.name, f.name, f.base, f.n))
    a("")
    a("## Known limits")
    a("")
    a("- **Truncated payloads.** MAVLink 2 senders drop trailing zero bytes of the")
    a("  payload and set LEN to the shorter length. Each kind matches only LEN = the")
    a("  full length, so a truncated frame decodes as `no-kind`. Reading one needs the")
    a("  future framed-binary wire (a length-prefixed payload that is zero-extended).")
    a("- **CRC.** Decode does not verify the checksum and encode does not write it.")
    a("  Encode output is the header and payload up to the last mapped byte; it is not")
    a("  a transmittable frame until a framer adds truncation and the CRC (with the")
    a("  message's CRC_EXTRA). Input that carries the CRC or a signature decodes: bytes")
    a("  after the last mapped bit are ignored.")
    a("- **Short output.** In %d kinds the payload ends in unmapped array fields, so" % len(short))
    a("  encode output is shorter than `10 + LEN` bytes: %s." % ", ".join("`%s`" % m.kind for m in short))
    a("- **Unmapped bits do not round-trip.** The bits wire has no residue: INCOMPAT,")
    a("  COMPAT and unmapped arrays are written as zero.")
    a("- **`invalid` values.** A field's `invalid` attribute (a value that means")
    a("  unknown) is not interpreted; the key holds the number.")
    a("- **Text.** `ascii` refuses bytes outside 0x20..0x7E, so a `char[n]` field that")
    a("  holds UTF-8 or binary data fails to decode. Trailing NULs are dropped; an")
    a("  all-NUL field is the empty string, present.")
    a("- **`uint64_t`** is mapped with `uint` to the model type int; a value of 2^63 or")
    a("  above is the negative model integer with the same bits (engine-spec 0.5, ruling 2).")
    a("- **Enums and bitmasks** are carried as their integer.")
    a("")
    a("## Vectors")
    a("")
    a("`vectors/rt-<id>-<kind>.json`: one same-format round trip per kind. The input")
    a("is the frame as the encoder writes it (no CRC, unmapped arrays absent or zero),")
    a("so input and expected output are identical. Values are inside each field's")
    a("range; floats are multiples of 0.25 or 0.125; every other `uint64_t` sample has")
    a("its top bit set.")
    a("")
    a("`vectors/x-NN-<kind>-to-geojson.json`: %d full frames with a correct CRC," % len(CROSS))
    a("converted to GeoJSON. Expected output: `coordinates` = `[lon, lat]` in degrees")
    a("(wire value / 10^7), `properties` empty because `geojson` carries no other key")
    a("this pack maps.")
    return "\n".join(o) + "\n"


# --------------------------------------------------------------------- main ---

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("--core-def", help="path to model/core.def of goat-transformers")
    args = ap.parse_args()
    root = args.root
    src = os.path.join(root, "sources")

    sha = read_provenance(src)
    msgs = load_messages(src)
    for m in msgs:
        lay_out(m)
    for name, want in KNOWN_CRC_EXTRA.items():
        got = [m.crc_extra for m in msgs if m.name == name]
        if got != [want]:
            raise GenError("CRC_EXTRA of %s is %s, protocol value is %d" % (name, got, want))
    keys, qualified = assign_keys(msgs)
    choose_requires(msgs)
    for m in msgs:
        m.mapped_len = max((f.offset + f.bytes for f in m.wire if f.status != "unmapped"), default=0)

    model_text = emit_model(keys, sha)
    pack_text = emit_pack(msgs, sha)
    model_path = os.path.join(root, "model", MODULE + ".def")
    pack_dir = os.path.join(root, "packs", FORMAT)
    vec_dir = os.path.join(pack_dir, "vectors")
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    os.makedirs(pack_dir, exist_ok=True)
    with open(model_path, "w", encoding="utf-8") as fh:
        fh.write(model_text)
    with open(os.path.join(pack_dir, "pack.def"), "w", encoding="utf-8") as fh:
        fh.write(pack_text)
    n_vec = write_vectors(msgs, vec_dir)

    # ---- self-check, from the files on disk
    modules = {MODULE: parse_model(open(model_path, encoding="utf-8").read())}
    if args.core_def:
        modules["core"] = parse_model(open(args.core_def, encoding="utf-8").read())
    else:
        modules["core"] = {"keys": dict(CORE_FALLBACK), "dist": "public"}
    pack = parse_pack(open(os.path.join(pack_dir, "pack.def"), encoding="utf-8").read())
    check_pack(pack, modules)
    if list(pack["kinds"]) != [m.kind for m in msgs]:
        raise GenError("kinds on disk differ from the source messages")
    for m in msgs:
        k = pack["kinds"][m.kind]
        if sorted(k["when"]) != sorted([(0, LOC_MSGID[0], 24, m.id), (0, LOC_LEN[0], 8, m.length)]):
            raise GenError("%s: when lines do not match id and length" % m.kind)
    used = {f[0].split(".", 1)[1] for k in [pack["common"]] + list(pack["kinds"].values())
            for f in k["fields"] if f[0].startswith(MODULE + ".")}
    if used != set(modules[MODULE]["keys"]):
        raise GenError("module keys and mapped keys differ")
    checked = check_vectors(pack, vec_dir)
    if checked != n_vec:
        raise GenError("vector count mismatch")

    per_file = collections.Counter(m.file for m in msgs)
    allf = [f for m in msgs for f in m.wire]
    stats = {
        "per_file": per_file, "fields": len(allf),
        "scalar": sum(f.status == "scalar" for f in allf),
        "ascii": sum(f.status == "ascii" for f in allf),
        "elements": sum(f.status == "elements" for f in allf),
        "element_lines": sum(len(f.lines) for f in allf if f.status == "elements"),
        "core": sum(f.status == "core" for f in allf),
        "unmapped": sum(f.status == "unmapped" for f in allf),
        "field_lines": 3 + sum(len(f.lines) for f in allf),
    }
    stats["mapped"] = stats["fields"] - stats["unmapped"]
    with open(os.path.join(pack_dir, "pack.md"), "w", encoding="utf-8") as fh:
        fh.write(emit_pack_md(msgs, keys, qualified, stats, sha))

    unm = collections.Counter(f.base for f in allf if f.status == "unmapped")
    print("commit            %s" % sha)
    print("messages          %d %s" % (len(msgs), dict(per_file)))
    print("kinds             %d" % len(pack["kinds"]))
    print("payload fields    %d  mapped %d (scalar %d, ascii %d, element arrays %d = %d lines, core %d)"
          % (stats["fields"], stats["mapped"], stats["scalar"], stats["ascii"], stats["elements"],
             stats["element_lines"], stats["core"]))
    print("not mapped        %d arrays > %d elements, by element type %s"
          % (stats["unmapped"], MAX_ARRAY_ELEMENTS, dict(unm)))
    print("field lines       %d" % stats["field_lines"])
    print("module keys       %d" % len(modules[MODULE]["keys"]))
    print("message-qualified %d fields %s" % (len(qualified), dict(collections.Counter(qualified.values()))))
    print("kinds short of LEN %d; kinds whose requires another kind also satisfies %d"
          % (sum(m.mapped_len < m.length for m in msgs), sum(bool(m.shadowed_by) for m in msgs)))
    print("vectors           %d written, %d checked" % (n_vec, checked))
    print("self-check        ok")


if __name__ == "__main__":
    try:
        main()
    except GenError as e:
        sys.stderr.write("mavlink2pack: FAILED: %s\n" % e)
        sys.exit(1)
