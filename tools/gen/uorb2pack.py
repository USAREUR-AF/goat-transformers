#!/usr/bin/env python3
"""uorb2pack: PX4 uORB topics, in the ULog binary form, as goat-transformers packs.

Reads   <px4>/msg/*.msg and <px4>/msg/versioned/*.msg   the uORB message definitions
        <px4>/LICENSE, <px4>/docs/en/dev_log/ulog_file_format.md,
        <px4>/Tools/msg/px_generate_uorb_topic_helper.py, <px4>/Tools/msg/templates/uorb/msg.json.em
        tools/gen/sources/px4-ulog-PROVENANCE.md   (tag, commit and SHA-256 of every file;
                                                    written with --commit, checked otherwise)
Writes  <out>/model/px4ulog.def                     raw keys of every topic
        <out>/packs/px4-ulog-<topic>/pack.def        one `bits` pack per uORB topic
        <out>/packs/px4-ulog-<topic>/pack.md
        <out>/packs/px4-ulog-<topic>/PROVENANCE.md
        <out>/packs/px4-ulog-<topic>/vectors/gen-*.json
        <out>/packs/geojson/vectors/gen-geojson-to-px4-ulog-*.json
        <out>/tools/gen/names/px4-ulog.json         the key name of every path, kept from run to run

The message of a pack is the `data` of a ULog 'D' (logged data) message: the bytes
after its two-byte `msg_id`. A log binds a `msg_id` to a topic with an 'A'
(subscription) message, so the id means something only inside one log, and the
data carries nothing that names its topic. Each topic is therefore a format of
its own, and the caller names it.

The layout of the data is the layout of the C struct that PX4's uORB generator
writes for the message. In this project's words:

  1. Take the fields in the order of the .msg file (constants are not fields).
  2. Order them by the size of one element, largest first: 8-byte types, then 4,
     2 and 1 byte types, then fields of another message type. Fields of the same
     element size keep their order from the file. An array sorts by the size of
     its element, not of the whole array.
  3. Lay them out one after another with no gaps, except that before a field of
     another message type the offset is raised to a multiple of 8 with padding
     bytes, and after the last field the size is raised to a multiple of 8.
  4. A field of another message type takes the size of that type laid out by the
     same rules, its closing padding included; an array of it takes that size times
     the element count. Its fields are laid out inside it as rule 3 says.
  5. In the data of a 'D' message the padding after the last field is not written
     (the ULog format allows a writer to leave it out); a padding field before a
     field of another type, or at the end of a nested type, is written.

Multi-byte values are little-endian. `bool` and `char` are one byte. A message
whose first field in the file is `uint64 timestamp` has it at offset 0.

Python 3 standard library only. Re-runnable: the same inputs give the same bytes.
Each round-trip vector is written by a serializer in this file that works from
the layout above. After writing, the script loads the module and every pack
through gtcheck and decodes and re-encodes every vector with a small fixed-layout
`bits` codec written from spec/engine-spec.md (0.2, 0.5, 0.6, 0.7). With
--compare-formats it also compares the layout with the field lists that PX4's own
generator writes (the 'F' format strings of a ULog file). Exit status is non-zero
when a check fails.

Usage: uorb2pack.py --px4 DIR --out DIR [--check] [--commit SHA --tag TAG]
                    [--compare-formats DIR]
"""
import argparse
import base64
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
MODULE = "px4ulog"
REPO = "https://github.com/PX4/PX4-Autopilot"
PROV_NAME = "px4-ulog-PROVENANCE.md"
PROV_REL = "tools/gen/sources/" + PROV_NAME
NAMES_REL = "tools/gen/names/px4-ulog.json"
MAX_UNROLL = 64             # a numeric array of more elements is a group, not one key per element
DOC = "docs/en/dev_log/ulog_file_format.md"
HELPERS = ["Tools/msg/px_generate_uorb_topic_helper.py", "Tools/msg/templates/uorb/msg.json.em"]

BUILTIN = {          # .msg type -> (bytes, transform, key type)
    "int8": (1, "twos", "int"), "int16": (2, "twos", "int"), "int32": (4, "twos", "int"),
    "int64": (8, "twos", "int"), "uint8": (1, "uint", "int"), "uint16": (2, "uint", "int"),
    "uint32": (4, "uint", "int"), "uint64": (8, "uint", "int"), "float32": (4, "f32", "float"),
    "float64": (8, "f64", "float"), "bool": (1, "uint", "int"), "char": (1, "ascii", "string"),
}
# Fields bound to core keys: (message, field) -> (key, evidence in this project's words).
# Only latitude and longitude, where the .msg states WGS 84 and degrees.
CORE = {
    ("VehicleGlobalPosition", "lat"): ("lat", "file header: fused global position in WGS84; field: latitude in degrees, float64"),
    ("VehicleGlobalPosition", "lon"): ("lon", "as lat; longitude in degrees"),
    ("SensorGps", "latitude_deg"): ("lat", "file header: GPS position in WGS84 coordinates; field: latitude in degrees, float64"),
    ("SensorGps", "longitude_deg"): ("lon", "as latitude_deg; longitude in degrees"),
    ("HomePosition", "lat"): ("lat", "file header: GPS home position in WGS84 coordinates; field: latitude in degrees, float64"),
    ("HomePosition", "lon"): ("lon", "as lat; longitude in degrees"),
    ("CameraCapture", "lat"): ("lat", "field: latitude in degrees (WGS84), float64; the position where the image was taken"),
    ("CameraCapture", "lon"): ("lon", "field: longitude in degrees (WGS84), float64"),
}
CORE_TYPES = {"lat": "float", "lon": "float"}
# Every pack whose message binds lat and lon gets a vector to geojson; these get one from it.
FROM_GEOJSON = ["vehicle_global_position", "sensor_gps"]


class GenError(Exception):
    pass


def fail(msg):
    raise GenError(msg)


def snake(name):
    """PascalCase to snake_case as PX4's generator turns a file name into a topic name."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# --------------------------------------------------------------------------
# .msg parser
# --------------------------------------------------------------------------

class Field:
    def __init__(self, typ, name, count, line):
        self.type = typ            # builtin name or message name
        self.name = name
        self.count = count         # None for a scalar, else the fixed array length
        self.line = line

    @property
    def builtin(self):
        return self.type in BUILTIN


class Msg:
    def __init__(self, name, rel):
        self.name = name           # PascalCase, the file name
        self.rel = rel             # path under the PX4 checkout
        self.fields = []
        self.constants = []
        self.topics = []


LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_/]*)(?:\[(\d+)\])?\s+([A-Za-z_][A-Za-z0-9_]*)\s*(=\s*(.+))?$")


def parse_msg(path, rel):
    name = os.path.basename(path)[:-4]
    m = Msg(name, rel)
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("# TOPICS"):
                for t in stripped[len("# TOPICS"):].split():
                    m.topics.append(snake(t))
                continue
            code = stripped.split("#", 1)[0].strip()
            if not code:
                continue
            g = LINE_RE.match(code)
            if not g:
                fail("%s:%d: cannot read %r" % (rel, n, code))
            typ, count, fname, eq, value = g.groups()
            if eq:
                m.constants.append((typ, fname, value.strip()))
                continue
            if "/" in typ:
                typ = typ.split("/")[-1]
            m.fields.append(Field(typ, fname, int(count) if count else None, n))
    if not m.topics:
        m.topics = [snake(name)]
    return m


def load_catalog(px4):
    msgs = collections.OrderedDict()
    for sub in ("msg", "msg/versioned"):
        d = os.path.join(px4, *sub.split("/"))
        for f in sorted(os.listdir(d)):
            if f.endswith(".msg"):
                m = parse_msg(os.path.join(d, f), sub + "/" + f)
                if m.name in msgs:
                    fail("message %s defined twice" % m.name)
                msgs[m.name] = m
    for m in msgs.values():
        for f in m.fields:
            if not f.builtin and f.type not in msgs:
                fail("%s: field %s has unknown type %s" % (m.rel, f.name, f.type))
    return msgs


# --------------------------------------------------------------------------
# Layout (the rules in the docstring)
# --------------------------------------------------------------------------

class Slot:
    """One entry of a laid-out struct: a field or a padding run, at a byte offset."""

    def __init__(self, field, offset, size, padding=0):
        self.field = field          # None for padding
        self.offset = offset
        self.size = size            # bytes of the whole entry
        self.padding = padding      # bytes, for a padding entry


class Layout:
    def __init__(self, slots, size, end_padding):
        self.slots = slots          # in order, padding included
        self.size = size            # with the closing padding
        self.end_padding = end_padding

    @property
    def logged_size(self):
        return self.size - self.end_padding


def element_size(f):
    return BUILTIN[f.type][0] if f.builtin else 0


def layout(msgs, name, cache=None):
    cache = {} if cache is None else cache
    if name in cache:
        return cache[name]
    msg = msgs[name]
    ordered = sorted(msg.fields, key=lambda f: -element_size(f))      # sorted() is stable
    slots, offset = [], 0
    for f in ordered:
        if f.builtin:
            one = BUILTIN[f.type][0]
        else:
            pad = (-offset) % 8
            if pad:
                slots.append(Slot(None, offset, pad, pad))
                offset += pad
            one = layout(msgs, f.type, cache).size
        size = one * (f.count or 1)
        slots.append(Slot(f, offset, size))
        offset += size
    end = (-offset) % 8
    if end:
        slots.append(Slot(None, offset, end, end))
    cache[name] = Layout(slots, offset + end, end)
    return cache[name]


def format_string(msgs, name):
    """The field list PX4's generator writes for a message (the 'F' format of ULog):
    `<type>[n] <name>;` per entry, padding as `uint8[n] _padding<i>`."""
    out, i = [], 0
    for s in layout(msgs, name).slots:
        if s.field is None:
            out.append("uint8[%d] _padding%d" % (s.padding, i))
            i += 1
        else:
            t = s.field.type if s.field.builtin else snake(s.field.type)
            out.append("%s%s %s" % (t, "[%d]" % s.field.count if s.field.count else "", s.field.name))
    return out


PX4_CODES = {0x82: "int8", 0x83: "int16", 0x84: "int32", 0x85: "int64", 0x86: "uint8",
             0x87: "uint16", 0x88: "uint32", 0x89: "uint64", 0x8a: "float32", 0x8b: "float64",
             0x8c: "bool", 0x8d: "char"}


def compare_formats(msgs, json_dir):
    """Compare the layout with the `fields` strings of PX4's generator (its `--json`
    output, one file per message). Returns the number compared; fails on a difference."""
    n = 0
    for name in msgs:
        path = os.path.join(json_dir, snake(name) + ".json")
        if not os.path.isfile(path):
            fail("--compare-formats: %s is missing" % path)
        with open(path, encoding="utf-8") as fh:
            fields = json.load(fh)["fields"]
        theirs = []
        for entry in fields.split(";"):
            if not entry:
                continue
            code = ord(entry[0])
            entry = (PX4_CODES[code] + entry[1:]) if code in PX4_CODES else entry
            theirs.append(entry)
        mine = format_string(msgs, name)
        if mine != theirs:
            fail("--compare-formats: %s differs:\n mine   %s\n theirs %s" % (name, mine, theirs))
        n += 1
    return n


# --------------------------------------------------------------------------
# Leaves: the mapped places of one topic
# --------------------------------------------------------------------------

class Leaf:
    def __init__(self, key, bit, length, transform, keytype, desc, pathid, rostype):
        self.key, self.bit, self.length, self.transform = key, bit, length, transform
        self.keytype, self.desc, self.pathid, self.rostype = keytype, desc, pathid, rostype


class Group:
    def __init__(self, key, bit, item_bits, count, body, desc, pathid):
        self.key, self.bit, self.item_bits, self.count = key, bit, item_bits, count
        self.body, self.desc, self.pathid = body, desc, pathid


class Namer:
    def __init__(self, names):
        self.names = names              # path id -> key, from the names file
        self.taken = {v: k for k, v in names.items()}
        self.used = set()

    def name(self, pathid, proposal):
        if pathid in self.names:
            k = self.names[pathid]
        else:
            k, i = proposal, 2
            while k in self.taken and self.taken[k] != pathid:
                k = "%s_%d" % (proposal, i)
                i += 1
            self.names[pathid] = k
            self.taken[k] = pathid
        self.used.add(pathid)
        return k


def leaves(msgs, top, name, base_bit, kpath, ppath, desc, namer, inside_group=False):
    """The mapped places of message `name` laid out at bit `base_bit`; key names from
    the top-level message and the field path."""
    out = []
    for s in layout(msgs, name).slots:
        f = s.field
        if f is None:
            continue
        bit = base_bit + s.offset * 8
        k2 = kpath + [f.name]
        p2 = ppath + ("." if ppath else "") + f.name
        d2 = desc + "." + f.name
        rostype = f.type + ("[%d]" % f.count if f.count else "")
        if f.builtin and f.type == "char":
            if f.count is None:
                out.append(scalar(top, f, bit, 8, "uint", "int", k2, p2, d2, rostype, namer))
            else:
                if f.count > 255:
                    fail("%s.%s: char array longer than 255" % (name, f.name))
                out.append(scalar(top, f, bit, f.count * 8, "ascii", "string", k2, p2, d2, rostype, namer))
            continue
        if f.builtin:
            nbytes, tr, kt = BUILTIN[f.type]
            if f.count is None:
                out.append(scalar(top, f, bit, nbytes * 8, tr, kt, k2, p2, d2, rostype, namer))
            elif f.count <= MAX_UNROLL:
                for i in range(f.count):
                    out.append(scalar(top, f, bit + i * nbytes * 8, nbytes * 8, tr, kt, k2 + [str(i)],
                                      "%s[%d]" % (p2, i), "%s[%d]" % (d2, i), f.type, namer))
            else:
                key = namer.name("%s:%s[]" % (top, p2), "_".join([snake(top)] + k2))
                ikey = namer.name("%s:%s[]." % (top, p2), "_".join([snake(top)] + k2 + ["value"]))
                body = [Leaf(ikey, 0, nbytes * 8, tr, kt, "%s[] item (%s)" % (d2, f.type), p2 + "[].", f.type)]
                out.append(Group(key, bit, nbytes * 8, f.count, body, "%s (%s)" % (d2, rostype), p2 + "[]"))
            continue
        sub = layout(msgs, f.type)
        if f.count is None:
            out.extend(leaves(msgs, top, f.type, bit, k2, p2, d2, namer, inside_group))
        elif f.count <= MAX_UNROLL:
            for i in range(f.count):
                out.extend(leaves(msgs, top, f.type, bit + i * sub.size * 8, k2 + [str(i)],
                                  "%s[%d]" % (p2, i), "%s[%d]" % (d2, i), namer, inside_group))
        else:
            fail("%s.%s: array of %d messages, more than %d" % (name, f.name, f.count, MAX_UNROLL))
    return out


def scalar(top, f, bit, length, tr, kt, kpath, pathid, desc, rostype, namer):
    bound = CORE.get((top, pathid))
    if bound:
        return Leaf(bound[0], bit, length, tr, kt, desc, pathid, rostype)
    key = namer.name("%s:%s" % (top, pathid), "_".join([snake(top)] + kpath))
    return Leaf(key, bit, length, tr, kt, "%s (%s)" % (desc, rostype), pathid, rostype)


def iter_leaves(items):
    for x in items:
        if isinstance(x, Group):
            for y in x.body:
                yield y
        else:
            yield x


def qual(key):
    return key if key in CORE_TYPES else "%s.%s" % (MODULE, key)


# --------------------------------------------------------------------------
# Serializer for vectors: works from the layout, not from pack.def
# --------------------------------------------------------------------------

class Sampler:
    def __init__(self):
        self.n = 0

    def value(self, typ):
        self.n += 1
        n = self.n
        if typ == "bool":
            return n % 2
        if typ == "char":
            return 0x41 + n % 26
        if typ == "float32":
            return (n % 61 - 30.5) * 0.25
        if typ == "float64":
            return float("%s%d.%03d" % ("-" if n % 3 == 0 else "", n, n * 7 % 1000))
        size = BUILTIN[typ][0] * 8
        if typ.startswith("uint"):
            return (n * 2654435761 + 12345) % (1 << size) if size < 64 else n * 1000003 + 1700000000000000
        span = 1 << size
        v = (n * 40503 + 7) % span - span // 2
        return v if size < 64 else -(n * 1000003)

    def text(self, count):
        self.n += 1
        t = ("t%d" % self.n)[:count]
        return t.encode("ascii") + b"\0" * (count - len(t))


def pack_scalar(typ, v):
    fmt = {"int8": "<b", "int16": "<h", "int32": "<i", "int64": "<q", "uint8": "<B",
           "uint16": "<H", "uint32": "<I", "uint64": "<Q", "float32": "<f", "float64": "<d",
           "bool": "<B", "char": "<B"}[typ]
    return struct.pack(fmt, v)


def serialize(msgs, name, buf, base, sampler, values, path, top):
    """Write sample values of message `name` into `buf` at byte `base`; record the
    value of each field path in `values`."""
    for s in layout(msgs, name).slots:
        f = s.field
        if f is None:
            continue
        at = base + s.offset
        p = path + ("." if path else "") + f.name
        if f.builtin and f.type == "char" and f.count:
            b = sampler.text(f.count)
            buf[at:at + f.count] = b
            values[p] = b.rstrip(b"\0").decode("ascii")
        elif f.builtin:
            size = BUILTIN[f.type][0]
            for i in range(f.count or 1):
                v = sampler.value(f.type)
                buf[at + i * size:at + (i + 1) * size] = pack_scalar(f.type, v)
                values[p if f.count is None else "%s[%d]" % (p, i)] = v
        else:
            sub = layout(msgs, f.type)
            for i in range(f.count or 1):
                serialize(msgs, f.type, buf, at + i * sub.size, sampler,
                          values, p if f.count is None else "%s[%d]" % (p, i), top)


# --------------------------------------------------------------------------
# Independent check: a fixed-layout `bits` codec from spec/engine-spec.md
# (0.2 fixed layout; 0.5 lsb order, fields past their word, f32, f64, ascii;
#  0.6 const; 0.7 groups with a fixed count). It reads pack.def text.
# --------------------------------------------------------------------------

class Fail(Exception):
    def __init__(self, kind, detail=""):
        Exception.__init__(self, "%s: %s" % (kind, detail))
        self.kind = kind


def tok(line):
    return gtcheck.tokenize(line)


def read_pack(text):
    """field, const and group lines of a fixed-layout bits pack, in order."""
    root, stack = [], []
    cur = root
    for line in text.split("\n"):
        t = tok(line)
        if not t:
            continue
        d = t[0]
        if d == "field":
            w, p, n = (int(x) for x in t[2].split(":"))
            cur.append(("field", t[1], w * 8 + p, n, t[3]))
        elif d == "const":
            w, p, n = (int(x) for x in t[1].split(":"))
            cur.append(("const", w * 8 + p, n, int(t[2])))
        elif d == "group":
            w, p = (int(x) for x in t[2].split(":"))
            item = int(t[t.index("item") + 1])
            count = int(t[t.index("count") + 1])
            body = []
            cur.append(("group", t[1], w * 8 + p, item, count, body))
            stack.append(cur)
            cur = body
        elif d == "end":
            cur = stack.pop()
    return root


def extent(lines, base=0):
    end = 0
    for ln in lines:
        if ln[0] == "field":
            end = max(end, base + ln[2] + ln[3])
        elif ln[0] == "const":
            end = max(end, base + ln[1] + ln[2])
        else:
            end = max(end, base + ln[2] + ln[3] * ln[4])
    return end


def get_bits(data, pos, length):
    return (int.from_bytes(data, "little") >> pos) & ((1 << length) - 1)


def decode_value(raw, length, tr):
    if tr == "uint":
        return raw
    if tr == "twos":
        return raw - (1 << length) if raw >> (length - 1) else raw
    if tr == "f32":
        v = struct.unpack("<f", raw.to_bytes(4, "little"))[0]
    elif tr == "f64":
        v = struct.unpack("<d", raw.to_bytes(8, "little"))[0]
    elif tr == "ascii":
        b = raw.to_bytes(length // 8, "little").rstrip(b"\0")
        if any(c < 0x20 or c > 0x7e for c in b):
            raise Fail("transform-decode", "ascii")
        return b.decode("ascii")
    else:
        fail("transform %s not in this codec" % tr)
    if math.isnan(v) or math.isinf(v):
        raise Fail("transform-decode", "not finite")
    return v


def decode(lines, data, base=0):
    ent = {}
    for ln in lines:
        if ln[0] == "field":
            ent[ln[1]] = decode_value(get_bits(data, base + ln[2], ln[3]), ln[3], ln[4])
        elif ln[0] == "group":
            ent[ln[1]] = [decode(ln[5], data, base + ln[2] + i * ln[3]) for i in range(ln[4])]
    return ent


def encode_value(v, length, tr):
    if tr in ("uint", "twos"):
        return int(v) & ((1 << length) - 1)
    if tr == "f32":
        return int.from_bytes(struct.pack("<f", v), "little")
    if tr == "f64":
        return int.from_bytes(struct.pack("<d", v), "little")
    if tr == "ascii":
        b = v.encode("ascii")
        if len(b) > length // 8:
            raise Fail("transform-encode", "ascii too long")
        return int.from_bytes(b + b"\0" * (length // 8 - len(b)), "little")
    fail("transform %s not in this codec" % tr)


def encode(lines, ent, base=0, acc=0):
    for ln in lines:
        if ln[0] == "field" and ln[1] in ent:
            mask = ((1 << ln[3]) - 1) << (base + ln[2])
            acc = (acc & ~mask) | (encode_value(ent[ln[1]], ln[3], ln[4]) << (base + ln[2]))
        elif ln[0] == "group":
            items = ent.get(ln[1])
            if items is None:
                raise Fail("transform-encode", "absent list under a fixed count")
            if len(items) != ln[4]:
                raise Fail("transform-encode", "count")
            for i, it in enumerate(items):
                acc = encode(ln[5], it, base + ln[2] + i * ln[3], acc)
    for ln in lines:
        if ln[0] == "const":
            mask = ((1 << ln[2]) - 1) << (base + ln[1])
            acc = (acc & ~mask) | (ln[3] << (base + ln[1]))
    return acc


def convert_bits(lines, hexin):
    data = bytes.fromhex(hexin)
    nbytes = (extent(lines) + 7) // 8
    if len(data) < nbytes:
        raise Fail("malformed-wire", "short input")
    ent = decode(lines, data)
    return encode(lines, ent).to_bytes(nbytes, "little").hex(), ent


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
            g = json.loads(vec["input"])
            c = (g.get("geometry") or {}).get("coordinates") or []
            ent = {"lat": float(c[1]), "lon": float(c[0])} if len(c) >= 2 else {}
            lines = lines_of[dst]
            out = encode(lines, ent).to_bytes((extent(lines) + 7) // 8, "little").hex()
        else:
            out, ent = convert_bits(lines_of[src], vec["input"])
            if dst == "geojson":
                out = geojson_point(ent["lat"], ent["lon"]) if "lat" in ent and "lon" in ent else None
        for k, want in vec.get("model", {}).items():
            got = ent.get(k)
            if isinstance(got, float):
                ok = abs(got - float(want)) <= 1e-9
            else:
                ok = str(got) == want
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
# Emit
# --------------------------------------------------------------------------

def pack_name(topic):
    return "px4-ulog-" + topic.replace("_", "-")


def emit_lines(items, indent=""):
    out = []
    for x in items:
        if isinstance(x, Group):
            out.append("%sgroup  %s  0:%d  item %d  count %d" % (indent, qual(x.key), x.bit, x.item_bits, x.count))
            out.extend(emit_lines(x.body, indent + "  "))
            out.append("%send" % indent)
        else:
            out.append("%sfield  %s  0:%d:%d  %s" % (indent, qual(x.key), x.bit, x.length, x.transform))
    return out


def sources_lines(tag, commit):
    return ['"PX4 uORB message definitions, %s msg/ and msg/versioned/ at tag %s, commit %s; field names, types and array lengths; BSD 3-Clause License"' % (REPO, tag, commit),
            '"PX4 ULog file format, %s %s at tag %s (CC BY 4.0); the data of a D message and the treatment of padding fields"' % (REPO, DOC, tag),
            '"PX4 uORB generator, %s Tools/msg/px_generate_uorb_topic_helper.py and templates/uorb/msg.json.em at tag %s (BSD); the field order and padding rule, restated in tools/gen/uorb2pack.py"' % (REPO, tag)]


def emit_pack(topic, msg, items, lay, const_bit, tag, commit):
    a = ["# PX4 uORB topic %s (message %s) as the data of a ULog D message." % (topic, msg.name),
         "# Generated by tools/gen/uorb2pack.py; do not edit by hand.",
         "# The data after the msg_id of a 'D' message; layout of PX4's uORB struct, little-endian.",
         "format        %s" % pack_name(topic),
         "version       %s" % VERSION,
         "distribution  public"]
    a += ["source        %s" % s for s in sources_lines(tag, commit)]
    a += ["uses          %s" % MODULE, "wire          bits", "bit_order     lsb", "word_bytes    1"]
    a += emit_lines(items)
    if const_bit is not None:
        a.append("const  0:%d:8  0      # last padding byte of a nested type: the data is %d bytes"
                 % (const_bit, lay.logged_size))
    return "\n".join(a) + "\n"


def emit_module(decls, tag, commit):
    a = ["# The px4ulog module: raw keys of the px4-ulog-<topic> formats, one per field of a",
         "# PX4 uORB message (nested messages flattened, short arrays one key per element).",
         "# Generated by tools/gen/uorb2pack.py; edit the generator, not this file.",
         "module        %s" % MODULE, "version       %s" % VERSION, "distribution  public"]
    a += ["source        %s" % s for s in sources_lines(tag, commit)[:1]]
    w = max(len(d[1]) for d in decls)
    for kind_, name, typ, desc in decls:
        if kind_ == "list":
            a.append('list %-*s          "%s"' % (w, name, desc))
        else:
            a.append('key  %-*s  %-6s  -  "%s"' % (w, name, typ, desc))
    return "\n".join(a) + "\n"


def emit_pack_md(topic, msg, items, lay, deps, n_vec, cross_to, cross_from, msgs):
    fmt = pack_name(topic)
    others = [t for t in msg.topics if t != topic]
    a = ["# %s" % fmt, "",
         "PX4 uORB topic `%s`, message `%s`, as the data of a ULog 'D' (logged data) message." % (topic, msg.name),
         "Generated by `tools/gen/uorb2pack.py` (run by `tools/gen/uorb2pack-run.sh`); do not",
         "edit by hand.", "",
         "## Message convention", "",
         "A message of this format is the `data` of one ULog 'D' message: the bytes after",
         "its two-byte `msg_id`, %d bytes. ULog gives a topic its `msg_id` in an 'A'" % lay.logged_size,
         "(subscription) message of the same log, so the id has no meaning outside that log",
         "and the data holds nothing that names the topic. There is no value on the wire a",
         "`when` line could select by, so each topic is a format of its own and the caller",
         "names it. Other topics with this layout: %s." % (", ".join("`%s`" % t for t in others) if others else "none"), "",
         "The data is the C struct PX4's uORB generator writes for the message: fields",
         "ordered by element size (8, 4, 2, 1 bytes, then nested messages; ties keep the",
         "order of the .msg file), a nested message starting at a multiple of 8 bytes,",
         "every nested message padded to a multiple of 8, little-endian, no gap",
         "otherwise. The padding after the last field is not part of the data (the ULog",
         "format lets a writer leave it out); input that has it is accepted and the",
         "encoder does not write it. `tools/gen/uorb2pack.py` states the rule in full.", "",
         "This is a different format from `ros2-px4-msgs`, which is the rosbridge JSON of",
         "the ROS 2 copy of the same messages.", "",
         "## Layout", "",
         "| Offset (bytes) | Bits | .msg field | Type | Line |",
         "|---|---|---|---|---|"]
    for x in items:
        if isinstance(x, Group):
            a.append("| %d | %d x %d | `%s` | group, %d items | `%s` |" % (
                x.bit // 8, x.count, x.item_bits, x.desc.split(" ")[0], x.count, qual(x.key)))
        else:
            a.append("| %d | %d | `%s` | %s | `%s` %s |" % (
                x.bit // 8, x.length, x.desc.split(" (")[0].split(".", 1)[1], x.rostype, qual(x.key), x.transform))
    a += ["", "Padding bytes are not in the table: no line maps them. A numeric array of up",
          "to %d elements is one key per element (`_0`, `_1`, ...); a longer one is a `group`" % MAX_UNROLL,
          "with a fixed count. A `char` array is `ascii` text.", "",
          "## Shared-model keys", ""]
    bound = [x for x in iter_leaves(items) if x.key in CORE_TYPES]
    if bound:
        a += ["| Field | Key | Evidence in the .msg file |", "|---|---|---|"]
        for x in bound:
            a.append("| `%s` | `%s` | %s |" % (x.pathid, x.key, CORE[(msg.name, x.pathid)][1]))
        a += ["", "Altitude, velocity and time are not bound: this pack binds latitude and",
              "longitude only, and `timestamp` is microseconds since the system started, not UTC."]
    else:
        a += ["None. No field of this message is stated as a WGS 84 latitude or longitude in",
              "degrees. `timestamp` is microseconds since the system started, not UTC, so it is",
              "not `time_ms`. Every field is a raw key of module `%s`." % MODULE]
    a += ["", "## Not mapped, and why", "", "| What | Why |", "|---|---|",
          "| Padding bytes | they carry no value. On encode they are zero, so a round trip of "
          "input whose padding is not zero gives zeros there; the `bits` wire keeps no residue |",
          "| Constants of the .msg (%d) | the pack language names no constant of a field; the "
          "value is carried as a number |" % len(msg.constants),
          "| Bytes of a `char` array after its first NUL | `ascii` removes trailing NULs and "
          "refuses other bytes outside 0x20-0x7E (`transform-decode`), so text followed by "
          "leftover bytes does not decode |",
          "| NaN and infinite floats | the `f32` and `f64` transforms refuse them on decode "
          "(`transform-decode`); PX4 writes NaN for a value it does not know |",
          "| `uint64` values above 2^63-1 | a model `int` is a signed 64-bit integer; such a "
          "value decodes to a negative integer with the same bits and encodes back unchanged "
          "(engine-spec 0.5 ruling 2) |",
          "| The 'A' subscription, `multi_id` and the ULog header | other messages of the log; "
          "this format is the data of one 'D' message |"]
    a += ["", "## Vectors", "",
          "`vectors/gen-rt.json` is a round trip with every field set: values chosen by the",
          "generator, serialized by its own code from the layout, zero padding. `gen-*` files",
          "beside it, where there are any, are edge and error cases and conversions to",
          "geojson; each states its rule in `source`. %d vector file(s)." % n_vec]
    if cross_from:
        a.append("`packs/geojson/vectors/gen-geojson-to-%s.json` converts from geojson." % fmt)
    a += ["", "## Sources", "",
          "The .msg files read for this topic: %s. See `PROVENANCE.md`." % ", ".join("`%s`" % d for d in deps)]
    return "\n".join(a) + "\n"


def emit_provenance(tag, commit, files, date_read):
    a = ["# Provenance", "",
         "Generated by `tools/gen/uorb2pack.py`. No source file is copied into this",
         "repository. The generator reads field names, types and array lengths from the",
         ".msg files, and states the layout rule of PX4's uORB generator and the ULog data",
         "message in its own words. Date read: %s." % date_read, "",
         "| Fact | Value |", "|---|---|",
         "| Repository | %s |" % REPO, "| Tag | `%s` |" % tag, "| Commit | `%s` |" % commit, "",
         "Each file is `https://raw.githubusercontent.com/PX4/PX4-Autopilot/<commit>/<path>`.", "",
         "| Path | SHA-256 |", "|---|---|"]
    for rel, sha in files:
        a.append("| `%s` | `%s` |" % (rel, sha))
    a += ["", "## Licenses, as the sources state them", "",
          "- `LICENSE` at the root begins \"BSD 3-Clause License\" and \"Copyright (c) 2012 - 2023,",
          "  PX4 Development Team\", followed by the three-clause BSD text. The .msg files and",
          "  `Tools/msg/` carry no other licence; `px_generate_uorb_topic_helper.py` carries the",
          "  BSD header \"Copyright (C) 2013-2022 PX4 Pro Development Team\".",
          "- `docs/LICENSE` states \"CC BY 4.0\" for the documentation, which includes",
          "  `%s`. Nothing of its text is copied; the pack states the layout" % DOC,
          "  in its own words.", "",
          "No source carries a distribution statement, handling marking, export-control",
          "notice or proprietary notice."]
    return "\n".join(a) + "\n"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def read_sources_provenance(out):
    """(tag, commit, {path: sha}) from tools/gen/sources/px4-ulog-PROVENANCE.md."""
    text = out.read(PROV_REL)
    tag = re.search(r"^\| Tag \| `([^`]+)` \|$", text, re.M).group(1)
    commit = re.search(r"^\| Commit \| `([0-9a-f]{40})` \|$", text, re.M).group(1)
    shas = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    return tag, commit, shas


def source_files(px4, msgs):
    return ["LICENSE", "docs/LICENSE", DOC] + HELPERS + [m.rel for m in msgs.values()]


def emit_sources_provenance(tag, commit, rels, px4, date_read):
    a = ["# Provenance of the PX4 inputs of tools/gen/uorb2pack.py", "",
         "Written by `uorb2pack.py --commit`; every later run checks the files against it.",
         "Date read: %s." % date_read, "",
         "| Fact | Value |", "|---|---|",
         "| Repository | %s |" % REPO, "| Tag | `%s` |" % tag, "| Commit | `%s` |" % commit, "",
         "| Path | SHA-256 |", "|---|---|"]
    for rel in rels:
        a.append("| `%s` | `%s` |" % (rel, sha256_file(os.path.join(px4, *rel.split("/")))))
    a += ["", "License: `LICENSE` (BSD 3-Clause License, Copyright (c) 2012 - 2023, PX4",
          "Development Team) for the .msg files and `Tools/msg/`; `docs/LICENSE` (CC BY 4.0)",
          "for the ULog format document. See any `packs/px4-ulog-*/PROVENANCE.md`."]
    return "\n".join(a) + "\n"


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


def build(args, out):
    px4 = args.px4
    msgs = load_catalog(px4)
    rels = source_files(px4, msgs)
    if args.commit:
        out.write(PROV_REL, emit_sources_provenance(args.tag, args.commit, rels, px4, args.date_read))
    tag, commit, shas = read_sources_provenance(out)
    for rel in rels:
        got = sha256_file(os.path.join(px4, *rel.split("/")))
        if shas.get(rel) != got:
            fail("%s: SHA-256 %s is not the one in %s" % (rel, got, PROV_REL))
    if set(shas) != set(rels):
        fail("%s lists other files than the run reads: %s" % (PROV_REL, sorted(set(shas) ^ set(rels))))
    if args.compare_formats:
        n = compare_formats(msgs, args.compare_formats)
        print("uorb2pack: layout of %d messages matches PX4's generator" % n)
    for (mname, field), (key, _) in CORE.items():
        if mname not in msgs or not any(f.name == field for f in msgs[mname].fields):
            fail("binding %s.%s: no such field" % (mname, field))
    names = json.loads(out.read(NAMES_REL)) if out.exists(NAMES_REL) else {}
    namer = Namer(names)
    topics = collections.OrderedDict()
    for m in msgs.values():
        for t in m.topics:
            if t in topics:
                fail("topic %s defined by %s and %s" % (t, topics[t].name, m.name))
            topics[t] = m
    # leaves per message (topics of one message share keys and layout)
    per_msg, decls, seen = {}, [], set()
    for m in msgs.values():
        lay = layout(msgs, m.name)
        first = next((s.field for s in lay.slots if s.field is not None), None)
        if first is None or first.name != "timestamp" or first.type != "uint64":
            fail("%s: first field of the layout is not uint64 timestamp" % m.name)
        items = leaves(msgs, m.name, m.name, 0, [], "", m.name, namer)
        per_msg[m.name] = items
        for x in items:
            for y in ([x] + (x.body if isinstance(x, Group) else [])):
                if y.key in CORE_TYPES or y.key in seen:
                    continue
                seen.add(y.key)
                if isinstance(y, Group):
                    decls.append(("list", y.key, None, y.desc))
                else:
                    decls.append(("key", y.key, y.keytype, y.desc))
    module_text = emit_module(decls, tag, commit)
    out.write("model/%s.def" % MODULE, module_text)
    out.write(NAMES_REL, json.dumps(collections.OrderedDict(sorted(namer.names.items())), indent=1) + "\n")
    # packs
    prov_files_of = {}
    lines_of, vectors = {}, []
    wanted_dirs = set()
    for topic, m in topics.items():
        fmt = pack_name(topic)
        lay = layout(msgs, m.name)
        items = per_msg[m.name]
        end_bits = max((x.bit + (x.item_bits * x.count if isinstance(x, Group) else x.length)) for x in items)
        const_bit = None
        if end_bits < lay.logged_size * 8:
            const_bit = lay.logged_size * 8 - 8
        deps = []

        def walk(name):
            if name not in deps:
                deps.append(name)
                for f in msgs[name].fields:
                    if not f.builtin:
                        walk(f.type)
        walk(m.name)
        deps_rel = [msgs[d].rel for d in deps]
        text = emit_pack(topic, m, items, lay, const_bit, tag, commit)
        rel = "packs/%s" % fmt
        wanted_dirs.add(fmt)
        out.write(rel + "/pack.def", text)
        files = [(r, shas[r]) for r in ["LICENSE", "docs/LICENSE", DOC] + HELPERS + deps_rel]
        out.write(rel + "/PROVENANCE.md", emit_provenance(tag, commit, files, args.date_read))
        # vectors
        sampler = Sampler()
        buf = bytearray(lay.size)
        values = {}
        serialize(msgs, m.name, buf, 0, sampler, values, "", m.name)
        hexin = bytes(buf[:lay.logged_size]).hex()
        model = collections.OrderedDict()
        for x in iter_leaves(items):
            if x.pathid in values and len(model) < 4:
                model[qual(x.key)] = model_value(x, values[x.pathid])
        vs = [("gen-rt.json", vec("rt-" + topic, fmt, fmt, hexin, hexin, model,
                                  source="tools/gen/uorb2pack.py: values chosen by the generator, written "
                                         "by its serializer at the offsets of the layout rule; padding zero"))]
        bound = {x.key: x for x in iter_leaves(items) if x.key in CORE_TYPES}
        cross_to = "lat" in bound and "lon" in bound
        if cross_to:
            lat, lon = 47.3977419, 8.5455938
            b2 = bytearray(buf)
            b2[bound["lat"].bit // 8:bound["lat"].bit // 8 + 8] = struct.pack("<d", lat)
            b2[bound["lon"].bit // 8:bound["lon"].bit // 8 + 8] = struct.pack("<d", lon)
            vs.append(("gen-x-to-geojson.json", vec(
                "x-%s-to-geojson" % topic, fmt, "geojson", bytes(b2[:lay.logged_size]).hex(),
                geojson_point(lat, lon), {"lat": fmt_float(lat), "lon": fmt_float(lon)},
                source="the bound fields lat and lon (pack.md) are float64 degrees; geojson writes [lon, lat] "
                       "(RFC 7946, engine-spec 0.1.1 ruling 4); no other key of this format is a geojson key")))
        cross_from = cross_to and topic in FROM_GEOJSON
        if cross_from:
            b3 = bytearray(lay.size)
            b3[bound["lat"].bit // 8:bound["lat"].bit // 8 + 8] = struct.pack("<d", 47.25)
            b3[bound["lon"].bit // 8:bound["lon"].bit // 8 + 8] = struct.pack("<d", 8.5)
            gv = vec("gen-geojson-to-%s" % fmt, "geojson", fmt,
                     '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.5,47.25,410]},'
                     '"properties":{"callsign":"UAV1"},"id":"u-1"}',
                     bytes(b3[:lay.logged_size]).hex(), {"lat": "47.25", "lon": "8.5"},
                     source="tools/gen/uorb2pack.py: only lat and lon have a line; every other byte "
                            "is zero (absent fields write nothing); hae, uid and callsign have no line")
            out.write("packs/geojson/vectors/gen-geojson-to-%s.json" % fmt, dump_json(gv))
            vectors.append(("packs/geojson/vectors/gen-geojson-to-%s.json" % fmt, gv))
        if topic == "vehicle_global_position":
            full = bytes(buf).hex()
            vs.append(("gen-edge-with-closing-padding.json", vec(
                "edge-with-closing-padding", fmt, fmt, full, hexin,
                source="ULog lets a writer include or leave out the padding after the last field; "
                       "input longer than the message is accepted and the extra bytes are ignored "
                       "(engine-spec 0.5), and the encoder writes %d bytes" % lay.logged_size)))
            vs.append(("gen-err-short.json", vec(
                "err-short", fmt, fmt, hexin[:-2], error="malformed-wire",
                source="one byte short of the %d-byte message (vector-format, malformed input)" % lay.logged_size)))
        for name in out.listdir(rel + "/vectors"):
            if name.startswith("gen-") and name not in {n for n, _ in vs}:
                out.remove(rel + "/vectors/" + name)
        for name, v in vs:
            out.write(rel + "/vectors/" + name, dump_json(v))
            vectors.append((rel + "/vectors/" + name, v))
        out.write(rel + "/pack.md", emit_pack_md(topic, m, items, lay, deps_rel, len(vs), cross_to, cross_from, msgs))
        lines_of[fmt] = None
        prov_files_of[fmt] = files
    # packs of an earlier run whose topic is gone
    if os.path.isdir(out.path("packs")):
        for d in sorted(os.listdir(out.path("packs"))):
            if d.startswith("px4-ulog-") and d not in wanted_dirs:
                for sub in ("pack.def", "pack.md", "PROVENANCE.md"):
                    out.remove("packs/%s/%s" % (d, sub))
                for name in out.listdir("packs/%s/vectors" % d):
                    out.remove("packs/%s/vectors/%s" % (d, name))
    # check: load through gtcheck, then run every vector through the codec
    model = gtcheck.Model()
    with open(os.path.join(args.core_def), encoding="utf-8") as fh:
        model.add(fh.read(), "model/core.def")
    model.add(out.read("model/%s.def" % MODULE), "model/%s.def" % MODULE)
    for fmt in lines_of:
        text = out.read("packs/%s/pack.def" % fmt)
        try:
            gtcheck.load_pack(text, model, label="packs/%s/pack.def" % fmt)
        except gtcheck.CheckError as e:
            fail(str(e))
        lines_of[fmt] = read_pack(text)
    for rel, v in vectors:
        check_vector(json.loads(out.read(rel)), lines_of, rel)
    return len(topics), len(msgs), len(decls), len(vectors)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--px4", required=True, metavar="DIR", help="a PX4-Autopilot checkout (msg/, Tools/msg/, docs/)")
    genio.add_arguments(ap)
    ap.add_argument("--commit", help="write tools/gen/sources/%s for this commit (with --tag)" % PROV_NAME)
    ap.add_argument("--tag", help="the release tag of --commit")
    ap.add_argument("--compare-formats", metavar="DIR",
                    help="the --json output of PX4's Tools/msg/px_generate_uorb_topic_files.py; "
                         "every message's layout is compared with it")
    ap.add_argument("--core-def", help="model/core.def (default: <out>/model/core.def)")
    ap.add_argument("--date-read", default="2026-11-19")
    args = ap.parse_args(argv)
    if args.commit and not args.tag:
        ap.error("--commit needs --tag")
    args.core_def = args.core_def or os.path.join(args.out, "model", "core.def")
    out = genio.Output(args.out, check=args.check)
    try:
        nt, nm, nk, nv = build(args, out)
    except GenError as e:
        print("uorb2pack: %s" % e, file=sys.stderr)
        return 1
    print("uorb2pack: %d topics of %d messages, %d keys and lists, %d vectors checked" % (nt, nm, nk, nv))
    return out.report("uorb2pack")


if __name__ == "__main__":
    sys.exit(main())
